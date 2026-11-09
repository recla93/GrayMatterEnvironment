"""knowledge_link_graph(format="json"): what the GM Graphs panel draws.

The text form carries no layer and no ids, so the panel could not dim an
archived node nor tell two nodes with the same name apart.
"""
import asyncio
import json

import pytest

from neurag.db import KnowledgeGraph


def test_json_form_has_every_node_once_with_its_layer_and_the_links(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    import neurag.server as srv
    g = KnowledgeGraph(db_path=tmp_path / "k.db")
    root = g.add_node(name="Root", node_type="godnode")
    a = g.add_node(name="alpha", node_type="fundamental", parent_id=root, tags=["x", "y"])
    b = g.add_node(name="beta", node_type="fundamental", parent_id=root, tags=["x", "y"])
    g.rebuild_links()
    g.archive(b)
    monkeypatch.setattr(srv, "_get_db", lambda: g)
    out = json.loads(asyncio.run(srv.call_tool("knowledge_link_graph", {"format": "json"}))[0].text)

    ids = [n["id"] for n in out["nodes"]]
    assert len(ids) == len(set(ids)) and {root, a, b} <= set(ids)
    layer = {n["name"]: n["layer"] for n in out["nodes"]}
    assert layer["beta"] > 2 and layer["alpha"] == 2
    assert {(l["source_id"], l["target_id"]) for l in out["links"]} & {(a, b), (b, a)}
    # the text form is unchanged for the model
    text = asyncio.run(srv.call_tool("knowledge_link_graph", {}))[0].text
    assert "-->" in text
