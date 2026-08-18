# GRAY MATTER — Compendio Unificato

> Bug, fix, idee, piano evolutivo, audit, stato progetti.
> Unisce e deduplica: `GMFixAndIdeas`, `HANDOFF-07-16/17/18`, `STATO-E-PIANO`, `PIANO-EVOLUZIONE`.
> Aggiornato: 2026-07-22 rev.3 (GUI universale) — pannelli via CLI (decoupling), bootstrap GM in `<tool> gui`, Tkinter ritirata, --force ovunque.

---

## 0f. Standalone totale — 2026-07-22 (GM 1.1.0 · NeuRAG 1.2.0 · Neuron 6.1.0)

Neuron e NeuRAG sono ora TOTALMENTE standalone (decisioni utente, handoff `HANDOFF-STANDALONE-2026-07-22.md`):

- **`neurag/clients.py`** (NUOVO, keep-in-sync con `neuron/clients.py`): matrice client
  (claude-desktop, claude-code, cursor, vscode, opencode), register/deregister non
  distruttivi, entry `python -m neurag.server`. CLI: `neurag register|deregister`.
- **Deregister per-tool**: `gray-matter deregister --tool neuron|neurag|all` e
  `neuron|neurag go-standalone` — il tool si registra come MCP diretto e GM smette di
  gestirlo (knob `unmanaged` in settings; `detect_subservers` e l'autoregister dei
  server lo rispettano → mai tool doppi). Caso misto: entry `gray-matter` resta nei
  client finché un peer è gestito; rimossa solo quando nessuno lo è. Round-trip:
  `gray-matter register --gateway` azzera `unmanaged` ed evict le entry dirette.
- **GUI universale (rev.3, 2026-07-22)**: `neuron gui` e `neurag gui` aprono il control
  center condiviso (`gray_matter.webgui`). Se GM manca, ogni tool lo **bootstrappa** da
  solo nello stesso venv (cartella sorella in dev, poi indice pip — extra `[gui]`),
  streamando il progresso, poi apre. **GUI Tkinter di Neuron ritirata** (`gui.py` +
  entry `neuron-gui` cancellati): la GUI è UNA.
- **Pannelli speciali tutti via CLI (decoupling)**: Config/Repair/Uninstall/Processi non
  importano più gli interni di GM (`settings`/`executor`/`paths`/`clients`). Passano per
  `python -m <tool>.cli <cmd> --json` come ogni altro comando → `grep "from gray_matter"
  webgui.py` = solo `catalog` + `__version__`. Metadati (knob, superfici repair/uninstall)
  sono SSOT nel tool che li possiede, esposti con `--json`. Pannello Processi: solo i
  comandi lanciati dalla GUI (niente più scan `tasklist`/pids del daemon a ogni render →
  via latenza + flash). Il daemon si ferma dalla card `gray-matter → stop`.
- **`--force` in TUTTI gli installer** (prima solo GM): reinstall forzato del proprio
  pacchetto, flag inoltrato al GM installer.
- **Auto-repair dai propri path**: `neuron|neurag repair` stampa/lancia
  (`--reinstall`) il PROPRIO installer via `paths.source_dir()`; la card Ripara delega
  a `<tool> repair <wipe...> --reinstall` (i `wipe` sono i token CLI da `repair --json`).

Verifica (rev.3, editable install nel venv reale `%LOCALAPPDATA%\gray-matter\.venv`):
py_compile OK su tutti i file toccati; `catalog.environments()` 3 ambienti 0 errori
(22/12/17 comandi); `grep "from gray_matter" webgui.py` = solo catalog+__version__;
round-trip HTTP reale su tutti i pannelli (catalog, config_knobs/set bool+vuoto,
repair_state 3 scope, uninstall_state, process_list); `neuron-gui.exe` non più
generato dopo reinstall. Da confermare con l'utente al monitor: click reali sui
pannelli in finestra WebView2, install `-Force` in terminale, bootstrap in venv
senza GM, porta occupata, `neurag doctor` senza pyturso.

## 0e. Audit documentazione + fix — 2026-07-22

Sessione di revisione e allineamento documentazione post-release 6.0.1.

**Fix applicati:**
- **AGENTS.md:** riscritto — versione corretta (6.0.1), path aggiornati (`Gray Matter Enviroment\neuron`), test count corretto (272), rimosso riferimento `Imported Claude Cowork`
- **CLAUDE.md:** versione 6.0.0 → 6.0.1
- **CONFIGURATION.md:** versione 6.0.0 → 6.0.1
- **DATA.md:** `links.link_type` corretto — valori reali (`cause-effect`, `analogy`, `evolution`, `contrast`, `deepening`, `instance-of`), separato da `weight` (`strong`, `medium`, `tangential`)
- **TROUBLESHOOTING.md:** entry L2 riscritta con diagnosi reale (race WAL multi-processo), mitigazione 2026-07-21 (retry + degrade sqlite3), fix reale (restart GM)
- **EVOLUTION.md:** open threads aggiornati (L2 mitigato, multilingual embeddings ✅, version alignment ✅); aggiunta 6.0.1 al changelog

**Neural BACK v2-1 esplorato** — 5 versioni documentate:
| Versione | Cartella | Innovazione |
|---|---|---|
| v2.0 | `neural_stimulus_v2 FULL DEPENDENCIES/` | Python puro, LLM extraction, 6 moduli |
| v2.1 | `neural_stimulus/` | +M7 dedup, +M8 persistenza SQLite, CLI |
| v3.0 | `CheckpointNeuralGraphNavigation/` | MCP server, 12 tool, 256-dim feature hashing, Turso |
| v3.0+ | `Neural-Stimulus-hub-vectorX/` | v3.0 con installer multi-client |
| v4-6 | (attuale `Gray Matter Enviroment/`) | 33 tool, fastembed 384-dim, Gray Matter gateway |

**Stato:** Gray Matter WIP (disattivato per fix). Documentazione pronta per il diario di sviluppo con i backup delle vecchie versioni.

