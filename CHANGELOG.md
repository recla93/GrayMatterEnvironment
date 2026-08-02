# Changelog — Neuron

## 6.3.0 (2026-08-02)
- **Seed knowledge rigenerato dall'intero ecosistema** (`base_knowledge.db`:
  27 → 1130 nodi, 1525 link). Il seed precedente (10/07) conteneva solo la
  documentazione interna dei tool e copriva una Neuron che non esiste più:
  mancavano `dismiss`, `recall`, `introspect`. Ora il seed è la mappa completa
  di Gray Matter Environment — architettura, flussi, ADR, bug noti e risoluzioni
  di gray_matter, neurag e Neuron stesso — costruito da
  `scripts/import_vault.py` sul workspace dev con i grafi graphify dei tre repo.
  Conseguenza pratica: un grafo nuovo fa warm-start dal seed e un client "sa" chi
  è l'ecosistema senza aver mai letto i README.
- **Embedding del seed allineati al runtime (ADR-001)**. `import_vault.py`
  generava i vettori con `all-MiniLM-L6-v2` (solo EN) mentre il server usa
  `paraphrase-multilingual-MiniLM-L12-v2` (EN+IT): il seed nasceva con vettori
  di un modello diverso, scartati e ricalcolati a ogni avvio (spazi vettoriali
  non confrontabili). Lo script ora legge `NS_EMBED_MODEL` con lo stesso default
  del runtime — una sola env governa la suite, come già fatto per NeuRAG.
- **`import_vault.py` ignora i contenitori tecnici** (`.venv`, `build`, `vendor`,
  `handoff`, caches): prima scannerizzava anche il `.venv` del repo, portando
  nel seed nodi da `site-packages` estranei.


- **Un archivio corrotto ora dice cosa fare** (`db.corrupt_store_hint`). Un
  `graph.db` malformato arrivava come `DatabaseError: file is not a database` in
  cima a un traceback: il sintomo, senza il file e senza un rimedio. È lo stesso
  vicolo cieco che NeuRAG ha chiuso nella 1.1.1 e che questo lato non ha mai
  ricevuto, pur essendo il gemello keep-in-sync di quel `db.py`.
  `corrupt_store_hint` riconosce le varie grafie della corruzione — quale ti
  tocca dipende dal tier che ha aperto il file (pyturso o sqlite3) e da quanto
  header è stato letto — e restituisce una frase con causa e recupero;
  `server.call_tool` la mette **prima** del traceback, che resta sotto perché è
  l'unica telemetria che attraversa worker → GM → client.
  Un hint e non una classe di eccezione: un `Graph` viene caricato e salvato da
  molti punti, e `call_tool` incanala già ogni errore in testo, quindi
  classificare al confine cambia un posto invece di trenta. Il classificatore è
  volutamente stretto: dire "archivio corrotto" a chi ha solo una cartella
  mancante lo manda a cancellare la cosa sbagliata.
  Verificato end-to-end su un file davvero rotto, non solo sulle stringhe
  (`tests/test_corrupt_store.py`).
  Nota: `save_sqlite` **alza** su un archivio corrotto — controllato apposta,
  perché un salvataggio che riporta successo senza scrivere sarebbe perdita di
  memoria silenziosa. Il `return` anticipato che si vede a mano è il guard
  "graph non dirty", non un errore ingoiato.
- **Un `;` dentro un commento SQL non può più troncare uno schema**
  (`db.py:_split_sql`). Il client remoto non ha `executescript`, quindi
  `RemoteTursoConnection` taglia lo script su `;` a mano: un punto e virgola
  dentro un `--` spezzava la statement che lo conteneva e il motore riceveva
  "incomplete input", con una tabella mancante in silenzio. Gli schemi di Neuron
  non hanno commenti SQL, quindi qui non era mai scattato — è scattato in NeuRAG,
  il cui `db.py` è la porta keep-in-sync di questo file, appena qualcuno ha
  commentato una colonna. Difetto latente, cioè in attesa di chi documenta una
  colonna: sistemato su entrambi i lati perché il prossimo che copia copi il fix.
  Test: `tests/test_sql_script_split.py`, che fa passare anche gli schemi veri
  di `models.py`/`engine.py` attraverso lo splitter vero.

