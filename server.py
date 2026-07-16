"""Gray-Matter MCP server — proxy + orchestrator.

Runs as a stdio MCP server that:
1. Accepts tool calls from the client
2. Routes them to the right registered MCP server (Neuron, NeuRAG)
3. Returns the response to the client
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

from gray_matter import __version__
from gray_matter.registry import Registry

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAY_MATTER_PORT = 9876
GRAY_MATTER_HOST = "127.0.0.1"
HEARTBEAT_INTERVAL = 5.0  # seconds
HEARTBEAT_TIMEOUT = 15.0  # seconds — after 3 missed beats, mark dead
IDLE_SLEEP_TIMEOUT = 600.0  # 10 minutes — sleep after this long idle
MAX_RESTART_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# IPC helpers (tiny TCP-based protocol for server <-> Gray-Matter)
# ---------------------------------------------------------------------------

def _send_ipc(data: dict) -> dict:
    """Send a JSON IPC message to the local Gray-Matter process."""
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


def _send_registration(name: str, tool_names: list[str], socket_path: str, pid: int) -> dict:
    """Register this server with Gray-Matter."""
    return _send_ipc({
        "action": "register",
        "name": name,
        "tool_names": tool_names,
        "socket_path": socket_path,
        "pid": pid,
    })


def _send_heartbeat(name: str) -> dict:
    """Send a heartbeat ping."""
    return _send_ipc({
        "action": "heartbeat",
        "name": name,
    })


def _is_gray_matter_running() -> bool:
    """Check if a Gray-Matter process is listening on the IPC port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((GRAY_MATTER_HOST, GRAY_MATTER_PORT))
            s.close()
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def autoregister(name: str, tool_names: list[str]) -> bool:
    """Auto-register with a running Gray-Matter. Returns True on success.

    If Gray-Matter is not running, spawns one first.
    Then registers this server.
    """
    # Spawn Gray-Matter if not running
    if not _is_gray_matter_running():
        _spawn_gray_matter()

    # Register (retry up to 3 times — race with spawn)
    pid = os.getpid()
    socket_path = f"tcp://{GRAY_MATTER_HOST}:{os.getpid() + 50000}"  # dummy, placeholder
    for attempt in range(3):
        result = _send_registration(name, tool_names, socket_path, pid)
        if "error" not in result:
            return True
        time.sleep(0.3)
    return False


