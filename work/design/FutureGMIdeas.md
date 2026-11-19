# Future Gray Matter Ideas

Deferred during the 2026-07-28 deploy-readiness audit. Not scheduled — pick up
only if a concrete need shows up, and only after verifying it's actually
better in production, not just in a synthetic measurement. Each idea below
lists what "better" would need to mean before it's worth building.

---

## 1. Selectable embedding model (multilingual / English-only / Italian-only)

**The idea:** let the user pick their embedding model at install time (GUI
question, a product decision — not the CLI installers) and change it later
from GM's GUI. Three options, all measured for real resident memory on this
machine (2026-07-28, worker process, `threads=2, enable_cpu_mem_arena=False`):

| Option | Model | Languages | Measured memory | Notes |
|---|---|---|---|---|
| Multilingual, quantized | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, `onnx/model_qint8_avx512_vnni.onnx` | IT+EN | ~549 MB | Same architecture as current default, official quantized build from the model's own HF repo. 384-dim, no re-embed needed. |
| English only | `sentence-transformers/all-MiniLM-L6-v2` | EN | ~267 MB | Already in fastembed's built-in catalog. 384-dim. Smaller architecture (6 layers vs 12), not just quantization. |
| Italian only | `nickprock/sentence-bert-base-italian-uncased`, `onnx/model_qint8_avx512_vnni.onnx` | IT | ~295 MB | **Third-party model**, not maintained by fastembed/sentence-transformers. 768-dim (not 384) — sets `NS_EMBED_DIM=768`. Not in fastembed's default catalog; needs `TextEmbedding.add_custom_model()`. |

Current unquantized default (`paraphrase-multilingual-MiniLM-L12-v2`, fp32):
~700 MB, for comparison.

**What's already there to build on:**
- `NS_EMBED_MODEL` / `NEURAG_EMBED_MODEL` env vars already select the model
  (`neuron/src/neuron/server.py:175-185`); NeuRAG already falls back to
  Neuron's value ("one env governs the suite").
- `NS_EMBED_DIM` already overrides the vector dimension dynamically —
  `pack_vector`/`unpack_vector` are dimension-agnostic, and there's already a
  graceful mismatch guard (`models.py:1650-1662`) that detects a model-name OR
  dimension change and safely ignores + recomputes stale vectors instead of
  crashing or silently corrupting. Confirmed by reading the code, not assumed.
- `neuron/scripts/reembed.py` already exists for "I changed my mind" —
  idempotent, `--dry-run` supported, per-context or `--all`.
- Adding a subcommand to `neuron/__main__.py`'s `COMMANDS` dict auto-surfaces
  it as a GUI button (dynamic command discovery, already how every other GM
  command reaches the GUI) — no `webgui.html` changes needed for the control
  itself, only for hooking a nicer settings/Prefs-style presentation if wanted.

**What would need to be true before building it for real:**
- The 3-way choice is worth the UX cost (one more install-time question, one
  more thing to explain) *only if* people actually want English-only or
  Italian-only, i.e. actually care about the last ~250MB after the free win
  below. Nobody's asked for this yet — it was found while profiling, not
  requested by a user.
- Semantic quality of the quantized models hasn't been checked at all here —
  only memory was measured. Before shipping, compare retrieval/recall quality
  (quantized vs fp32, and the Italian model vs the multilingual one on actual
  Italian text) — memory savings that come with a real recall regression
  aren't a win.
- The Italian model is an unvetted third-party dependency (single HF author).
  Worth a second look at maintenance status / license / any known issues
  before depending on it for anyone's actual memory store.
- Decide whether the quantized-multilingual swap (next section) alone is
  "good enough" — it needs none of the above risk and might make the 3-way
  choice unnecessary for most users.

---

## 2. Quantized multilingual as the new default (low-risk, standalone win)

