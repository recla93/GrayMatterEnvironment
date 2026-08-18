# NEURON AUDIT — Stato del Core e Slug

> Generato: 2026-07-23. Scope: Neuron standalone, slug `neuron5` → `neuron`, allineamento installer.
> Contesto: release imminente — il core deve essere perfetto.

---

## 1. Neuron standalone: è funzionante?

### 1.1 Features che funzionano SENZA Gray Matter

| Feature | Modulo | Note |
|---------|--------|------|
| MCP Server (la funzionalità principale) | `server.py` | Zero dipendenza GM |
| Tutti i CLI | `__main__.py` | register, doctor, setup, manage, consolidate, bridge, tunnel, console, connect, init, repair, record-paths, go-standalone |
| Estrazione semantica | `extraction.py` | Heuristic, zero GM |
| Vector search (fastembed 384-dim) | `search.py` | pyturso → sqlite3 fallback |
| Curation keyword | `curation.py` | Quality gate, stdlib-only |
| Multi-context registry | `registry.py` | GraphRegistry |
| Bridge HTTP | `bridge.py` | Espone stdio su HTTP |
| Tunnel HTTPS | `tunnel.py` | Via cloudflared |
| Registrazione client MCP (7 client) | `clients.py` | Claude Desktop, Claude Code, Cursor, VS Code, OpenCode, Zed, Codex |
| Desktop shortcut | `shortcut.py` | Tool-local, zero dipendenza GM |
| Repair/self-healing | `setup.py`, `__main__.py` | --wipe-memory, --reinstall |
| GUI auto-bootstrap | `__main__.py:136-180` | Installa GM al primo `neuron gui` |

### 1.2 Features che servono GM

| Feature | Dipendenza | Workaround |
|---------|-----------|------------|
| GUI web | `gray_matter.webgui` | Auto-bootstrap (installa GM al primo click) |
| Cross-store bridges (Neuron ↔ NeuRAG) | GM gateway | N/A — serve GM |
| Neighbor auto-surface | GM gateway | N/A — serve GM |

### 1.3 Verdetto

**Neuron standalone è pienamente funzionale per la core use case** (MCP server + memory + search + register). L'unica feature che serve GM è la GUI web, che si bootstrappa da sola. Per la release, lo standalone è pronto.

---

## 2. Il problema dello slug: `neuron5` hardcoded in 30 punti

### 2.1 Mappa completa delle occorrenze

#### Moduli core (Python)

| File | Riga | Codice | Impatto |
|------|------|--------|---------|
| `config.py` | 36 | `return os.environ.get("NEURON_SLUG", "neuron5")` | **SSOT** — tutti gli altri delegano qui |
| `config.py` | 35 | docstring: `"The install slug (default neuron5)"` | Documentazione |
| `config.py` | 47 | docstring: `"Uses NEURON_SLUG (default neuron5)"` | Documentazione |
| `server.py` | 401 | `app = Server("neuron5", version=__version__)` | **Identità MCP server** — i client la vedono |
| `clients.py` | 523 | `KNOWN_SLUGS = ("neuron", "neuron5")` | Backwards compat doctor |
| `clients.py` | 781 | `slug = slug or os.environ.get("NEURON_SLUG", "neuron5")` | Default per `default_server_python()` |
| `clients.py` | 835 | `ap.add_argument("--slug", default=os.environ.get("NEURON_SLUG", "neuron5"))` | Default CLI register/doctor |
| `setup.py` | 138 | `ap.add_argument("--slug", default=os.environ.get("NEURON_SLUG", "neuron5"))` | Default CLI setup |
| `__main__.py` | 118 | `slug = os.environ.get("NEURON_SLUG", "neuron5")` | Default go-standalone |
| `bridge.py` | 61 | `slug = os.environ.get("NEURON_SLUG", "neuron5")` | Default bridge |
| `project.py` | 87 | `slug = os.environ.get("NEURON_SLUG", "neuron5")` | Project identity |
| `manage.py` | 184 | `doctor(os.environ.get("NEURON_SLUG", "neuron5"), ...)` | Default manage |

#### Hook instruction files (testo statico, zero import)

