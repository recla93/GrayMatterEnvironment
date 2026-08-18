# Tasklist Fix — Safety Checks & Dependency Verification

> Ogni task è auto-controllante: prima di applicare il fix, verifica i metodi che dipendono dal codice modificato.
> Ordine: P0 prima, P1 dopo, P2 post-release. Ogni task ha un campo `DEPENDENCIES` che elenca cosa controllare.

---

## NEURON — Fix Tasklist

### N-P0-1: Cambiare default slug `neuron5` → `neuron` (SSOT) ✅ APPLICATO

**File:** `src/neuron/config.py:36`
**Fix:** `return os.environ.get("NEURON_SLUG", "neuron")`

**DEPENDENCIES — controllare PRIMA del fix:**
- [x] `config.py:36` è l'SSOT — tutti gli altri moduli delegano qui
- [x] Verificare che `resolve_slug()` (config.py:51) usi `slug()` — se no, fix anche lì
- [x] `paths.py` chiama `config.slug()` — non ha default hardcoded indipendente
- [x] `search.py`, `stimulus.py` lazy-import da `server.py` — non usano slug direttamente

**Dopo il fix — safety check:**
- [ ] `grep -rn "neuron5" src/neuron/ --include="*.py"` — restano solo: `KNOWN_SLUGS` (backwards compat), commenti, docstring
- [ ] `python -c "from neuron.config import slug; assert slug() == 'neuron'"` — SSOT confermato
- [ ] `python -c "from neuron.paths import graphs_dir; print(graphs_dir())"` — path usa `neuron/` non `neuron5/`

---

### N-P0-2: Cambiare MCP server identity ✅ APPLICATO

**File:** `src/neuron/server.py:401`
**Fix:** `app = Server("neuron", version=__version__)`

**DEPENDENCIES — controllare PRIMA del fix:**
- [x] I nomi tool MCP diventano `mcp__neuron__*` (prima `mcp__neuron5__*`)
- [x] I client che usano `mcp__neuron5__pre_turn` etc. devono essere aggiornati (→ N-P0-3)
- [x] `clients.py:523` `KNOWN_SLUGS` deve includere `"neuron5"` per backwards compat
- [x] `server.py:1901` commento menziona `neuron5` — aggiornare

**Dopo il fix — safety check:**
- [ ] `python -c "from neuron.server import app; assert app.name == 'neuron'"` 
- [ ] Avviare MCP server → `list_tools` mostra tool con prefisso `mcp__neuron__`

---

### N-P0-3: Aggiornare hook instruction files (20 sostituzioni) ✅ APPLICATO

**Files:**
- `src/neuron/clients/claude-code-hook/neuron_sessionstart_hook.py` (~10 occorrenze)
- `src/neuron/clients/cowork-plugin/neuron-guard/hooks/neuron_handshake.py` (~10 occorrenze)

**Fix:** `mcp__neuron5__*` → `mcp__neuron__*` in entrambi i file

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Hook files sono testo statico (zero import) — cambiano solo i nomi tool
- [ ] I tool esposti dal server (N-P0-2) devono matchare esattamente i nomi negli hook
- [ ] `executor.py:33` `_HOOK_MARKERS` include `"neuron_sessionstart_hook"` — non cambia (è il nome file, non tool)
- [ ] `installer.py:22-26` `HOOK_ASSETS` map asset → path — non cambia

**Dopo il fix — safety check:**
- [ ] `grep -rn "neuron5" src/neuron/clients/ --include="*.py"` — zero occorrenze
- [ ] `grep -c "mcp__neuron__" src/neuron/clients/claude-code-hook/neuron_sessionstart_hook.py` — ~10
- [ ] I nomi tool negli hook matchano esattamente quelli esposti dal server

---

### N-P0-4: Aggiornare default hardcoded nei moduli ✅ APPLICATO

