"""The retrieval benchmark DESIGN-EVOLUTION §7 asks for, as a runnable artefact.

Until now the numbers in §6b (recall@5 67% -> 94%) came from a query set that
lived only in a session: reproducible by nobody, comparable to nothing. §7 asks
for "a fixed ~30-query set over a fixed corpus, IT and EN, with known-good
answers. Recall@5 and MRR recorded per phase. No phase may regress the previous."
Without that as a versioned file, every future change to ranking can only be
argued, not measured. That is the block this removes -- and it earned its keep
immediately: folding spreading activation into `search()` looked obviously
right and measured 13 points of recall WORSE, so it was removed instead of
shipped.

The corpus is the `neurag/` tree itself. Self-hosting is not laziness here: it
is the only corpus that travels with the repo, so a result is reproducible from
a commit hash alone.

    python bench/run.py                  # ingest if needed, measure, print
    python bench/run.py --json > bench/results/P5.json

Read the per-KIND breakdown, not the total. The total hides the finding that
justified hybrid retrieval in the first place: vector-only scored 94% on
paraphrase and 67% overall because it failed the identifier class outright.
A single number cannot regress in the way that matters.

Two honest limits of this set, stated so nobody reads more into a number:
  * ground truth is "the file that contains the answer", found by grep at
    authoring time -- which by construction favours lexical matching on the
    identifier half. That is why the two halves are reported apart.
  * the corpus is a densely cross-referenced repo, not a personal vault of
    loosely related documents. Same caveat as the parking thresholds (§8.1).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent))

from neurag.db import KnowledgeGraph      # noqa: E402
from neurag.ingest import auto_ingest     # noqa: E402

QUERIES = _HERE / "queries.json"
DEFAULT_CORPUS = _HERE.parent
DEFAULT_VAULT = _HERE / "vault" / "bench.db"

RECALL_AT = 5
MRR_AT = 10


def _sources(hits: list[dict]) -> list[str]:
    """Chunk `source` is an absolute path (`index_into_node`); ground truth is a
    suffix, so the set survives being run from a clone at any path."""
    return [pathlib.PurePath(h.get("source") or "").as_posix() for h in hits]


def _rank_of_first_hit(hits: list[dict], expect: list[str]) -> int | None:
    """1-based rank of the first result from an expected file, or None."""
    for i, src in enumerate(_sources(hits), start=1):
        if any(src == e or src.endswith("/" + e) for e in expect):
            return i
    return None


def load_queries() -> dict:
    return json.loads(QUERIES.read_text(encoding="utf-8"))


def check_ground_truth(kg: KnowledgeGraph, queries: list[dict]) -> list[str]:
    """Every expected path must be in the vault before a miss means anything.

    Ground truth rots: a file gets renamed and the query silently becomes
    unanswerable, so the benchmark reports a regression the code did not cause.
    Cheaper to fail here than to chase a phantom recall drop.
    """
    have = {pathlib.PurePath(r["source"]).as_posix()
            for r in kg._conn.execute(
                "SELECT DISTINCT source FROM chunks WHERE source IS NOT NULL").fetchall()}
    missing = []
    for q in queries:
        for e in q["expect"]:
            if not any(s == e or s.endswith("/" + e) for s in have):
                missing.append(f"q{q['id']}: {e}")
    return missing


def ensure_vault(corpus: pathlib.Path, vault: pathlib.Path,
                 rebuild: bool = False) -> KnowledgeGraph:
    fresh = rebuild or not vault.exists()
    if rebuild and vault.exists():
        vault.unlink()
    vault.parent.mkdir(parents=True, exist_ok=True)
    kg = KnowledgeGraph(vault)
    if fresh:
        print(f"[bench] ingesting {corpus} -> {vault} (embeds every chunk, "
              f"takes minutes; reused on the next run)", file=sys.stderr)
        t0 = time.time()
        report = auto_ingest(kg, corpus)
        decontaminate(kg)
        print(f"[bench] {report['files']} files, {report['chunks']} chunks, "
              f"links {report['links']}, {time.time() - t0:.0f}s", file=sys.stderr)
    assert not _bench_sources(kg), "the query set is in the corpus it measures"
    return kg


def _bench_sources(kg: KnowledgeGraph) -> list[str]:
    """Chunks that came out of THIS directory.

    Filtered in Python on a resolved path rather than by `source LIKE '%bench%'`:
    the substring version also flagged `tests/test_bench_set.py`, an ordinary
    repo file that belongs in the corpus and holds no query text. It can only
    cost recall, never grant it -- it is in no `expect` list. (LIKE would also
    need its `_` and `%` escaped out of a filesystem path.)
    """
    here = _HERE.resolve()
    out = []
    for r in kg._conn.execute(
            "SELECT DISTINCT source FROM chunks WHERE source IS NOT NULL").fetchall():
        try:
            pathlib.Path(r["source"]).resolve().relative_to(here)
        except ValueError:
            continue
        out.append(r["source"])
    return out


def decontaminate(kg: KnowledgeGraph) -> None:
    """Drop this directory back out of the vault it just went into.

    `.json` and `.py` are both indexed, so a plain ingest of the corpus files
    `queries.json` -- every question next to the filename that answers it, in
    one chunk. The concept half would then be answered by the answer key. The
    node goes after the ingest rather than the directory being added to
    `_SKIP_DIRS`: a global rule about the word "bench" would follow users into
    projects where that folder is real knowledge.

    `delete_node` already unwinds chunks, join rows and tag counts; the links
    have to be rebuilt because they were derived with the contamination in.
    """
    node = kg.get_node_by_name(_HERE.name)
    if node:
        kg.delete_node(node["id"])
        kg.rebuild_links()


def measure(kg: KnowledgeGraph, queries: list[dict]) -> dict:
    rows = []
    for q in queries:
        # touch=False: answering marks nodes and raises tag salience, so a
        # benchmark that warms the vault it measures stops being a fixed corpus
        # after its first run.
        hits = kg.search(q["q"], top_n=MRR_AT, touch=False)
        rank = _rank_of_first_hit(hits, q["expect"])
        rows.append({
            "id": q["id"], "kind": q["kind"], "lang": q["lang"], "q": q["q"],
            "rank": rank,
            "hit@%d" % RECALL_AT: bool(rank and rank <= RECALL_AT),
            "top": _sources(hits)[:3],
        })
    return {"queries": rows, "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    def agg(subset: list[dict]) -> dict:
        if not subset:
            return {"n": 0}
        hits = sum(1 for r in subset if r["hit@%d" % RECALL_AT])
        rr = sum(1.0 / r["rank"] for r in subset if r["rank"])
        return {"n": len(subset),
                "recall@%d" % RECALL_AT: round(hits / len(subset), 3),
                "mrr@%d" % MRR_AT: round(rr / len(subset), 3)}

    out = {"all": agg(rows)}
    for key in ("kind", "lang"):
        for value in sorted({r[key] for r in rows}):
            out[value] = agg([r for r in rows if r[key] == value])
    return out


def report(result: dict) -> None:
    for r in result["queries"]:
        mark = "ok " if r["hit@%d" % RECALL_AT] else "MISS"
        rank = r["rank"] if r["rank"] else "-"
        print(f"  {mark} q{r['id']:<3} {r['kind']:<10} {r['lang']}  rank={rank!s:<4} {r['q'][:56]}")
        if not r["hit@%d" % RECALL_AT]:
            print(f"       got: {', '.join(s.rsplit('/', 1)[-1] for s in r['top']) or '(nothing)'}")
    print()
    for label, s in result["summary"].items():
        if s["n"]:
            print(f"  {label:<12} n={s['n']:<3} "
                  f"recall@{RECALL_AT}={s['recall@%d' % RECALL_AT]:<6} "
                  f"mrr@{MRR_AT}={s['mrr@%d' % MRR_AT]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", type=pathlib.Path, default=DEFAULT_CORPUS)
    ap.add_argument("--vault", type=pathlib.Path, default=DEFAULT_VAULT)
    ap.add_argument("--rebuild", action="store_true",
                    help="re-ingest from scratch instead of reusing the vault")
    ap.add_argument("--json", action="store_true", help="machine-readable, for recording a phase")
    args = ap.parse_args(argv)

    data = load_queries()
    kg = ensure_vault(args.corpus, args.vault, args.rebuild)
    try:
        missing = check_ground_truth(kg, data["queries"])
        if missing:
            print("[bench] ground truth points at files not in the vault -- fix the "
                  "query set, do not read the numbers:", file=sys.stderr)
            for m in missing:
                print("  " + m, file=sys.stderr)
            return 2
        result = measure(kg, data["queries"])
    finally:
        kg.close()

    result["set_version"] = data["version"]
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
