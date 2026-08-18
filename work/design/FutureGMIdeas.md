# Future Gray Matter Ideas

Deferred during the 2026-07-28 deploy-readiness audit. Not scheduled — pick up
only if a concrete need shows up, and only after verifying it's actually
better in production, not just in a synthetic measurement. Each idea below
lists what "better" would need to mean before it's worth building.

---

## 1. Selectable embedding model (multilingual / English-only / Italian-only)

**The idea:** let the user pick their embedding model at install time (GUI
question, per Claudio's call — not the CLI installers) and change it later
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

**Why it's parked:** Claudio's call — running the full suite (GM + Neuron +
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
