<!-- ════════════════════════════════════════════════════════════════════ -->
<!--                         GRAY MATTER · README                          -->
<!-- ════════════════════════════════════════════════════════════════════ -->

<div align="center">

<img src="assets/gray-matter-logo.png" alt="Gray Matter logo" width="360">

<h1>⚡ Gray Matter</h1>

<h3>The orchestrator that turns Neuron + NeuRAG into one brain.</h3>

<p>
Gray Matter is an MCP gateway: your AI client registers <em>one</em> server,
and Gray Matter fans out to Neuron (semantic memory) and NeuRAG (knowledge base)
as warm managed workers — plus a combined pulse, context cache, cross-store
bridges, and serendipitous flash recall.
</p>

<br>

<!-- ── identity badges ─────────────────────────────────────────────── -->
<img alt="version"  src="https://img.shields.io/badge/version-1.2.0-7c8cff?style=flat-square">
<img alt="license"  src="https://img.shields.io/badge/license-PolyForm_NC_1.0.0-4be1a0?style=flat-square">
<img alt="python"   src="https://img.shields.io/badge/python-3.10_--_3.14-3776AB?style=flat-square&logo=python&logoColor=white">
<img alt="protocol" src="https://img.shields.io/badge/protocol-MCP-000000?style=flat-square">
<img alt="platform" src="https://img.shields.io/badge/platform-Windows_·_macOS_·_Linux-8b93b8?style=flat-square">
<img alt="status"   src="https://img.shields.io/badge/status-beta-ffb84d?style=flat-square">

<br><br>

<!-- ── nav buttons ─────────────────────────────────────────────────── -->
<a href="#-what-is-gray-matter"><img alt="What is" src="https://img.shields.io/badge/⚡_What_is-1a2350?style=for-the-badge"></a>
<a href="#-how-it-works"><img alt="How it works" src="https://img.shields.io/badge/⚙️_How_it_works-1a2350?style=for-the-badge"></a>
<a href="#-quickstart"><img alt="Quickstart" src="https://img.shields.io/badge/🚀_Quickstart-2ea44f?style=for-the-badge"></a>
<a href="#-mcp-tools"><img alt="Tools" src="https://img.shields.io/badge/🧰_MCP_tools-1a2350?style=for-the-badge"></a>
<a href="#-cli-reference"><img alt="CLI" src="https://img.shields.io/badge/⌨️_CLI-1a2350?style=for-the-badge"></a>

</div>

---

## ✨ What is Gray Matter?

Gray Matter is a **local-first MCP gateway/orchestrator** that sits between your AI
client and the Neuron + NeuRAG duo. Instead of registering three separate servers
in every client, you register **one** — Gray Matter — and it handles everything:

- **Pass-through proxy** — republishes every Neuron and NeuRAG tool with real
  schemas, so the LLM can call them directly.
- **`gray_matter_pulse(topic)`** — the killer feature: one call that fans out to
  Neuron (context memory) and NeuRAG (knowledge chunks) in parallel, joins the
  results, adds cross-store bridges, and fires a serendipitous flash — all in a
  single round-trip.
- **Persistent workers** — each sub-server runs as a long-lived subprocess with
  its model pre-warmed. No cold imports per call.
- **Context cache** — TTL + LRU, multi-topic, targeted invalidation on writes.
- **Cross-store bridges** — Hebbian links between Neuron concepts and NeuRAG
  nodes; unused ones decay, 5+ uses promote the concept (confirm → trust).
- **Flash** — serendipitous dormant-concept recall on topic shifts.

> **In one line:** one server, two brains, zero re-registration.

---

## 🌟 Highlights

|  | Feature | What it means for you |
|---|---|---|
| 🔌 | **One server to rule them all** | Register `gray-matter` once — Neuron + NeuRAG are auto-discovered as managed workers. |
| ⚡ | **Unified pulse** | `gray_matter_pulse(topic)` = memory + knowledge + bridges + flash in one call. |
| 🧠 | **Cross-store bridges** | Hebbian links connect Neuron concepts to NeuRAG nodes; usage promotes, idleness decays. |
| 💾 | **Warm workers** | Persistent subprocesses with pre-warmed models — no cold import penalty per call. |
| 🗃️ | **Smart cache** | TTL + LRU with targeted invalidation — cached pulses survive until a relevant write happens. |
| 🎯 | **Flash recall** | On topic shifts, a dormant concept surfaces serendipitously — the AI remembers what you forgot to ask. |
| 🩺 | **Full CLI** | `status`, `doctor`, `stats`, `bridges`, `knowledge`, `config` — manage everything from the terminal. |
| 🖥️ | **Web GUI** | Unified control center with real-time server status, cache stats and bridge visualization. |

---

## ⚙️ How it works

