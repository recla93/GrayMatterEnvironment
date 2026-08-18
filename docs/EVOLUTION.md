# Evolution

> How the Gray Matter Environment got here. Written by examining the code
> and CHANGELOG files. Gaps are marked — these need human input.

---

## Era 0 — Standalone Neuron (before July 2026)

**What existed:** Neuron as a standalone MCP server. Single process, single DB, 18 tools. Users called `neuron_pre_turn` and `neuron_store_turn` directly. No gateway, no orchestrator.

**What broke:** Users had to configure 2-3 MCP servers separately (Neuron + NeuRAG + optional GM). Each AI assistant needed individual registration. No cross-store learning — Neuron's episodic memory and NeuRAG's knowledge base were islands.

**What remains:** The core 18 Neuron tools, the Hebbian link system, the context hierarchy, the 3-tier storage engine. All still the foundation.

> **[FILL: exact version range, release tags, specific incidents that triggered the shift]**

---

## Era 1 — Gray Matter orchestrator (early July 2026)

**Idea:** One MCP server that re-publishes all tools. Users connect once. GM calls Neuron and NeuRAG in parallel via persistent workers.

**What happened:**
- GM v0.1.0 built as an orchestrator: `pulse` (parallel context+knowledge), `bridge` (cross-store links), `status`
- Worker processes (`_worker.py`) replaced per-call re-imports (F0)
- IPC via length-prefixed TCP (F1 fixed)

**What broke:**
- F19: Cache singleton was recreated inside every `pulse` — cache never hit
- F20: Cache cleared on topic change — never accumulated across alternating topics
- F12: Pass-through tools had empty `inputSchema` — clients couldn't validate tool calls

**What remains:** The gateway pattern, parallel workers, the 3-tool GM interface.

---

## Era 2 — Gateway flip (2026-07-18)

**What happened:** `gray-matter register --gateway` now evicts neuron/neurag from all client configs, registers only GM. Single daemon via exclusive bind (`SO_EXCLUSIVEADDRUSE`). Stdio handshake fixed (`InitializationOptions` now includes capabilities + GM instructions). GM serves 33 tools via pass-through with real schemas (F12).

**What broke:**
- Duplicate daemon instances (Claude Desktop spawns 2 MCP clients from 1 entry)
- L2: `store_turn → open: NotFound` — intermittent, traced to `_graphs.clear()` + WAL race between concurrent worker processes on the same DB file; mitigated with retry + degrade (2026-07-21)

**What remains:** All clients connect to one server. `.bak` backups enable rollback. Daemon singleton enforced by kernel.

---

## Era 3 — Trust + Refs + Projects (2026-07-20)

**What happened:**
- `Node.trust: float` column with atomic delta `MAX(0, trust + ?)`
- `confirm(confidence)` tool: boosts trust, propagated in merge/dedup, negative confidence = refute
- `refs` table: structured file/URL/commit references, append-only, natural PK
- `project.py`: `.neuron/project.json` marker, relative paths, provenance tracking
- Installer unification: canonical `install.ps1` / `install.sh` delegating to GM

**What remains:** Trust integrates into ranking. Refs enable file provenance. Projects isolate per-repo knowledge.

---

## Era 4 — Knowledge features (2026-07-20)

**What happened (NeuRAG):**
- `link_graph` + `rebuild_links`: node links with weights and evidence
- Source attribution in `knowledge_query` results (D1)
- `neighbors`: BFS neighborhood, structured JSON, SQL-only
- AST chunking: code chunked by function/class, symbol tags merged into triggers

**What happened (GM):**
- Worker pre-warm (`_prewarm_workers`: spawn + cheap read at startup)
- Multi-turn buffer (`_topic_buffer` deque of 3): expands NeuRAG query with recent context
- Dynamic cache TTL: +50% per hit, cap 3x, heat preserved across refresh
- Proactive knowledge: `neighbors` at depth 2 appended as "Potrebbe interessarti: ..."

**What remains:** The knowledge layer is complete for v1. Future: incremental indexing (D5), feedback loop.

---

## Era 5 — Documentation + Release prep (2026-07-20)

