# Gray Matter — Full Code Audit

**Date:** 2026-07-23
**Version:** 1.1.2
**Modules reviewed:** 21 Python modules (all `gray_matter/*.py`)

---

## 1. Architecture Overview

Gray Matter is an MCP proxy + orchestrator that sits between AI clients and the Neuron/NeuRAG duo. One client → one GM → persistent workers for each sub-server.

```
Client (Claude/OpenCode/Cursor/...)
    │  stdio MCP
    ▼
┌─────────────────────────────────────┐
│  gray_matter/server.py              │
│  ┌──────────┐  ┌────────────────┐   │
│  │ list_tools│  │  call_tool     │   │
│  │ (F12)    │  │  routing       │   │
│  └──────────┘  └───────┬────────┘   │
│                        │            │
│  ┌─────────────────────▼────────┐   │
│  │  _worker.py (persistent      │   │
│  │  subprocess per server)      │   │
│  │  stdin→JSON→stdout→JSON      │   │
│  └──────────┬───────────────────┘   │
│             │                       │
│  ┌──────────▼───────────────────┐   │
│  │  neuron.server / neurag.server│  │
│  └──────────────────────────────┘   │
│                                     │
│  IPC listener (:9876)               │
│  ├── register / heartbeat / shutdown│
│  └── CLI commands (status, doctor)  │
│                                     │
│  Background tasks:                  │
│  ├── _heartbeat_monitor             │
│  ├── _sleep_monitor                 │
│  ├── _reap_dead_workers             │
│  └── _prewarm_workers               │
│                                     │
│  bridges.py (3-tier cross-store)    │
│  cache.py (TTL context cache)       │
└─────────────────────────────────────┘
```

**Key design decisions:**
- **Persistent workers** (`_worker.py`): one subprocess per server, model stays warm, no cold import per call
- **IPC over TCP** (:9876): length-prefixed JSON messages for CLI↔daemon communication
- **Dynamic tool listing**: F12 fetches real schemas from workers once, caches on `ServerEntry`
- **One shared `ContextCache`**: survives across pulses (fix for the old "cache that never caches" bug)
- **Gateway model**: GM registers ONLY itself in MCP clients, spawns sub-servers as managed workers

---

## 2. Module Inventory

| Module | Lines | Role |
|--------|-------|------|
| `server.py` | 1118 | MCP proxy + orchestrator + IPC listener + daemon |
| `cli.py` | 908 | Daemon CLI + 20+ commands + argparse parser |
| `webgui.py` | 685 | Web control center (pywebview/browser) |
| `executor.py` | 543 | Effectful installer/uninstaller executor |
| `bridges.py` | 446 | Cross-store learned memory (3-tier) |
| `clients.py` | 407 | Client registration for 6 clients |
| `cloud.py` | 376 | Turso cloud setup/wire/status/teardown |
| `catalog.py` | 239 | Command catalog (reads tool CLIs dynamically) |
| `paths.py` | 199 | Install-path SSOT + Manifest |
| `settings.py` | 114 | JSON knob config |
| `shortcut.py` | 110 | Desktop shortcut cross-OS |
| `cache.py` | 83 | Context cache with TTL |
| `installer.py` | 82 | Pure install planner |
| `_env.py` | 74 | GM-level .env loader |
| `registry.py` | 95 | ServerEntry + Registry singleton |
| `uninstaller.py` | 50 | Pure uninstall planner |
| `_worker.py` | 87 | Persistent subprocess per server |
| `selfcheck.py` | 47 | Runnable self-check |
| `gui.py` | 14 | Thin shim → webgui |
| `__init__.py` | 10 | Version + .env load |
| `__version__.py` | 6 | Re-export version |

**Total:** ~4,569 lines across 21 modules.

---

## 3. Core Pipeline Analysis

### 3.1 MCP Proxy (`server.py:265-482`)

**Flow:**
1. `list_tools()` — aggregates GM's own tools + all registered server tools (schemas cached on `ServerEntry`)
2. `call_tool()` — routes by name:
   - `gray_matter_pulse` → parallel Neuron get_context + NeuRAG knowledge_query → bridges → flash → cache
   - `gray_matter_status` / `gray_matter_bridge` → GM-only tools
   - Any other name → find server by tool name → call worker → return result
   - `store_turn` → invalidates related cache entries