| File | Riga | Cosa |
|------|------|------|
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | 31 | `mcp__neuron5__pre_turn` |
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | 33 | `mcp__neuron5__store_turn` |
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | 35 | `mcp__neuron5__find_candidates` |
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | 38 | `mcp__neuron5__help`, `mcp__neuron5__skill` |
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | 40 | `mcp__neuron5__*` |
| `clients/cowork-plugin/neuron-guard/hooks/neuron_handshake.py` | 25 | `mcp__neuron5__pre_turn` |
| `clients/cowork-plugin/neuron-guard/hooks/neuron_handshake.py` | 27 | `mcp__neuron5__store_turn` |
| `clients/cowork-plugin/neuron-guard/hooks/neuron_handshake.py` | 29 | `mcp__neuron5__find_candidates` |
| `clients/cowork-plugin/neuron-guard/hooks/neuron_handshake.py` | 32 | `mcp__neuron5__help`, `mcp__neuron5__skill` |
| `clients/cowork-plugin/neuron-guard/hooks/neuron_handshake.py` | 34 | `mcp__neuron5__*` |

#### Commenti e docstring (nessun impatto funzionale, solo leggibilità)

| File | Riga | Contesto |
|------|------|----------|
| `clients.py` | 544 | `"duplicate identities (both 'neuron' and 'neuron5') flagged"` |
| `clients.py` | 646 | `"both 'neuron' and 'neuron5' registered"` |
| `clients.py` | 738 | `"v4 'neuron' next to v5 'neuron5'"` |
| `clients.py` | 763 | `"duplicate keys (neuron AND neuron5)"` |
| `server.py` | 1901 | `"neuron5", v4 = "neuron"` |
| `neuron_sessionstart_hook.py` | 20 | `"registered under the key neuron5"` |
| `neuron_handshake.py` | 11 | `"server key neuron5"` |
| `neuron_handshake.py` | 14 | `"mcp__neuron5__* tools"` |

**Totale: 30 occorrenze** (12 funzionali + 10 hook instruction + 8 commenti/docstring)

### 2.2 Impatto del cambio `neuron5` → `neuron`

#### MCP tool names cambiano

Prima:
```
mcp__neuron5__pre_turn
mcp__neuron5__store_turn
mcp__neuron5__find_candidates
mcp__neuron5__help
mcp__neuron5__skill
mcp__neuron5__get_context
mcp__neuron5__status
mcp__neuron5__auto
mcp__neuron5__confirm
mcp__neuron5__summary
mcp__neuron5__switch_context
mcp__neuron5__list_contexts
mcp__neuron5__forgotten
mcp__neuron5__prune
mcp__neuron5__flash
mcp__neuron5__dedup
mcp__neuron5__export
mcp__neuron5__reset
mcp__neuron5__consolidate
mcp__neuron5__vector_search
mcp__neuron5__find_candidates
mcp__neuron5__merge
```

Dopo:
```
mcp__neuron__pre_turn
mcp__neuron__store_turn
... (stessi nomi, prefisso diverso)
```

**Attenzione**: i nomi tool MCP sono generati dal server come `Server("neuron5", ...)` + i nomi delle tool functions. Il prefisso `mcp__<server_name>__<tool>` è what the client uses. Cambiare il server name cambia tutti i prefissi.

#### Backwards compatibility

- Utenti con `neuron5` registrato nei client: dopo il upgrade, il vecchio entry resta (orphan). Il doctor dovrebbe rimuoverlo.
- `KNOWN_SLUGS = ("neuron", "neuron5")` va tenuto per il doctor (detect + cleanup).
- Hook instruction files devono essere aggiornati: se un utente ha il vecchio hook ma il nuovo server, i nomi tool non matchano → il modello non trova i tool.

#### Graph store path

`config.py:51-54`: `resolve_slug()` → `os.path.join(base, slug, "graphs")`

Con `neuron5`: `%LOCALAPPDATA%\neuron5\graphs`
Con `neuron`: `%LOCALAPPDATA%\neuron\graphs`

**Impatto**: i grafi esistenti restano nella cartella vecchia. Serve una migrazione o un symlink, oppure accettare la perdita del grafo esistente (accettabile per release early-stage).

---

## 3. Installer: è allineato alla realtà?

### 3.1 Neuron install.ps1

| Affermazione | Realtà | Allineato? |
|---|---|---|
| "Install Neuron STANDALONE" | Crea venv `%LOCALAPPDATA%\neuron\.venv`, pip install, register nei client | **Sì** |
| `neuron register --client all` | Registra **`neuron5`** (non `neuron`) nei 7 client | **No** — slug sbagliato |
| `neuron gui --shortcut-only` | Crea icona Desktop standalone (zero GM) | **Sì** |
| "Desktop icon opens control center (installs GM on first click)" | `neuron gui` fa auto-bootstrap GM | **Sì** |
| "Restart your AI apps" | Register sovrascrive i config file | **Sì** |
| Dialog "Install Gray Matter? [Y/n]" | Solo 2 opzioni, manca "Dettagli" | **No** — UX incompleta |

