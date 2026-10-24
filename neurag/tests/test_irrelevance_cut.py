"""knowledge_query drops what is weak on both signals, and shows its cosine.

RRF ranks the least bad and has no floor, so every query came back full —
reported 2026-10-24: a deploy question returned the NgRx note too. Thresholds
tuned on bench/ (numbers in `KnowledgeGraph._cut_irrelevant`).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph

KG = KnowledgeGraph


def _row(i, cos, bm25, text="a short but real sentence"):
    return {"id": i, "cos": cos, "bm25": bm25, "text": text}


def test_a_heading_with_no_body_needs_the_lexical_match_too():
    """10% of the real vault are chunks like `### Variabili d'ambiente`: near
    everything in meaning, and empty as an answer — "carbonara" got five. A
    short sentence with a body is content, and stays."""
    rows = [_row(1, 0.40, 1.0, "### Variabili d'ambiente"),
            _row(2, 0.40, 10.0, "## Backup\n\n### Rotazione"),
            _row(3, 0.36, 1.0), _row(4, 0.40, 1.0, "## Backup\nogni giorno, 7 copie")]
    assert [r["id"] for r in KG._cut_irrelevant(rows)] == [2, 3, 4]


def test_a_row_close_in_meaning_stays_without_any_lexical_match():
    assert KG._cut_irrelevant([_row(1, KG.CUT_COS, 0.0)])


def test_below_the_cosine_only_the_best_lexical_match_survives():
    """The identifier case: bench answers sit as low as cos 0.23, always as the
    query's top BM25. A weak lexical match there is a shared stopword."""
    rows = [_row(1, 0.25, 10.0), _row(2, 0.25, 9.5), _row(3, 0.25, 4.0)]
    assert [r["id"] for r in KG._cut_irrelevant(rows)] == [1, 2]


def test_below_the_floor_not_even_the_best_lexical_match_survives():
    """Several chunks tie on the best BM25 of a common word, at cosine ~0."""
    assert KG._cut_irrelevant([_row(1, 0.0, 10.0), _row(2, -0.05, 10.0)]) == []


def test_a_row_without_a_cosine_is_never_cut():
    """A vault with no embedder ranks lexically: nothing to measure against."""
    assert KG._cut_irrelevant([_row(1, None, 0.0)])


def test_every_result_carries_its_cosine_and_bm25():
    kg = KnowledgeGraph(pathlib.Path(":memory:"))
    n = kg.add_node("N", "fundamental", parent_id=0)
    # Not a real identifier of this repo: bench/ greps the corpus for those.
    kg.add_chunk(n, "the exact identifier zq_cut_probe appears here", source="x.py")
    kg.add_chunk(n, "questo testo parla di ricerca semantica", source="y.md")
    hits = kg.search("zq_cut_probe", top_n=5)
    kg.close()
    assert hits and all("cos" in h and "bm25" in h for h in hits), hits
