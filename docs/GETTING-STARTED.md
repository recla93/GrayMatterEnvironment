# Getting started — end-to-end tutorial

> Install → first pulse → first store_turn → first vault indexed → confirm/trust.
> Max 10 minutes of reading. Every step shows expected output.

## Prerequisites

- Python 3.10 or later
- An MCP-compatible AI client (Claude Desktop, Cursor, VS Code, OpenCode, etc.)

## Step 1: install

### Option A — One-click installer (recommended)

**Windows** — double-click `install.cmd` in the root:

```
.\install.ps1
```

**macOS / Linux**:

```sh
sh install.sh
```

What it does: bootstraps Python if missing → one shared venv → installs GM +
Neuron + NeuRAG → registers gateway in MCP clients → Desktop GUI shortcut.

### Option B — pip (source checkout)

```bash
git clone https://github.com/recla93/Neuron.git
cd Neuron

# On Windows, add --find-links neuron/vendor for pyturso:
pip install --find-links neuron/vendor -e gray_matter -e neuron -e neurag

# On Linux/macOS:
pip install -e gray_matter -e neuron -e neurag
```

### Option C — Individual repos

```bash
pip install neuron neurag gray-matter
gray-matter install --gateway
```

Expected output:
```
Installing (gateway model)...
  [OK] register: gray-matter added to Claude Desktop
Done. Restart your AI apps.
```

## Step 2: verify

```bash
gray-matter doctor
```

Expected output:
```
Gray-Matter v1.1.2 — awake
  cache: 0 entries | bridges: 0
  [ok] neuron (alive, collab) worker+
  [ok] neurag (alive, collab) worker+
```

If you see `[DEAD]`, run `gray-matter stop && gray-matter start`.

## Step 3: your first pulse

From your AI client, call:
```
gray_matter_pulse(topic="python testing")
```

Expected: a text response combining Neuron context (may be empty on first run)
and NeuRAG results (if you have indexed knowledge). If both are empty, that's
normal on a fresh install — the memory builds over time.

## Step 4: store your first memory

After the AI responds to something substantive, call:
```
gray_matter_store_turn(
  topic="python testing",
  keywords=["pytest", "fixtures", "mocking"],
  domain="backend",
  intent="exploration",
  sentiment="neutral"
)
```

This persists the concepts into Neuron's graph. On the next pulse about testing,
`pre_turn` will surface these keywords.

## Step 5: load context before responding

```
pre_turn(topic="python testing", keywords=["pytest"])
```

Returns compact context from the graph. Fold it silently into your answer.

## Step 6: index a knowledge base

### Option A — Auto-ingest (recommended)

The `knowledge_ingest` tool scans an entire directory and creates nodes,
chunks, embeddings, and links **server-side** in a single call:

```
knowledge_ingest(path="/path/to/your/docs", godnode="BackEndNotes")
```

This creates:
- Root folder → godnode
- First-level subfolders → fundamental nodes
- Deeper subfolders → specialization nodes
- Files → chunks attached to their folder's node
- Embeddings (if FastEmbed available)
- Cross-links (tag_overlap + cross_ref)

### Option B — Step by step

```
knowledge_index(path="/path/to/your/docs")
```

Returns JSON chunks. Then organize them:
```
knowledge_add_node(name="MyDocs", node_type="godnode")
knowledge_add_chunks(node_name="MyDocs", chunks=[...the chunks from step 1...])
knowledge_rebuild_links()
```

### Option C — CLI

```bash
neurag chunk /path/to/your/docs > chunks.json
neurag add-node MyDocs godnode
neurag add-chunks MyDocs --file chunks.json
```

## Step 7: query your knowledge

```
knowledge_query(query="how to configure logging", top_n=3)
```

Returns relevant chunks from your indexed docs.

## Step 8: confirm useful context

When `pre_turn` or `get_context` surfaces something that helps:
```
confirm(keywords=["pytest", "fixtures"], boost=2)
```

This reinforces those concepts so they surface more prominently in future retrieval.

## Step 9: check graph health

```bash
gray-matter doctor          # overall health
gray-matter status          # registered servers with tool lists
```

Or directly:
```
neuron status               # Neuron graph stats
knowledge_status            # NeuRAG knowledge base stats
```

Healthy indicators for Neuron: strong+medium > 40%, nodes/turn between 3-5,
pre_turn ≈ store_turn.

## Step 10: tear down (optional)

```bash
gray-matter uninstall
```

Memory is preserved unless you pass `--purge-data`.

---

## What just happened

1. **Gray Matter** started as a daemon, discovered Neuron and NeuRAG, spawned workers
2. **Neuron** loaded its seed graph and became ready to store/retrieve concepts
3. **NeuRAG** initialized its knowledge DB with vector search capability
4. Each `pulse` fans out to both backends in parallel, merges results, and caches
5. The memory loop (`pre_turn` → respond → `store_turn`) builds the graph over time
6. Cross-store bridges link Neuron concepts to NeuRAG nodes automatically
7. Semantic flashes surface lateral associations every N turns
8. The context cache (TTL + LRU) speeds up repeated queries

## Next steps

- [Configuration](CONFIGURATION.md) — tune flash rate, cache TTL, embedding model
- [Architecture](ARCHITECTURE.md) — understand the internals
- [Tools](TOOLS.md) — complete tool reference