### 3.2 Neuron install.sh (macOS/Linux)

Stesse identiche有问题. L'unica differenza: `exec sh` blocca il fallback standalone (BASS-4).

### 3.3 Neuron install.cmd

Semplice wrapper: `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*` + `pause`. Funziona.

---

## 4. Piano di fix per la release

### Fix P0 — obbligatori prima della release

| # | Fix | File da modificare | Sfida |
|---|-----|-------------------|-------|
| **1** | Cambiare default slug da `neuron5` a `neuron` | `config.py:36` | **SSOT** — un solo punto, tutti gli altri delegano |
| **2** | Cambiare MCP server identity | `server.py:401` | `Server("neuron", ...)` |
| **3** | Aggiornare hook instruction files | 2 file, ~20 sostituzioni | `mcp__neuron5__*` → `mcp__neuron__*` |
| **4** | Aggiornare default nei moduli | clients.py:781,835, setup.py:138, __main__.py:118, bridge.py:61, project.py:87, manage.py:184 | Tutti delegano a config.py, ma hanno il default hardcoded |
| **5** | Installer: passare `--slug neuron` | neuron/install.ps1:62 | Oppure il nuovo default basta |
| **6** | Tenere `KNOWN_SLUGS = ("neuron", "neuron5")` | clients.py:523 | Backwards compat per doctor |

### Fix P1 — consigliati prima della release

| # | Fix | Note |
|---|-----|------|
| **7** | Dialog 3 opzioni Neuron/NeuRAG installer | `[S]ì / [N]o / [D]ettagli` |
| **8** | `$ErrorActionPreference = "Stop"` + stderr | Aggiungere `2>$null` ai comandi nativi |
| **9** | NeuRAG register automatico | `neurag register --client all` invece di `doctor` + manuale |
| **10** | Riepilogo post-install | Stampare cosa è stato installato |

### Fix P2 — post-release

| # | Fix | Note |
|---|-----|------|
| **11** | Migrazione grafo da `neuron5` a `neuron` | Symlink o copy automatico |
| **12** | Dialog repair da install.cmd GM | Check esistenza + prompt |
| **13** | Unificare installer Neuron/NeuRAG | `install-peer.ps1` parametrico |

---

## 5. Verifica completa moduli (approfondita)

### 5.1 Tutti i 20 moduli core Python

| Modulo | Importa GM? | Logica GM condizionale? | Standalone? | Note |
|--------|-------------|------------------------|-------------|------|
| `__init__.py` | No | No | Sì | |
| `_env.py` | No | No | Sì | Puro stdlib |
| `config.py` | No | No | Sì | SSOT path/slug |
| `paths.py` | No | No | Sì | Delega a config |
| `db.py` | No | No | Sì | 3-tier: Turso cloud → pyturso → sqlite3 |
| `models.py` | No | No | Sì | Node, Link, Graph |
| `extraction.py` | No | No | Sì | Puro stdlib |
| `curation.py` | No | No | Sì | Puro stdlib |
| `project.py` | No | No | Sì | Puro stdlib |
| `search.py` | No | No | Sì | Lazy coupling a server.py (ADR-006, intenzionale) |
| `funnel.py` | No | No | Sì | Skill delivery via importlib.resources |
| `init.py` | No | No | Sì | Puro stdlib |
| `connect.py` | No | No | Sì | Probe table cleanup potrebbe fallire silenziosamente |
| `console.py` | No | No | Sì | Legge .db locali, senza WAL mode |
| `tunnel.py` | No | No | Sì | Subprocess: cloudflared |
| `manage.py` | No | No | Sì | Operazioni quotidiane |
| `registry.py` | No | No | Sì | Multi-context GraphRegistry |
| `engine.py` | No | No | Sì | CLI interattivo, non production. reimplementa Node (divergence risk) |
| `setup.py` | No | No | Sì | Lifecycle CLI |
| `bridge.py` | No | No | Sì | Subprocess: mcp-proxy |
| `shortcut.py` | No | No | Sì | Icona desktop, zero dipendenza GM |
| `stimulus.py` | No | No | Sì | Lazy coupling a server.py (ADR-006, intenzionale) |

### 5.2 Entry point con logica GM (solo GUI)

