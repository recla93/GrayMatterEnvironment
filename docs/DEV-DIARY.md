# Development Diary — Neural Stimulus → Neuron → Gray Matter

> A chronological record of the project's evolution. Version numbers reflect actual releases.
> Technical details verified against source code where available.

---

## v1.0 — NeuralStimulus: LLM as Engine (early July 2026)

**The idea:** Give LLMs a persistent semantic memory by instructing them to build a concept graph through conversation. No external NLP, no separate extraction pipeline — the model IS the extraction engine.

**Architecture:** A single Python file (`neural_stimulus.py`) exposed factory functions (`create_local`, `create_openai`, etc.) that wrapped any LLM client. The skill file (SKILL.md) taught the LLM a 5-phase loop:

1. **Extract** — model produces topic, keywords, entities, intent, sentiment, domain from each message
2. **Link** — model compares new keywords with previous turns, creates typed semantic links (cause-effect, analogy, evolution, contrast, deepening, instance-of)
3. **Inject** — build invisible cognitive substrate from most salient connections
4. **Output** — respond enriched by the substrate, append link summary
5. **Update** — save new nodes, bump inactivity counters, prune expired tangential links

**Why it worked:** LLMs are already good at understanding semantic relationships. Making them explicit about it (forcing structured output) created a feedback loop where each conversation strengthened the next one. The graph was the model's "working memory" across sessions.

**Why it was limited:** Graph lived in memory only. Every session started cold. The LLM had to re-extract everything. And the extraction + linking consumed tokens — in long sessions, the overhead became noticeable.

**6 modules (M1-M6):** Sentiment tracking, domain boost, periodic summary, semantic flashbacks, dual model (fast extraction + slow response), salience scoring. All optional, all toggled via constructor args.

---

## v2.0 — Persistence + Deduplication (mid-July 2026)

**Problem solved:** Zero context loss between sessions. The graph now persisted to SQLite.

**Key technical decisions:**

- **SQLite over in-memory:** Simplest possible persistence. No server, no daemon, just a file. The tradeoff is no concurrent access, but at this stage it was single-user, single-process.

- **Keyword deduplication (M7):** Without it, a 50-turn session could create 200+ nodes with near-duplicates ("kotlin" and "Kotlin" and "kotlin_lang"). The dedup screen compares new keywords against existing ones before creating nodes. This was the first step toward the `find_candidates` tool that became central in later versions.

- **Link enrichment:** The linking prompt was improved — instead of just seeing keyword names, the LLM now received the domain and topic of each previous node. This made link types more accurate (less "instance-of" spam, more genuine "deepening" and "cause-effect").

- **Link diversity filter:** Hard cap — no single link type can exceed 50% of new links per turn. This prevented the `instance-of` bias where the model would connect everything as "X is an instance of Y" instead of finding richer relationships.

- **Health indicators:** `status()` and `summary()` exposed metrics: strong/medium ratio (>40% = healthy), link type variety (3+ types = good), nodes-per-turn average (3-5 = healthy, >8 = keywords too granular). These became the foundation for the `introspect` tool in v5.

**What was still missing:** No MCP protocol. The LLM ran Python code directly. This meant every client needed the Python library installed, and the graph was coupled to the LLM's execution environment.

---

## v3.0 — MCP Server + Vector Search (mid-July 2026)

**The pivot:** From "LLM runs Python" to "LLM calls tools." This was the single most important architectural decision in the project's history.

**Why MCP:** The Model Context Protocol standardized how AI assistants talk to external tools. Instead of writing provider-specific integration code, one MCP server worked with OpenCode, Claude Desktop, Cursor, VS Code, and 8+ other clients. The install-once-use-everywhere dream.

**Architecture shift:**
- `mcp_server.py` exposed 12 tools via MCP stdio transport
- The LLM called `ns_store_turn(...)`, `ns_get_context(...)` etc. instead of running `NeuralStimulus.chat()`
- The server was stateless from the LLM's perspective — it stored and queried, the LLM decided what to save
- Separation of concerns: MCP server = storage engine, LLM = intelligence layer

**256-dim feature hashing:** Before fastembed, embeddings were computed via MD5 on character n-grams:

