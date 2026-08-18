# RIEPILOGO DOCUMENTAZIONE — NEURON

> Server MCP di memoria semantica persistente per LLM.
> Versione: 6.1.2 | Autore: Claudio Costantino | License: PolyForm Noncommercial 1.0.0

---

## 1. Documenti nella cartella `neuron/`

### Root
| File | Contenuto |
|------|-----------|
| `README.md` | Landing page completa: cosa è Neuron (memoria semantica persistente con grafo concettuale vivente), highlights (8 features), diagramma di funzionamento (2-step loop: `pre_turn` → `store_turn`), quickstart, configurazione in 13 MCP clients, storage tiers (Turso cloud → local pyturso → sqlite3), graph visualizer, 22 MCP tools, setup sviluppo |
| `CHANGELOG.md` | Storia versioni v5.4.2→v6.1.2. Milestone: v6.0.0 (prima release gateway-era), v6.1.0 (go-standalone, GUI universale, repair, installer --force), v6.1.1 (fix flash CMD Windows), v6.1.2 (GUI Tkinter ritirata, repair --json, register guard) |
| `LICENSE` | PolyForm Noncommercial License 1.0.0 |
| `pyproject.toml` | Config pacchetto: setuptools src-layout, v6.1.2. Dipendenze: mcp≥1.28, pyturso==0.6.1 (pinnato), fastembed≥0.5.0. Entry points: `neuron-mcp`, `neuron`. Package-data: seed DB, skills, client configs, vendor GM wheels |
| `AGENTS.md` / `CLAUDE.md` | Memoria di progetto per AI: struttura, workflow rules (import TASKLIST.md), graphify rules |
| `INSTALL.md` | Installazione completa (346 righe): 3 metodi (automated, wheel, source), vendor wheels Windows, register CLI, troubleshooting, uninstall |
| `INSTALL-AI.md` / `INSTALL-AI.it.md` | Istruzioni per AI agent: 2 percorsi (via Gray Matter gateway, standalone) |
| `TASKLIST.md` | Ledger persistente task (700+ righe): T1–T84, la maggior parte completati. Copre code-quality, GUI evolution, installer unification, bridge/watchdog, Turso cloud reconnect |
| `constraints.txt` | Dipendenze pin: mcp≥1.28,<2 e fastembed≥0.8,<1 |

### `docs/`
| File | Contenuto |
|------|-----------|
| `DEVELOPER.md` (821 righe) | Guida dev completa: architettura ASCII, struttura progetto, dipendenze, vector embeddings 384-dim, fallback chain, Turso cloud setup, key behaviors (context inheritance, extraction, auto-link, salience/decay), MCP client config per 13 client, CLI interattivo (6 provider), sviluppo, memoria dinamica v5 (Hebbian, spreading activation, flash, drift, sleep), consolidamento |
| `BRIDGE.md` | Guida Bridge per ChatGPT via HTTP: bridge.py, mcp-proxy, Cloudflare tunnel, troubleshooting |
| `TEAM.md` | Memoria condivisa su Turso Cloud: DB shared, token, strategie contesto, scritture concorrenti, sicurezza |
| `RELEASE_PLAN.md` | Proposta tecnica v3.3.0: bug installer + packaging (src-layout, seed in wheel, release.yml) |
| `RELEASING.md` | Flow release (trunk-based): commit+tag → release.yml → wheels + GitHub Release |
| `CORE_AUDIT.md` | Audit 2026-07-15: 235 test passed, compileall OK, no broken deps |
| `ENHANCEMENTS-2026-07.md` | Piano 05 enhancement: performance (98% fewer link writes, cache intra-call, pre-warm), installer centralization, memory quality (curation gate, episodes), modularizzazione server.py 2550→2149 linee |
| `design/` (10 ADRs + BACKLOG) | ADR-00: roadmap "bomba" (3 livelli substrate/embedding→engine/search→stimuli/output). ADR-01/02: embedding model + vector consolidation. ADR-03/04: stimulus engine + drift. ADR-05: efficienza. ADR-06: modularizzazione. ADR-07: installer universale. **ADR-08**: architettura 4 livelli memoria (Session Cache → Active Graph → Graveyard → Forgotten). BACKLOG: 5 Epic, ~77 story points |

### `handoff/`
| File | Contenuto |
|------|-----------|
| `HANDOFF-code.md` | Handoff PC: docs reorg, bridge launcher, install.ps1, pip→uv fallback, test matrix |
| `HANDOFF-test-env-setup.md` | Protocollo test store isolato: NEURON_NO_DOTENV + NS_GRAPHS_DIR |
| `HISTORY.md` | Digest tutti gli handoff: evoluzione da quality passes iniziali a release 5.3.0 |
| `FutureIdeas.md` | 8 proposte ispirate al cervello (14gg totali): Hebbian, drift, consolidamento offline, sleep, salience ranking, extract --curated, sentiment decay, role-based tagging |
| `TEST-PROTOCOL-opencode.md` | Protocollo test intensivo OpenCode: 7 suite (virgin store, curation, episodes, context, stimuli, telemetry, stress) |

### `knowledge/`
| File | Contenuto |
|------|-----------|
| `base_knowledge.db` | Seed knowledge database con concetti pre-caricati dai vault Obsidian |
| `self-vault/` (26 .md) | Doc individuale per ogni MCP tool: auto, confirm, consolidate, dedup, export, extract, find_candidates, flash, forgotten, get_context, help, list_contexts, merge, pre_turn, prune, reset, skill, status, store_turn, summary, switch_context, vector_search, ecc. |