| Modulo | Importa GM? | Dove? | Standalone? |
|--------|-------------|-------|-------------|
| `server.py` | No top-level | Solo inside `gui` subcommand (try/except) | Sì |
| `clients.py` | No top-level | Solo inside `gui` subcommand (try/except) | Sì |
| `__main__.py` | No top-level | Solo inside `gui` subcommand (try/except + bootstrap) | Sì |

### 5.3 Hook instruction files (testo statico)

| File | Dipendenze | Note |
|------|-----------|------|
| `clients/claude-code-hook/neuron_sessionstart_hook.py` | Nessuna | Stampa handshake, esce. Zero import. |
| `clients/opencode-plugin/neuron-handshake.mjs` | Nessuna | JS, experimental |
| `clients/cowork-plugin/neuron-guard/` | Nessuna | Plugin Claude Code, stesso pattern statico |

### 5.4 Verdetto bug

**Nessun bug funzionale trovato nel core Neuron.** Le uniche peculiarità note:
- `search.py` / `stimulus.py` lazy-coupling a `server.py` → intenzionale (ADR-006)
- `engine.py` reimplementa `Node` dataclass → non usato in produzione
- `console.py` senza WAL mode → edge case minore
- `connect.py` probe cleanup potrebbe fallire silenziosamente → best-effort

---

## 6. File orfani nel repo

### 6.1 `.fuse_hidden*` — 62 file in `neuron/src/neuron/data/`

Artifact di un mount FUSE (sshfs/gocryptfs). Il `.gitignore:62` ha `.fuse_hidden*` ma i file sono già tracked.

**Fix**: `git rm --cached src/neuron/data/.fuse_hidden*`

### 6.2 Test suite — 38 riferimenti a `neuron5`

| File | Match | Cosa testano |
|------|-------|-------------|
| `test_clients.py` | 33 | Registrazione, doctor, deregister con slug `neuron5` |
| `test_setup.py` | 5 | `do_status("neuron5", ...)`, `do_install("neuron5", ...)` |

**Fix**: aggiornare tutti i riferimenti a `neuron` quando lo slug cambia.

---

## 7. Checklist release

### Slug change (P0)
- [ ] `config.py:36` → default `neuron`
- [ ] `server.py:401` → `Server("neuron", ...)`
- [ ] Hook Claude Code → `mcp__neuron__*`
- [ ] Hook cowork → `mcp__neuron__*`
- [ ] Tutti i default nei moduli → `neuron` (clients.py, setup.py, __main__.py, bridge.py, project.py, manage.py)
- [ ] `KNOWN_SLUGS` tiene `("neuron", "neuron5")` per doctor backwards compat

### Installer (P0)
- [ ] Installer passa `--slug neuron` (o il nuovo default basta)

### Test (P0)
- [ ] `test_clients.py` → aggiornare 33 riferimenti a `neuron5`
- [ ] `test_setup.py` → aggiornare 5 riferimenti a `neuron5`

### Repo cleanup (P1)
- [ ] `git rm --cached` dei 62 `.fuse_hidden*` in `data/`

### Verifica (P0)
- [ ] `neuron register --client all` registra `neuron` (non `neuron5`)
- [ ] `neuron doctor` trova e segnala entry `neuron5` orfane
- [ ] `neuron gui` funziona standalone (auto-bootstrap GM)
- [ ] MCP server risponde come `neuron` (non `neuron5`)
- [ ] Test suite passa

---

## 8. Analisi Core Pipeline: extraction → search → stimulus → persistence

> Scope: bug, code smell, discrepanze nei 7 moduli core del pipeline Neuron.

### 8.1 Pipeline flow (architettura)

```
MCP call_tool (server.py)
  ├─ pre_turn → _resolve_context → _search_embeddings → context window
  ├─ store_turn → curation gate → add_node/add_link → save_sqlite
  ├─ auto → extract → store_turn (0-token fallback)
  └─ get_context → _resolve_context (link walk + vector fallback)
```

### 8.2 Moduli core e responsabilità

| Modulo | Riga | Responsabilità | Note |
|--------|------|----------------|------|
| `extraction.py` | 416 | Heuristic semantic extraction (0 token) | Accent folding, stop words, domain/intent/sentiment |
| `search.py` | 301 | Hybrid vector search (Turso SQL or Python cosine) | Seed DB caching, SIM_THRESHOLD=0.3 |
| `stimulus.py` | 256 | Context window + 3 semantic flash types | Anti-echo cooldown, spreading activation |
| `models.py` | 1668 | Graph (Node/Link) + persistence (SQLite/Turso) | Incremental delta saves, Hebbian reinforcement |
| `server.py` | 1926 | MCP server + 22 tool handlers | Curation gate, context inheritance, domain switch |
| `db.py` | 354 | 3-tier connection layer | Remote Turso retry, local pyturso L2 guard |
| `curation.py` | 144 | Keyword quality gate (T54) | Filler verb detection, near-dup remapping |

