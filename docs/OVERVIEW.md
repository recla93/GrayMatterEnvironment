# Gray Matter Environment — overview

> The Gray Matter Environment is a suite of three MCP tools that give AI assistants
> persistent memory and a structured knowledge base. One gateway, full power.

## What it is

Gray Matter is a **gateway/proxy** that sits between your AI client (Claude Desktop, Cursor, VS Code, OpenCode, Gemini CLI, Windsurf, etc.) and two specialized backends:

- **Neuron** — persistent semantic memory. A concept graph that remembers what matters across sessions: keywords, links, domains, salience, trust, 384-dim vector embeddings. It learns from use and decays forgotten topics naturally.
- **NeuRAG** — hierarchical knowledge base. A structured vault of chunked documents with vector search, organized in a godnode/fundamental/specialization tree. Features auto-ingest, AST-aware chunking, Turso auto-provision, and cross-linking.

The client connects to **one MCP server** (Gray Matter). GM discovers, manages, and proxies to Neuron and NeuRAG as worker subprocesses. You get the power of three tools with one configuration entry.

## When to use it

- You want your AI assistant to **remember** across sessions (not start cold every time)
- You have a **knowledge base** (docs, notes, code) you want the assistant to search
- You want **cross-store intelligence**: Neuron's memory enriches NeuRAG's search, and vice versa
- You want **semantic flashes** — lateral associations that simulate analogical thinking
- You want **auto-ingest** — scan a folder and build a knowledge base automatically

## How it fits together

```
AI Client (Claude Desktop, Cursor, VS Code, OpenCode, ...)
    |
    | stdio (MCP protocol)
    v
Gray Matter (gateway/orchestrator)
    |
    +-- Neuron (semantic memory)     -- persistent worker subprocess
    +-- NeuRAG (knowledge base)      -- persistent worker subprocess
```

The gateway pattern means:
- One MCP server entry in your client config
- One process to launch
- Automatic sub-server discovery (Neuron and NeuRAG are detected via `importlib`)
- Persistent workers keep expensive models (fastembed) warm
- **Cross-store bridges** link Neuron concepts to NeuRAG nodes (Hebbian promotion/decay)
- **Context cache** (TTL + LRU) with targeted invalidation speeds up repeated queries
- **Semantic flashes** surface lateral associations every N turns
- **Catalog** introspects argparse from each tool — new CLI commands appear in the GUI automatically
- **GME registry** tracks health across multiple venvs for multi-tool installs
- **Desktop shortcuts** (cross-platform: .lnk/.command/.desktop) for one-click access

## Quick start

### One-click installer (recommended)

**Windows** — double-click `install.cmd`:
```powershell
.\install.ps1
```

**macOS / Linux**:
```sh
sh install.sh
```

### Verify

```bash
gray-matter doctor                              # health snapshot
gray-matter status                              # registered servers with tool lists
```

### Use from your AI client

```
gray_matter_pulse(topic="your topic")           # unified memory + knowledge call
```

### Or standalone

```bash
# Neuron only
pip install neuron
neuron register

# NeuRAG only
pip install neurag
python -m neurag.server
```

## Projects

| Project | Role | Version | License |
|---|---|---|---|
| Gray Matter | Gateway/orchestrator | 1.1.2 | PolyForm Noncommercial 1.0.0 |
| Neuron | Semantic memory | 6.1.2 | PolyForm Noncommercial 1.0.0 |
| NeuRAG | Knowledge base | 1.2.2 | PolyForm Noncommercial 1.0.0 |

## Documentation map

### Suite-level
| Document | What it covers |
|---|---|
| [ARCHITETTURA.md](../ARCHITETTURA.md) | Architecture deep dive (all three projects) |
| [INSTALL.md](INSTALL.md) | Installation for humans and AI agents |
| [GETTING-STARTED.md](GETTING-STARTED.md) | End-to-end tutorial (10 min) |
| [TOOLS.md](TOOLS.md) | Complete MCP tool reference |
| [CLI.md](CLI.md) | All command-line commands |
| [CONFIGURATION.md](CONFIGURATION.md) | Environment variables and config knobs |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Internal design and data flow |
| [DATA.md](DATA.md) | Database schemas and storage paths |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and fixes |
| [TECHNOLOGY.md](TECHNOLOGY.md) | Technology choices: why each tool was picked |
| [EVOLUTION.md](EVOLUTION.md) | How the project got here, era by era |
| [PROCESS.md](PROCESS.md) | How the team works, lessons learned |

### Per-project
| Project | Docs |
|---|---|
| Neuron | [README](../neuron/README.md) • [INSTALL-AI](../neuron/INSTALL-AI.md) • [DOCTOOLUPDATE](../neuron/DOCTOOLUPDATE.md) |
| NeuRAG | [README](../neurag/README.md) • [INSTALL-AI](../neurag/INSTALL-AI.md) • [DOCTOOLUPDATE](../neurag/DOCTOOLUPDATE.md) |
| Gray Matter | [README](../gray_matter/README.md) • [INSTALL-AI](../gray_matter/INSTALL-AI.md) • [DOCTOOLUPDATE](../gray_matter/DOCTOOLUPDATE.md) |

---

## Next steps

- [Installation](INSTALL.md) — get it running
- [Getting started](GETTING-STARTED.md) — end-to-end tutorial (10 min)
- [Architecture](../ARCHITETTURA.md) — understand the internals
- [Technology choices](TECHNOLOGY.md) — why each tool was picked
