# Changelog — Gray Matter

## Unreleased
- **Quanto contesto GM inietta è ora un budget, non un effetto collaterale.**
  Il senso del progetto è far risparmiare token, e il blocco **proattivo** della
  pulse — bridge, vicini, flash: roba che nessuno ha chiesto — non aveva alcun
  tetto. Misurato: 40 bridge che condividevano un tag valevano **~5100 token in
  una sola pulse**. E `bridges_for` rinforzava *ogni* match, quindi un match di
  massa era anche una promozione di massa verso la soglia che manda un `confirm`
  a Neuron. Il match per identità di tag ha reso quel caso più facile da
  raggiungere, non meno.
  - `proactive_budget_chars` (default 800, `0` = niente proattivo): tetto in
    caratteri, applicato per **blocco** — mai un taglio a metà frase, che
    costerebbe lo stesso contesto e sembrerebbe un bug. Un blocco troppo grosso
    viene saltato e i successivi più piccoli entrano: sono spunti indipendenti,
    farne stare più vale più di un prefisso stretto dell'ordine.
  - `knowledge_top_n` (default 5): quanti chunk di vault per pulse. È la voce
    più costosa — 5 sono ~292 token misurati, 10 ~689.
  - Il flash ha priorità sui bridge: è l'unico contenuto proattivo che non si
    può ri-ottenere chiedendo (i bridge stanno in `gray-matter bridges`, i vicini
    in `knowledge_neighbors`). Un flash tagliato è perso.
  - `bridges_for(..., limit=N)` limita anche il **rinforzo**: mostrare un bridge
    è ciò che conta come usarlo, e quella regola stava già nel docstring mentre
    match e rinforzo vivevano nello stesso loop.
  - Il razionale di un bridge viene troncato a 80 caratteri nell'iniezione. Lo
    store ne accetta 500 perché lì è documentazione che un umano legge in
    `gray-matter bridges`; cinque razionali interi da soli sfondavano il budget e
    facevano cadere *tutti* i bridge.
  - Pulse tipica, stimata: ~700 token contro i ~6200 del caso peggiore prima.
- **Tutte le manopole di GM hanno finalmente un testo di aiuto** (`HELP`,
  `SUGGEST` in `settings.py`). La GUI costruisce la sua card da
  `config list --json` e `_knob_dict` legge `HELP` con fallback a `{}`: GM non ne
  aveva nessuno, quindi il pannello mostrava undici manopole nude — comprese
  quelle che decidono quanto contesto finisce in un modello. Un test ora fallisce
  se un knob nuovo arriva senza spiegazione.

## 1.1.2
- **GUI universale — pannelli speciali via CLI (decoupling)**. I 4 pannelli
  (Config, Repair, Uninstall, Processi) non importano più gli interni di GM
  (`settings`/`executor`/`paths`/`clients`): passano per la stessa via generica
  degli altri comandi (`python -m <tool>.cli <cmd> --json`). `grep "from
  gray_matter" webgui.py` ora resta solo `catalog` + `__version__`. Effetti:
  log uniformi (tutto passa dallo streaming/console), errori come righe taggate
  invece di traceback in-process, pannelli tool-agnostici (Config/Repair valgono
  per ogni tool che espone il comando).
- **`config`/`repair`/`uninstall` con `--json`** (SSOT dei metadati nel tool che
  li possiede): `config list --json` emette i knob (value/default/type/help/
  suggest); `repair --json` le superfici cancellabili (`key` = token CLI da
  ripassare); `uninstall --list/--json` superfici + esito+verifica. `gray-matter
  repair --reinstall` lancia la suite installer -Force. `config set` accetta ora
  il valore vuoto (guard `value is None`).