def _spawn_gray_matter() -> None:
    """Spawn Gray-Matter as a background process."""
    # Use python -m gray_matter.server to run the server module
    # Detach from parent process so it survives parent death
    import sys
    cmd = [sys.executable, "-m", "gray_matter.server", "--daemon"]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    subprocess.Popen(
        cmd,
        creationflags=creationflags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Gray-Matter MCP Server
# ---------------------------------------------------------------------------

_registry = Registry.instance()
_last_call_time: float = time.time()
_flash_counter: int = 0
_cache: dict[str, tuple[float, str]] = {}  # topic -> (timestamp, response_text)
CACHE_TTL = 60.0  # seconds
# Flash v1: fire on a topic shift (serendipity at transitions), rate-limited.
_last_topic: str = ""
_flashed: set = set()          # concepts already flashed this session (cooldown)
_calls_since_flash: int = 0
FLASH_MIN_GAP = 3              # min pulses between flashes (anti-spam)


_is_sleeping: bool = False
_restart_attempts: dict[str, int] = {}

app = Server("gray-matter")


  # server_name -> consecutive failures


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Dynamically list tools from all registered servers."""
    tools = []

    # Gray-Matter's own tools
    tools.append(Tool(
        name="gray_matter_pulse",
        description="Pre-contesto + chunk knowledge + flash. Chiama neuron_get_context e neurag_query in parallelo, unisce, usa cache.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic da cercare"},
                "top_n": {
                    "type": "integer", "description": "Numero chunk (default 5)",
                    "default": 5, "minimum": 1, "maximum": 10,
                },
            },
            "required": ["topic"],
        },
    ))
    tools.append(Tool(
        name="gray_matter_status",
        description="Show Gray-Matter status: registered servers, cache, counters.",
        inputSchema={"type": "object", "properties": {}},
    ))

    # Tools from registered servers
    for server in _registry.alive_servers():
        for tool_name in server.tool_names:
            tools.append(Tool(
                name=tool_name,
                description=f"({server.name}) {tool_name}",
                inputSchema={"type": "object", "properties": {}},
            ))

    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _last_call_time, _flash_counter

    _last_call_time = time.time()
    _flash_counter += 1

    # --- Gray-Matter orchestrated tools ---

    if name == "gray_matter_pulse":
        global _is_sleeping
        _is_sleeping = False
        topic = arguments["topic"]
        top_n = min(int(arguments.get("top_n", 5)), 10)

        # Cache hit?
        from gray_matter.cache import ContextCache
        cache = ContextCache()
        cached = cache.get(topic)
        if cached is not None:
            return [TextContent(type="text", text=cached)]

        # Collect calls to registered servers
        tasks = []

        neuron = _registry.get_server("neuron")
        if neuron and neuron.is_alive() and neuron.collaborative:
            tasks.append(_call_server_async("neuron", "get_context", {"topic": topic, "depth": 1}))

        neurag = _registry.get_server("neurag")
        if neurag and neurag.is_alive() and neurag.collaborative:
            tasks.append(_call_server_async("neurag", "knowledge_query", {"query": topic, "top_n": top_n}))

        if not tasks:
            return [TextContent(type="text", text="No servers available for pulse.")]

        # Parallel execution
        results = await asyncio.gather(*tasks, return_exceptions=True)

        context_parts = []
        for r in results:
            if isinstance(r, Exception):
                context_parts.append(f"[error: {r}]")
            elif r:
                context_parts.append(r)

        response = "\n---\n".join(context_parts) if context_parts else "No results."

        # Flash: serendipitous dormant-concept recall, fired at a topic shift.
        flash_note = await _maybe_flash(topic)
        if flash_note:
            response += "\n\n" + flash_note

        # Cache
        cache.set(topic, response)

        return [TextContent(type="text", text=response)]

    if name == "gray_matter_status":
        lines = [
            f"Gray-Matter v{__version__}",
            f"Flash counter: {_flash_counter}",
            f"Servers: {len(_registry.all_servers())}",
            _registry.summary(),
        ]
        return [TextContent(type="text", text="\n".join(lines))]

    # --- Route to registered server (pass-through) ---
    server = _registry.find_server_by_tool(name)
    if server is None:
        return [TextContent(type="text", text=f"Tool '{name}' not found in any registered server.")]

    result = await _call_server_async(server.name, name, arguments)
    return [TextContent(type="text", text=result or "(empty)")]


async def _call_server_async(server_name: str, tool_name: str, arguments: dict) -> str:
    """Call a registered server's tool asynchronously via subprocess."""
    pkg = {"neurag": "neurag.server", "neuron": "neuron.server"}.get(server_name, server_name + ".server")
    code = (
        f"import sys, json, asyncio; "
        f"from {pkg} import app; "
        f"async def _run(): "
        f"  result = await app.call_tool('{tool_name}', {json.dumps(arguments)}); "
        f"  print(result[0].text); "
        f"asyncio.run(_run())"
    )
    loop = asyncio.get_event_loop()
    r = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=30
        )
    )
    if r.returncode != 0:
        _registry.mark_dead(server_name)
        return f"[{server_name}] error: {r.stderr.strip()}"
    return r.stdout.strip()


async def _sleep_monitor():
    """Background: if idle > IDLE_SLEEP_TIMEOUT, flag sleep.

    Sleep means servers are marked 'sleeping'. First client call wakes them.
    """
    global _is_sleeping
    while True:
        await asyncio.sleep(30)
        now = time.time()
        idle = now - _last_call_time

        if idle > IDLE_SLEEP_TIMEOUT and not _is_sleeping:
            _is_sleeping = True
            for s in _registry.all_servers():
                s.status = "sleeping"
        elif idle < IDLE_SLEEP_TIMEOUT and _is_sleeping:
            _is_sleeping = False


