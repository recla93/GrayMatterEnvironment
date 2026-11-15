"""A re-ingest touches only what changed (2026-11-15).

Every `neurag ingest` re-chunked and re-embedded every file of the tree, so
refreshing a vault after editing one note cost as much as building it. Now a
source whose bytes, model, chunk ceiling and chunker are all unchanged is kept.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph  # noqa: E402
from neurag.ingest import auto_ingest  # noqa: E402


@pytest.fixture
def kg(tmp_path):
    g = KnowledgeGraph(tmp_path / "k.db")
    yield g
    g.close()


def _ids(kg):
    return [r[0] for r in kg._conn.execute("SELECT id FROM chunks ORDER BY id")]


def _tree(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("# A\n\n" + "alpha content worth keeping. " * 10, encoding="utf-8")
    (root / "b.md").write_text("# B\n\n" + "beta content worth keeping. " * 10, encoding="utf-8")
    return root


def test_unchanged_tree_keeps_every_chunk(kg, tmp_path):
    root = _tree(tmp_path)
    first = auto_ingest(kg, root)
    ids = _ids(kg)
    again = auto_ingest(kg, root)
    assert _ids(kg) == ids, "an unchanged file was re-chunked"
    assert again["unchanged"] == again["files"] == 2
    assert again["chunks"] == first["chunks"]


def test_an_edited_file_is_reindexed_alone(kg, tmp_path):
    root = _tree(tmp_path)
    auto_ingest(kg, root)
    b_ids = [r[0] for r in kg._conn.execute(
        "SELECT id FROM chunks WHERE source LIKE '%b.md' ORDER BY id")]
    (root / "a.md").write_text("# A\n\nnew alpha text about gamma rays. " * 3, encoding="utf-8")
    rep = auto_ingest(kg, root)
    assert rep["unchanged"] == 1
    assert [r[0] for r in kg._conn.execute(
        "SELECT id FROM chunks WHERE source LIKE '%b.md' ORDER BY id")] == b_ids
    assert kg.search("gamma rays"), "the edited text is not searchable"


def test_hash_follows_the_chunk_ceiling(kg, tmp_path):
    p = _tree(tmp_path) / "a.md"
    h = kg._source_hash(p)
    kg._max_chunk_chars += 1
    assert kg._source_hash(p) != h, "a new ceiling must re-chunk the file"
