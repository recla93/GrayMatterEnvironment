"""Work history is typed 'storia' and loses a near tie (phase 2, 2026-11-15).

CHANGELOG/HANDOFF describe what happened, not how things are; on the bench a
HANDOFF ranked above the real answer in 3 of 11 misses.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph, doc_type  # noqa: E402
from neurag.ingest import auto_ingest  # noqa: E402


def test_type_from_name_folder_and_frontmatter(tmp_path):
    (tmp_path / "history").mkdir()
    cases = {
        "CHANGELOG.md": ("# Changelog\n", "storia"),
        "HANDOFF-2026-11-08.md": ("# Handoff\n", "storia"),
        "history/AUDIT.md": ("# Audit\n", "storia"),
        "diario.md": ("---\ntype: log\n---\n# x\n", "storia"),
        "afu.md": ("---\ntype: AFU\n---\n# x\n", "afu"),
        "README.md": ("# Readme\n", ""),
    }
    for name, (body, want) in cases.items():
        p = tmp_path / name
        p.write_text(body, encoding="utf-8")
        assert doc_type(p) == want, name


@pytest.fixture
def kg(tmp_path):
    g = KnowledgeGraph(tmp_path / "k.db")
    yield g
    g.close()


def test_reference_beats_history_on_the_same_text(kg, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    text = "# Parking\n\nA node nobody reads for thirty days is parked at layer three.\n"
    (root / "HANDOFF.md").write_text(text, encoding="utf-8")
    (root / "layers.md").write_text(text, encoding="utf-8")
    auto_ingest(kg, root)
    hits = kg.search("when is a node parked", top_n=2, touch=False)
    assert pathlib.Path(hits[0]["source"]).name == "layers.md"


def test_a_literal_mention_in_history_is_not_penalised(kg, tmp_path):
    """An identifier only a CHANGELOG names must still come first (like bench q5)."""
    root = tmp_path / "docs"
    root.mkdir()
    (root / "CHANGELOG.md").write_text("# 1.0\n\nVectors are now stored with qz_vecpack.\n",
                                       encoding="utf-8")
    (root / "vectors.md").write_text("# Vectors\n\nVectors are stored as packed float blobs.\n",
                                     encoding="utf-8")
    auto_ingest(kg, root)
    hits = kg.search("qz_vecpack", top_n=2, touch=False)
    assert pathlib.Path(hits[0]["source"]).name == "CHANGELOG.md"