**What happened:**
- DOCS-GUIDELINES.md written (truth from code, single source, no duplication)
- Suite-level docs created: 8 ENG + 8 ITA files (OVERVIEW, ARCHITECTURE, CONFIGURATION, TOOLS, CLI, DATA, TROUBLESHOOTING, GETTING-STARTED)
- Per-project docs distributed
- Sapienziali (TECHNOLOGY, EVOLUTION, PROCESS) — this document is one of them
- Version drift resolved (2026-07-21): versions unified to Neuron 6.0.0, NeuRAG 1.0.0, Gray Matter 1.0.0 across pyproject, `__version__`, README, and docs
- Patch 6.0.1 (2026-07-22): bump per fix `COMMANDS` in `__main__.py` (control center vuoto senza subcomandi)

> **[FILL: release tag names, exact dates for eras 0-1, any incidents not listed]**

---

## Era 6 — The brain in the real servers (2026-08-03)

**What happened:** the "brain" vision moved from mocks into the real servers,
in four steps each verified with a runtime MCP test:
- `gray_matter/state.py`: sqlite blackboard with three tools (`state_set` /
  `state_get` / `state_delta`), TTL and versions on the keys. `state_delta`
  reports expired entries too — a consumer must be able to see that a key
  decayed, not just that it vanished.
- `neuron/src/neuron/modes.py`: four retrieval modes (`semantic` default,
  `focus`, `brainstorm`, `pattern`), applied inside `_resolve_context` *before*
  the sort, which now returns a sixth value, `pattern_hits`. `pattern` reads
  the append-only `turns.jsonl` log: the graph does not keep turn history, and
  `nd.turn` is the turn a node was *created*, not last touched — a cache keyed
  on it would have been wrong.
- Injection from the GM proxy: `_inject_neuron_mode` reads `cervello/mode` and
  `cervello/focus` from the blackboard and injects them into
  `get_context`/`pre_turn`. An explicit `mode` from the agent always wins.
- `gray_matter_brainstorm`: candidates pooled from Neuron nodes (`1-cos`
  distance) and NeuRAG chunks (rank as a distance proxy), sorted by descending
  distance — the most unexpected first. No separate `evaluate`: the evaluation
  *is* the ordering.

**Released as** Neuron 6.4.0, Gray Matter 1.4.0, NeuRAG 1.3.1. The same release
fixed two things the previous one had shipped wrong: Neuron's `__version__` was
stuck at `6.2.0` while `pyproject.toml` said `6.3.0`, and the Gray Matter
wheels vendored inside `neuron/` and `neurag/` were still at 1.2.0 — the test
that guards against exactly that had been red.

**What remains:** the Turso→sqlite3 degrade (L2 guard) is a per-process
fallback, never active in single-session production (one owning process per
DB).

**Future ideas from the creativity tests (2026-08-03):**
- Maintenance as worker tools (reembed/backup/checkpoint over MCP) → removes
  the lock problem in maintenance cases
- On-demand explainability (`why` flag on `get_context`/`pre_turn`: which
  link/episode/salience surfaced a node) — the data already exists
- Pulse routing driven by the blackboard (mode → routing)
- WAL checkpoint on shutdown
- Dropped: `sqld` daemon (YAGNI for a single session), on-demand flash (already
  covered by brainstorm), `body_status` (pure aggregation of three calls the
  agent can already make)

See `gray_matter/docs/CERVELLO.md` for the anatomical map and the criterion
that decides which component owns a new capability.

---

## Open threads

| Thread | Status | Next |
|---|---|---|
| L2 daemon WAL race | ◐ Mitigato (retry 3x + degrade sqlite3 su stesso file, 2026-07-21) | Verifica su daemon vivo con pyturso reale; considerare WAL checkpoint periodico |
| Incremental indexing (D5) | Non iniziato | watchdog/mtime su `neurag watch <dir>` |
| Feedback loop (B1-B4) | ✅ Completo | Bridge auto-learning + confirm → salience/trust |
| Multilingual embeddings | ✅ Paraphrase-multilingual-MiniLM-L12-v2 (384-dim) | Nessuna azione richiesta |
| Version alignment | ✅ Unificato (6.0.1 / 1.0.0 / 1.0.0) | Nessuna azione richiesta |