**Files e righe:**
- `clients.py:781` — `slug or os.environ.get("NEURON_SLUG", "neuron")`
- `clients.py:835` — `default=os.environ.get("NEURON_SLUG", "neuron")`
- `setup.py:138` — `default=os.environ.get("NEURON_SLUG", "neuron")`
- `__main__.py:118` — `os.environ.get("NEURON_SLUG", "neuron")`
- `bridge.py:61` — `os.environ.get("NEURON_SLUG", "neuron")`
- `project.py:87` — `os.environ.get("NEURON_SLUG", "neuron")`
- `manage.py:184` — `os.environ.get("NEURON_SLUG", "neuron")`

**Fix:** Cambiare `"neuron5"` → `"neuron"` in ogni default

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Ogni modulo qui usa `os.environ.get("NEURON_SLUG", ...)` NON `config.slug()` — verificare
- [ ] Se qualcuno chiama `config.slug()`, il default in config.py (N-P0-1) basta
- [ ] `KNOWN_SLUGS = ("neuron", "neuron5")` in clients.py:523 — NON cambiare (backwards compat)

**Dopo il fix — safety check:**
- [ ] `grep -rn '"neuron5"' src/neuron/ --include="*.py"` — restano solo `KNOWN_SLUGS` e commenti
- [ ] Ogni file modificato: il default matcha `config.slug()`

---

### N-P0-5: Installer passa `--slug neuron` (o default basta) ✅ NO-OP

**Files:** `neuron/install.ps1:62`, `neuron/install.sh`

**DEPENDENCIES — controllare PRIMA del fix:**
- [x] Se il default in config.py è già `neuron` (N-P0-1), l'installer NON serve `--slug`
- [x] Verificare che `register --client all` usi `config.slug()` — se sì, il default basta
- [x] `install.cmd` wrappa `install.ps1` — fix solo in .ps1 e .sh

**Dopo il fix — safety check:**
- [ ] `grep -n "slug" neuron/install.ps1` — o rimosso o passa `--slug neuron`
- [ ] Eseguire `install.ps1` dry-run → registra `neuron` (non `neuron5`)

---

### N-P0-6: Test suite — aggiornare riferimenti a `neuron5` ✅ APPLICATO

**Files:** `tests/test_clients.py` (33 ref), `tests/test_setup.py` (5 ref)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] I test usano lo slug come argomento — cambiarlo a `neuron`
- [ ] `KNOWN_SLUGS` in clients.py include ancora `neuron5` — i test di backwards compat lo testano?
- [ ] `test_clients.py` testa `register()`, `doctor()`, `deregister()` — tutti usano slug

**Dopo il fix — safety check:**
- [ ] `grep -rn "neuron5" tests/ --include="*.py"` — zero occorrenze (tranne backwards compat test)
- [ ] `python -m pytest tests/test_clients.py tests/test_setup.py` — tutti passano

---

### N-P0-7: Rimuovere `.fuse_hidden*` dal tracking git ✅ NO-OP

**Command:** `git rm --cached src/neuron/data/.fuse_hidden*`

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `.gitignore` ha `.fuse_hidden*` — dopo `git rm --cached`, git ignora i file
- [ ] I file restano su disco (solo rimossi dal tracking)
- [ ] `src/neuron/data/` non ha altri file importanti da perdere

**Dopo il fix — safety check:**
- [ ] `git status` mostra i file come "deleted" (staged)
- [ ] `ls src/neuron/data/.fuse_hidden*` — file ancora su disco
- [ ] `.gitignore` li ignora

---

### N-P1-1: Dialog 3 opzioni installer ✅ APPLICATO

**Files:** `neuron/install.ps1:30-36`, `neuron/install.sh:20-28`

**Fix:** `[S]ì / [N]o / [D]ettagli` con ramo "Dettagli" che mostra info e torna al prompt

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Il dialog è solo UX — non cambia la logica di install
- [ ] La scelta "Dettagli" NON deve modificare variabili `$InstallGM`
- [ ] Dopo "Dettagli", il loop torna al prompt (non esce)