## 6.1.2
- **GUI Tkinter ritirata**. Cancellato `src/neuron/gui.py` e le entry
  `neuron-gui` da `[project.scripts]`/`[project.gui-scripts]`: `neuron-gui.exe`
  non viene più generato. Il control center è UNO, la webgui condivisa di Gray
  Matter. Rimosso il fallback `from neuron.gui import main` in `__main__.py`.
- **`neuron gui` bootstrap reale**: se Gray Matter manca, lo installa nello
  stesso venv (cartella sorella in dev, poi indice pip) streamando il progresso,
  poi apre — niente più GUI separata né install muto.
- **`repair --json`**: elenca la superficie cancellabile (`--wipe-memory`) con
  path/stato, per il pannello Repair del control center.
- **Guard su `neuron register`**: se GM è presente e gestisce ancora Neuron (non è
  in `unmanaged`), il register DIRETTO si rifiuta (eviterebbe una doppia
  registrazione nei client) e indirizza a `neuron go-standalone` (register +
  release atomico) o `gray-matter deregister neuron`. Bypass: `--force`. Senza
  GM (standalone puro) nessun guard. `go-standalone` non passa dal guard.
- **Bootstrap GM — wheel d'emergenza OFFLINE**: `neuron gui` prova cartella
  sorella (dev) → **wheel GM vendorata nel package** (`neuron/_gm_vendor/*.whl`,
  install `--find-links` senza rete: GM ha solo `mcp` come dep, già presente) →
  indice pip → `git+https://github.com/recla93/gray-matter`. La wheel va
  ricostruita a ogni release di GM (vedi RELEASE-CHECKLIST).
- **Icona desktop "Neuron"** (launcher standalone): l'installer standalone la crea
  già a fine install (`neuron gui --shortcut-only`) e `neuron gui` la ri-assicura
  a ogni apertura. Logica in `neuron/shortcut.py` (copia tool-local cross-OS,
  keep-in-sync con `gray_matter/shortcut.py` — serve senza GM). L'icona punta a
  `neuron gui`, che bootstrappa GM al primo click. Idempotente (marker nel venv).

## 6.1.1
- **Fix flash CMD (Windows)**: `clients.py` (register/deregister via `claude` CLI,
  `_list_processes` PowerShell, `_default_killer` taskkill) e `bridge.py` (probe
  `mcp-proxy --version`) ora usano `CREATE_NO_WINDOW`. Il flag è nel runner di
  default, così i runner iniettati dai test non ricevono `creationflags` a forza.
- **Extra `[gui]`** = `gray-matter`: il control center è UNO (`gray_matter.webgui`);
  `neuron gui` lo bootstrappa se manca. Il runtime MCP resta indipendente da GM
  (import guardato) — verificato: Neuron importa e gira con gray_matter assente.

## 6.1.0
- **`neuron go-standalone`**: Neuron esce dal gateway GM — si registra come MCP
  diretto nei client col PROPRIO engine (`clients.register_all`) e chiede a GM
  (se presente) di non gestirlo più (`gray_matter.clients.release_tool`,
  persistente + IPC best-effort). L'entry `gray-matter` nei client resta finché
  un peer è ancora gestito da GM. Reversibile: `gray-matter register --gateway`.
- **Guardia autoregister**: il server NON si ri-registra al gateway se Neuron è
  in lista `unmanaged` (niente tool pubblicati due volte).
- **GUI universale**: `neuron gui` apre il control center condiviso
  (`gray_matter.webgui`) quando GM c'è; senza GM degrada alla Tkinter storica.
- **Repair puntuale**: `neuron repair` stampa (o lancia con `--reinstall`) il
  PROPRIO installer con `--force`, risolto dai path registrati
  (`paths.source_dir()`).
- **Installer `--force`**: `install.ps1 -Force` / `install.sh --force` —
  reinstall forzato del pacchetto Neuron anche a versione invariata (pattern di
  gray_matter, inoltrato anche al GM installer).

