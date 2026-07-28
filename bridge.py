"""NeuRAG HTTP bridge launcher — expose the stdio server over HTTP for ChatGPT & co.

Same architecture as neuron.bridge: wraps NeuRAG's stdio MCP server behind
mcp-proxy so remote LLMs (Perplexity, ChatGPT Dev Mode) can reach it over
HTTPS via a tunnel.

Usage::

    # run with the Python where NeuRAG is installed
    python scripts/bridge.py                      # serves http://127.0.0.1:8001/mcp
    python scripts/bridge.py --port 9000
    python scripts/bridge.py --host 0.0.0.0       # bind all interfaces (for tunnels)
    python scripts/bridge.py --tunnel             # auto-launch tunnel after bridge
    python scripts/bridge.py --print-cmd          # show what it would run, don't run
    python scripts/bridge.py -- <custom launch command>   # override the child

Env vars (override CLI defaults):
    NEURAG_BRIDGE_HOST     bind host (default 127.0.0.1)
    NEURAG_BRIDGE_PORT     bind port (default 8001 — one above Neuron's 8000)
    NEURAG_BRIDGE_TUNNEL   "1" to auto-launch tunnel

See docs/BRIDGE.md for the full picture.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import time

# Make Unicode output safe on legacy Windows consoles (cp1252).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WIN = os.name == "nt"


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is not None:
        try:
            return int(v)
        except ValueError:
            pass
    return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key, "").lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    return default


def _find_free_port(start: int, end: int) -> int | None:
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def _port_is_occupied(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def resolve_neurag_cmd(override: list[str] | None) -> list[str]:
    """Return the command that launches the MCP server over HTTP.

    In full suite (Gray Matter installed), launches ``gray_matter.server`` so
    the remote LLM sees ALL tools: Neuron + NeuRAG + GM orchestration. In
    standalone, launches ``neurag.server`` directly.

    Priority: explicit override → GM detected → neurag-mcp on PATH → this
    interpreter."""
    if override:
        return override

    # Full suite: GM is the orchestrator — launch it so all tools are exposed.
    if importlib.util.find_spec("gray_matter.server") is not None:
        if os.name == "nt":
            slug = os.environ.get("GM_SLUG", "gray-matter")
            local = os.environ.get("LOCALAPPDATA", "")
            venv_py = os.path.join(local, "Programs", slug, ".venv", "Scripts", "python.exe")
            if os.path.isfile(venv_py):
                return [venv_py, "-m", "gray_matter.server"]
        return [sys.executable, "-m", "gray_matter.server"]

    # Standalone NeuRAG
    if shutil.which("neurag-mcp"):
        return ["neurag-mcp"]
    if importlib.util.find_spec("neurag.server") is not None:
        return [sys.executable, "-m", "neurag.server"]
    return [sys.executable, "-m", "neurag.server"]


def resolve_proxy_runner() -> list[str] | None:
    """Find a way to run mcp-proxy."""
    if shutil.which("mcp-proxy"):
        return ["mcp-proxy"]
    if shutil.which("uvx"):
        return ["uvx", "mcp-proxy"]
    if shutil.which("uv"):
        return ["uv", "tool", "run", "mcp-proxy"]
    if shutil.which("pipx"):
        return ["pipx", "run", "mcp-proxy"]
    return None


def preflight(server_cmd: list[str], seconds: float = 3.0) -> bool:
    """Start the MCP server briefly; if it exits immediately, show why."""
    gm = importlib.util.find_spec("gray_matter.server") is not None
    label = "Gray Matter (full suite)" if gm else "NeuRAG"
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
    print(f"\n  → Fix that first. Run this script with the Python where {'Gray Matter' if gm else 'NeuRAG'} is installed.")
    return False


def _launch_tunnel(host: str, port: int) -> subprocess.Popen | None:
    """Launch neuron tunnel as a background process."""
    # Try to use neuron's tunnel module
    if importlib.util.find_spec("neuron.tunnel") is not None:
        python = sys.executable
        tunnel_cmd = [python, "-m", "neuron.tunnel", "--port", str(port), "--host", host]
    else:
        # Fallback: use cloudflared directly
        cf = shutil.which("cloudflared")
        if not cf:
            print("  ✗ Neither neuron.tunnel nor cloudflared found for auto-tunnel.",
                  file=sys.stderr)
            return None
        tunnel_cmd = [cf, "tunnel", "--url", f"http://{host}:{port}"]

    print(f"\n  Launching tunnel: {' '.join(tunnel_cmd)}")
    try:
        flags = 0x08000000 if WIN else 0
        proc = subprocess.Popen(
            tunnel_cmd, stdout=sys.stdout, stderr=sys.stderr,
            creationflags=flags)
        time.sleep(2)
        return proc
    except FileNotFoundError as exc:
        print(f"  ✗ Could not launch tunnel: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Launch the NeuRAG→HTTP bridge (mcp-proxy in server mode).")
    parser.add_argument("--port", type=int,
                        default=_env_int("NEURAG_BRIDGE_PORT", 8001),
                        help="HTTP port (default 8001, env: NEURAG_BRIDGE_PORT).")
    parser.add_argument("--host",
                        default=os.environ.get("NEURAG_BRIDGE_HOST", "127.0.0.1"),
                        help="Bind host (default 127.0.0.1, env: NEURAG_BRIDGE_HOST). "
                             "Use 0.0.0.0 for tunnel exposure.")
    parser.add_argument("--no-check", action="store_true", help="Skip the NeuRAG preflight.")
    parser.add_argument("--print-cmd", action="store_true",
                        help="Print the full command and exit (don't run).")
    parser.add_argument("--tunnel", action="store_true",
                        help="Auto-launch tunnel after bridge starts.")
    parser.add_argument("--no-tunnel", action="store_true",
                        help="Disable tunnel even if NEURAG_BRIDGE_TUNNEL=1.")
    parser.add_argument("--port-range", type=int, default=10,
                        help="If default port is taken, try this many consecutive ports (default 10).")
    parser.add_argument("neurag_cmd", nargs=argparse.REMAINDER,
                        help="Optional: everything after '--' is the NeuRAG launch command.")
    args = parser.parse_args(argv)

    want_tunnel = args.tunnel or (_env_bool("NEURAG_BRIDGE_TUNNEL") and not args.no_tunnel)

    override = args.neurag_cmd
    if override and override[0] == "--":
        override = override[1:]
    neurag_cmd = resolve_neurag_cmd(override or None)

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

    # Smoke test
    try:
        r = subprocess.run(proxy + ["--version"], capture_output=True, timeout=15,
                           creationflags=(subprocess.CREATE_NO_WINDOW if WIN else 0))
        if r.returncode != 0:
            print(f"  [!] '{' '.join(proxy)}' did not return a valid mcp-proxy.",
                  file=sys.stderr)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  [!] '{' '.join(proxy)}' — {exc}", file=sys.stderr)

    # Port fallback
    port = args.port
    if _port_is_occupied(port):
        print(f"  Port {port} is occupied, scanning for a free port...", flush=True)
        free = _find_free_port(port, port + args.port_range - 1)
        if free is None:
            print(f"  ✗ No free port found in range {port}-{port + args.port_range - 1}.",
                  file=sys.stderr)
            return 1
        print(f"  ✓ Using port {free} instead.", flush=True)
        port = free

    full = proxy + [f"--port={port}", f"--host={args.host}", "--"] + neurag_cmd
    url = f"http://{args.host}:{port}/mcp"

    if args.print_cmd:
        print(" ".join(full))
        return 0

    if not args.no_check and not preflight(neurag_cmd):
        return 1

    bind_info = f"{'all interfaces' if args.host == '0.0.0.0' else args.host}:{port}"

    gm = importlib.util.find_spec("gray_matter.server") is not None
    print(f"\nStarting NeuRAG bridge via: {' '.join(proxy)}")
    print(f"  local endpoint : {url}")
    print(f"  bind           : {bind_info}")
    print(f"  server         : {'gray_matter.server (full suite)' if gm else 'neurag.server (standalone)'}")
    if want_tunnel:
        print(f"  tunnel         : will auto-launch after bridge starts")
    else:
        print(f"  next step      : expose it over public HTTPS, e.g.")
        print(f"                   neuron tunnel --port {port}")
        print(f"                   cloudflared tunnel --url http://{args.host}:{port}")
    print(f"  Use /mcp (Streamable HTTP), not /sse — Cloudflare buffers the SSE handshake.\n")
    sys.stdout.flush()

    try:
        flags = 0x08000000 if WIN else 0

        if want_tunnel:
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


if __name__ == "__main__":
    raise SystemExit(main())
