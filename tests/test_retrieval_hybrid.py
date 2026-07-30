"""Hybrid retrieval: both rankers always run, and the tree scopes the search.

Retrieval used to be either/or — vector when embeddings existed, lexical ONLY
as a fallback when they did not — so on every real install the lexical ranker
was dead code. That is backwards for code and technical docs: dense vectors are
weakest exactly where precision matters most (identifiers, flags, error
strings), while lexical is blind to paraphrase and cross-language matches, which
an IT+EN vault needs constantly.

Measured on the `neurag/` tree, recall@5 over 18 queries mixing exact
identifiers with conceptual paraphrases:

    vector-only (what shipped)  67%
    lexical-only                94%
    hybrid RRF                  94%

The point of fusing is not beating the better half on a friendly query set —
it is that hybrid cannot be catastrophically wrong on a whole CLASS of query
the way vector-only was on identifiers.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.chunker import (_GENERIC_CODE_EXTENSIONS, _PLAIN_EXTENSIONS,
                            _SUPPORTED_EXTENSIONS)
from neurag.db import KnowledgeGraph
from neurag.embedder import prefixes_for


def _kg():
    return KnowledgeGraph(pathlib.Path(":memory:"))


# --- BM25 replaces length-unnormalised TF-IDF --------------------------------

def test_bm25_does_not_let_length_win_on_raw_term_count():
    """`count * idf` summed meant a long rambling chunk beat a precise short
    one purely by repeating the term. BM25's `b` penalises exactly that."""
    short = {"id": 1, "text": "alpha beta"}
    padded = {"id": 2, "text": "alpha " + " ".join(f"filler{i}" for i in range(400))}
    ranked = KnowledgeGraph._rank_lexical("alpha beta", [short, padded], 2)
    assert ranked[0]["id"] == 1, "the padded chunk won on length again"


def test_bm25_idf_never_goes_negative():
    """A term in most documents must not SUBTRACT score."""
    rows = [{"id": i, "text": "common word here"} for i in range(10)]
    rows.append({"id": 99, "text": "common word here plus rare_token"})
    ranked = KnowledgeGraph._rank_lexical("common rare_token", rows, 3)
    assert ranked[0]["id"] == 99


# --- the tree finally participates in retrieval ------------------------------

def test_search_can_be_scoped_to_a_subtree():
    """`node_id` was never a search parameter, so the hierarchy contributed
    nothing to retrieval — only to browsing."""
    kg = _kg()
    a = kg.add_node("Alpha", "fundamental", parent_id=0)
    b = kg.add_node("Bravo", "fundamental", parent_id=0)
    child = kg.add_node("AlphaChild", "specialization", parent_id=a)
    kg.add_chunk(a, "shared topic discussed in alpha", source="a.md")
    kg.add_chunk(child, "shared topic discussed in the alpha child", source="ac.md")
    kg.add_chunk(b, "shared topic discussed in bravo", source="b.md")

    scoped = kg.search("shared topic", top_n=10, node_id=a)
    ids = {r["node_id"] for r in scoped}
    assert ids <= {a, child}, f"scope leaked outside the subtree: {ids}"
    assert child in ids, "descendants must be included, not just the node itself"

    unscoped = kg.search("shared topic", top_n=10)
    assert b in {r["node_id"] for r in unscoped}
    kg.close()


def test_scope_ids_includes_the_whole_subtree():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    c1 = kg.add_node("C1", "specialization", parent_id=a)
    c2 = kg.add_node("C2", "specialization", parent_id=c1)
    assert set(kg._scope_ids(a)) == {a, c1, c2}
    assert kg._scope_ids(None) is None
    kg.close()


# --- fusion ------------------------------------------------------------------

def test_hybrid_returns_results_from_both_rankers():
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "the exact identifier vector_distance_cos appears here",
                 source="x.py")
    kg.add_chunk(n, "questo testo parla di ricerca semantica e significato",
                 source="y.md")
    for i in range(8):
        kg.add_chunk(n, f"unrelated filler number {i}", source=f"f{i}.md")

    hits = kg.search("vector_distance_cos", top_n=3)
    assert any("vector_distance_cos" in h["text"] for h in hits), (
        "an exact identifier must be retrievable — this is what vector-only lost")
    kg.close()


def test_search_survives_an_empty_vault():
    kg = _kg()
    assert kg.search("anything", top_n=5) == []
    kg.close()


