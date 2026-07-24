"""Tests for node_links: schema, upsert, get, graph."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph


def _kg():
    return KnowledgeGraph(pathlib.Path(":memory:"))


def test_schema_creates_links_table():
    kg = _kg()
    tables = [r[0] for r in kg._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "node_links" in tables
    kg.close()


def test_upsert_link_basic():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["x"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["y"])
    kg.upsert_link(a, b, "tag_overlap", 0.5, "shared: x")
    links = kg.get_links(a)
    assert len(links) == 1
    assert links[0]["target_id"] == b
    assert links[0]["other_name"] == "B"
    assert links[0]["direction"] == "out"
    assert links[0]["weight"] == 0.5
    assert links[0]["evidence"] == "shared: x"
    kg.close()


def test_upsert_link_idempotent():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "tag_overlap", 0.3)
    kg.upsert_link(a, b, "tag_overlap", 0.7, "updated")
    links = kg.get_links(a)
    assert len(links) == 1
    assert links[0]["weight"] == 0.7
    assert links[0]["evidence"] == "updated"
    kg.close()


def test_upsert_self_link_ignored():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    kg.upsert_link(a, a, "tag_overlap")
    assert kg.link_count() == 0
    kg.close()


def test_get_links_bidirectional():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "cross_ref")
    # get_links from B should see incoming link from A
    links_b = kg.get_links(b)
    assert len(links_b) == 1
    assert links_b[0]["source_id"] == a
    assert links_b[0]["other_name"] == "A"
    assert links_b[0]["direction"] == "in"
    kg.close()


def test_get_links_filtered_by_type():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    c = kg.add_node("C", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "tag_overlap")
    kg.upsert_link(a, c, "cross_ref")
    tags = kg.get_links(a, link_type="tag_overlap")
    assert len(tags) == 1
    assert tags[0]["other_name"] == "B"
    # incoming filter from C
    tags_c = kg.get_links(c, link_type="cross_ref")
    assert len(tags_c) == 1
    assert tags_c[0]["other_name"] == "A"
    assert tags_c[0]["direction"] == "in"
    kg.close()


def test_get_link_graph():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "tag_overlap", 0.8, "evidence")
    graph = kg.get_link_graph()
    assert len(graph) == 1
    assert graph[0]["source_name"] == "A"
    assert graph[0]["target_name"] == "B"
    assert graph[0]["weight"] == 0.8
    kg.close()


def test_link_count():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    c = kg.add_node("C", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "tag_overlap")
    kg.upsert_link(a, c, "cross_ref")
    kg.upsert_link(b, c, "semantic")
    assert kg.link_count() == 3
    kg.close()


def test_cascade_delete_node():
    """Deleting a node removes its links — via delete_node(), NOT raw DELETE:
    pyturso 0.6.1 stack-overflows on the FK cascade trigger (audit 2026-07-20),
    so delete_node() does explicit bottom-up deletes instead."""
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "tag_overlap")
    assert kg.link_count() == 1
    assert kg.delete_node(b) == 1
    assert kg.link_count() == 0
    assert kg.get_node(b) is None and kg.get_node(a) is not None
    kg.close()


def test_delete_node_subtree():
    """delete_node removes the whole subtree, leaves the rest untouched."""
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "specialization", parent_id=a)
    c = kg.add_node("C", "specialization", parent_id=b)
    other = kg.add_node("Other", "fundamental", parent_id=0)
    kg.add_chunk(b, "chunk on b")
    kg.upsert_link(c, other, "tag_overlap")
    removed = kg.delete_node(a)
    assert removed == 3                                   # a + b + c
    assert kg.get_node(other) is not None
    assert kg.link_count() == 0                           # link di c rimosso
    assert kg.delete_node(99999) == 0
    kg.close()


def test_status_includes_links():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "tag_overlap")
    s = kg.status()
    assert s["links"] == 1
    kg.close()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---------- Fase 2: tag-based linking ----------

def test_build_tag_links_basic():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["java", "spring"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["java", "kotlin"])
    c = kg.add_node("C", "fundamental", parent_id=0, tags=["python"])
    added = kg.build_tag_links()
    assert added == 1  # only A-B share "java"
    links = kg.get_links(a)
    assert len(links) == 1
    assert links[0]["other_name"] == "B"
    assert links[0]["weight"] > 0
    assert "java" in links[0]["evidence"]
    kg.close()


def test_build_tag_links_no_overlap():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["java"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["python"])
    added = kg.build_tag_links()
    assert added == 0
    assert kg.link_count() == 0
    kg.close()


def test_build_tag_links_multiple_shared():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["a", "b", "c"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["b", "c", "d"])
    added = kg.build_tag_links()
    assert added == 1
    links = kg.get_links(a)
    assert links[0]["weight"] == 2 / 4  # {b,c} / {a,b,c,d}
    kg.close()


def test_build_tag_links_empty_tags():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=[])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=[])
    added = kg.build_tag_links()
    assert added == 0
    kg.close()


def test_build_tag_links_idempotent():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["x"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["x"])
    kg.build_tag_links()
    count1 = kg.link_count()
    kg.build_tag_links()
    count2 = kg.link_count()
    assert count1 == count2  # no duplicates


# ---------- Fase 3: cross-ref linking ----------

def test_build_crossref_links_basic():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.add_chunk(a, "hello", source="file1.md", section="s1")
    kg.add_chunk(b, "world", source="file1.md", section="s2")
    added = kg.build_crossref_links()
    assert added == 1
    links = kg.get_links(a)
    assert len(links) == 1
    assert links[0]["other_name"] == "B"
    assert links[0]["weight"] > 0
    kg.close()


def test_build_crossref_links_no_overlap():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.add_chunk(a, "a", source="file1.md")
    kg.add_chunk(b, "b", source="file2.md")
    added = kg.build_crossref_links()
    assert added == 0
    kg.close()


def test_build_crossref_links_same_node_skipped():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    kg.add_chunk(a, "a", source="file1.md")
    kg.add_chunk(a, "b", source="file1.md")
    added = kg.build_crossref_links()
    assert added == 0  # same node, no link
    kg.close()


def test_build_crossref_links_idempotent():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.add_chunk(a, "x", source="file1.md")
    kg.add_chunk(b, "y", source="file1.md")
    kg.build_crossref_links()
    c1 = kg.link_count()
    kg.build_crossref_links()
    c2 = kg.link_count()
    assert c1 == c2


# ---------- Fase 4: rebuild + search_with_links ----------

def test_rebuild_links():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["java"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["java"])
    kg.add_chunk(a, "x", source="file1.md")
    kg.add_chunk(b, "y", source="file1.md")
    result = kg.rebuild_links()
    assert result["tag_overlap"] >= 1
    assert result["cross_ref"] >= 1
    assert result["total"] == result["tag_overlap"] + result["cross_ref"]
    # Rebuild again — should not duplicate
    result2 = kg.rebuild_links()
    assert result2["total"] == result["total"]
    kg.close()


def test_search_with_links_enriches():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["java"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["java"])
    c = kg.add_node("C", "fundamental", parent_id=0, tags=["python"])
    kg.add_chunk(a, "java springs framework", source="file1.md")
    kg.add_chunk(b, "java kotlin coroutines", source="file2.md")
    kg.add_chunk(c, "python fastapi uvicorn", source="file3.md")
    kg.rebuild_links()
    results = kg.search_with_links("java", top_k=3)
    # Tier-agnostic: search_with_links ENRICHES hits with a `links` field (it does
    # not expand with linked nodes). The count is tier-dependent — the lexical
    # tier returns the 2 "java" chunks; the vector tier (fastembed) ranks all 3 by
    # similarity — so assert on the invariant (>=2 + enrichment), not a fixed count.
    assert len(results) >= 2
    # At least one result should have links
    has_links = any(len(r.get("links", [])) > 0 for r in results)
    assert has_links
    kg.close()


def test_search_with_links_single_result():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    kg.add_chunk(a, "unique content xyz", source="file1.md")
    results = kg.search_with_links("unique", top_k=5)
    assert len(results) == 1
    assert results[0].get("links", []) == []
    kg.close()


# ---------- Fase 5: MCP tool integration ----------

def test_link_graph_tool_output():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["x"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["x"])
    kg.upsert_link(a, b, "tag_overlap", 0.75, "shared: x")
    graph = kg.get_link_graph()
    assert len(graph) == 1
    assert graph[0]["source_name"] == "A"
    assert graph[0]["target_name"] == "B"
    assert graph[0]["link_type"] == "tag_overlap"
    assert graph[0]["weight"] == 0.75
    assert graph[0]["evidence"] == "shared: x"
    kg.close()


def test_rebuild_links_full_pipeline():
    """Full pipeline: nodes + chunks + rebuild + verify links."""
    kg = _kg()
    root = kg.add_node("Root", "godnode")
    a = kg.add_node("A", "fundamental", parent_id=root, tags=["web", "api"])
    b = kg.add_node("B", "fundamental", parent_id=root, tags=["api", "rest"])
    c = kg.add_node("C", "fundamental", parent_id=root, tags=["db", "sql"])
    kg.add_chunk(a, "REST API patterns", source="guide.md", section="api")
    kg.add_chunk(b, "HTTP endpoints", source="guide.md", section="http")
    kg.add_chunk(c, "SQL queries", source="db.md", section="queries")
    result = kg.rebuild_links()
    assert result["total"] > 0
    # A and B share tags + same source
    links_a = kg.get_links(a)
    links_b_to_a = [l for l in links_a if l["other_name"] == "B"]
    assert len(links_b_to_a) >= 1
    # C has no tag overlap with A/B
    links_c = kg.get_links(c)
    assert len(links_c) == 0
    kg.close()