async def _restart_dead_servers():
    """Background: attempt to restart dead servers (up to 3 tries)."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL * 2)
        for server in _registry.all_servers():
            if server.status != "dead":
                continue
            name = server.name
            attempts = _restart_attempts.get(name, 0)
            if attempts >= MAX_RESTART_ATTEMPTS:
                continue
            try:
                os.kill(server.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
            _restart_attempts[name] = attempts + 1


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


async def _maybe_flash(topic: str) -> str:
    """Flash v1 — serendipitous recall. Fires at a *topic shift* (not a blind
    counter), surfaces a dormant concept *without* a topic-match filter (a flashback
    is meant to be non-obvious), rate-limited by a min gap + a per-session
    per-concept cooldown. Read-only; the cross-store bridge (v3) is where GM writes.
    """
    global _last_topic, _calls_since_flash
    _calls_since_flash += 1
    shifted = _norm(topic) != _norm(_last_topic)
    _last_topic = topic
    if not shifted or _calls_since_flash < FLASH_MIN_GAP:
        return ""

    neuron = _registry.get_server("neuron")
    if not neuron or not neuron.is_alive():
        return ""
    forgotten = (await _call_server_async("neuron", "forgotten", {"threshold": 5})).strip()
    if not forgotten or forgotten.startswith("["):   # skip empties / "[neuron] error: ..."
        return ""
    key = forgotten[:80]
    if key in _flashed:                              # per-concept cooldown
        return ""
    _flashed.add(key)
    _calls_since_flash = 0
    return f"⚡ Flashback: {forgotten}"


# ---------------------------------------------------------------------------
# IPC listener (background) — receives registrations, heartbeats
# ---------------------------------------------------------------------------

async def _ipc_listener():
    """Background task: listens for incoming IPC connections (registrations, heartbeats)."""
    loop = asyncio.get_event_loop()
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((GRAY_MATTER_HOST, GRAY_MATTER_PORT))
    server_sock.listen(5)
    server_sock.setblocking(False)

    while True:
        try:
            conn, addr = await loop.sock_accept(server_sock)
            conn.settimeout(3.0)
            data = await loop.sock_recv(conn, 4096)
            if data:
                try:
                    # Parse length-prefixed JSON
                    msg = json.loads(data[4:].decode("utf-8"))  # skip 4-byte length
                    action = msg.get("action")
                    response = {}

                    if action == "register":
                        _registry.register(
                            name=msg["name"],
                            tool_names=msg["tool_names"],
                            socket_path=msg["socket_path"],
                            pid=msg["pid"],
                        )
                        response = {"status": "ok", "message": f"Registered {msg['name']}"}
                    elif action == "heartbeat":
                        ok = _registry.heartbeat(msg["name"])
                        response = {"status": "ok" if ok else "unknown"}
                    elif action == "unregister":
                        _registry.unregister(msg["name"])
                        response = {"status": "ok"}
                    elif action == "isolate":
                        ok = _registry.set_collaborative(msg["name"], False)
                        response = {"status": "ok" if ok else "unknown"}
                    elif action == "collaborate":
                        ok = _registry.set_collaborative(msg["name"], True)
                        response = {"status": "ok" if ok else "unknown"}
                    elif action == "mode":
                        want = msg.get("mode") == "collaborate"
                        for s in _registry.all_servers():
                            s.collaborative = want
                        response = {"status": "ok"}
                    elif action == "status":
                        response = _registry.to_dict()
                    elif action == "shutdown":
                        response = {"status": "ok"}
                        # Graceful shutdown
                        conn.sendall(struct.pack("!I", len(json.dumps(response).encode("utf-8"))) + json.dumps(response).encode("utf-8"))
                        conn.close()
                        server_sock.close()
                        os._exit(0)
                    else:
                        response = {"error": f"Unknown action: {action}"}

                    resp = json.dumps(response).encode("utf-8")
                    await loop.sock_sendall(conn, struct.pack("!I", len(resp)) + resp)
                except (json.JSONDecodeError, KeyError) as e:
                    pass
            conn.close()
        except OSError:
            await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Heartbeat monitor (background) — marks dead servers
# ---------------------------------------------------------------------------

async def _heartbeat_monitor():
    """Background task: check heartbeats, mark dead servers."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        now = time.time()
        for server in _registry.all_servers():
            if server.status == "alive" and (now - server.last_heartbeat) > HEARTBEAT_TIMEOUT:
                server.status = "dead"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run Gray-Matter as a stdio MCP server with background IPC listener."""
    async def _run():
        # Start background tasks
        ipc_task = asyncio.create_task(_ipc_listener())
        hb_task = asyncio.create_task(_heartbeat_monitor())
        sleep_task = asyncio.create_task(_sleep_monitor())
        restart_task = asyncio.create_task(_restart_dead_servers())

        # Start stdio MCP server
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="gray-matter",
                    server_version=__version__,
                ),
            )

        # Cleanup
        ipc_task.cancel()
        hb_task.cancel()
        sleep_task.cancel()
        restart_task.cancel()

    asyncio.run(_run())


def auto_register_and_run(name: str, tool_names: list[str]) -> None:
    """Called by a server (Neuron, NeuRAG) on startup.

    Tries to register with existing Gray-Matter.
    If Gray-Matter is not running, spawns one first,
    then runs the server's own MCP main loop.
    """
    autoregister(name, tool_names)

    # Start heartbeat in background
    import threading
    def _heartbeat_loop():
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            _send_heartbeat(name)
    t = threading.Thread(target=_heartbeat_loop, daemon=True)
    t.start()


def run_daemon() -> None:
    """Registry/orchestrator only: IPC listener (:9876) + monitors, NO stdio MCP.
    This is how Gray-Matter runs when started as a background daemon (autoregister
    or `gray-matter start`) — there's no MCP client to attach stdio to, so main()'s
    stdio_server() would just exit on a detached process."""
    async def _run():
        await asyncio.gather(
            _ipc_listener(),
            _heartbeat_monitor(),
            _sleep_monitor(),
            _restart_dead_servers(),
        )
    asyncio.run(_run())


if __name__ == "__main__":
    import sys
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        main()