- **Launcher desktop cross-OS centralizzato** (`gray_matter/shortcut.py`, SSOT):
  `ensure_desktop_shortcut()` crea un'icona (.lnk Windows via WScript.Shell,
  .desktop Linux, .command mac) una volta per installazione (marker nel venv).
  La chiama `gray-matter gui` a ogni apertura (copre anche una GM installata via
  bootstrap, che non ha eseguito l'installer). Neuron/NeuRAG hanno una copia
  tool-local (`neuron/shortcut.py`, `neurag/shortcut.py`, keep-in-sync) così
  creano la loro icona anche in standalone senza GM.
- **Pannello Processi più leggero**: mostra solo i comandi lanciati dalla GUI
  (fonte `gui`); niente più scan `tasklist`/lettura pids del daemon a ogni
  render — via il coupling a `executor` E lo spawn ripetuto (latenza + flash).
  Il daemon di background si ferma dalla card `gray-matter → stop`.

## 1.1.1
- **Fix: niente più flash di CMD nella GUI**. Il pannello "Processi" si ricarica
  a ogni render (quindi a ogni clic sul tool in sidebar) e chiamava
  `tasklist`/`taskkill` senza `CREATE_NO_WINDOW`: su Windows (GUI via pythonw)
  lampeggiava una console a ogni clic. Aggiunto il flag Windows-only a tutti i
  subprocess console raggiungibili dalla GUI: `executor._alive`/`_reap`,
  `webgui.process_list`, `clients.py` register/deregister (claude CLI),
  `cloud.py` (turso CLI).
- **Audit comandi**: verificato che ogni comando del catalogo ha il suo handler
  (GM 24/24, NeuRAG 19/19, Neuron OK), nessun ambiente in errore.

## 1.1.0
- **Deregister per-tool (go-standalone)**: `gray-matter deregister --tool
  neuron|neurag|all` toglie il tool dal gateway e ne triggera la registrazione
  MCP diretta nei client (via il SUO engine `<tool>.clients`). Persistito nel
  knob `unmanaged` (settings): `detect_subservers()` non ri-gestisce un tool
  uscito, nemmeno dopo un restart. Caso misto sicuro: l'entry `gray-matter`
  resta nei client finché ALMENO un peer è gestito da GM; sparisce solo quando
  nessuno lo è. Reversibile: `gray-matter register --gateway` azzera
  `unmanaged` e riprende tutto (round-trip completo).
- **`clients.release_tool(name)`** / `standalone_register_tool(name)` /
  `unmanaged_tools()` / `set_unmanaged()`: la logica condivisa che usano sia
  `gray-matter deregister` sia `neuron|neurag go-standalone`.
- **GUI universale**: `neuron gui` e `neurag gui` aprono il control center
  condiviso (`gray_matter.webgui`) quando GM è importabile; la card Ripara con
  scope `neuron`/`neurag` ora preferisce l'installer DEL TOOL con `--force`
  (fallback `pip --force-reinstall --no-deps` invariato).

## 1.0.12
- **Path SSOT/SoC**: ogni componente possiede i PROPRI path; GM li SCOPRE, non
  li ridefinisce. `paths.neuron_graphs()`/`neurag_db()`/`neurag_config()` ora
  delegano a `neuron.paths`/`neurag.paths` (fallback storico se il peer manca).
  Nuovi `source_dir(component)` (chiede al peer), `discover_sources()`,
  `installer_script()` via discovery. GM registra solo il PROPRIO sorgente
  (`paths.json` in GM_HOME); i peer registrano sé stessi con `record-paths`.
  **Fix collaterale**: prima GM cercava `neurag_db` sotto LOCALAPPDATA mentre
  NeuRAG scrive in `~/.local/share/neurag` — ora combaciano (repair/uninstall
  puntano al file giusto).

## 1.0.11
- **Registro path sorgente** (`paths.py` → `env.json` in `<GM_HOME>`). Una lista
  unica di path che punta alle cartelle sorgente del trio (gray_matter, neurag,
  neuron). L'installer la scrive a ogni run (`record-env --root ... --gm ...`,
  chiamato da `install.ps1`/`install.sh`) → si **auto-aggiorna**; se manca fa
  self-heal deducendola dal layout. Repair/reinstall e la GUI ora leggono da qui
  (`paths.source_dir()`/`installer_script()`) invece di indovinare da `__file__`:
  ogni cosa punta al posto giusto. Risolve il "installer non raggiungibile dalla
  GUI" e rende il repair per-scope affidabile ovunque giri il control center.