```
keyword → lowercase → extract 2-gram and 3-gram
→ for each n-gram: MD5(position) + MD5(sign)
→ sum contributions into 256-dim vector
→ L2 normalize
```

Zero dependencies (just `hashlib` + `struct`), deterministic (same keyword → same vector everywhere), fast. The downside: semantically weak. "database" and "Data" shared n-grams so they were close, but "Kubernetes" and "container orchestration" were unrelated despite being semantically linked. This limitation drove the move to real embeddings in v4.

**Turso Database:** The first use of Turso (libSQL, SQLite fork with native vector support). The installer compiled pyturso from Rust source on Windows (~10-30 min first time). Fallback to sqlite3 if compilation failed. This 3-tier pattern (cloud → local Turso → sqlite3) became the foundation for all future storage.

**Installer complexity:** `install.ps1` had to handle: Python version check, Rust toolchain installation, MSVC linker detection (fallback to GNU/MinGW), pyturso compilation, MCP SDK installation, client config registration. This was the first sign that deployment would need a dedicated orchestrator — which became Gray Matter.

---

## v4.0 — Real Embeddings + Cognitive Architecture (late July 2026)

**The upgrade that changed everything:** 256-dim feature hashing → fastembed 384-dim neural embeddings via ONNX runtime.

**Why fastembed:** Native Turso `vector_distance_cos()` ran server-side, but the quality of 256-dim feature hashing was insufficient for real semantic search. fastembed gave us:
- Real neural embeddings (sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
- 384-dim vectors with actual semantic meaning
- Multilingual support (Italian works without separate model)
- ONNX runtime — no PyTorch dependency, fast inference

**The embedding pipeline:**
1. Keyword text → fastembed model → 384-dim float32 vector
2. Vector packed with `struct.pack` into 1536-byte BLOB
3. Stored in `node_vectors` table (composite PK: context + keyword)
4. Search: `vector_distance_cos(f32blob(stored), f32blob(query))` in SQL, or Python brute-force on sqlite3 fallback

**Context hierarchy:** Keywords got parent-child relationships. `get_context` traverses 1-3 hops, building a tree of related concepts. This enabled "zoom in" (specific child) and "zoom out" (parent context) behavior.

**Hebbian reinforcement — the learning mechanism:**
- `co_activation_count` on each link tracks how often two keywords appear in the same turn
- Cooldown: at most one count per `HEBBIAN_COOLDOWN` (default 2) turns on the same link
- Promotion: tangential → medium at 3 co-activations, medium → strong at 8
- Monotone: never downgrades. Once strong, always strong (unless pruned)
- This is how the system "learns" which concepts belong together — through repeated co-occurrence

**Domain drift — cross-pollination:**
- When a keyword from a *different* context surfaces alongside current keywords, a drift link forms
- Born tangential, strict rules: max one drift link per `DRIFT_COOLDOWN` (5) turns per pair
- Decays faster than regular tangentials: `DRIFT_EXPIRY_TURNS` = 3 (vs 5 for regular)
- Purpose: serendipitous connections between unrelated domains. "You mentioned Redis in a Spring context — that connects to the caching discussion from last week."

**Semantic flashbacks — lateral recall:**
- Every 5-7 turns, probe for strong links to concepts from 3+ turns ago
- Result: "This connects back to turn N regarding [previous_topic]"
- Enriches without forcing the reference — the model decides if it's relevant

**Sleep mode — automatic housekeeping:**
- After 30 min idle (`NEURON_SLEEP_IDLE_SECONDS`), next load triggers consolidation
- Consolidation: merge near-duplicate nodes, archive low-salience orphans to `_graveyard`
- Pre-stage top stimulus so the next `pre_turn` serves it "warm"
- Staged stimulus valid for 6h (`NEURON_STAGE_FRESH_SECONDS`)

**Episodic memory — facts, not just themes:**
- Nodes carry compact facts (max 200 chars, ~40 tokens)
- Max 5 episodes per node; oldest dropped during consolidation
- `pre_turn` surfaces these as one-liner facts alongside the thematic context
- This bridged the gap between "this node is about Kotlin" and "Kotlin coroutine scope was discussed on 2026-07-18"

**The rename:** Neural Stimulus → **Neuron**. The project had outgrown its name. It wasn't a "stimulus" anymore — it was a memory system.

---

## v5.0-5.5 — Trust, Safety, Gateway Prelude (July 18-21, 2026)

A rapid series of releases that added the social and safety layer.

### v5.4.2 — Safety
- `reset` requires `confirm=true` — prevents accidental graph destruction
- POSIX sh launcher + macOS pipx shortcut — cross-platform without Electron

### v5.5.0 — Serendipity v2
- `near=` parameter on `forgotten`: mid-band similarity selector (0.30-0.75 cosine distance)
- Finds concepts that are *related but not obvious* — serendipity over precision
- Optional GM autoregister (`NEURON_NO_GM` opt-out) — first step toward gateway architecture

---

## v5.6.0 — The Gateway Flip (2026-07-18)

**The problem:** Users had to configure 2-3 MCP servers separately (Neuron + NeuRAG + optional GM). Each AI assistant needed individual registration. No cross-store learning.

**The solution:** One MCP server (Gray Matter) re-publishes all tools. Users connect once. GM orchestrates Neuron and NeuRAG as persistent worker subprocesses.

**How the gateway works:**

```
AI Client → MCP stdio → Gray Matter daemon (:9876)
                              │
                    ┌─────────┴─────────┐
                    │                   │
              Neuron worker        NeuRAG worker
              (persistent)         (persistent)
```

- **Worker processes** (`_worker.py`): persistent Python subprocesses that import Neuron/NeuRAG once and stay warm. IPC via length-prefixed TCP (4 bytes length + payload). Replaced per-call re-imports (F0) that caused 2-5s cold starts.

- **Daemon singleton:** exclusive bind on :9876 using `SO_EXCLUSIVEADDRUSE` (Windows). Without this, Claude Desktop's 2 MCP clients (chat + host) could spawn 2 daemon instances. The losing bind kills the duplicate.

- **Stdio handshake:** `InitializationOptions` must include `capabilities` (MCP spec requirement) + GM instructions (the pre_turn/store_turn loop guidance). Without capabilities, the first stdio startup crashes — never seen before because only the daemon was tested.

- **Tool pass-through (F12):** Worker's `list_tools` → cache in `ServerEntry.tool_schemas` → GM's `list_tools` republishes real schemas. Without this, clients saw empty `inputSchema` and couldn't validate tool calls.

**Trust system:**
- `Node.trust: float` column (REAL DEFAULT 0)
- Atomic delta: `UPDATE nodes SET trust = MAX(0, trust + ?)` — no read-modify-write race
- `confirm(confidence)` with confidence in [-1, 1]: positive boosts trust, negative refutes
- Trust propagated in merge/dedup (max of the two)
- Integrated into ranking: `score = w1·sim + w2·salience + w3·recency + w4·trust`

**Refs table — structured provenance:**
- `refs(context, keyword, path, project_id, by)` with natural PK
- No blob JSON (which caused read-modify-write clobber between concurrent writers)
- Append-only: two writers adding refs to the same node get two separate rows
- `project_id` from `.neuron/project.json` marker (UUID, travels with shared folder)
- `by` = provenance tag, not ACL. "Who touched what" without permission semantics.

**Installer unification:**
- Canonical `install.ps1` / `install.sh` delegates to GM's CLI
- Thin launchers in each repo point to the canonical installer
- `uninstall.sh` simplified to thin wrapper on `gray-matter uninstall`

---

## v6.0.0 — First Public Release (2026-07-21)

The consolidation release. Everything from v5.5.x-5.6.0, tagged and stable.

**Three components, one install:**

| Component | Version | Tools | Storage |
|---|---|---|---|
| Neuron | 6.0.0 | 33 | Turso cloud → local pyturso → sqlite3 |
| NeuRAG | 1.0.0 | 12 | Local pyturso → sqlite3 (separate DB) |
| Gray Matter | 1.0.0 | 3 pass-through + 10 own | Worker orchestration, cache, bridges |

**NeuRAG — the knowledge base that Neuron isn't:**

Neuron is episodic (learns from conversation). NeuRAG is factual (stores documents). The distinction matters:

- **Neuron:** "We discussed Kotlin coroutines on July 18" — ephemeral, learning, decays
- **NeuRAG:** "Kotlin coroutines documentation says..." — permanent, factual, never decays

NeuRAG's features:
- Three-tier hierarchy: godnode → fundamental → specialization
- AST chunking for code (functions/classes as chunks, symbol tags merged into triggers)
- Multi-format: .md, .py, .kt, .java, .pdf, .docx, .yaml
- Source attribution in query results
- Knowledge neighbors (BFS at depth 2, "Potrebbe interessarti: ...")
- Link graph with weights and evidence (tag_overlap, cross_ref)

**Gray Matter — the orchestrator:**

- `pulse` = parallel Neuron context + NeuRAG knowledge + flash + neighbors
- Context cache with dynamic TTL: +50% per hit, cap 3x, heat preserved across refresh
- Multi-turn buffer: deque of 3 recent topics, expands NeuRAG query (cap 300 char)
- Bridge system: cross-store links with Hebbian learning (weight +1 per use, cap 1000; decay -1 after 7 days idle; auto-confirm at weight ≥ 5)
- Web GUI: setup wizard (checkbox Neuron/NeuRAG), preferences panel, Turso cloud panel
- Worker pre-warm: spawn + cheap read at startup, loads fastembed before first pulse

**The 3-tier storage engine (Neuron):**

```
TURSO_DATABASE_URL + TURSO_AUTH_TOKEN set?
  ├─ YES → libsql-client (HTTP to Turso Cloud)
  │        vector_distance_cos() server-side
  └─ NO → pyturso installed?
           ├─ YES → embedded libSQL engine
           │        vector_distance_cos() native
           └─ NO → stdlib sqlite3
                    Python brute-force cosine
```

The same pattern in NeuRAG (without the cloud tier):
```
pyturso installed?
  ├─ YES → embedded libSQL (vector_distance_cos native)
  └─ NO → sqlite3 + Python cosine or TF-IDF
```

---

## v6.0.1 — Patch (2026-07-22)

Bump release. v6.0.0 installed before the `COMMANDS` refactor in `__main__.py` — the control center GUI showed an empty Neuron section because 0 subcommands were registered. No code changes, just forces reinstall.

---

## Open Threads (as of 2026-07-22)

| Thread | Status | Impact |
|---|---|---|
| L2 daemon WAL race | ◐ Mitigated (retry 3x + degrade sqlite3) | `store_turn` intermittently fails under concurrent GM workers on same DB file |
| Incremental indexing (D5) | Not started | `neurag watch <dir>` for auto-reindexing on file changes |
| NeuRAG semantic coherence L2 | Not started | Chunk outlier detection, near-duplicate merging |
| NeuRAG consistency L3 | Not started | Internal tension detection, LLM-assisted resolution |

---

## Key Architectural Decisions — Summary

| Decision | Why | Tradeoff |
|---|---|---|
| LLM as extraction engine | No NLP pipeline to maintain; model already understands semantics | Token overhead; extraction quality depends on model |
| MCP protocol | One server works with 12+ clients; standardized interface | Locked to stdio transport; no streaming |
| fastembed over feature hashing | Real semantic similarity; multilingual | ~500MB ONNX model; cold start 2-5s |
| Turso over raw SQLite | Native vector SQL; cloud sync possible | Rust compilation on Windows; extra dependency |
| Gray Matter as gateway | Single connection point; parallel workers; cache | Extra process; IPC complexity; daemon management |
| Hebbian learning | Automatic concept strengthening through use | No downgrade path; requires co-occurrence to learn |
| Trust as float (0-1) | Fine-grained; atomic updates; propagated in merge | Extra column; extra ranking weight to tune |
| Refs as table (not JSON blob) | Append-only; no clobber; structured provenance | Extra table; extra query in store_turn |

---

*Technical details verified against source code: `db.py`, `models.py`, `server.py`, `config.py` (Neuron), `db.py`, `embedder.py`, `reranker.py` (NeuRAG), `server.py`, `_worker.py`, `bridges.py`, `cache.py` (Gray Matter).*
