# PIANO D'AZIONE — Gray Matter Environment

> Ordine di intervento per release production. Nessuna stima temporale.
> Ogni fase dipende dalla precedente除非 esplicitamente marcata come indipendente.

---

## FASE 0 — Verifica stato attuale

Prima di toccare qualsiasi cosa, girare la suite completa sul tier reale.

```
# In locale, con pyturso installato
cd Neuron && pip install -e ".[dev,semantic]" && pytest -q
cd ../neurag && pip install -e ".[dev,semantic,pdf,docx,yaml]" && pytest -q
cd ../gray_matter && pip install -e ".[dev]" && pytest -q
```

**Output atteso:** 340+ test verdi, 0 fail.

Se qualcosa fallisce, fixare PRIMA di procedere. Il codice che parti è il codice che testi.

---

## FASE 1 — Fondamenta DB

> Blocca: senza questo, il DB perde dati sotto concorrenza.

### 1.1 File lock per `store_turn` (fix L2)

**Chain:** `neuron/db.py` → `gray_matter/_worker.py` → `gray_matter/server.py`

- [ ] Aggiungere `LockedConnection` in `neuron/db.py`
- [ ] Gestire platform-specific (msvcrt su Windows, fcntl su POSIX)
- [ ] Timeout lock con fallback a sqlite3 (già mitigato, rendere robusto)
- [ ] Rimuovere `_graphs.clear()` da `_worker.py` — connessione persistente
- [ ] Test: 2 processi che scrivono sullo stesso DB contemporaneamente
- [ ] Test: processo che crasha con il lock attivo — gli altri non restano bloccati
- [ ] Verifica su daemon vivo con pyturso reale

**Reference:** NEURON-Tasks.md → T4, PROBLEM-REGISTER → L2

### 1.2 UPDATE atomici salience (fix L1)

**Chain:** `neuron/models.py` → `neuron/db.py` → `neuron/server.py`

- [ ] Nuovo metodo `db.update_salience(node_id, delta)` con `MAX(0, salience + ?)`
- [ ] `Node.salience` diventa proprietà read-only (legge dal DB)
- [ ] Aggiornare tutti i punti in `server.py` che fanno `node.salience += ...`
- [ ] Aggiornare `models.py` — `Graph.add_link()` usa salience
- [ ] Test: 2 processi che aggiornano salience sullo stesso nodo
- [ ] Confrontare pattern con trust (già atomico) — allineare

**Reference:** NEURON-Tasks.md → T2

### 1.3 Verifica suite su Turso

- [ ] Girare `pytest` con pyturso attivo (non sqlite fallback)
- [ ] Verificare `test_vector_sql.py` (NeuRAG)
- [ ] Verificare `test_cloud_turso.py` (NeuRAG) con credenziali reali
- [ ] Verificare `test_l2_open_guard.py` (Neuron)
- [ ] Documentare eventuali fallimenti nel PROBLEM-REGISTER

---

## FASE 2 — Installer

> Prima thing che l'utente tocca. Se si rompe qui, perdi l'utente.

### 2.1 Architettura modulare

**File:** `installer/` (nuova cartella alla root del workspace)

- [ ] Creare `installer/install.py` — logica pura, zero subprocess
- [ ] Creare `installer/steps/python.py` — check/install Python
- [ ] Creare `installer/steps/venv.py` — create/verify venv
- [ ] Creare `installer/steps/deps.py` — pip install
- [ ] Creare `installer/steps/register.py` — MCP client registration
- [ ] Creare `installer/steps/hooks.py` — deploy hooks
- [ ] Creare `installer/steps/shortcut.py` — desktop shortcut
- [ ] Creare `installer/platform/windows.py` — Windows-specific
- [ ] Creare `installer/platform/macos.py` — macOS-specific
- [ ] Creare `installer/platform/linux.py` — Linux-specific
- [ ] Creare `installer/rollback.py` — rollback manager

### 2.2 Step interface

Ogni step implementa:
```python
class InstallStep:
    def check(self) -> bool       # Già installato?
    def install(self) -> bool     # Installa
    def verify(self) -> bool      # Verifica
    def rollback(self) -> bool    # Torna indietro
    def log(self) -> str          # Cosa ha fatto
```

- [ ] Definire interfaccia base
- [ ] Implementare per ogni step
- [ ] Test: ogni step isolato (mock subprocess)