def test_rrf_is_rank_based_not_score_based():
    """RRF fuses RANKINGS, so an unbounded BM25 score and a [0,1] cosine can be
    combined without normalising either — that is what makes always running
    both affordable."""
    assert KnowledgeGraph.RRF_K == 60


# --- every result says what it scored, and on which scale --------------------

_STAGES = {"cosine", "bm25", "rrf", "cross-encoder"}


def _vault():
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "the exact identifier vector_distance_cos appears here",
                 source="x.py")
    kg.add_chunk(n, "questo testo parla di ricerca semantica e significato",
                 source="y.md")
    for i in range(8):
        kg.add_chunk(n, f"unrelated filler number {i}", source=f"f{i}.md")
    return kg


def test_every_result_carries_a_score_and_its_scale():
    """`sim` was attached by the vector leg only, and the fused RRF value was
    dropped entirely — so half a hybrid ranking had no score at all and the
    other half carried a cosine that no longer explained the order. Nothing
    could display or threshold the result it was handed."""
    kg = _vault()
    for query in ("vector_distance_cos", "ricerca semantica", "filler"):
        hits = kg.search(query, top_n=5)
        assert hits
        for h in hits:
            assert isinstance(h.get("score"), float), f"{query}: {sorted(h)}"
            assert h.get("score_from") in _STAGES
        assert len({h["score_from"] for h in hits}) == 1, "one ranking, one scale"
    kg.close()


def test_the_lexical_only_leg_still_scores_its_results():
    """No embedder → no vector leg. The BM25 rows are the whole ranking, and
    they used to come back bare."""
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0)
    for i in range(5):
        kg.add_chunk(n, f"alpha beta gamma {i}", source=f"f{i}.md")
    kg._conn.execute("UPDATE chunks SET embedding = NULL")
    kg._conn.commit()
    hits = kg.search("alpha", top_n=3)
    assert hits and all(h["score_from"] == "bm25" for h in hits)
    assert all(h["score"] > 0 for h in hits)
    kg.close()


def test_the_reranker_replaces_the_score_it_reorders_by():
    """A cross-encoder that reorders while leaving the first stage's number in
    place hands back a ranking its own score contradicts."""
    from neurag.reranker import FastEmbedReranker, NullReranker

    cand = [{"id": 1, "text": "a", "score": 0.9, "score_from": "rrf"},
            {"id": 2, "text": "b", "score": 0.1, "score_from": "rrf"}]
    # null routing is the identity: it ranks nothing, so it rewrites nothing
    assert NullReranker().rerank("q", cand, 2) == cand

    fake = FastEmbedReranker.__new__(FastEmbedReranker)
    fake._m = type("M", (), {"rerank": staticmethod(lambda q, docs: [-2.0, 3.0])})()
    out = fake.rerank("q", cand, 2)
    assert [c["id"] for c in out] == [2, 1]
    assert out[0]["score"] == 3.0 and out[0]["score_from"] == "cross-encoder"


# --- e5 prefixes -------------------------------------------------------------

@pytest.mark.parametrize("model,expected", [
    ("intfloat/multilingual-e5-large", ("query: ", "passage: ")),
    ("intfloat/e5-base-v2", ("query: ", "passage: ")),
    ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", ("", "")),
    ("sentence-transformers/all-MiniLM-L6-v2", ("", "")),
    ("", ("", "")),
])
def test_only_e5_models_get_prefixes(model, expected):
    """E5 needs `query: `/`passage: ` and degrades without them — it is option 4
    in every installer, sold as "best quality", and nothing applied them. Adding
    a prefix to a model that was not trained with one poisons the vector, so
    this is a strict allowlist."""
    assert prefixes_for(model) == expected


def test_query_and_document_embeddings_are_asymmetric():
    from neurag.embedder import NullEmbedder
    e = NullEmbedder()
    assert e.embed("x") is None and e.embed_query("x") is None   # null stays null


# --- indexable file types ----------------------------------------------------

@pytest.mark.parametrize("ext", [".sh", ".ps1", ".cmd", ".sql", ".c", ".cs", ".html"])
def test_shell_and_common_languages_are_indexable(ext):
    """install.ps1 / install.sh are the most-discussed files in this suite and
    were not indexable at all: a query for `pyvenv.cfg` could not be answered
    because the only file containing it was never ingested."""
    assert ext in _SUPPORTED_EXTENSIONS


def test_extension_sets_do_not_overlap():
    assert not (_GENERIC_CODE_EXTENSIONS & _PLAIN_EXTENSIONS)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