Sessione di allineamento e robustezza (dettaglio in `PROBLEM-REGISTER-2026-07-21.md`).
- **Versioni unificate** a Neuron 6.0.0 / NeuRAG 1.0.0 / GM 1.0.0 (pyproject,
  `__version__`, README, docs, CHANGELOG). Patch 6.0.1 per fix COMMANDS (2026-07-22).
- **Docs:** creato `docs/INSTALL(.it).md` (link OVERVIEW risolti), tool `status` in
  TOOLS, "32→33 tool", marker trust B1–B3 ⬜→✅ qui in §Fase B.
- **Test (sqlite):** 270+30+35 verdi, 0 fail. Fix test `search_with_links`
  (enrich-only) e `importorskip(mcp)` sui 2 test GM.
- **Decoupling NeuRAG:** vendor wheel proprio (`Neurag/vendor/` + `release.yml`),
  non dipende più da `Neuron/vendor`.
- **Flow installer:** ogni crossing point ora degrada a fallback; Neuron/NeuRAG
  bootstrappano GM se assente (locale→GitHub release→PyPI→EXIT). EXIT solo su
  no-Python / no-venv / GM-core-non-installabile.
- **Cloud Turso in NeuRAG (nuovo):** risolta l'asimmetria — `Neurag/db.py` ora ha
  il tier cloud (`RemoteTursoConnection` su libsql-client, extra `[cloud]`), come
  Neuron. Facade adattato (righe name-accessible), guardia L2 anche qui. Test
  `test_cloud_turso.py`. Path cloud reale da verificare in locale.
- **L2:** ◐ mitigato (`_open_local_engine`/`_open_local_turso` + degrade sqlite3);
  race multi-processo → verdetto sul daemon vivo.
- **Resta:** verifica cloud live (Neuron+NeuRAG su Turso condiviso); build wheel;
  bootstrap remoto attivo post-publish; git/tag/push = ultimo step.

## 0c. Wizard GUI — 2026-07-20

Card **Setup** nella webgui (prima card): checkbox Neuron/NeuRAG + Preview /
Install / Test. Backend: `setup_state` (peers+manifest+client rilevati),
`setup_run` (pip dei peer selezionati mancanti via `_peer_steps` riusato da
`eco_install`, poi `gray-matter install`; dry_run = solo anteprima gateway),
`setup_test` (ping+doctor). Smoke sandbox verde. **Completato 2026-07-20 sera**: pannello Preferences nel
wizard (`setup_prefs_get/set` su settings.py, righe dinamiche dai DEFAULTS,
coercion + reject chiavi ignote, nota restart; pannello Turso già esistente).
Resta: prova nel browser in locale + raffinamento comandi Neuron/NeuRAG nella
GUI. **Percorso release: vedi `RELEASE-CHECKLIST.md`** (nuovo SSOT del rilascio).

## 0b. Handoff docs — 2026-07-19 (in corso)

Documentazione internazionale avviata: `INSTALL-AI.md` (EN) + `INSTALL-AI.it.md`
nei 3 repo; README EN nuovi per radice, `gray_matter/`, `neurag/`.
✅ `Neuron/README.md` allineato (callout "Recommended: Gray Matter gateway" in
§Mounting + riga INSTALL-AI nella documentation map). **Opzionali prossima
sessione:** README.it, note dev per-repo più ricche, badge/versioni aggiornati.

## 0. Handoff & TODO — 2026-07-18 rev.2

**Fatto in questa sessione** (verifica: compile sandbox + test isolati; *locale* dove segnato):

- **GM** — A4 `stats`/`doctor` + fix **cache singleton** `_ctx_cache`; **D2** worker pre-warm; **F4** ingest-validation bridge; cache **multi-topic** (rimosso clear su cambio topic) + invalidazione mirata post `store_turn` + validazione `topic` in `pulse`; **F12** schemi reali pass-through (worker `list_tools` → cache `ServerEntry.tool_schemas` → `list_tools` GM).
- **Neuron** — **G3** `project.py` (marker `.neuron/project.json`, path relativi, provenance); marker creato per l'environment (`project_id 550dfdcd-…`). **G1** refs canonicalizzati in `store_turn` + merge su nodi rivisitati + riga `files:` in `pre_turn`.
- **Deploy** — `INSTALLER-UX.md` (SSOT): registrare **solo GM** (gateway, keystone F12); uninstall **interattivo**; hook/plugin = layer per-client (§8b). **Passo 3** `paths.py` + `Manifest` (path per-OS, componenti, client, hook) — 8 test verdi.

**Aggiornamento 2026-07-18 rev.3 (Fable, in locale)** — flip gateway ESEGUITO:

- ✅ **Verifica locale + commit**: `pytest` Neuron 253 verdi, GM 24 verdi; commit `gray_matter` `e304f5e`→`072c634`.
- ✅ **Singleton daemon**: bind esclusivo su :9876 (`SO_EXCLUSIVEADDRUSE` su Windows — `SO_REUSEADDR` lì permetteva 2 bind contemporanei, causa dei daemon duplicati); il daemon perdente muore, un'istanza **stdio** sopravvive senza listener.
- ✅ **`gray-matter register --gateway`**: registra solo GM ed evict `neuron`/`neuron5`/`neurag`; copre anche il config **MSIX** (`Packages\Claude_*\LocalCache\...`) e scrive su TUTTI i config esistenti del client.
- ✅ **Fix handshake stdio**: `InitializationOptions` senza `capabilities` (campo obbligatorio) crashava al primo avvio stdio — mai visto perché girava solo il daemon. Ora `_init_options()` + `instructions` GM (loop pre_turn/store_turn) servite all'handshake.
- ✅ **Installer §8b**: `plan()` emette `deploy_hook` per claude-code/cowork/opencode (asset in `Neuron/clients/`), manifest traccia gli hook (`record_hook`).
- ✅ **Smoke locale GM stdio**: handshake + `tools/list` → 32 tool ripubblicati con schemi reali (pass-through neuron+neurag OK).
- ✅ **FLIP ESEGUITO** (2026-07-18): Claude Desktop (APPDATA + MSIX), Claude Code (`√ Connected`), Cursor, VS Code, OpenCode → solo `gray-matter`. Backup `.bak` accanto a ogni config JSON; rollback: `neuron register` o ripristino `.bak`. **Serve riavvio delle app.**
- 🔎 **Doppi server spiegati**: Claude Desktop (1 pid GUI) instanzia 2 client MCP da 1 entry (chat + host interno); il terzo era il claude.exe CLI di Cowork. Il figlio `neuron → neuron` è il **venv launcher di Python 3.14** (redirector), non codice Neuron: `CREATE_NO_WINDOW` in `bridge.py` sarebbe un no-op. "duplicate keys" del doctor = falso allarme.