Gray Matter runs a **fan-out model** around every pulse:

```
    ┌──────────────────────────────────────────────────────────────┐
    │  LLM calls gray_matter_pulse(topic="kotlin coroutines")     │
    └──────────────────────────────────────────────────────────────┘
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
    ┌─────────────────────┐   ┌─────────────────────────┐
    │  Neuron worker      │   │  NeuRAG worker           │
    │  get_context(...)   │   │  knowledge_query(...)    │
    │  (semantic memory)  │   │  (knowledge chunks)      │
    └─────────────────────┘   └─────────────────────────┘
                 │                         │
                 └────────────┬────────────┘
                              ▼
    ┌──────────────────────────────────────────────────────────────┐
    │  Join results → Add cross-store bridges → Flash recall       │
    │  → Cache → Return to LLM                                    │
    └──────────────────────────────────────────────────────────────┘
```

Each sub-server runs as a **persistent worker subprocess** (`_worker.py`). The worker
imports the server module once and keeps the process alive — so the model stays warm
across calls. Gray Matter serializes requests per worker pipe with an `asyncio.Lock`,
so there's no interleaving.

**Cross-store bridges** are the magic glue: when a Neuron concept and a NeuRAG topic
co-occur frequently, the bridge gets promoted (5+ uses → `confirm` call → trust boost).
Idle bridges decay. This means the two memories learn to cooperate over time.

---

## 🚀 Quickstart

### Option A — One-click installer (recommended)

This repo bundles Neuron + NeuRAG. Double-click the installer — Python is
bootstrapped if missing, one venv is created, the gateway is registered in your
MCP clients, hooks are deployed, and a **Gray Matter GUI** shortcut appears on
the Desktop.

| Platform | Action |
|---|---|
| **Windows** | Double-click **`install.cmd`** (or `.\install.ps1` from a terminal) |
| **macOS** | Double-click **`install.command`** (or `sh install.sh` from a terminal) |
| **Linux** | `sh install.sh` from a terminal |

No Python? The installer bootstraps it (winget on Windows, brew/apt on Linux/macOS).
Pre-built `pyturso` wheels are bundled — no C/Rust compiler needed.

### Option B — pip (source checkout)

```bash
git clone https://github.com/recla93/gray-matter.git
cd gray-matter
pip install -e ".[dev]"             # editable install with test deps
pip install -e ".[cloud,rag,gui]"   # optional: Turso, NeuRAG, web GUI
```

### Register and verify

```bash
gray-matter install --dry-run   # preview: what would be registered
gray-matter install             # idempotent, .bak backups, manifest
gray-matter doctor              # health snapshot: servers, workers, cache, bridges
gray-matter status              # registered servers with tool lists
gray-matter stats               # cache hit rate, flashes, bridges, latency
```

This registers **only** `gray-matter` in your MCP clients (evicts standalone Neuron/NeuRAG
entries) and deploys per-client hooks.

### Use

Once installed, your AI client can call:

- **`gray_matter_pulse(topic)`** — the unified memory + knowledge call
- **Any Neuron/NeuRAG tool** — passed through transparently (e.g. `neuron_store_turn`,
  `knowledge_query`, `knowledge_index`)

### Teardown

```bash
gray-matter uninstall              # interactive: asks about memory retention
gray-matter uninstall --purge-data # wipes everything, no questions
```

📖 AI agents: see [`INSTALL-AI.md`](INSTALL-AI.md).

---

## 🧰 MCP tools

<details>
<summary><strong>The unified pulse</strong></summary>

| Tool | Description |
|---|---|
| `gray_matter_pulse(topic, top_n?)` | Combined memory + knowledge + bridges + flash in one call |
| `gray_matter_status()` | Server summary: version, flash counter, registered servers |
| `gray_matter_bridge(neuron_concept, neurag_node, rationale?)` | Persist a cross-store bridge manually |

</details>

<details>
<summary><strong>Pass-through: Neuron tools</strong></summary>

All Neuron tools are republished with their original schemas:

`neuron_pre_turn`, `neuron_store_turn`, `neuron_confirm`, `neuron_get_context`,
`neuron_status`, `neuron_summary`, `neuron_vector_search`, `neuron_find_candidates`,
`neuron_merge`, `neuron_auto`, `neuron_extract`, `neuron_switch_context`,
`neuron_list_contexts`, `neuron_forgotten`, `neuron_prune`, `neuron_export`, `neuron_reset`

</details>

<details>
<summary><strong>Pass-through: NeuRAG tools</strong></summary>

All NeuRAG tools are republished with their original schemas:

`knowledge_query`, `knowledge_index`, `knowledge_add_node`, `knowledge_add_chunks`,
`knowledge_status`, `knowledge_tree`, `knowledge_health`,
`knowledge_link_graph`, `knowledge_rebuild_links`

