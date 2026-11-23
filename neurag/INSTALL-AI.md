# INSTALL-AI — NeuRAG (hierarchical knowledge base)

> Instructions for an AI agent asked to install NeuRAG.

**Inside the umbrella repo** (`gray_matter/` and `neuron/` sit next to this
folder): stop here and follow `../gray_matter/INSTALL-AI.md`. It covers every
combination of the suite.

**In the standalone NeuRAG repo**, read on.

## Why you must not just run the installer

`install.ps1` / `install.sh` ask the human which mode, with an interactive
prompt. When you run them, nobody sees it: the installer takes the default
silently or fails on the prompt. So ask in chat first, then run
non-interactively (`GM_YES=1`) with the answer as a flag.

## 1. Ask the user

**What to install** — always ask:

| # | Choice | What the user gets |
|---|---|---|
| 1 | **NeuRAG + Gray Matter** (recommended) | knowledge base behind the GM gateway, GUI; GM is fetched if missing |
| 2 | **NeuRAG alone** | knowledge base only, registered directly in the MCP clients; no GUI, no bridges |

For the full suite (with Neuron's memory too), point the user to the Gray
Matter repo and its `INSTALL-AI.md`.

**If an install already exists**, ask: refresh the code (`-Force` /
`--force`), rebuild the venv (`-Clear` / `--clear`), or leave it. Data is kept
in both cases. Never offer a wipe.

## 2. Run

| # | Windows (PowerShell) | macOS / Linux |
|---|---|---|
| 1 | `$env:GM_YES="1"; $env:GM_NO_NEURON="1"; .\install.ps1` | `GM_YES=1 GM_NO_NEURON=1 sh install.sh` |
| 2 | `$env:GM_YES="1"; .\install.ps1 --no-gm` | `GM_YES=1 sh install.sh --no-gm` |

Inside Claude Desktop or another MSIX app on Windows, the installer refuses to
run: see the MSIX section of the Gray Matter `INSTALL-AI.md`.

## 3. Verify

- With GM: `gray-matter doctor`.
- Alone: the NeuRAG entry is listed in the client's MCP config.

Then tell the user to restart the AI apps.

## Data, ingest, rollback

- Knowledge base: `<data-dir>/neurag/knowledge.db` (Turso/SQLite; never touched by install).
- Ingest: `knowledge_index <dir>` or bulk YAML import (`neurag/importer.py`);
  adaptive chunking for .md/.py/.kt/.java/.pdf/.docx/.yaml.
- Embedding: lexical by default (zero deps); FastEmbed auto-detected if installed.
- Vault health: `knowledge_health` tool (orphans, broken hierarchy, empty chunks).
- Removal: `gray-matter uninstall` (interactive on data) or restore the `.bak` files.
