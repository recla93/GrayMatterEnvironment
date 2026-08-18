"""D3 — knowledge_neighbors: BFS strutturato su parent/children/links."""
import json

import pytest

from neurag.db import KnowledgeGraph


@pytest.fixture
def kg(tmp_path):
    kg = KnowledgeGraph(db_path=tmp_path / "k.db")
    ids = {}
    ids["root"] = kg.add_node(name="Root", node_type="godnode")
    ids["java"] = kg.add_node(name="Java", node_type="fundamental", parent_id=ids["root"])
    ids["spring"] = kg.add_node(name="Spring_Boot", node_type="specialization",
                                parent_id=ids["java"], triggers=["spring boot"])
    ids["kotlin"] = kg.add_node(name="Kotlin", node_type="specialization", parent_id=ids["java"])
    kg.add_node(name="Python", node_type="fundamental", parent_id=ids["root"])
    kg.upsert_link(ids["spring"], ids["kotlin"], link_type="tag_overlap",
                   weight=0.5, evidence="jvm")
    return kg, ids


def test_depth1_parent_and_link(kg):
    g, ids = kg
    n = g.get_neighbors(ids["spring"], depth=1, limit=10)
    rel = {x["name"]: x["relation"] for x in n}
    assert set(rel) == {"Java", "Kotlin"}
    assert rel["Java"] == "parent" and rel["Kotlin"] == "link:tag_overlap"


def test_depth2_reaches_grandparent_with_distance(kg):
    g, ids = kg
    n = g.get_neighbors(ids["spring"], depth=2, limit=10)
    dist = {x["name"]: x["distance"] for x in n}
    assert dist["Java"] == 1 and dist["Root"] == 2


def test_limit_and_missing_node(kg):
    g, ids = kg
    assert len(g.get_neighbors(ids["spring"], depth=2, limit=1)) == 1
    assert g.get_neighbors(999999) == []


def test_tool_returns_structured_json(kg, monkeypatch):
    pytest.importorskip("mcp")
    import asyncio
    import neurag.server as srv
    g, _ = kg
    monkeypatch.setattr(srv, "_get_db", lambda: g)
    out = asyncio.run(srv.call_tool("knowledge_neighbors",
                                    {"query": "spring boot", "depth": 2}))
    data = json.loads(out[0].text)
    assert data["node"]["name"] == "Spring_Boot"
    assert any(x["name"] == "Root" for x in data["neighbors"])
    # query senza match → JSON vuoto, mai errore testuale
    out = asyncio.run(srv.call_tool("knowledge_neighbors", {"query": "zzz"}))
    assert json.loads(out[0].text) == {"node": None, "neighbors": []}
