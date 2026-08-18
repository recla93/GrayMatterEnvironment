# Handoff → Claude Code (LOCAL) — GUI universale: refactor pannelli → API + rimozione Tkinter

**Da eseguire in locale con Claude Code**, nel repo `Gray Matter Enviroment/` (venv reale). Il motivo di farlo qui e non in Cowork: questo blocco si **valida solo eseguendo** (GUI WebView2/pywebview, click reali, install `-Force`, register/deregister sui config veri, bind porta). Static-check non basta.

Leggi prima: `DESIGN-GUI-UNIVERSALE-2026-07-22.md` (decisione + audit flussi) e `HANDOFF-STANDALONE-2026-07-22.md` (contesto standalone). Questo doc è operativo.

---

## 0. Setup locale (fai PRIMA, una volta)

L'installer **salta il reinstall se la versione sorgente == installata** (gate in `install.ps1`/`.sh`). In sviluppo → **editable install** per evitare "la GUI resta vecchia":

```
<venv>\Scripts\python -m pip install -e .\gray_matter -e .\neurag -e .\neuron
```

Così ogni modifica è live senza bumpare. (Per i rilasci veri: bump `pyproject`+`__init__` combacianti.)

## 1. Stato attuale (NON rifare)

Versioni: **GM 1.1.x · NeuRAG 1.2.1 · Neuron 6.1.1**. Già fatto/verificato (static):
- **Path SSOT/SoC**: `neurag/paths.py`, `neuron/paths.py`, GM delega+scopre. `record-paths`/`record-env`.
- **Porta dinamica** + rendezvous (`resolve_port`, `<GM_HOME>/port`, probe `ping`).
- **Repair** scoped (GM + `neuron repair` + `neurag repair`), caselle default spente.
- **Standalone runtime**: Neuron/NeuRAG importano e girano **senza gray_matter** (import GM guardato, non tra le deps). Extra `[gui]=gray-matter` aggiunto a entrambi.
- **Flash CMD** guardati (`CREATE_NO_WINDOW`) in: `gray_matter` (executor/webgui/clients/cloud), `neurag` (db pip pyturso, clients), `neuron` (clients powershell/taskkill, bridge probe). Pattern runner-injection: flag nel **default runner**, non nei call-site (non rompere i test).
- **Click & run** presenti in tutti i repo (`install.cmd/.command/.sh/.ps1`) — NON romperli.

## 2. Il lavoro, in ORDINE SICURO

### A. Refactor pannelli webgui → API/CLI (togliere gli import di gray_matter interni)

Problema: in `gray_matter/webgui.py` i 4 pannelli speciali importano gli **interni** di GM invece di passare per la via generica API (`Api.run` → `python -m <tool>.cli <cmd>`). Righe (circa): `config_knobs`/`config_set` → `settings`; `repair_state`/`repair_run` → `executor`,`paths`; `uninstall_state`/`uninstall_run` → `executor`,`clients`; `process_list`/`process_stop` → `executor`.

Obiettivo: dopo il refactor, `grep "from gray_matter" webgui.py` deve restare **solo** `catalog` e `__version__`.

