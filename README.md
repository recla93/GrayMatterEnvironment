<!-- ════════════════════════════════════════════════════════════════════ -->
<!--                           NEURAG · README                             -->
<!-- ════════════════════════════════════════════════════════════════════ -->

<div align="center">

<img src="assets/neurag-logo.png" alt="NeuRAG logo" width="360">

<h1>📚 NeuRAG</h1>

<h3>Hierarchical knowledge base for AI — an MCP server that gives LLMs a <em>permanent vault</em>.</h3>

<p>
NeuRAG is a structured, trigger-navigable knowledge base: index entire directories,
organize content into a node hierarchy, and search with semantic or lexical ranking.
No salience, no decay — facts stay put. Pairs with Neuron (episodic memory) behind
the Gray Matter gateway.
</p>

<br>

<!-- ── identity badges ─────────────────────────────────────────────── -->
<img alt="version"  src="https://img.shields.io/badge/version-1.3.2-7c8cff?style=flat-square">
<img alt="license"  src="https://img.shields.io/badge/license-PolyForm_NC_1.0.0-4be1a0?style=flat-square">
<img alt="python"   src="https://img.shields.io/badge/python-3.10_--_3.14-3776AB?style=flat-square&logo=python&logoColor=white">
<img alt="protocol" src="https://img.shields.io/badge/protocol-MCP-000000?style=flat-square">
<img alt="platform" src="https://img.shields.io/badge/platform-Windows_·_macOS_·_Linux-8b93b8?style=flat-square">
<img alt="status"   src="https://img.shields.io/badge/status-beta-ffb84d?style=flat-square">

<br><br>

<!-- ── nav buttons ─────────────────────────────────────────────────── -->
<a href="#-what-is-neurag"><img alt="What is" src="https://img.shields.io/badge/📚_What_is-1a2350?style=for-the-badge"></a>
<a href="#-how-it-works"><img alt="How it works" src="https://img.shields.io/badge/⚙️_How_it_works-1a2350?style=for-the-badge"></a>
<a href="#-quickstart"><img alt="Quickstart" src="https://img.shields.io/badge/🚀_Quickstart-2ea44f?style=for-the-badge"></a>
<a href="#-mcp-tools"><img alt="Tools" src="https://img.shields.io/badge/🧰_MCP_tools-1a2350?style=for-the-badge"></a>
<a href="#-cross-linking"><img alt="Links" src="https://img.shields.io/badge/🔗_Cross-linking-1a2350?style=for-the-badge"></a>

</div>

---

## ✨ What is NeuRAG?

NeuRAG is a **local-first MCP server** that gives large language models a
**permanent, structured knowledge base**. Point any MCP client at it and you can:

- **Index entire directories** — adaptive chunking for code (AST-aware: functions,
  classes), Markdown, PDF, DOCX, YAML, and more.
- **Organize into a hierarchy** — godnode → fundamental → specialization, with
  trigger-based navigation that jumps straight to the right node.
- **Search** — semantic (FastEmbed 384-dim vectors) or lexical (TF-IDF fallback),
  with trigger matching as a fast path.
- **Cross-link** — automatic link building between nodes sharing tags or source
  files, with weighted evidence and graph visualization.

> **In one line:** your AI's permanent reference library — structured, searchable, never forgotten.

---

## 🌟 Highlights

|  | Feature | What it means for you |
|---|---|---|
| 🗂️ | **Hierarchical vault** | Godnode → fundamental → specialization: knowledge organized like a book, not a bag of vectors. |
| 🎯 | **Trigger-based navigation** | "Spring Boot" jumps straight to `Java/Spring_Boot/` — no search needed for known topics. |
| ✂️ | **Adaptive chunking** | AST-aware for code (function/class boundaries), plus Markdown headings, PDF pages, DOCX sections. |
| 🔍 | **Semantic + lexical search** | FastEmbed 384-dim vectors when available, TF-IDF fallback — works with zero extra dependencies. |
| 🔗 | **Cross-linking** | Tags and shared source files create weighted links between nodes — query enrichment shows the graph. |
| 🩺 | **Vault health** | `knowledge_health` catches orphans, broken hierarchy, empty chunks, duplicate names. |
| 💾 | **Turso / SQLite** | Native vector search on Turso Cloud or embedded libSQL; stdlib sqlite3 as last resort. |
| 🧩 | **Gateway-ready** | Runs standalone or as a managed worker behind Gray Matter — zero config change. |

