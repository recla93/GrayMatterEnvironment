# Technology choices

> Every significant technology decision in the Gray Matter Environment.
> Format: problem → alternatives rejected → choice → why → accepted limits.

---

## 1. Storage engine: libSQL / Turso

**Problem:** Need persistent graph storage for Neuron nodes/links and NeuRAG chunks/nodes, with optional vector search and multi-process access.

**Alternatives rejected:**
- **SQLite (stdlib):** No vector search, no multi-process safety via network protocol. Fine for single-process but fails on shared access.
- **PostgreSQL:** Overkill for a local-first tool. Heavy dependency, defeats the "install and go" ethos.
- **ChromaDB:** Was used in early NeuRAG (v0.1.0). Dropped because: separate daemon, opaque internals, no SQL fallback path.

**Choice:** libSQL (Turso fork) with 3-tier fallback: remote Turso → local pyturso → SQLite.

**Why:** libSQL reads plain SQLite files (zero migration from local). The 3-tier fallback means it works offline, on LAN, or cloud. pyturso==0.6.1 is pinned for wheel compatibility across Python 3.10-3.14.

**Accepted limits:** pyturso wheels are platform-specific (win_amd64, macosx, manylinux). Vector index (`libsql_vector_idx`) not yet used — full-scan cosine is fine for vaults under ~50K chunks.

---

## 2. Embeddings: ONNX + fastembed

**Problem:** Need semantic vector embeddings for Neuron keyword similarity and NeuRAG chunk search.

**Alternatives rejected:**
- **OpenAI embeddings API:** Requires API key, network, cost. Violates local-first.
- **Sentence-transformers (PyTorch):** ~2GB dependency. Heavy for what amounts to 384-dim vectors.
- **TF-IDF only:** No semantic understanding. "Spring Boot" and "spring framework" are unrelated.

**Choice:** ONNX Runtime + fastembed (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-dim). Lazy-loaded on first use. Both Neuron and NeuRAG default to this exact model (NeuRAG reads `NS_EMBED_MODEL`) so the two stores share one vector space.

**Why:** ONNX runs on CPU without PyTorch. Model is ~130MB, downloads once. fastembed wraps it cleanly. TF-IDF kept as transparent fallback if ONNX unavailable.

**Accepted limits:** Multilingual model (switched 2026-07-20 from the earlier English-only `all-MiniLM-L6-v2` so Italian + English memory live in one comparable space). Small model trades accuracy for speed (acceptable for retrieval-augmented use). Overridable via `NS_EMBED_MODEL` — changing it invalidates stored vectors (must match on read).

---

## 3. IPC: length-prefixed TCP

**Problem:** Gray Matter orchestrator needs to call Neuron and NeuRAG tools without blocking the main event loop.

**Alternatives rejected:**
- **In-process imports:** `_call_server_async` re-imported server at every call (F0). Cold start 2-5s per call.
- **HTTP/REST:** Overkill for same-machine. Added framework dependency.
- **Subprocess pipes:** Fragile on Windows, no multiplexing.

**Choice:** Persistent worker processes with length-prefixed TCP on localhost (port 0 = auto-assign).

**Why:** Workers stay warm (import cost paid once). Length-prefixed framing is trivial to implement. `_worker_for` does lazy spawn + respawn on death.

**Accepted limits:** F1 bug (IPC read assumed single `recv` for length bytes) was fixed but pattern is fragile if message > 64KB. Not a concern for tool responses.

---

## 4. Client registration: file-system JSON

**Problem:** MCP clients (Claude Desktop, VS Code, Cursor, etc.) need to know how to reach the Gray Matter gateway.

**Alternatives rejected:**
- **Single config path:** Each client has its own config location (APPDATA, MSIX Packages, XDG, etc.).
- **Symlinks:** Break across drives, permissions issues on Windows.

**Choice:** `clients.py` scans all known config locations, writes/updates JSON entries, creates `.bak` backups. `register --gateway` evicts old neuron/neurag entries.

**Why:** Works across all platforms. `.bak` enables rollback. Scanning known paths covers Claude Desktop (APPDATA + MSIX), VS Code (settings.json), Cursor, OpenCode.

**Accepted limits:** New client = new path in `clients.py`. MSIX path discovery is brittle (depends on package naming convention).

---

## 5. Gateway pattern: single MCP server re-publishing tools

**Problem:** AI assistants expect one MCP server. Three separate servers means three connections, three configs, potential conflicts.

**Alternatives rejected:**
- **Mount all three as sub-servers in MCP config:** Each client mounts neuron, neurag, gray_matter separately. Verbose, fragile.
- **Proxy via HTTP:** Extra hop, loses stdio transport.

**Choice:** Gray Matter binds once (stdio or TCP :9876), re-publishes all 33 tools from Neuron + NeuRAG under their original names.

**Why:** One connection to manage. Tools keep their names (no aliasing confusion). Worker processes handle the sub-calls internally.

**Accepted limits:** GM is a single point of failure. If GM dies, all tools die. Mitigated by daemon singleton + respawn.

---

## 6. Daemon: singleton via exclusive bind

**Problem:** Multiple launches (Claude Desktop chat + host, VS Code, Cowork) each try to start a daemon. Duplicate daemons cause file locks and race conditions.

**Alternatives rejected:**
- **PID file:** Can go stale. Doesn't handle zombie processes.
- **Mutex (Windows):** Platform-specific, doesn't help on Linux/macOS.

**Choice:** `SO_EXCLUSIVEADDRUSE` (Windows) / `SO_REUSEADDR` (POSIX) on port 9876. Bind fails = existing daemon alive, new instance dies. Fallback to stdio mode if bind fails.

**Why:** Kernel-enforced singleton. No PID management needed. The losing daemon dies immediately.

**Accepted limits:** Port 9876 could collide with another service. `GM_PORT` env var available but rarely needed.

---

## 7. Hebbian bridges: cross-store learning

**Problem:** NeuRAG knows facts, Neuron knows episodic context. No link between them. "This chunk relates to that concept" is never persisted.

**Alternatives rejected:**
- **Explicit user commands:** User must manually call `bridge` every time. Doesn't scale.
- **Embedding proximity:** Unreliable cross-store cosine comparison.

**Choice:** Bridge auto-learning: when `pulse` finds both a Neuron context hit and a NeuRAG knowledge hit on the same topic, GM creates a bridge link with initial weight 1.0. Repeated co-occurrence bumps weight (Hebbian: "fire together, wire together"). Bridges inactive 7+ turns decay.

**Why:** Organic knowledge graph growth without user intervention. Weight is a proxy for relevance.

**Accepted limits:** Bridge quality depends on topic overlap between stores. False bridges possible if topic is too generic. Decay is turn-based, not time-based.