Come, pannello per pannello (i tool ESPONGONO GIÀ i comandi):
- **Config** → chiama `<tool> config list|get|set` via subprocess. Consiglio: aggiungi un flag `--json` a `config list` nei tool (NeuRAG ce l'ha come knobs; GM idem) per un parsing robusto invece di leggere testo.
- **Repair** → chiama `<tool> repair ...` (esiste in tutti e tre). Le card passano lo scope = env.key (già così lato JS).
- **Uninstall** → chiama `<tool> uninstall` / `<tool> deregister` (esistono).
- **Process** → è OS-level (tasklist) + pid del daemon GM: NON tool-agnostico. Due scelte, decidi testando: (a) mostrare il pannello Processi **solo** per scope `gray-matter`/quando GM è presente; (b) spostare i 3 helper pid (`_tracked_pids`/`_alive`/`_reap`) come funzioni self-contained dentro `webgui.py` (una sola, con `CREATE_NO_WINDOW`), senza importare `executor`. Preferisci (a) se vuoi il minimo: in standalone senza GM il pannello Processi non ha senso.

Regole: mantieni tutto **non-bloccante** (usa `_stream`, non chiamate sincrone lunghe nel thread Api). Gli errori diventano righe di console taggate (meglio del traceback in-process). L'unica utility OS residua (tasklist) sta dietro UNA funzione con `CREATE_NO_WINDOW`.

### B. `<tool> gui` → bootstrap gray_matter se manca

`neuron gui` e `neurag gui` devono: provare `from gray_matter.webgui import main`; se ImportError → installare gray_matter **nello stesso venv** (`sys.executable -m pip install gray-matter` o dal wheel vendorato / GitHub), streamando il progresso, poi rilanciare la GUI. Extra `[gui]` già dichiarato. Verifica che il ramo bootstrap sia completo e loggato (niente install muto).

### C. Rimuovere la GUI Tkinter — SOLO DOPO A+B

- Cancella `neuron/src/neuron/gui.py`.
- `neuron/pyproject.toml`: togli `neuron-gui` da `[project.scripts]` e `[project.gui-scripts]`.
- `neuron/__main__.py`: togli il fallback `from neuron.gui import main`; il comando `gui` deve puntare SOLO alla webgui condivisa; aggiorna la docstring.
- Rimuovi asset Tkinter orfani (icone usate solo dalla vecchia GUI).
- `gray_matter/gui.py` (shim `from gray_matter.webgui import main`): se `grep` non trova referenze → cancellalo; se è in uno shortcut, lascialo o redirigi.
- **Non** toccare `install.cmd/.command/.sh/.ps1` (i click&run restano).

### D. Responsiveness — pannello Processi

Oggi `render()` ricarica il pannello Processi a OGNI click (spawn `tasklist` ogni volta, ora nascosto ma sprecone). Debounce/lazy: caricalo **on-demand** quando la card è aperta (come config/repair), oppure cache 2-3s. Riduce latenza e spawn.

## 3. CHECKLIST TEST LOCALE (il vero motivo di stare in Code)

Windows (primario), poi mac/Linux se possibile:
1. `install.ps1 -Force` → reinstalla senza "already installed skip"; la GUI si apre.
2. Apri la GUI, **clicca Neuron e NeuRAG in sidebar**: NESSUN CMD deve lampeggiare (bug originale).
3. Apri ogni pannello: **Config** (toggle rerank su NeuRAG salva davvero), **Repair** (mostra scope giusto, default spento), **Processi**, **Uninstall** (dry/annulla). Nessun flash, nessun traceback in console; il pulsante **Copia** copia la trace.
4. **Register/deregister standalone**: `neurag deregister` / `neuron go-standalone` → verifica che l'entry compaia/sparisca nel config reale del client (Claude Desktop/Code) e che ci sia il `.bak`.
5. **GUI senza GM**: in un venv dove gray_matter NON è installato, `neuron gui` → deve bootstrapparlo e aprirsi. Poi `neurag gui` idem.
6. **Porta occupata**: occupa 9876 con un'altra app → il daemon deve prendere la porta successiva (log "porta … occupata → uso …") e i client seguirlo (`<GM_HOME>/port`).
7. **Turso**: su una macchina senza pyturso, `neurag doctor` → deve tentare le wheel e poi degradare documentando (nessun crash, nessun flash del pip).
8. Re-scan flash: nessun `tasklist|taskkill|claude|turso|pip` console senza `creationflags` nei path GUI.
9. Dopo la rimozione Tkinter: `neuron gui` funziona (via webgui), `neuron-gui.exe` non più generato, nessun import rotto (`python -c "import neuron.__main__"`).

## 4. Gotchas (non dimenticare)
- **Editable install** o **bump versione** a ogni giro, o la GUI resta vecchia (gate installer).
- **keep-in-sync**: `neurag/clients.py` è clone di `neuron/clients.py`; ogni fix in entrambi.
- **Runner-injection**: `creationflags` nel default runner, MAI nei call-site (rompe i test che iniettano un runner).
- **Non cancellare la Tkinter prima di A+B** (buco GUI in standalone).
- **Non toccare i click&run** (`install.cmd/.command/.sh`).
- **Degrado grazioso** dei pannelli che parlano col daemon quando GM non è attivo (standalone).
- Alcuni tool non espongono tutte le chiavi config via CLI → il pannello si adatta (card assente), non assumere `config` ovunque.

## 5. Chiusura
- `py_compile` tutto; `bash -n` sugli `.sh`; `catalog.environments()` 0 errori.
- `grep "from gray_matter" gray_matter/webgui.py` → solo `catalog` + `__version__`.
- Bump versioni dei repo toccati (pyproject+__init__ combacianti) + CHANGELOG.
- Aggiorna `GRAY-MATTER-COMPENDIUM.md` (sez. GUI/architettura) e `docs/` se serve.
