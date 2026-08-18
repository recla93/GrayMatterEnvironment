# NEURAG AUDIT — Stato del Core e Installer

> Generato: 2026-07-23. Scope: NeuRAG standalone, allineamento installer, release readiness.
> Contesto: release imminente — il core deve essere perfetto.

---

## 1. NeuRAG standalone: è funzionante?

### 1.1 Features che funzionano SENZA Gray Matter

| Feature | Modulo | Note |
|---------|--------|------|
| MCP Server (12 tools) | `server.py` | Zero dipendenza GM (heartbeat opzionale) |
| CLI completo (18 subcommand) | `cli.py` | status, chunk, add-node, add-chunks, query, tree, import, ingest, rename-node, remove-node, health, doctor, config, repair, record-paths, register, deregister, go-standalone, gui |
| Knowledge graph (Turso/SQLite) | `db.py` | 3-tier: Turso cloud → pyturso → sqlite3 |
| Adaptive chunking (MD/Python/code/PDF/docx) | `chunker.py` | Puro stdlib + optional PyMuPDF/python-docx |
| Vector search (fastembed 384-dim) | `embedder.py` | Opzionale, fallback a lexical |
| Reranker (cross-encoder) | `reranker.py` | Off by default, opt-in |
| Auto-ingest pipeline | `ingest.py` | Sync + async background job |
| YAML bulk import | `importer.py` | Puro stdlib |
| Client registration (5 client) | `clients.py` | Slug: `neurag` |
| Desktop shortcut | `shortcut.py` | Cross-OS, zero dipendenza GM |
| Self-test | `selfcheck.py` | Eseguibile standalone |
| Config knobs | `settings.py` | rerank, pool, model |
| Path management | `paths.py` | SSOT, override via `NEURAG_HOME` |

### 1.2 Features che servono GM

| Feature | Dipendenza | Workaround |
|---------|-----------|------------|
| GUI web | `gray_matter.webgui` | Auto-bootstrap al primo `neurag gui` |
| Heartbeat registration | `gray_matter.clients` | Solo se GM presente, altrimenti niente |
| go-standalone release | `gray_matter.clients.release_tool` | try/except — se GM assente, stampa msg |

### 1.3 Verdetto

**NeuRAG standalone è pienamente funzionale** per la core use case (knowledge graph + chunking + search + MCP server). L'unica feature che serve GM è la GUI web (auto-bootstrap). Per la release, lo standalone è pronto.

---

## 2. Matrice dipendenze GM

| Modulo | Importa GM? | Riga/e | Condizionale? | Standalone? |
|--------|-------------|--------|---------------|-------------|
| `__init__.py` | No | — | — | Sì |
| `__version__.py` | No | — | — | Sì |
| `cli.py` | **Sì** | L144, L179, L218-224 | try/except ImportError | Sì |
| `clients.py` | **Sì** | L458-464 | `gm_still_manages` + `_guard_direct_register` | Sì |
| `server.py` | **Sì** | L18-21, L377-391 | try/except modulo level + runtime guard | Sì |
| `db.py` | No | — | — | Sì |
| `settings.py` | No | — | — | Sì |
| `paths.py` | No | — | — | Sì |
| `models.py` | No | — | — | Sì |
| `chunker.py` | No | — | — | Sì |
| `embedder.py` | No | — | — | Sì |
| `reranker.py` | No | — | — | Sì |
| `ingest.py` | No | — | — | Sì |
| `importer.py` | No | — | — | Sì |
| `selfcheck.py` | No | — | — | Sì |
| `shortcut.py` | No | — | — | Sì |

**Totale**: 3 moduli su 16 importano GM, tutti condizionali. Il core è 100% standalone.

---

## 3. MCP Server — 12 tools esposti

| Tool | Descrizione | Richiede DB? |
|------|-------------|-------------|
| `knowledge_ingest` | Graph-ize cartella (background job) | Sì |
| `knowledge_ingest_status` | Poll status job | Sì |
| `knowledge_index` | Chunk file/dir a JSON (no save) | No |
| `knowledge_add_node` | Crea nodo nella gerarchia | Sì |
| `knowledge_add_chunks` | Allega chunk a nodo | Sì |
| `knowledge_query` | Cerca nella knowledge base | Sì |
| `knowledge_status` | Engine, nodi, chunk, embedded | Sì |
| `knowledge_tree` | Stampa gerarchia | Sì |
| `knowledge_health` | Audit strutturale | Sì |
| `knowledge_link_graph` | Tutti i link con weight + evidence | Sì |
| `knowledge_rebuild_links` | Clear + rebuild tag_overlap + cross_ref | Sì |
| `knowledge_neighbors` | BFS neighborhood (depth 1-3) | Sì |

