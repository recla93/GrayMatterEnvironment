"""Gateway flip (register --gateway) + daemon singleton — minimal checks."""
import asyncio
import json
import socket

import pytest

from gray_matter import clients


def test_register_json_gateway_evicts_neuron(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {
        "neuron5": {"command": "py", "args": ["-m", "neuron"]},
        "neurag": {"command": "py", "args": ["-m", "neurag.server"]},
        "other": {"command": "x"},
    }}), encoding="utf-8")
    spec = {"label": "Claude Desktop", "style": "args"} | {"keys": ["mcpServers"]}
    r = clients._register_json(spec, str(cfg), ["gray-matter"], "py",
                               evict=clients.GATEWAY_EVICT)
    assert r["ok"]
    data = json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
    assert "gray-matter" in data
    assert "neuron5" not in data and "neurag" not in data and "neuron" not in data
    assert data["other"] == {"command": "x"}          # untouched
    assert (tmp_path / "claude_desktop_config.json.bak").exists()


def test_register_json_non_dict_root_returns_error_not_crash(tmp_path):
    """JSON valido ma root non-oggetto: un tempo esplodeva (setdefault su str/list),
    ora error pulito e file lasciato intatto."""
    spec = {"label": "Test", "style": "args"} | {"keys": ["mcpServers"]}
    for i, bad in enumerate(["string", ["list"], 42, True, None]):
        cfg = tmp_path / f"cfg_{i}.json"
        raw = json.dumps(bad)
        cfg.write_text(raw, encoding="utf-8")
        r = clients._register_json(spec, str(cfg), ["gray-matter"], "py")
        assert r["ok"] is False and r["action"] == "error", r
        assert cfg.read_text(encoding="utf-8") == raw   # non toccato


def test_ipc_listener_exits_when_port_taken(monkeypatch):
    pytest.importorskip("mcp")  # imports gray_matter.server; needs real MCP (local/CI)
    from gray_matter import server
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    monkeypatch.setattr(server, "GRAY_MATTER_HOST", "127.0.0.1")
    monkeypatch.setattr(server, "GRAY_MATTER_PORT", port)
    monkeypatch.setattr(server, "GRAY_MATTER_PORT_SPAN", 1)  # only try the blocked port
    try:
        with pytest.raises(SystemExit):
            asyncio.run(server._ipc_listener())
        # stdio mode: same conflict must NOT kill the instance, just skip the listener
        asyncio.run(server._ipc_listener(exit_on_busy=False))
    finally:
        blocker.close()


def test_prewarm_dismisses_local_workers_when_daemon_appears(monkeypatch):
    """La race dei 30 s: due gateway partiti nello stesso secondo.

    Chi perde l'elezione aveva gia' messo `_daemon_gone_until` a +30 s, quindi
    `_daemon_reachable()` continuava a dire "nessun daemon" per mezzo minuto —
    abbastanza perche' il prewarm spawnasse un set locale completo, che poi
    teneva i file di grafo per tutta la vita del processo. Il prewarm ora
    ri-sonda a ogni giro scavalcando il backoff, e dismette cio' che ha aperto.
    """
    pytest.importorskip("mcp")
    from gray_matter import server

    monkeypatch.setattr(server, "_IS_DAEMON", False)
    monkeypatch.setattr(server, "_daemon_gone_until", __import__("time").time() + 30)
    monkeypatch.setattr(server.os, "environ", {**server.os.environ, "GM_PREWARM": "1"})
    monkeypatch.setattr(server, "_cfg", {**server._cfg, "prewarm": True})

    answers = [False, True]          # primo giro: nessun daemon; secondo: c'e'
    monkeypatch.setattr(server, "gm_answers", lambda *a, **k: answers.pop(0) if answers else True)
    monkeypatch.setattr(server, "resolve_port", lambda: 9876)

    spawned, dismissed = [], []
    monkeypatch.setattr(server, "_worker_for", lambda n: spawned.append(n))
    monkeypatch.setattr(server, "_shutdown_workers", lambda: dismissed.append(True))

    class _S:
        name, collaborative = "neuron", True
    monkeypatch.setattr(server._registry, "alive_servers", lambda: [_S()])
    monkeypatch.setattr(server, "_WARM_TOOL", {})
    monkeypatch.setattr(server, "_prewarmed", set())

    async def _fast_sleep(_s):
        return
    monkeypatch.setattr(server.asyncio, "sleep", _fast_sleep)

    asyncio.run(asyncio.wait_for(server._prewarm_workers(), timeout=5))

    assert spawned == ["neuron"], "primo giro: nessun daemon, il prewarm scalda in locale"
    assert dismissed, "daemon apparso: i worker locali vanno dismessi, non lasciati sul DB"


def test_ipc_shutdown_flushes_workers_before_exiting(monkeypatch):
    """`action: shutdown` usciva con os._exit(0), che salta atexit E la pulizia
    in fondo a _run(): i worker del daemon gli sopravvivevano come writer orfani
    sugli stessi file di grafo, senza checkpoint finale. Il flush va PRIMA."""
    pytest.importorskip("mcp")
    import inspect
    from gray_matter import server
    src = inspect.getsource(server._ipc_listener)
    i_flush = src.find("_shutdown_workers()")
    i_exit = src.find("os._exit(0)")
    assert i_flush != -1, "lo shutdown IPC non fa il flush dei worker"
    assert i_flush < i_exit, "il flush deve precedere os._exit, o non viene eseguito"
