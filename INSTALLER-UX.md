# INSTALLER & UX — Architettura di deploy del trio

> SSOT del deploy: modello di registrazione, path per-OS, install manifest,
> flussi install/uninstall/scan, superficie comandi/tuning.
> Sibling di `GRAY-MATTER-COMPENDIUM.md` / `ARCHITETTURA.md` / `ENVIRONMENT.md`.
> Creato: 2026-07-18.

---

## 1. Modello: Gray Matter come gateway (proxy) — un solo connettore

In MCP l'LLM vede **solo i tool che il server connesso gli dichiara**; non parla
mai coi processi direttamente. Quindi:

- Il client MCP connette **un solo** server: **Gray Matter**.
- GM dichiara i propri tool (`pulse`, `status`, `bridge`) **e ri-pubblica** quelli
  di Neuron e NeuRAG (pass-through). Per l'LLM sono tutti "tool di GM".
- Quando l'LLM chiama `store_turn`/`knowledge_query`/…, **GM inoltra** la chiamata
  al **worker** del sotto-server (canale stdin/stdout già esistente, `_worker.py`),
  ne prende il risultato e lo ritorna.
- Neuron e NeuRAG girano come **processi SUB gestiti da GM**, NON come connettori
  del client. GM è insieme *server MCP* verso il client e *gestore* dei worker.

Immagine: GM è una ciabatta — l'LLM attacca una spina sola (GM), gli altri tool
sono dietro a GM. Li usa tutti, ma *attraverso* GM.

**Chiave di volta — F12 (bloccante).** Un tool proxato è usabile solo se l'LLM ha
nome + descrizione (GM già li passa) **e lo schema argomenti**. Oggi GM passa lo
schema **vuoto** → il modello non sa cosa passare. F12 = GM interroga ogni worker
via `list_tools`, ottiene gli schemi reali e li ripubblica. Finché F12 non è fatto,
il modello "solo GM" NON è utilizzabile → transitoriamente si tengono i tre
registrati.

**Trade-off.** GM diventa single point of failure (muore GM → spariscono i tool).
Mitigazioni: GM respawna i worker; il client rilancia GM all'avvio; `doctor` di
autoriparazione. In cambio: connettore unico, orchestrazione (`pulse`, cache,
flash, bridge), "GM deployabile a prescindere".

**Cosa registrare nei client MCP:** → **solo Gray Matter** (target, dopo F12).

**Self-bootstrap (implementato 2026-07-18).** Poiché col gateway il client lancia
solo GM, i sotto-server non si auto-registrano più via IPC. GM li **auto-scopre**
(`detect_subservers`), li registra come **managed** (`register_managed`, vivi senza
heartbeat) e ne carica i tool dal worker (F12). Cablato in `main()` (`_bootstrap_subservers`);
l'`heartbeat_monitor` ignora i managed. Verificato (registry) — 6 check verdi.
**Resta (locale):** flip della registrazione client = CLI `gray-matter register --gateway`
(registra SOLO gray_matter + deregistra neuron/neurag) poi restart dei client.

---

## 2. Deploy: GM è il centro, bundle-ato da ogni tool

- Scarichi **Neuron** → il suo installer installa **Neuron + Gray Matter**.
- Scarichi **NeuRAG** → il suo installer installa **NeuRAG + Gray Matter**.
- GM è **condiviso e idempotente**: se già presente, non lo si reinstalla — lo si
  riusa/aggiorna. Un solo GM per macchina.
- Output: nella cartella d'install, l'**eseguibile GM per l'OS in uso** (il command
  center). GM funziona anche con **un solo** sotto-tool installato (`pulse` gestisce
  già i server assenti).

---

## 3. Path SSOT per-OS

**UNA regola per-OS**, ripetuta identica in ogni modulo che risolve path
(`neuron/config.py`, `neuron/paths.py`, `neuron/project.py`, `neuron/tunnel.py`,
`neurag/paths.py`, `gray_matter/paths.py`, `gray_matter/gme.py:user_base()`):

```
Windows        %LOCALAPPDATA%
macOS / Linux  $XDG_DATA_HOME, altrimenti ~/.local/share
```