Separate from #1 — this part doesn't require any install/GUI work at all,
doesn't touch language coverage, and doesn't need a decision from anyone:
swap the *current* default model to its own official quantized ONNX build
(row 1 of the table above). ~22% less resident memory per worker, same
384-dim space, existing mismatch guard handles the transition safely for
users with existing stores (falls back to the old model's vectors until
they're recomputed, prints a note pointing at `reembed.py`).

This is close to "just do it" — the main remaining work is registering the
custom ONNX build via `fastembed`'s `add_custom_model()` in both
`neuron/search.py` and `neurag/embedder.py` (they each construct their own
`TextEmbedding` independently, so the registration has to be duplicated,
matching the existing keep-in-sync pattern between the two files) and
re-verifying both test suites.

---

## 3. Share GM's worker pool across connected clients instead of one pair per client

**The problem, measured live on this machine (2026-07-28):** 25 gray-matter
processes, 4.4GB committed memory. Only one process is genuinely the IPC
coordination daemon (confirmed via `Get-NetTCPConnection` — exactly one PID
listening on the rendezvous port); everything else is per-client-app private
worker pairs (`gray_matter._worker neuron.server` / `neurag.server`), each
independently loading its own ~650-700MB embedding model. 3 connected client
apps ≈ 4+ GB just from this duplication.

**The idea:** route tool calls through the daemon's single shared worker pool
(new `call_tool` IPC action, `_call_server_async` prefers the daemon,
falls back to a local worker only if the daemon is unreachable — same
degrade-gracefully pattern already used in `bridge.py`/`tunnel.py`/`db.py`).

**Why it's parked:** a product decision — running the full suite (GM + Neuron +
NeuRAG together, one worker pair per client) is an accepted trade-off, not a
bug to be fixed reflexively. Revisit only if:
- Memory pressure becomes an actual, felt problem (not just a big number in a
  profiler) — e.g. on a machine with less RAM, or once 4+ clients are
  routinely connected simultaneously.
- The isolation cost (one client's slow/bad request briefly affecting
  another, once the per-server lock becomes cross-client instead of
  per-process) is judged acceptable for how this tool is actually used.

---

## 4. `store_turn` async save (the audit's old "D4")

`AUDIT-PERFORMANCE.md`'s D4 suggestion ("Store + pre-load async — background
during the write") sounds like a free latency win but isn't one on inspection:
`_g.save(ctx or None)` runs synchronously in `neuron/src/neuron/server.py:1341`
*before* `store_turn` returns, and the response text literally says "Turn N
saved." Backgrounding the save would make that message potentially false and
risks losing a turn if the process dies before the background write lands —
a real durability trade-off for a tool whose entire job is being a
*persistent* memory, not a safe drop-in perf fix.

**Revisit only if** someone explicitly decides the latency is worth that
trade-off — and if so, the fix should keep the "Turn N saved" message
honest (e.g. don't send it until the write actually lands, even if that
means the tool call itself still waits — moving the wait doesn't remove it,
it just relocates where the user perceives it).

---

## 5. Audit's D3 — dynamic cache TTL

Still on `AUDIT-PERFORMANCE.md`'s own list, still not done: `ContextCache`
uses a static TTL; the audit suggested making it adaptive. Not investigated
further during this session — no code read, no design proposed. Lowest
priority of the five; revisit if cache hit/miss behavior is ever observed to
be a real problem, not preemptively.

---

## 6. Turso panel — live connection status + fallback-tier display

2026-07-28: shipped the easy half of the HANDOFF-2026-07-26 TODO — the full
DB URL was already computed server-side (`gray_matter/webgui.py`'s
`cloud_state()`, truncated to 50 chars) but silently dropped by the frontend;
now rendered. What's still missing, and why it wasn't done in the same pass:

- **Live connection status** ("configured" only means the env vars are set,
  not that the DB actually answers). Doing this right needs an async probe
  (matches the `gm_answers()` pattern already used for the IPC daemon) —
  wiring that into `cloud_state()` synchronously would add real network
  latency to every GUI poll cycle, which is worse UX than the missing data.
- **Fallback-chain display** (which tier — cloud / local pyturso / sqlite3 —
  is actually active right now). The data isn't computed or surfaced by
  either tool's IPC status response today; would need a small addition to
  Neuron's/NeuRAG's own status tool output, then plumbing through
  `health_state()`, not just a frontend change like today's URL fix.

Revisit together, not separately — they're the same "is Turso actually
working" question a user would ask.

## 7. `promote` carries the memory, not just the name (2026-09-14)

**What's wrong today.** `_do_promote` (gray_matter/server.py) reads Neuron's
`export` — nodes and links, **no episodes** — and writes NeuRAG with
`knowledge_add_node(name, triggers)` only: **no chunks**. A promoted concept is
a bare label in the vault: no text, no embedding, `knowledge_query` never finds
it. The CLS "missing third" (neurag/DESIGN-EVOLUTION.md §5.3) is only half
built: the trace that made the concept stable never reaches the cortex.

**The idea.** NeuRAG becomes *knowledge with its history*: every promoted
concept lands with its episodes and its link rationales as chunks.

