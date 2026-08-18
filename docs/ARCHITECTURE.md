# Architecture — internal design and data flow

> How the three components connect, what happens during a pulse, and the key
> design decisions with their rationale.

## System architecture

```
                    MCP Client (Claude Desktop, Cursor, VS Code, ...)
                               |
                               | stdio (MCP protocol)
                               v
                    +----------------------+
                    |   Gray Matter (GM)   |  <-- server.py
                    |  Orchestrator/Proxy  |
                    |                      |
                    |  ContextCache (LRU)  |  <-- cache.py
                    |  Bridges Store       |  <-- bridges.py
                    |  Registry            |  <-- registry.py
                    +----------+-----------+
                               |
                    +----------+-----------+
                    |   TCP IPC (:9876)    |  <-- CLI, GUI
                    +---------------------+

                    +----------------------+
                    |  Persistent Workers   |  <-- _worker.py
                    |  (one per sub-server) |
                    |                      |
                    |  +--------+ +------+ |
                    |  | Neuron | |NeuRAG| |
                    |  | worker | |worker| |
                    |  +---+----+ +--+---+ |
                    +------+---------+-----+
                           |         |
                      neuron.server  neurag.server
```

## Gateway pattern

The MCP client connects to **one server**: Gray Matter. GM self-discovers installed sub-servers (Neuron, NeuRAG) via `importlib.util.find_spec()`, fetches their real tool schemas from persistent workers, and re-publishes them under their original names. The client sees all tools from all projects as if they were one server.

Sub-servers run as **long-lived worker subprocesses** (`_worker.py`). Each worker:
- Imports the server module once (fastembed model stays warm)
- Reads JSON lines on stdin, writes JSON responses on stdout
- Is serialized per-worker via `asyncio.Lock` to avoid pipe interleaving

An earlier version spawned a new subprocess per call. The persistent worker model keeps the expensive embedding model warm and avoids cold-start latency.

## Data flow: a pulse

1. Client calls `gray_matter_pulse(topic="kotlin coroutines")`
2. Check `ContextCache` — if hit, return cached response immediately
3. If miss, fan out in parallel:
   - Neuron `get_context(topic, depth=1)` — semantic memory recall
   - NeuRAG `knowledge_query(rag_query, top_n)` — knowledge base search. The query is expanded with the last 3 topics from a conversation buffer for multi-turn recall
4. Join results with `---` separator
5. Attach relevant cross-store **bridges** (links between Neuron concepts and NeuRAG nodes). If a bridge reaches weight 5+, auto-confirm the Neuron concept (salience boost)
6. If NeuRAG had a hit, fetch **proactive neighbors** (depth-2 structured neighbors not already in the response)
7. Fire **Flash** on topic shifts: call Neuron `forgotten(threshold=5, near=topic)` to surface dormant mid-band concepts. Rate-limited (min gap of 3 pulses + per-concept cooldown)
8. If flash surfaced a dormant concept AND NeuRAG had a hit, auto-create a cross-store bridge (v3b auto-discovery)
9. Cache the response, record latency stats, return

## Key design decisions

### Hebbian bridge learning

Cross-store bridges reinforce their weight each time they are surfaced in a pulse (+1, capped at 1000). Unused bridges decay during idle periods (weight -1 after 7 days unused, pruned below 1.0). At weight >= 5, the Neuron concept gets an auto-confirm. This is the orchestrator's own memory that learns from use.

### Dynamic cache TTL

Hot topics (frequently queried) earn longer cache lives via linear extension: `base TTL * (1 + 0.5 * hits)`, capped at 3x. A topic that gets hit 4+ times lives 3x longer than a cold one.

### Context hysteresis

The brain doesn't hard-reset context every time a topic is mentioned once. Neuron only switches the active graph after `CONTEXT_SWITCH_THRESHOLD` (default 2) consecutive turns signaling the same non-active domain. Feedback/clarification turns reset the counter.

### Plan/executor split for install/uninstall

`installer.plan()` and `uninstaller.plan()` are pure functions (testable, no side effects). `executor.py` is the thin effectful layer. Memory (graph, DB, bridges) is never deleted without explicit user consent.

### Stdlib first

Gray Matter's only runtime dependency is `mcp>=1.28.0,<2.0`. Everything else is stdlib: `argparse` (not click/typer), `json` (not pydantic for settings), `http.server` (for webgui), `tkinter` (for legacy gui), `socket`+`struct` (for IPC), `OrderedDict` (for LRU cache).

### Neuron: composite retrieval ranking

A node's rank blends four signals (ADR-003):

| Signal | Weight | What it measures |
|---|---|---|
| `sim` | 0.5 | Cosine similarity to the query |
| `salience` | 0.3 | Hebbian reinforcement (what matters) |
| `recency` | 0.2 | How recently the node was active |
| `trust` | 0.1 | Confidence from confirm/refute signals |

### NeuRAG: three-tier search fallback

1. **Trigger match** — instant SQL lookup via JSON triggers array
2. **Vector SQL** — `vector_distance_cos()` on Turso (when pyturso available)
3. **Python cosine / TF-IDF** — brute-force fallback when no vector SQL support

Transparent degradation: the user never sees which tier is active.

### NeuRAG: LLM-in-the-loop indexing

`knowledge_index` only chunks and returns JSON. The LLM decides where to place chunks in the hierarchy via `knowledge_add_node` + `knowledge_add_chunks`. This keeps the human/LLM in control of taxonomy.

## IPC protocol

Gray Matter exposes a TCP IPC listener on `127.0.0.1:9876`. Used by the CLI and GUI for daemon management. Protocol: 4-byte big-endian length prefix + JSON payload.

| IPC Action | Purpose |
|---|---|
| `register` | Register a sub-server with its tools |
| `heartbeat` | Keep-alive ping from sub-servers |
| `unregister` | Remove a server |
| `isolate` / `collaborate` | Toggle a server's participation in pulse |
| `mode` | Set all servers to collaborate or separate |
| `status` | Registry dump |
| `stats` | Orchestrator counters |
| `doctor` | Health snapshot |
| `knowledge_cmd` | Delegate to NeuRAG tools |
| `gm-neuron` / `gm-neurag` | Call arbitrary tools on a specific sub-server |
| `shutdown` | Graceful daemon stop |

## Background tasks (asyncio)

| Task | Purpose |
|---|---|
| `_ipc_listener` | TCP server on :9876 for IPC |
| `_heartbeat_monitor` | Marks servers dead if they miss heartbeats >15s |
| `_sleep_monitor` | Marks all servers sleeping after idle timeout; runs bridge decay |
| `_reap_dead_workers` | Kills worker subprocesses for servers marked dead |
| `_prewarm_workers` | Spawns workers and fires a cheap read to warm models at startup |

---

## Next steps

- [Data](DATA.md) — database schemas
- [Tools](TOOLS.md) — what each tool does
- [Configuration](CONFIGURATION.md) — tunables