---

## ⚙️ How it works

NeuRAG organizes knowledge in a **three-level hierarchy**:

```
    ┌──────────────────────────────────────────────────────────────┐
    │  Root (godnode)                                              │
    │  ├── Java (fundamental)                                      │
    │  │   ├── Spring_Boot (specialization)                        │
    │  │   │   └── [chunks: "REST controllers", "DI patterns"...] │
    │  │   └── Kotlin (specialization)                             │
    │  │       └── [chunks: "coroutines", "flows"...]             │
    │  └── Python (fundamental)                                    │
    │      └── FastAPI (specialization)                            │
    │          └── [chunks: "async endpoints", "Pydantic"...]     │
    └──────────────────────────────────────────────────────────────┘
```

**Indexing** (`knowledge_index`): a directory is scanned, files are chunked per their
type (AST for code, heading splits for Markdown, page breaks for PDF), and chunks are
returned as JSON. The LLM then organizes them into the hierarchy with `knowledge_add_node`
+ `knowledge_add_chunks`.

**Search** (`knowledge_query`): first checks trigger matches (instant lookup), then falls
back to semantic search (vector cosine) or lexical ranking (TF-IDF). Results include the
source file, section, and chunk text.

**Cross-linking** (`knowledge_rebuild_links`): scans tags and source file metadata to
build weighted links between nodes. Tags use Jaccard similarity; source files use chunk
overlap. Links are queried bidirectionally and returned with search results.

---

## 🚀 Quickstart

### Option A — One-click installer (recommended)

The installer sets up **Gray Matter + NeuRAG** in a single venv, registers the
gateway in your MCP clients, and creates a Desktop shortcut to the control center.

| Platform | Action |
|---|---|
| **Windows** | Double-click **`install.cmd`** (or `.\install.ps1` from a terminal) |
| **macOS** | Double-click **`install.command`** (or `sh install.sh` from a terminal) |
| **Linux** | `sh install.sh` from a terminal |

No Python? The installer bootstraps it (winget on Windows, brew/apt on Linux/macOS).
Pre-built `pyturso` wheels are bundled — no C/Rust compiler needed.

### Option B — pip (source checkout)

```bash
git clone https://github.com/recla93/neurag.git
cd neurag
pip install -e ".[dev]"           # editable install with test deps
pip install -e ".[semantic]"      # optional: FastEmbed 384-dim vectors
pip install -e ".[cloud]"         # optional: Turso Cloud support
pip install -e ".[pdf,docx]"      # optional: PDF and Word document support
```

### Option C — Standalone MCP (no gateway)

```json
// ~/.config/opencode/opencode.json  (or your client's MCP config)
{
  "mcp": {
    "neurag": { "command": ["python", "-m", "neurag.server"], "type": "local" }
  }
}
```

### Index a knowledge base

```bash
# Via MCP tools (from your AI client):
knowledge_ingest(path="C:/path/to/docs")       # auto-ingest: scan → nodes → chunks → links
# OR step by step:
knowledge_index(path="C:/path/to/docs")         # → returns JSON chunks
knowledge_add_node(name="Java", node_type="fundamental", parent_name="Root")
knowledge_add_chunks(node_name="Java", chunks=[...])
knowledge_rebuild_links()                       # build cross-links
```

### Query

```bash
knowledge_query(query="Spring Boot REST patterns", top_n=5)
```

### Check health

```bash
knowledge_health    # orphans, broken hierarchy, empty chunks
knowledge_status    # node count, chunk count, link count, engine info
knowledge_tree      # full hierarchy visualization
```

📖 AI agents: see [`INSTALL-AI.md`](INSTALL-AI.md).

---

## ⚡ Auto-ingest

The `knowledge_ingest` tool graficates an entire directory **or a single
document** server-side in a single call — no chunks travel through the LLM
context:

```
scan → folder structure → nodes (godnode/fundamental/specialization)
     → chunk per file (AST-aware for code, heading splits for Markdown)
     → embeddings (if FastEmbed available)
     → rebuild links (tag_overlap + cross_ref)
```

