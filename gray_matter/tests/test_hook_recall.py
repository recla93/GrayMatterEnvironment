"""ADR-014: the daemon builds in one request what the memory hook injects."""
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
    assert again == "", "the same fact does not come back just because the topic changed"


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
    # The KB pointer is by vector: the search by name pointed at whole folders.
    assert "knowledge_query" in srv._calls and "knowledge_neighbors" not in srv._calls
    assert '📚 KB: "INSTALL.md :: Install > Long paths" (cos 0.61)' in out, out


def test_recall_searches_the_message_not_the_extracted_words(srv, monkeypatch):
    """extract let greetings and verbs through (`ciao`, `visto`), and pre_turn
    searches each keyword as a key of its own: each one stole a place in the
    context. The whole message is one key, with the meaning inside."""
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
    """Phase 4: clients without the hook get the flash on pre_turn, without pulse."""
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
    assert "📚" not in out, "below the threshold the vector hit was wrong: better nothing"


def test_the_same_kb_section_is_pointed_at_once_per_session(srv):
    a = asyncio.run(srv._hook_recall("come si installa con i path lunghi?", "s1"))
    b = asyncio.run(srv._hook_recall("e ancora sui path lunghi di Windows?", "s1"))
    assert "📚" in a and "📚" not in b


def test_the_vector_pointer_mints_no_bridge(srv, monkeypatch):
    from gray_matter import bridges
    minted = []
    monkeypatch.setattr(bridges, "add_bridge", lambda *a, **k: minted.append(a) or True)
    asyncio.run(srv._hook_recall("come si installa con i path lunghi?", "s1"))
    assert minted == [], "a pointer is a suggestion, a bridge is a claim"


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
    out = asyncio.run(srv._hook_recall("parliamo ancora del flash di GM", "s1", profile=False))
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


def _profile_spy(srv, monkeypatch):
    sent, fake = [], srv._call_server_async

    async def spy(server, tool, args):
        if tool == "pre_turn":
            sent.append(bool(args.get("profile")))
        return await fake(server, tool, args)
    monkeypatch.setattr(srv, "_call_server_async", spy)
    return sent


def test_the_hook_asks_for_the_profile_once_per_session(srv, monkeypatch):
    """ADR-015 D7.1: user/habit facts on a session's first message only."""
    sent = _profile_spy(srv, monkeypatch)
    for msg, session in (("first message long enough", "s1"), ("second message, same session", "s1"),
                         ("first message of another session", "s2")):
        asyncio.run(srv._hook_recall(msg, session))
    assert sent == [True, False, True], sent


def test_a_gateway_asks_for_the_profile_on_its_first_pre_turn_only(srv, monkeypatch):
    """A stdio gateway lives as long as its client's session: clients without
    the hook get the profile on their first pre_turn."""
    from gray_matter.registry import ServerEntry
    neuron = ServerEntry(name="neuron", tool_names=["pre_turn"], socket_path="", pid=0)
    monkeypatch.setattr(srv._registry, "find_server_by_tool",
                        lambda tool: neuron if tool == "pre_turn" else None)
    monkeypatch.setattr(srv, "_PROFILE_SENT", False)
    sent = _profile_spy(srv, monkeypatch)
    args = {"topic": "flash"}
    for _ in range(2):
        asyncio.run(srv.call_tool("pre_turn", args))
    assert sent == [True, False], sent
    assert "profile" not in args, "the caller's arguments are not mutated"


def _ctx_spy(srv, monkeypatch, replies):
    excluded, fake = [], srv._call_server_async

    async def spy(server, tool, args):
        if tool == "pre_turn":
            excluded.append(list(args.get("exclude") or []))
            return replies.pop(0)
        return await fake(server, tool, args)
    monkeypatch.setattr(srv, "_call_server_async", spy)
    return excluded


def test_the_hook_does_not_bring_back_a_fact_of_this_session(srv, monkeypatch):
    """ADR-015 D7: the ids a pre_turn showed travel as `exclude` on the next one."""
    excluded = _ctx_spy(srv, monkeypatch, ["facts: [habit] no push (push) #0a1b2c3d", "", ""])
    for msg, session in (("first message long enough", "s1"), ("second message, same session", "s1"),
                         ("first message of another session", "s2")):
        asyncio.run(srv._hook_recall(msg, session))
    assert excluded[1] == ["0a1b2c3d"] and "0a1b2c3d" not in excluded[2], excluded


def test_a_gateway_does_not_bring_back_a_fact_of_its_session(srv, monkeypatch):
    from gray_matter.registry import ServerEntry
    neuron = ServerEntry(name="neuron", tool_names=["pre_turn"], socket_path="", pid=0)
    monkeypatch.setattr(srv._registry, "find_server_by_tool",
                        lambda tool: neuron if tool == "pre_turn" else None)
    monkeypatch.setattr(srv, "_flashed", set())
    excluded = _ctx_spy(srv, monkeypatch, ["facts: [fix] a fix (wal) #00ff00ff", ""])
    for _ in range(2):
        asyncio.run(srv.call_tool("pre_turn", {"topic": "flash"}))
    assert excluded[0] == [] and "00ff00ff" in excluded[1], excluded   # the flash's id joins too



