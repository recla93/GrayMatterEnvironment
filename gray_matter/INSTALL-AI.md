# INSTALL-AI — Gray Matter suite (GM + Neuron, NeuRAG as an add-on)

> Instructions for an AI agent asked to install this suite. This file is the
> single entry point: `neuron/INSTALL-AI.md` and `neurag/INSTALL-AI.md` send
> you here.

## Why you must not just run the installer

The installers ask the human questions with an interactive prompt (which
tools, which embedding model, what to do with an existing install). When you
run them, nobody sees those prompts: the installer either takes the default
silently or fails on the prompt. So **you** ask the questions in chat, then run
the installer non-interactively (`GM_YES=1`) with the answers as flags.

## 1. Ask the user — before running anything

**Question 1 — what to install.** Always ask; never pick for them.

| # | Choice | What the user gets |
|---|---|---|
| 1 | **Neuron + Gray Matter** (recommended, the default) | persistent memory behind the gateway, with hooks and GUI; no knowledge base |
| 2 | **Full suite** | the above + NeuRAG (knowledge base), the add-on for an archive of project documents |
| 3 | **NeuRAG + Gray Matter** | knowledge base behind the gateway, with GUI; no memory, no session hooks |
| 4 | **Neuron alone** | memory only, registered directly in the MCP clients; no GUI, no bridges |
| 5 | **NeuRAG alone** | knowledge base only, registered directly; no GUI, no bridges |

Without GM the user loses: bridges between Neuron and NeuRAG, neighbor
auto-surface, the GUI control center, automatic registration of the gateway.

**When NeuRAG is worth it** (ADR-023, measured): it is the archive of the
user's *project documentation* — designs, specs, decisions, Word files
included — kept outside the repository they work in. On those documents its
one-line pointer named the right section 10 times in 11. It does not help with
the repository being worked on (already on disk) nor with general knowledge
(the model has it). So the default leaves it out: offer 2 only to a user who
has such documents.

**Question 2 — embedding model.** Only for choices that include Neuron (1, 2, 4).
Changing it later means re-embedding the whole store, so ask.

| # | Model | Size | Note |
|---|---|---|---|
| 1 | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 220 MB | multilingual (EN+IT), default |
| 2 | `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | 1.0 GB | multilingual, stronger |

**Question 3 — only if a previous install exists.** Look for the venv
`<suite>/graymatter/.venv`, where `<suite>` is `GM_HOME` if set, else on
Windows `%USERPROFILE%\GrayMatterEnvironment` (or an older
`%LOCALAPPDATA%\GrayMatterEnvironment`), on Linux/macOS
`$XDG_DATA_HOME/GrayMatterEnvironment` or `~/.local/share/GrayMatterEnvironment`.
If it exists, ask:

| Choice | Flag | Effect |
|---|---|---|
| Refresh the code | `-Force` / `--force` | reinstalls the code; data, settings, registrations kept |
| Rebuild the venv | `-Clear` / `--clear` | deletes the venv and rebuilds it; data kept |
| Leave it | — | do not run the installer |

Never offer a wipe. Deleting memory and knowledge is for the human to do by
hand (`gray-matter uninstall`, interactive).

## 2. Run the matching command

Run from the folder of the repo you were given. In the umbrella repo the three
tools are siblings: `gray_matter/`, `neuron/`, `neurag/`. Add the embedding
model and the Question 3 flag to the command. An upgrade keeps NeuRAG when it
is already installed, with or without `GM_WITH_NEURAG`.

**Windows (PowerShell):**

| # | Command |
|---|---|
| 1 | `$env:GM_YES="1"; .\gray_matter\install.ps1 -EmbedModel <model>` |
| 2 | `$env:GM_YES="1"; $env:GM_WITH_NEURAG="1"; .\gray_matter\install.ps1 -EmbedModel <model>` |
| 3 | `$env:GM_YES="1"; $env:GM_WITH_NEURAG="1"; $env:GM_NO_NEURON="1"; .\gray_matter\install.ps1` |
| 4 | `$env:GM_YES="1"; .\neuron\install.ps1 --no-gm -EmbedModel <model>` |
| 5 | `$env:GM_YES="1"; .\neurag\install.ps1 --no-gm` |

**macOS / Linux:**

| # | Command |
|---|---|
| 1 | `GM_YES=1 GM_EMBED_MODEL=<model> sh gray_matter/install.sh` |
| 2 | `GM_YES=1 GM_WITH_NEURAG=1 GM_EMBED_MODEL=<model> sh gray_matter/install.sh` |
| 3 | `GM_YES=1 GM_WITH_NEURAG=1 GM_NO_NEURON=1 sh gray_matter/install.sh` |
| 4 | `GM_YES=1 sh neuron/install.sh --no-gm --embed-model <model>` |
| 5 | `GM_YES=1 sh neurag/install.sh --no-gm` |

The install takes minutes (it downloads Python if missing, and the embedding
model): run it in the background and wait for `INSTALL COMPLETE`.

### Windows: when you run inside Claude Desktop or another MSIX app

The default suite is in `%USERPROFILE%`, outside AppData, so the installer
runs from inside Claude Desktop as it is. It refuses only when the suite it
finds is an older one under `%LOCALAPPDATA%`: writes to AppData inside an MSIX
app land in a private copy the other apps never see. If it stops with that
message, do not set `GM_HOME` just for this run: the installer does not make it
persistent, so code and data would end up in two different roots. Launch the
installer outside the container, as a normal process:

```powershell
$cmd = 'powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:GM_YES=''1''; & ''<repo>\gray_matter\install.ps1'' *> ''<log file>''"'
Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
```

Then follow the log file until `INSTALL COMPLETE`. Add the same env vars and
flags of the chosen row inside the quoted command.

## 3. Verify and report

```bash
gray-matter doctor    # only gray-matter in the clients; warns if the vector tier is degraded
gray-matter ping
```

For a standalone install (4, 5) there is no `gray-matter`: check that the tool
is listed in the client's MCP config.

Tell the user what was installed, then: **restart the AI apps** so they load
the new MCP server.

## 4. Rollback / removal

```bash
gray-matter uninstall --dry-run
gray-matter uninstall            # interactive: asks BEFORE touching memory
```

User memory (graphs, knowledge.db, bridges) is never deleted without explicit
consent. Spec: `INSTALLER-UX.md`; paths: `gray_matter/paths.py`.