> **macOS non usa `~/Library/Application Support`** — scelta consapevole
> (2026-07-29). Era la convenzione Apple e `gme.py` la seguiva, ma era l'UNICO
> posto: gli altri sei risolvevano `~/.local/share`. Risultato su Mac: registro
> dei tool in `Library`, tutti i DATI in `.local/share`, e `tunnel.json` scritto
> nella cartella `GrayMatterEnvironment` sbagliata. Una radice sola vale più
> della radice più idiomatica. `gme_root()` continua a leggere un registro
> `Library` preesistente (l'installato vince), quindi nessun Mac perde nulla.

| Cosa | Windows | macOS / Linux |
|---|---|---|
| Registro tool (GME) | `%LOCALAPPDATA%\GrayMatterEnvironment\<tool>.json` | `<base>/GrayMatterEnvironment/<tool>.json` |
| Venv condiviso | `%LOCALAPPDATA%\gray-matter\.venv` | `<base>/gray-matter/.venv` |
| Data: grafo Neuron | `%LOCALAPPDATA%\neuron\graphs` | `<base>/neuron/graphs` |
| Data: DB NeuRAG | `%LOCALAPPDATA%\neurag\knowledge.db` | `<base>/neurag/knowledge.db` |
| Settings NeuRAG | `…\neurag\config.json` | idem |
| Data: bridge GM | `…\graymatter\bridges.db` | idem |
| Config/knob GM | `…\graymatter\config.json` | idem |
| Log | `…\graymatter\logs\` | idem |
| Install manifest | `…\graymatter\manifest.json` | idem |
| Config tunnel | `…\GrayMatterEnvironment\tunnel.json` | idem |
| Marker progetto | `<project>/.neuron/project.json` | idem |
| Config client MCP | vedi `clients.py` (6 client) | idem |

> Lo slug è **`neuron`**, non `neuron5`: `neuron5` è ritirato e sopravvive solo
> nei path che lo riconoscono come legacy (`test_installer_parity.py` fallisce
> se ricompare in un installer).
>
> NeuRAG scriveva `~/.local/share/neurag` su OGNI OS, Windows compreso — fuori
> da `%LOCALAPPDATA%`. Allineato il 2026-07-29 con la stessa regola
> "l'esistente vince": un vault già presente nella vecchia posizione continua a
> essere usato lì, nessuno spostamento automatico di un DB potenzialmente aperto.

Regola: **dati** (grafo/DB/bridge) separati da **codice** (binari/venv). L'uninstall
li tratta diversamente (§6).

---

## 4. Install manifest — il registro di cosa/dove

Senza manifest, l'uninstall è a indovinare. Un JSON scritto dall'installer:

```json
{
  "schema": 1,
  "installed_at": "2026-07-18T..",
  "components": {
    "gray_matter": {"version": "…", "app_dir": "…", "exe": "…"},
    "neuron":      {"version": "…", "data_dir": "…", "slug": "neuron5"},
    "neurag":      {"version": "…", "db": "…"}
  },
  "clients_registered": ["claude-desktop", "claude-code", "cursor", "vscode", "opencode", "codex"],
  "python": "C:\\Python314\\python.exe",
  "pids_file": "…\\graymatter\\pids.json"
}
```

L'uninstall legge il manifest e rimuove **esattamente** ciò che è stato scritto.

---

## 5. Flusso install (idempotente, GM-centric)

1. **Mode selector** (solo interattivo, non `--no-gm` / `-Force`):
   - **Full suite** (default, Invio) — GM + Neuron + NeuRAG
   - **Solo Neuron/NeuRAG** — standalone, si registra direttamente nei client
   - **Dettagli** — mostra cosa si perde senza GM, poi chiede di nuovo
2. **Rileva** install esistenti (manifest, data dir, entry nei client, processi).
3. **Termina** eventuali processi orfani prima di scrivere (evita lock Windows +
   più writer sullo stesso store).
4. Installa il tool richiesto (Neuron o NeuRAG) nel proprio data dir.
5. **Assicura GM**: se assente installa, se presente aggiorna (mai duplicare).
6. **Registra SOLO GM** nei client MCP (`clients.py`); GM terrà i worker.
7. Scrive/aggiorna **manifest** + **pids**.
8. `doctor` finale: verifica registrazione e avvio.

---

## 6. Flusso uninstall (INTERATTIVO sui dati) + legacy scan

Decisione: **chiedi sempre** prima di toccare la memoria utente.

1. **Termina** i processi del trio (dal pids/manifest; fallback: scan per nome).
2. **Deregistra** dai client MCP (`deregister_all`, già in `clients.py`).
3. **Rimuovi codice/binari/venv** (dal manifest).
4. **Dati (grafo/DB/bridge): CHIEDI** — "Conservare la memoria? [conserva/elimina]".
   Default nessuna cancellazione senza risposta esplicita.
5. **Legacy scan** (`--deep`): cerca e segnala artefatti di vecchie install —
   - slug vecchio `neuron` (vs `neuron5`) e relative data dir;
   - vecchio nome **Neural-Stimulus** (assente nel repo attuale → solo residui su
     disco/PC ospite);
   - script su PATH, entry di config stantie nei 6 client, processi orfani;
   - li elenca; `--purge` per rimuoverli previa conferma.
6. Rimuove manifest per ultimo.

---

## 7. Processi — singleton e reap

- Un **pids.json** traccia i PID di GM + worker.
- All'avvio GM: se esiste già un GM sano sulla porta IPC, non ne parte un secondo.
- `gray-matter doctor` rileva processi orfani (come i **4 Neuron** visti il 2026-07-18)
  e offre di terminarli. Funzionale, non solo igiene: più server sullo stesso store
  = rischio clobber (lega a L1).

---

## 8. Superficie comandi / tuning ("sensibilità")

Le CLI ci sono già — Neuron (`setup/manage/doctor/register/consolidate/console/
connect/bridge/tunnel/gui`), GM (`status/stats/doctor/start/stop/isolate/
collaborate/mode/register/bridges/gui`). Il centro di comando **unifica** il
controllo dei tre sotto GM, più:

- **Config unico** (`…/graymatter/config.json`) per i knob oggi sparsi come
  costanti/env: flash rate (`FLASH_MIN_GAP`), cache TTL/size, cadenza `consolidate`,
  soglie salience; poi pesi trust/decay quando arriva B.
- Comandi: `gray-matter config get|set <chiave> [valore]`, `gray-matter install|
  uninstall|scan`, editabili anche da GUI. Niente edit del codice per il tuning.

---

## 8b. Hook & plugin — il layer handshake (per-client, NON lo fa GM)

Distinzione fondamentale, due lavori separati:

- **Routing + schemi dei tool → GM** (il proxy, F12). Questo lo fa tutto GM.
- **Handshake di sessione → hook/plugin, per-client.** Iniettano la loop-guidance
  ("chiama `pre_turn` prima, `store_turn` dopo") all'avvio della sessione. GM **non
  può** farlo: gli hook scattano nel client attorno al prompt, non dentro il canale
  MCP. Un server MCP può solo offrire `instructions` all'handshake — che alcuni
  client mostrano e altri ignorano: è *per questo* che esistono gli hook.

Cosa c'è già (in `Neuron/clients/`), da riusare:

| Client | Meccanismo handshake |
|---|---|
| Claude Code / Cowork | SessionStart hook + plugin `neuron-guard` (`hooks/hooks.json`) |
| OpenCode | plugin `neuron-handshake.mjs` (`experimental.chat.system.transform`) |
| Cursor / VS Code / Codex | `instructions` MCP servite dal server (nessun hook separato) |

**Implicazioni del passaggio a "solo GM":**

1. Gli hook/plugin **restano** (layer per-client) — non spariscono in GM.
2. Il loro **deploy passa all'installer unificato** di GM (oggi lo fa quello di
   Neuron); l'**uninstall** li rimuove per-client (`scripts/uninstall.ps1` ha già
   il wipe granulare plugin/hook — base buona).
3. **GM serve le `instructions`** all'handshake MCP: così i client che le onorano
   non hanno bisogno di hook; l'hook resta solo per quelli che le ignorano.
4. **Contenuto**: minima revisione del testo per riflettere il modello GM-gateway
   (i nomi dei tool del loop restano `pre_turn`/`store_turn`, quindi cambio minimo).
5. Il **manifest** (§4) registra hook/plugin deployati per client → l'uninstall sa
   esattamente cosa togliere.

Riassunto per la domanda "lo fa tutto Gray?": **no.** GM fa routing e schemi; gli
hook/plugin restano un layer per-client, ma li **consolidiamo sotto l'installer di
GM** e li tracciamo nel manifest.

## 9. Priorità (ordine per dipendenze)

| # | Passo | Perché in quest'ordine | Dove |
|---|---|---|---|
| 1 | **Questa spec** (SSOT) | Allinea il modello prima di scrivere codice | ✅ questo file |
| 2 | **F12** — schemi reali pass-through | Chiave di volta del "solo GM": senza, il modello target è inusabile | Neuron/NeuRAG + GM, **locale** |
| 3 | **paths.py + manifest** | Struttura dati su cui poggiano install E uninstall | GM · ◐ `paths.py` + `Manifest` (path per-OS, componenti, client, hook) + 8 test verdi (2026-07-18); resta `pids`/wiring |
| 4 | **Installer** GM-centric idempotente | Registra solo GM, scrive manifest, singleton processi | ◐ `installer.py`: `plan()` puro (reap→ensure_data→install→register-solo-gateway→manifest) + `record_install`, 6 test verdi (2026-07-18). Resta parte effettful (reap/spawn/register) **locale** |
| 5 | **Uninstaller + legacy scan** | Interattivo sui dati; usa manifest + `deregister_all` + reap | ◐ `uninstaller.py`: `plan()` puro (reap→deregister→remove_hook→remove_code→**ask_data**; `purge_data` per wipe) + `legacy_scan_plan` (old_slug/old_name/PATH/stale_client/orphan_procs), 7 test verdi (2026-07-18). Resta parte effettful **locale** |
| 6 | **Config unico + command center** | Tuning/sensibilità senza toccare codice; unifica le CLI | ✅ `settings.py` + `gray-matter config get\|set\|list` (5 test) + **`server.py` legge i 5 knob** (flash_min_gap, cache ttl/size, prewarm, heartbeat, idle) da config al restart (2026-07-18). Resta solo: deploy hook/plugin nell'installer |

> Nota ambiente: F12/installer/uninstaller vanno **verificati in locale** (server
> reali, 6 client, processi) — nel sandbox si scrive e si fa check statico, non si
> garantisce (regola `ENVIRONMENT.md`).
