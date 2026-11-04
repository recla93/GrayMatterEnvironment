"""A file that left the folder stops answering, and is not deleted (I5).

Re-ingesting a folder replaced the chunks of the files still there and never
looked at the ones that left: after a docs cleanup the vault kept quoting the
retired documents. Their chunks now move to a parked node — out of the default
scan, still returned by `recall`, replaced if the file comes back.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph  # noqa: E402
from neurag.ingest import auto_ingest  # noqa: E402

RETIRED = "# Ritirato\n\n" + "il compendio zafferano descrive il sistema. " * 10
KEPT = "# Vivo\n\n" + "la guida corrente spiega l'installazione. " * 10


@pytest.fixture
def kg(tmp_path):
    g = KnowledgeGraph(tmp_path / "k.db")
    yield g
    g.close()


@pytest.fixture
def docs(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "vecchio.md").write_text(RETIRED, encoding="utf-8")
    (d / "vivo.md").write_text(KEPT, encoding="utf-8")
    return d


def _sources(hits):
    return {pathlib.Path(h["source"]).name for h in hits}


def test_a_vanished_file_leaves_the_default_search(kg, docs):
    auto_ingest(kg, docs)
    assert "vecchio.md" in _sources(kg.search("compendio zafferano"))

    (docs / "vecchio.md").unlink()
    rep = auto_ingest(kg, docs)

    assert rep["parked"] > 0
    assert "vecchio.md" not in _sources(kg.search("compendio zafferano"))
    assert "vivo.md" in _sources(kg.search("guida corrente installazione"))


def test_recall_still_returns_it_word_for_word(kg, docs):
    auto_ingest(kg, docs)
    before = {h["text"] for h in kg.search("compendio zafferano", deep=True)
              if h["source"].endswith("vecchio.md")}
    (docs / "vecchio.md").unlink()
    auto_ingest(kg, docs)
    after = {h["text"] for h in kg.recall("compendio zafferano")
             if h["source"].endswith("vecchio.md")}
    assert before and after == before


def test_a_file_that_comes_back_replaces_its_parked_copy(kg, docs):
    auto_ingest(kg, docs)
    old = docs / "vecchio.md"
    old.unlink()
    auto_ingest(kg, docs)
    old.write_text(RETIRED, encoding="utf-8")
    auto_ingest(kg, docs)
    n = kg._conn.execute("SELECT COUNT(*) FROM chunks WHERE source = ?",
                         (str(old.resolve()),)).fetchone()[0]
    assert n > 0
    assert "vecchio.md" in _sources(kg.search("compendio zafferano"))
    retired = kg.get_node_by_name(kg.RETIRED_NODE)
    assert kg._conn.execute("SELECT COUNT(*) FROM chunks WHERE node_id = ?",
                            (retired["id"],)).fetchone()[0] == 0


def test_only_files_under_the_ingested_root_are_touched(kg, tmp_path, docs):
    other = tmp_path / "altro"
    other.mkdir()
    (other / "fuori.md").write_text(RETIRED, encoding="utf-8")
    auto_ingest(kg, other)
    (other / "fuori.md").unlink()
    rep = auto_ingest(kg, docs)                 # a different root
    assert rep["parked"] == 0