## 1.0.10
- **Porta dinamica** (`cli.py`/`server.py`). 9876 non è più fissa: il daemon la
  prova e, se è presa da un processo ESTRANEO, scala alla prima libera
  (`GRAY_MATTER_PORT_SPAN`). La porta scelta va in un **rendezvous file**
  (`<GM_HOME>/port`) che i client leggono con `resolve_port()` per seguirla. Il
  singleton resta: se su una candidata risponde già un GM (probe `ping` → `gm:true`)
  il nuovo esce. Prima, se 9876 era occupata da un'altra app, GM non partiva mai.
- **Repair per-tool (scope)**: la card Ripara ora è scoped all'ambiente che la
  lancia — da Neuron pulisce/reinstalla solo Neuron, da NeuRAG solo NeuRAG, da
  Gray Matter tutta la suite. `repair_targets(scope)`/`repair_run(scope)` +
  comando `repair` esposto anche in Neuron e NeuRAG. Le caselle "cosa cancellare"
  partono **spente** (default: non cancella nulla).

## 1.0.9
- **Repair / reinstall pulito** (GUI + CLI). Nuova card **Ripara** (gruppo
  lifecycle) nel control center: mostra ciò che è presente (memoria Neuron,
  knowledge.db NeuRAG, bridges, config GM/NeuRAG, registrazioni client), spunti
  SOLO cosa cancellare — il resto resta — e con conferma a due click cancella i
  dati scelti e reinstalla il codice **forzato**. Backend `executor.repair_targets`/
  `execute_repair` + Api `repair_state`/`repair_run`; CLI `gray-matter repair
  [chiavi] [--dry-run]` (e `repair list`).
- **Installer `-Force`/`--force`** (`install.ps1`/`install.sh`): bypassa lo skip
  di versione ("already installed") e reinstalla il codice anche a versione
  invariata (`pip --force-reinstall --no-deps`). È ciò che usa il bottone Ripara,
  e risolve il caso "modifiche di solo-codice non venivano mai reinstallate".

## 1.0.8
- GUI console: pulsante **Copia** — copia tutta la trace negli appunti per
  poterla incollare/segnalare. Tre fallback: `navigator.clipboard` →
  `textarea`+`execCommand` → metodo Python `copy_clipboard` (`clip`/`pbcopy`/
  `xclip`) per WebView2/pywebview dove la clipboard JS è bloccata.
- GUI: card **Impostazioni** — il comando `config` (Gray Matter e NeuRAG) è reso
  come pannello di toggle/select/campi che salvano subito (`config_knobs`/
  `config_set`), non più il form grezzo action/key/value.

## 1.0.7
- GUI: un ambiente installato che espone 0 comandi (versione stantia nel
  venv, come Neuron 6.0.0 pre-refactor `COMMANDS`) ora lo dice a schermo con
  il rimedio, invece di mostrare una sezione vuota. Neuron 6.0.1 è il bump
  che forza il reinstall.

## 1.0.6
- Finestra nativa: su Windows si esige WebView2 (`gui="edgechromium"`) —
  senza, pywebview ripiegava su MSHTML/IE11 che non esegue il JS della
  pagina: finestra aperta, zero card, zero errori. Se WebView2 manca si apre
  il browser da soli. `GM_GUI_BROWSER=1` forza il browser, `GM_GUI_DEBUG=1`
  apre i devtools.
- La testata mostra la versione (`Control Center · vX.Y.Z`): un venv stantio
  si riconosce a colpo d'occhio.

## 1.0.5
- Finestra pywebview: si carica l'URL del server interno, non l'HTML come
  stringa — su about:blank WebView2 blocca le fetch verso 127.0.0.1 e la
  finestra restava senza card (regressione comparsa proprio installando
  pywebview). Same-origin = tutto lecito.
- La pagina non resta mai bianca: se il backend non risponde lo scrive e
  riprova da sola.

## 1.0.4
- `gm-neuron` / `gm-neurag` coesi col resto della GUI: se il daemon non gira
  lo avviano da soli (stessa logica di `start`) invece di rispondere
  "connection refused"; messaggi d'errore in italiano con l'esempio JSON
  giusto; help dei campi `tool` e `args` con i nomi dei tool più comuni.
  Il parametro `args` È facoltativo (vuoto = `{}`).
