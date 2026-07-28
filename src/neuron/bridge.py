"""Neuron HTTP bridge launcher — expose the stdio server over HTTP for ChatGPT & co.

The hard parts of "run the bridge" are (1) launching the *right* Neuron, and
(2) getting `mcp-proxy` without a manual install. This script does both:

  * it launches Neuron with **this interpreter** (``sys.executable -m neuron``),
    so if you run this script with the venv where Neuron is installed, the child
    resolves correctly — no more bare ``python3 -m neuron`` hitting the wrong
    Python (the usual cause of mcp-proxy's "McpError: Connection closed": the
    child died with "No module named neuron");
  * it finds a way to run `mcp-proxy` — preferring ``uvx`` / ``uv`` / ``pipx``,
    which fetch it on demand, so nothing has to be pip-installed by hand;
  * it **preflights** the Neuron command (starts it briefly) and, if it dies,
    shows you the real error instead of a cryptic proxy stack trace.

Usage::

    # run with the SAME python where Neuron is installed (e.g. the install venv)
    python scripts/bridge.py                      # serves http://127.0.0.1:8000/mcp (+ /sse)
    python scripts/bridge.py --port 9000
    python scripts/bridge.py --host 0.0.0.0       # bind all interfaces (for tunnels)
    python scripts/bridge.py --tunnel             # auto-launch tunnel after bridge
    python scripts/bridge.py --print-cmd          # show what it would run, don't run
    python scripts/bridge.py -- <custom neuron launch command>   # override the child

Env vars (override CLI defaults):
    NEURON_BRIDGE_HOST     bind host (default 127.0.0.1)
    NEURON_BRIDGE_PORT     bind port (default 8000)
    NEURON_BRIDGE_TUNNEL   "1" to auto-launch tunnel

Then expose the port over public HTTPS (remote connectors can't reach
localhost) — e.g.  ``cloudflared tunnel --url http://127.0.0.1:8000`` — and add
the resulting ``https://…/mcp`` URL as a connector. Use the ``/mcp`` (Streamable
HTTP) endpoint, NOT ``/sse``: Cloudflare buffers the legacy SSE handshake so the
``/sse`` URL times out behind a tunnel. See docs/BRIDGE.md.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import subprocess
import sys
import time

# Make Unicode output safe on legacy Windows consoles (cp1252): reconfigure
# stdout/stderr to UTF-8 so the glyphs printed below never raise
# UnicodeEncodeError. Best-effort and never fatal.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WIN = os.name == "nt"


def _env_int(key: str, default: int) -> int:
    """Read an int from env, falling back to *default*."""
    v = os.environ.get(key)
    if v is not None:
        try:
            return int(v)
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool = False) -> bool:
    """Read a bool from env ('1'/'true'/'yes' → True)."""
    v = os.environ.get(key, "").lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return default


def _find_free_port(start: int, end: int) -> int | None:
    """Find a free port in [start, end]. Returns None if all occupied."""
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def resolve_neuron_cmd(override: list[str] | None) -> list[str]:
    """Return the command that launches the MCP server over HTTP.

    In full suite (Gray Matter installed), launches ``gray_matter.server`` so
    the remote LLM sees ALL tools: Neuron + NeuRAG + GM orchestration (pulse,
    bridges, flash, cache). In standalone, launches ``neuron`` directly.

    Priority: explicit override → GM detected → the installed venv → this
    interpreter."""
    if override:
        return override

    # Full suite: GM is the orchestrator — launch it so all tools are exposed.
    if importlib.util.find_spec("gray_matter.server") is not None:
        if WIN:
            slug = os.environ.get("GM_SLUG", "gray-matter")
            local = os.environ.get("LOCALAPPDATA", "")
            venv_py = os.path.join(local, "Programs", slug, ".venv", "Scripts", "python.exe")
            if os.path.isfile(venv_py):
                return [venv_py, "-m", "gray_matter.server"]
        return [sys.executable, "-m", "gray_matter.server"]

    # Standalone Neuron
    if WIN:
        slug = os.environ.get("NEURON_SLUG", "neuron")
        local = os.environ.get("LOCALAPPDATA", "")
        venv_py = os.path.join(local, "Programs", slug, ".venv", "Scripts", "python.exe")
        if os.path.isfile(venv_py):
            return [venv_py, "-m", "neuron"]
        bat = os.path.join(local, "Programs", slug, "scripts", "run_mcp.bat")
        if os.path.isfile(bat):
            return ["cmd", "/c", bat]
    if importlib.util.find_spec("neuron") is not None:
        return [sys.executable, "-m", "neuron"]
    return [sys.executable, "-m", "neuron"]


def resolve_proxy_runner() -> list[str] | None:
    """Find a way to run `mcp-proxy`, preferring on-demand runners so nothing
    needs a manual install."""
    if shutil.which("mcp-proxy"):
        return ["mcp-proxy"]
    if shutil.which("uvx"):
        return ["uvx", "mcp-proxy"]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "mcp-proxy"]
    if shutil.which("pipx"):
        return ["pipx", "run", "mcp-proxy"]
    return None


# Need shutil for resolve_proxy_runner
import shutil


def preflight(server_cmd: list[str], seconds: float = 3.0) -> bool:
    """Start the MCP server briefly; if it exits immediately, show why.
    A healthy stdio MCP server stays alive waiting for input."""
    gm = importlib.util.find_spec("gray_matter.server") is not None
    label = "Gray Matter (full suite)" if gm else "Neuron"
    print(f"Preflight: starting {label} → {' '.join(server_cmd)}")
    try:
        proc = subprocess.Popen(
            server_cmd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        print(f"  ✗ cannot launch it: {exc}")
        return False
    time.sleep(seconds)
    if proc.poll() is None:
        proc.kill()
        print(f"  ✓ {label} starts and stays alive.")
        return True
    err = (proc.stderr.read() or b"").decode(errors="replace").strip()
    print(f"  ✗ {label} exited immediately (code {proc.returncode}). Its error:\n")
    print("    " + "\n    ".join((err or "(no stderr)").splitlines()[-15:]))
    print(f"\n  → Fix that first. Most often: run this script with the Python where")
    print(f"    {'Gray Matter' if gm else 'Neuron'} is installed, or pass your launch command after '--'.")
    return False


def _launch_tunnel(host: str, port: int) -> subprocess.Popen | None:
    """Launch `neuron tunnel` as a background process. Returns the Popen or None."""
    neuron_py = resolve_neuron_cmd(None)
    python = neuron_py[0]  # first element is the Python executable
    tunnel_cmd = [python, "-m", "neuron.tunnel", "--port", str(port), "--host", host]
    print(f"\n  Launching tunnel: {' '.join(tunnel_cmd)}")
    try:
        flags = 0x08000000 if WIN else 0
        proc = subprocess.Popen(
            tunnel_cmd, stdout=sys.stdout, stderr=sys.stderr,
            creationflags=flags)
        time.sleep(2)  # give it a moment to print the URL
        return proc
    except FileNotFoundError as exc:
        print(f"  ✗ Could not launch tunnel: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Launch the Neuron→HTTP bridge (mcp-proxy in server mode).")
    parser.add_argument("--port", type=int,
                        default=_env_int("NEURON_BRIDGE_PORT", 8000),
                        help="HTTP port (default 8000, env: NEURON_BRIDGE_PORT).")
    parser.add_argument("--host",
                        default=os.environ.get("NEURON_BRIDGE_HOST", "127.0.0.1"),
                        help="Bind host (default 127.0.0.1, env: NEURON_BRIDGE_HOST). "
                             "Use 0.0.0.0 for tunnel exposure.")
    parser.add_argument("--no-check", action="store_true", help="Skip the Neuron preflight.")
    parser.add_argument("--print-cmd", action="store_true",
                        help="Print the full command and exit (don't run).")
    parser.add_argument("--tunnel", action="store_true",
                        help="Auto-launch tunnel after bridge starts.")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="Disable tunnel even if NEURON_BRIDGE_TUNNEL=1.")
    parser.add_argument("--port-range", type=int, default=10,
                        help="If default port is taken, try this many consecutive ports (default 10).")
    parser.add_argument("neuron_cmd", nargs=argparse.REMAINDER,
                        help="Optional: everything after '--' is the Neuron launch command.")
    args = parser.parse_args(argv)

    # Env overrides
    want_tunnel = args.tunnel or (_env_bool("NEURON_BRIDGE_TUNNEL") and not args.no_tunnel)

    override = args.neuron_cmd
    if override and override[0] == "--":
        override = override[1:]
    neuron_cmd = resolve_neuron_cmd(override or None)

    proxy = resolve_proxy_runner()
    if proxy is None:
        print("No way to run 'mcp-proxy' was found.\n"
              "Install a runner (any one):\n"
              "  • uv (recommended, no pip needed):\n"
              "      Windows : irm https://astral.sh/uv/install.ps1 | iex\n"
              "      macOS/Linux : curl -LsSf https://astral.sh/uv/install.sh | sh\n"
              "  • pipx : python -m pip install --user pipx\n"
              "Then re-run this script.", file=sys.stderr)
        return 2

    # Quick smoke test: can the proxy runner actually launch mcp-proxy?
    try:
        r = subprocess.run(proxy + ["--version"], capture_output=True, timeout=15,
                           creationflags=(subprocess.CREATE_NO_WINDOW
                                          if os.name == "nt" else 0))
        if r.returncode != 0:
            print(f"  [!] '{' '.join(proxy)}' did not return a valid mcp-proxy.",
                  file=sys.stderr)
            print("      It may still work at runtime, but check your network / runner install.",
                  file=sys.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  [!] '{' '.join(proxy)}' — {exc}", file=sys.stderr)

    # Port fallback: find a free port if default is occupied
    port = args.port
    if port_is_occupied(port):
        print(f"  Port {port} is occupied, scanning for a free port...", flush=True)
        free = _find_free_port(port, port + args.port_range - 1)
        if free is None:
            print(f"  ✗ No free port found in range {port}-{port + args.port_range - 1}.",
                  file=sys.stderr)
            return 1
        print(f"  ✓ Using port {free} instead.", flush=True)
        port = free

    full = proxy + [f"--port={port}", f"--host={args.host}", "--"] + neuron_cmd
    url = f"http://{args.host}:{port}/mcp"

    if args.print_cmd:
        print(" ".join(full))
        return 0

    if not args.no_check and not preflight(neuron_cmd):
        return 1

    # TCP keepalive: mcp-proxy doesn't expose keepalive settings directly,
    # but we can set it via the socket after binding. For now, print guidance.
    bind_info = f"{'all interfaces' if args.host == '0.0.0.0' else args.host}:{port}"

    print(f"\nStarting bridge via: {' '.join(proxy)}")
    print(f"  local endpoint : {url}")
    print(f"  bind           : {bind_info}")
    print(f"  server         : {'gray_matter.server (full suite)' if importlib.util.find_spec('gray_matter.server') is not None else 'neuron (standalone)'}")
    if want_tunnel:
        print(f"  tunnel         : will auto-launch after bridge starts")
    else:
        print(f"  next step      : expose it over public HTTPS, e.g.")
        print(f"                   neuron tunnel --port {port}")
        print(f"                   cloudflared tunnel --url http://{args.host}:{port}")
    print(f"  Use /mcp (Streamable HTTP), not /sse — Cloudflare buffers the SSE handshake.\n")
    sys.stdout.flush()

    # Launch bridge
    try:
        # CREATE_NO_WINDOW (T81): under the windowless GUI, a console child
        # (uvx/mcp-proxy) would otherwise open its own CMD window. Stdio
        # handles are inherited regardless, so output still flows when run
        # from a real terminal.
        flags = 0x08000000 if os.name == "nt" else 0

        if want_tunnel:
            # Launch tunnel in background, then bridge in foreground
            tunnel_proc = _launch_tunnel(args.host, port)
            try:
                rc = subprocess.call(full, creationflags=flags)
            except KeyboardInterrupt:
                rc = 0
            finally:
                if tunnel_proc and tunnel_proc.poll() is None:
                    tunnel_proc.terminate()
                    try:
                        tunnel_proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        tunnel_proc.kill()
            return rc
        else:
            return subprocess.call(full, creationflags=flags)

    except KeyboardInterrupt:
        return 0
    except FileNotFoundError as exc:
        print(f"Failed to start the proxy: {exc}", file=sys.stderr)
        return 2


def port_is_occupied(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is already in use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
