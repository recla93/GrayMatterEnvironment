"""The KB rides pre_turn (2026-09-12), with a vector pointer (2026-11-05).

On a real vault test the knowledge base was indexed, bridged, and consulted
ZERO times: everything that needs the model's initiative beyond
pre_turn/store_turn does not happen. So GM appends ONE KB pointer to the call
that does happen, inside the proactive budget.

The pointer was a SQL name/trigger lookup until 2026-11-05: on five real
messages it named a whole folder every time and minted false bridges. It is a
vector search now, with a threshold, and it mints no bridge.
"""
import asyncio

import pytest


@pytest.fixture
def srv(tmp_path, monkeypatch):
    import importlib

    from gray_matter import bridges
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    importlib.reload(bridges)

    import gray_matter.server as S
    from gray_matter.registry import ServerEntry
    neurag = ServerEntry(name="neurag", tool_names=["knowledge_query"],
                         socket_path="", pid=0)
    monkeypatch.setattr(S._registry, "get_server",
                        lambda name: neurag if name == "neurag" else None)
    monkeypatch.setattr(S, "PROACTIVE_BUDGET", 800)
    S._KB_HINT_SHOWN.clear()
    S._stats["kb_hints"] = 0

    calls: list[tuple[str, str, dict]] = []
    replies = {"cos": "0.61"}

    async def fake_call(server, tool, args):
        calls.append((server, tool, dict(args)))
        if tool == "knowledge_query":
            return ("Top 1 results:\n  [1] D:\\vault\\db\\TURSO.md :: Turso > Embedded replica (2/9)"
                    f"  (cos {replies['cos']})\n")
        raise AssertionError(f"unexpected call {server}.{tool}")
    monkeypatch.setattr(S, "_call_server_async", fake_call)
    S._calls = calls
    S._replies = replies
    return S


def _hint(S, **args):
    return asyncio.run(S._knowledge_hint(args))


def test_a_close_section_yields_one_pointer_and_no_bridge(srv):
    from gray_matter import bridges
    out = _hint(srv, topic="scelta del database", keywords=["latency", "libsql", "wal"])
    assert '📚 KB: "TURSO.md :: Turso > Embedded replica" (cos 0.61)' in out, out
    assert "knowledge_query" in out, "the pointer says how to get the detail"
    assert [c[1] for c in srv._calls] == ["knowledge_query"]
    assert bridges.all_bridges() == [], "a pointer is a hint, a bridge is a claim"
    assert srv._stats["kb_hints"] == 1


def test_below_the_threshold_there_is_no_pointer(srv):
    """The two wrong answers measured on 2026-11-05 sat at cos 0.45-0.46."""
    srv._replies["cos"] = "0.46"
    assert _hint(srv, topic="credenziali turso cloud", keywords=["credenziali"]) == ""
    assert srv._stats["kb_hints"] == 0


def test_a_section_is_pointed_at_once_per_session(srv):
    first = _hint(srv, topic="db", keywords=["turso"])
    again = _hint(srv, topic="db", keywords=["libsql"])
    assert "📚" in first
    assert "📚" not in again, again
    assert srv._stats["kb_hints"] == 1


def test_the_bridges_of_the_topic_ride_along(srv):
    from gray_matter import bridges
    bridges.add_bridge("latency", "Turso", "Turso adds ~2ms per write over sqlite")
    out = _hint(srv, topic="latency del database", keywords=["latency"])
    assert "🔗 latency ↔ Turso — Turso adds ~2ms" in out, out


def test_without_neurag_the_pre_turn_is_untouched(srv, monkeypatch):
    monkeypatch.setattr(srv._registry, "get_server", lambda name: None)
    assert _hint(srv, topic="x", keywords=["turso"]) == ""
    assert srv._calls == []


def test_a_zero_proactive_budget_disables_it(srv, monkeypatch):
    monkeypatch.setattr(srv, "PROACTIVE_BUDGET", 0)
    assert _hint(srv, topic="x", keywords=["turso"]) == ""
    assert srv._calls == []


def test_pre_turn_passthrough_carries_the_hint(srv, monkeypatch):
    """The wiring: call_tool('pre_turn') returns Neuron's text + the KB block."""
    from gray_matter.registry import ServerEntry
    neuron = ServerEntry(name="neuron", tool_names=["pre_turn"], socket_path="", pid=0)
    monkeypatch.setattr(srv._registry, "find_server_by_tool",
                        lambda tool: neuron if tool == "pre_turn" else None)
    real = srv._call_server_async

    async def routed(server, tool, args):
        if server == "neuron":
            return "[neuron] ctx=ai turn=1"
        return await real(server, tool, args)
    monkeypatch.setattr(srv, "_call_server_async", routed)

    async def no_net(*a, **k):
        return ""
    monkeypatch.setattr(srv, "_safety_net_note", no_net)

    out = asyncio.run(srv.call_tool("pre_turn", {"topic": "db", "keywords": ["turso"]}))
    text = out[0].text
    assert text.startswith("[neuron] ctx=ai turn=1")
    assert '📚 KB: "TURSO.md :: Turso > Embedded replica"' in text