---

## 4. DB Layer — 3-tier

| Tier | Engine | Vector Search | Trigger |
|------|--------|--------------|---------|
| **Cloud** | `libsql_client` (remote Turso) | SQL `vector_distance_cos` | `NEURAG_TURSO_DATABASE_URL` + `NEURAG_TURSO_AUTH_TOKEN` |
| **Local** | `pyturso` (Rust extension) | SQL `vector_distance_cos` via `f32blob()` | Auto-detect se importabile |
| **Base** | `sqlite3` (stdlib) | Python brute-force cosine + TF-IDF | Fallback |

### pyturso status

**Mandatory** in `pyproject.toml` (`pyturso==0.6.1`). Wheel vendorati in `vendor/` per Windows 3.10-3.14. Il fallback sqlite3 esiste come difesa (concurrent-open race, install corrotta), non come tier opzionale.

### Schema (3 tabelle)

- **nodes**: id, name, node_type, parent_id, path, tags, triggers, created_at
- **chunks**: id, node_id, text, source, section, chunk_index, embedding (BLOB 384-dim), created_at
- **node_links**: source_id, target_id, link_type, weight, evidence, timestamps

---

## 5. Client Registration

### Slug: `"neurag"`

| Client | Config path | Entry |
|--------|------------|-------|
| Claude Desktop | `%APPDATA%/Claude/claude_desktop_config.json` + MSIX | `{"command": py, "args": ["-m", "neurag.server"]}` |
| Claude Code | `~/.claude.json` | `claude mcp add` (preferito) o file edit |
| Cursor | `~/.cursor/mcp.json` | `{"command": py, "args": ["-m", "neurag.server"]}` |
| VS Code | `%APPDATA%/Code/User/settings.json` | `{"type": "stdio", "command": py, "args": [...]}` |
| OpenCode | `~/.config/opencode/opencode.json` | `{"command": [py, "-m", "neurag.server"], "type": "local"}` |

### Funzionalità registration

- Non-destructive merge
- Backup `.neurag-bak` prima di ogni write
- Verify-after-write + rollback su fallimento
- JSONC tolerance (legge ma non riscrive)
- Claude Code: preferisce `claude mcp add` CLI
- GM guard: blocca registrazione diretta se GM gestisce ancora NeuRAG

### Client mancanti (vs Neuron)

NeuRAG registra in **5 client**. Neuron ne registra **7**. Mancano:
- **Zed** — `~/.config/zed/settings.json`
- **Codex CLI** — `~/.codex/config.toml`

---

## 6. Installer: è allineato alla realtà?

### 6.1 Cosa fa install.ps1 (standalone)

| Passo | Operazione | Allineato? |
|-------|-----------|-----------|
| 1 | Trova Python 3.10+ | Sì |
| 2 | Crea venv `%LOCALAPPDATA%\neurag\.venv` | Sì |
| 3 | pip install con `--find-links vendor/` | Sì |
| 4 | `neurag doctor` | Sì — check passivo |
| 5 | `neurag gui --shortcut-only` | Sì — crea icona Desktop |
| 6 | **Stampa** istruzioni manuali per registrazione | **NO** — dovrebbe chiamare `register --client all` |

### 6.2 BUG PRINCIPALE: Nessuna registrazione automatica standalone

**Dove**: `neurag/install.ps1:62-68`, `neurag/install.sh:50-55`