## 6.0.3
- **Path SSOT (Neuron possiede i suoi path)**: nuovo `neuron/paths.py` — fonte
  di verità delle location Neuron (`graphs_dir` delega a `config`, `data_dir`,
  `source_dir`). Gray Matter li SCOPRE via `neuron.paths` invece di hardcodarli.
- `neuron record-paths --source <dir>` + comando `repair` (reinstall pulito
  scope-Neuron): Neuron registra il proprio sorgente per repair/reinstall.
  Entrambi nascosti dal control center dove serve.

## 6.0.1
- Bump di release: la 6.0.0 installata prima del refactor `COMMANDS` in
  `__main__.py` esponeva 0 subcomandi al catalogo del control center (GUI con
  la sezione Neuron vuota). Nessun cambio di codice: serve solo a far
  reinstallare il pacchetto dall'installer, che salta le versioni identiche.

## Unreleased

### Fix da audit OpenCode (2026-07-21)
- `_env.py`: `.env` letto con `utf-8-sig` (BOM di PowerShell 5.1 corrompeva la
  prima chiave). Keep-in-sync con `gray_matter/_env.py` e `gray_matter/cloud.py`.
- `install.ps1`/`install.sh`: nel fallback PyPI, exit solo su successo di
  `gray-matter install` — un install del gateway fallito ora degrada a
  standalone (§6) invece di terminare (fix dell'audit su NeuRAG, specchiato).

### Installer — GM opt-out (consenso informato, DESIGN-CLOUD-MEMORY §6)
- `install.sh`/`install.ps1`: Gray Matter non è più forzato — prompt
  `Install Gray Matter (recommended)? [Y/n]` con il deficit esplicito (senza GM
  si perdono solo bridge cross-store e auto-surface dei vicini). Headless:
  `--no-gm` / `GM_OPTIN=0`. Rifiuto → install STANDALONE (venv proprio,
  `neuron register --client all`). GM non ottenibile (offline) → degrada a
  standalone invece di uscire. Reversibile ri-eseguendo senza `--no-gm`.

## v6.0.0 (2026-07-21)

Prima release pubblica dell'era gateway. Consolida il lavoro 5.5.x–5.6.0 (trust +
refs table, prune dry-run, gateway GM-only, installer unificato). Bump a major per
la prima distribuzione stabile e taggata; nessun cambiamento di comportamento
rispetto a 5.6.0.

## v5.6.0 (2026-07-20)

### Gateway flip
- `gray-matter register --gateway` evicts neuron/neurag from all clients, registers only GM
- Singleton daemon via exclusive bind on :9876 (`SO_EXCLUSIVEADDRUSE`)
- Stdio handshake fixed: `InitializationOptions` now includes capabilities + GM instructions
- GM serves 32 tools via pass-through with real schemas (F12)

### Trust system (B1-B3)
- `Node.trust: float` column (REAL DEFAULT 0) with atomic delta `MAX(0, trust + ?)`
- `confirm(confidence)` tool: boosts trust, propagated in merge/dedup
- Trust integrated into ranking weights

### Refs table (G2)
- New `refs` table (context, keyword, path, project_id, by) with natural PK
- `store_turn` canonical refs + merge on revisited nodes + `files:` line in `pre_turn`

### Project system (G3)
- `project.py`: `.neuron/project.json` marker, relative paths, provenance tracking

### Installer unification
- Canonical install via `install.ps1` / `install.sh` delegating to GM
- `uninstall.sh` simplified
- INSTALL-AI.md (EN) + INSTALL-AI.it.md (IT) added

### Fixes
- F3: `reset` requires `confirm=true` (v5.4.2)
- F4: `prune` now has `dry_run` support
- F5: `dedup` toggle with explicit enable option
- F10: POSIX bashisms fixed in installer scripts
- G1: File refs canonicalized in `store_turn`

### Cleanup
- Removed `MINIMAX-BRAINSTORM.md` and `install-gui.sh`

## v5.5.0 (2026-07-18)

- Optional GM autoregister (opt-out `NEURON_NO_GM`)
- Forgotten `near=` mid-band serendipity selector (flash v2)

## v5.4.2 (2026-07-18)

- Reset requires confirm + dedup explicit enable
- POSIX sh launcher + macOS pipx shortcut
