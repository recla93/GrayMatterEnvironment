# DESIGN-EVOLUTION — NeuRAG as a real graph, and the suite as one brain

**Status:** Draft for approval
**Date:** 2026-07-29
**Scope:** NeuRAG (primary), Neuron (cross-tool surface), Gray Matter (orchestration only)
**Supersedes:** `neurag/DESIGN-CROSSLINKS.md` §2–§4 and §6 (design shipped wrong or not at all — see §1)

---

## 0. Why

NeuRAG's link layer does not work. Not "works poorly" — produces zero rows, always,
on the only ingest path most users take. Measured on a 3-file corpus:

```
report: nodes 3, files 3, chunks 5, links {'tag_overlap': 0, 'cross_ref': 0, 'total': 0}
node tags:     [('a', '[]'), ('b', '[]')]
node triggers: [('a', '["alpha_helper","alpha","helper","betathing",…]')]
```

Two independent causes, both structural:

1. **`build_tag_links` reads `nodes.tags`; `auto_ingest` never writes it.** The chunker
   computes tags correctly (`chunker._tags`), `index_into_node` files them into
   `node.triggers` via `add_triggers`, and the linker filters on
   `WHERE tags IS NOT NULL AND tags != '[]'` — which matches nothing. One column off.
2. **`build_crossref_links` groups chunks by source file**, but every file's chunks land
   in exactly one node, so each source maps to one node and the pair loop never runs.