### 2.3 Ordine di installazione

1. Python check → se manca, download binario (non da package manager)
2. Venv creation
3. pip install (tutti i progetti insieme)
4. GM registration (default on, opt-out)
5. Peer detection (Neuron? NeuRAG? Installa se manca)
6. Shortcut creation
7. Verify (run test base)

- [ ] Implementare sequenza
- [ ] Test: install pulito su Windows
- [ ] Test: riesecuzione (idempotenza)
- [ ] Test: install a metà + rollback

### 2.4 CLI installer

- [ ] `install.cmd` (Windows) → chiama `install.py`
- [ ] `install.sh` (Linux/Mac) → chiama `install.py`
- [ ] `install.py --uninstall` → rollback pulito
- [ ] `install.py --verify` → controlla install
- [ ] `install.py --repair` → rifix cose rotte
- [ ] Log file in `%LOCALAPPDATA%/gray-matter/install.log`

### 2.5 Test installer

- [ ] Test su Windows (Python 3.10, 3.12, 3.14)
- [ ] Test su Linux (Python 3.10, 3.12)
- [ ] Test su macOS (Python 3.12)
- [ ] Test: Python non installato → download automatico
- [ ] Test: venv già esistente → idempotente
- [ ] Test: permessi insufficienti → errore chiaro

### 2.6 Pulizia vecchi installer

- [ ] Rimuovere `install.sh` alla root (dopo nuovo installer funzionante)
- [ ] Rimuovere `install.ps1` alla root
- [ ] Aggiornare `install.sh`/`.ps1` in Neuron/ e neurag/ → thin launcher
- [ ] Aggiornare README con nuove istruzioni

---

## FASE 3 — Pulizia codice

> Zero rischio, beneficio immediato su leggibilità.

### 3.1 Magic numbers → costanti

**Neuron:**
- [ ] Creare `neuron/config.py` costanti (EMBEDDING_DIM, BUSY_TIMEOUT_MS, etc.)
- [ ] Sostituire in `db.py` (384, 5000, 40)
- [ ] Sostituire in `server.py` (400, 3, 10)
- [ ] Sostituire in `models.py`

**NeuRAG:**
- [ ] Creare `neurag/constants.py` costanti
- [ ] Sostituire in `db.py` (384, 5000, 40)
- [ ] Sostituire in `server.py` (200, 3, 20)
- [ ] Sostituire in `chunker.py` (20, 60, 160, 8, 6)

**Reference:** NEURON-Tasks.md → T3, NEURAG-Tasks.md → T3

### 3.2 Fix import duplicati

- [ ] `neuron/db.py`: rimuovere `import re as _re`, usare solo `import re`
- [ ] `neurag/db.py`: stessa cosa

**Reference:** NEURON-Tasks.md → T6, NEURAG-Tasks.md → T4

### 3.3 Rimuovere dead code

- [ ] Cancellare `neuron/__version__.py`
- [ ] Cancellare `neurag/__version__.py`
- [ ] Rimuovere `QueryResult` da `neurag/models.py`
- [ ] Rimuovere `Optional` da `neurag/models.py` import
- [ ] Marcare re-export deprecati in `neuron/server.py` con warning

**Reference:** NEURON-Tasks.md → T5, NEURAG-Tasks.md → T5

---

## FASE 4 — Refactoring moduli

> Il grosso lavoro. Farlo dopo le fondamenta e la pulizia.

### 4.1 Refactor Neuron `server.py` (1926 righe)

- [ ] Creare `neuron/state.py` — stato globale (_embedder, _ctx_cache, _domain_state, etc.)
- [ ] Creare `neuron/handlers.py` — tutti i `_tool_*` estratti
- [ ] `server.py` diventa router: `call_tool()` → lookup in `HANDLERS` dict
- [ ] Mantenere re-export per backward compat
- [ ] Aggiornare `search.py` — `_S()` legge da `state.py`
- [ ] Aggiornare `stimulus.py` — `_domain_state` da `state.py`
- [ ] Test: tutti i 272 test passano dopo refactor
- [ ] Test: re-export funzionano (backward compat)

**Reference:** NEURON-Tasks.md → T1

### 4.2 Refactor NeuRAG `cli.py` (872 righe)