**Dopo il fix — safety check:**
- [ ] Testare le 3 opzioni: Y → installa GM, N → skip, D → mostra info + torna al prompt
- [ ] Verificare che `$ErrorActionPreference = "Stop"` sia ancora attivo dopo il dialog

---

### N-P1-2: `$ErrorActionPreference = "Stop"` + stderr guard ✅ APPLICATO

**Files:** `neuron/install.ps1`, `neurag/install.ps1` (diviso in N-P1-2 e NR-P0-2)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] I comandi nativi (git, pip) mandano output su stderr
- [ ] Con `ErrorActionPreference = "Stop"`, stderr nativo = eccezione PowerShell
- [ ] Aggiungere `2>$null` SOLO ai comandi nativi, NON a python/pip (hanno info utili)

**Dopo il fix — safety check:**
- [ ] Eseguire `install.ps1` → nessun crash per stderr di git/pip
- [ ] `python -m neuron doctor` → output completo (non filtrato)

---

### N-P2-1: Migrazione grafo `neuron5` → `neuron` ✅ APPLICATO

**Files:**
- `src/neuron/paths.py` — aggiunta funzione `migrate_graphs()`
- `src/neuron/__main__.py` — aggiunto comando `migrate` al COMMANDS dict + handler `_migrate_cli`
- `gray_matter/catalog.py` — aggiunta descrizione in HELP_IT

**Fix:** Migra automaticamente i grafi dalla vecchia slug (`neuron5`) alla nuova (`neuron`). Idempotente e sicuro.

**DEPENDENCIES — controllare PRIMA del fix:**
- [x] `graphs_dir()` usa `config.slug()` — con il nuovo default, punta a `neuron/graphs/`
- [x] I grafi esistenti sono in `%LOCALAPPDATA%/neuron5/graphs/`
- [x] La migrazione deve: (1) verificare che `neuron/graphs/` non esista già, (2) spostare o symlinkare
- [x] Se l'utente ha `NEURON_SLUG=neuron5`, non migrare (sta usando il vecchio slug volutamente)

**Dopo il fix — safety check:**
- [x] `neuron migrate --dry-run` → mostra cosa farebbe
- [x] Eseguire con grafo esistente → i grafi si trovano nella nuova posizione
- [x] Eseguire di nuovo → idempotente (nessun doppio spostamento)
- [x] `neuron console` → grafo leggibile

---

## NEURAG — Fix Tasklist

### NR-P0-1: Auto-register standalone ✅ APPLICATO

**Files:** `neurag/install.ps1:62`, `neurag/install.sh:50`

**Fix:** Aggiungere `& (Join-Path $Venv "Scripts\neurag.exe") register --client all` dopo `doctor`

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `register --client all` in `clients.py` funziona standalone (nessuna dipendenza GM)
- [ ] Il register sovrascrive i config esistenti — verificare che sia non-destructive (backup `.bak`)
- [ ] Se il register fallisce, l'installer deve continuare (non abortire)

**Dopo il fix — safety check:**
- [ ] Eseguire `install.ps1` → dopo install, `neurag doctor` mostra neurag registrato
- [ ] Verificare che i config dei client abbiano l'entry `neurag`
- [ ] Verificare che i backup `.bak` siano stati creati

---

### NR-P0-2: Dialog 3 opzioni ✅ APPLICATO

**Files:** `neurag/install.ps1:30-36`, `neurag/install.sh:20-28`

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Stessa logica di N-P1-1 — il dialog è solo UX
- [ ] La scelta "Dettagli" NON deve modificare variabili
- [ ] Dopo "Dettagli", il loop torna al prompt

**Dopo il fix — safety check:**
- [ ] Testare le 3 opzioni: Y → installa GM, N → skip, D → mostra info
- [ ] Verificare che l'installazione standalone funzioni indipendentemente dalla scelta

---

### NR-P0-3: Aggiungere Zed + Codex ai client — SKIP (decisione utente 2026-07-22)

**File:** `neurag/clients.py`