| NeuRAG chunk | Carries |
|---|---|
| `text` | the episode ("hook one line behind, repair run, doctor still red") or the link with its reason (`doctor -[contrast]-> repair: repair alone only wipes`) |
| `source` | provenance: `neuron:<context>/<keyword>` |
| `section` | when: `turn 138` (or a date, see below) |
| `embedding` | computed by NeuRAG — the fact becomes searchable |

Then a bridge `neuron:<kw> <-> neurag:<kw>` so `pulse` and `brainstorm` know the
two faces are one concept. Zero schema changes in NeuRAG (chunks already have
`source`/`section`/`created_at`).

**Steps (small):**
1. Neuron `export` adds `"episodes"` — one line, the only touch on Neuron.
2. `_do_promote`: after `add_node`, `add_chunks` with episodes + link rationales.
3. Auto-bridge for each written node.
4. Dry-run on the real `ai` graph (376 nodes) before `--apply`.

**Guard rail.** Promoted text does not decay (promote.py docstring). Keep the
three floors and the dry-run default; promote only the episodes recorded
*after* the node cleared `min_trust`, not all five — facts from when the concept
was still uncertain are the least reliable ones.

**Dates — deliberately NOT in Neuron.** Episodes carry `turn`, not a timestamp.
Decided 2026-09-14: leave the core alone. If dates are ever wanted, they go in a
GM sidecar (`turn_ts(context, turn, ts)` in the bridges SQLite), written by the
pass-through when `store_turn` answers "Turn N saved", joined at promote time.
Extension-table pattern (JPA `@SecondaryTable`): the entity does not know the
annotation exists; whoever needs it joins. Only GM-routed turns get a date —
fine, promote is GM-only anyway (I2).

**What "better" must mean:** a promoted concept is *found* by `knowledge_query`
on the text of one of its facts, and `brainstorm` on a bug seed surfaces a
past fix from the vault, not only from Neuron.

## 8. Pattern recognition: an isolated analysis module (2026-11-19, draft)

**Status: a draft to refine with the user.** The cycle below is agreed in
principle; every stage still needs its definitions, thresholds and a measure.

