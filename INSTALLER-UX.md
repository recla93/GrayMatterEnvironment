# INSTALLER & UX — how the trio is deployed

> Single source of truth for deployment: registration model, per-OS paths,
> install manifest, install/uninstall/scan flows, command and tuning surface.
> Decisions fixed on 2026-07-18; translated and brought up to date with the code
> on 2026-10-26. The code cites this file by section (`INSTALLER-UX §5`): keep
> the numbers stable.

---

## 1. Model: Gray Matter as the gateway — one connector

In MCP the LLM sees **only the tools the connected server declares**; it never
talks to processes directly. So:

- The MCP client connects **one** server: **Gray Matter**.
- GM declares its own tools (`pulse`, `status`, `bridge`) **and re-publishes**
  Neuron's and NeuRAG's (pass-through). To the LLM they are all "GM tools".
- When the LLM calls `store_turn`, `knowledge_query` and so on, **GM forwards**
  the call to the sub-server's **worker** (stdin/stdout channel, `_worker.py`),
  takes the result and returns it.
- Neuron and NeuRAG run as **sub-processes managed by GM**, NOT as client
  connectors. GM is both the *MCP server* towards the client and the *manager*
  of the workers.

**Keystone — F12, implemented.** A proxied tool is usable only if the LLM has
its name, description **and argument schema**. GM asks each worker for its real
tool list (`list_tools`) and re-publishes the schemas
(`gray_matter/_worker.py`, `gray_matter/server.py`).

**Trade-off.** GM is a single point of failure: if GM dies, the tools vanish.
Mitigations: GM respawns the workers; the client relaunches GM at startup;
`doctor` repairs. In exchange: one connector, orchestration (`pulse`, cache,
flash, bridges), and a GM that can be deployed on its own.

**What to register in MCP clients:** **Gray Matter only.**

**Self-bootstrap.** Since the client launches only GM, the sub-servers no
longer register themselves over IPC. GM **discovers** them
(`detect_subservers`), registers them as **managed** (`register_managed`: alive
without heartbeat) and loads their tools from the worker (F12). Wired in
`main()` (`_bootstrap_subservers`); `heartbeat_monitor` ignores managed servers.

---

## 2. Deploy: GM is the centre, bundled by every tool

- Download **Neuron** → its installer installs **Neuron + Gray Matter**.
- Download **NeuRAG** → its installer installs **NeuRAG + Gray Matter**.
- GM is **shared and idempotent**: if present, it is reused or upgraded, never
  installed twice. One GM per machine.
- GM works with **a single** sub-tool installed: `pulse` handles absent servers.

---

## 3. Per-OS paths

**ONE base per OS**, identical in every module that resolves paths
(`neuron/config.py`, `neuron/paths.py`, `neuron/project.py`, `neuron/tunnel.py`,
`neurag/paths.py`, `gray_matter/paths.py`, `gray_matter/gme.py:user_base()`):

```
Windows        %LOCALAPPDATA%
macOS / Linux  $XDG_DATA_HOME, else ~/.local/share
```

Under it, **one suite root**: `<base>/GrayMatterEnvironment/`.

> **macOS does not use `~/Library/Application Support`** — a deliberate choice
> (2026-07-29). It is the Apple convention and `gme.py` followed it, but it was
> the ONLY place that did: the other six resolved `~/.local/share`. On a Mac the
> tool registry ended up in `Library` and all the DATA in `.local/share`. One
> root beats the most idiomatic root. An existing `Library` registry is still
> read (what is installed wins), so no Mac loses anything.

| What | Path (`<root>` = `<base>/GrayMatterEnvironment`) | Override |
|---|---|---|
| Neuron graphs | `<root>/neuron/graphs` | `NS_GRAPHS_DIR` |
| NeuRAG vault | `<root>/neurag/knowledge.db` | `NEURAG_HOME` |
| NeuRAG settings | `<root>/neurag/config.json` | `NEURAG_HOME` |
| GM config (tuning knobs) | `<root>/graymatter/config.json` | `GM_HOME` |
| GM bridges | `<root>/graymatter/bridges.db` | `GM_HOME` |
| GM blackboard | `<root>/graymatter/state.db` | `GM_HOME` |
| Install manifest | `<root>/graymatter/manifest.json` | `GM_HOME` |
| PID registry | `<root>/graymatter/pids.json` | `GM_HOME` |
| Logs | `<root>/graymatter/logs/` | `GM_HOME` |
| Daily backups | `<root>/backups/` | `GM_HOME` |
| Tool registry (GME) | `<root>/registry/<tool>.json` | — |
| Tunnel config | `<root>/registry/tunnel.json` | — |
| Shared venv | `<base>/graymatter/.venv` (before 1.4.1: `<base>/gray-matter/.venv`) | the manifest records it |
| Project marker | `<project>/.neuron/project.json` | — |
| MCP client configs | see `clients.py` (6 clients) | — |

**An existing store always wins.** Each tool used to write in its own root
(`<base>/neuron`, `<base>/neurag`, and NeuRAG in `~/.local/share/neurag` on
every OS, Windows included). A store already in an old location keeps being
used there: changing the rule must not make a memory disappear. The move is
explicit (`gray_matter.paths.migrate_to_suite_root`), never a side effect of an
upgrade.

