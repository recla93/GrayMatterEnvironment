"""Gray-Matter CLI: start, stop, status, logs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path

from gray_matter import __version__
from gray_matter.server import GRAY_MATTER_HOST, GRAY_MATTER_PORT


def _send_ipc(data: dict) -> dict:
    payload = json.dumps(data).encode("utf-8")
    length = struct.pack("!I", len(payload))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3.0)
            s.connect((GRAY_MATTER_HOST, GRAY_MATTER_PORT))
            s.sendall(length + payload)
            resp_len_bytes = s.recv(4)
            if not resp_len_bytes:
                return {"error": "no response"}
            resp_len = struct.unpack("!I", resp_len_bytes)[0]
            resp_data = s.recv(resp_len)
            return json.loads(resp_data.decode("utf-8"))
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        return {"error": str(e)}


def cmd_status() -> None:
    result = _send_ipc({"action": "status"})
    if "error" in result:
        print(f"Gray-Matter not running ({result['error']}).")
        sys.exit(1)
    print(f"Gray-Matter v{__version__}")
    print(f"Servers: {len(result)}")
    for name, info in result.items():
        status = info.get("status", "unknown")
        tools = ", ".join(info.get("tool_names", []))
        pid = info.get("pid", "?")
        collab = "collab" if info.get("collaborative", True) else "ISOLATED"
        print(f"  {name} ({status}, {collab}) pid={pid} tools=[{tools}]")


def cmd_stop() -> None:
    import json
    result = _send_ipc({"action": "shutdown"})
    if "error" in result:
        print(f"Gray-Matter not running ({result['error']}).")
        sys.exit(1)
    print("Gray-Matter stopped.")


def cmd_start() -> None:
    from gray_matter.server import _spawn_gray_matter, _is_gray_matter_running
    if _is_gray_matter_running():
        print("Gray-Matter already running.")
        return
    _spawn_gray_matter()
    for _ in range(30):          # up to ~3s for the daemon to bind :9876 (cold Python start)
        time.sleep(0.1)
        if _is_gray_matter_running():
            print("Gray-Matter started.")
            return
    print("Failed to start Gray-Matter.")
    sys.exit(1)


def cmd_ping() -> None:
    from gray_matter.server import _is_gray_matter_running
    if _is_gray_matter_running():
        print("Gray-Matter is running.")
    else:
        print("Gray-Matter is not running.")
        sys.exit(1)


def _not_running(r: dict) -> bool:
    if "error" in r:
        print(f"Gray-Matter not running ({r['error']}).")
        return True
    return False


def cmd_isolate(name: str) -> None:
    r = _send_ipc({"action": "isolate", "name": name})
    if _not_running(r):
        return
    print(f"Isolated '{name}': out of the combined pulse, still callable directly."
          if r.get("status") == "ok" else f"No such server: {name}.")


def cmd_collaborate(name: str) -> None:
    r = _send_ipc({"action": "collaborate", "name": name})
    if _not_running(r):
        return
    print(f"'{name}' back in the combined pulse."
          if r.get("status") == "ok" else f"No such server: {name}.")


def cmd_mode(mode: str) -> None:
    r = _send_ipc({"action": "mode", "mode": mode})
    if _not_running(r):
        return
    print(f"Mode: {mode} (all servers).")


def cmd_register() -> None:
    """Register every installed trio server in the detected MCP clients."""
    from gray_matter import clients
    servers = clients.installed_servers()
    if not servers:
        print("No installed servers to register (install one first).")
        return
    print(f"Registering {', '.join(servers)} in detected MCP clients...")
    for r in clients.register(servers):
        mark = "OK" if r.get("ok") else ("--" if r.get("action") == "skipped" else "!!")
        line = f"  [{mark}] {r['client']}: {r['action']}"
        if r.get("detail"):
            line += f" — {r['detail']}"
        print(line)
        if r.get("snippet"):
            print("       add by hand:")
            for ln in r["snippet"].splitlines():
                print("         " + ln)
    print("Done. Restart your AI apps to load the servers.")


def cmd_bridges() -> None:
    from gray_matter.bridges import all_bridges
    bs = all_bridges()
    if not bs:
        print("No bridges yet.")
        return
    print(f"{len(bs)} cross-store bridge(s), strongest first:")
    for b in bs:
        rat = f" — {b['rationale']}" if b.get("rationale") else ""
        print(f"  [w={b.get('weight', 1)}] {b['neuron']} <-> {b['neurag']}{rat}")


def main() -> None:
    import json
    parser = argparse.ArgumentParser(description="Gray-Matter control")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show Gray-Matter status and registered servers")
    sub.add_parser("start", help="Start Gray-Matter daemon")
    sub.add_parser("stop", help="Stop Gray-Matter daemon")
    sub.add_parser("ping", help="Check if Gray-Matter is running")

    iso = sub.add_parser("isolate", help="Exclude a server from the combined pulse (still callable directly)")
    iso.add_argument("name", help="Server name (neuron|neurag)")
    col = sub.add_parser("collaborate", help="Put a server back into the combined pulse")
    col.add_argument("name", help="Server name (neuron|neurag)")
    md = sub.add_parser("mode", help="Set ALL servers to collaborate or separate")
    md.add_argument("mode", choices=["collaborate", "separate"])

    gui_p = sub.add_parser("gui", help="Open the unified web control center")
    gui_p.add_argument("--classic", action="store_true",
                       help="Use the legacy Tkinter control center instead")
    sub.add_parser("register", help="Register installed trio servers in your MCP clients")
    sub.add_parser("bridges", help="List persisted cross-store bridges")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "ping":
        cmd_ping()
    elif args.command == "isolate":
        cmd_isolate(args.name)
    elif args.command == "collaborate":
        cmd_collaborate(args.name)
    elif args.command == "mode":
        cmd_mode(args.mode)
    elif args.command == "gui":
        if getattr(args, "classic", False):
            from gray_matter.gui import main as gui_main
        else:
            from gray_matter.webgui import main as gui_main
        gui_main()
    elif args.command == "register":
        cmd_register()
    elif args.command == "bridges":
        cmd_bridges()


if __name__ == "__main__":
    main()