- [ ] Creare `neurag/commands/` cartella
- [ ] Creare `neurag/commands/ingest.py`
- [ ] Creare `neurag/commands/query.py`
- [ ] Creare `neurag/commands/node.py`
- [ ] Creare `neurag/commands/status.py`
- [ ] Creare `neurag/commands/repair.py`
- [ ] Creare `neurag/commands/install.py`
- [ ] `cli.py` diventa router con `register(subparsers)`
- [ ] Lazy imports nei moduli comandi (pattern esistente)
- [ ] Test: tutti i 36 test passano dopo refactor
- [ ] Verificare che `webgui.py` funziona ancora (`python -m neurag.cli <cmd> --json`)

**Reference:** NEURAG-Tasks.md → T1

### 4.3 Refactor NeuRAG `db.py` (1103 righe)

- [ ] Creare `neurag/search.py` — search logic (search, _retrieve, _rank_lexical, _get_embedding, _cosine_sim)
- [ ] Creare `neurag/graph.py` — graph operations (add_node, get_node, get_children, delete_node, etc.)
- [ ] `db.py` diventa connection manager + schema init
- [ ] `KnowledgeGraph` espone `self.graph` e `self.search`
- [ ] Test: tutti i test passano dopo refactor

**Reference:** NEURAG-Tasks.md → T2

### 4.4 Refactor Gray Matter `server.py`

- [ ] Creare `gray_matter/handlers.py` — tool handlers (pulse, store_turn, status)
- [ ] Creare `gray_matter/ipc.py` — logica IPC
- [ ] `server.py` diventa router + demone
- [ ] Test: tutti i 35 test passano dopo refactor

**Reference:** GRAY-MATTER-Tasks.md → T2

---

## FASE 5 — Feature production

> Funzionalità che mancano per la release.

### 5.1 Validazione chunk (NeuRAG)

**Chain:** `neurag/chunker.py` → `neurag/db.py` → `neurag/server.py`

- [ ] Creare `neurag/validate.py` — funzioni validazione
- [ ] Validare chunk in `add_chunk()` — rifiutare vuoti/junk
- [ ] Validare nodi in `add_node()` — rifiutare nomi duplicati
- [ ] Report: quanti chunk scartati e perché
- [ ] Test: chunk validi passano, invalidi vengono scartati

**Reference:** NEURAG-Tasks.md → T6

### 5.2 Flash cooldown persistente (Gray Matter)

**Chain:** `gray_matter/server.py` → nuovo file o DB

- [ ] Decidere persistenza: file JSON o campo in Neuron
- [ ] Implementare load/save stato flash
- [ ] Cooldown per-topic (non globale)
- [ ] Pulizia periodica (TTL sui record)
- [ ] Test: flash persiste tra sessioni

**Reference:** GRAY-MATTER-Tasks.md → T3

### 5.3 Instructions in risposte (Gray Matter)

**Chain:** `gray_matter/server.py`

- [ ] Definire testo instructions (conciso, max 200 token)
- [ ] Aggiungere in output di `pulse` e `store_turn`
- [ ] Test: instructions presenti nelle risposte

**Reference:** GRAY-MATTER-Tasks.md → T5

### 5.4 Fix `_first_conchet` (Gray Matter)

**Chain:** `gray_matter/server.py` → `neuron/server.py`

- [ ] Verificare se Neuron restituisce JSON strutturato
- [ ] Se sì, usare `json.loads()` invece di parsing testo
- [ ] Se no, usare regex robuste
- [ ] Test: parsing non si rompe se output Neuron cambia

**Reference:** GRAY-MATTER-Tasks.md → T4

---

## FASE 6 — GUI

> Solo dopo che il core funziona.

### 6.1 Semplificare webgui

**Chain:** `gray_matter/webgui.py`