**TODO rimanenti** (ordine):

1. ✅ **Conferma post-riavvio** (2026-07-18, in Cowork): sessione vede solo `gray-matter`; `gray_matter_status` → neuron+neurag alive come worker managed; `pre_turn` pass-through raggiunge il grafo reale (26 nodi). Resta da osservare: costo dei 2 GM stdio per-app (worker duplicati → thin-shim stdio→daemon solo se la RAM dà fastidio).
2. ◐ **Parte effectful dell'installer/uninstaller** (2026-07-18, Fable): `gray_matter/executor.py` — dispatch sottile su `installer.plan()`/`uninstaller.plan()`: `reap` (taskkill/SIGTERM + pids.json), `ensure_data`, `install` (dirs GM), `register` (`clients.register(gateway=True, only=…)`, "skipped" ≠ fail), `deploy_hook` per-client (claude-code: copia in `~/.claude/hooks/` + entry SessionStart idempotente in `settings.json`; cowork: copytree `neuron-guard` → `~/.claude/plugins/`; opencode: `.mjs` → `plugins/` + array `plugin` in `opencode.json`), `write_manifest` (hooks tracciati). Uninstall simmetrico: `deregister()` nuovo in `clients.py` (backup `.bak`, mai clobber JSONC), `remove_hook` + scrub `settings.json`/`opencode.json` (solo entry nostre), `remove_code`, `ask_data` interattivo / `purge_data`. CLI: `gray-matter install|uninstall [--dry-run|--purge-data|--yes]`. `detect_state()` legge macchina reale. Test: `tests/test_executor.py` (7 casi) + smoke sandbox completo verde. **Verificato in locale 2026-07-19** (31+253 pytest verdi, install reale OK, idempotente). Fix post-test: EOFError su `uninstall --dry-run` (ask_data ora salta il prompt in dry-run) e `_print_results` espande i sub-result del register (il `[!!] register` era muto). Le 4 entry SessionStart in `settings.json` = residuo installer Neuron legacy (path neuron5), non nostre: lo scrub dell'uninstall le rimuove tutte; cleanup opzionale via legacy scan.
3. ◐ **TODO 3 cablato (2026-07-19, Fable)** — L1: già coperto da T11 Fase 2b, esteso a trust. **B1–B3**: `Node.trust: float` (colonna `trust REAL DEFAULT 0` + migrazione ALTER), delta-relativo atomico `MAX(0, trust + ?)` con `_trust_baseline` (stesso pattern salience), `confirm(confidence 0–1, clamp, default 1.0)` → `trust += confidence`, ranking `RANK_WEIGHTS + trust: 0.1` normalizzato; trust propagato in merge/dedup (max). **G2**: tabella `refs (context, keyword, path, project_id, by)` PK naturale + `INSERT OR IGNORE` → append di due writer = righe diverse, zero clobber; il path atomico NON tocca più il blob `nodes.refs` (legacy read-only); load = union blob+tabella (dedup, cap 20); delete refs con i nodi rimossi. Test: `test_trust.py` (6) + `test_refs_table.py` (5); smoke sandbox verdi (roundtrip, 2-writer, clamp, legacy). **Resta: suite completa in locale** (253+11) + commit. Nota: `engine.py` legacy non persiste trust (path v4, non usato dal server v5).

---

## 1. Bug e Fix noti

### Fix completati

| # | Bug | Repo | Fix | Stato |
|---|---|---|---|---|
| F0 | `_call_server_async` re-importa server a freddo a ogni call | GM | Worker persistenti (`_worker.py`) | ✅ fatto |
| F1 | IPC length-prefixed letto male (`data[4:]` assume un solo `recv`) | GM | `server.py` `_ipc_listener` — leggere 4 byte di lunghezza poi `readexactly` | ✅ fatto |
| F2 | `_restart_dead_servers` uccide ma non riavvia (`os.kill` only) | GM | Togliere `os.kill`; heartbeat gestisce liveness; worker si respawna in `_worker_for` | ✅ fatto |
| F3 | Reset Glama senza `confirm` (score C, rischio alto) | Neuron | Aggiunto `confirm=true` obbligatorio | ✅ fatto (v5.4.2) |
| F4 | DRY-run mancante su `prune` | Neuron | `dry_run` sul tool + `Graph.expired_tangential()` read-only condiviso | ✅ fatto (2026-07-20) |
| F5 | `dedup` toggle senza stato in output | Neuron | Aggiunto `enable` opzionale idempotente | ✅ fatto (v5.4.2) |
| F6 | `gray_matter_store` rimosso (in additivo lo store va diretto a Neuron) | GM | Rimosso, store diretto a `store_turn` | ✅ fatto |
| F7 | NeuRAG: chunker codice a blocchi fissi (50 righe) | NeuRAG | AST chunking (funzione/classe) + tag simboli | ✅ fatto |
| F8 | NeuRAG: DB ChromaDB deprecato | NeuRAG | Migrazione a Turso/SQLite completa | ✅ fatto |
| F9 | NeuRAG: embedding mancante | NeuRAG | `embedder.py` — Null (lessicale default) / FastEmbed auto | ✅ fatto |
| F10 | Neuron: bashismi POSIX in installer | Neuron | Fix `&>`/`disown` → `nohup … 2>&1 &`; shortcut macOS | ✅ fatto (v5.4.2) |
| F11 | `gray-matter` "Failed to start" (daemon mode mancante) | GM | Daemon mode `--daemon` fixato | ✅ fatto |
| F19 | `ContextCache` ricreata dentro ogni `pulse` → cache non fa **mai** hit ("cache che non cacha") | GM | Istanza unica condivisa `_ctx_cache` in `server.py` | ✅ fatto (2026-07-18) |
| F20 | `ContextCache.set` svuota **tutta** la cache a ogni cambio topic → non accumula mai su topic alternati | GM | Rimosso `clear()` su cambio topic; restano TTL + LRU | ✅ fatto (2026-07-18) |
| F21 | Cache stale dopo `store_turn` (contesto vecchio servito da cache) | GM | `invalidate_related(topic)` mirata sul pass-through di `store_turn` | ✅ fatto (2026-07-18) |
| F22 | Nessuna validazione ingest sui bridge (endpoint vuoti/1-char/blob, self-bridge) | GM | `add_bridge`: `_clean` + `_valid_endpoint`, reject junk/self (unico write-path) | ✅ fatto (2026-07-18) |
| F23 | `pulse` senza validazione del topic | GM | coerce/strip/collapse/cap; reject vuoto; clamp `top_n` a [1,10] | ✅ fatto (2026-07-18) |

