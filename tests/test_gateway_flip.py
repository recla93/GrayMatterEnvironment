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
