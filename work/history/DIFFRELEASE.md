# DIFFRELEASE — Gray Matter Suite

## Release 1 — BugFix + Release prep

**Data:** 2026-07-29  
**Commit:** BugFix + Release prep (tutti e 3 i repo)  
**Tag:** `v1.1.2` (gray_matter) · `v6.1.2` (neuron) · `v1.2.2` (neurag)  
**Branch:** `main` (gray_matter, neurag) · `master` (neuron)

---

## Release 2 — feat/graph-and-chunk-ceiling

**Data:** 2026-07-30  
**Branch:** `feat/graph-and-chunk-ceiling` (tutti e 3 i repo)  
**Totale:** ~4.200 righe aggregate

---

## Indice

1. [Gray Matter](#1-gray-matter) (main → v1.1.2)
2. [Neuron](#2-neuron) (master → v6.1.2)
3. [NeuRAG](#3-neurag) (main → v1.2.2)
4. [Modifiche Trasversali (tutti e 3)](#4-modifiche-trasversali)
5. [feat/graph-and-chunk-ceiling — Gray Matter](#5-featgraph-and-chunk-ceiling--gray-matter)
6. [feat/graph-and-chunk-ceiling — NeuRAG](#6-featgraph-and-chunk-ceiling--neurag)
7. [feat/graph-and-chunk-ceiling — Neuron](#7-featgraph-and-chunk-ceiling--neuron)

---

## 1. Gray Matter

**21 file | 1419 insertions | 72 deletions**

### Nuovi file

| File | Descrizione |
|------|-------------|
| `assets/GM.png` | Logo Gray Matter (305 KB) — servito dal control center web |
| `tests/test_client_targeting.py` | Verifica che la matrice `CLIENTS` sia identica tra GM, Neuron e NeuRAG |
| `tests/test_gme_root_platform.py` | Test cross-platform su `gme_root()` e `user_base()` |
| `tests/test_gui_bundling.py` | Test che il control center web si apra correttamente |
| `tests/test_handshake.py` | Verifica che gli hook SessionStart siano byte-identici in tutti e 3 i repo |
| `tests/test_installer_parity.py` | Verifica che tutti e 3 i progetti abbiano install.cmd/sh/command |
| `tests/test_version_parity.py` | Verifica che tutti e 3 i CLI rispondano a `--version` |

### File modificati

#### `cli.py`
- Aggiunto `--version` globale (prima dei subparser) — risolve il bug dove `gray-matter --version` moriva con argparse usage error
- `register` e `install` ora accettano `--client` (all | detected | ask | comma-separated)
- Gateway model: `cmd_install` delega la scelta client a `resolve_clients`

#### `clients.py`
- **Supporto VS Code `mcp.json`** (VS Code 1.102+): cerca `User/mcp.json` PRIMA di `settings.json`
- `_vscode_keys_for()`: nesting keys diverso a seconda del file
- **Windsurf**: nuovo client Cognition (Codeium `mcp_config.json` + VS Code-fork `mcp.json`)
- **Codex CLI**: nuovo client con formato TOML (`config.toml` + `_register_toml`)
- `resolve_clients()`: traduttore del selettore `--client`
- `_pick_clients_interactively()`: picker interattivo con detected pre-selezionati
- `detected_clients()`: rileva quali client hanno config esistenti
- `register()` ora accetta `only=`, gateway mode evita peer double-register
- `keys_for()`: dispatcher che usa `keys_for` per-client quando presente
- TOML writer: upsert/remove di sezione mirata, mai overwrite del file

#### `executor.py`
- `_find_clients_root()` ora cerca ANCHE in `neurag` (non solo `neuron`) per gli assets handshake
- `execute_install()` accetta `only=` per filtrare i client

#### `gme.py`
- **`user_base()`**: nuova funzione per-OS unificata (macOS ora usa `~/.local/share` invece di `~/Library/Application Support`)
- `_legacy_macos_root()`: fallback per install esistenti su macOS
- `gme_root()`: usa `user_base()` + legacy detection
- `_find_venv_for()`: sostituita copia manuale con `user_base()`

#### `webgui.py`
- **`/logo.png`**: route GET per logo (evita base64 inline)
- **MCP Clients panel**: `clients_state()` + `clients_register()` — API per detect + verify + merge
- **Self-test fix**: `GM_GUI_SELFTEST_TIMEOUT` (default 45s) e attesa evento `loaded` invece di sleep fissa

#### `webgui.html`
- Pannello MCP Clients: detect/verify/register con checkbox, dot status, problemi evidenziati
- Logo nell'header (servito da `/logo.png`)
- Stringhe IT/EN per il nuovo pannello

#### `install.ps1` / `install.sh`
- **`$Ask` gate**: unico flag "non chiedere" per tutti i prompt
- Peer discovery ora rispetta `GM_NO_NEURON` / `GM_NO_NEURAG`
- **Selezione embedding model** (full-suite path): menu 4 modelli + download one-time
- `--client` propagation: `$ClientSel` → `gray-matter install --client`
- **Terminatore esplicito**: `[OK] INSTALL COMPLETE - Gray Matter X.Y.Z`
- `-Yes` / `GM_YES` gate per installer headless
- Read-Host con try/catch: non blocca più su GUI installer senza stdin

#### `paths.py`
- `_neurag_dir_fallback()`: regola "vault esistente vince" per NeuRAG (`~/.local/share` vs `%LOCALAPPDATA%`)

### File eliminati

| File | Motivo |
|------|--------|
| `gui.py` | Sostituito da `webgui.py` (unico entry point GUI) |

---

## 2. Neuron

**23 file | 1653 insertions | 586 deletions**

### Nuovi file

| File | Descrizione |
|------|-------------|
| `src/neuron/clients/cowork-plugin/neuron-guard/hooks/neuron_sessionstart_hook.py` | Handshake per Cowork (byte-identico a Claude Code hook) |
| `src/neuron/clients/deploy_hooks.py` | Deployer handshake per standalone (Claude Code + OpenCode + Cowork mirror) |
| `tests/test_user_env.py` | Test per `set_user_env()` / `user_env_file()` |
| `tests/test_version_flag.py` | Test per `--version` su tutti i CLI |

### File modificati

#### `src/neuron/__main__.py`
- **Fix `--version` bloccante**: `neuron --version` avviava il server MCP e bloccava su stdin. Ora stampa versione ed esce.
- Guardia per flag sconosciuti: non parte più come server MCP con `--help` o refusi

#### `src/neuron/_env.py`
- **Doppio `.env`**: ora carica PRIMA il `.env` di progetto (walk-up), POI il per-user (`user_env_file()`)
- `_read_env_file()`: funzione estratta per riuso
- `_user_env_file()`: lazy import di `neuron.config.user_env_file()`

#### `src/neuron/clients.py`
- **VS Code `mcp.json`**: stessi fix di GM (`vscode_candidates()`, `vscode_keys_for()`)
- **Windsurf**: nuovo client con doppia configurazione
- `resolve_clients()` / `_pick_clients_interactively()`: selettore interattivo
- `detected_clients()`: rilevamento
- `register()`: guardia `dry_run` + `GM_NO_CLIENT_REGISTER` env
- `deregister()`: ora SWEEP su TUTTI i file del client (non solo il più recente)
- TOML writer per Codex

#### `src/neuron/config.py`
- `user_data_dir()`: funzione pubblica per la root dati per-OS
- `user_env_file()`: percorso del `.env` per-utente (sopravvive a qualsiasi cwd)
- `set_user_env()`: merge key-value nel per-user `.env` (legge/scrittura con BOM support)

#### `src/neuron/tunnel.py`
- `_tunnel_config_path()`: ora usa `gray_matter.gme.gme_root()` (lazy import) invece di copia manuale
- Fix bug macOS (tunnel.json in cartella sbagliata) e `LOCALAPPDATA` vuoto (path relativo)

#### `install.ps1` / `install.sh`
- **Auto-install Python su Windows**: scarica 3.14.x da python.org se assente (per-user, no admin)
- **Selezione embedding model**: menu 4 modelli + download one-time (persiste in `user_env_file()`)
- `Invoke-Tool`: fallback `python -m neuron` se `neuron.exe` non trovato (venv danneggiato)
- Handshake assets deploy per standalone
- Bootstrapping GM ora come **sibling** (non più in `.gm-bootstrap/`), via `git clone` prima di zip
- **Terminatore esplicito**: `[OK] INSTALL COMPLETE - Neuron X.Y.Z (standalone)`
- Modalità "Neuron only": [S]tandalone vs [G]et Gray Matter (seconda scelta)
- `-Yes` gate unificato

#### `docs/CORE_AUDIT.md` / `docs/DEVELOPER.md`
- Rimosso `NeuronInstaller.exe` dalla documentazione
- Documentato il nuovo setup Python auto-install
- Aggiornati path e struttura del progetto

#### `src/neuron/clients/claude-code-hook/neuron_sessionstart_hook.py`
- **Riscritto completamente**: ora supporta `gray-matter > neuron > neurag` priority
- Tool-name prefix DINAMICO (non più hardcoded `mcp__gray-matter__`)
- Gateway + peers: annuncia solo capabilities realmente installate
- `installed_slugs()`: legge GME registry (stdlib only, mai import dei peer)
- KEEP IN SYNC: copia byte-identica in tutti e 3 i repo

#### `src/neuron/clients/cowork-plugin/neuron-guard/hooks/hooks.json`
- Riattivato SessionStart hook con matcher startup|resume|clear|compact

#### `src/neuron/clients/opencode-plugin/neuron-handshake.mjs`
- **Riscritto**: Owner risolto da GME registry a runtime (non più deploy-time)
- `handshakeFor()`: selettore capability-based
- Nessun prefix hardcoded
- Keep-in-sync: stessi blocchi testo del Python hook

### File eliminati

| File | Motivo |
|------|--------|
| `installer/NeuronInstaller.cs` | Bootstrapper C# rimosso (sostituito da `install.cmd`) |
| `installer/README.md` | Doc del bootstrapper orfana |
| `installer/build-installer.ps1` | Script build orfano |

---

## 3. NeuRAG

**24 file | 1821 insertions | 65 deletions**

### Nuovi file

| File | Descrizione |
|------|-------------|
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | Handshake per Claude Code |
| `clients/cowork-plugin/neuron-guard/.claude-plugin/plugin.json` | Plugin manifest Cowork |
| `clients/cowork-plugin/neuron-guard/README.md` | Istruzioni plugin Cowork |
| `clients/cowork-plugin/neuron-guard/hooks/hooks.json` | Config hook Cowork |
| `clients/cowork-plugin/neuron-guard/hooks/neuron_sessionstart_hook.py` | Handshake Cowork |
| `clients/cowork-plugin/neuron-guard/skills/neuron-usage/SKILL.md` | Skill di usage |
| `clients/deploy_hooks.py` | Deployer handshake per standalone |
| `clients/opencode-plugin/neuron-handshake.mjs` | Plugin OpenCode |
| `skills/usage.md` | Skill retrieval workflow |
| `tests/test_embed_settings.py` | Test per risoluzione modello embedding |
| `tests/test_paths_data_dir.py` | Test per data_dir() e legacy fallback |

### File modificati

#### `cli.py`
- Aggiunto `--version` globale — fix stesso bug degli altri repo

#### `clients.py`
- **Matrice CLIENTI completa**: ora identica a Neuron (VSCode mcp.json, Windsurf, Zed, Codex TOML)
- `toml_upsert_section()`: upsert mirato per Codex
- `codex_entry_lines()`: formato entry Codex
- `vscode_candidates()` / `vscode_keys_for()`: stessi fix VS Code
- `windsurf_candidates()`: nuovo client
- `resolve_clients()` / `detected_clients()` / `_pick_clients_interactively()`
- `register()`: supporto TOML + `dry_run` guard + `GM_NO_CLIENT_REGISTER`
- `deregister()`: sweep su TUTTI i file del client

#### `embedder.py`
- **`_resolve_model()`**: env → persisted setting → default multilingue
- **`_resolve_dim()`**: non più hardcoded 384 — legge `NEURAG_EMBED_DIM` / `NS_EMBED_DIM` / `embed_dim` da settings

#### `paths.py`
- `_user_base()`: funzione unificata per-OS (allineata a Neuron/GM)
- `legacy_data_dir()`: dove NeuRAG ha sempre scritto
- `data_dir()`: vault esistente vince — Windows ora usa `%LOCALAPPDATA%\neurag` con fallback a `~/.local/share/neurag`

#### `pyproject.toml`
- Inclusi `skills/*.md` e `clients/**/*` nel pacchetto wheel

#### `server.py`
- **Tool `skill`**: Nuovo MCP tool che serve `skills/usage.md` su richiesta
- `_read_skill()`: via `importlib.resources` (wheel) con fallback source checkout

#### `settings.py`
- `embed_model` / `embed_dim`: nuove impostazioni persistenti
- `embed_model` suggest: lista allineata a install.ps1 (incluso "" per seguire Neuron)

#### `install.ps1` / `install.sh`
- Stesso pattern degli altri due: embedding model prompt, `-Yes` gate, terminatore esplicito, auto-Python

---

## 4. Modifiche Trasversali

### Handshake unificato (tutti e 3 i repo)

Il **SessionStart hook** ora è un unico file `neuron_sessionstart_hook.py` **byte-identico** in tutti e 3 i repo. Ownership risolta a runtime via GME registry:

```
gray-matter installed?  -> Gray Matter parla (gateway)
else neuron?            -> Neuron parla     (standalone)
else neurag?            -> NeuRAG parla     (standalone)
else                    -> silenzio
```

Il tool-name prefix non è più hardcoded: ogni client decide il suo (`mcp__<slug>__*` per Claude, `<slug>_*` per OpenCode). Non annuncia capabilities non installate.

### VS Code mcp.json (tutti e 3)

VS Code 1.102+ ha spostato i server MCP da `settings.json` a `User/mcp.json`. I tre repo ora cercano `mcp.json` PRIMA, con chiavi di accesso diverse:
- `mcp.json` → `{"servers": {...}}` (root)
- `settings.json` → `{"mcp": {"servers": {...}}}` (annidato)

### Matrice CLIENTI unificata

Tutti e 3 i repo espongono gli stessi 9 client:

| Client | Config |
|--------|--------|
| claude-desktop | `claude_desktop_config.json` (classico + MSIX) |
| claude-code | settings.json hooks (CLI `claude mcp add`) |
| cursor | `.cursor/mcp.json` |
| vscode | `mcp.json` (1.102+) / `settings.json` (legacy) |
| zed | `settings.json` → `context_servers` |
| opencode | `opencode.json` → `mcp` |
| windsurf | `mcp_config.json` (Codeium) / `mcp.json` (VSCode fork) |
| codex | `config.toml` (formato TOML) |

`test_client_targeting.py` fallisce se la matrice dei 3 repo diverge.

### Embedding model selezionabile

Tutti e 3 gli installer ora permettono di scegliere il modello di embedding:

| # | Modello | Dim | Size | Note |
|---|--------|-----|------|------|
| 1 | `paraphrase-multilingual-MiniLM-L12-v2` | 384 | 220 MB | **Default** multilingue EN+IT |
| 2 | `all-MiniLM-L6-v2` | 384 | 90 MB | Solo inglese, piccolo e veloce |
| 3 | `paraphrase-multilingual-mpnet-base-v2` | 768 | 1.0 GB | Multilingue, più forte |
| 4 | `multilingual-e5-large` | 1024 | 2.2 GB | Multilingue, massima qualità |

Persistito nel per-user `.env`, scaricato one-time all'install. NeuRAG ora risolve DIM dinamicamente.

### --version unificato

Tutti e 3 i CLI ora rispondono a `--version` / `-V` — prima `gray-matter --version` e `neurag --version` morivano con argparse usage error, e `neuron --version` partiva come server MCP bloccando su stdin.

### Auto-install Python (Windows Neuron)

Neuron su Windows installa Python 3.14.x da python.org se nessun interprete 3.10-3.14 è trovato (per-user, senza admin, Include_pip + tcltk).

### Bootstrapping GM fuori da `.gm-bootstrap/`

Neuron (e NeuRAG in gateway mode) ora scarica Gray Matter come **sibling** nel parent della suite, non più in `.gm-bootstrap/` dentro il repo. Usa `git clone` prima, zip GitHub come fallback. Così GM può vedere i peer (neurag/) come fratelli.

### Per-user .env (neuron)

Il file `~/.local/share/neuron/.env` (o `%LOCALAPPDATA%/neuron/.env`) sopravvive a qualsiasi cwd — risolve il bug dove le impostazioni (embedding model, Turso creds) scritte in un `.env` di progetto erano invisibili a runtime perché l'MCP client spawna da cwd arbitraria.

---

## 5. feat/graph-and-chunk-ceiling — Gray Matter

**~~ main → origin/feat/graph-and-chunk-ceiling**  
**11 commit | 12 file | 1078 insertions | 44 deletions**

### Nuovi file

| File | Descrizione |
|------|-------------|
| `promote.py` | Promuove memoria semantica (Neuron) in conoscenza permanente (NeuRAG) |
| `tests/test_bridge_matching.py` | Bridge matching su token interi e identità tag |
| `tests/test_injection_budget.py` | Budget di contesto: quanto contesto iniettare senza saturare |
| `tests/test_promote.py` | Test per il ciclo promote memoria→conoscenza |

### Commit e modifiche

#### `1444877` — Fix install.sh line endings + .gitattributes
- `.gitattributes`: policy line-ending per evitare CR/LF drift

#### `8f78694` — Skip the console counter-proof when the runner has no console
- `tests/test_no_console_window.py`: test per ambienti senza console

#### `3e5af77` — Document NeuRAG's four layer commands in the catalog
- `catalog.py`: +43 righe di documentazione comandi layer

#### `6ce9f6a` — Check that no installer offers to skip the embedder
- `tests/test_installer_parity.py`: +48 righe, verifica che l'embedder non sia skippabile

#### `09a128a` — Document NeuRAG's confirm and related in the catalog
- `catalog.py`: +24 righe documentazione comandi confirm/related

#### `15ff245` — Match bridges on whole tokens and on tag identity, not on substrings
- **`bridges.py`**: matching su token interi + identità tag (non più substring match)
- **`server.py`**: adattato ai nuovi bridge matcher
- **`tests/test_bridge_matching.py`**: 120 righe di test

#### `8fde365` — Make injected context a budget instead of a side effect
- **`bridges.py`**: contesto iniettato come budget limitato
- **`server.py`**: +102 righe, logica budget injection
- **`settings.py`**: +51 righe, configurazione `injection_budget`
- **`tests/test_injection_budget.py`**: 159 righe di test

#### `3df68a5` — Put the memory budget under the user's control too
- **`server.py`**: budget esposto come parametro
- **`settings.py`**: `injection_budget` come impostazione utente
- **`tests/test_injection_budget.py`**: +15 righe

#### `edd9932` — Catalogue NeuRAG's reindex command
- `catalog.py`: +13 righe documentazione reindex

#### `abdff11` — Promote memory that proved itself into permanent knowledge
- **`promote.py`**: 119 righe — ciclo promote (Neuron → NeuRAG)
- **`catalog.py`**: +16 righe documentazione promote
- **`cli.py`**: +37 righe, subcomando `promote`
- **`server.py`**: +43 righe, tool MCP `promote`
- **`tests/test_promote.py`**: 143 righe di test

---

## 6. feat/graph-and-chunk-ceiling — NeuRAG

**~~ main → origin/feat/graph-and-chunk-ceiling**  
**18 commit | 15 file | 2628 insertions | 118 deletions**

### Nuovi file

| File | Descrizione |
|------|-------------|
| `HANDOFF.md` | Documento di handoff: stato del branch, verifiche, cosa resta |
| `tests/test_hebbian.py` | Apprendimento Hebbiano su conferme |
| `tests/test_layers.py` | Gradiente di attivazione (activation layers) |
| `tests/test_standalone_invariant.py` | Invarianti del vault standalone |
| `tests/test_tag_substrate.py` | Substrato tag: row invece di stringhe JSON |

### Commit e modifiche

#### `43cfe4d` — .gitattributes (line-ending policy)
- `.gitattributes`: policy allineata a Neuron

#### `78c4ec6` — Turn the link layer on, and stop silently truncating 77% of the vault
- **`DESIGN-EVOLUTION.md`**: +448 righe di design evolution
- **`chunker.py`**: chunker budget-aware
- **`db.py`**: link layer attivo + fix troncatura vault
- **`embedder.py`**: embedding astratto
- **`ingest.py`**: adattato ai link
- **`settings.py`**: +9 righe
- **`tests/test_chunker_budget.py`**: 175 righe
- **`tests/test_node_links.py`**: 155 righe

#### `8b6a868` — Make standalone NeuRAG able to embed, and fuse the two retrievers
- **`chunker.py`**: adattato
- **`db.py`**: due retriever fusi in uno
- **`embedder.py`**: embedding funzionante standalone
- **`pyproject.toml`**: dipendenze embedding
- **`tests/test_retrieval_hybrid.py`**: 158 righe
- **`tests/test_standalone_embedding.py`**: 110 righe

#### `a5e4c12` — Refuse an embedding-model change that would strand the vault, and add reindex
- **`cli.py`**: comando `reindex`
- **`db.py`**: guardia cambio modello embedding
- **`server.py`**: tool `knowledge_reindex`
- **`tests/test_reindex_guard.py`**: 185 righe

#### `8f6d3ff` — Make a tag a row, not a string in five JSON columns
- **`db.py`**: tag come row SQL, non più stringa JSON
- **`tests/test_tag_substrate.py`**: 201 righe

#### `499ea74` — Stop a semicolon in a comment from truncating the schema
- **`db.py`**: fix `_split_sql` (portato anche su Neuron)
- **`tests/test_tag_substrate.py`**: +19 righe

#### `f7d34e5` — Give every search result a score, and say which scale it is on
- **`db.py`**: score sempre presente, scala documentata
- **`reranker.py`**: adattato
- **`tests/test_retrieval_hybrid.py`**: +65 righe

#### `7217a4e` — Stop handing the stored vector back to callers
- **`db.py`**: vettori non più restituiti al chiamante
- **`tests/test_retrieval_hybrid.py`**: +14 righe

#### `d02e145` — Make the tag substrate visible where a vault gets audited
- **`db.py`**: audit esporta substrato tag
- **`tests/test_tag_substrate.py`**: +28 righe
- **`tests/test_standalone_invariant.py`**: 82 righe

#### `49cd161` — Point the splitter's rationale at its keep-in-sync twin in Neuron
- `db.py`: commento cross-reference

#### `540111b` — Give the vault an activation gradient instead of one flat shelf
- **`cli.py`**: comandi layer (activate/deactivate/freeze)
- **`db.py`**: gradiente di attivazione (336 righe)
- **`tests/test_layers.py`**: 396 righe

#### `a05631a` — Stop the installers offering the half of NeuRAG that does not work
- **`install.ps1`** / **`install.sh`**: installer ridotti
- **`db.py`**: fix
- **`pyproject.toml`**: dipendenze minime

#### `404b8a8` — Add the handoff for this branch
- `HANDOFF.md`: 136 righe

#### `a85598e` — Let the graph learn on confirmation, and reach what it learned
- **`db.py`**: apprendimento Hebbiano (159 righe)
- **`cli.py`**: comandi Hebbian
- **`server.py`**: tool MCP Hebbian
- **`tests/test_hebbian.py`**: 339 righe

#### `b8f1d17` — Let the tags leave the vault, so Gray Matter can join on them
- **`db.py`**: tag esportabili
- **`server.py`**: tool per esportazione tag
- **`tests/test_tag_substrate.py`**: +35 righe

#### `228fee7` / `e1eb212` — Update the handoff (P6 progress)
- `HANDOFF.md`: P6 a due terzi, injection budget documentato

---

## 7. feat/graph-and-chunk-ceiling — Neuron

**~~ master → origin/feat/graph-and-chunk-ceiling**  
**1 commit | 3 file | 98 insertions | 2 deletions**

### `9824417` — Stop a semicolon in a comment from truncating a schema

#### `src/neuron/db.py`
- Nuova funzione **`_split_sql(script)`**: split di script SQL rispettando i commenti `--`
- Il vecchio `split(";")` troncava uno statement se conteneva un `;` dentro un commento, lasciando lo schema senza una tabella
- Il bug era già emerso in NeuRAG (primo commento SQL in uno schema); fix portato su Neuron per keep-in-sync
- `ponytail:` non gestisce stringhe letterali — se uno schema futuro quota un `--`, serve un tokenizer vero

#### `tests/test_sql_script_split.py`
- 65 righe di test con commenti, statement multipli, edge case

#### `CHANGELOG.md`
- +13 righe changelog