### Fix aperti

| # | Bug | File | Impatto | Fix proposto | Priorità |
|---|---|---|---|---|---|
| F12 | **Pass-through tools con `inputSchema` vuoto** | `registry.py` + `server.py` + `_worker.py` | 🔴 alto | ✅ **cablato (2026-07-18)**: worker op `list_tools` → `_fetch_tool_schemas`/`_ensure_schemas` → cache in `ServerEntry.tool_schemas` → `list_tools` di GM ripubblica schemi reali (fallback vuoto se worker freddo). Da verificare in locale coi server accesi. | alta |
| F13 | **Self-linking in `auto` tool** | `Neuron/src/neuron/server.py:1513` | 🔴 medio | Gestito a livello modello: `Graph.add_link()` blocca `source == target`. `_tool_auto` non ha guardia esplicita ma non serve | risolto (model-level) |
| F14 | **Worker persistence gap** — GM ricomincia da freddo se non daemon | `gray_matter/server.py` | 🟡 medio | Risolto: `_worker_for` fa respawn lazy, il worker resta caldo dopo primo caricamento | risolto (lazy respawn) |
| F15 | **`_first_conchet` parsing fragile** — dipende dal formato output di Neuron | `server.py:406-414` | 🟡 basso | Ponytail: fixa quando si rompe, non prima | bassa |
| F16 | **Flash cooldown session-bound** — `_flashed: set()` non persiste tra sessioni | `Neuron/src/neuron/server.py:144` | 🟡 basso | Persistere in DB | bassa |
| F17 | **Nessuna validazione model embedding** — typo in `NS_EMBED_MODEL` → crash silenzioso | `Neuron/src/neuron/server.py:162-164` | 🟡 medio | Check lazy a primo uso (non all'avvio) — errore表面 al primo embedding | lazy check (fatto a runtime) |
| F18 | **Instructions solo all'handshake** — client che non mostrano istruzioni non vedono il loop guidance | `server.py:376-398` | 🟡 basso | Riproporre in risposte successive | bassa |

### Lacune architetturali

| # | Lacuna | Note | Priorità |
|---|---|---|---|
| L1 | Concorrenza Fase 2 Neuron — `UPDATE ... SET salience = salience + ?` atomici | Oggi read-modify-write in memoria (`survivor.salience += …`). Serve per scrittura condivisa live. **Nota 2026-07-21:** il path *trust* usa già delta atomico `MAX(0, trust + ?)` (B2, `test_trust.py`); resta da portare/verificare l'atomicità anche sul path *salience* | media (prereq per trust) |
| L2 | Neuron `store_turn → open: NotFound` | `pre_turn` funziona, `store_turn` no. **Test locale 2026-07-19**: Neuron diretto (store isolato) FUNZIONA → il bug è nel path GM worker (sospetti: `reg._graphs.clear()` pre-call in `_worker.py`, env/cwd del daemon senza .env/token Turso). Repro esteso 2026-07-19 (one-shot worker, 5 scenari + stress 10x): NON riproducibile; nel daemon vivo funziona dopo restart app → **intermittente, legato allo stato del daemon pre-riavvio**. Strumentato: `_worker.py` ritorna `trace` e GM lo surfaccia. **2026-07-19 sera: riprodotto 2 volte nel daemon vivo — pattern: fallisce il turno che fa scattare lo SWITCH di context (domain signal 2/2), il turno dopo la switch riesce.** La trappola worker non scatta: la lib MCP riduce l'eccezione a `str(e)` dentro Neuron → aggiunto try/except con traceback in `call_tool` (server.py, ultimo punto col trace vivo). Prossimo avvistamento = traceback completo nel messaggio. **3ª riproduzione (19/7 sera, senza trace → worker con codice pre-patch: serve respawn).** Ipotesi principale: più processi GM (Desktop chat+host, Cowork) = più worker pyturso sullo STESSO graph_*.db, e il worker fa `_graphs.clear()`+reload a ogni call → race su file WAL/sidecar tra open e checkpoint concorrenti. Spiega l'intermittenza e i repro one-shot sempre verdi. **Mitigazione 2026-07-21:** `db._open_local_engine` — retry limitato (3×) sull'open pyturso locale + degradazione a `sqlite3` sullo STESSO file se persiste (formato compatibile), così un `store_turn` degrada invece di crashare. Repro sandbox conferma che il sotto-caso "dir nuova mancante" è già coperto da `_ensure_parent_dir`; il residuo (race multi-processo WAL/sidecar) resta da verificare sul daemon vivo con pyturso reale. Test: `test_l2_open_guard.py` (2). ◐ mitigato, verdetto finale in locale | alta (repro trovato) |
| L3 | `install.ps1` manca bundle GM | ✅ risolto (2026-07-20): installer unificati — canonico in `gray_matter/install.{sh,ps1}` (usa `cli install` gateway, shortcut GUI su desktop, `GM_PEER_DIR` per download standalone), thin launcher identici in Neuron/, neurag/ e radice (2 file per progetto). Delega testata con stub; **verifica locale Windows pendente**. Pulizia vecchi entry point Neuron (2026-07-20): `install-gui.sh` eliminato, `uninstall.sh` → thin su `gray-matter uninstall`, README/INSTALL.md aggiornati (via NeuronInstaller.exe→install.ps1, Control Center→Gray Matter GUI, uninstall unificato; `scripts/uninstall.ps1` resta come deep-clean legacy). `NeuronInstaller.exe` invoca `install.ps1` → ora delega al canonico: catena OK, da riverificare al prossimo build | ✅ |
| L4 | Vecchio `install.sh` al root del workspace | ✅ sostituito dal thin launcher full-suite (2026-07-20) | ✅ |
| L5 | Conftest unify (P1#5) | `_FakeEmbed/_FakeSrv/_FakeConn` ridefiniti in 7 file | bassa |

---

## 2. Velocità del flusso

### Latenze attuali

| Fase | Latenza | Bottleneck |
|---|---|---|
| Prima `pulse` (cold worker) | 2-5s | Import fastembed nel worker |
| `pulse` (cache miss, warm) | 1-3s | Neuron get_context + NeuRAG query in parallelo |
| `pulse` (cache hit) | <100ms | Solo lookup in-memory |
| `store_turn` | 0.5-1s | Scrittura DB + embedding |
| Flash check | 0.5-1s | `forgotten` + `vector_search` |

### Ottimizzazioni proposte

1. ✅ **Pre-warming parallelo** — `_prewarm_workers` in `main()`: attende la registrazione, poi spawn worker + read cheap (neuron `status`, neurag warmup) per caricare fastembed **prima** del primo pulse. `GM_PREWARM=0` per disattivare. (D2 fatto 2026-07-18)
2. ✅ **Cache invalidation intelligente** — invalidazione mirata post `store_turn` (`invalidate_related`) + TTL dinamico (2026-07-20: +50% per hit, cap 3x, heat conservato al refresh)
3. ⬜ **Store + pre-load async** — background parte DURANTE la scrittura (overlap I/O) non dopo

---

## 3. Qualità RAG

### Funziona
- Trigger-based navigation (matchare "Spring Boot" → navigare l'albero `Java/Spring_Boot/` direttamente)
- AST chunking (codice chunkato per funzione/classe, tag mergiati nei trigger)
- TF-IDF fallback (senza fastembed)
- Multi-formato: .md, .py, .kt, .java, .pdf, .docx, .yaml
- Reranker cross-encoder opzionale (OFF di default, opt-in per install)

### Manca
- **Feedback loop** — il sistema non sa quali query funzionano (serve `confirm` → salienza su Neuron)
- **Query expansion** — oggi cerca la query esatta; ampliare con trigger del nodo per recall migliore

### Efficienza vettoriale (fix 2026-07-20, osservazione di Claudio)
NeuRAG usava il tier Turso SOLO per URL cloud: i file locali giravano su sqlite3
stdlib e `search()` faceva full-scan `SELECT *` + coseno in Python puro (O(N)
per query, blob tutti in RAM). Fix speculare a Neuron: (1) `_connect` usa
l'engine pyturso anche sui file locali (libSQL legge il formato SQLite);
(2) `search()` fast-path in SQL — `1.0 - vector_distance_cos(f32blob(...),
f32blob(?)) ORDER BY sim DESC LIMIT n`, stesso pattern di `search.py` Neuron —
con fallback trasparente Python/lessicale. `status().engine` ora dice la
verità. Test `test_vector_sql.py` (3, incl. confronto SQL vs Python skippato
senza pyturso). **Verifica locale con pyturso attivo pendente.** Prossimi passi
possibili (non fatti, YAGNI finché il vault è piccolo): indice vettoriale
nativo (`libsql_vector_idx`) e scoping della search al sottoalbero del trigger.

### Reranker cross-encoder (opt-in, OFF di default) — 2026-07-22
`search()` è a due stadi: `_retrieve()` recupera un pool ampio di candidati
(`rerank_pool`, default 50) con il path esistente (vector SQL / coseno Python /
lessicale), poi — **solo se il reranker è attivo** — un cross-encoder
(`fastembed.TextCrossEncoder`, `neurag/reranker.py`) li riordina e tiene i veri
top-n. Pattern RAG standard "retrieve wide, rerank narrow": più precisione al
costo di latenza + download modello, perciò **spento di default** (con reranker
OFF `search()` è un no-op wrapper, comportamento invariato). Toggle per **tutte
le install** via `neurag config set rerank on` (`neurag/settings.py`, config.json
separato da `knowledge.db`) — compare da solo nel control center perché
catalog-driven, e funziona anche in NeuRAG standalone. Env `NEURAG_RERANK` ha la
precedenza sul file. Fallback identico a `embedder.py`: se off o modello assente
→ `NullReranker`, costo zero. Nel control center la card `config` è un pannello
Impostazioni (toggle/picker che salvano subito, `webgui.py` `config_knobs`/
`config_set`); i knob si auto-descrivono da `settings.HELP`/`SUGGEST`.

---

## 4. Ruoli dei componenti

| Componente | Cosa è | Salience | Decay | Scopo |
|---|---|---|---|---|
| **NeuRAG** | Knowledge base fattuale | No | No | Vault strutturato: nodi, chunk, trigger. Knowledge permanente. |
| **Neuron** | Memoria episodica/concettuale | Sì | Link tangential sì, nodi no | Grafo semantico: impara dall'uso, legami deboli decadono. |
| **Gray Matter** | Orchestratore/ponte | — | Bridge mai usati sì | Collega NeuRAG a Neuron. Valida bridge. Non tocca la knowledge. |

---

## 5. Piano evolutivo

### Fase A — Correttezza (subito · piccolo sforzo)

| # | Cosa | File | Stato |
|---|---|---|---|
| A1 | IPC length-prefixed letto male | `gray_matter/server.py` | ✅ |
| A2 | `_restart_dead_servers` non deve uccidere i server del client | `gray_matter/server.py` | ✅ |
| A3 | Passthrough `inputSchema` vuoto | `registry.py` + `server.py` + `_worker.py` | ✅ cablato (2026-07-18), verifica locale |
| A4 | `gray-matter doctor` / `stats` (+ fix cache singleton `_ctx_cache`) | `gray_matter/cli.py` + `server.py` | ✅ CLI (non MCP tool) |

### Fase B — Il ciclo di feedback (il cuore · medio)

| # | Cosa | Repo | Stato |
|---|---|---|---|
| B1 | `confirm(keywords, confidence=1.0)` — parametro graduato (0–1) | Neuron | ✅ (2026-07-19, vedi TODO-3): `confirm(confidence 0–1, clamp, default 1.0)` → `trust += confidence`. Test: `test_trust.py` |
| B2 | `Node.trust: float` in models.py | Neuron | ✅ (2026-07-19): colonna `trust REAL DEFAULT 0` + migrazione ALTER, delta atomico `MAX(0, trust + ?)`. Test: `test_trust.py` |
| B3 | Trust nel ranking: `score = w1·sim + w2·salience + w3·recency + w4·trust` | Neuron | ✅ (2026-07-19): `RANK_WEIGHTS + trust: 0.1` normalizzato; propagato in merge/dedup (max). Test: `test_trust.py` |
| B4 | Bridge auto-learning (Hebbiano + decay) | GM | ✅ completo (2026-07-19): promozione una-tantum a peso 5 → `confirm(confidence 0.5)` sul concetto Neuron dalla pulse, flag `promoted` persistito |

### Fase C — Igiene nodi / auto-regolazione

| # | Cosa | Repo | Stato |
|---|---|---|---|
| C1 | `refute(keywords)` / `confirm` con confidence negativa → abbassa trust | Neuron | ✅ (2026-07-19): `confirm` accetta confidence [-1,1]; negativa = refute (trust giù con floor 0, niente boost salience). Nessun tool nuovo |
| C2 | `consolidate` trust-aware — droppa nodi salience+trust bassi verso `_graveyard` | Neuron | ✅ (2026-07-19): le guardie di consolidate/`_drop_orphans` contano `salience + trust` — un nodo confermato non viene assorbito né droppato |
| C3 | `neuron_introspect` — ~30 righe, aggrega stats che Neuron già traccia | Neuron | ✅ (2026-07-19): tool `introspect` — strongest/most_trusted, recent_growth, weakest_area, loop_stats. JSON |

### Fase D — Quick win RAG / UX

| # | Cosa | Repo | Stato |
|---|---|---|---|
| D1 | Source attribution (`knowledge_query` restituisce `source` del chunk) | NeuRAG | ✅ |
| D2 | Worker pre-warm (`_prewarm_workers`: spawn + read cheap all'avvio; `GM_PREWARM=0` off) | GM | ✅ (2026-07-18) |
| D3 | Knowledge proattiva (depth=2 traversal, "Potrebbe interessarti:") | GM+NeuRAG | ✅ (2026-07-20, approccio strutturato approvato da Claudio): tool NeuRAG `knowledge_neighbors(query, depth 1-3, limit)` — risolve il nodo (trigger→nome esatto→parole singole), BFS SQL-only su parent/children/links, JSON `{node, neighbors:[{name,path,node_type,relation,distance}]}`. GM pulse: se neurag_hit, chiama neighbors(depth 2), filtra i nomi già in risposta, appende "💡 Potrebbe interessarti: …" (best-effort, mai blocca). Niente parsing di prosa (anti-F15). Test: `neurag/tests/test_neighbors.py` (4) + smoke |
| D4 | Multi-turn nel RAG (conversation buffer ultimi 3-5 topic) | GM | ✅ (2026-07-20): `_topic_buffer` deque(3) in server.py, refresh su re-ask; espande SOLO la query NeuRAG (cap 300 char) — cache key resta il topic puro, Neuron ha già la sua window |
| D5 | Incremental indexing (`neurag watch <dir>` con watchdog/mtime) | NeuRAG | ⬜ |

### Fase E — Osservabilità

| # | Cosa | Repo | Stato |
|---|---|---|---|
| E1 | `gray-matter stats` — cache hit rate, flash, bridge count, latenza media miss, worker | GM | ✅ CLI (2026-07-18) |
| E2 | `gray-matter logs --follow` — streaming log daemon | GM | ⬜ |

### Fase F — NeuRAG: salute e coerenza del vault

| # | Cosa | Stato |
|---|---|---|
| F1 | `knowledge_health` L1 (orfani, gerarchia rotta, chunk vuoti, nomi duplicati) | ✅ |
| F2 | Coerenza semantica L2 (chunk outlier, near-duplicate) | ⬜ |
| F3 | Consistenza L3 (tensioni interne, LLM-assistita) | ⬜ |
| F4 | Validazione all'ingest (`knowledge_add_chunks`/`import` rifiutano dati sporchi) | ◐ nodo ✅; chunk vuoti/junk scartati con report (2026-07-20); restano dedup nomi e chunk-outlier (→F2) |

### Fase G — Memoria path + provenienza (progetto condiviso)

> Design in §6.10. Neuron, in chiusura. G2 dipende da **L1** (UPDATE atomici) per la sicurezza in scrittura condivisa.

| # | Cosa | Repo | Stato |
|---|---|---|---|
| G1 | `refs` canonicalizzati in `store_turn` (path relativi + `project_id` + `by`, idempotente) + merge sui nodi rivisitati + surfacing `files:` in `pre_turn` | Neuron | ✅ cablato + 9 test pure-fn (2026-07-18); integrazione end-to-end da confermare con suite locale |
| G2 | Tabella `refs` strutturata (`path`, `project_id`, `by`) — no blob JSON, no clobber concorrente | Neuron | ⬜ (locale, dipende L1) |
| G3 | `project_id` da marcatore `.neuron/project.json` (UUID una volta, senza Git); path relativi POSIX alla radice | Neuron | ✅ `project.py` + 5 test pytest (2026-07-18); marcatore creato per l'environment |
| G4 | Fallback marcatore assente → path non-shared nel sidecar per-utente (`sidecar_dir`, fuori dal DB condiviso) | Neuron | ◐ helper pronto (`canonical_ref shared=False` + `sidecar_dir`); routing lato store ⬜ (locale) |

### Deploy / Installer / UX (decisioni 2026-07-18) → `INSTALLER-UX.md`

Spec completa in **`INSTALLER-UX.md`** (SSOT del deploy). Decisioni fissate:

- **Registrazione MCP = solo Gray Matter** (gateway/proxy): Neuron e NeuRAG come
  worker SUB di GM, non connettori del client. **Prerequisito: F12** (schemi reali
  pass-through) — senza, il modello "solo GM" è inusabile.
- **GM bundle-ato e idempotente** da ogni installer (uno solo per macchina);
  eseguibile GM per-OS = command center; funziona anche con un solo sotto-tool.
- **Uninstall interattivo sui dati**: chiede sempre prima di toccare la memoria
  (grafo/DB/bridge); `--deep`/legacy scan per slug vecchio `neuron`, nome
  Neural-Stimulus, script/config/processi orfani.
- **Ordine**: 1) spec ✅ · 2) F12 · 3) `paths.py`+manifest · 4) installer · 5)
  uninstaller+scan · 6) config unico + command center.