- `install.ps1`: probe dei moduli senza stderr (`find_spec`) — il probe
  `import webview` abortiva lo script sotto ErrorActionPreference=Stop
  proprio quando pywebview mancava; stesso fix per turso/fastembed e per il
  check post-install.

## 1.0.3
- Catalogo GUI: descrizioni per i nuovi comandi NeuRAG `ingest`,
  `rename-node`, `remove-node` (grafizzazione server-side + modifica nodi
  dal control center).

## 1.0.2

### Latenza: freshness con TTL + cronometro per worker
- `_worker.py`: il graph cache di Neuron veniva svuotato a OGNI chiamata →
  grafo riletto per intero dal DB per ogni tool call (2-3 volte a turno con
  pulse; sul tier Turso cloud ogni rilettura passa dalla rete). Ora si
  rilegge al massimo ogni `GM_WORKER_FRESH_TTL` secondi (default 5; 0 =
  comportamento vecchio). Il modello fastembed era già caldo: il collo era
  questo.
- Il worker misura il tempo dentro il tool (`ms` nella risposta) e
  `gray-matter stats` espone `worker_latency` (calls/avg_ms/last_ms per
  server): prima si misurava, poi si ottimizza.

### GUI autosufficiente
- `webgui`: print sicuro (`_say`) — sotto pythonw.exe (lo shortcut desktop)
  `sys.stdout` è None e un `print()` nudo uccideva il processo all'avvio.
  Era il crash della modalità browser lanciata dallo shortcut.
- `Api.catalog` e `catalog.environments` non possono più morire: qualunque
  eccezione (anche `SystemExit`) diventa un messaggio in console GUI, mai un
  processo morto o una sidebar vuota senza spiegazione.
- `install.ps1`: installa pywebview (best-effort) → finestra nativa, la GUI
  non dipende più da una console aperta.
- NeuRAG 1.0.1: `cli.py` non importa più db/chunker a livello modulo — il
  catalogo GUI legge i comandi senza caricare sqlite/turso/embedder (e senza
  sparire se una dipendenza manca nel processo GUI).

## 1.0.1

### Control center: funziona, una GUI sola
- `cli.py` non importa più `gray_matter.server` a livello modulo: il processo
  GUI non tocca `mcp`, quindi il catalogo di Gray Matter non risulta più
  "illeggibile" (era la causa dei pulsanti morti). Host/porta IPC ora vivono
  in `cli.py` (SSOT) e `server.py` li importa da lì.
- Comandi interattivi (`uninstall`, `cloud`, `neuron setup/manage/connect`)
  marcati in `catalog.INTERACTIVE`: la GUI li apre in una finestra di
  terminale vera invece di lasciarli appesi con stdin chiuso.
- Form: solo i campi obbligatori in vista; opzioni e campo libero sotto
  "Opzioni avanzate". Obbligatorio mancante → errore in italiano, subito.
- Spiegazioni in italiano per ogni comando (`catalog.HELP_IT`), fallback al
  testo argparse per i comandi futuri.
- GUI Tkinter ritirata: `gui.py` rimanda a `webgui`, `--classic` ignorato,
  i comandi `gui` nascosti dalle card.

## Unreleased

### Bridge come terzo store (B-STORE)
- `bridges.py`: da JSON a tabella `bridges` 3-tier — Turso cloud
  (`GM_TURSO_DATABASE_URL`, DB proprio `gm_bridges`) → sqlite locale
  (`bridges.db`). API pubblica invariata; upsert concurrent-safe; migrazione
  one-shot da `bridges.json`. Extra `pip install gray-matter[cloud]`.

### Env model daemon→worker
- `_env.py`: il daemon carica `<GM_HOME>/.env` all'import (env reale vince,
  no-op sotto pytest, opt-out `GM_NO_DOTENV`, override `GM_ENV_FILE`);
  i worker ereditano l'env → un solo `.env` per `TURSO_*` / `NEURAG_TURSO_*` /
  `GM_TURSO_*`.