### 8.3 Bug e code smell

| # | Severità | Modulo:Riga | Problema | Impatto |
|---|----------|-------------|----------|---------|
| **NP-1** | P2 | `search.py:228` | `_normalize_domain` rimuove `-` e spazi prima di lookup alias, ma `DOMAIN_ALIASES` ha chiavi con `-` (es. `back-end`, `front-end`). `"back-end"` → `"backend"` (corretto), ma `"back-end-"` → `"backend"` (silenzioso). | Low — input viene da MCP tools, non utente diretto |
| **NP-2** | P2 | `stimulus.py:218` | `_stim_recent` è un dict a livello di modulo (non persistito). A restart del processo, l'anti-echo viene resettato e lo stesso stimulus può essere emesso di nuovo. | Low — il cooldown è anti-noise, non safety |
| **NP-3** | P3 | `models.py:1008` | `consolidate()` usa `itertools.combinations` su tutti i nodi con vettore — O(N^2). Con 500 nodi (MAX_NODES default) = 125k paia. Early termination aiuta ma il scan parte sempre. | Medium — documentato, ma 500 nodi è il default |
| **NP-4** | P3 | `models.py:1036-1040` | `_merge_into` modifica `lk.source`/`lk.target` in-place while iterating `self.links`. Se un link viene modificato e un altro link ha lo stesso source/target appena cambiato, potrebbe essere processato due volte. | Low — il link redirect è idempotente (a→s è lo stesso che b→s dopo merge) |
| **NP-5** | P2 | `server.py:948-949` | `_resolve_context` chiama `_search_embeddings` con `top_n=max(len(g.nodes), 1)` — per grafi grandi questo embedda e confronta tutti i nodi. | Medium — il Turso SQL ha un LIMIT, il fallback Python no |
| **NP-6** | P3 | `search.py:263-272` | `_refine_domain` fallback Python itera tutti i nodi di tutti i grafi caricati (`_graphs.values()`). Con molti contexti e grafi grandi, molte cosine calls. | Low — il Turso SQL path è preferito |
| **NP-7** | P2 | `server.py:1048` | `_tool_status` accede a `dedup_enabled` e `flash_enabled` che sono variabili globali del modulo server. Se non inizializzati (import ordine), NameError. | Low — `__init__.py` li inizializza prima |

### 8.4 Note positive

- **extraction.py**: Accent folding solido (`_fold_accents`), STOP_WORDS comprehensive (IT + EN + verb forms), compound entity promotion a keywords
- **search.py**: Seed DB caching con `weakref.ref(g)` per invalidazione, SIM_THRESHOLD=0.3 consistente tra Turso e Python
- **stimulus.py**: 3 flash types (dormant pulse, cross-domain spark, creative leap), anti-echo cooldown, spreading activation con decay
- **models.py**: Incremental delta saves (O(delta) vs O(graph)), atomic upserts con relative salience delta, Hebbian reinforcement, consolidation con merge + orphan drop, graveyard recoverable
- **server.py**: Curation gate (T54) con soft drop + in-context teaching, context inheritance parent chain, domain switch detection con hysteresis, loop compliance telemetry (T55), piggyback stimulus su ogni risposta
- **db.py**: 3-tier connection con retry + reconnect (T76), URL fallback (ws→https), L2 concurrent-open guard
- **curation.py**: Filler verb detection (IT + EN), near-dup remapping con singularization, `_AMBIGUOUS_ADJUNCTS` per compound legitimi

### 8.5 Raccomandazioni

| Priorità | Fix | Sforzo |
|----------|-----|--------|
| P2 | `_resolve_context`: limitare `top_n` in `_search_embeddings` a `min(len(g.nodes), 50)` | 0.5h |
| P2 | `_tool_init`: garantire che `dedup_enabled`/`flash_enabled` siano inizializzati prima di qualsiasi tool call | 1h |
| P3 | `consolidate()`: soglia提前 con `if len(nodes) < 50: return []` per grafi piccoli | 0.5h |
- [ ] Test: MCP server risponde come `neuron` (non `neuron5`)