### Ordine consigliato (aggiornato 2026-07-17)

| Pri | Stato | Cosa | Fase | Sforzo | Repo |
|---|---|---|---|---|---|
| 1 | ◐ | IPC read ✅ + restart-no-kill ✅ + passthrough schema ⬜ | A1–A3 | piccolo | GM |
| 2 | ◐ | NeuRAG health L1 ✅ + validazione all'ingest ⬜ | F1/F4 | piccolo-medio | NeuRAG |
| 3 | ✅ | `confirm(confidence)` + `Node.trust` + trust nel ranking | B1–B3 | medio | Neuron |
| 4 | ✅ | Bridge auto-learning ✅ + promozione→trust ✅ | B4 | piccolo | GM |
| 5 | ✅ | `consolidate` trust-aware + `refute` (confidence negativa) | C1–C2 | medio | Neuron |
| 6 | ✅ | `introspect` | C3 | piccolo | Neuron |
| 7 | ⬜ | NeuRAG coerenza semantica L2 | F2 | medio | NeuRAG |
| 8 | ✅ | Source attribution ✅ + worker pre-warm ✅ | D1–D2 | piccolo | GM/NeuRAG |
| 9 | ✅ | `gray-matter stats` + doctor (CLI) | A4/E1 | piccolo | GM |
| 10 | ⬜ | Knowledge proattiva + multi-turn + incremental | D3–D5 | medio | GM/NeuRAG |
| 11 | ⬜ | NeuRAG consistenza L3 | F3 | medio | NeuRAG |

