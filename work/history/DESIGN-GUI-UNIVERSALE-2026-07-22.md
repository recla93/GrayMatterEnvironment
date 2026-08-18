# Design + Flow-Audit — GUI universale standalone (API-driven, compatibile ovunque)

**Data:** 2026-07-22
**Decisione delegata all'autore del doc.** Copre: dove vive la GUI, il gap "tutto API calls", e l'audit di OGNI flusso interagente su 6 assi — Compatibilità, Comandi, Logs, Trace, Readiness, Responsiveness. Più: file da cancellare, flash-fix residui, sequenza, versioni.

---

## 0. Finding chiave (determina tutto)

La webgui è **una sola** (`gray_matter/webgui.py` + `webgui.html`) ed è **catalog-driven**: scopre i tool installati leggendo la loro CLI (`gray_matter/catalog.py` via `importlib.find_spec` + `build_parser`/`COMMANDS`). L'esecuzione dei comandi è **già API/CLI**: `Api.run(tool, command, args)` lancia `python -m <tool>.cli <cmd>` — tool-agnostica, nessun aggancio agli interni del tool.

**MA** i pannelli speciali aggiunti dopo **bypassano** questa via e importano gray_matter internamente (verificato in `webgui.py`):
- `config_knobs`/`config_set` → `from gray_matter import settings` (+ `neurag.settings`)
- `repair_state`/`repair_run` → `from gray_matter import executor`, `paths`
- `uninstall_state`/`uninstall_run` → `executor`, `clients`
- `process_list`/`process_stop` → `executor`

Conseguenza: **la webgui NON è portabile/standalone finché questi pannelli dipendono da gray_matter**. Il tuo "dovrebbe essere tutto refactor con API calls" è vero solo per `run`; i pannelli speciali sono il debito.

### Decisione
1. **Una sola GUI, canonica in `gray_matter`** (niente triplicazione: il backend è accoppiato a catalog/executor/paths/clients/settings — copiarla richiederebbe copiare mezzo gray_matter). Resta l'SSOT della GUI.
2. **Completare il refactor "tutto API calls"**: i pannelli speciali smettono di importare gli interni e passano per la stessa via generica — i tool espongono GIÀ i comandi CLI necessari (`<tool> config`, `<tool> repair`, `<tool> record-paths`, `<tool> register/deregister`). Il pannello Processi resta l'unica utility OS-side (tasklist), isolata dietro una funzione sola.
3. **"Present in ogni repo, anche senza gray_matter"** = ogni tool ha il comando `gui` che lancia la GUI canonica e, se gray_matter non è importabile, **la installa da solo** (self-configurable, extra `[gui]` + bootstrap). NON è una copia fisica: è "lanciabile da ovunque, si auto-configura". Se in futuro si vuole la copia fisica pura, serve prima estrarre un pacchetto `gm-webgui-core` (catalog+executor+paths+clients+settings) — **deferito**, troppo per ora.
4. **Cancellare** la GUI Tkinter (`neuron/src/neuron/gui.py`) e gli agganci — **solo DOPO** che il punto 3 è in piedi (altrimenti uno standalone senza gray_matter resta senza GUI).

---

## 1. Compatibilità

