"""A tool the diet hides from list_tools still routes through the gateway by
name: the worker dispatches by name and answers itself when a tool really does
not exist. Without this, `NEURON_TOOLS=all` on the client side (or a client with
a cached tool list) would get "not found" for tools that work."""
import asyncio

import pytest


@pytest.fixture
def gm(monkeypatch):
    import gray_matter.server as S
    from gray_matter.registry import ServerEntry
    entries = {
        "neuron": ServerEntry(name="neuron", tool_names=["pre_turn"], socket_path="", pid=0),
        "neurag": ServerEntry(name="neurag", tool_names=["knowledge_query"], socket_path="", pid=0),
    }
    monkeypatch.setattr(S._registry, "get_server", lambda name: entries.get(name))
    monkeypatch.setattr(S._registry, "find_server_by_tool",
                        lambda tool: next((e for e in entries.values() if tool in e.tool_names), None))
    routed = []

    async def fake_call(server, tool, args):
        routed.append((server, tool))
        return "ok"
    monkeypatch.setattr(S, "_call_server_async", fake_call)
    S._routed = routed
    return S


def _call(S, name):
    return asyncio.run(S.call_tool(name, {}))


def test_an_unannounced_tool_routes_by_name_prefix(gm):
    _call(gm, "knowledge_neighbors")     # hidden by NeuRAG's diet
    _call(gm, "consolidate")             # hidden by Neuron's diet
    # (consolidate makes side-calls of its own; membership is what matters)
    assert {("neurag", "knowledge_neighbors"), ("neuron", "consolidate")} <= set(gm._routed)


def test_an_announced_tool_still_routes_by_the_index(gm):
    _call(gm, "knowledge_query")
    assert gm._routed[-1] == ("neurag", "knowledge_query")