> The slug is **`neuron`**, not `neuron5`: `neuron5` is retired and survives
> only where it is recognised as legacy (`test_installer_parity.py` fails if it
> reappears in an installer).

Rule: **data** (graphs, DBs, bridges) is kept apart from **code** (venv,
binaries). Uninstall treats them differently (§6).

---

## 4. Install manifest — the record of what went where

Without a manifest, uninstall is guesswork. The installer writes:

```json
{
  "schema": 1,
  "installed_at": "2026-07-18T..",
  "components": {
    "gray_matter": {"version": "…", "app_dir": "…", "exe": "…"},
    "neuron":      {"version": "…", "data_dir": "…", "slug": "neuron"},
    "neurag":      {"version": "…", "db": "…"}
  },
  "clients_registered": ["claude-desktop", "claude-code", "cursor", "vscode", "opencode", "codex"],
  "python": "C:\\Python314\\python.exe",
  "pids_file": "…\\graymatter\\pids.json"
}
```

Uninstall reads the manifest and removes **exactly** what was written.

---

## 5. Install flow (idempotent, GM-centric)

1. **Mode selector** (interactive only, not with `--no-gm` / `-Force`):
   - **Full suite** (default, Enter) — GM + Neuron + NeuRAG
   - **Neuron/NeuRAG only** — standalone, registers directly in the clients
   - **Details** — shows what is lost without GM, then asks again
2. **Detect** existing installs (manifest, data dirs, client entries, processes).
3. **Stop** orphan processes BEFORE writing (avoids Windows file locks and
   several writers on the same store).
4. Install the requested tool (Neuron or NeuRAG).
5. **Ensure GM**: install if absent, upgrade if present (never duplicate).
6. **Register ONLY GM** in the MCP clients (`clients.py`); GM runs the workers.
7. Write or update **manifest** and **pids**.
8. Final `doctor`: checks registration and startup.

---

## 6. Uninstall flow (INTERACTIVE on data) + legacy scan

Decision: **always ask** before touching the user's memory.

1. **Stop** the trio's processes (from pids/manifest; fallback: scan by name).
2. **Deregister** from the MCP clients (`deregister_all` in `clients.py`).
3. **Remove code, binaries, venv** (from the manifest).
4. **Data (graphs, DBs, bridges): ASK** — "Keep the memory? [keep/delete]".
   Nothing is deleted without an explicit answer.
5. **Legacy scan** (`--deep`): finds and reports artefacts of old installs —
   - the retired `neuron5` slug and its data dirs;
   - the old name **Neural-Stimulus** (absent from the repo, so only leftovers on
     disk);
   - scripts on PATH, stale config entries in the 6 clients, orphan processes;
   - lists them; `--purge` removes them after confirmation.
6. Removes the manifest last.

---

## 7. Processes — singleton and reaping

- **pids.json** tracks the PIDs of GM and its workers.
- At GM startup: if a healthy GM already holds the IPC port, a second one does
  not start.
- `gray-matter doctor` detects orphan processes (four Neuron servers were seen
  on 2026-07-18) and offers to stop them. This is functional, not hygiene:
  several servers on the same store risk overwriting each other.

---

## 8. Command and tuning surface

The CLIs exist per tool — Neuron (`setup/manage/doctor/register/consolidate/
console/connect/bridge/tunnel/gui`), GM (`status/stats/doctor/start/stop/
isolate/collaborate/mode/register/bridges/gui`). The command centre **unifies**
control of the three under GM, plus:

- **One config file** (`<root>/graymatter/config.json`) for the knobs that used
  to be scattered as constants and env vars: flash rate (`FLASH_MIN_GAP`), cache
  TTL and size, `consolidate` cadence, salience thresholds.
- Commands: `gray-matter config get|set|list <key> [value]`, `gray-matter
  install|uninstall|scan`, editable from the GUI too. Tuning never needs a code
  edit (`settings.py`).

---

## 8b. Hooks & plugins — the handshake layer (per client, NOT GM's job)

Two separate jobs:

- **Tool routing and schemas → GM** (the proxy, F12).
- **Session handshake → hooks/plugins, per client.** They inject the loop
  guidance ("call `pre_turn` first, `store_turn` after") at session start. GM
  **cannot** do it: hooks fire inside the client around the prompt, not inside
  the MCP channel. An MCP server can only offer `instructions` at the handshake,
  which some clients show and others ignore: that is *why* hooks exist.

The assets live in `neuron/src/neuron/clients/` and travel in the wheel:

| Client | Handshake mechanism |
|---|---|
| Claude Code / Cowork | SessionStart hook + `neuron-guard` plugin (`hooks/hooks.json`) |
| OpenCode | `neuron-handshake.mjs` plugin (`experimental.chat.system.transform`) |
| Cursor / VS Code / Codex | MCP `instructions` served by the server (no separate hook) |

Consequences of the "GM only" model:

1. Hooks and plugins **stay**: they are a per-client layer, not part of GM.
2. **GM's unified installer deploys them**; uninstall removes them per client
   (`neuron/scripts/uninstall.ps1` has the granular plugin/hook wipe).
3. **GM serves the `instructions`** at the MCP handshake: clients that honour
   them need no hook; the hook remains for the ones that ignore them.
4. The **manifest** (§4) records the hooks and plugins deployed per client, so
   uninstall knows exactly what to remove (`installer.py`).