**Fix:** Aggiungere entry per:
- Zed: `~/.config/zed/settings.json`, key `context_servers`, style `args`
- Codex CLI: `~/.codex/config.toml`, style TOML

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Copiare la struttura da `neurag/clients.py` esistente (stessa matrice)
- [ ] Zed usa `context_servers` (stessa struttura di Claude Desktop)
- [ ] Codex usa TOML — serve `tomllib` (stdlib 3.11+)
- [ ] `doctor()` deve leggere anche i nuovi config

**Dopo il fix — safety check:**
- [ ] `neurag doctor` → mostra Zed e Codex se installati
- [ ] `neurag register --client all` → registra anche in Zed e Codex
- [ ] `grep -n "zed\|codex" neurag/clients.py` — entry presenti

---

### NR-P1-1: Fix `test_node_links.py` `:memory:` ✅ APPLICATO

**File:** `tests/test_node_links.py`

**Fix:** `KnowledgeGraph(pathlib.Path(":memory:"))` → `KnowledgeGraph(":memory:")`

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `KnowledgeGraph.__init__` accetta sia `str` sia `Path` — verificare
- [ ] Se accetta solo `Path`, serve un adapter
- [ ] I test usano solo letture (no write) — il fix non rompe nulla

**Dopo il fix — safety check:**
- [ ] `ls :memory:` — nessun file orfano creato
- [ ] `python -m pytest tests/test_node_links.py` — tutti passano

---

### NR-P1-2: Lazy import in `db.py` ✅ APPLICATO

**File:** `neurag/db.py`

**Fix:** Deferire `from neurag.chunker import chunk_file, scan_directory` e `from neurag.embedder import get_embedder` e `from neurag.reranker import get_reranker` dentro le funzioni che le usano

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Identificare quali funzioni di `db.py` usano chunker/embedder/reranker
- [ ] Verificare che `server.py` importi `db.py` a module level
- [ ] Verificare che `cli.py` importi `db.py` a module level
- [ ] Se `db.py` è importato all'avvio del MCP server, il lazy import risparmia ~380MB di fastembed

**Dopo il fix — safety check:**
- [ ] `python -c "import neurag.db"` — fastembed NON viene caricato
- [ ] `neurag knowledge_query` — funziona normalmente (embedder caricato lazy)
- [ ] `neurag ingest` — funziona (chunker caricato lazy)

---

### NR-P1-3: Header install corretti ✅ APPLICATO

**Files:** `neurag/install.ps1` header, `neurag/install.cmd` header, `neurag/install.sh` header

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] I header sono solo commenti — nessun impatto funzionale
- [ ] Cambiare "unified Gray Matter installer" → "NeuRAG installer" o simile
- [ ] Verificare che `install.cmd` wrappi correttamente `install.ps1`

**Dopo il fix — safety check:**
- [ ] `grep -n "unified" neurag/install.*` — zero occorrenze
- [ ] Leggere i nuovi header → accurati

---

### NR-P2-1: `reranker.py` import-time settings ✅ APPLICATO

**File:** `neurag/reranker.py`

**Fix:** Deferire la lettura di `_MODEL` dentro `get_reranker()` invece di module level

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `_MODEL` è usato solo in `get_reranker()` — verificare
- [ ] Se il config file è corrotto, il default deve essere usato (non crashare)
- [ ] `reranker.py` è opzionale (opt-in) — non deve influenzare l'avvio

**Dopo il fix — safety check:**
- [ ] `python -c "import neurag.reranker"` — config file non letto
- [ ] `neurag config set rerank true` → reranker funziona con il modello corretto

---

## GRAY MATTER — Fix Tasklist

### GM-P0-1: `_send_ipc` recv loop [GIÀ APPLICATO]

**File:** `gray_matter/server.py:52-68`
**Status:** ✅ Fix applicato — `_recv_exact()` loop aggiunto

**DEPENDENCIES — safety check POST-fix:**
- [ ] `_send_ipc` è usato da: `_send_registration`, `_send_heartbeat`, `_is_gray_matter_running`
- [ ] `_send_ipc` è usato da `cli.py` (definizione separata, stessa logica)
- [ ] Il fix NON cambia la signature — solo l'implementazione interna
- [ ] `struct.unpack("!I", ...)` richiede esattamente 4 byte — il loop garantisce