**The idea (the user's).** A workbench to dig through data and find
coincidences, recurring occurrences, cycles and footholds ("appigli"): numeric
series (markets, prices), historical occurrences, cycles of events, the
behaviour of people and companies observed every day. It is **analysis of the
data being worked**, not recall, and it stays isolated so that neither side
adds noise to the other.

**Not the old pattern mode.** That one (removed 2026-09-13, 0 right
predictions out of 155 turns) predicted the agent's next turn from recurring
concepts. Not PIANO-STRATI §G either (the agent's procedural layer).

### The user's method: a jigsaw puzzle

> You start from the frame: its pieces have fewer sides to match and follow a
> line. Once the frame is closed, you place the inner pieces: which one fits
> the other? Is it anomalous, out of routine? Does it break a habit, does it
> feel out of place? Then links form, and pieces that could not be seen
> before connect, because the missing piece was exactly that one.
>
> An anomaly is not a sure link. When it links to other events that shift the
> course slightly, they chain to everything else: that is where "something
> smells here" starts the deep investigation into occurrences and
> predictions. (The user predicts people, companies and things they observe
> daily this way, without thinking about it.)

This is a better method than "search every coincidence, then test it":
comparing each piece with a solid frame makes few comparisons, each with a
meaning, so the noise falls by construction.

### The cycle (the backbone)

| # | Stage | What it is | How (first idea) |
|---|---|---|---|
| 1 | **Frame** | The routine of each entity and series: typical values, cycles, usual sequences, the calendar | STL decomposition, baseline statistics, frequent sequences |
| 2 | **Frame check** | A crooked frame makes everything look out of place, or nothing | held-out data |
| 3 | **Out-of-place pieces** | A deviation from the frame, measured: how far, against what. Kept as an **open piece** (pending) until it fits or is discarded | stumpy (discords: the most unusual subsequences), residuals, ruptures (a habit that breaks) |
| 4 | **The chain** | Small deviations, each below the threshold, that link in sequence: through a shared entity or closeness in time. The signal is the accumulation, not the peak | CUSUM on the series; anomaly chains on the graph |
| 5 | **"Something smells"** | The chain crosses a threshold, calibrated on shuffled data (a chain that forms in noise too opens nothing) | an **investigation** object holding its chain of evidence |
| 6 | **Investigation** | Past occurrences of similar chains, what followed them, the missing piece (a link the structure expects and is absent) | graph: communities, bridges, link prediction; event study |
| 7 | **Prediction** | Written *before*: what, horizon, confidence | `predictions` table |
| 8 | **Score** | At the horizon, how it went; a per-domain track record | where the user's instinct is reliable, where it is not |

Every new piece is checked against the frame (stage 3) **and against the open
pieces**: the most valuable alert is "piece X connects open anomalies A and B",
the moment the user describes as seeing what could not be seen before.

**Two rules that keep it honest.** An anomaly is not a pattern: it becomes
one only when it connects or recurs, and the module keeps "out of place" and
"connected" apart. The feeling of "out of place" stays the user's: the module
measures and ranks, the user judges what matters.

### Application: announcements that move markets (phase 2)

The same cycle on one domain. Frame: how a person usually announces (time,
channel, tone, topic) and how the market usually reacts. Event: who, exact
time with time zone, channel, text, and the type and surprise classified by
the model. Measure: abnormal return net of the market, per speaker x type,
with a random-date placebo, confounding news excluded, pre-event drift noted,
held-out years. Live: a feed -> classify -> match confirmed hypotheses ->
alert with n and hit rate -> the outcome logged, so a pattern that stops
working loses its score. Out-of-routine announcements are probably the ones
that matter.

Limits: markets move on big announcements in seconds; the value is context
(what usually happens, how long it lasts, when it reverts) more than speed.
Intraday prices and real-time news are mostly paid; one person makes few
announcements of one type, so every alert shows n. History first, alerts
second.

### Engines and storage

| Data | Engine | Finds |
|---|---|---|
| Relational: people, places, events, dates | graph (networkx; Neuron's typed links as the model) | links, chains, recurring event types, gaps, bridges |
| Numeric series | statistics | routine, cycles, deviations, regime changes, lead-lag |
| Both | event study: a series aligned around the events' dates | what changes before and after an event |

SQLite as the store: one file, already in the suite. Turso only for cloud sync:
locally it adds nothing over SQLite (0.8.3: no vector index, no full-text
search). DuckDB for the analysis: column-oriented, it reads the SQLite file
directly and hands results to pandas. Dates in one form (ISO) plus derived
columns (weekday, month, quarter) computed at load time.

| Table | Holds |
|---|---|
| `series`, `observations(series_id, ts, value)` | numeric data |
| `events(ts, kind, place, text)`, `entities`, `event_entities` | relational data |
| `frames` | the routine per entity / series, with its check |
| `pieces` | deviations, open / connected / discarded |
| `investigations`, `evidence` | chains that crossed the threshold |
| `predictions` | what, horizon, confidence, outcome |
| `attempts` | every search run, counted (multiple-comparison correction) |

Libraries: pandas (or polars); statsmodels (STL, autocorrelation, CUSUM,
Granger, Benjamini-Hochberg) and scipy for the series; stumpy for motifs and
discords; ruptures for regime changes; a sequential-pattern miner for "A then
B within N days"; networkx for the graph. Heavy (several hundred MB with
numba): an optional extra of the module, never in the base suite.

**The model reasons, the code computes.** The model classifies texts,
proposes hypotheses and reads results; it never sees raw rows in its context.
Confirmed hypotheses move to NeuRAG with their evidence through the existing
bridges; rejected ones stay as `tried:` so they are not proposed again.

### Repository and place in the suite

A new folder in this monorepo, one more `prefix` in `mirror.yml`, published
to its own public repo like neuron, neurag and gray_matter: it shares the gate,
the isolated instance and the tests. Created when the work starts.

Neuron gains from it through the bridges (confirmed findings, the prediction
track record), not by absorbing it: the isolation is what keeps both clean.

**Not investment advice.** The module is an analysis tool; a pattern it finds
is a hypothesis to test, not a decision.

### To refine

- What a frame is per domain, and how long it must be observed before it counts.
- The distance that makes a piece "out of place", per kind of data.
- What links two pieces into a chain (shared entity, time window, similarity).
- The "something smells" threshold and its calibration on shuffled data.
- What an investigation shows the user, and how a prediction is written.
- The first domain and a case whose answer the user already knows.

**Gain / loss / worth it.**
- Gain: a real new use of the suite with a clear method; less noise by
  construction; an alert ("this piece connects the open ones") that no
  coincidence search would give; a track record of the user's own intuition.
- Loss: a new product, not an option: a module, ingest, frames per domain and
  a statistics engine to maintain, while the direction is consolidation.
- Worth it: yes as a direction, **after TODO P0-P3**. First prototype small:
  SQLite + DuckDB + pandas + stumpy, one domain, stages 1-5 only.

**What "better" must mean:** on a case whose answer the user already knows,
built blind, the known connections come out as chains above the threshold,
they do not form on shuffled data, and the predictions written before score
better than a naive "same as last time".
