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


def cmd_stats() -> None:
    r = _send_ipc({"action": "stats"})
    if "error" in r:
        print(f"Gray-Matter not running ({r['error']}).")
        sys.exit(1)
    print("Gray-Matter stats:")
    order = ["pulses", "cache_hits", "cache_misses", "cache_hit_rate", "cache_size",
             "flashes", "bridges_added_session", "bridges_total", "avg_miss_ms",
             "workers_alive"]
    for k in order:
        if k in r:
            print(f"  {k:22} {r[k]}")


def cmd_doctor() -> None:
    r = _send_ipc({"action": "doctor"})
    if "error" in r:
        print(f"Gray-Matter not running ({r['error']}).")
        sys.exit(1)
    print(f"Gray-Matter v{r.get('version')} — {'sleeping' if r.get('sleeping') else 'awake'}")
    print(f"  cache: {r.get('cache_size')} entries | bridges: {r.get('bridges_total')}")
    servers = r.get("servers", [])
    if not servers:
        print("  (no servers registered)")
    for s in servers:
        mark = "ok" if s.get("alive") else "DEAD"
        collab = "collab" if s.get("collaborative") else "ISOLATED"
        worker = "worker+" if s.get("worker") else "worker-"
        print(f"  [{mark}] {s['name']} ({s.get('status')}, {collab}) {worker}")
    if r.get("neurag_engine") == "sqlite":
        print("  [!!] NeuRAG vector tier DEGRADED (sqlite3, Python cosine) — "
              "full tier: pip install neurag[turso]  (wheels in Neuron/vendor)")


def cmd_config(action: str, key: str = "", value: str = "") -> None:
    from gray_matter import settings
    if action == "list":
        cfg = settings.load()
        print("Gray-Matter config (knob = valore):")
        for k in sorted(cfg):
            print(f"  {k:22} {cfg[k]}")
        return
    if action == "get":
        if not key:
            print("uso: gray-matter config get <key>"); sys.exit(1)
        val = settings.get(key)
        if val is None:
            print(f"chiave sconosciuta: {key}"); sys.exit(1)
        print(val)
        return
    # set
    if not key or value == "":
        print("uso: gray-matter config set <key> <value>"); sys.exit(1)
    try:
        cfg = settings.set(key, value)
    except KeyError as e:
        print(str(e)); sys.exit(1)
    print(f"{key} = {cfg[key]}")


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


def cmd_register(gateway: bool = False) -> None:
    """Register every installed trio server in the detected MCP clients.

    --gateway: proxy model — register ONLY gray-matter, evict neuron/neurag
    (GM self-bootstraps them as managed workers)."""
    from gray_matter import clients
    servers = ["gray-matter"] if gateway else clients.installed_servers()
    if not servers:
        print("No installed servers to register (install one first).")
        return
    verb = "Gateway flip: registering" if gateway else "Registering"
    print(f"{verb} {', '.join(servers)} in detected MCP clients...")
    for r in clients.register(servers, gateway=gateway):
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


def _print_results(results: list) -> None:
    for r in results:
        mark = "OK" if r.get("ok") else "!!"
        line = f"  [{mark}] {r['action']}"
        for key in ("component", "client", "name", "path", "detail"):
            if isinstance(r.get(key), str):
                line += f" {r[key]}" if key != "detail" else f" — {r[key]}"
        print(line)
        for s in (r.get("clients") if isinstance(r.get("clients"), list) else []):
            smark = "OK" if s.get("ok") else ("--" if s.get("action") == "skipped" else "!!")
            print(f"       [{smark}] {s.get('client')}: {s.get('action')}"
                  + (f" — {s['detail']}" if s.get("detail") else ""))


def cmd_install(dry_run: bool = False) -> None:
    """Idempotent install: reap orphans, ensure data dirs, register ONLY the
    gateway, deploy per-client hooks, write manifest (INSTALLER-UX §5)."""
    from gray_matter import executor
    print(("[dry-run] " if dry_run else "") + "Installing (gateway model)...")
    _print_results(executor.execute_install(dry_run=dry_run))
    print("Done." + ("" if dry_run else " Restart your AI apps."))


def cmd_uninstall(purge_data: bool = False, yes: bool = False,
                  dry_run: bool = False) -> None:
    """Uninstall: reap, deregister, remove hooks/code; memory is INTERACTIVE
    (asks per data path) unless --purge-data (INSTALLER-UX §6)."""
    from gray_matter import executor
    print(("[dry-run] " if dry_run else "") + "Uninstalling...")
    _print_results(executor.execute_uninstall(
        purge_data=purge_data, assume_yes=yes, dry_run=dry_run))
    print("Done.")


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


_KNOWLEDGE_TOOLS = {
    "status": "knowledge_status",
    "rebuild-links": "knowledge_rebuild_links",
    "link-graph": "knowledge_link_graph",
}