**Verifica:**
- [ ] `python -c "from gray_matter.server import _send_ipc; print('OK')"` — import ok
- [ ] `gray-matter ping` — funziona (IPC round-trip)
- [ ] `gray-matter doctor` — risposta completa (non troncata)

---

### GM-P0-2: File handle leak `_spawn_gray_matter` [GIÀ APPLICATO]

**File:** `gray_matter/server.py:129-156`
**Status:** ✅ Fix applicato — `finally: out.close()` aggiunto

**DEPENDENCIES — safety check POST-fix:**
- [ ] `_spawn_gray_matter` è usato da: `autoregister()`, `cmd_start()`, `_ensure_daemon()`
- [ ] Il fix NON cambia il comportamento — solo chiude il FD del parent dopo Popen
- [ ] Il child heredita il FD — `out.close()` nel parent non lo chiude nel child

**Verifica:**
- [ ] `python -c "from gray_matter.server import _spawn_gray_matter; print('OK')"` — import ok
- [ ] `gray-matter start` → `gray-matter stop` — funziona, log scritto correttamente

---

### GM-P1-1: Estrarre `_send_ipc` condiviso

**Files:** `gray_matter/server.py` e `gray_matter/cli.py`

**Fix:** Creare `gray_matter/_ipc.py` con `_send_ipc` + `_recv_exact`, importare da entrambi

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `cli.py:_send_ipc` — usata da: `_send_ipc` (IPC commands), `cmd_stop`, `cmd_isolate`, `cmd_collaborate`, `cmd_mode`, `cmd_knowledge`, `_ensure_daemon`, `_cmd_gm_tool`
- [ ] `server.py:_send_ipc` — usata da: `_send_registration`, `_send_heartbeat`, `_is_gray_matter_running`
- [ ] Le due implementazioni hanno timeout diverso? → Unificare a 3s (entrambe 3s)
- [ ] `server.py` importa da `cli.py` già (linea 41) — non creare circular import

**Dopo il fix — safety check:**
- [ ] `python -c "from gray_matter._ipc import _send_ipc"` — import ok
- [ ] `grep -rn "_send_ipc" gray_matter/ --include="*.py"` — solo `_ipc.py` lo definisce
- [ ] `gray-matter ping` — funziona
- [ ] `gray-matter status` — funziona
- [ ] `gray-matter doctor` — risposta completa
- [ ] `gray-matter isolate neuron` — funziona
- [ ] `gray-matter collaborate neuron` — funziona

---

### GM-P1-2: `selfcheck.py` — aggiornare test per recv loop

**File:** `gray_matter/selfcheck.py`

**Fix:** Aggiungere test per `_recv_exact` (funzione nuova)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `_recv_exact` è in `server.py` (o `_ipc.py` se GM-P1-1 è fatto)
- [ ] Il test deve simulare: recv parziale → loop → dati completi
- [ ] Il test NON deve aprire connessioni TCP reali (mock socket)

**Dopo il fix — safety check:**
- [ ] `python -m gray_matter.selfcheck` — tutti i test passano (incluso il nuovo)
- [ ] `_recv_exact` testa: dati completi in un chunk, dati multipli chunk, connessione chiusa

---

### GM-P2-1: `_first_concept` — structured return [DEFERITO]

**Status:** Deferred — attende il refactor della persistenza di Neuron. Il `ponytail:` comment documenta lafragilità.

---

### GM-P2-2: `bridges_for` — FTS index [DEFERITO]

**Status:** Deferred — accettabile a <100 bridges. Se cresce >1000, aggiungere FTS.

---

## INSTALL FLOW — Fix Tasklist (da AUDIT-INSTALL-FLOW)

### IF-MED-1: Version mismatch fallback remoto GM ✅ APPLICATO

**Files:** `neuron/install.ps1:83`, `neurag/install.ps1:83`

