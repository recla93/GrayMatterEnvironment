# Handoff → Fable — Standalone totale (deregister + registrazione MCP individuale + GUI universale)

**Data:** 2026-07-22
**Per:** Claude Fable 5 (esecuzione in un'unica passata)
**Contesto repo:** `Gray Matter Enviroment/` con 3 progetti in 3 cartelle: `gray_matter/` (orchestratore/gateway), `neuron/` (memoria semantica, src-layout `neuron/src/neuron`), `neurag/` (knowledge base RAG, flat-layout). Gray Matter è l'orchestratore di Neuron e NeuRAG; Neuron e NeuRAG possono lavorare standalone o insieme.

**Obiettivo di questo handoff:** rendere Neuron e NeuRAG **totalmente standalone** — registrarsi da soli come MCP nei client, essere de-registrati da GM per-tool, ripararsi/reinstallarsi dai propri path senza GM, e caricare una **GUI universale** da qualunque tool. Le decisioni sotto sono già state prese dall'utente: seguirle, non rimetterle in discussione.

---

## 0. Decisioni dell'utente (vincolanti)

1. **NeuRAG registrazione standalone** → creare un `neurag/clients.py` **completo**, sul modello di `neuron/src/neuron/clients.py` (matrice client, register/deregister per ognuno). NeuRAG deve registrarsi/deregistrarsi da solo, senza GM.
2. **Deregister** → **per-tool**: un'azione che toglie il/i tool selezionati (entrambi o uno solo) dal gateway GM e li registra come MCP diretti nei vari config dei client. Reversibile (tornare al gateway con `gray-matter register --gateway`).
3. **GUI universale** → qualunque tool dell'environment carica la GUI (control center). In standalone la GUI parte dal tool di riferimento senza GM. Se GM non c'è, si registrerà da solo all'install; Neuron e NeuRAG ci sono già.

---

## 1. STATO ATTUALE — cosa è GIÀ fatto in questa sessione (NON rifare)

Versioni correnti: **GM 1.0.12 · NeuRAG 1.1.3 · Neuron 6.0.3** (pyproject + `__init__` allineati).

Già implementato e verificato staticamente:

- **Path SSOT/SoC** (fatto ora): ogni componente possiede i suoi path.
  - `neurag/paths.py` (NUOVO): `data_dir()`, `db_path()`, `config_path()`, `source_dir()`, `record_self()`, `data_paths()`. `db.py` e `settings.py` delegano qui. Override `NEURAG_HOME`.
  - `neuron/src/neuron/paths.py` (NUOVO): `graphs_dir()` (delega a `config.graphs_dir()`), `data_dir()`, `source_dir()`, `record_self()`, `data_paths()`.
  - `gray_matter/paths.py`: `neuron_graphs()`/`neurag_db()`/`neurag_config()` ora **delegano** ai peer (import lazy + fallback storico). Nuovi `source_dir(component)` (chiede al peer), `discover_sources()`, `installer_script()`, `record_self()` (GM registra solo sé), `env_file()` = `<GM_HOME>/paths.json`. **Fix collaterale**: prima GM cercava `neurag_db` sotto LOCALAPPDATA, ora combacia con `~/.local/share/neurag` (dove NeuRAG scrive davvero).
  - CLI self-register: `gray-matter record-env --gm <dir>`, `neuron record-paths --source <dir>`, `neurag record-paths --source <dir>` (tutti nascosti dalla GUI via `catalog.GUI_HIDDEN`). L'installer GM li chiama.
- **Porta dinamica** (GM): `cli.py` ha `resolve_port()`, `write_port_file()`, `port_is_free()`, `gm_answers()` (probe `ping`→`gm:true`), `GRAY_MATTER_PORT_SPAN`. `server.py` `_ipc_listener` scandisce le porte da 9876, scrive `<GM_HOME>/port`, mantiene il singleton via probe. Client via `resolve_port()`.
- **Repair** (GM + per-tool CLI): card "Ripara" scoped nella webgui (`repair_state(scope)`/`repair_run(scope)`), `executor.repair_targets(scope)`/`execute_repair(wipe)`, comando `gray-matter repair`, `neuron repair`, `neurag repair`. Caselle "cosa cancellare" **spente di default**.
- **Installer `--force`** — SOLO in `gray_matter/install.ps1` e `install.sh` (bypassa lo skip di versione, `pip --force-reinstall --no-deps`). **MANCA in neuron/ e neurag/** (vedi §2.D).
- **Turso** (NeuRAG): preferito con fallback documentato — `db._ensure_turso()` prova import + `pip install pyturso` dalle wheel (`NEURAG_TURSO_ATTEMPTS`, default 3), poi degrada a sqlite3 documentando (`status.turso_degraded`/`turso_errors`, `doctor`). Escape `NEURAG_REQUIRE_TURSO=0`, `NEURAG_TURSO_AUTOINSTALL=0`.
- **Reranker** (NeuRAG): opt-in OFF di default (`neurag/reranker.py`, `settings.py` `rerank`/`rerank_pool`/`rerank_model`), card Impostazioni nella GUI (`config_knobs`/`config_set`), extra `neurag[rerank]`.
- **GUI**: pulsante **Copia** in console (`copy_clipboard`), card Impostazioni generica (`c.name==="config"`), card Ripara (`c.name==="repair"`). La GUI è **catalog-driven**: un subcomando aggiunto a una CLI compare da solo (`gray_matter/catalog.py`).

---

## 2. LAVORO DA FARE (con le decisioni sopra)

### A. NeuRAG si registra da solo — `neurag/clients.py` completo

Modello: `neuron/src/neuron/clients.py`. Ha una matrice `CLIENTS` (`claude-desktop`, `claude-code`, `cursor`, `vscode`, `opencode`) con `entry(python_exe)`, `keys`, `candidates()`, `format` (json/jsonc/toml), e le funzioni:
`register(client, slug, python_exe, install_dir="", dry_run=False) -> Result`, `register_all(...)`, `deregister(client, slug) -> Result`, `deregister_all(slug)`, più helper (`pick_existing`, `load_config`, `save_json`, `backup`, `read_text`) e la registrazione Claude Code via `claude mcp add` CLI.

Da fare:
1. Creare `neurag/clients.py` che rifà la stessa struttura ma per NeuRAG:
   - `slug` = `"neurag"`; l'entry MCP lancia il server standalone `neurag-mcp` (console-script già in `pyproject [project.scripts] neurag-mcp = "neurag.server:main"`). L'entry deve puntare al python del venv + `-m neurag.server` (NON al console-script sul PATH — vedi la nota in `gray_matter/webgui.py` `_MODULE_FOR`).
   - Riusare la STESSA matrice client (stessi path/candidates/format). **Non copiare-incollare** la logica di parsing JSON/TOML se si può fattorizzare, ma dato che Neuron è un modulo a sé e NeuRAG idem, un clone mirato è accettabile; documentare `keep-in-sync con neuron/clients.py`.
   - `register`/`deregister`/`register_all`/`deregister_all` identici come firma.
2. `neurag/cli.py`: aggiungere i comandi `register` e `deregister` (subparser), che chiamano `neurag.clients`. Gestirli PRIMA di aprire il DB (come `config`/`repair`/`record-paths`). Gruppo `lifecycle` in `COMMAND_GROUPS`. `deregister` NON va nascosto (serve visibile), `register` nemmeno.
3. **Decouple `neurag/server.py` da GM**: oggi importa `from gray_matter.server import autoregister, auto_register_and_run` (righe ~19, ~373). Renderlo opzionale: se GM è importabile → autoregister col gateway; se NON lo è → NeuRAG gira come server MCP standalone puro (nessun errore). Deve già esserci un try/except attorno all'import GM (verificare `_GM_AVAILABLE`); assicurarsi che il path standalone sia completo (il server risponde ai client senza GM).

### B. Deregister per-tool (go-standalone)

Semantica scelta: togliere il/i tool selezionati da GM e registrarli come MCP diretti nei config.

Da fare:
1. **GM lato gateway** (`gray_matter/clients.py`): esiste già `register(..., gateway=True)` che registra SOLO gray-matter ed evict neuron/neurag (`GATEWAY_EVICT`), e `deregister(servers)`. Aggiungere una funzione/*flag* per il passaggio inverso **per-tool**: dato un tool (`neuron`|`neurag`), rimuovere l'entry gateway per quel tool dal gateway model e lasciare che il tool si registri da solo. In pratica: quando un tool va standalone, GM non deve più spawnare/gestire quel worker e i client devono avere l'entry diretta del tool invece di `gray-matter`.
2. **Comando utente** — due modi coerenti (implementarli entrambi, condividono la logica):
   - `neuron go-standalone` / `neurag go-standalone`: il tool (a) si registra diretto nei client via il proprio `clients.register_all(slug, py)`, (b) chiede a GM (se presente) di smettere di gestirlo — via IPC `deregister` (già esiste l'azione `unregister` nel dispatch IPC di `server.py`; aggiungere se serve un `set_managed(name, False)` o riusare unregister), e (c) se il gateway model era attivo, NON rimuove del tutto `gray-matter` dai client se l'altro peer resta gestito da GM (attenzione a non rompere l'altro tool).
   - `gray-matter deregister --tool neuron|neurag|all`: lato GM, evict quel tool dal gateway e triggera la sua registrazione standalone (`<tool> register`).
3. **Reversibile**: `gray-matter register --gateway` deve riportare tutto al modello gateway (già esiste). Documentare il round-trip.
4. **Attenzione al caso misto**: un tool standalone + l'altro dietro GM. I client devono avere: entry diretta del tool standalone + entry `gray-matter` per il resto. Non rimuovere `gray-matter` dai client finché almeno un peer è ancora gestito da GM.

### C. GUI universale (parte da qualunque tool, anche senza GM)

Oggi la webgui vive in `gray_matter/webgui.py` + `webgui.html`, ed è catalog-driven leggendo i 3 ambienti. In standalone (GM assente) non c'è webgui.

Decisione utente: **qualunque tool carica la GUI**; se GM manca, si registrerà da solo all'install (Neuron/NeuRAG già presenti). Interpretazione operativa (scegliere la via più semplice che la soddisfa):

- **Via consigliata**: la GUI resta UN solo modulo (`gray_matter.webgui`) ma diventa raggiungibile da ogni tool:
  - `neuron gui` e `neurag gui` (già esistono per Neuron Tkinter; per NeuRAG aggiungere un comando `gui`) devono, se `gray_matter` è importabile, lanciare la **control-center condivisa** (`gray_matter.webgui:main`); se GM NON è installato, lanciarne l'install/registrazione al volo (bootstrap: GM è leggero) OPPURE degradare a una GUI minimale del solo tool.
  - Il `catalog.py` già degrada: un ambiente non installato compare come "non installato", non rompe la GUI. Verificare che con GM assente ma Neuron/NeuRAG presenti la pagina si disegni comunque (serve che `webgui`/`catalog` non abbiano import obbligatori che spariscono senza un peer).
  - "GM si registra da solo all'install": quando parte la GUI universale e GM non è installato, offrire (o eseguire best-effort) l'install di GM come gateway, poi la GUI mostra tutti e tre. Neuron/NeuRAG restano utilizzabili nel frattempo.
- La card **Ripara** in standalone deve funzionare senza le Api di GM (vedi §2.E): se `repair_run` (Api GM) non c'è, il tool usa il proprio percorso di repair CLI/installer.

Chiarire in implementazione: NON serve duplicare l'intera webgui in ogni tool. Basta che (1) il comando `gui` di ogni tool porti alla control-center condivisa quando GM c'è, (2) esista un fallback quando GM manca (install GM o GUI minima), (3) il repair standalone non dipenda dalle Api GM.

### D. `--force` negli installer standalone

`gray_matter/install.ps1`+`.sh` hanno già `-Force`/`--force`. Replicare lo STESSO pattern in:
- `neuron/install.ps1` + `neuron/install.sh`
- `neurag/install.ps1` + `neurag/install.sh`

Pattern (vedi `gray_matter/install.ps1`): `param([switch]$Force)` primo statement; `$ForceArgs = @(); if ($Force) { $ForceArgs = @("--force-reinstall","--no-deps") }`; bypassare il check `already_installed`/`Test-AlreadyInstalled` quando `$Force`; aggiungere `@ForceArgs`/`$FORCE_ARGS` alle `pip install`. Bash: `FORCE=0; for a in "$@"; do case "$a" in -f|--force) FORCE=1;; esac; done; FORCE_ARGS=...`. **Nota**: gli installer di neuron/neurag oggi fanno bootstrap di GM (fetch); assicurarsi che `--force` valga anche per il reinstall del PROPRIO pacchetto, non solo di GM.

### E. Auto-repair standalone dai propri path

Ogni tool deve potersi riparare/reinstallare **dai propri path**, senza GM:
- `neuron/src/neuron/__main__.py` `_repair_cli` e `neurag/cli.py` `_cmd_repair`: oggi stampano "install.ps1 -Force" generico. Renderlo puntuale: usare `paths.source_dir()` del tool per trovare il PROPRIO installer e (opzionale) lanciarlo con `--force` (o almeno stampare il path assoluto corretto). Il tool conosce il proprio `source_dir()` (già fatto in §1).
- Nella webgui `repair_run(scope=...)`: per scope `neuron`/`neurag`, usare `paths.source_dir(scope)` (già lo fa via `_scope_dir`) e preferire l'installer DEL TOOL con `--force`; il fallback `pip --force-reinstall` resta.
- Verificare che in standalone (GM assente) l'utente possa fare tutto da CLI: `neuron repair --wipe-memory` + `install.ps1 -Force`; `neurag repair --wipe-knowledge` + `install.ps1 -Force`.

---

## 3. PIANO FILE-PER-FILE (ordine consigliato)

1. `neurag/clients.py` (NUOVO) — clone mirato di `neuron/clients.py`, slug `neurag`, entry `-m neurag.server`. Riusa matrice client.
2. `neurag/cli.py` — comandi `register`/`deregister` (pre-DB), gruppo lifecycle; wiring a `neurag.clients`.
3. `neurag/server.py` — rendere l'autoregister GM opzionale (standalone puro se GM assente).
4. `neuron/__main__.py` — comando `go-standalone` (register standalone + chiedi a GM di mollarlo); `neurag/cli.py` — idem `go-standalone`.
5. `gray_matter/clients.py` + `gray_matter/cli.py` — `deregister --tool neuron|neurag|all` (evict per-tool + trigger register standalone del tool); mantenere reversibilità con `register --gateway`.
6. `gray_matter/server.py` — se serve, azione IPC per smettere di gestire un singolo worker (riusare/estendere `unregister`).
7. `neuron/install.ps1`+`.sh`, `neurag/install.ps1`+`.sh` — `--force` (pattern di GM).
8. `neurag/cli.py` — comando `gui` che lancia `gray_matter.webgui:main` se GM importabile, altrimenti bootstrap/fallback. (Neuron ha già `gui` Tkinter: valutare se puntarlo alla control-center condivisa quando GM c'è.)
9. `gray_matter/webgui.py`/`webgui.html`/`catalog.py` — verificare che la GUI si disegni con GM assente ma peer presenti; repair standalone non dipenda dalle Api GM (fallback CLI/installer del tool).
10. `_cmd_repair`/`_repair_cli` — puntare all'installer del tool via `source_dir()`.
11. Bump versioni + CHANGELOG nei 3 repo (vedi §5).

---

## 4. GOTCHAS (leggere prima di scrivere)

- **Gate di versione dell'installer**: `install.ps1`/`.sh` saltano il `pip install` se la versione sorgente == installata. Quindi OGNI modifica di codice va accompagnata da un **bump di `pyproject.toml` E `__init__.py`** (devono combaciare), altrimenti la GUI/i comandi restano vecchi. `Get-SrcVersion` legge `version = "..."` da `pyproject.toml`.
- **GUI catalog-driven**: aggiungere un subcomando a una CLI lo fa comparire da solo nel control center. Per nasconderlo: `gray_matter/catalog.py` `GUI_HIDDEN`. Per il gruppo/ordine: `COMMAND_GROUPS` nella CLI del tool. Comandi interattivi (aprono terminale) vanno in `catalog.INTERACTIVE`.
- **Entry MCP via `-m modulo`, non console-script**: gli script in `Scripts/` non sono sempre sul PATH del processo (causa "command not found"). Vedi `gray_matter/webgui.py` `_MODULE_FOR`.
- **`keep-in-sync`**: `neurag/clients.py` clona `neuron/clients.py` — annotare la parentela nei commenti. Idem per le facade Turso già annotate.
- **Non rompere il caso misto** (un tool standalone, l'altro dietro GM): non rimuovere `gray-matter` dai client finché un peer è ancora gestito da GM.
- **Path già SSOT/SoC**: usare SEMPRE `<comp>.paths.*` (mai reintrodurre path hardcodati). GM scopre i peer, non li ridefinisce.
- **Standalone = niente import obbligatori di `gray_matter`** nei percorsi runtime di Neuron/NeuRAG. Ogni import GM va in try/except con fallback.
- **Backup/verify**: i writer di config (clients.py) fanno backup `.bak` e non riscrivono mai JSONC/TOML alla cieca — mantenere questa cautela nel nuovo `neurag/clients.py`.
- **ENVIRONMENT.md**: GUI/executor si testano in locale; in sandbox solo static check + test in tmp-dir. Non lanciare install reali in sandbox.

---

## 5. VERIFICA + VERSIONI

Static (sandbox, `PYTHONPATH="neurag:gray_matter:neuron/src"`):
- `python -m py_compile` su tutti i file toccati.
- `bash -n` sugli `install.sh`.
- `catalog.environments()`: 3 ambienti, `error='-'`, `register`/`deregister`/`go-standalone` presenti dove attesi, `record-*` nascosti.
- `neurag.clients`: register/deregister in dry-run su config tmp (nessuna scrittura reale).
- Round-trip: `neurag register` (dry) → entry attesa; `neurag deregister` (dry) → rimozione.
- GUI con GM assente: simulare (rimuovere gray_matter dal PYTHONPATH) e verificare che `neuron.paths`/`neurag.paths` e i comandi standalone reggano.

Locale (utente): GUI reale, bind porta reale, install `-Force`, switch gateway↔standalone e ritorno.

Bump proposto a fine lavoro: **GM → 1.1.0** (feature grosse: deregister per-tool + GUI universale), **NeuRAG → 1.2.0** (clients.py proprio + register/deregister + gui), **Neuron → 6.1.0** (go-standalone). Aggiornare i 3 CHANGELOG e, se serve, `GRAY-MATTER-COMPENDIUM.md` (sezioni architettura/registrazione) e `docs/` (CONFIGURATION/ARCHITECTURE IT+EN).

---

## 6. Domande aperte da confermare con l'utente (se Fable ha dubbi)

- Nel deregister per-tool, quando ENTRAMBI vanno standalone: rimuovere del tutto `gray-matter` dai client, o lasciarlo dormiente? (Proposta: rimuoverlo se nessun peer resta gestito da GM.)
- GUI universale con GM assente: install automatico di GM (best-effort) o solo prompt/fallback? (Proposta: prompt/offerta, non install silenzioso.)
- NeuRAG `clients.py`: stessa identica matrice client di Neuron (claude-desktop, claude-code, cursor, vscode, opencode) — confermare che non servono client aggiuntivi.
