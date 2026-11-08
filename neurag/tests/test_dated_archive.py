"""ADR-017 D1: knowledge is dated; history is an archive, not noise.

Live 2026-11-08: old documents in the user's language beat the current ones
(27% of the hits came from work/history). Deleting them was the shortcut; the
fix is a date on every chunk, the newer winning a near tie, and history moved
to the archive layer, reachable on request.
"""
import asyncio
import json
import os
import time

import pytest

from neurag import db as D
from neurag.db import KnowledgeGraph


def test_the_document_date_comes_from_name_then_header_then_mtime(tmp_path):
    named = tmp_path / "STATO-LAVORI-2026-11-08.md"
    named.write_text("# x\n", encoding="utf-8")
    header = tmp_path / "CINQUE.md"
    header.write_text("---\ncreated: 2026-11-03\n---\n# y\n", encoding="utf-8")
    plain = tmp_path / "plain.md"
    plain.write_text("# z\n", encoding="utf-8")
    os.utime(plain, (0, time.mktime((2025, 1, 2, 12, 0, 0, 0, 0, -1))))
    assert D.doc_date(named) == "2026-11-08"
    assert D.doc_date(header) == "2026-11-03"
    assert D.doc_date(plain) == "2025-01-02"


def test_recency_halves_yearly_and_an_undated_chunk_is_neutral():
    assert D.recency("2026-11-08", today="2026-11-08") == 1.0
    assert abs(D.recency("2025-11-08", today="2026-11-08") - 0.5) < 0.01
    assert D.recency(None) == 0.0 and D.recency("not a date") == 0.0


@pytest.fixture
def kg(tmp_path):
    g = KnowledgeGraph(db_path=tmp_path / "k.db")
    root = g.add_node(name="Root", node_type="godnode")
    ids = {}
    for name, day in (("old", "2024-01-01"), ("new", "2026-11-01")):
        ids[name] = g.add_node(name=name, node_type="fundamental", parent_id=root)
        f = tmp_path / f"{name}-{day}.md"
        f.write_text("# Release\nhow to cut a release of the suite, step by step\n",
                     encoding="utf-8")
        g.index_into_node(f, ids[name])
    return g, ids


def test_ingest_dates_the_chunks_and_the_newer_wins_a_tie(kg):
    g, ids = kg
    dates = {r[0] for r in g._conn.execute("SELECT doc_date FROM chunks").fetchall()}
    assert dates == {"2024-01-01", "2026-11-01"}
    top = g.search("how to cut a release", top_n=2, touch=False)
    assert top[0]["node_id"] == ids["new"], [(r["node_id"], r.get("doc_date")) for r in top]


def test_an_archived_node_leaves_the_default_search_and_comes_back_on_request(kg, monkeypatch):
    pytest.importorskip("mcp")
    import neurag.server as srv
    g, ids = kg
    assert g.archive(ids["old"]) == 1
    assert {r["node_id"] for r in g.search("release", top_n=5, touch=False)} == {ids["new"]}
    monkeypatch.setattr(srv, "_get_db", lambda: g)
    call = lambda args: asyncio.run(srv.call_tool("knowledge_query", args))[0].text  # noqa: E731
    out = call({"query": "how to cut a release", "archive": True})
    assert "[2024-01-01] [archive]" in out and "[2026-11-01]" in out, out
    assert "2024-01-01" not in call({"query": "how to cut a release"})
    g.archive(ids["old"], restore=True)
    assert len({r["node_id"] for r in g.search("release", top_n=5, touch=False)}) == 2