**Fix:** `$GmVersion` hardcoded `"1.0.0"` → leggere da `gray_matter/pyproject.toml` o defaultare all'ultima release nota (`"1.1.2"`)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `gray_matter/pyproject.toml` ha `version = "1.1.2"` — leggere da lì
- [ ] Il fallback remoto scarica `https://github.com/recla93/gray-matter/archive/refs/tags/v$GmVersion.zip`
- [ ] Se `$env:GM_VERSION` è impostato, usare quello (override manuale)
- [ ] Entrambi gli installer (.ps1) devono avere lo stesso default

**Dopo il fix — safety check:**
- [ ] `grep -n "GmVersion" neuron/install.ps1 neurag/install.ps1` — entrambi leggono da pyproject.toml o hanno `1.1.2`
- [ ] Se `$env:GM_VERSION` non è impostato, il fallback punta a una release esistente

---

### IF-CRIT-3 / IF-BUG-5: Dialog repair da install.cmd (GM)

**File:** `gray_matter/install.ps1:134-148`

**Fix:** Quando `Test-AlreadyInstalled` è true e l'utente è interattivo, chiedere `[R]ipara / [I]nforma / [A]nnulla`

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `Test-AlreadyInstalled` è definito nello stesso file — verificare la signature
- [ ] Il flag `-Force` esiste già — il dialog deve impostare `$Force = $true` se l'utente sceglie Ripara
- [ ] Se non interattivo (CLI), comportamento attuale (exit 0) — non cambiare
- [ ] La sezione "Info" deve mostrare versione + componenti installati + come fare repair

**Dopo il fix — safety check:**
- [ ] Double-click install.cmd su install esistente → dialog compare
- [ ] Scegliere "Ripara" → install viene eseguito con `-Force`
- [ ] Scegliere "Annulla" → "Done (nothing changed)."
- [ ] Eseguire da CLI senza `-Force` → stessa logica interattiva
- [ ] Eseguire da CLI con `-Force` → skip dialog, install diretto

---

### IF-MED-4: Nessuna verifica post-install nel dialog standalone ✅ APPLICATO

**Files:** `neuron/install.ps1:62`, `neurag/install.ps1:62`

**Fix:** Dopo `register --client all` (Neuron) o `register` (NeuRAG), eseguire `doctor` per verificare che la registrazione sia riuscita

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Neuron: `register --client all` → dopo, `doctor` mostra lo stato
- [ ] NeuRAG: `register --client all` → dopo, `doctor` mostra lo stato (dopo NR-P0-1)
- [ ] Il check deve essere best-effort: se fallisce, non bloccare l'install
- [ ] Output: `[ok] Registered in X clients` o `[!!] Registration may have failed`

**Dopo il fix — safety check:**
- [ ] Install standalone Neuron → output mostra stato registrazione
- [ ] Install standalone NeuRAG → output mostra stato registrazione
- [ ] Se un client non è installato, il check lo segnala come "not found" (non errore)

---

### IF-BASS-4: `install.sh` usa `exec sh` per delegare a GM ✅ APPLICATO

**Files:** `neuron/install.sh:61`, `neurag/install.sh:61`

**Fix:** Rimuovere `exec` — `exec` sostituisce il processo corrente, se GM installer fallisce il fallback standalone non viene mai raggiunto

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `exec sh "$gm/install.sh" "$@"` → `sh "$gm/install.sh" "$@"; gm_exit=$?`
- [ ] Dopo la chiamata, controllare `$gm_exit` — se non zero, continuare al fallback standalone
- [ ] Il fallback standalone è dopo la riga di delega (righe 101-104 in install.sh)
- [ ] Entrambi gli .sh (neuron e neurag) hanno lo stesso pattern

**Dopo il fix — safety check:**
- [ ] Se GM installer fallisce, il fallback standalone viene eseguito
- [ ] Se GM installer ha successo, il processo termina normalmente (no `exec` = il parent continua)
- [ ] `grep -n "exec sh" neuron/install.sh neurag/install.sh` — zero occorrenze