def test_the_hook_decides_profile_and_exclusions(srv, monkeypatch):
    """The hook reads them from the transcript; the daemon follows it, even for
    a session it has never seen (it restarted) or one it saw (a recall the hook
    gave up on, cold, 2026-11-08)."""
    seen, fake = [], srv._call_server_async

    async def spy(server, tool, args):
        if tool == "pre_turn":
            seen.append((args.get("profile"), list(args.get("exclude") or [])))
        return await fake(server, tool, args)
    monkeypatch.setattr(srv, "_call_server_async", spy)
    asyncio.run(srv._hook_recall("first message long enough", "s1", profile=False, exclude=["0a1b2c3d"]))
    asyncio.run(srv._hook_recall("second message long enough", "s1", profile=True))
    assert seen[0] == (False, ["0a1b2c3d"]) and seen[1][0] is True, seen


def test_the_hook_reads_what_it_injected_from_the_transcript(tmp_path):
    from gray_matter import memhook as mh
    ctx = "[neuron] ...\\nprofile: [habit] no push #0a1b2c3d | facts: [fix] wal (wal) #00ff00ff"
    lines = [{"type": "attachment", "attachment": {"type": "hook_additional_context",
                                                   "content": [ctx]}},
             {"type": "user", "message": {"role": "user", "content": "profile: [habit] typed #11111111"}}]
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    assert mh.session_memory(str(t)) == (True, ["00ff00ff", "0a1b2c3d"])
    assert mh.session_memory(str(tmp_path / "missing.jsonl")) == (False, [])


def test_pulse_reads_facts_like_pre_turn_and_mints_no_bridge(srv, monkeypatch):
    """ADR-016 D1/D4: pulse used get_context (names, zero facts) and minted a
    bridge from every flash that met a KB hit."""
    import gray_matter.bridges as br

    async def no_bridges(*_a):
        return []
    monkeypatch.setattr(srv, "_bridge_blocks", no_bridges)
    monkeypatch.setattr(br, "add_bridge", lambda *a, **k: pytest.fail("a flash minted a bridge"))
    monkeypatch.setattr(srv, "_flashed", set())
    out = asyncio.run(srv.call_tool("gray_matter_pulse", {"topic": "flash pulse unique topic"}))[0].text
    assert "pre_turn" in srv._calls and "get_context" not in srv._calls, srv._calls
    assert "knowledge_neighbors" not in srv._calls, srv._calls
    assert out.startswith("[neuron] CTX") and "⚡ Flash: [idea]" in out, out


def test_a_bridge_needs_a_neurag_node_with_that_exact_name(srv, monkeypatch):
    """ADR-016 D4: bridges were born pointing at the question's text."""
    import gray_matter.bridges as br
    made = []
    monkeypatch.setattr(br, "add_bridge", lambda n, r, why="": made.append((n, r)) or True)

    async def kb(server, tool, args):
        name = {"install guide": "Install Guide", "install": "Install Guide"}.get(args["query"].lower())
        return json.dumps({"node": {"name": name} if name else None, "neighbors": []})
    monkeypatch.setattr(srv, "_call_server_async", kb)
    bridge = lambda node: asyncio.run(srv.call_tool("gray_matter_bridge", {  # noqa: E731
        "neuron_concept": "venv", "neurag_node": node}))[0].text
    assert bridge("install guide") == "Bridge saved." and made == [("venv", "Install Guide")]
    assert "Did you mean 'Install Guide'" in bridge("install")
    assert "no NeuRAG node named 'come installo?'" in bridge("come installo?")
    assert len(made) == 1


def test_a_claude_code_gateway_leaves_the_profile_to_the_hook(srv, monkeypatch, tmp_path):
    """Seen live 2026-11-08: Claude Code got the profile from the hook AND from
    its gateway's first pre_turn."""
    from types import SimpleNamespace as NS
    from gray_matter.registry import ServerEntry
    neuron = ServerEntry(name="neuron", tool_names=["pre_turn"], socket_path="", pid=0)
    monkeypatch.setattr(srv._registry, "find_server_by_tool",
                        lambda tool: neuron if tool == "pre_turn" else None)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text('{"hooks": "gm_memhook.py recall"}')
    monkeypatch.setenv("USERPROFILE", str(tmp_path)); monkeypatch.setenv("HOME", str(tmp_path))
    for client, expect in (("claude-code", False), ("cursor", True)):
        ctx = NS(session=NS(client_params=NS(clientInfo=NS(name=client))))
        monkeypatch.setattr(type(srv.app), "request_context", property(lambda self, c=ctx: c))
        monkeypatch.setattr(srv, "_PROFILE_SENT", False)
        sent = _profile_spy(srv, monkeypatch)
        asyncio.run(srv.call_tool("pre_turn", {"topic": "flash"}))
        assert sent == [expect], (client, sent)


def test_the_first_message_has_room_for_the_profile_too(srv, monkeypatch):
    """Live 2026-11-08: a 600-char profile and the 1200-char hook budget left
    out 2 of the 4 user/habit facts. The first message gets the profile's room
    on top; later ones the usual budget."""
    from gray_matter import memhook as mh
    long_ctx = "[neuron] ...\nprofile: " + "p" * 900 + " | facts: " + "f" * 900

    async def fake(server, tool, args):
        return long_ctx if tool == "pre_turn" else ""
    monkeypatch.setattr(srv, "_call_server_async", fake)
    first = asyncio.run(srv._hook_recall("first message long enough", "s1", profile=True))
    later = asyncio.run(srv._hook_recall("second message long enough", "s1", profile=False))
    assert mh.BUDGET < len(first) <= mh.BUDGET + mh.PROFILE_BUDGET, len(first)
    assert len(later) <= mh.BUDGET, len(later)
    assert len(mh.fit("x" * 3000, mh.BUDGET + mh.PROFILE_BUDGET)) == mh.BUDGET + mh.PROFILE_BUDGET
