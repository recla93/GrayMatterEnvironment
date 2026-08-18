# Troubleshooting — symptoms, diagnosis, fixes

> Common issues across Neuron, Gray Matter, and NeuRAG. Each entry: symptom →
> how to diagnose → how to fix.

## Gray Matter not running

**Symptom:** `gray-matter status` returns "Gray-Matter not running".

**Diagnosis:** `gray-matter ping` — checks if daemon is listening on `:9876`.

**Fix:** `gray-matter start`. If it fails to bind, check for stale processes: on Windows use `netstat -ano | findstr 9876`, on Linux `lsof -i :9876`. Kill the stale process, then `gray-matter start` again.

## No servers visible in gray-matter status

**Symptom:** `gray-matter status` shows 0 servers.

**Diagnosis:** `gray-matter doctor` — shows which servers are registered and alive.

**Fix:** Ensure Neuron and/or NeuRAG are installed (`pip install neuron`, `pip install neurag`). Then `gray-matter install` or `gray-matter register --gateway` to re-register.

## Pulse returns "No servers available"

**Symptom:** `gray_matter_pulse` returns "No servers available for pulse."

**Diagnosis:** `gray-matter status` — check if neuron/neurag are listed and alive. If listed but dead, check worker subprocess status.

**Fix:** `gray-matter stop` then `gray-matter start` to restart all workers. If a specific server keeps dying, check its logs (stderr of the worker subprocess).

## Worker subprocess dies repeatedly

**Symptom:** `gray-matter doctor` shows `[DEAD] neuron` or `[DEAD] neurag`.

**Diagnosis:** Run the server directly to see the error:
```bash
# Neuron
python -m neuron

# NeuRAG
neurag-mcp
```

**Fix:** Most common causes:
- Missing dependency: `pip install neuron` or `pip install neurag`
- pyturso compilation failure on Windows: install from vendored wheel (`Neuron/vendor/`)
- Seed DB missing: reinstall the package

## NeuRAG vector tier DEGRADED

**Symptom:** `gray-matter doctor` shows `[!!] NeuRAG vector tier DEGRADED (sqlite3, Python cosine)`.

**Diagnosis:** pyturso is not installed. NeuRAG falls back to sqlite3 + Python brute-force cosine.

**Fix:** Install pyturso from vendored wheels: `pip install Neuron/vendor/pyturso-0.6.1-*.whl` (platform-specific). Full tier gives native `vector_distance_cos()` SQL support.

## "open: NotFound" error (L2 bug)

**Symptom:** `store_turn` intermittently returns `[tool_name] error: open: NotFound`. `pre_turn` works fine. The error only appears under Gray Matter workers, never when Neuron runs standalone.

**Diagnosis:** Multiple GM worker processes (e.g. from Claude Desktop's chat + host instances) access the same `graph_*.db` file concurrently. A `_graphs.clear()` + reload inside pyturso's open races with WAL/sidecar checkpoints from another process.

**Mitigation (2026-07-21):** `db._open_local_engine` retries up to 3 times on open failure, then degrades to sqlite3 on the same file (compatible format). A `store_turn` degrades instead of crashing.

**Fix:** Restart Gray Matter (`gray-matter stop && gray-matter start`) to get fresh workers. If persistent, the WAL race between concurrent pyturso processes is the root cause. A full fix requires single-writer serialization or WAL checkpoint coordination.

## Graph appears empty after install

**Symptom:** `neuron status` shows 0 nodes on a fresh install.

**Diagnosis:** Check the graph store path: `neuron console` shows the active store location. Verify the seed DB exists at the package's `data/base_knowledge.db`.

**Fix:** The seed DB is loaded on first `get_context` or `pre_turn` call. Call `neuron status` or `pre_turn(topic="test")` to trigger initialization. If still empty, reinstall: `pip install --force-reinstall neuron`.

## Client doesn't see Neuron/NeuRAG tools

**Symptom:** Your AI client shows only Gray Matter tools, not the pass-through tools from Neuron/NeuRAG.

**Diagnosis:** `gray-matter status` — check if neuron/neurag are listed with their tools. If tools column is empty, the worker failed to respond to `list_tools`.

**Fix:**
1. `gray-matter stop && gray-matter start` — restarts workers
2. If still empty, check that neuron/neurag are importable: `python -c "import neuron; import neurag"`
3. Re-register: `gray-matter register --gateway`

## Double GM daemon

**Symptom:** `gray-matter status` shows multiple entries or unexpected behavior.

**Diagnosis:** `gray-matter ping` may succeed but the wrong daemon is handling requests.

**Fix:** `gray-matter stop` (sends shutdown to the daemon on :9876). Wait 2s. `gray-matter start`.

## Cache returns stale results

**Symptom:** Pulse returns outdated information even after the knowledge base was updated.

**Diagnosis:** The context cache (`cache_ttl_seconds`, default 60s) may be serving a cached response.

**Fix:** Wait for TTL expiry, or restart Gray Matter (`gray-matter stop && gray-matter start`). For immediate freshness: `gray-matter config set cache_ttl_seconds 0` (then set back to 60 after).

## Neuron store stopped persisting turns (Turso Cloud)

**Symptom:** `neuron status` shows nodes but `pre_turn` never surfaces them.

**Diagnosis:** The remote Turso connection may have silently dropped. Check with `neuron connect` (tests the connection).

**Fix:** The `_reconnect` logic should handle this automatically (T76). If it doesn't, `gray-matter stop && gray-matter start` recreates the worker with a fresh connection. For persistent issues, check `TURSO_AUTH_TOKEN` hasn't expired. If using local sqlite3, verify the DB file is not locked by another process.

## Embedding dimension mismatch

**Symptom:** Error about embedding dimension not matching `VECTOR_DIM` (384).

**Diagnosis:** The graph was created with a different `NS_EMBED_MODEL` (different dimension). Vectors from different models are NOT comparable.

**Fix:** Full re-embed: `python scripts/reembed.py` (in the Neuron repo). This regenerates all vectors with the current model. Changing `NS_EMBED_MODEL` without re-embedding corrupts search results.

## NeuRAG health check shows issues

**Symptom:** `neurag health` or `knowledge_health` reports serious issues.

**Diagnosis:** Common issues:
- **Broken hierarchy:** node references a parent that doesn't exist
- **Empty chunks:** chunks with whitespace-only text
- **Duplicate node names:** two nodes with the same name

**Fix:** These are data integrity issues. Use `knowledge_health` to identify affected nodes, then manually fix via `knowledge_add_node` / `knowledge_add_chunks`. There is no automatic repair.

---

## Next steps

- [Configuration](CONFIGURATION.md) — check env vars and defaults
- [Data](DATA.md) — understand what's stored where
- [Architecture](ARCHITECTURE.md) — understand why things work this way