- [ ] Identificare pannelli utili vs inutili
- [ ] Eliminare pannello Processi (PID non servono all'utente)
- [ ] Eliminare pannello Ecosystem (install peer = one-shot)
- [ ] Eliminare pannello Network (bridge/tunnel = avanzato)
- [ ] Tenere: Status, Log, Preferences
- [ ] Test: tutti i test GUI passano dopo semplificazione

### 6.2 Split admin/utente

- [ ] GUI utente: chat + stato (minimal)
- [ ] GUI admin: config + repair (separata)
- [ ] Entry point separati: `gray-matter gui` (utente), `gray-matter admin` (admin)
- [ ] Test: entrambe le GUI partono e funzionano

### 6.3 Fallback CLI

- [ ] Verificare che ogni operazione GUI ha equivalente CLI
- [ ] Documentare comandi CLI in README
- [ ] Test: GUI non parte → CLI funziona

### 6.4 (Opzionale) Tauri/Electron per GUI utente

- [ ] Valutare se pywebview basta o serve electron
- [ ] Se Tauri: architettura React/Svelte + Rust backend
- [ ] Se pywebview: ottimizzare performance e look

---

## FASE 7 — Release

> L'ultimo passo.

### 7.1 Bump versioni

- [ ] Neuron: `6.1.2` → `6.2.0` (feat: file lock, atomic salience, refactor)
- [ ] NeuRAG: `1.2.2` → `1.3.0` (feat: validazione chunk, refactor)
- [ ] Gray Matter: `1.1.2` → `1.2.0` (feat: fix L2, flash persistente, refactor)
- [ ] Aggiornare `__version__` in `__init__.py` per ogni progetto
- [ ] Aggiornare `pyproject.toml` per ogni progetto
- [ ] Aggiornare README badge per ogni progetto

### 7.2 Documentazione

- [ ] Aggiornare CHANGELOG per ogni progetto
- [ ] Aggiornare ARCHITETTURA.md se cambiano i moduli
- [ ] Aggiornare INSTALL.md con nuovi installer
- [ ] Aggiornare TOOLS.md se cambiano i tool
- [ ] Aggiornare GRAY-MATTER-COMPENDIUM.md con nuovi fix

### 7.3 Git

- [ ] Commit tutti i cambiamenti
- [ ] Tag: `v6.2.0` (Neuron), `v1.3.0` (NeuRAG), `v1.2.0` (GM)
- [ ] Push a origin
- [ ] Creare GitHub release con release notes

### 7.4 PyPI (opzionale)

- [ ] Build wheel per ogni progetto
- [ ] Test upload su TestPyPI
- [ ] Upload su PyPI
- [ ] Verificare `pip install neuron neurag gray-matter`

### 7.5 Smoke test finale

- [ ] Install pulito su Windows da zero
- [ ] Install pulito su Linux da zero
- [ ] `neuron status` → ok
- [ ] `neurag status` → ok
- [ ] `gray-matter status` → ok
- [ ] `gray-matter pulse` → contesto + chunk
- [ ] `neuron store_turn` → persiste
- [ ] GUI parte → mostra stato

---

## MATRICE DIPENDENZE

```
FASE 0 (verifica)
    │
    ▼
FASE 1 (fondamenta DB)
    │
    ├──→ FASE 3 (pulizia) ──→ FASE 4 (refactoring)
    │                              │
    │                              ▼
    │                         FASE 5 (feature)
    │                              │
    ▼                              ▼
FASE 2 (installer) ──────→ FASE 6 (GUI)
                                   │
                                   ▼
                              FASE 7 (release)
```

**Indipendenti:**
- FASE 2 (installer) può partire subito, non dipende da FASE 1
- FASE 3 (pulizia) può partire subito, non dipende da FASE 1
- FASE 5.2-5.4 (feature GM) possono partire subito

**Bloccanti:**
- FASE 4 (refactoring) dipende da FASE 1 + FASE 3
- FASE 6 (GUI) dipende da FASE 4
- FASE 7 (release) dipende da tutto

---

## CHECKLIST FINALE RELEASE

Prima di tagliare il tag, verificare:

- [ ] 340+ test verdi su Turso reale
- [ ] L2 fixato e verificato con 2 processi
- [ ] L1 fixato e verificato con 2 processi
- [ ] Installer funziona su Windows + Linux
- [ ] `pip install` funziona da PyPI
- [ ] Nessun warning di deprecation nei test
- [ ] Nessun magic number rimasto (grep per numeri hardcoded)
- [ ] Nessun dead code (grep per import inutilizzati)
- [ ] CHANGELOG aggiornato per tutti e 3 i progetti
- [ ] README aggiornato con istruzioni install
- [ ] Tag git + push
- [ ] Smoke test manuale: install → status → pulse → store_turn → GUI

---

*Fine piano d'azione.*