### turso CLI: install offerta di default (opt-out)
- `cloud setup` senza turso CLI ora la offre lui: prompt `[Y/n]` → installer
  ufficiale pinnato (`GM_TURSO_CLI_VERSION`, default v0.7.0-pre.22; Windows
  nativo via `irm …turso_cli-installer.ps1 | iex`, POSIX via `.sh`). Opt-out:
  `--no-cli-install` / `GM_TURSO_CLI_INSTALL=0`; headless `--yes`. Rifiuto o
  fallimento → `CLI_GUIDE` (comandi per OS, link docs, e il reminder che
  `wire` non richiede nulla). GUI: bottoni "Install CLI" (con conferma) e
  "Guide" nel pannello Cloud group.

### Fix dai test manuali post-install (2026-07-21 sera)
- **GUI: tutti i comandi rotti** — root-cause: la GUI gira col python del venv
  GM ma il PATH del processo non include `Scripts/` → `Popen(["gray-matter"|
  "neuron"|"neurag", …])` = command not found. Fix: `_exe()` risolve i console
  script accanto a `sys.executable` (applicato a `_stream`, `_run_seq`,
  `_open_terminal`; fallback al nome per git/powershell/cloudflared).
- **Register Claude Code falliva sempre** — su Windows `claude` è uno shim
  `.cmd` (npm) che CreateProcess non esegue. Fix: path da `shutil.which` +
  wrapper `cmd /c` per `.cmd`/`.bat`; il report ora include l'errore VERO
  (ultima riga di stderr), non un muto "cli failed".
- **Installer non idempotente a vista** — re-run reinstallava GM/peer. Fix
  (install.sh+ps1): confronto versione sorgente (pyproject) vs installata →
  "already installed — skipping" invece del rebuild.
- **Setup card**: checkbox Neuron/NeuRAG ora **OFF di default** (le spunte
  aggiungono componenti; senza spunte Install/Repair ripara solo il gateway).

### B4 chiuso — turso CLI: comando token e CLI giusta
- `_mint_group_token` usa `turso group tokens create <group>` (confermato dalle
  docs; `mint` non esiste).
- **Scoperta**: il pacchetto `tursodatabase/turso` v0.7.x (installer nativo
  Windows) è il database locale, NON la CLI cloud → l'install offerta usa lo
  script ufficiale `get.tur.so` (mac/linux); su Windows guida onesta (WSL) con
  `wire` come strada raccomandata. `setup` riconosce la CLI sbagliata sul PATH
  ("unrecognized subcommand") e rimanda alla guida.

### Doctor esteso (passo 5)
- `gray-matter doctor` ora riporta i **tier di tutti e 3** (neuron/neurag/
  gm_bridges, env reale > .env GM; NeuRAG dal suo engine live quando su) e se il
  **cross-store è attivo** (neuron+neurag vivi e collaborativi).

### Stimulus safety-net (passo 6)
- Se il piggyback 🧠 di Neuron non passa da `stimulus_safety_gap` turni-tool,
  GM rilancia lo stimolo sul pass-through (via `forgotten`, best-effort, mai
  bloccante). Toggle/tuning: `stimulus_safety_net` / `stimulus_safety_gap`
  (config CLI e GUI Preferences).

### `gray-matter logs [--follow]` (G2, passo 7)
- Il daemon scrive stdout/stderr in `<GM_HOME>/logs/daemon.log` (spawn con
  `-u`, marker di sessione; fallback DEVNULL mai bloccante). `logs` fa la coda
  (`-n`), `--follow` resta in ascolto.

### Fix audit B8 (OpenCode) + rotazione token
- `wire()` non scrive più un token orfano (fix OpenCode: token solo con almeno
  una URL valida). Esteso alla **rotazione**: token nuovo con URL già cablate
  nel `.env` è lecito (probe contro una URL salvata); token senza alcuna URL —
  né nuova né salvata — resta rifiutato.