```powershell
# install.ps1 — standalone
& (Join-Path $Venv "Scripts\neurag.exe") doctor
# ... stampa istruzioni manuali ...
Write-Host "  `"neurag`": { `"command`": `"$Mcp`" }"
```

**Problema**: L'installer standalone NON chiama `neurag register --client all`. A differenza di Neuron (che lo fa a `neuron/install.ps1:62`), NeuRAG richiede registrazione manuale. Il comando `register` esiste e funziona perfettamente — non viene solo chiamato.

**Confronto con Neuron**:
```powershell
# neuron/install.ps1:62 — AUTO-REGISTRA
& (Join-Path $Venv "Scripts\neuron.exe") register --client all
```

**Fix**:
```powershell
# neurag/install.ps1 — dopo "neurag doctor", prima del print:
& (Join-Path $Venv "Scripts\neurag.exe") register --client all
```

### 6.3 Dialog 2 opzioni (non 3)

```powershell
$ans = Read-Host "Install Gray Matter (recommended)? [Y/n]"
```

Solo Y/n. Mancano le 3 opzioni `[S]ì / [N]o / [D]ettagli` richieste dall'utente.

### 6.4 Discrepanze testuali

| Affermazione | Realtà |
|---|---|
| `install.cmd` header: "Runs the unified Gray Matter installer" | Esegue `install.ps1`, che NON è l'installer GM — è un orchestrator che PUÒ delegare a GM |
| `install.ps1` header: "launcher for the UNIFIED Gray Matter installer" | Fuorviante. Prova GM ma fallback standalone |
| "Desktop icon 'NeuRAG' opens the control center (installs GM on first click)" | Vero, ma l'utente potrebbe non realizzare che il click triggera un install GM |
| `pyproject.toml`: pyturso è mandatory | `db.py` ha ancora il fallback sqlite3 — i due layer mandano segnali diversi |

---

## 7. Issues minori trovate

### ISSUE-1: `test_node_links.py` usa `:memory:` in modo errato

```python
def _kg():
    return KnowledgeGraph(pathlib.Path(":memory:"))
```

Passa `Path(":memory:")` → crea un file letteralmente chiamato `:memory:` su disco. SQLite tratta un Path come file path, non come DB in-memory. Per DB in-memory bisogna passare la stringa `":memory:"` direttamente.

**Impatto**: probabilmente funziona (i test non ispezionano il file), ma lascia un file `:memory:` orfano su disco dopo i test.

### ISSUE-2: `db.py` importa moduli pesanti a module level

```python
from neurag.chunker import chunk_file, scan_directory
from neurag.embedder import get_embedder
from neurag.reranker import get_reranker
```

Questi import girano al load time di `db.py`. Se `db.py` viene importato (es. da `server.py`), carica `fastembed` (380MB) anche se non servono embedding. Attualmente non è un problema (`db.py` è lazy-importato), ma viola il pattern CLI-fast documentato in `cli.py:8-12`.

### ISSUE-3: `reranker.py` legge settings a import time

```python
_MODEL = (os.environ.get("NEURAG_RERANK_MODEL")
          or settings.get("rerank_model")
          or "Xenova/ms-marco-MiniLM-L-6-v2")
```

Se il config file è corrotto, fallisce silenziosamente al default.

---

## 8. Confronto Neuron vs NeuRAG

| Aspetto | Neuron | NeuRAG |
|---------|--------|--------|
| Moduli core | 22 | 16 |
| Import GM | 3 (conditional) | 3 (conditional) |
| MCP tools | 18+ | 12 |
| Client registration | 7 client (Zed, Codex inclusi) | 5 client (nessuno Zed/Codex) |
| Slug | `neuron5` (da cambiare in `neuron`) | `neurag` (corretto) |
| Auto-register standalone | **Sì** (`register --client all`) | **NO** — stampa manuale |
| pyturso | Mandatory | Mandatory |
| Desktop shortcut | Standalone (zero GM) | Standalone (zero GM) |
| GUI auto-bootstrap | Sì | Sì |
| Test suite | 34 file, 38 ref a `neuron5` | 5 file |
| `.fuse_hidden*` nel repo | 62 file | No |

---

## 9. Piano di fix per la release

### Fix P0 — obbligatori

| # | Fix | File | Note |
|---|-----|------|------|
| **1** | Auto-register standalone | `neurag/install.ps1:62`, `neurag/install.sh:50` | Aggiungere `neurag register --client all` dopo `doctor` |
| **2** | Dialog 3 opzioni | `neurag/install.ps1:30-36`, `neurag/install.sh:20-28` | `[S]ì / [N]o / [D]ettagli` |
| **3** | Aggiungere Zed + Codex ai client | `neurag/clients.py` | Stessa matrice di Neuron |

### Fix P1 — consigliati

| # | Fix | Note |
|---|-----|------|
| **4** | Fix `test_node_links.py` `:memory:` | Passare stringa, non Path |
| **5** | Lazy import in `db.py` | Deferire chunker/embedder/reranker |
| **6** | Header install.cmd/ps1 fuorvianti | Correggere "unified Gray Matter installer" |

### Fix P2 — post-release

| # | Fix | Note |
|---|-----|------|
| **7** | `reranker.py` import-time settings | Lazy-load il config |

---

## 10. Checklist release

### Installer (P0)
- [ ] `neurag register --client all` chiamato in standalone
- [ ] Dialog 3 opzioni `[S]ì / [N]o / [D]ettagli`
- [ ] Header install corretti (non "unified Gray Matter installer")

### Client (P0)
- [ ] Zed aggiunto a `clients.py`
- [ ] Codex aggiunto a `clients.py`

### Test (P1)
- [ ] `test_node_links.py` — fix `:memory:` Path → string

### Verifica (P0)
- [ ] `neurag register --client all` registra `neurag` in 7 client
- [ ] `neurag doctor` mostra stato corretto
- [ ] `neurag gui` funziona standalone (auto-bootstrap GM)
- [ ] MCP server risponde con 12 tools

---

## 11. Analisi Core Pipeline: estruzione → chunking → embedding → ricerca → ingest

> Scope: bug, code smell, discrepanze nei 6 moduli core.

### 11.1 Pipeline flow (architettura)

```
knowledge_ingest (MCP/CLI)
  └─ ingest.py: start_job() → background thread
       └─ ingest_directory(root)
            ├─ create godnode (root)
            ├─ per subdirectory → add_node() → create node
            └─ index_directory_into_node() → per file:
                 ├─ chunker.chunk_file() → [Chunk(text, source, section, tags)]
                 ├─ db.add_chunk() → _get_embedding() → pack → INSERT
                 └─ add_triggers() from code symbols
```

### 11.2 Bug e code smell

| # | Severità | Modulo:Riga | Problema | Impatto |
|---|----------|-------------|----------|---------|
| **CP-1** | P2 | `db.py:589-591` | `find_node_by_trigger` usa `LIKE '%"keyword"%'` su JSON. Se keyword contiene `%` o `_` (wildcard SQLite), matcha falsi positivi. | Low — le query vengono da MCP tools, non input diretto utente |
| **CP-2** | P2 | `db.py:721-758` | `get_neighbors` BFS: chiama `get_node()`, `get_children()`, `get_links()` per ogni nodo del frontier (N+1 pattern SQL). A depth=3 con molti nodi, molte query singole. | Medium — risolvibile con batch `IN (...)` |
| **CP-3** | P2 | `db.py:867-868` | `search_with_links`: chiama `get_links()` per ogni result node separatamente (N+1). Per 10 risultati = 10 query extra. | Medium — stessa fix batch |
| **CP-4** | P3 | `db.py:948` | Fallback cosine: `SELECT * FROM chunks` carica tutti i chunk in memoria per Python cosine. Per DB grandi (>100k chunks), memoria e latenza. | Low — il fallback è per engine senza vettori |
| **CP-5** | P3 | `db.py:791-806` | `build_tag_links`: per ogni tag, genera tutte le coppie O(n²). Con un tag popolare e 1000 nodi = 500k coppie. | Low — accettabile per dimensioni ragionevoli |
| **CP-6** | P2 | `db.py:533` | `delete_node` disabilita FK enforcement. try/finally corretto, ma se un’eccezione non è catturata dal finally (es. kill del processo), FK resta off. | Low — ponytail comment documenta |

### 11.3 Note positive

- **chunker.py**: parsing solido — heading detection, code fence, token counting via tiktoken, fallback a split 1000 chars
- **embedder.py**: NullEmbedder always available, ONNX lazy-load, 384-dim fastembed
- **reranker.py**: Cross-encoder off by default, lazy-load, pool size configurabile
- **ingest.py**: Background job con progress tracking, sync + async, godnode auto-creation
- **server.py**: 12 MCP tools tutti implementati, auto-register con GM, heartbeat thread
- **db.py `search()`**: Two-stage architecture (retrieve + rerank) ben strutturata
- **db.py `health()`**: Audit strutturale completo (hierarchy, chunks, duplicates, orphans)

### 11.4 Raccomandazioni

| Priorità | Fix | Sforzo |
|----------|-----|--------|
| P2 | `get_neighbors` + `search_with_links`: batch SQL con `IN (...)` anziché N+1 | 2h |
| P2 | `find_node_by_trigger`: usare `json_each()` o escape dei wildcard | 1h |
| P3 | `build_tag_links`: lazy evaluation o threshold per tag troppo popolari | 1h |
- [ ] Test suite passa