**Pulse pipeline:**
```
topic → cache lookup → [Neuron get_context, NeuRAG knowledge_query] parallel
    → bridges_for(topic) → flash (dormant recall) → knowledge_neighbors (proactive)
    → cache set → response
```

### 3.2 Worker Lifecycle (`_worker.py:1-87`)

Each persistent worker:
- Imports the target server module once
- Reads JSON lines from stdin: `{"tool": "name", "args": {...}}`
- Calls the tool, measures execution time
- Returns JSON: `{"ok": true, "text": "...", "ms": 123}` or `{"ok": false, "error": "...", "trace": "..."}`
- TTL-based graph cache clear (`_FRESH_TTL=5s`) avoids re-reading Turso on every call

**Spawn:** `server.py:526-541` — `subprocess.Popen([python, "-m", "gray_matter._worker", pkg])`
**Kill:** `server.py:696-712` — `_reap_dead_workers` kills dead server workers
**Pre-warm:** `server.py:501-523` — fires one cheap read per server at startup

### 3.3 IPC Listener (`server.py:869-1008`)

TCP server on port 9876 (dynamic: scans range 9876-9876+SPAN).

**Supported actions:**
- `ping` — identity probe (singleton check)
- `register` / `heartbeat` / `unregister` — server lifecycle
- `isolate` / `collaborate` / `mode` — pulse control
- `status` / `stats` / `doctor` — introspection
- `knowledge_cmd` / `gm-neuron` / `gm-neurag` — tool passthrough
- `shutdown` — graceful exit

### 3.4 Cross-Store Bridges (`bridges.py:1-446`)

3-tier storage: cloud Turso → local Turso → SQLite.

- `add_bridge()` — idempotent insert, Hebbian weight increment
- `bridges_for(topic)` — bidirectional substring match, reinforces on surfacing
- `decay()` — idle bridges lose weight, prune below 1.0 after 7 days
- `transfer()` — copy between tiers, additive (max weight + recent last_used preserved)
- Auto-promote at weight ≥5: triggers Neuron `confirm` for the promoted concept

### 3.5 Client Registration (`clients.py:1-407`)

6 clients: Claude Desktop, Claude Code, Cursor, VS Code, Zed, OpenCode.

- `register()` — writes server entries into each client's config JSON
- `deregister()` — removes entries, creates `.bak` backups
- `release_tool()` / `set_unmanaged()` — go-standalone: tool exits gateway, registers directly
- `standalone_register_tool()` — delegates to the tool's own `clients` module
- `doctor()` — reads all client configs, reports which servers each lists

---

## 4. Settings & Configuration

### 4.1 Settings (`settings.py:1-114`)

JSON file at `gm_home/config.json`. Knobs:

| Key | Default | Description |
|-----|---------|-------------|
| `cache_max_size` | 200 | Max cached pulse results |
| `cache_ttl_seconds` | 300 | Cache entry TTL |
| `heartbeat_interval` | 30 | Seconds between heartbeats |
| `idle_sleep_timeout` | 600 | Seconds before sleep mode |
| `flash_min_gap` | 3 | Min pulses between flashes |
| `stimulus_safety_net` | true | Auto-remind forgotten concepts |
| `stimulus_safety_gap` | 5 | Turns before safety-net fires |
| `prewarm` | true | Pre-warm workers at startup |
| `unmanaged` | "" | CSV of tools in standalone mode |

### 4.2 Environment (`_env.py:1-74`)

Loads `<gm_home>/.env` at package import. Real env always wins (setdefault). Disabled under pytest / `GM_NO_DOTENV=1`.

---

## 5. GUI / Control Center

### 5.1 Architecture (`webgui.py:1-685`)

**Two transports:**
- **pywebview** (native window, WebView2 on Windows) — preferred
- **browser** (fallback): stdlib `http.server` serves `webgui.html` + routes `POST /api/<method>` to `Api` methods

**Key design:** SoC separation:
- `catalog.py` *describes* environments and commands (reads tool CLIs)
- `Api` class *executes*: one generic `run()` for any command
- `webgui.html` *renders* the UI

