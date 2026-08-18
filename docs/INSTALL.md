# Installation

> How to install the Gray Matter Environment (Gray Matter + Neuron + NeuRAG).
> The `gray_matter` download bundles all three: one installer sets up the whole
> suite behind a single MCP connector. For per-project detail see
> [`neuron/INSTALL.md`](../neuron/INSTALL.md).

## Prerequisites

- **Python 3.10+** (3.12 recommended). The installer can bootstrap it for you on
  Windows (winget), macOS (Homebrew), Debian/Ubuntu (apt) and Fedora (dnf) with
  your consent.
- An MCP client: Claude Desktop, Cursor, VS Code, OpenCode, Gemini CLI, Windsurf.
- No compiler needed: `pyturso` installs from prebuilt wheels vendored in
  `neuron/vendor/` (`--find-links`), so nothing builds from source.

## 1. One-click installer (recommended)

The full-suite installer lives in the `gray_matter` folder and installs Gray
Matter plus whichever peers (Neuron, NeuRAG) sit next to it into **one shared
venv**, registers them in your MCP clients, and opens the control center.

**Windows** — double-click `install.cmd` in the root or `gray_matter\install.cmd`:

```powershell
.\install.ps1                                    # root
powershell -NoProfile -ExecutionPolicy Bypass -File .\gray_matter\install.ps1  # gray_matter/
```

**macOS / Linux** — double-click `install.command` or:

```sh
sh install.sh                                    # root
sh gray_matter/install.sh                        # gray_matter/
```

Non-interactive (CI / scripted):

```sh
sh install.sh --yes
```

What it does:
1. Finds/bootstraps Python 3.10+ (winget on Windows, brew/apt on Linux/macOS)
2. Creates one shared venv
3. Installs GM + bundled Neuron + NeuRAG (pyturso wheels from `neuron/vendor/`, fastembed best-effort)
4. `gray-matter install` — registers ONLY the gateway in every detected MCP client
   with `.bak` backups, deploys session hooks, writes manifest
5. Desktop GUI shortcut → opens the control center

## 2. Verify

```sh
gray-matter doctor                              # health snapshot
gray-matter status                              # registered servers with tool lists
gray-matter stats                               # cache hit rate, flashes, bridges, latency
```

Then, from your AI client, call `gray_matter_pulse(topic="hello")`. One MCP
entry (Gray Matter) exposes all Neuron + NeuRAG tools.

## 3. Individual repos (standalone mode)

Each project is also available as a standalone repo with its own installer:

| You downloaded | Double-click | You get |
|---|---|---|
| **gray_matter** (full suite) | `install.cmd` / `install.command` | GM + bundled Neuron + NeuRAG |
| **Neuron** | `install.cmd` / `install.command` | Mode selector → Full suite or Solo Neuron |
| **neurag** | `install.cmd` / `install.command` | Mode selector → Full suite or Solo NeuRAG |

Running a standalone installer shows a **mode selector**:

```
  Installation mode:
    [F] Full suite — GM + Neuron + NeuRAG (recommended)
    [N] Solo Neuron — standalone (registers directly in clients)
    [D] Details — what you lose without GM

  Choice [F]:
```

Press **Enter** for the default (Full suite). Choose **N** for standalone mode —
the tool installs in its own venv and registers itself directly in MCP clients.
Without GM you lose only the cross-store links (bridges) and the neighbor
auto-surface; you keep memory, knowledge and every native stimulus.

Headless / CI: pass `--no-gm` or set `GM_OPTIN=0` to skip the selector and
install standalone. If GM cannot be obtained (offline), the installer degrades
to standalone instead of exiting.

## 4. pip (source checkout)

```sh
git clone https://github.com/recla93/Neuron.git
cd Neuron

# Install all three:
pip install -e gray_matter -e neuron -e neurag

# Or individually:
pip install -e neuron                            # Neuron only
pip install -e neurag                            # NeuRAG only
pip install -e neurag"[semantic,cloud]"          # NeuRAG with optional deps
pip install -e gray_matter -e gray_matter"[dev,cloud,rag,gui]"  # Gray Matter only
```

### Windows (pyturso)

On Windows, point pip at the vendored pyturso wheels:

```sh
pip install --find-links neuron/vendor neuron neurag gray_matter
```

### Register the gateway

```sh
gray-matter install --dry-run                    # preview: what would happen
gray-matter install                             # idempotent, .bak backups, manifest
```

`install` registers only `gray-matter` in your MCP clients and evicts standalone
Neuron/NeuRAG entries (backups saved as `.bak`).

## 5. Upgrade

Re-run the one-click installer (step 1). It reuses the shared venv and
re-registers clients idempotently.

## 6. Uninstall

```sh
gray-matter uninstall                            # app only: venv, deps, client de-registration
gray-matter uninstall --dry-run                  # preview a full wipe, change nothing
gray-matter uninstall --purge-data --yes         # also memory graph + NeuRAG vault + .env secrets
```

Interactive mode: asks BEFORE touching memory. Memory (graph, vault, bridges) is
never deleted without `--purge-data`.

## 7. Troubleshooting

- **`pip` tries to compile pyturso / "Microsoft Visual C++ required" (Windows):**
  you skipped the vendored wheels. Re-run with `--find-links neuron/vendor`.
- **`pyturso` wheel doesn't match my Python:** the vendored wheels cover
  cp310–cp314 on `win_amd64`. Use Python 3.10–3.14, or install on Linux/macOS
  where PyPI serves matching wheels.
- **`ModuleNotFoundError: fastembed` / `mcp`:** the venv is incomplete — re-run
  the installer, or `pip install -e .` in each repo.
- **The client doesn't see the tools:** confirm the daemon is up
  (`gray-matter status`) and that the client was restarted after registration.
- **Turso auto-install fails:** NeuRAG tries to install pyturso automatically from
  bundled wheels. If it fails, it degrades to sqlite3. Check `knowledge_status`
  for engine info. Set `NEURAG_REQUIRE_TURSO=0` to skip auto-install.

## 8. Environment variables (quick reference)

### Neuron
| Env var | Default | Funzione |
|---|---|---|
| `TURSO_DATABASE_URL` | (empty) | URL Turso remoto |
| `TURSO_AUTH_TOKEN` | (empty) | Token auth Turso |
| `NEURON_NO_DOTENV` | `"0"` | Se `"1"`, salta `.env` |
| `NS_GRAPHS_DIR` | (home) | Directory storage grafi |

### NeuRAG
| Env var | Default | Funzione |
|---|---|---|
| `NEURAG_EMBEDDER` | `"auto"` | Embedder: `auto`/`fastembed`/`null` |
| `NEURAG_RERANK` | `"off"` | Reranker: `on`/`off` |
| `NEURAG_TURSO_DATABASE_URL` | (empty) | URL Turso remoto (SEPARATO da Neuron!) |
| `NEURAG_REQUIRE_TURSO` | `"1"` | Se `"0"`, salta auto-install |

### Gray Matter
| Env var | Default | Funzione |
|---|---|---|
| `GM_FLASH_RATE` | `0.15` | Probabilità flash per turno |
| `GM_CACHE_TTL` | `3600` | TTL cache in secondi |
| `GM_PREWARM` | `"1"` | Pre-warm modelli all'avvio |

For the full per-component matrix, see [`neuron/INSTALL.md`](../neuron/INSTALL.md).

---

## Next steps

- [Getting started](GETTING-STARTED.md) — end-to-end tutorial (10 min)
- [Configuration](CONFIGURATION.md) — environment variables and tiers
- [Troubleshooting](TROUBLESHOOTING.md) — symptom → diagnosis → fix