### `gray-matter cloud wire` — Turso SENZA CLI (bring-your-own)
- Un utente normale non deve installare la turso CLI: `cloud wire` cabla nel
  `.env` GM le URL incollate dal dashboard (parziale ok: anche una sola) + un
  token — con probe best-effort via `neuron.connect` prima di salvare (probe
  fallito → niente scritto). Token mai su argv obbligatorio (env/.env/prompt
  nascosto) e mai in output. GUI: sezione "Manual — NO turso CLI" nel pannello
  Cloud group (3 URL + token, chiamata in-process). `setup` resta il percorso
  auto-provisioning per chi HA la CLI.

### `gray-matter cloud setup|status|teardown`
- CLI core idempotente (full group / bring-your-own / parziale): verifica
  `turso` CLI+login, crea/rileva gruppo e 3 DB, un solo group token (riusato se
  già cablato), scrive il `.env` GM (backup `.bak`, mai clobber). `teardown`
  de-cabla solo le env (i DB restano). Pannello "Cloud group…" nella webgui che
  invoca la CLI e ne streamma l'output; `turso_save` ora scrive nel `.env` GM
  (non più nella cwd).

### Fix da audit OpenCode (2026-07-21)
- `.env` con BOM (PowerShell 5.1 `Set-Content -Encoding utf8`): letti con
  `utf-8-sig` in `_env.py` e `cloud.py` (read + update, riscrittura senza BOM);
  chiavi comunque ripulite come cintura. Keep-in-sync con `neuron/_env.py`.

### GUI adattiva (G3) + pannello di controllo
- La webgui mostra/nasconde le sezioni in base ai componenti installati
  (`data-req` + `eco_status`): funziona in ogni combo — Neuron solo, NeuRAG
  solo, GM+uno, full suite. L'Ecosystem box resta sempre visibile come
  recovery (bottoni Install).
- Sidebar completa: sezione "Memory (Neuron)" (overview, doctor, consolidate,
  visualize, register, console) e nuova "Knowledge (NeuRAG)" (status, tree,
  query, import, health, doctor).
- Orchestrator card: bottoni espliciti **Full suite** (bridge ON) /
  **Standalone (no bridge)** + Stats + Doctor.
- **Dashboard**: pannello con snapshot strutturato (`panel_info`, best-effort
  su ogni parte): componenti, versioni, stato daemon, attività (pulses/cache/
  flashes/workers), bridge, tier cloud per componente.

## v1.0.0 (2026-07-21)

Prima release stabile del gateway. Consolida 0.2.0 (wizard GUI, settings CLI,
cache TTL dinamica, gateway flip, pass-through degli schemi reali). Fix:
`__version__` allineato al pyproject (riportava 0.1.0, ora 1.0.0).

## v0.2.0 (2026-07-20)

### Wizard GUI
- Setup card: component selection (Neuron/NeuRAG) + Preview/Install/Test
- Preferences card: dynamic settings from `settings.py` DEFAULTS
- Turso connection card (existing)
- Backend: `setup_state`, `setup_run`, `setup_test`, `setup_prefs_get/set`

### Gateway flip
- `register --gateway` evicts neuron/neurag, registers only GM
- Daemon singleton via exclusive bind
- MSIX config support (Claude Desktop Packages path)

### Settings CLI
- `gray-matter config get|set|list` backed by `settings.py`

### Cache improvements
- Dynamic TTL based on topic heat
- Multi-topic accumulation (removed clear on topic change)
- `invalidate_related(topic)` post `store_turn`

### Installer/Uninstaller
- `executor.py`: dispatch on `installer.plan()` / `uninstaller.plan()`
- Steps: reap, ensure_data, install, register, deploy_hook, write_manifest
- Uninstall: interactive data deletion, `.bak` restore
- Hook deployment: claude-code, cowork, opencode

### Fixes
- F0: Worker persistent processes (no re-import per call)
- F1: IPC length-prefixed read fixed
- F2: `_restart_dead_servers` now respawns
- F19: Cache singleton (no more recreate per pulse)
- F20: Cache no longer clears on topic change
- F21: Cache invalidation post store_turn
- F22: Bridge ingest validation
- F23: Pulse topic validation

### Tests
- 38 tests passing (test_executor, test_cache_dynamic_ttl, test_topic_buffer, etc.)