> **Prereq trasversale:** concorrenza Fase 2 — UPDATE atomici in Neuron. Serve al decadimento/rinforzo di trust. Farlo insieme a B.
>
> **Housekeeping:** Neuron `install.ps1` bundle GM (Windows); cancellare vecchio `install.sh` al root; bug Neuron `store_turn → open: NotFound`; test infra (pytest flash/gating GM, pytest offline vendor); conftest unify P1#5; precision/recall eval; modello embedding E0.4; release.yml 3.14.
>
> **Parcheggiato per scelta:** self/ context, semantic routing, affect layer, framing "coscienza/self-model", E2 logs --follow, VISION.md (a mano, non LLM-polished).

---

## 6. Idee — visione

### 6.1 Auto-learning dall'uso

Il sistema impara quali stimoli funzionano, guidato dall'uso reale. Learning su **Neuron** (salience + trust), non su NeuRAG (permanente).

- `confirm` → boost salience nodi/trigger in Neuron
- Bridge che si ripresenta in `pulse` → peso incrementale (Hebbiano)
- Bridge mai usati → decadono (solo bridge, non nodi NeuRAG)
- Bridge confermati 5+ volte → boost salience/trust su Neuron

### 6.2 Knowledge proattiva (il "terzo occhio")

Dopo ogni `pulse`, GM cerca nodi NeuRAG correlati al topic ma non nel risultato (depth=2). Se trova connessioni → "Potrebbe interessarti:". Serendipità su knowledge reale (diverso dal flash, che è su dormienti di Neuron).

