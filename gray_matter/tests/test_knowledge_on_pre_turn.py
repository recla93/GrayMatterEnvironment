"""The KB rides pre_turn (2026-09-12).

On a real vault test the knowledge base was indexed, bridged, and consulted
ZERO times: everything that needs the model's initiative beyond
pre_turn/store_turn does not happen. So GM appends a KB pointer to the one
call that does happen — gated by a SQL-only name/trigger lookup, never by a
vector search, and inside the proactive budget.
"""
import asyncio
import json

import pytest


@pytest.fixture
def srv(tmp_path, monkeypatch):
    import importlib

    from gray_matter import bridges
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    importlib.reload(bridges)

    import gray_matter.server as S
    from gray_matter.registry import ServerEntry
    neurag = ServerEntry(name="neurag", tool_names=["knowledge_neighbors"],
                         socket_path="", pid=0)
    monkeypatch.setattr(S._registry, "get_server",
                        lambda name: neurag if name == "neurag" else None)
    monkeypatch.setattr(S, "PROACTIVE_BUDGET", 800)
    S._KB_HINT_CACHE.clear()
    S._stats["kb_hints"] = 0

    calls: list[tuple[str, str, dict]] = []

    async def fake_call(server, tool, args):
        calls.append((server, tool, dict(args)))
        # "turso" is the node's own name; "libsql" is a TRIGGER that resolves to it
        if tool == "knowledge_neighbors" and args["query"].lower() in ("turso", "libsql"):
            return json.dumps({"node": {"name": "Turso", "path": "db/turso"},
                               "tags": ["sqlite", "cloud"],
                               "neighbors": [{"name": "libsql"}, {"name": "embedded replica"}]})
        if tool == "knowledge_neighbors":
            return json.dumps({"node": None, "neighbors": []})
        raise AssertionError(f"unexpected call {server}.{tool}")
    monkeypatch.setattr(S, "_call_server_async", fake_call)
    S._calls = calls
    return S


def _hint(S, **args):
    return asyncio.run(S._knowledge_hint(args))


def test_a_keyword_the_kb_resolves_yields_one_pointer_and_a_bridge(srv):
    out = _hint(srv, topic="scelta del database", keywords=["latency", "libsql", "wal"])
    assert '📚 KB knows "Turso" (db/turso)' in out, out
    assert "near: libsql, embedded replica" in out
    assert 'knowledge_query("Turso")' in out, "the pointer says how to get the detail"
    # the detail itself is NOT fetched: no vector search on the pre_turn path
    assert {c[1] for c in srv._calls} == {"knowledge_neighbors"}
    # the resolved keyword is a bridge now: Neuron concept <-> KB node
    from gray_matter import bridges
    assert [(b["neuron"], b["neurag"]) for b in bridges.all_bridges()] == [("libsql", "Turso")]
    assert srv._stats["kb_hints"] == 1


def test_a_keyword_equal_to_the_node_name_is_a_pointer_but_not_a_bridge(srv):
    """The store refuses same-name bridges (it would link a word to itself);
    the pointer still comes, and bridges_for matches that word either way."""
    from gray_matter import bridges
    out = _hint(srv, topic="db", keywords=["turso"])
    assert '📚 KB knows "Turso"' in out
    assert bridges.all_bridges() == []


def test_no_match_means_no_text_and_no_vector_search(srv):
    out = _hint(srv, topic="pranzo con Ada", keywords=["pranzo", "ada"])
    assert out == ""
    assert {c[1] for c in srv._calls} == {"knowledge_neighbors"}


def test_misses_are_cached_per_keyword_for_the_session(srv):
    _hint(srv, topic="t", keywords=["pranzo"])
    n = len(srv._calls)
    _hint(srv, topic="t", keywords=["pranzo"])
    assert len(srv._calls) == n, "a known miss costs nothing the second time"


def test_a_cached_hit_does_not_reinforce_the_bridge_every_turn(srv):
    from gray_matter import bridges
    for _ in range(3):
        _hint(srv, topic="db", keywords=["libsql"])
    (b,) = [b for b in bridges.all_bridges() if b["neuron"] == "libsql"]
    # minted once (weight 1); only a bridges_for() surfacing reinforces it, and
    # "db" matches neither endpoint nor the tags here
    assert b["weight"] == 1, b


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
    assert '📚 KB knows "Turso"' in text