---

### IF-ARCH-1: Duplicazione Neuron ↔ NeuRAG installer

**Status:** DEFERITO — strutturale, richiede refactor. Le due versioni funzionano. Unificare quando il flusso è stabile.

---

### IF-UX-1: Riepilogo post-install ✅ APPLICATO

**File:** `gray_matter/install.ps1:285-287`

**Fix:** Sostituire "Done. Restart your AI apps." con un riepilogo strutturato: versioni componenti, client registrati, shortcut

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `Get-SrcVersion` esiste e restituisce la versione da pyproject.toml
- [ ] I nomi dei client sono disponibili (da `CLIENTS` dict o hardcoded)
- [ ] Il shortcut path è noto
- [ ] Il riepilogo deve essere l'ultima cosa stampata PRIMA di aprire la GUI

**Dopo il fix — safety check:**
- [ ] Output mostra: `✓ Gray Matter X.Y.Z`, `✓ Neuron X.Y.Z`, `✓ NeuRAG X.Y.Z`
- [ ] Output mostra: `✓ Registered in: Claude Desktop, Cursor, ...`
- [ ] Output mostra: `✓ Desktop shortcut: Gray Matter`
- [ ] Output mostra: `Restart your AI apps to load the servers.`

---

### IF-UX-2: Error messages con azione ✅ APPLICATO

**Files:** Tutti gli installer (.ps1, .sh)

**Fix:** Ogni messaggio di errore deve dire cosa fare dopo (link a download, comando winget, etc.)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Identificare tutti i messaggi "ERROR:" nei 6 installer
- [ ] Ogni errore deve avere un'azione suggerita
- [ ] Non cambiare il codice di exit (1 per errori, 0 per successo)

**Dopo il fix — safety check:**
- [ ] `grep -n "ERROR:" neuron/install.ps1 neurag/install.ps1 gray_matter/install.ps1` — ogni riga ha un'azione
- [ ] `grep -n "ERROR:" neuron/install.sh neurag/install.sh` — ogni riga ha un'azione

---

## VERIFICA FINALE — Post tutti i fix

### Neuron
- [ ] `python -m pytest tests/` — tutti passano
- [ ] `grep -rn "neuron5" src/neuron/ --include="*.py"` — solo `KNOWN_SLUGS` e commenti
- [ ] `neuron register --client all` → registra `neuron`
- [ ] `neuron doctor` → trova entry `neuron5` orfane e le segnala
- [ ] MCP server risponde come `neuron` (non `neuron5`)
- [ ] `neuron gui` → auto-bootstrap GM, GUI funziona

### NeuRAG
- [ ] `python -m pytest tests/` — tutti passano
- [ ] `neurag register --client all` → registra in 7 client (incluse Zed + Codex)
- [ ] `neurag doctor` → mostra stato corretto con tutti i client
- [ ] MCP server risponde con 12 tools
- [ ] `neurag gui` → auto-bootstrap GM, GUI funziona

### Gray Matter
- [ ] `python -m gray_matter.selfcheck` — tutti passano
- [ ] `gray-matter ping` — daemon risponde
- [ ] `gray-matter doctor` — tutti i server up, cache funzionante
- [ ] `gray-matter status` — registrazioni corrette
- [ ] GUI web funziona (pywebview o browser)
- [ ] `gray-matter bridges` — bridges list corretta

### Cross-project
- [ ] GM registra SOLO `gray-matter` nei client (proxy model)
- [ ] Neuron + NeuRAG registrati SOLO come managed workers (non direttamente)
- [ ] `gray_matter_pulse` funziona: Neuron context + NeuRAG knowledge + bridges + flash
- [ ] Hooks deployati correttamente in Claude Code + OpenCode