### 6.3 Cross-session memory con feedback

Il LLM chiama `confirm(keywords=["spring_boot", "autoconfiguration"])` quando il contesto è utile → Neuron boosta salienza. GM traccia quali topic producono conferme → prossima volta quei nodi vengono prioritizzati.

### 6.4 Cross-linking e bridge accuracy

- **Cross-linking**: GM scopre concetto Neuron = nodo NeuRAG → persiste il bridge (v3b auto-discovery)
- **Accuracy check**: bridge usato + confermato → accurato; bridge non confermato → rimosso
- **Bridge decay**: solo bridge mai usati in `pulse` reale decadono
- **Promozione bridge → Neuron**: bridge presentato 5+ volte → salience del concetto Neuron aumenta

### 6.5 Observability

- `gray-matter stats` → cache hit rate, flash count, bridge count, worker health, latency media per tool
- `gray-matter logs --follow` → streaming log daemon
- `gray-matter dashboard` → web UI (oggi `webgui.html` minimal)

### 6.6 Multi-turn context nel RAG

GM tiene "conversation buffer" (ultimi 3-5 topic). Ogni `pulse` espande la query col contesto recente. Neuron fa già qualcosa di simile con `_build_context_window` — NeuRAG no.

### 6.7 Incremental indexing

`neurag watch <directory>` → daemon che monitora file .md/.py/.kt. Al cambio → chunka solo il file modificato, upsert nel DB. `watchdog` (pure Python) o `mtime` check periodico.

### 6.8 Semantic routing intelligente