</details>

---

## ⌨️ CLI reference

### Lifecycle

| Command | Description |
|---|---|
| `gray-matter install [--dry-run]` | Idempotent gateway install: reap orphans, register GM, deploy hooks |
| `gray-matter uninstall [--purge-data] [--yes] [--dry-run]` | Remove GM (interactive on memory) |
| `gray-matter repair` | Clean reinstall: choose what to delete, what to keep |
| `gray-matter start` | Start the GM daemon |
| `gray-matter stop` | Stop the GM daemon |

### Diagnostics

| Command | Description |
|---|---|
| `gray-matter ping` | Check if GM is running |
| `gray-matter status` | Show registered servers with tool lists |
| `gray-matter doctor` | Health snapshot: servers, workers, cache, bridges |
| `gray-matter stats` | Orchestrator counters: cache hit rate, flashes, latency |
| `gray-matter logs` | Show daemon log (last N lines) |

### Client management

| Command | Description |
|---|---|
| `gray-matter register [--gateway]` | Register the gateway in MCP clients |
| `gray-matter deregister <tool>` | Release a tool from the gateway (standalone mode) |
| `gray-matter link <tool>` | Re-attach a standalone tool to the gateway |

### Knowledge & bridges

| Command | Description |
|---|---|
| `gray-matter knowledge status` | NeuRAG knowledge base status (nodes, chunks, links) |
| `gray-matter knowledge rebuild-links` | Rebuild cross-links (tag_overlap + cross_ref) |
| `gray-matter knowledge link-graph` | Show the cross-link graph |
| `gray-matter bridges` | List persisted cross-store bridges |
| `gray-matter bridges-transfer` | Move bridges between local and cloud |
| `gray-matter bridge` | Expose the suite over HTTP for remote connectors |

### Configuration

| Command | Description |
|---|---|
| `gray-matter config list` | Show all tunable knobs |
| `gray-matter config set <key> <value>` | Set a knob |
| `gray-matter config get <key>` | Get a knob value |
| `gray-matter cloud` | Connect to Turso Cloud (interactive) |
| `gray-matter mode <collaborate\|separate>` | Set all servers to collaborate or separate |
| `gray-matter isolate <name>` | Exclude a server from the combined pulse |
| `gray-matter collaborate <name>` | Put a server back into the combined pulse |

### Interface

| Command | Description |
|---|---|
| `gray-matter gui [--classic]` | Open the web control center |
| `gray-matter gm-neuron <tool> <args>` | Call a Neuron tool via the gateway (testing) |
| `gray-matter gm-neurag <tool> <args>` | Call a NeuRAG tool via the gateway (testing) |

---

## 🏗️ Architecture

```
gray_matter/
├── server.py          # MCP server + daemon: pulse, bridges, flash, pass-through
├── _worker.py         # Persistent worker subprocess (imports server module once)
├── registry.py        # Server registry: liveness, tool schemas, collaborative flags
├── cache.py           # TTL + LRU context cache with targeted invalidation
├── bridges.py         # Cross-store bridge persistence + Hebbian promotion/decay
├── executor.py        # Effectful install/uninstall (writes files, registers clients)
├── installer.py       # Pure install plan (no side effects)
├── uninstaller.py     # Pure uninstall plan (no side effects)
├── clients.py         # MCP client config detection + registration
├── settings.py        # Tunable knobs (flash rate, cache TTL, prewarm, ...)
├── catalog.py         # GUI command catalog (introspects argparse, no hardcoded lists)
├── gme.py             # Tool registry (GME): multi-venv discovery, health tracking
├── shortcut.py        # Desktop shortcut creation (cross-platform: .lnk/.command/.desktop)
├── cli.py             # CLI entry point (24+ commands, argparse)
├── webgui.py          # Web-based control center (pywebview)
├── gui.py             # Legacy Tkinter control center
├── bridge.py          # HTTP bridge for remote connectors (ChatGPT, Perplexity)
├── _env.py            # Credential sanitization (shared with Neuron/NeuRAG)
└── tests/             # Test suite (34 tests)
```

**Key design decisions:**

- **Daemon singleton** on port 9876 (exclusive bind on Windows via `SO_EXCLUSIVEADDRUSE`).
- **stdio instances** survive without a listener — the managed workers don't need the port.
- **Gateway model**: clients see only `gray-matter`; GM self-bootstraps Neuron and NeuRAG
  as internal workers. `gray-matter register --gateway` evicts standalone entries.
- **Catalog SSOT**: the GUI reads commands from each tool's argparse — new subcommands
  appear automatically without touching the GUI code.
- **GME registry**: each tool writes a JSON file after install; the GUI reads these to find
  the correct Python for each tool (multi-venv support).

---

