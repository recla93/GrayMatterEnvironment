"""ADR-014: il daemon compone in una richiesta quello che l'hook di memoria inietta."""
import asyncio
import json
from types import SimpleNamespace

import pytest


def _forgotten(topic: str, concept: str) -> str:
    return (f"Dormant & mid-band related to '{topic}':\n"
            f"  {concept}  last_turn=189  (6 turns ago)  salience=4\nTotal: 1 concepts")


@pytest.fixture
def srv(monkeypatch):
    import gray_matter.server as S
    alive = SimpleNamespace(is_alive=lambda: True, collaborative=True)
    monkeypatch.setattr(S._registry, "get_server", lambda name: alive)
    monkeypatch.setattr(S, "FLASH_MIN_GAP", 0)
    monkeypatch.setattr(S, "PROACTIVE_BUDGET", 800)
    monkeypatch.setattr(S, "_last_topic", "")
    S._KB_HINT_CACHE.clear()
    S._HOOK_SEEN.clear()
    calls = []

    async def fake_call(server, tool, args):
        calls.append(tool)
        if tool == "extract":
            return json.dumps({"topic": args["text"][:20], "keywords": ["flash", "hook"]})
        if tool == "pre_turn":
            return "[neuron] CTX"
        if tool == "forgotten":
            return _forgotten(args["near"], "around")
        if tool == "knowledge_neighbors":
            return json.dumps({"node": None, "neighbors": []})
        raise AssertionError(f"unexpected {server}.{tool}")
    monkeypatch.setattr(S, "_call_server_async", fake_call)
    S._calls = calls
    return S


def test_the_flash_cooldown_is_per_concept_not_per_topic(srv):
    flashed: set = set()
    first, _ = asyncio.run(srv._maybe_flash("primo argomento", flashed))
    again, _ = asyncio.run(srv._maybe_flash("secondo argomento", flashed))
    assert "around" in first
    assert again == "", "lo stesso concetto non torna solo perche' il topic e' cambiato"


def test_one_request_brings_context_and_flash(srv):
    out = asyncio.run(srv._hook_recall("parliamo ancora del flash di GM", "s1"))
    assert out.startswith("[neuron] CTX")
    assert "⚡ Flashback:" in out and "around" in out
    assert "knowledge_query" not in srv._calls, "niente ricerca vettoriale sul percorso del hook"


def test_each_session_has_its_own_cooldown(srv):
    a1 = asyncio.run(srv._hook_recall("primo messaggio abbastanza lungo", "s1"))
    a2 = asyncio.run(srv._hook_recall("secondo messaggio su altro tema", "s1"))
    b1 = asyncio.run(srv._hook_recall("terzo messaggio in un'altra sessione", "s2"))
    assert "⚡" in a1 and "⚡" not in a2 and "⚡" in b1


def test_a_gateway_pre_turn_carries_the_flash_too(srv, monkeypatch):
    """Fase 4: i client senza hook ricevono il flash su pre_turn, senza pulse."""
    from gray_matter.registry import ServerEntry
    neuron = ServerEntry(name="neuron", tool_names=["pre_turn"], socket_path="", pid=0)
    monkeypatch.setattr(srv._registry, "find_server_by_tool",
                        lambda tool: neuron if tool == "pre_turn" else None)
    monkeypatch.setattr(srv, "_flashed", set())

    async def no_net(*a, **k):
        return ""
    monkeypatch.setattr(srv, "_safety_net_note", no_net)
    out = asyncio.run(srv.call_tool("pre_turn", {"topic": "flash", "keywords": ["flash"]}))
    assert out[0].text.startswith("[neuron] CTX")
    assert "⚡ Flashback:" in out[0].text
