"""ADR-014: il daemon compone in una richiesta quello che l'hook di memoria inietta."""
import asyncio
import json
from types import SimpleNamespace

import pytest


def _forgotten(topic: str, concept: str) -> str:
    """Neuron's forgotten(facts=True): one dormant fact near the topic."""
    return (f"Dormant facts near '{topic}':\n"
            f"  [idea] eventi in stile aspect per gli stimoli ({concept}) #0a1b2c3d")


@pytest.fixture
def srv(monkeypatch):
    import gray_matter.server as S
    alive = SimpleNamespace(is_alive=lambda: True, collaborative=True)
    monkeypatch.setattr(S._registry, "get_server", lambda name: alive)
    monkeypatch.setattr(S, "FLASH_MIN_GAP", 0)
    monkeypatch.setattr(S, "PROACTIVE_BUDGET", 800)
    monkeypatch.setattr(S, "_last_topic", "")
    S._HOOK_SEEN.clear()
    calls = []

    async def fake_call(server, tool, args):
        calls.append(tool)
        if tool == "extract":
            return json.dumps({"topic": args["text"][:20], "keywords": ["flash", "hook"]})
        if tool == "pre_turn":
            return "[neuron] CTX"
        if tool == "forgotten":
            assert args.get("facts") is True, "a flash is a fact (ADR-016 D2)"
            return S._forgotten_reply or _forgotten(args["near"], "around")
        if tool == "knowledge_neighbors":
            return json.dumps({"node": None, "neighbors": []})
        if tool == "knowledge_query":
            return S._kq_reply
        raise AssertionError(f"unexpected {server}.{tool}")
    monkeypatch.setattr(S, "_call_server_async", fake_call)
    S._calls = calls
    S._forgotten_reply = ""
    S._kq_reply = ("Top 1 results:\n  [1] D:\\repo\\docs\\INSTALL.md :: Install > Long paths (3/7)"
                   "  (cos 0.61)\n")
    return S


def test_the_flash_is_a_fact_once_per_session(srv):
    flashed: set = set()
    first, concept = asyncio.run(srv._maybe_flash("primo argomento", flashed))
    again, _ = asyncio.run(srv._maybe_flash("secondo argomento", flashed))
    assert first == "⚡ Flash: [idea] eventi in stile aspect per gli stimoli (around) #0a1b2c3d", first
    assert concept == "around"
    assert again == "", "lo stesso fatto non torna solo perche' il topic e' cambiato"


def test_no_dormant_fact_no_flash(srv):
    """ADR-016 D2: nothing near the topic means no flash. It used to fall back
    to the oldest node: "che tempo fara' domani a Milano?" got `clipboard`."""
    srv._forgotten_reply = "No dormant fact near 'che tempo fara domani a Milano?'."
    out, concept = asyncio.run(srv._maybe_flash("che tempo fara domani a Milano?", set()))
    assert (out, concept) == ("", "")


def test_one_request_brings_context_and_flash(srv):
    out = asyncio.run(srv._hook_recall("parliamo ancora del flash di GM", "s1"))
    assert out.startswith("[neuron] CTX")
    assert "⚡ Flash: [idea]" in out and "around" in out
    # Il puntatore KB e' vettoriale: la ricerca per nome indicava cartelle intere.
    assert "knowledge_query" in srv._calls and "knowledge_neighbors" not in srv._calls
    assert '📚 KB: "INSTALL.md :: Install > Long paths" (cos 0.61)' in out, out


def test_recall_searches_the_message_not_the_extracted_words(srv, monkeypatch):
    """extract lasciava passare saluti e verbi (`ciao`, `visto`), e pre_turn
    cerca ogni parola chiave come una chiave a se': ognuna rubava un posto nel
    contesto. Il messaggio intero e' una chiave sola, col significato dentro."""
    seen = {}
    fake = srv._call_server_async

    async def spy(server, tool, args):
        if tool == "pre_turn":
            seen.update(args)
        return await fake(server, tool, args)
    monkeypatch.setattr(srv, "_call_server_async", spy)
    msg = "Ciao! Ho visto che ieri hai pushato. Come va la suite?"
    asyncio.run(srv._hook_recall(msg, "s1"))
    assert seen["topic"] == msg and not seen.get("keywords"), seen
    assert "extract" not in srv._calls


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
    out = asyncio.run(srv.call_tool("pre_turn", {"topic": "flash", "keywords": ["flash"]}))
    assert out[0].text.startswith("[neuron] CTX")
    assert "⚡ Flash: [idea]" in out[0].text


def test_a_weak_kb_match_gives_no_pointer(srv):
    srv._kq_reply = "Top 1 results:\n  [1] D:\\repo\\A.md :: Titolo (1/2)  (cos 0.46)\n"
    out = asyncio.run(srv._hook_recall("dove salva le credenziali Turso per il cloud?", "s1"))
    assert "📚" not in out, "sotto soglia il vettoriale sbagliava: meglio niente"


def test_the_same_kb_section_is_pointed_at_once_per_session(srv):
    a = asyncio.run(srv._hook_recall("come si installa con i path lunghi?", "s1"))
    b = asyncio.run(srv._hook_recall("e ancora sui path lunghi di Windows?", "s1"))
    assert "📚" in a and "📚" not in b


def test_the_vector_pointer_mints_no_bridge(srv, monkeypatch):
    from gray_matter import bridges
    minted = []
    monkeypatch.setattr(bridges, "add_bridge", lambda *a, **k: minted.append(a) or True)
    asyncio.run(srv._hook_recall("come si installa con i path lunghi?", "s1"))
    assert minted == [], "un puntatore e' un suggerimento, un bridge e' un'affermazione"


def test_a_long_memory_context_does_not_cut_the_flash(srv, monkeypatch):
    """Live on 2026-11-08 three long facts filled the hook budget and the flash,
    last, arrived as `[fact] mocoder architecture in docs/ARCHITETTURA.…`."""
    from gray_matter import memhook
    fake = srv._call_server_async

    async def long_ctx(server, tool, args):
        if tool == "pre_turn":
            return "[neuron] " + "x" * 5000
        return await fake(server, tool, args)
    monkeypatch.setattr(srv, "_call_server_async", long_ctx)
    out = asyncio.run(srv._hook_recall("parliamo ancora del flash di GM", "s1"))
    assert len(out) <= memhook.BUDGET, len(out)
    assert out.endswith("⚡ Flash: [idea] eventi in stile aspect per gli stimoli (around) #0a1b2c3d"), out[-120:]
    assert "📚 KB:" in out
    assert memhook.fit(out) == out, "the hook's own cut must not touch it any more"


def test_the_daemon_warms_neurons_model_and_recall_vectors():
    """ADR-016 D6: `status` loaded the graph, not the model nor the vectors, and
    the first recall after a start waited 44 s. forgotten(facts) loads both and
    has no side effect (pre_turn would consume the staged stimulus)."""
    import gray_matter.server as S
    tool, args = S._WARM_TOOL["neuron"]
    assert (tool, args.get("facts")) == ("forgotten", True)
