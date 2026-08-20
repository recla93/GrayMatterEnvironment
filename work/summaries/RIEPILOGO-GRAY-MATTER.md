# RIEPILOGO DOCUMENTAZIONE — GRAY MATTER

> Gateway/orchestratore MCP che unisce Neuron + NeuRAG in un unico server.
> Versione: 1.1.2 | Autore: Claudio Costantino | License: PolyForm Noncommercial 1.0.0

---

## 1. Documenti nella cartella `gray_matter/`

### Root
| File | Contenuto |
|------|-----------|
| `README.md` | Landing page completa: Gray Matter = MCP gateway/orchestrator tra AI client e duo Neuron+NeuRAG. Highlights: one server to rule, unified pulse, cross-store bridges, warm workers, smart cache (TTL+LRU), flash recall, CLI, web GUI. Quickstart, 3 MCP tools, CLI reference (24 comandi), architettura ASCII, tuning (JSON knobs + env vars) |
| `CHANGELOG.md` | Storia v0.2.0→v1.1.2. v1.1.2: GUI universale decoupling (Config/Repair/Uninstall/Processi passano per CLI --json), desktop shortcut cross-OS, pannello Processi leggero. v1.1.1: fix CMD flash, audit comandi. v1.1.0: deregister per-tool (go-standalone), GUI universale. v1.0.x: path SSOT, porta dinamica, repair/reinstall, cache TTL dinamica, wizard GUI, gateway flip, installer/uninstaller, bridge come 3-store, env model daemon→worker, cloud CLI, doctor esteso, stimulus safety-net, logs, wire (turso senza CLI), GUI adattiva+dashboard |
| `pyproject.toml` | v1.1.2, dipendenze: mcp≥1.28. Extras: cloud (libsql-client), dev (pytest), gui (pywebview), rag (neurag). Entry points: `gray-matter`, `gray-matter-mcp`, `gray-matter-gui` (gui-scripts). Flat layout |
| `__init__.py` | Carica .env GM all'import (`_env.load_dotenv_once`). v1.1.2 |
| `__version__.py` | Re-export version da `__init__.py` (SSOT) |
| `gme.py` (421 righe) | **Gray Matter Environment** — tool registry centralizzato. Ogni tool scrive un JSON qui dopo install. La GUI legge questi per trovare il Python corretto. Funzioni: `gme_root()` (platform-specific), `read_tool`/`write_tool`/`list_tools`, `update_health`, `mark_missing`, `remove_tool`, `get_python`/`get_venv`/`is_installed`/`get_version`, `detect_old_installs()` (migrazione), `migrate_tool`/`migrate_all`. Location: `%LOCALAPPDATA%\GrayMatterEnvironment\` (Win), `~/Library/Application Support/GrayMatterEnvironment/` (Mac), `~/.local/share/GrayMatterEnvironment/` (Linux) |

### Sorgente Python (analisi moduli)
| Modulo | Funzione |
|--------|----------|
| `server.py` (1140 righe) | **Core del gateway**. MCP server stdio + daemon IPC. 3 tools propri: `gray_matter_pulse(topic, top_n?)` (fan-out parallelo Neuron+NeuRAG, join, bridges, flash, cache), `gray_matter_status()`, `gray_matter_bridge(neuron_concept, neurag_node, rationale?)`. Pass-through: ripubblica TUTTI i tool di Neuron/NeuRAG con schemi reali (F12). Worker persistenti (`_worker.py`), IPC TCP (:9876), 5 background tasks (IPC listener, heartbeat monitor, sleep monitor, reaper, prewarm). Daemon singleton con porta dinamica (SO_EXCLUSIVEADDRUSE). Stimulus safety-net (rilancia forgotten se piggyback tace). Cross-store bridges Hebbian (auto-promote a 5+ usi). Flash serendipitous su topic shift. Conversation buffer (D4) per multi-turn RAG. Cache TTL + LRU con invalidazione mirata |
| `cli.py` (942 righe) | CLI entry point: 24+ comandi. SSOT per host/porta IPC (server.py importa da qui). Comandi: lifecycle (install/uninstall/repair/start/stop/gui/register/deregister/link/record-env), inspect (status/stats/doctor/bridges/logs/ping/gm-neuron/gm-neurag), tuning (config/cloud/mode/isolate/collaborate), maintenance (bridges-transfer/knowledge). `cmd_link()`: ri-aggancia al gateway tool andati standalone. `cmd_cloud()`: setup/wire/status/teardown per Turso cloud. `_ensure_daemon()`: avvio automatico daemon da GUI |
| `bridges.py` (561 righe) | Cross-store bridges: la "memoria propria" di GM che impara dall'uso. Tabella `bridges` (neuron_key, neurag_key, neuron, neurag, rationale, weight, created, last_used, promoted). 3-tier storage identico a Neuron/NeuRAG: Turso cloud → local pyturso → sqlite3. API: `add_bridge()` (idempotent, weight+1), `bridges_for()` (substring match bidirezionale, reinforce on surface), `decay()` (idle bridges lose weight, prune below 1.0), `all_bridges()`, `transfer()` (local↔cloud, additivo mai distruttivo). Hebbian: weight cresce ad ogni co-occorrenza, _PROMOTE_AT=5 triggera confirm su Neuron |
| `cache.py` (77 righe) | Context cache: TTL + LRU + invalidazione mirata. Dynamic TTL (topic "hot" → TTL fino a 3x). `get()`/`set()`/`invalidate()`/`invalidate_related(term)` (drop entries il cui topic si sovrappone). Ordine: OrderedDict per LRU |
| `registry.py` (114 righe) | Server registry: `ServerEntry` dataclass (name, tool_names, socket_path, pid, status, collaborative, tool_schemas, managed). `Registry` singleton: register/unregister, find_server_by_tool, alive_servers, collaborators, set_collaborative, heartbeat, mark_dead. Supporta sia server IPC che managed workers (gateway model) |
| `executor.py` (543 righe) | Effectful install/uninstall/repair. `detect_state()`: stato live machine (installed, clients, orphans). `execute_install()`: reap → ensure_data → install_gm → register (gateway) → deploy_hook → write_manifest. `execute_uninstall()`: kill orphans → deregister → remove hooks → remove code → ask/remove data. `execute_repair()`: rimuove SOLO le superfici scelte dall'utente. Deploy hooks: Claude Code (SessionStart), Cowork (plugin), OpenCode (.mjs). `_find_clients_root()`: localizza assets handshake dentro il pacchetto neuron installato |
| `clients.py` | Registrazione MCP client: matrix completa, non-distruttiva (backup, verify-after-write, rollback). `release_tool()`/`standalone_register_tool()`/`unmanaged_tools()`/`set_unmanaged()`: logica go-standalone/return-to-gateway |
| `settings.py` | Knobs JSON: flash_min_gap, cache_ttl_seconds, cache_max_size, prewarm, heartbeat_interval, idle_sleep_timeout, stimulus_safety_net, stimulus_safety_gap. `load()`/`get()`/`set()` |
| `bridge.py` | HTTP bridge launcher per full suite: resolve cmd, mcp-proxy, tunnel, default port 8002 |
| `cloud.py` | Turso cloud: setup (auto-provisioning), wire (bring-your-own), status, teardown. Legge/scrive .env GM. `install_cli()`: installer turso CLI. `CLI_GUIDE`: guida manuale per OS |
| `installer.py` | Install plan puro (no side effects): steps list per gateway model |
| `uninstaller.py` | Uninstall plan puro: deregister, remove hooks, remove code, ask/remove data |
| `webgui.py` / `webgui.html` | Web control center: pannelli adattivi (mostra/nasconde per componenti installati), dashboard, sidebar completa (Memory+Knowledge), card Setup/Preferences/Turso/Cloud/Processi/Repair |
| `gui.py` | Legacy Tkinter → ritirata, rimanda a webgui |
| `shortcut.py` | Desktop shortcut cross-OS centralizzato: .lnk (WScript.Shell COM), .desktop, .command. Marker file idempotente |
| `_env.py` | .env loader: daemon carica `<GM_HOME>/.env` all'import, workers ereditano. No-op pytest, opt-out `GM_NO_DOTENV` |
| `_worker.py` | Worker subprocess persistente: importa server module una volta, modello rimane caldo. JSON pipe (stdin→stdout), `CREATE_NO_WINDOW` su Windows |

---

## 2. Documenti ROOT dedicati a Gray Matter

| File | Contenuto |
|------|-----------|
| `GrayMatterAudit.md` | Audit specifico Gray Matter |
| `AUDIT-INSTALL-FLOW.md` | Audit flow installazione (GM executor) |
| `AUDIT-PERFORMANCE.md` | Audit performance (GM pulse, cache, workers) |
| `DESIGN-CLOUD-MEMORY-2026-07-21.md` | Design memoria cloud: Turso dual-DB, wire senza CLI, retry/reconnect/transactions |
| `DESIGN-FLASH-COGNITION-2026-07-22.md` | Design flash cognition: serendipitous recall su topic shift |
| `DESIGN-GUI-UNIVERSALE-2026-07-22.md` | Design GUI universale: 4 fasi (registry/discovery, health stream, migration UI+i18n, desktop shortcuts) |
| `DOCS-GUIDELINES.md` | Linee guida documentazione |
| `ENVIRONMENT.md` | Ambiente di sviluppo e regole |
| `FIX-TASKLIST.md` | Tasklist fix (include GM) |
| `GRAY-MATTER-COMPENDIUM.md` | Compendio completo (SSOT tra sessioni AI) |
| `HANDOFF-CODE-GUI-2026-07-22.md` | Handoff codice GUI |
| `HANDOFF-STANDALONE-2026-07-22.md` | Handoff modalità standalone |
| `INSTALLER-UX.md` | Spec completa installer/uninstaller (SSOT) |
| `PLAN-RAG-OPTIMIZATION-2026-07-22.md` | Piano ottimizzazione RAG |
| `PROBLEM-REGISTER-2026-07-21.md` | Problema registrazione |
| `RELEASE-CHECKLIST.md` | Release checklist |
| `work/audit/GRAY-MATTER-TASKS.md` | Task audit/manutenzione GM |
| `work/audit/PIANO-AZIONE.md` | Piano d'azione condiviso |
| `work/design/` | 5 file: ADR-009 GME Registry, Implementation Plan, Mock Implementations, Risk Analysis, Summary Checklist |

---

## 3. Documenti `docs/` (condivisi, rilevanza per GM)

| File | Rilevanza per GM |
|------|------------------|
| `docs/OVERVIEW.md` | Gray Matter = gateway/proxy, quickstart, diagram |
| `docs/ARCHITECTURE.md` | **Architettura completa**: diagramma ASCII 3 componenti, gateway pattern (re-pubblca tools), pulse data flow (9 step), design decisions (Hebbian bridges, dynamic cache TTL, context hysteresis, plan/executor split), Neuron ranking 4-signal, NeuRAG 3-tier search, IPC protocol TCP, 5 background asyncio tasks |
| `docs/DATA.md` | Schema GM: config.json, bridges.json/db, manifest.json. Bridge schema completo |
| `docs/CONFIGURATION.md` | 10 GM env vars (GM_HOME, GM_PREWARM, GM_NEURON_CLIENTS, GM_GUI_NOBROWSER, GM_TURSO_*, GRAY_MATTER_BRIDGES, GM_ENV_FILE, GM_NO_DOTENV), 8 GM config knobs (flash_min_gap, stimulus_safety_net/gap, cache_ttl_seconds, cache_max_size, prewarm, heartbeat_interval, idle_sleep_timeout) |
| `docs/TOOLS.md` | 3 GM tools documentati: pulse (topic, top_n), status, bridge (neuron_concept, neurag_node, rationale) |
| `docs/CLI.md` | CLI reference GM (entry: `gray-matter`): 24+ comandi |
| `docs/TROUBLESHOOTING.md` | GM troubleshooting: daemon not running, no servers visible, pulse "No servers available", worker dies, double GM daemon, cache stale |
| `docs/TECHNOLOGY.md` | Decisioni tech GM: gateway pattern (single MCP server re-publishing), daemon singleton (SO_EXCLUSIVEADDRUSE), Hebbian bridges |
| `docs/EVOLUTION.md` | Evoluzione Era 1-5: GM orchestrator built → gateway flip → trust+refs → knowledge features → documentation |
| `docs/DEV-DIARY.md` | v5.6.0: gateway flip, worker subprocessi, daemon singleton, tool pass-through (F12) |
| `docs/PROCESS.md` | Processo team: compendium come shared brain, Laguna audit, L2 debugging, schema-anchored design |
| `docs/GETTING-STARTED.md` | Tutorial 10 step: install → doctor → pulse → store → index → query → confirm → health → uninstall |

---

## 4. Architettura Concettuale di Gray Matter

- **Gateway pattern**: Un solo MCP server, i client registrano solo `gray-matter`
- **Fan-out model**: `pulse()` → parallelo Neuron context + NeuRAG knowledge → join → bridges → flash → cache
- **Worker persistenti**: Subprocess long-lived, modello pre-warm, nessun cold import per call
- **IPC TCP**: Porta dinamica (9876 default), length-prefixed JSON, 10 azioni IPC
- **Cross-store bridges**: Link Hebbian tra concetti Neuron e nodi NeuRAG, weight cresce con uso, decay idle
- **Cache**: TTL + LRU, invalidazione mirata post-write, dynamic TTL (hot topics 3x)
- **Flash**: Serendipitous recall di concetti dormienti su topic shift, rate-limited
- **Daemon singleton**: Porta dinamica con rendezvous file, SO_EXCLUSIVEADDRUSE
- **Gateway vs Standalone**: Modo gateway (raccomandato) vs tool individuali standalone, reversibile
- **Stimulus safety-net**: Se Neuron non produce stimoli da N turni, GM lo rilancia
- **3-tier storage coerente**: Turso cloud → local pyturso → sqlite3 (stessa gerarchia per tutti e 3 i componenti)