### `skills/`
| File | Contenuto |
|------|-----------|
| `playbook.md` (301 righe) | Workflow completo: flow PRE→RESPOND→POST, pre_turn shortcut, concept extraction, duplicate screening, store_turn, confirm, semantic flashes, token budget, smart activation, context switching, 22 tools, compatibilità provider |
| `neuron-opener.md` | Session opener compatto: per-turn loop, curation rules, anti-misuse rules |
| `neuron-curated-memory/SKILL.md` | Curation graph: keyword rules (noun/entities/tech only), link rules (typed, no self-link), esempi italiano |

### `clients/` (8 file)
Config JSON esempio per: Claude Desktop, Claude Code, Cursor, OpenCode, VS Code Copilot, Zed, Cline/Roocode, generic MCP. Tutti usano chiave `neuron5`.

### `scripts/` (25 file)
Script chiave: `run_interactive.py` (6 provider), `bridge.py` (stdio→HTTP), `connect_turso.py` (cloud setup), `generate_graph_html.py` (visualizzatore), `import_vault.py` (Obsidian→seed), `reembed.py` (re-embed dopo cambio modello), `bench_embed.py`/`bench_turn.py` (benchmarks), `deploy.ps1` (sync source→install)

### `src/neuron/` (30 entry)
Moduli core: `server.py` (MCP server, ~22 tools), `engine.py` (CLI engine standalone), `models.py` (Node, Link, Graph, episodes), `db.py` (3-tier DB selector), `registry.py` (multi-context con ereditarietà), `extraction.py` (SemanticExtractor + lessici), `curation.py` (quality gate), `search.py` (vector + graph retrieval), `stimulus.py` (spreading activation), `funnel.py` (skill registry), `clients.py` (registrazione cross-platform), `config.py` (SSOT paths/settings), `paths.py`, `project.py`, `bridge.py`, `connect.py`, `console.py`, `tunnel.py`, `shortcut.py`, `_env.py`, `_gm_vendor/` (wheel emergency Gray Matter)

---

## 2. Documenti ROOT che parlano di Neuron

| File | Rilevanza per Neuron |
|------|----------------------|
| `work/audit/NEURON-TASKS.md` | Task di audit/manutenzione specifici per Neuron |
| `work/audit/PIANO-AZIONE.md` | Piano d'azione condiviso (include Neuron) |
| `NeuronAudit.md` | Audit specifico del componente Neuron |
| `ARCHITETTURA.md` | Architettura 3 componenti (Neuron è uno dei 3) |
| `DESIGN-CLOUD-MEMORY-2026-07-21.md` | Design memoria cloud (Neuron + Turso) |
| `DESIGN-FLASH-COGNITION-2026-07-22.md` | Design flash cognition (feature Neuron) |
| `HANDOFF-SQLITE-DEGRADATION.md` | Fallback SQLite per Neuron (3-tier) |
| `GRAPH_EXTRACTION_PLAN.md` | Piano estrazione grafo (Neuron) |
| `GRAY-MATTER-COMPENDIUM.md` | Compendio condiviso (include Neuron) |
| `FIX-TASKLIST.md` | Tasklist fix (include Neuron) |
| `PROBLEM-REGISTER-2026-07-21.md` | Problema registrazione (Neuron) |
| `RELEASE-CHECKLIST.md` | Release checklist (include Neuron) |
| `docs/OVERVIEW.md` | Overview progetto (Neuron = semantic memory) |
| `docs/ARCHITECTURE.md` | Architettura (data flow Neuron nel gateway) |
| `docs/DATA.md` | Schema DB Neuron (6 tabelle: meta, nodes, node_vectors, links, _graveyard, refs, episodes) |
| `docs/CONFIGURATION.md` | 25+ env vars Neuron, 3-tier storage, paths |
| `docs/TOOLS.md` | 22+ MCP tool Neuron documentati |
| `docs/TECHNOLOGY.md` | Decisioni tech (embeddings fastembed, IPC TCP, Hebbian bridges) |
| `docs/EVOLUTION.md` | Evoluzione Era 0-5 (Neuron da standalone a gateway worker) |
| `docs/DEV-DIARY.md` | Diario sviluppo v1.0→v6.0 (Neuron da NeuralStimulus a Neuron) |
| `docs/PROCESS.md` | Processo team (include Neuron dogfooding) |
| `docs/TROUBLESHOOTING.md` | 13 troubleshooting entries (molti su Neuron) |
| `docs/GETTING-STARTED.md` | Tutorial 10 step (usato Neuron) |
| `docs/INSTALL.md` | Installazione (include Neuron) |
| `docs/CLI.md` | CLI reference Neuron (entry: `neuron`) |

---

## 3. Concetti Chiave di Neuron

- **Two-step loop**: `pre_turn(topic, keywords)` prima di rispondere → `store_turn(keywords, links, ...)` dopo
- **Multi-context hierarchy**: `java/spring` → `java` → `default` (ereditarietà automatica)
- **3-tier DB**: Turso cloud → local pyturso (libSQL embedded) → stdlib sqlite3
- **Hebbian reinforcement**: Co-activated links si rafforzano (tangential→medium a 3, medium→strong a 8 co-attivazioni)
- **Spreading activation**: Propagazione lungo link con decay, drive semantic flashes
- **4-level memory** (ADR-08): Session Cache → Active Graph → Graveyard → Forgotten
- **Curation gate**: Scarta filler/verbs, canonicizza link, merge near-duplicates
- **Gateway vs Standalone**: Gray Matter gateway (raccomandato) o registrazione standalone diretta