GM analizza la query (intent). `question` fattuale → solo NeuRAG. `exploration` → solo Neuron. `task` → entrambi. Risparmio: 0-1 chiamata invece di 2.

### 6.9 Neuron come self-model (da Minimax, 2026-07-17)

Neuron non è un "memory tool" — è un **persistent self-model**. Tre mosse concrete:

- **Partizione `self/`** — context dedicato che memorizza lo stato di Neuron stesso (conteggi, topic forti, tasso crescita, errori, conferme)
- **`neuron_introspect` tool** — auto-comprensione di Neuron: `strongest_memory`, `weakest_area`, `recent_growth`, `self_summary`
- **`trust` float per nodo** — `confirm` → trust += 1; nessuna conferma per N turni → decay; ranking: `score = 0.5*sim + 0.3*salience + 0.2*recency + 0.1*trust`

> **Cosa skip per ora**: pride score (troppo antropomorfo), self-summary generato, framing "first-person memory".
>
> **Vision doc**: creare `VISION.md` — 3 paragrafi scritti a mano da Claudio (cosa è Neuron, cosa non deve diventare, cosa significa "bene"). Non LLM-polished.

### 6.10 Memoria dei path + provenienza (progetto condiviso) — *design fissato 2026-07-18*

**Idea (Claudio):** se l'utente lavora a un progetto, Neuron ricorda anche i **path dei file visitati** → recall associativo che risparmia ricerche e contesto in sessioni intense. In più, vista la natura cloud/condivisa, tenere traccia di **chi "possiede"** un file tra gli utenti del DB.

**Il rischio che lo giustifica (grounded sullo schema):** l'identità nodo è `(context, keyword)` — nessuna dimensione utente (v5.1 tiene lo stato per-utente in un *sidecar locale*, fuori dal DB condiviso). In un cervello condiviso i **concetti si fondono** (feature: stesso concetto = stesso nodo, rinforzato da più teste). Ma **un path è un'istanza, non un concetto** → con la stessa regola si fonde/confonde:

- *Ambiguità semantica*: stesso path relativo con radice diversa, o path assoluti da macchine diverse (inutili + leak di home/username), attaccati allo stesso nodo.
- *Clobber in concorrenza*: `refs` è una lista JSON nella riga del nodo → più writer fanno read-modify-write e si **sovrascrivono** (update persi), non solo "confusi".

**Decisione:** le due idee di Claudio (path + possesso) sono **la stessa soluzione** — la provenienza è il disambiguatore dei path. Ref come **record strutturato**, non stringa nuda:

```
{ path: "<relativo alla radice>", project_id: "<UUID>", by: "<utente>" }
```

- **`project_id` da file marcatore** `.neuron/project.json` (UUID generato una volta, viaggia con la cartella condivisa → deterministico e **uguale per tutti senza Git**). Scelta: `project_id` > git-remote perché non tutti hanno Git. Il `root` per i path relativi è la cartella del marcatore.
- **Path relativi alla radice**, mai assoluti nel DB condiviso (portabilità + privacy).
- **`by` = provenienza**, non ACL. Disambigua + risponde a "chi ha toccato cosa". Neuron resta memoria, non permission-layer.
- **`refs` come tabella propria** (non blob JSON), chiave che include `project_id` + `by` → append di due writer = righe diverse, niente clobber. (Si lega a **L1**: UPDATE atomici.)
- **Fallback marcatore assente**: id locale, path nel **sidecar per-utente** (precedente v5.1), fuori dal DB condiviso, finché il progetto non è "adottato". Meglio non-condiviso che erroneamente-fuso.

**Effetto:** i concetti si fondono (giusto), le posizioni restano distinte via `project_id` + `by`; due utenti sullo **stesso file logico** (stesso `project_id` + `path`) si fondono e rinforzano → "hotspot del team". La colonna `nodes.refs` **esiste già**; il lavoro è esporre i refs nell'API e strutturarli. → Neuron, in chiusura con suite verde (vedi Fase G).

---

## 7. Struttura progetti

```
Gray Matter Enviroment/
├── gray_matter/         MCP orchestratore (proxy, cache, flash, bridges)
│   ├── server.py        demone GM
│   ├── registry.py      registro server interni
│   ├── cache.py         cache contesto TTL
│   ├── flash.py         generazione flash
│   ├── bridges.py       store JSON ponti cross-store
│   ├── cli.py           CLI
│   ├── clients.py       registrazione cross-platform
│   ├── webgui.py        GUI web v2
│   └── _worker.py       worker persistenti
├── Neuron/              MCP grafo semantico
│   ├── src/neuron/server.py   grafo nodi/link + vector search
│   └── tests/
├── neurag/              MCP knowledge base gerarchica
│   ├── neurag/
│   │   ├── server.py    server MCP
│   │   ├── db.py        Turso/SQLite gerarchico + vector (retrieve + rerank opz.)
│   │   ├── chunker.py   chunking adattivo (AST, md, pdf, docx)
│   │   ├── embedder.py  Null / FastEmbed auto
│   │   ├── reranker.py  cross-encoder opzionale (OFF di default)
│   │   ├── settings.py  knob NeuRAG (rerank…), config.json separato dal DB
│   │   └── importer.py  import bulk YAML
│   └── test/
├── ARCHITETTURA.md      architettura NeuRAG + Gray Matter
├── ENVIRONMENT.md       regole d'ambiente
└── GRAY-MATTER-COMPENDIUM.md  → questo file
```

---

## 8. Regole d'ambiente (sintesi)

→ Vedi `ENVIRONMENT.md` per il completo.

- **File-tool (Read/Write/Edit) = fonte di verità.** Mai validare col mount bash un file appena editato.
- **Git si usa solo in locale** (sandbox ha index stale).
- **Pytest offline**: `pip download pytest -d Neuron/vendor/dev` una volta in locale.
- **Editable install**: `pip install -e .` per vivere gli edit.
- **Store isolato**: `NEURON_NO_DOTENV=1 NS_GRAPHS_DIR=/tmp/neuron-test`.
- **Un fix nel sandbox non è "verde" finché non gira in locale.**
