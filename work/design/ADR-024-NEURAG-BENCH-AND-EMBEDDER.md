# ADR-024: NeuRAG — a fast suite, a bench that does not drift, an embedder trial

> Status: **Proposed** — 2026-11-16. D1 needs no GPU; D2-D4 wait for it.
> Scope: NeuRAG (`neurag/tests`, `neurag/bench`). Relates to ADR-017.
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

- The NeuRAG suite takes 7-8 minutes of the gate's 10 (443 tests; 430-484 s on
  2026-11-16). It is the brake on every round of work on the other two tools.
- The bench reference `neurag/bench/results/P5.json` (recall@5 0.967, recorded
  on set v3) and today's run (0.933, set v5) differ by one query, q20, and the
  cause is the corpus, not the code: the corpus **is the repo**, so a docstring
  and a README edit overtook the expected chunk lexically (`queries.json`, note
  `v5-gap`). A bench whose corpus changes with every commit cannot guard a
  change.
- The embedder is `paraphrase-multilingual-MiniLM-L12-v2`: trained to recognise
  paraphrases, not to retrieve a passage for a question.
- Measured 2026-11-08: a question in the documents' language scores hit@5 7/8,
  in another language 5/8.

## Decision

**D1. A faster suite, by measuring first.** Run
`pytest neurag/tests --durations=25`; the slow tests will be the ones that load
the real embedder or re-ingest. For those: share one embedder per session
(a session-scoped fixture), or use `NEURAG_EMBEDDER=null` where the test is
about lexical or plumbing behaviour. Target: under 3 minutes. No test deleted to
get there.

**D2. A frozen corpus for the bench.** Snapshot the corpus at a commit into a
folder the bench reads (or pin the commit and read the tree from git). Record
the commit in the result file. A new reference is recorded on the frozen corpus.

**D3. An embedder trial**, opt-in beside the light default:
`intfloat/multilingual-e5-large` (retrieval-trained, MIT, 1024 dimensions,
2.2 GB; listed by the installed fastembed 0.9.1). It needs the `query:` /
`passage:` prefixes: `prefixes_for` in NeuRAG already handles prefixes. Adopt
only on a measured gain on the frozen bench **and** on Neuron's three sets;
otherwise close as "measured, not adopted". Ruled out already:
`jina-embeddings-v3` (non-commercial licence),
`paraphrase-multilingual-mpnet-base-v2` (same paraphrase family).

**D4. Questions in the documents' language.** The open item from ADR-016/017:
when the message's language differs from the indexed material's, Gray Matter
asks with the terms Neuron's facts hold for that topic (they are in English, the
pivot language). The 7/8 against 5/8 figure is quoted in `knowledge_query`'s
description (`neurag/server.py`); the eight questions are not in the repo as a
set: find them in the history or rebuild a set first, then measure.

## Steps

D1 now. D2 → D3 → D4 with the GPU, each closed by a number.

## Traps

- D1: the three suites must stay in separate processes (`pytest.ini`,
  `conftest.py`); a session fixture must not leak across them.
- D2: the frozen corpus must not be indexed by the live NeuRAG (it would double
  every document). Keep it out of the vault's roots.
- D3: a new embedder means a full re-embedding and vectors of another size: the
  store checks the model (`NS_EMBED_MODEL` alignment in Neuron). Run it on an
  isolated instance, never on the live knowledge base. Hook latency on CPU must
  be measured: the recall runs on every message.
- D3 on a laptop without GPU is the heavy run the user asked to avoid.

## Acceptance

- D1: the gate's NeuRAG step under 3 minutes, same number of tests.
- D2: two runs a week apart give the same recall@5 with unchanged code.
- D3: a table with both embedders on both benches, and the latency per query.
