"""Gray Matter HTTP Bridge — full suite entry point over Streamable HTTP.

Exposes the complete orchestrator (Neuron + NeuRAG + GM orchestration) via
mcp-proxy so remote LLMs (Perplexity, ChatGPT, etc.) see ALL tools.

Port 8002 (distinct from Neuron=8000, NeuRAG=8001).

Usage::

    gray-matter bridge                  # localhost:8002
    gray-matter bridge --port 9000      # custom port
    gray-matter bridge --tunnel         # launch tunnel after bridge
    gray-matter bridge --bind all       # 0.0.0.0 for LAN

Env vars: ``GM_BRIDGE_HOST``, ``GM_BRIDGE_PORT``, ``GM_BRIDGE_TUNNEL``
"""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import List, Optional

WIN = os.name == "nt"
DEFAULT_PORT = 8002


def _find_free_port(start: int, range_size: int = 1) -> int | None:
    """Find an unused port in [start, start+range_size)."""
    for p in range(start, start + range_size):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return None


def resolve_gm_cmd(override: list[str] | None) -> list[str]:
    """Return the command that launches gray_matter.server.

    Priority: explicit override → the installed venv (via the GME registry)
    → this interpreter.

    The venv used to be guessed as ``%LOCALAPPDATA%\\Programs\\<slug>\\.venv``,
    a location no installer has ever written: the branch could not fire, so the
    bridge always fell through to ``sys.executable``. The registry is where the
    interpreter is actually recorded (``gme.register_installed`` writes
    ``sys.prefix`` at install time), and it is per-OS, so no WIN special case."""
    if override:
        return override
    try:
        from gray_matter import gme
        venv_py = gme.get_python("gray-matter")
        if venv_py and os.path.isfile(venv_py) and venv_py != sys.executable:
            return [venv_py, "-m", "gray_matter.server"]
    except (ImportError, OSError):
        pass
    if importlib.util.find_spec("gray_matter.server") is not None:
        return [sys.executable, "-m", "gray_matter.server"]
    return [sys.executable, "-m", "gray_matter.server"]


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
    print(f"Preflight: starting Gray Matter (full suite) → {' '.join(server_cmd)}")
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
        print("  ✓ Gray Matter starts and stays alive.")
        return True
    err = (proc.stderr.read() or b"").decode(errors="replace").strip()
    print(f"  ✗ Gray Matter exited immediately (code {proc.returncode}). Its error:\n")
    print("    " + "\n    ".join((err or "(no stderr)").splitlines()[-15:]))
    print("\n  → Fix that first. Run this script with the Python where Gray Matter is installed.")
    return False


def _launch_tunnel(host: str, port: int) -> subprocess.Popen | None:
    """Launch `neuron tunnel` as a background process."""
    if importlib.util.find_spec("neuron.tunnel") is not None:
        # Same dead `Programs\<slug>\.venv` guess as resolve_gm_cmd had — and here
        # it mattered less only because find_spec already proves neuron is
        # importable from THIS interpreter. Registry first, self as the fallback.
        python = sys.executable
        try:
            from gray_matter import gme
            reg = gme.get_python("neuron")
            if reg and os.path.isfile(reg):
                python = reg
        except (ImportError, OSError):
            pass
        cmd = [python, "-m", "neuron.tunnel", "--port", str(port)]
    elif shutil.which("cloudflared"):
        cmd = ["cloudflared", "tunnel", "--url", f"http://{host}:{port}"]
    else:
        print("  [!] Neither neuron.tunnel nor cloudflared found — cannot auto-launch tunnel.")
        return None
    try:
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except Exception as exc:
        print(f"  ✗ Could not launch tunnel: {exc}", file=sys.stderr)
        return None


def main(argv: Optional[List[str]] = None) -> int:
    env_host = os.environ.get("GM_BRIDGE_HOST")
    env_port = os.environ.get("GM_BRIDGE_PORT")
    env_tunnel = os.environ.get("GM_BRIDGE_TUNNEL", "").lower() in ("1", "true", "yes")

    p = argparse.ArgumentParser(
        prog="gray-matter bridge",
        description="Expose Gray Matter (full suite) over HTTP for remote LLM connectors.",
    )
    p.add_argument("--host", default=env_host or "127.0.0.1",
                    help="Bind address (default: 127.0.0.1; env: GM_BRIDGE_HOST)")
    p.add_argument("--bind", choices=["local", "all"], default="local",
                    help="Shorthand: 'local' → 127.0.0.1, 'all' → 0.0.0.0")
    p.add_argument("--port", type=int, default=int(env_port or DEFAULT_PORT),
                    help=f"TCP port (default: {DEFAULT_PORT}; env: GM_BRIDGE_PORT)")
    p.add_argument("--port-range", type=int, default=10,
                    help="How many ports to try if the primary is busy (default: 10)")
    p.add_argument("--tunnel", action="store_true", default=env_tunnel,
                    help="Auto-launch a tunnel after the bridge starts")
    p.add_argument("--proxy", default=None,
                    help="Explicit mcp-proxy command (overrides auto-detect)")
    p.add_argument("--no-check", action="store_true",
                    help="Skip the preflight check")
    p.add_argument("--print-cmd", action="store_true",
                    help="Print the mcp-proxy command and exit")
    args = p.parse_args(argv)

    if args.bind == "all":
        args.host = "0.0.0.0"

    gm_cmd = resolve_gm_cmd(None)
    proxy = resolve_proxy_runner()
    if proxy is None:
        print("No way to run 'mcp-proxy' was found.\n"
              "Install one: pip install mcp-proxy | pipx install mcp-proxy\n"
              "Or use uv/uvx: uvx mcp-proxy\n"
              "Or pass --proxy 'your-command mcp-proxy'")
        return 1

    port = args.port
    port = _find_free_port(port, args.port_range) or port

    url = f"http://{args.host}:{port}"
    full = [*proxy, f"--port={port}", f"--host={args.host}", "--", *gm_cmd]

    if args.print_cmd:
        print(" ".join(full))
        return 0

    if not args.no_check and not preflight(gm_cmd):
        return 1

    bind_info = f"{'all interfaces' if args.host == '0.0.0.0' else args.host}:{port}"

    print(f"\nStarting Gray Matter bridge via: {' '.join(proxy)}")
    print(f"  local endpoint : {url}")
    print(f"  bind           : {bind_info}")
    print(f"  server         : gray_matter.server (full suite — Neuron + NeuRAG + GM)")
    if args.tunnel:
        print(f"  tunnel         : will auto-launch after bridge starts")
    else:
        print(f"  next step      : expose it over public HTTPS, e.g.")
        print(f"                   neuron tunnel --port {port}")
        print(f"                   cloudflared tunnel --url http://{args.host}:{port}")
    print(f"  Use /mcp (Streamable HTTP), not /sse — Cloudflare buffers the SSE handshake.\n")
    sys.stdout.flush()

    try:
        flags = 0x08000000 if WIN else 0

        if args.tunnel:
            tunnel_proc = _launch_tunnel(args.host, port)
            try:
                rc = subprocess.call(full, creationflags=flags)
            except KeyboardInterrupt:
                rc = 0
            finally:
                if tunnel_proc and tunnel_proc.poll() is None:
                    tunnel_proc.terminate()
        else:
            try:
                rc = subprocess.call(full, creationflags=flags)
            except KeyboardInterrupt:
                rc = 0

        return rc
    except Exception as exc:
        print(f"Failed to start the proxy: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