### Install Flow
- [ ] Neuron install standalone → `register --client all` → `doctor` verifica registrazione
- [ ] NeuRAG install standalone → `register --client all` → `doctor` verifica registrazione
- [ ] Dialog 3 opzioni funziona: Sì/Nò/Dettagli in entrambi gli installer
- [ ] Dialog repair funziona in GM install.cmd (double-click su install esistente)
- [ ] `$ErrorActionPreference = "Stop"` non crasha su stderr di git/pip
- [ ] `install.sh` fallback standalone raggiungibile (no `exec`)
- [ ] Version mismatch fallback remoto: `GmVersion` punta a release esistente
- [ ] Post-install: riepilogo con versioni + client + shortcut
- [ ] Error messages hanno azione suggerita

---

## GUI — Fix Tasklist (da AUDIT-CONTROL-CENTER)

### GUI-P0-1: Aggiungere comandi start/stop a Neuron e NeuRAG ✅ APPLICATO

**Files:**
- `neuron/src/neuron/__main__.py` — aggiunti `start` e `stop` al COMMANDS dict + funzioni `_start_cli` e `_stop_cli`
- `neurag/cli.py` — aggiunti `start` e `stop` al parser + funzioni `_cmd_start` e `_cmd_stop`

**Fix:** Ogni tool può ora avviare/fermare il proprio server MCP come processo background. Usa PID file in `data_dir()` per tracciare il processo.

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `neuron.paths.data_dir()` restituisce la cartella dati corretta
- [ ] `neurag.paths.data_dir()` restituisce la cartella dati corretta
- [ ] `subprocess.Popen` con `stdin=DEVNULL` funziona per i server MCP stdio
- [ ] `_is_alive()` funziona su Windows (os.kill(pid, 0))

**Dopo il fix — safety check:**
- [ ] `neuron start` → avvia il server, stampa PID
- [ ] `neuron stop` → ferma il server
- [ ] `neurag start` → avvia il server, stampa PID
- [ ] `neurag stop` → ferma il server
- [ ] `neuron start` due volte → "già in esecuzione"
- [ ] `neuron stop` senza server → "non in esecuzione"

---

### GUI-P0-2: Aggiornare HELP_IT in catalog.py ✅ APPLICATO

**File:** `gray_matter/catalog.py`

**Fix:** Aggiunte descrizioni per `start`/`stop` in Neuron e NeuRAG. Rese più chiare le descrizioni di `register`/`deregister`/`config`/`repair` per distinguere tra GM, Neuron e NeuRAG.

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Le chiavi `(tool, command)` matchano i nomi nei rispettivi CLI
- [ ] Le descrizioni sono in italiano e concise

**Dopo il fix — safety check:**
- [ ] `python -c "from gray_matter import catalog; print('OK')"` — import ok
- [ ] La GUI mostra le nuove descrizioni per start/stop
- [ ] Le descrizioni di register/deregister sono chiare su cosa fanno

---

### GUI-P1-1: Verificare che la GUI mostri le nuove card

**File:** `gray_matter/webgui.html` (nessuna modifica necessaria — le card vengono generate dal catalogo)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] Il catalogo restituisce i comandi `start`/`stop` per Neuron e NeuRAG
- [ ] La GUI li raggruppa nel gruppo `lifecycle`

**Dopo il fix — safety check:**
- [ ] Aprire la GUI → Neuron mostra card "start" e "stop"
- [ ] Aprire la GUI → NeuRAG mostra card "start" e "stop"
- [ ] Le card hanno le descrizioni corrette da HELP_IT

---

### GUI-P1-2: Verificare che start/stop funzionino dalla GUI

**File:** `gray_matter/webgui.py` (nessuna modifica necessaria — usa `Api.run()` generico)

**DEPENDENCIES — controllare PRIMA del fix:**
- [ ] `Api.run()` può eseguire `neuron start`, `neuron stop`, `neurag start`, `neurag stop`
- [ ] Lo streaming funziona (output visibile nella console)

**Dopo il fix — safety check:**
- [ ] Cliccare "start" su Neuron → server avviato, output nella console
- [ ] Cliccare "stop" su Neuron → server fermato
- [ ] Cliccare "start" su NeuRAG → server avviato, output nella console
- [ ] Cliccare "stop" su NeuRAG → server fermato
