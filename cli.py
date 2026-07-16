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
        print(f"  {name} ({status}) pid={pid} tools=[{tools}]")


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
    time.sleep(0.5)
    if _is_gray_matter_running():
        print("Gray-Matter started.")
    else:
        print("Failed to start Gray-Matter.")
        sys.exit(1)


def cmd_ping() -> None:
    from gray_matter.server import _is_gray_matter_running
    if _is_gray_matter_running():
        print("Gray-Matter is running.")
    else:
        print("Gray-Matter is not running.")
        sys.exit(1)


def main() -> None:
    import json
    parser = argparse.ArgumentParser(description="Gray-Matter control")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show Gray-Matter status and registered servers")
    sub.add_parser("start", help="Start Gray-Matter daemon")
    sub.add_parser("stop", help="Stop Gray-Matter daemon")
    sub.add_parser("ping", help="Check if Gray-Matter is running")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "ping":
        cmd_ping()


if __name__ == "__main__":
    main()