- **OS/transport**: `webgui.py` usa pywebview (WebView2 su Windows) e, se assente, `http.server` stdlib in browser. Entrambi via lo stesso `Api`. Mantieni i due percorsi; il refactor dei pannelli non li tocca.
- **gray_matter presente vs assente**: `<tool> gui` → prova `from gray_matter.webgui import main`; se manca → bootstrap (install `gray-matter` come extra/da GitHub/PyPI, poi rilancia). Già impostato da Fable per `neuron gui`/`neurag gui` — verificare che il ramo di bootstrap sia completo e loggato.
- **Venv condiviso vs per-tool**: l'installer del trio usa UN venv (tutti e tre importabili). In un tool installato in venv isolato, `gui` deve installare gray_matter **in quel venv** (stesso `sys.executable`).
- **Entry MCP via `-m modulo`** (non console-script): mantenere ovunque (`_MODULE_FOR`).
- **Back-compat comando `gui`**: `neuron gui` prima = Tkinter, ora = webgui. La rimozione della Tkinter va **sequenziata** (vedi §7). Rimuovere anche `neuron-gui` da `[project.scripts]` e `[project.gui-scripts]` in `neuron/pyproject.toml`.
- **Shim `gray_matter/gui.py`**: è solo `from gray_matter.webgui import main`. Non è in `[project.scripts]` (lì c'è `gray-matter-gui = gray_matter.webgui:main`). Se nessuno lo importa → cancellabile; verificare con un grep prima.
- **Gate di versione installer**: ogni modifica richiede bump `pyproject`+`__init__` combacianti, o l'installer salta il reinstall.

## 2. Comandi (catalog-driven)

- **Copertura handler** (verificato oggi): GM 24/24, NeuRAG 19/19, Neuron OK, 0 ambienti in errore. Ogni comando ha il suo dispatch.
- **`gui` unificato** nei 3 tool: stessa semantica (lancia webgui canonica, bootstrap gray_matter se assente). `neuron gui` e `neurag gui` esistono; allinearli.
- **Pannelli speciali → comandi CLI**: dopo il refactor, la card Config chiama `<tool> config get|set`, la card Repair chiama `<tool> repair ...`, ecc. — così sono API calls e compaiono coerenti. Attenzione: alcuni tool potrebbero non esporre TUTTE le chiavi via CLI (es. `neurag config` sì; `neuron` non ha config knobs) → il pannello si adatta a ciò che il tool espone (assente = niente card).
- **Hidden/interactive**: `GUI_HIDDEN` = gui, record-env, record-paths. `INTERACTIVE` = uninstall/cloud/setup/manage/connect (aprono terminale). Verificare che repair/deregister NON siano interactive (girano in pannello).
- **Deletions comandi**: togliere il ramo `from neuron.gui import main` (fallback Tkinter) da `neuron/__main__.py`; aggiornare la docstring del comando `gui`.

## 3. Logs

- **Console webgui**: buffer `deque(maxlen=_MAX_LOG=4000)`, drenato da `poll_log` ogni 400ms; ogni riga taggata (`_tag_of`: err/warn/ok/cmd). `clear_log` svuota. **Pulsante Copia** (fatto) esporta tutta la trace.
- **Streaming comandi**: `_stream` cattura stdout+stderr riga per riga → console. Dopo il refactor dei pannelli via CLI, anche config/repair passano da qui → **log uniformi** (oggi i pannelli in-process non loggano nella console allo stesso modo). Miglioramento gratuito.
- **Bootstrap gray_matter da `<tool> gui`**: l'install va streamato/visibile (non silenzioso), sia in console che in terminale se serve.
- **Log del daemon GM**: `paths.logs_dir()` (separato dalla console GUI). In standalone senza daemon, i comandi girano one-shot: nessun log daemon, solo console.

## 4. Trace (visibilità errori)

- **Errori tool strutturati**: il worker ritorna `{ok, error, trace}`; il gateway li propaga; la webgui li mostra rossi (`l-err`). La Copia serve proprio a mandarli.
- **DB corrotto / Turso degradato**: già riportati in `status`/`health`/`doctor` (`corrupt`, `turso_degraded`/`turso_errors`) → visibili in console via i comandi. Nessun crash muto.
- **Register/deregister standalone**: gli errori dei client-writer (`clients.py` Result) vanno superficializzati in console con il dettaglio (già fanno backup + verify).
- **Refactor pannelli**: passando per CLI, gli errori diventano righe di console taggate invece di eccezioni Python in-process — trace più leggibile e copiabile.

## 5. Readiness (è su? può servire?)

- **Porta dinamica + rendezvous**: daemon scandisce da 9876, scrive `<GM_HOME>/port`; client (`resolve_port`) seguono; singleton via probe `ping`→`gm:true`. La webgui NON richiede il daemon per **disegnare** il catalogo (legge i pacchetti installati), ma le azioni IPC (`status`/`stats`) sì.
- **Standalone senza daemon GM**: catalogo + `run` di comandi one-shot funzionano; i pannelli che oggi fanno IPC (status/process via daemon) devono **degradare con grazia** (mostrare "daemon non attivo" invece di errore). Da verificare nel refactor.
- **Avvio webgui**: `loadCatalog()` con retry (1.5s) se il backend non risponde; `poll()` loop. Nessuna pagina bianca.
- **Bootstrap readiness**: dopo self-install di gray_matter, la GUI deve (ri)caricare il catalogo (già `setTimeout(loadCatalog, 4000)` dopo install_env — riusare lo stesso pattern per il bootstrap).
- **Discovery tool**: `find_spec` per-tool → un tool presente compare anche senza gray_matter. `paths.discover_sources()` (per repair/reinstall) chiede ai peer.

## 6. Responsiveness

- **Pannello Processi**: `render()` lo ricarica a OGNI render (ogni click sul tool) → `tasklist` per pid. Ora è **senza flash** (CREATE_NO_WINDOW aggiunto), ma **spawna comunque `tasklist` a ogni click** → latenza/spreco. **Consigliato**: debounce/cache (es. cache 2-3s del risultato, o caricamento on-demand solo quando la card Processi è aperta, come config/repair).
- **Async**: `call()` è async; `_stream` gira in thread daemon → UI non blocca. Mantenere: il refactor dei pannelli via CLI deve restare non-bloccante (usare `_stream`, non chiamate sincrone lunghe nel thread Api).
- **Poll**: 400ms per la console; catalogo cache lato JS (`CATALOG`), non rifetchato al click (il click è pure JS render). Confermato: il click non chiama il backend TRANNE i pannelli auto-load (Processi, e config/repair quando aperti).
- **pywebview vs browser**: nessuna differenza logica; il browser aggiunge latenza HTTP trascurabile.

---

## 7. Sequenza di rollout (ordine sicuro)

1. **Refactor pannelli → API/CLI** (`webgui.py` config/repair/uninstall/process): rimuovere gli import diretti di `gray_matter.executor/paths/clients/settings`; usare `run`/comandi CLI dei tool. Isolare l'unica utility OS (tasklist) dietro una funzione con `CREATE_NO_WINDOW`.
2. **`<tool> gui` + bootstrap**: ogni tool lancia la webgui canonica; se gray_matter manca, self-install (extra `[gui]`), poi rilancia + reload.
3. **Solo ORA cancellare la Tkinter**: `neuron/src/neuron/gui.py`, entries `neuron-gui` in `pyproject` (scripts + gui-scripts), fallback in `__main__.py`, docstring; e lo shim `gray_matter/gui.py` se inutilizzato. Rimuovere eventuali asset Tkinter orfani.
4. **Flash-fix residui** (task originale, ancora aperto): `neurag/db.py:386` (pip pyturso, mia dimenticanza), `neurag/clients.py` (runner + claude CLI), `neuron/clients.py` (runner + claude CLI + taskkill 673; la riga `ps` 656 è Unix, niente flag), `neuron/bridge.py:143` (probe `--version`). Pattern: `_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0`; per il pattern `run = runner or subprocess.run` NON aggiungere `creationflags` al call-site (rompe i runner iniettati dai test) — definire un default runner che inietta il flag solo quando `runner is None`.
5. **Responsiveness**: debounce/cache del pannello Processi.
6. **Bump + changelog** nei repo toccati; verifica.

## 8. Verifica (static, sandbox `PYTHONPATH=neurag:gray_matter:neuron/src`)

- `py_compile` su tutti i file toccati; `bash -n` sugli `install.sh`.
- `catalog.environments()`: 3 ambienti, 0 errori, `gui`/`repair`/`register`/`deregister` presenti, `record-*`/`gui` gestiti in HIDDEN dove serve.
- **Decoupling**: `grep "from gray_matter" webgui.py` → dopo il refactor deve restare SOLO `catalog` e `__version__` (il minimo per disegnare), non più executor/paths/clients/settings.
- **Standalone**: rimuovere gray_matter dal PYTHONPATH e verificare che `neuron`/`neurag` importino e che `<tool> gui` prenda il ramo bootstrap.
- **Flash**: re-scan `tasklist|taskkill|claude|turso|pip install` senza `creationflags` nei path GUI → vuoto.
- Locale (utente): GUI reale da ogni tool, con e senza gray_matter, bind porta, register/deregister, repair.

## 9. Versioni (a fine lavoro)
Bump patch/minor dei repo toccati (GM per il refactor pannelli + flash; NeuRAG/Neuron per clients flash + gui + rimozione Tkinter). Ricorda: `pyproject` + `__init__` combacianti, o l'installer salta il reinstall.

## 10. Rischi / cose da non dimenticare
- Non cancellare la Tkinter prima del bootstrap (buco GUI in standalone).
- Il pannello Processi che spawna `tasklist` a ogni render: nasconderlo NON basta per la responsiveness — va debounced.
- Runner-injection nei `clients.py`: il flag va nel default runner, non nei call-site (test).
- Alcuni tool non espongono tutte le chiavi config via CLI: il pannello si adatta (card assente), non assumere `config` ovunque.
- Degrado grazioso dei pannelli IPC quando il daemon GM non è attivo (standalone).
- Extra `[gui]`: aggiungere a `neuron`/`neurag` pyproject; vendorare il wheel gray_matter se si vuole install offline (coerente col vostro `--find-links vendor`).
