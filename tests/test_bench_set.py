"""The benchmark query set is an artefact, so it needs a keeper.

`bench/run.py` itself cannot run here: it ingests the whole tree and embeds
every chunk, which is minutes and a model download. What DOES belong in the
suite is everything that can rot without anyone noticing -- a renamed file
turning a query unanswerable, a duplicated id, a metric that quietly stops
counting -- because a benchmark nobody trusts is worse than no benchmark: it
reports regressions the code did not cause.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from neurag.bench.run import (_rank_of_first_hit, load_queries,  # noqa: E402
                              summarise)

CORPUS = pathlib.Path(__file__).resolve().parent.parent
DATA = load_queries()
QUERIES = DATA["queries"]


# --- the set is what §7 asked for -------------------------------------------

def test_the_set_is_about_thirty_queries_in_both_languages_and_both_kinds():
    assert 28 <= len(QUERIES) <= 34, "§7 specifies a ~30-query set"
    assert {q["lang"] for q in QUERIES} == {"it", "en"}
    assert {q["kind"] for q in QUERIES} == {"identifier", "concept"}
    # The two kinds are reported apart, so neither may be a rounding error.
    for kind in ("identifier", "concept"):
        assert sum(1 for q in QUERIES if q["kind"] == kind) >= 10


def test_query_ids_are_unique():
    ids = [q["id"] for q in QUERIES]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("q", QUERIES, ids=lambda q: f"q{q['id']}")
def test_every_expected_file_still_exists_on_disk(q):
    """Ground truth rot: a rename makes the query unanswerable, and the
    benchmark blames the retriever."""
    for rel in q["expect"]:
        assert (CORPUS / rel).is_file(), f"q{q['id']} points at a missing {rel}"


def _ingested_files():
    """The files `auto_ingest` would actually put in the vault, minus the bench
    directory `run.py` takes back out. Derived from the ingest rules rather than
    re-listed here, so a change to either one cannot leave this behind."""
    from neurag.chunker import _SUPPORTED_EXTENSIONS
    from neurag.ingest import _skippable
    out = []
    for p in CORPUS.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue
        rel = p.relative_to(CORPUS)
        if _skippable(rel.parts[:-1]) or rel.parts[0] == "bench":
            continue
        out.append(rel.as_posix())
    return out


@pytest.mark.parametrize("q", [q for q in QUERIES if q["kind"] == "identifier"],
                         ids=lambda q: f"q{q['id']}")
def test_identifier_ground_truth_is_exactly_what_the_corpus_contains(q):
    """The identifier half is mechanical: expect = every ingested file holding
    the string literally.

    This is the guard against the failure mode that ruins a benchmark. The
    first run of this set missed four queries whose ground truth was simply
    under-listed, and the fix was to widen it -- which is indistinguishable,
    from the outside, from widening it until the score looks good. Recomputing
    from disk means the identifier half cannot be argued with at all: it is
    whatever `grep` says, and a drop is the retriever's fault by construction.

    The concept half cannot be mechanised this way ("does this answer the
    question" is a judgement), so it is frozen instead -- see queries.json
    `rules`.
    """
    found = sorted(rel for rel in _ingested_files()
                   if q["q"] in (CORPUS / rel).read_text(encoding="utf-8",
                                                         errors="ignore"))
    assert sorted(q["expect"]) == found, (
        f"q{q['id']} ({q['q']}) drifted from the corpus")


@pytest.mark.parametrize("q", [q for q in QUERIES if q["kind"] == "concept"],
                         ids=lambda q: f"q{q['id']}")
def test_a_concept_query_shares_no_rare_word_with_its_answer_filename(q):
    """A paraphrase query that names its own answer measures nothing. The
    filename is the part most likely to leak in by accident."""
    words = set(q["q"].lower().replace("'", " ").split())
    for rel in q["expect"]:
        stem = pathlib.PurePath(rel).stem.lower()
        assert stem not in words, f"q{q['id']} names {stem} outright"


# --- the metrics count what they say they count ------------------------------

def _hits(*sources):
    return [{"source": s} for s in sources]


def test_rank_is_one_based_and_matches_on_a_path_suffix():
    """Chunk `source` is absolute, ground truth is relative -- the set has to
    survive being run from a clone at a different path."""
    hits = _hits("/x/neurag/cli.py", "/x/neurag/db.py")
    assert _rank_of_first_hit(hits, ["db.py"]) == 2
    assert _rank_of_first_hit(hits, ["tests/test_hebbian.py"]) is None
    # a suffix must not match mid-name: `db.py` is not `mydb.py`
    assert _rank_of_first_hit(_hits("/x/neurag/mydb.py"), ["db.py"]) is None


def test_any_expected_file_counts_not_all_of_them():
    hits = _hits("/x/neurag/install.sh")
    assert _rank_of_first_hit(hits, ["install.ps1", "install.sh"]) == 1


def test_recall_and_mrr_are_reported_per_kind_not_only_in_total():
    """The total hid the P3 finding: vector-only was fine on paraphrase and
    failed the identifier class outright. One number cannot regress that way."""
    rows = [
        {"kind": "identifier", "lang": "en", "rank": 1, "hit@5": True},
        {"kind": "identifier", "lang": "en", "rank": None, "hit@5": False},
        {"kind": "concept", "lang": "it", "rank": 2, "hit@5": True},
        {"kind": "concept", "lang": "it", "rank": 8, "hit@5": False},
    ]
    s = summarise(rows)
    assert s["all"]["recall@5"] == 0.5
    assert s["identifier"]["recall@5"] == 0.5 and s["concept"]["recall@5"] == 0.5
    assert s["identifier"]["mrr@10"] == 0.5          # (1/1 + 0) / 2
    assert s["concept"]["mrr@10"] == 0.312           # (1/2 + 1/8) / 2
    assert s["it"]["n"] == 2 and s["en"]["n"] == 2


def test_a_rank_past_the_recall_cutoff_still_counts_toward_mrr():
    """Recall@5 and MRR@10 measure different things: a result at rank 8 is a
    miss for the first and evidence for the second."""
    s = summarise([{"kind": "concept", "lang": "en", "rank": 8, "hit@5": False}])
    assert s["all"]["recall@5"] == 0.0 and s["all"]["mrr@10"] == 0.125


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