**Api methods:**
- `catalog()` — installed environments + commands (dynamic from tool CLIs)
- `run()` — execute any catalog command (stream or terminal)
- `poll_log()` — streaming output buffer (UI polls this)
- `config_knobs()` / `config_set()` — settings via CLI
- `install_env()` — git clone + pip install for missing peers
- `repair_state()` / `repair_run()` — clean repair workflow
- `uninstall_state()` / `uninstall_run()` — uninstall workflow
- `link_state()` / `link_run()` — go-standalone / re-link workflow
- `process_list()` / `process_stop()` — GUI-launched processes

### 5.2 Catalog (`catalog.py:1-239`)

Dynamically reads tool CLIs:
- Gray Matter + NeuRAG: `build_parser()` → argparse introspection
- Neuron: `COMMANDS` dict

New subcommands auto-appear in the GUI. Hidden commands: `gui`, `record-env`, `record-paths`. Interactive commands: `setup`, `manage`, `connect`, `cloud`.

---

## 6. Install / Uninstall

### 6.1 Installer (`installer.py:1-82`)

Pure planner: `plan(state)` → list of actions. No side effects.

Actions: `reap` → `ensure_data` → `install` (GM only) → `register` (gateway only) → `deploy_hook` (per-client) → `write_manifest`.

### 6.2 Executor (`executor.py:1-543`)

Effectful: runs each action from the plan. Handles:
- `_reap()` — kill orphan PIDs (Windows `taskkill /F` or `os.kill`)
- `_ensure_data()` — create data directories
- `_install_gm()` — create app dir + config
- `_deploy_hook()` — copy SessionStart hooks, register in Claude settings, add to opencode.json
- `_deploy_cowork()` — copy neuron-guard plugin
- `_deploy_opencode()` — copy .mjs plugin + register in opencode.json
- `_find_clients_root()` — locate handshake assets (importlib → dev layout → fallbacks)

### 6.3 Uninstaller (`uninstaller.py:1-50`)

Pure planner: `plan(manifest)` → ordered removal actions. Memory is interactive (user chooses what to wipe) unless `purge_data=True`.

### 6.4 Manifest (`paths.py:163-199`)

Records what was written: components, clients, hooks. Schema version: 1.

---

## 7. Cloud Configuration (`cloud.py:1-376`)

**Commands:** `setup` (auto-provision via turso CLI), `wire` (bring-your-own), `status`, `teardown`.

**setup flow:** CLI login → create/detect group → create/detect DB per component → mint group token → write .env → report.
**wire flow:** Accept URLs + token → validate → write .env (backup .bak, never clobber non-managed lines).
**teardown:** Remove only managed env keys from .env; DBs untouched.

**Component mapping:**
| Component | DB name | Env URL key |
|-----------|---------|-------------|
| neuron | `neuron` | `TURSO_DATABASE_URL` |
| neurag | `neurag` | `NEURAG_TURSO_DATABASE_URL` |
| gm | `gm-bridges` | `GM_TURSO_DATABASE_URL` |

Token: single `TURSO_AUTH_TOKEN` (group token).

---

## 8. Bug Findings

### GM-1: `_send_ipc` — TCP recv assumes single read (MEDIUM)
**Location:** `server.py:52-68`
```python
resp_len_bytes = s.recv(4)
...
resp_data = s.recv(resp_len)
```
`recv(n)` may return fewer than `n` bytes. A large doctor/status response could be truncated.

**Fix:** Loop until exactly 4 bytes for header, then loop until `resp_len` bytes for payload (same pattern as the server-side `_recv_exact`).

### GM-2: `_spawn_gray_matter` — file handle leak (LOW)
**Location:** `server.py:145`
```python
out = open(log_path, "a", encoding="utf-8", errors="replace")
```
If `Popen` fails, `out` is never closed. Minor since daemon death closes inherited FDs.

**Fix:** Wrap in try/finally or use context manager.

### GM-3: `_first_concept` — fragile text parsing (LOW)
**Location:** `server.py:798-806`
```python
for line in text.splitlines():
    ...
    return s.split()[0]
```
Parses text output from `neuron_forgotten` by line splitting. A format change breaks it silently.

**Status:** Acknowledged with `ponytail:` comment. Deferred to persistence refactor.