def cmd_knowledge(subcmd: str) -> None:
    tool = _KNOWLEDGE_TOOLS.get(subcmd)
    if not tool:
        print(f"Unknown knowledge subcommand: {subcmd}")
        print(f"Available: {', '.join(_KNOWLEDGE_TOOLS)}")
        sys.exit(1)
    r = _send_ipc({"action": "knowledge_cmd", "tool": tool, "args": {}})
    if "error" in r:
        print(f"Error: {r['error']}")
        sys.exit(1)
    if "text" in r:
        print(r["text"])
    elif "result" in r:
        print(r["result"])


def cmd_gm_neuron(tool: str, args_json: str) -> None:
    """Call a Neuron tool via Gray Matter orchestrator."""
    try:
        tool_args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        print(f"Invalid JSON args: {e}")
        sys.exit(1)
    r = _send_ipc({"action": "gm-neuron", "tool": tool, "args": tool_args})
    if "error" in r:
        print(f"[gm-neuron] {tool} -> error: {r['error']}")
        sys.exit(1)
    if "result" in r:
        result = r["result"].strip() if isinstance(r["result"], str) else str(r["result"])
        print(f"[gm-neuron] {tool} -> {result}")


def cmd_gm_neurag(tool: str, args_json: str) -> None:
    """Call a NeuRAG tool via Gray Matter orchestrator."""
    try:
        tool_args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as e:
        print(f"Invalid JSON args: {e}")
        sys.exit(1)
    r = _send_ipc({"action": "gm-neurag", "tool": tool, "args": tool_args})
    if "error" in r:
        print(f"[gm-neurag] {tool} -> error: {r['error']}")
        sys.exit(1)
    if "result" in r:
        result = r["result"].strip() if isinstance(r["result"], str) else str(r["result"])
        print(f"[gm-neurag] {tool} -> {result}")


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
    reg_p = sub.add_parser("register", help="Register installed trio servers in your MCP clients")
    reg_p.add_argument("--gateway", action="store_true",
                       help="Proxy model: register ONLY gray-matter, remove neuron/neurag from clients")
    ins_p = sub.add_parser("install", help="Idempotent gateway install (reap, register GM, deploy hooks, manifest)")
    ins_p.add_argument("--dry-run", action="store_true", help="Show actions without doing them")
    uni_p = sub.add_parser("uninstall", help="Remove GM (interactive on the memory)")
    uni_p.add_argument("--purge-data", action="store_true", help="Also wipe memory WITHOUT asking")
    uni_p.add_argument("--yes", action="store_true", help="Answer yes to every prompt")
    uni_p.add_argument("--dry-run", action="store_true", help="Show actions without doing them")
    sub.add_parser("bridges", help="List persisted cross-store bridges")
    sub.add_parser("stats", help="Orchestrator counters: cache hit rate, flashes, bridges, latency")
    sub.add_parser("doctor", help="Health snapshot: servers, workers, cache, bridges")

    kn_p = sub.add_parser("knowledge", help="NeuRAG knowledge base management")
    kn_p.add_argument("subcmd", choices=["status", "rebuild-links", "link-graph"],
                       help="status=show nodes/chunks/links, rebuild-links= wipe+rebuild, link-graph= show graph")

    gm_nrn = sub.add_parser("gm-neuron", help="Call a Neuron tool via Gray Matter")
    gm_nrn.add_argument("tool", help="Neuron tool name (e.g. pre_turn, store_turn, get_context)")
    gm_nrn.add_argument("args", nargs="?", default="{}", help="JSON arguments for the tool")

    gm_nrg = sub.add_parser("gm-neurag", help="Call a NeuRAG tool via Gray Matter")
    gm_nrg.add_argument("tool", help="NeuRAG tool name (e.g. knowledge_query, knowledge_status)")
    gm_nrg.add_argument("args", nargs="?", default="{}", help="JSON arguments for the tool")

    cfg_p = sub.add_parser("config", help="Get/set tunable knobs (flash rate, cache TTL, prewarm, ...)")
    cfg_p.add_argument("action", choices=["get", "set", "list"])
    cfg_p.add_argument("key", nargs="?", default="")
    cfg_p.add_argument("value", nargs="?", default="")

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
        cmd_register(args.gateway)
    elif args.command == "install":
        cmd_install(args.dry_run)
    elif args.command == "uninstall":
        cmd_uninstall(args.purge_data, args.yes, args.dry_run)
    elif args.command == "bridges":
        cmd_bridges()
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "doctor":
        cmd_doctor()
    elif args.command == "config":
        cmd_config(args.action, args.key, args.value)
    elif args.command == "knowledge":
        cmd_knowledge(args.subcmd)
    elif args.command == "gm-neuron":
        cmd_gm_neuron(args.tool, args.args)
    elif args.command == "gm-neurag":
        cmd_gm_neurag(args.tool, args.args)


if __name__ == "__main__":
    main()