Drift from `DESIGN-CROSSLINKS.md` compounds it: the specified `min_jaccard=0.15`
threshold is absent from the shipped `build_tag_links` (hence the unbounded O(n²) pair
explosion it would produce *if* tags were ever populated); the specified
`link_by_cross_refs` (nodes whose chunks mention another node's triggers) was replaced
by the same-source no-op; and `semantic` exists in the schema `CHECK` constraint but is
never generated.

Consequence: `knowledge_neighbors`, `search_with_links`, and the GUI link panel are all
traversing an empty table. Everything downstream of "NeuRAG is a knowledge *graph*" is
currently aspiration.

This document fixes that, then builds on it.

---

## 1. Invariants

These are hard constraints. Any change that violates one is wrong regardless of merit.

| # | Invariant | Enforced by |
|---|---|---|
| I1 | **The six installers stay aligned.** A knob added to one is added to all: `install.ps1` + `install.sh` × 3 repos, plus `.cmd`/`.command` if flags change. | `gray_matter/tests/test_installer_parity.py` — extend `PS1_FEATURES` / `SH_FEATURES` in the same commit |
| I2 | **NeuRAG alone is the baseline, not a degraded mode.** Every quality gain in P0–P5 must be fully present with Neuron *and* Gray Matter absent. Neuron and GM are amplifiers on top of a system that is already good; they are never prerequisites for it. Same in reverse for Neuron. | the three-configuration matrix in §7 |
| I3 | **Gray Matter orchestrates; it does not own data.** GM manages cross-store bridges, enriches Neuron's stimuli with knowledge, routes. It never becomes required for retrieval. | I2 + `bridges.py` existing tier rules |
| I4 | **NeuRAG uses pyturso.** Native `vector_distance_cos` is the reason retrieval scales; the sqlite3 tier is a degraded fallback, not a target. **(2026-07-30: that fallback did not exist — `sqlite3.connect` was never called in `db.py`, so "degraded" meant `_conn = None` and a vault reported CORRUPT. Built for real; see §7 Engine.)** | `db._vector_sql`, `status()["engine"]` |
| I5 | **Nothing is ever deleted, in any store.** Not chunks, not nodes, not concepts. Unused things are *parked* — dropped from the active working set, kept in storage, reactivatable by `recall`. Only *link weights* and *tag salience* decay, and decay means "harder to reach", never "gone". | §3; `Graph._graveyard` is already "recoverable" |
| I6 | **Coherence across the three.** Shared vocabulary, shared vector space, shared tier ladder, shared settings shape. | `test_client_targeting.py` pattern |
| I7 | **The GUI is verified last, every time.** The control center reads `catalog` + `settings.HELP`/`SUGGEST`; a new knob invisible in the GUI is an unfinished knob. | manual pass + `test_gui_bundling.py` |

**Precondition (blocking, from the current release) — ✅ DONE 2026-07-29.**
`gray_matter/install.sh` (374 CRLF) and `neurag/install.sh` (309) were CRLF while
`neuron/install.sh` was LF — on Linux that is `bad interpreter: /usr/bin/env sh^M`.
The same drift affected all five shared handshake assets in `neurag/clients/`.
Seven files normalized to LF; `gray_matter/tests` went from 9 failures to 2.

**Known environment issue (not a code defect).** The remaining 2 failures in
`gray_matter/tests/test_version_parity.py`, and 4 in `neuron/tests/test_cli_dispatch.py`,
all spawn `python -m neuron` and get *"No module named neuron.__main__"*. Cause: the
venv's editable install points at `C:\Users\<utente>\Desktop\Gray Matter Enviroment\neuron\src`,
which no longer exists — the workspace moved to `D:\`. `import neuron` works under pytest
only because the root `conftest.py` injects the correct path; a subprocess inherits
nothing. **Every subprocess-based test in the suite is currently inert.** Repair with a
re-`pip install -e` of the three packages from `D:\`, then re-run before trusting any
CLI-level result.

---

## 2. Is embedding necessary?

**Yes — and the hybrid design below is what makes it affordable to say yes.**

The decisive argument is your corpus, not RAG orthodoxy. The vault is Italian *and*
English, often in the same document. Lexical retrieval cannot bridge
`salienza` → `salience`, `nodo` → `node`, `collegamento` → `link`. No amount of BM25
tuning crosses a language boundary. That alone settles it.

But "necessary" is not "sufficient", and today it is treated as all-or-nothing:
`_retrieve` uses vectors if they exist and falls back to lexical only when they don't.
That is backwards for a corpus of code and technical docs, where dense vectors are
weakest exactly where precision matters most — identifiers, flags, error strings
(`vector_distance_cos`, `WinError 5`, `--client`). Both retrievers already exist in
`db.py`; they have simply never run together.

**Decision:** embeddings stay, and become one of two fused signals rather than a switch.

- `NullEmbedder` + BM25 remains a legitimate zero-dependency standalone mode.
- With an embedder present, hybrid RRF fusion runs (§5.2).
- pyturso (I4) is what makes the vector half cheap at scale — native `vector_distance_cos`
  ranks in SQL instead of unpacking every blob into Python.

### 2.1 Model selection — mirror Neuron exactly

The plumbing largely exists and is already aligned:

| Layer | State |
|---|---|
| Install-time picker, 4 models | ✅ all three `install.ps1`/`install.sh` (`$EmbedModels` / `EM_*`) |
| Persisted per-user | ✅ `neuron.config.user_env_file()`, `neurag/settings.py` `embed_model`/`embed_dim` |
| GUI-editable | ✅ `settings.HELP` + `SUGGEST` are read by the control center |
| Dim resolved dynamically | ✅ `embedder._resolve_dim()` (fixed this release) |

Four real gaps — and the first one is a direct violation of I2:

0. ~~**Standalone NeuRAG cannot embed at all.**~~ **✅ FIXED 2026-07-30.** `fastembed` was
   a hard dependency of Neuron but only an optional `semantic` extra in NeuRAG, and no
   installer ever requested that extra — so NeuRAG alone resolved to `NullEmbedder` and
   searched lexically, embedding *only* when Neuron happened to share the venv. Exactly
   the dependency I2 forbids, and silent: picking `multilingual-e5-large` gave worse
   results than the default with nothing said.
   Fixed at the root — `fastembed` is now a hard dependency, mirroring Neuron, so all six
   installers inherit it through pip resolution rather than four call sites needing the
   extras syntax. This does **not** force a model download: weights are fetched lazily on
   first `TextEmbedding(...)`. `lexical_only_requested()` separates a *chosen* lexical mode
   from an *accidental* one, and `status()` reports `search_mode` as
   `semantic` / `lexical (requested)` / `lexical (DEGRADED)` with a fix hint.
   Verified: `pip show neurag` → `Requires: fastembed, mcp, pyturso`.

   **Half-finished until 2026-07-30.** The dependency became mandatory; the installers
   kept offering `"none" — lexical only, no model download` as the second menu entry, and
   the comment above it still explained that NeuRAG "is lexical-only without fastembed"
   and that the model is mandatory "unlike Neuron". Both statements had been false since
   this fix landed. Worse, the branch behind that entry wrote `embed_model = ''`, and `''`
   means *follow Neuron / the multilingual default* — so it printed "no embedding model
   will be downloaded", configured the model it had just promised not to fetch, and
   downloaded it on first use. Nothing ever wrote the literal `"none"` that
   `lexical_only_requested()` looks for, so the *chosen* lexical mode the same fix
   introduced was unreachable from the installer that was supposed to offer it.
   The entry is gone from both pickers. Lexical-only remains where an expert knob belongs:
   `neurag config set embed_model none`. Removed from the menu, not from the runtime.

Then:

1. ~~**Changing the model silently corrupts the vault.**~~ **✅ FIXED 2026-07-30.**
   `settings.set("embed_model", …)` succeeded instantly and every stored vector became
   noise; the only warning was prose in the knob's `HELP`, which nothing enforced.
   Now: `embed_model` + `embed_dim` live in a `meta` table **next to the vectors** —
   config.json can be edited, copied or reset independently of the vault, so it could
   never be the source of truth — and `embed_mismatch()` detects a swap at open rather
   than at query, surfaced through `status()`. `neurag reindex` (CLI `--json`, MCP
   `knowledge_reindex`, catalogued so the GUI renders it) re-embeds every chunk from
   stored text; sources are not needed and text/nodes/links are untouched. Changing
   `embed_model`/`embed_dim` on a populated vault is refused with the exact recovery
   command unless `--force`.
   Scope note: `reindex` is for a MODEL change. A chunk-*size* change needs re-chunking
   from disk — that is `neurag ingest`, which is idempotent per source file since P2.
2. **e5 models ship broken.** Option 4 is `intfloat/multilingual-e5-large`, advertised as
   best quality. E5 requires `query: ` / `passage: ` prefixes; a grep across all three
   repos finds none. Picking option 4 today yields *worse* results than option 1, with no
   signal why. **Deliverable:** per-model prefix map in `embedder.py`, applied
   asymmetrically (documents at ingest, queries at search).
3. **Dim/model pairing is unvalidated.** A custom model name from the installer's
   free-text path arrives with `dim = 0`. Derive it from a first embed and persist.

---

## 3. Layers — an activation gradient, not a disposal chain

Following ADR-008's four-level model. The key point, and the thing that makes both
stores coherent (I5): **no layer is a grave. Every layer is a parking level, and
`recall` reaches all of them.**

```
L1  Session working set    warm nodes + tags for the current session
    ↓ TTL (10 queries) + cap (8 entries), FIFO — eviction is not loss
L2  Active vault           nodes + chunks + links, fully indexed, vector SQL
    ↓ parked by inactivity × link weight   (NEVER by content age)
L3  Dormant                out of the default candidate scan; still stored,
                           still reachable — node scope, `deep=true`, or `recall`
    ↓ deep dormancy: no longer proposed spontaneously
L4  Deep dormant           never surfaced on its own; `recall` still wakes it
```

Neuron already works exactly this way and the terminology in this document was wrong
before: `consolidate()` archives absorbed nodes into `_graveyard` — the docstring says
**"recoverable"** — and orphan drops do the same. ADR-008's L4 is explicit that nodes
*"restano nel DB (non vengono cancellati)"*. The `DELETE FROM nodes` statements in
`models.py` are active-table synchronisation *after* archiving, not disposal. Neuron
does not forget in the sense of losing; it stops spending compute on what is not being
used, and `recall` brings it back.

So NeuRAG's L3/L4 is not a divergence from Neuron — it is the **same mechanism**:
Neuron's graveyard and NeuRAG's dormant tier are the same idea applied to two kinds of
content. That is a much better outcome for I6 than the asymmetry previously described
here.

What "decays" is the **route, not the trace**: link weights and tag salience fall, so a
dormant thing gets harder to reach spontaneously — never impossible, and never removed.
This is both the correct neuroscience and the principle `bridges.py` already states for
bridges. We extend it; we do not break it.

The only real asymmetry left is *pressure*: Neuron parks aggressively because a live
memory that keeps everything hot is a log, while NeuRAG parks reluctantly because a
library's job is availability. Same machinery, different thresholds — and the thresholds
are constants, tunable per store (§8.1).

L1 mirrors Neuron's `Graph._session_cache` (dict in memory, serialized to `meta`,
reloaded on restart). Same TTL, same cap, same eviction. Coherence (I6) is free here
because we are copying a working implementation.

---

## 4. The tag substrate

One atom, currently five representations, no join key:

| Store | Its word | Populated | Joinable by |
|---|---|---|---|
| NeuRAG chunk | `chunk.tags` | ✅ chunker | nobody |
| NeuRAG node | `node.triggers` | ✅ `add_triggers` | exact match only |
| NeuRAG node | `node.tags` | ❌ **always `[]`** | the linker — which reads this one |
| Neuron | `keywords` | ✅ | itself |
| GM bridge | endpoint strings | ✅ | substring containment |

**A tag becomes a first-class row, and the only object all three stores agree on.**

```sql
CREATE TABLE IF NOT EXISTS tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,     -- normalized: lowercase, trimmed
    uses      INTEGER DEFAULT 0,        -- document frequency, drives IDF suppression
    salience  REAL    DEFAULT 0.0,      -- Hebbian; decays (I5: tags decay, chunks don't)
    last_used TEXT
);
CREATE TABLE IF NOT EXISTS node_tags  (node_id  INTEGER, tag_id INTEGER,
                                       PRIMARY KEY (node_id, tag_id));
CREATE TABLE IF NOT EXISTS chunk_tags (chunk_id INTEGER, tag_id INTEGER,
                                       PRIMARY KEY (chunk_id, tag_id));
CREATE INDEX IF NOT EXISTS idx_node_tags_tag  ON node_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_chunk_tags_tag ON chunk_tags(tag_id);
```

What this buys, all at once:

- **Node linking becomes an index lookup**, not an O(n²) sweep — and `min_jaccard`
  returns from the original design.
- **High-frequency tags self-suppress via IDF.** A tag on 80% of nodes carries no
  information; `uses` makes that automatic instead of a hand-maintained stop list.
  (Information theory and neuroscience agree: a cue that predicts everything predicts
  nothing.)
- **Salience gets a correct home.** Not on the Neuron node, not on the NeuRAG node — on
  the tag, which both can reference.
- **Cross-tool joins stop being string matching.** GM's bridge is currently
  `_valid_endpoint` + substring containment on the topic; with tag ids it is a foreign key.

`node.tags` / `node.triggers` stay as legacy read paths through Phase 1 and are dropped
once migration is verified.

---

## 5. What we borrow from the brain — mostly from Neuron

Neuron already implements the neuroscience. It is in the wrong half of the suite.

| Mechanism | Neuron | NeuRAG today |
|---|---|---|
| Hebbian reinforcement | ✅ `reinforce_coactivation()`, cooldown 2, upgrade 3/8 (ADR-003 E2.1) | ❌ batch rebuild, curated links deleted |
| Spreading activation | ✅ `spreading_activation(seeds, k=2, decay=.5)` (E2.3) | ❌ shelved (`DESIGN-CROSSLINKS` §6) |
| Composite ranking | ✅ `cos*.5 + salience*.3 + recency*.2` (E2.4) | ❌ pure cosine |
| Consolidation / sleep | ✅ `sleep_maybe()` (ADR-004 E3.3) | ❌ none |
| Pre-staged stimulus | ✅ `take_staged_stimulus()` (E3.4) | ❌ none |
| Semantic dedup + MMR | ✅ ADR-008 §5.5/5.6 | ❌ none |

Porting is mostly moving working, tested code across a repo boundary — which is also
why it satisfies I6 for free.

### 5.1 Hebbian on retrieval, not batch rebuild

`rebuild_links()` opens with `DELETE FROM node_links` and runs at the end of every
`auto_ingest`. The graph cannot learn, and any hand-curated link has a lifetime of one
re-ingest.

- Add `origin TEXT DEFAULT 'auto'` to `node_links`. `rebuild_links` deletes
  `WHERE origin = 'auto'` only.
- Add `co_activation_count`. Two nodes co-returned **and confirmed useful** → `+1`,
  with Neuron's cooldown and the same `tangential→medium→strong` thresholds at 3 and 8.
- Co-retrieval without confirmation does not reinforce. Retrieval is cheap and often
  wrong; confirmation is the signal.

### 5.2 Retrieval: hybrid, scoped, diversified

`_retrieve` becomes:

1. **Two first-stage retrievers, always both** when an embedder exists —
   vector (pyturso `vector_distance_cos`, I4) and BM25 — fused with Reciprocal Rank Fusion.
2. **BM25 replaces the length-unnormalized TF-IDF** in `_rank_lexical`. The
   `ponytail:` comment at `db.py:1084` already flags this; it bites precisely because
   chunk lengths are wildly unequal (§5.4).
3. **Optional `node_id=` scope** → `WHERE node_id IN (descendants)`. One clause, and the
   hierarchy finally contributes to retrieval instead of only to browsing.
4. **MMR diversification** (λ=0.7, same as ADR-008 §5.6) so top-n is not five
   near-duplicates from one file. **Measured 2026-07-30 and it earns its place,
   barely:** recall@5 0.967 with, 0.933 without; it moves exactly one query out
   of 30 and moves it up (q27, rank 6 → 4). MRR is unchanged either way. Keep,
   but nobody should expect much from it on a corpus like this.
5. ~~**Spreading-activation expansion**~~ — **built, measured, removed
   (2026-07-30).** Folding activation into the ranking as a third RRF leg cost
   10 points of recall@5 and 22 of MRR@10 on the benchmark set: the graph
   carries no confirmed links yet, and the node distribution is degenerate
   enough that the vote is a near-constant prior. Full numbers in the CHANGELOG.
   The code is gone rather than switched off — an unused branch on the hot
   retrieval path is a maintenance cost the measurement does not justify — and
   `related` / `knowledge_related` keep activation available where a user asks
   for it directly. This is the entry that §7's benchmark existed to settle, and
   it settled it against the design.
6. ~~Cross-encoder rerank stays where it is: opt-in, last stage.~~
   **Measured 2026-07-31 and REMOVED.** recall@5 unchanged (0.967), the concept
   half of MRR *worse* (0.780 → 0.741), and the median query 397ms → 6815ms.
   Its wins were identifier queries moving rank 2 → 1, inside a top-5 the model
   reads whole. Opt-in and off by default was not enough to justify the module,
   three knobs and a branch on the hot path. Numbers in the CHANGELOG.
   The reusable part is the decision rule: **`recall@50 − recall@5` is the
   ceiling of any reranker**, since it reorders and never retrieves. Measure
   that before downloading 1.11 GB — it is the only multilingual option, the
   small ones being English-only and therefore worse than nothing on this vault.

### 5.3 Complementary Learning Systems — the missing third

The McClelland/O'Reilly model, two thirds of which the suite already is:

> **Hippocampus** — fast, episodic, plastic, decays, pattern-separates → **Neuron**
> **Neocortex** — slow, semantic, permanent, pattern-completes → **NeuRAG**
> **Consolidation** — stable traces replayed from hippocampus to cortex → **missing**

`sleep_maybe()` consolidates Neuron *within itself* and never writes to NeuRAG. A concept
reinforced across 200 turns — high salience, high trust, stable — stays in the decaying
store forever and never becomes permanent knowledge.

**Deliverable (Phase 5, GM-only):** consolidation promotes Neuron concepts above a
salience × trust × age threshold into NeuRAG nodes, tagged with the tag they already
share. GM's bridges currently *observe* the correlation; this *acts* on it.

Standalone Neuron keeps working with no promotion — that is not a degraded mode, it is
Neuron as it is today (I2).

### 5.4 Encoding specificity (Tulving)

Retrieval succeeds when the cue resembles the encoding context. Three consequences, all
in `chunker.py`, and **this is priority zero** — spreading activation over a
beautifully linked graph still returns truncated chunks if the encoder never saw past
token 128:

- **A token ceiling.** There is none anywhere in the repo (grepped: no `max_tokens`,
  `truncate`, `max_chars`). `chunk_markdown` emits one chunk per `##` section with only a
  *minimum*; `chunk_python_ast` one per class. Anything past the model window
  (128–512 depending on model — the default multilingual MiniLM is at the small end) is
  **silently unsearchable**. No error, results just quietly get worse with file size.
- **Heading breadcrumb prepended before embedding.** A chunk under
  `# Install / ## Windows / ### venv` currently embeds without any of those words.
- **Overlap** (~10–15%) so a definition on a boundary is not lost to both sides.

Plus: `chunk_markdown` matches `#{2,4}`, so H1 never splits and H5/H6 never split; and
PDF chunks per page, an arbitrary boundary that routinely exceeds the window.

### 5.5 What we deliberately do not borrow

- **Forgetting content.** I5. The vault is right and the biology agrees.
- **Spreading activation as *generator*.** ADR-003 chose "engine as selector, not
  generator" because of noise. The reasoning is stronger here: a knowledge base that
  free-associates is one you stop trusting.
- **Spiking, refractory periods, neuromodulation.** Zero retrieval payoff.

---

## 6. Phases

Each phase ships green, standalone (I2), and with the GUI verified (I7).

| # | Phase | Files | Gate |
|---|---|---|---|
| **P0** ✅ | **Turn the graph on.** `add_tags()` + `index_into_node` populates `nodes.tags`; `MIN_TAG_JACCARD=0.15` restored; `build_crossref_links` replaced with the designed trigger-mention scan (`MIN_CROSSREF_MENTIONS=2`, whole-word matching); `upsert_link(commit=False)` so a bulk build is one transaction. | `neurag/db.py`, `tests/test_node_links.py` | ✅ same fixture: `{tag_overlap: 0, cross_ref: 0}` → `{1, 2}`. `neurag/tests` 136 passed. Gate added: `test_auto_ingest_actually_produces_links` |
| **P1** ✅ | **Tag substrate.** `tags`/`node_tags`/`chunk_tags` + idempotent migration from the legacy JSON column (`meta.tags_migrated`); names normalized so they are a real join key; IDF suppression at `MAX_TAG_NODE_RATIO=0.5` / `MIN_TAG_NODE_FLOOR=50`; `build_tag_links` reads the index instead of parsing every node. `salience`/`last_used` columns exist with no writer yet — P5 owns the Hebbian half. Legacy columns kept as read path. | `neurag/db.py`, `tests/test_tag_substrate.py` | ✅ migration idempotent (asserted on a reopened file vault); link count identical to the legacy JSON computation on the same fixture. 206 passed |
| **P2** ✅ | **Encoding.** Ceiling derived from the live tokenizer (`embedder.max_chars_for`), breadcrumb `section` embedded with the body, 12% overlap taken *out* of the budget, H1–H6 split, single enforcement point at `chunk_file`. Plus: idempotent re-ingest, and generated-artefact dirs skipped. | `neurag/chunker.py`, `embedder.py`, `db.py`, `ingest.py`, `settings.py` | ✅ 77.3% of corpus text was unreachable → 0%. `neurag/tests` 154 passed |
| **P3** ✅ | **Retrieval.** RRF hybrid (both rankers always run), BM25 replacing length-unnormalised TF-IDF, `node_id` subtree scope, MMR (λ=0.7), e5 `query:`/`passage:` prefixes, `.sh`/`.ps1`/`.sql`/`.c`/`.cs`/… made indexable, plus `reindex` + the embed-model guard. | `neurag/db.py`, `embedder.py`, `chunker.py`, `cli.py`, `server.py`, `gray_matter/catalog.py` | ✅ recall@5 **67% → 94%** vs the shipped vector-only. 195 passed |
| **P4** ✅ | **Layers.** `nodes.layer`/`last_used` + `_ensure_columns` (the first column migration); L1 session cache ported from Neuron, with a wall-clock bound it does not need; parking by inactivity × link weight, DRY RUN unless `--apply`; half-life decay of link weight and tag salience, reinforced by use; `recall` = search across every layer. CLI: `park`, `unpark`, `decay`, `recall`, `query --deep`. No new settings knob, so the 6 installers are untouched. | `neurag/db.py`, `cli.py`, `tests/test_layers.py` | ✅ I5 asserted: park → re-ingest → rebuild → decay → restart → `recall` returns byte-identical. 239 passed |
| **P5** ✅ | **Brain.** `origin` on `node_links` (+ `upsert_link` refusing to let a derived write clobber a learned one); `confirm()` = Hebbian on confirmation, cooldown 2 queries, promotion at 3/8 — as a weight FLOOR, since NeuRAG's weights are floats and a threshold assignment would demote a strong link; `spreading_activation` + `related_nodes`. MCP: `knowledge_confirm`, `knowledge_related`. CLI: `confirm`, `related`. | `neurag/db.py`, `server.py`, `cli.py`, `tests/test_hebbian.py` | ✅ curated and Hebbian-promoted links both survive `rebuild_links`. 260 passed |
| **P6** | **Cross-tool (GM only).** CLS consolidation Neuron→NeuRAG; bridges join on tag ids; stimuli enriched with knowledge. | `gray_matter/bridges.py`, `server.py`, `neuron/…/stimulus.py` | all of P0–P5 still green with GM absent |
| **P7** | **Installers + GUI.** Any new knob → 6 scripts + parity features; GUI panels for reindex, tags, link health. | `install.ps1`/`.sh` ×3, `webgui.*`, `settings.py` | `test_installer_parity.py` extended in the same commit |

**P2 before P3.** Better ranking over truncated chunks is polish on top of data loss.

---

## 6b. Measured results (P0 + P2, 2026-07-29)

**The window is 128 tokens, not 512.** `fastembed.list_supported_models()` reports
`max_length: None` for every model we ship, so it had to be measured: appending text
until the vector stops moving puts the truncation point at **488 chars = exactly 128
tokens**, and the tokenizer confirms `{'max_length': 128}`. Both MiniLM options are 128.
The ceiling is therefore read from the live tokenizer at runtime rather than hardcoded —
pick a model with a real 512 window and chunks grow automatically.

**How much was being lost.** Chunking the `neurag/` tree, before vs after:

| | chunks | p50 | max | over window | text unreachable |
|---|---:|---:|---:|---:|---:|
| before | 1310 | 1566 | **164289** | 77.7% | **1 940 125 / 2 510 779 = 77.3%** |
| after | 8508 | 359 | 400 | 0% | 0% |

Three quarters of the corpus was stored, displayed, and silently absent from every
vector. The single largest chunk was 164k characters, of which 490 were embedded.

**Two defects found while verifying, both fixed:**

* **Re-ingest duplicated everything.** Nodes were reused, chunks appended: running
  `neurag ingest` twice doubled the vault, three times tripled it. This also blocked the
  P2 rollout — the only way to re-chunk an existing vault is to re-ingest it.
  `index_into_node` now replaces a source's chunks, which makes re-indexing free.
* **Generated artefacts were being ingested as knowledge.** `graphify-out/cache` JSON —
  path indexes, not prose — produced 8352 chunks instead of 1571 (81% junk) and poisoned
  linking: every project name appeared as a token in every chunk, so the `cache` node
  came out linked to six nodes at weight 1.0. Added to `_SKIP_DIRS`.

**Link quality after both.** `tag_overlap: 1, cross_ref: 79` on the `neurag/` tree, and
the top edges are real: `clients ↔ hooks`, `claude-code-hook ↔ hooks`,
`neuron-guard → claude-code-hook`, `neuron-usage → neurag · skills`.

**Retrieval, measured (P3).** recall@5 over 18 queries on the `neurag/` tree, half exact
identifiers (`vector_distance_cos`, `GM_NO_CLIENT_REGISTER`, `pyvenv.cfg`) and half
conceptual paraphrases in IT and EN:

| retriever | recall@5 |
|---|---:|
| vector only — **what shipped** | 67% |
| lexical only | 94% |
| **hybrid RRF** | **94%** |

The gain over what shipped is 27 points. Hybrid does not beat the better half on this
set, and that is not the point: vector-only failed an entire *class* of query
(identifiers, flags, error strings), and fusion means no class can fail that way again.
The single remaining miss — "how are duplicate nodes merged" → `consolidat` — is missed
by both retrievers; a genuine hard paraphrase, recorded rather than tuned away.

One finding came out of the benchmark rather than the code: `.sh`, `.ps1`, `.cmd`,
`.sql`, `.c`, `.cs`, `.html` were absent from `_SUPPORTED_EXTENSIONS`, so the installers
— the most-discussed files in this suite — could not be indexed at all. A query for
`pyvenv.cfg` was unanswerable because the only file containing it was never ingested.

**A note on tuning constants.** IDF suppression (`MAX_CUE_DOC_RATIO`) shipped as a bare
ratio and broke `build_crossref_links` on small vaults — at 3 chunks, `int(3 * 0.10)`
is 0, so a cap of 1 suppressed every genuine cue and the function returned 0 again, the
exact bug P0 fixed. A ratio needs an absolute floor (`MIN_CUE_DOC_FLOOR = 50`). The
tests caught it; keep every threshold in §8 on the same "report before act" discipline.

---

## 7. Verification

- **Link layer:** the fixture from §0 must produce non-zero `tag_overlap` *and*
  `cross_ref`. That single assertion would have caught the whole defect.
- **Retrieval:** a fixed ~30-query set over a fixed corpus, IT and EN, with known-good
  answers. Recall@5 and MRR recorded per phase. No phase may regress the previous.
  **Built 2026-07-30:** `bench/queries.json` + `bench/run.py`, recorded in
  `bench/results/`. P5 baseline: recall@5 0.967 / MRR@10 0.823 overall, and the
  reading that matters is per kind — identifier 1.000/0.867, concept 0.933/0.780.
  Read `bench/run.py`'s header before comparing two numbers: the corpus is this
  repo, recall@5 is close to saturated on it, and the identifier half is
  mechanically derived from disk so that only the concept half is a judgement.
- **Standalone matrix (I2) — the primary gate.** Every phase runs the retrieval
  benchmark in all three configurations, and the *first column is the one that must be
  good*:

  | Configuration | Requirement |
  |---|---|
  | **NeuRAG alone** | full P0–P5 quality: hybrid retrieval, real graph, layers, Hebbian. The benchmark target is set here. |
  | NeuRAG + Neuron | same, plus shared vector space and concept-driven entry points |
  | NeuRAG + Neuron + GM | same, plus bridges, CLS promotion, stimulus enrichment |

  A gain that only appears in column 2 or 3 is a design error, not a feature. Enforced
  structurally too: no top-level import of `neuron` or `gray_matter` anywhere in
  `neurag/`, and no top-level import of `gray_matter` in `neuron/` — assert on the
  import graph, not on intent.
- **Nothing deleted (I5):** park a node, park a chunk, run consolidation, re-ingest —
  then `recall` every parked item and assert byte-identical content returns.
- **Installers (I1):** `test_installer_parity.py`, extended with every new knob.
  Line-ending rules already covered; fix the current CRLF violation first.
- **Engine (I4):** `status()["engine"]` reports a Turso tier; the sqlite3 path is
  exercised only in the degradation test.
  **2026-07-30 — the degradation was fiction.** `sqlite3.connect` appeared
  nowhere in `db.py`. When pyturso could not open a file the branch set
  `_conn = None`, `_init_schema` then failed on `NoneType`, and the vault was
  reported CORRUPT. This is not theoretical: the live vault reported corrupt for
  exactly this reason, because the MCP server holds pyturso's exclusive lock and
  a second process could not take it. sqlite3 opens and reads that same file
  fine. The tier is now real, `_open_local_turso` reports *why* it failed, and
  `open_failure_message()` keeps "locked" from being answered with
  `--wipe-knowledge`. Note for whoever measures next: on the sqlite3 tier the
  vector leg is an O(N) Python cosine, so a benchmark run there measures ranking
  quality, not engine speed.
- **GUI (I7):** manual pass at the end of every phase — new knob visible, `reindex`
  reachable, link panel non-empty, IT/EN strings present.

---

## 8. Open questions

1. **Parking thresholds** — inactivity × link weight, and NeuRAG should park far more
   reluctantly than Neuron (§3). The cut points need real corpus data, so ship P4 with
   parking disabled by default and a `--dry-run` report first. Constants, not literals,
   in the shape of `RANK_WEIGHTS`.

   **First corpus data (2026-07-30, the `neurag/` tree: 16 nodes, 2117 chunks).** With
   `max_link_weight = 0.25`, *every node that holds chunks is above the threshold* —
   0.458 for the godnode, 0.571–1.0 for the rest — so parking cannot fire at all. Only
   the two empty directories (`_gm_vendor`, `assets`) were ever candidates. That is the
   reluctance working as intended on a small densely cross-referenced repo, but it means
   the current cut points are untested against the case they exist for: a large vault of
   loosely related documents, where `cross_ref` weights are far lower. The threshold to
   revisit first is `max_link_weight`, and the number to collect is the distribution of
   `MAX(weight)` per node on a real personal vault — not another repo.
2. **Promotion threshold for CLS** (P6) — salience × trust × age. Same approach: report
   first, act later, tunable constants like `RANK_WEIGHTS`.
3. **Re-index cost at scale.** A model change on a 50k-chunk vault is a long job. Needs
   the background-job pattern `ingest.start_job` already uses, plus resumability.
4. ~~**Chunk-level vs node-level tags.**~~ **ANSWERED 2026-07-30: they do not,
   and `chunk_tags` is parked.** Measured on a real vault: 9360 rows for 2117
   chunks, ~4.4 per chunk, and no reader in any of the three repos — linking
   reads `node_tags`, IDF (`tags.uses`) counts `node_tags`, and Gray Matter's
   tag join goes through `node_tag_names`, which is `node_tags` again. Write
   cost and disk for a join nobody was making. `add_chunk` no longer writes it;
   the table, its legacy rows, the cleanup sites and the `health()` audit all
   stay (I5), and a future reader repopulates by re-ingesting, since the data is
   derived from chunker tags rather than owned here.

---

## 9. Not in scope

- Neuron's installer/registration duplication. `clients.py` exists three times because
  standalone is a **requirement** (I2), not scope creep. The shape can be improved later
  with the one-asset-deployed-by-all pattern already proven this release for
  `neuron_sessionstart_hook.py` — Neuron loses nothing standalone. Separate effort.
- ~~`neuron/src/neuron/engine.py` — 1,133 lines imported by nothing in any repo, tests
  included. Unrelated dead code; delete whenever convenient.~~
  **Correction 2026-07-30: this was wrong, and acting on it would have broken
  something.** `scripts/run_interactive.py` imports it. Nothing in the *package*
  or the tests does, which is presumably how the claim got written — but "delete
  whenever convenient" against a file with a live importer is exactly the note
  someone acts on without re-checking. If it should go, the script goes with it,
  and that is a decision rather than a cleanup.