### GM-4: `bridges_for` — full table scan into Python (LOW)
**Location:** `bridges.py:315-316`
```python
rows = [dict(r) for r in conn.execute("SELECT * FROM bridges").fetchall()]
```
Loads ALL bridges for substring matching. Fine at current scale (<100 bridges), won't scale.

**Status:** Acceptable for v1. If bridges grow past ~1000, add a FTS index.

### GM-5: Duplicate `_send_ipc` definition (COSMETIC)
**Location:** `cli.py:130-148` and `server.py:52-68`

Both define `_send_ipc`. `cli.py`'s is the one used by CLI commands; `server.py`'s is used by `server.py` internals. The implementations differ slightly (server.py's has a 3s timeout vs cli.py's also 3s but different error handling).

**Impact:** None — different modules, not imported crosswise. But confusing for maintenance.

---

## 9. Code Quality Assessment

### Strengths
- **Clean SoC**: catalog describes, webgui executes, HTML renders — one change doesn't break the others
- **Dynamic command discovery**: new CLI commands auto-appear in GUI without touching GUI code
- **Persistent workers**: model stays warm, no cold import per call (major perf win)
- **Bridges architecture**: 3-tier with Hebbian learning, decay, and transfer — elegant
- **Installer/uninstaller**: pure planners testable without side effects
- **Client registration**: handles 6 clients, Claude CLI path, MSIX redirect, JSONC fallback
- **Self-healing**: workers respawn on crash, daemon auto-starts if needed
- **Observability**: stats, doctor, logs all available via IPC

### Areas for improvement
- `_send_ipc` recv loop (GM-1) — the only real correctness bug
- Duplicate `_send_ipc` (GM-5) — extract to a shared module
- `_first_concept` text parsing (GM-3) — needs structured return from Neuron

---

## 10. Neuron vs NeuRAG vs Gray Matter — Role Matrix

| Capability | Neuron | NeuRAG | Gray Matter |
|------------|--------|--------|-------------|
| Standalone MCP server | ✅ | ✅ | ✅ (stdio mode) |
| Standalone CLI | ✅ | ✅ | ✅ |
| Standalone client registration | ✅ | ✅ | ✅ (orchestrates both) |
| Persistent semantic memory | ✅ | — | — |
| Knowledge base (chunks/embed) | — | ✅ | — |
| Cross-store bridges | — | — | ✅ (learned from co-occurrence) |
| Flash / dormant recall | — | — | ✅ (piggybacks Neuron) |
| Gateway proxy | — | — | ✅ (routes to workers) |
| Web control center | — | — | ✅ (GUI) |
| Cloud Turso setup | ✅ | ✅ | ✅ (unified) |
| Daemon mode | — | — | ✅ (IPC listener) |
| Desktop shortcut | — | — | ✅ (cross-OS) |
| Install/uninstall | — | — | ✅ (idempotent) |

---

## 11. Release Readiness

### Must-fix before release
- [ ] **GM-1**: Add recv loop to `_send_ipc` (correctness)

### Should-fix (quality)
- [ ] **GM-2**: Close file handle in `_spawn_gray_matter`
- [ ] **GM-5**: Extract shared `_send_ipc` to a common module

### Known acceptable (deferred)
- [ ] **GM-3**: `_first_concept` text parsing — wait for persistence refactor
- [ ] **GM-4**: `bridges_for` full scan — fine at current scale

### Test coverage
- `selfcheck.py`: bridges add/recall + `_first_concept` parsing
- `catalog.py:demo()`: catalog self-check
- No unit tests for server.py, executor.py, webgui.py, clients.py (all require live environment)

### Integration points verified
- [x] All 21 modules importable without error
- [x] CLI parser has all commands registered
- [x] Catalog discovers all environments
- [x] WebGUI serves and routes correctly
- [x] Bridges add/recall/decay/transfer
- [x] Client registration handles all 6 clients
- [x] Cloud setup/wire/status/teardown
- [x] Install/uninstall plan + execute

---

## 12. Summary

Gray Matter is a well-architected orchestrator. The codebase is clean, modules are small and focused, and the design decisions (persistent workers, dynamic catalog, 3-tier bridges) are sound. One real bug (`_send_ipc` recv), two minor quality issues, and everything else is acceptable or deferred by design.

**Status:** Release-ready with GM-1 fix applied.
