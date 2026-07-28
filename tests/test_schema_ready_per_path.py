"""A graph must create the schema in EVERY file it saves to.

`_schema_ready` was a bool: "this graph already made a schema somewhere". A
graph warm-started from the seed (or simply saved to a second context) carried
it into a brand-new file, skipped creation, and died on
`SELECT value FROM meta` — "no such table: meta" against a 0-byte DB. Observed
live: switching to a fresh context made every store_turn fail, so nothing in
that context ever persisted.
"""
from __future__ import annotations

import os
import sys

from tests._mockdeps import install_mock_deps, unpoison_turso
install_mock_deps()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import sqlite3                                  # noqa: E402

from neuron.models import Graph, Node           # noqa: E402
unpoison_turso()


def _graph(keyword: str) -> Graph:
    g = Graph()
    g.add_node(Node(keyword=keyword, turn=1, topic="t",
                    domain="d", sentiment="neutral"))
    return g


def _tables(path) -> set[str]:
    c = sqlite3.connect(str(path))
    try:
        return {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def test_second_file_gets_its_own_schema(tmp_path):
    """The regression: same graph object, two context files."""
    g = _graph("alpha")
    first = tmp_path / "graph_default.db"
    g.save_sqlite(str(first), context="default")
    assert "meta" in _tables(first)

    second = tmp_path / "graph_software engineering.db"
    g._dirty = True                              # a new turn made it dirty again
    g.save_sqlite(str(second), context="software engineering")

    assert "meta" in _tables(second), "schema skipped — the 0-byte-DB bug"
    assert "nodes" in _tables(second)


def test_saving_twice_to_the_same_file_still_works(tmp_path):
    g = _graph("beta")
    path = tmp_path / "graph_default.db"
    g.save_sqlite(str(path), context="default")
    g._dirty = True
    g.save_sqlite(str(path), context="default")   # idempotent, no raise
    assert "meta" in _tables(path)


def test_schema_ready_records_the_path(tmp_path):
    g = _graph("gamma")
    assert g._schema_ready == ""
    path = tmp_path / "graph_default.db"
    g.save_sqlite(str(path), context="default")
    assert g._schema_ready == str(path)


def test_self_heals_when_schema_ready_flag_is_stale(tmp_path):
    """Live bug (2026-07-28): `_schema_ready` correctly names this path (an
    earlier save on it succeeded), but the file underneath it got reset —
    observed as a 0-byte .db with an equally 0-byte -wal, meta.embed_model
    query dying on 'no such table: meta'. The flag said "schema already
    exists here", the file disagreed. save_sqlite must recover, not crash."""
    g = _graph("delta")
    path = tmp_path / "graph_default.db"
    g.save_sqlite(str(path), context="default")
    assert g._schema_ready == str(path)

    path.write_bytes(b"")                      # simulate the reset file
    wal = tmp_path / (path.name + "-wal")
    if wal.exists():
        wal.write_bytes(b"")

    g._dirty = True
    g.save_sqlite(str(path), context="default")   # must not raise
    assert "meta" in _tables(path)
    assert "nodes" in _tables(path)