## 🛠️ Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q     # 34 tests, no network required
```

Key test modules: `test_executor.py`, `test_installer.py`, `test_uninstaller.py`,
`test_gateway_flip.py`, `test_settings.py`, `test_paths.py`.

Requires **Python 3.10+**.

---

## 🔧 Tuning

Gray Matter exposes two layers of configuration: **JSON knobs** (via `gray-matter config`)
and **environment variables** (set before starting the daemon).

### JSON config (`gray-matter config`)

| Knob | Default | What it controls |
|---|---|---|
| `flash_min_gap` | `3` | Minimum pulses between serendipitous flashbacks (anti-spam) |
| `cache_ttl_seconds` | `60` | TTL for the context cache — raise if topics repeat quickly |
| `cache_max_size` | `100` | LRU cap on cached pulse results |
| `prewarm` | `True` | Pre-warm worker models at startup (set `False` to save memory) |
| `heartbeat_interval` | `5.0` | Seconds between server liveness pings |
| `idle_sleep_timeout` | `600.0` | Seconds of idle before servers enter sleep mode |

```bash
gray-matter config list               # show all knobs
gray-matter config set cache_ttl_seconds 120
gray-matter config get flash_min_gap
```

### Environment variables

| Env var | Default | What it controls |
|---|---|---|
| `GM_PREWARM` | `"1"` | Set `"0"` to disable worker pre-warming |
| `GM_HOME` | `%LOCALAPPDATA%` (Win) / `$XDG_DATA_HOME` (Unix) | Root of all data dirs |
| `GRAY_MATTER_BRIDGES` | `~/.local/share/gray_matter/bridges.json` | Override bridges store path |

### Hardcoded constants (edit in source)

These are not yet exposed via config. Change them in `server.py` / `bridges.py` and restart:

| Constant | Value | File | What it controls |
|---|---|---|---|
| `HEARTBEAT_TIMEOUT` | `15.0` s | `server.py` | Missed heartbeats before marking a server dead |
| Worker call timeout | `60` s | `server.py` | Max time for a single worker pipe call |
| `_PROMOTE_AT` | `5` | `bridges.py` | Bridge weight to auto-promote a Neuron concept |
| `_WEIGHT_CAP` | `1000` | `bridges.py` | Max bridge weight (Hebbian cap) |

---

## 🗺️ Documentation map

| Doc | What's in it |
|---|---|
| **[INSTALL-AI.md](INSTALL-AI.md)** | Automated install + register instructions for AI agents |
| **[DOCTOOLUPDATE.md](DOCTOOLUPDATE.md)** | Complete tool documentation with real code examples |
| **[../neuron/README.md](../neuron/README.md)** | Neuron: semantic memory MCP server |
| **[../neurag/README.md](../neurag/README.md)** | NeuRAG: hierarchical knowledge base MCP server |

---

## 👤 Author

<div align="center">

**Gray Matter** is designed and built by **Claudio Costantino**.

<a href="https://www.linkedin.com/in/clacosta1999/"><img alt="LinkedIn" src="https://img.shields.io/badge/LinkedIn-Claudio_Costantino-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white"></a>
<a href="https://github.com/recla93/gray-matter"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-recla93%2Fgray--matter-181717?style=for-the-badge&logo=github&logoColor=white"></a>

</div>

---

## 🔌 What it orchestrates

Gray Matter is the gateway — on its own it routes, caches and bridges, but the
memory lives in the two servers it manages. Your client registers **one**
connector; both peers arrive through it as warm workers.

<table>
<tr>
<td width="50%" valign="top">

### 🧠 [Neuron](https://github.com/recla93/Neuron)
**Semantic memory — it learns.**

Concepts, typed links, salience and decay in a living graph. Answers
*"what did we decide, and why?"*

`pre_turn` · `store_turn` · `recall` · `find_candidates`

</td>
<td width="50%" valign="top">

### 📚 [NeuRAG](https://github.com/recla93/neurag)
**Knowledge vault — it keeps.**

A hierarchy of nodes and chunks, trigger-navigable. No decay: facts stay put.
Answers *"what do my documents say?"*

`knowledge_query` · `knowledge_ingest` · `knowledge_tree`

</td>
</tr>
</table>

Install either one next to Gray Matter and its installer picks it up
automatically. Neither is required: with one peer missing GM runs fine, just
with that half of the memory absent — and the session handshake announces only
the capabilities actually installed, never a tool that is not there.

Both are optional at runtime too — `gray-matter status` shows which are live,
and `gray_matter_pulse(topic)` merges whatever is present into one answer.

---

## 📜 License

**PolyForm Noncommercial License 1.0.0** — free for noncommercial use. See [LICENSE](LICENSE).

<div align="center"><sub>Built with ⚡ — one server, two brains, zero re-registration.</sub></div>