Mapping is automatic:
- Root folder → godnode
- First-level subfolders → fundamental
- Deeper subfolders → specialization (child of parent folder's node)
- Files → chunks attached to their folder's node

Hidden/build directories (`__pycache__`, `node_modules`, `.venv`, etc.) are skipped.

**A single file works too** — you do not have to invent a folder for one PDF.
Its godnode defaults to the *containing folder*, so documents dropped in the
same place stay together. Re-ingesting a file **replaces** that source's chunks,
which makes updating a document the same command as adding it.

```bash
# Via MCP tool — a whole tree, or one document:
knowledge_ingest(path="/path/to/your/docs", godnode="BackEndNotes")
knowledge_ingest(path="/path/to/contract.pdf")
# Poll progress:
knowledge_ingest_status()

# Via CLI:
neurag ingest ~/Documents/notes
neurag ingest ~/Downloads/contract.pdf
```

---

## 🖥️ CLI

Everything the MCP tools do, from a terminal — plus the commands that only make
sense as a deliberate act.

| Command | What it does |
|---|---|
| `neurag ingest <path>` | A folder tree **or** a single document → nodes, chunks, embeddings, links |
| `neurag query "<q>"` | Search the active vault (`--deep` includes parked nodes) |
| `neurag recall "<q>"` | Search **every** layer, parked included — nothing is deleted, only parked |
| `neurag confirm A B` | Say two nodes were useful *together*: the link between them learns from it |
| `neurag related <node>` | What else a node reaches, by spreading activation, ranked by strength |
| `neurag park` | Report nodes idle enough to drop a layer. **Dry run** unless `--apply` |
| `neurag unpark <node>` | Bring a parked node back to the active vault |
| `neurag decay` | Weaken link weights and tag salience by elapsed time (half-life) |
| `neurag health` | Structural audit — flags, never deletes |
| `neurag doctor` | Engine tier, embedder, vault, gateway — the one command to run first |
| `neurag reindex` | Re-embed every chunk after an embedding-model change |
| `neurag config get\|set\|list` | Tunable knobs; the control center renders these automatically |

Reinforcement is on **confirmation**, never on retrieval: retrieval is cheap and
often wrong, so being returned together proves nothing. `confirm` is the signal.

---

## 🔧 Turso auto-provision

NeuRAG **prefers Turso** for native vector SQL. If pyturso is not installed,
NeuRAG attempts to install it automatically from bundled wheels (up to `NEURAG_TURSO_ATTEMPTS`
times). Only after exhausting attempts does it degrade to sqlite3 — with full error logging
visible via `knowledge_status`.

```bash
# Auto-provisioning is ON by default. To disable:
NEURAG_REQUIRE_TURSO=0 python -m neurag.server    # skip auto-install, use sqlite3

# To connect to Turso Cloud (separate DB from Neuron):
NEURAG_TURSO_DATABASE_URL=libsql://... NEURAG_TURSO_AUTH_TOKEN=... python -m neurag.server
```

> **Important:** NeuRAG has its **own** Turso database. It must NOT share a URL with Neuron
> (different `nodes` table schema). Use `NEURAG_TURSO_*` env vars, not `TURSO_*`.

---

## 🧰 MCP tools

<details>
<summary><strong>Core: index, organize, query</strong></summary>

| Tool | Description |
|---|---|
| `knowledge_index(path)` | Chunk a file or directory → returns JSON list of chunks |
| `knowledge_add_node(name, node_type, parent_name?, triggers?)` | Create a node in the hierarchy |
| `knowledge_add_chunks(node_name, chunks)` | Attach previously indexed chunks to a node |
| `knowledge_query(query, top_n?)` | Search: vector **and** BM25 always, fused with RRF, then MMR-diversified |

</details>

<details>
<summary><strong>Inspection & health</strong></summary>

| Tool | Description |
|---|---|
| `knowledge_status` | Engine, node count, chunk count, embedded count, link count |
| `knowledge_tree` | Full hierarchy visualization |
| `knowledge_health` | Structural audit: orphans, broken hierarchy, empty chunks, duplicates |

</details>

<details>
<summary><strong>Cross-linking</strong></summary>

| Tool | Description |
|---|---|
| `knowledge_link_graph` | Show all node links with weights and evidence |
| `knowledge_rebuild_links` | Clear all links and rebuild from tags + cross-refs |

</details>

---

## 🔗 Cross-linking

NeuRAG builds **weighted links** between nodes to enrich search results. Two link types:

### Tag overlap (`tag_overlap`)
Nodes sharing tags get linked with **Jaccard similarity** weight:
```
weight = |shared tags| / |all tags combined|
evidence = "java,spring"  (the shared tags)
```

### Cross-reference (`cross_ref`)
Nodes whose chunks come from the **same source file** get linked with weight based
on chunk overlap:
```
weight = min(chunks_from_source_A, chunks_from_source_B) / max(total_chunks_A, total_chunks_B)
evidence = "path/to/file.md"  (the shared source)
```

**Usage:**
```bash
gray-matter knowledge rebuild-links    # build all links
gray-matter knowledge link-graph       # visualize the graph
gray-matter knowledge status           # see link count
```

Links are returned with `search_with_links()` — each search result includes
connections to other results in the same query.

📖 Full design: [`DESIGN-CROSSLINKS.md`](DESIGN-CROSSLINKS.md).

---

## 💾 Storage

NeuRAG resolves its storage tier automatically:

1. **Turso Cloud** — when `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` are set.
   Native `vector_distance_cos()` server-side.
2. **Local pyturso** — embedded libSQL with native vector search *(the default)*.
3. **stdlib sqlite3** — last-resort fallback, Python-side cosine similarity.

---

## 🏗️ Architecture

```
neurag/
├── server.py       # MCP server: 14 tools, Gray-Matter auto-registration
├── db.py           # KnowledgeGraph: 3-tier DB, vector search, node/chunk CRUD
├── chunker.py      # Adaptive chunking: AST (Python), definition-aware (Kotlin/Java/TS/JS), Markdown, PDF, DOCX
├── embedder.py     # NullEmbedder (lexical) / FastEmbedEmbedder (384-dim, shared with Neuron)
├── ingest.py       # Auto-ingest: folder → nodes → chunks → embeddings → links (server-side)
├── importer.py     # Bulk YAML import
├── selfcheck.py    # Deterministic self-tests (no model download)
├── models.py       # Data classes: Chunk, QueryResult
├── clients.py      # MCP client registration (shared pattern with Neuron)
├── settings.py     # Persistent config (embedding model, chunk size)
├── shortcut.py     # Desktop shortcut creation (cross-platform)
└── tests/          # Test suite (24 link tests + executor/settings tests)
```

**Key design decisions:**

- **No salience, no decay** — unlike Neuron, facts in NeuRAG are permanent. The
  knowledge base is a reference library, not a living memory.
- **Trigger-based fast path** — known topics jump straight to a node without search.
- **Gateway-ready** — auto-registers with Gray Matter via IPC; runs as a managed
  worker with pre-warmed model.
- **Cross-linking** — tag-based and source-based links enrich search results with
  graph context, connecting related nodes without manual annotation.
- **Shared embedding space** — same 384-dim model as Neuron, enabling cross-store bridges.

---

## 🛠️ Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q     # 24 link tests + settings/executor tests
```

**Self-check** (no install needed, deterministic — no model download):

```bash
python neurag/selfcheck.py     # embedder routing + lexical search + docx chunker
```

Requires **Python 3.10+**. Optional: `fastembed` for semantic search, `PyMuPDF` for PDF,
`python-docx` for Word documents.

---

## 🔧 Tuning

NeuRAG is configured via **environment variables** (set before starting) and
**hardcoded constants** in source. Most defaults work out of the box; tune these
when you need different chunk sizes, embedding models, or search behavior.

### Environment variables

| Env var | Default | What it controls |
|---|---|---|
| `NEURAG_EMBEDDER` | `"auto"` | Embedder: `auto` (fastembed if installed) / `fastembed` / `null` (lexical only) |
| `NEURAG_EMBED_MODEL` | `"paraphrase-multilingual-MiniLM-L12-v2"` | FastEmbed model (384-dim, multilingual IT/EN) |
| `NEURAG_TURSO_DATABASE_URL` | (empty) | Remote Turso DB URL (separate from Neuron!) |
| `NEURAG_TURSO_AUTH_TOKEN` | (empty) | Remote Turso auth token (falls back to `TURSO_AUTH_TOKEN`) |
| `NEURAG_REQUIRE_TURSO` | `"1"` | If `"0"`, skip auto-install of pyturso |
| `NEURAG_TURSO_ATTEMPTS` | `"3"` | Auto-install attempts before sqlite3 fallback |
| `NEURAG_TURSO_AUTOINSTALL` | `"1"` | If `"0"`, don't attempt `pip install` automatically |

### Hardcoded constants (edit in source)

#### Chunking (`chunker.py`)

| Constant | Value | What it controls |
|---|---|---|
| Min chunk length | `20` chars | Chunks shorter than this are silently dropped |
| Code `hard_cap` | `160` lines | Max lines before force-flushing a code chunk |
| `max_lines` (plain text) | `60` lines | Plain text chunk size |
| Tags per symbol | `[:8]` | Max trigger tags per symbol name |
| Tags per phrase | `[:6]` | Max trigger tags per heading/phrase |
| Sub-word min length | `>= 3` chars | Tags shorter than 3 are dropped |

#### Database (`db.py`)

| Constant | Value | What it controls |
|---|---|---|
| Trigger cap per node | `40` | Max triggers attached to a single node |
| Tiny chunk threshold | `< 20` chars | Health check flags chunks below this |
| `PRAGMA journal_mode` | `WAL` | SQLite journaling mode (concurrent reads) |
| `PRAGMA foreign_keys` | `ON` | FK enforcement |

#### Search (`db.py`)

| Parameter | Default | What it controls |
|---|---|---|
| `top_n` (query) | `5` | Default number of search results |
| `top_n` (query max) | `10` | Hard cap on results per query |

#### Cross-linking (`db.py`)

| Behavior | Detail |
|---|---|
| Tag weight | Jaccard similarity: `\|shared\| / \|union\|` |
| Cross-ref weight | `min(chunks_shared) / max(total_chunks)` |
| Self-links | Silently ignored |
| Rebuild | Idempotent — safe to run multiple times |

---

## 🗺️ Documentation map

| Doc | What's in it |
|---|---|
| **[INSTALL-AI.md](INSTALL-AI.md)** | Automated install + register instructions for AI agents |
| **[DESIGN-CROSSLINKS.md](DESIGN-CROSSLINKS.md)** | Cross-linking design: schema, algorithms, API, tests |
| **[DOCTOOLUPDATE.md](DOCTOOLUPDATE.md)** | Complete tool documentation with real code examples |
| **[../gray_matter/README.md](../gray_matter/README.md)** | Gray Matter: MCP gateway/orchestrator |
| **[../neuron/README.md](../neuron/README.md)** | Neuron: semantic memory MCP server |

---

## 👤 Author

<div align="center">

**NeuRAG** is designed and built by **Claudio Costantino**.

<a href="https://www.linkedin.com/in/clacosta1999/"><img alt="LinkedIn" src="https://img.shields.io/badge/LinkedIn-Claudio_Costantino-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white"></a>
<a href="https://github.com/recla93/neurag"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-recla93%2Fneurag-181717?style=for-the-badge&logo=github&logoColor=white"></a>

</div>

---

## 🧩 Part of the Gray Matter suite

Three MCP servers that work alone and work better together. Install any
one of them and it can pull in the others; the gateway then serves all
three through a **single** connector, so your client registers once.

| Project | What it does |
|---|---|
| 🧠 **[Neuron](https://github.com/recla93/Neuron)** | Semantic memory — concepts, links, salience. It <b>learns</b>. |
| 📚 **[NeuRAG](https://github.com/recla93/neurag)** ← you are here | Hierarchical knowledge vault — nodes, chunks, triggers. It <b>keeps</b>. |
| ⚡ **[Gray Matter](https://github.com/recla93/gray-matter)** | MCP gateway — one connector, warm workers, cross-store bridges. |

<sub>Whoever is installed first owns the session handshake: the gateway
when it is present, otherwise the standalone tool — so the model is never
told to call tools that are not there.</sub>

---

## 📜 License

**PolyForm Noncommercial License 1.0.0** — free for noncommercial use. See [LICENSE](LICENSE).

<div align="center"><sub>Built with 📚 — because your AI's knowledge shouldn't evaporate between sessions.</sub></div>
