# RIEPILOGO DOCUMENTAZIONE — NEURAG

> Server MCP di knowledge base gerarchica persistente per LLM.
> Versione: 1.2.2 | Autore: Claudio Costantino | License: PolyForm Noncommercial 1.0.0

---

## 1. Documenti nella cartella `neurag/`

### Root
| File | Contenuto |
|------|-----------|
| `README.md` | Landing page: NeuRAG è un MCP server RAG local-first con vault gerarchico (godnode→fundamental→specialization), navigazione trigger-based, chunking adattivo (AST-aware per codice), ricerca semantica+lessicale (FastEmbed 384-dim + TF-IDF), cross-linking tra nodi, storage Turso/SQLite |
| `CHANGELOG.md` | Storia v0.2.0→v1.2.2. v1.2.2: config --json, repair --json, register guard, shortcut. v1.2.1: fix flash CMD. v1.2.0: standalone MCP registration, decoupled da GM. v1.1.x: server-side ingest, rename/remove-node, path SSOT, Turso fallback, reranker. v1.0.0: prima release stabile |
| `LICENSE` | PolyForm Noncommercial License 1.0.0 |
| `pyproject.toml` | v1.2.2, dipendenze: mcp≥1.28, pyturso==0.6.1. Extras: cloud, dev, pdf (PyMuPDF), docx (python-docx), yaml (PyYAML), semantic/rerank (fastembed), gui (gray-matter). Entry points: `neurag`, `neurag-mcp`. Flat layout |
| `DESIGN-CROSSLINKS.md` | Design cross-linking: tabella `node_links` (source, target, link_type, weight, evidence). 3 algoritmi: tag_overlap (Jaccard), cross_ref (trigger mentions), semantic (cosine). Test cases, complessità, API methods, 5-phase implementation plan |

### `docs/`
| File | Contenuto |
|------|-----------|
| `TOOLS.md` | MCP tools reference: 10 core tools con tabelle parametri |

### Sorgente Python (analisi moduli)
| Modulo | Funzione |
|--------|----------|
| `__init__.py` | Pacchetto root, v1.2.2. Bridge a Neuron per convenzione, non dipendenza |
| `server.py` | MCP server: 14 tool (`knowledge_ingest`, `ingest_status`, `index`, `add_node`, `add_chunks`, `query`, `status`, `tree`, `health`, `link_graph`, `rebuild_links`, `neighbors`, `remove_node`, `rename_node`, `import`). `knowledge_query`: trigger match prima, fallback semantico/lessicale dopo. Gray-Matter auto-registration con heartbeat |
| `db.py` (1192 righe) | Database layer: schema 3 tabelle (nodes, chunks, node_links). Storage 3-tier: Cloud Turso → local pyturso (native vector_distance_cos) → sqlite3 (Python cosine). `RemoteTursoConnection`: facade sqlite3-compatible su libSQL cloud con retry, buffered transactions. `KnowledgeGraph`: node CRUD, chunk operations con auto-embedding, link operations, search con optional reranker, health audit |
| `chunker.py` | Chunking adattivo: `chunk_markdown()` (split ## headings), `chunk_python_ast()` (1 chunk per top-level func/class), `chunk_code_generic()` (regex per Kotlin/Java/TS/JS/Rust/Go, cap 160 righe), `chunk_lines()` (60 righe plain text), `chunk_pdf()` (1 chunk per page), `chunk_docx()` (heading sections). Tag generation: subwords camelCase/snake_case, trigger candidates (max 8) |
| `cli.py` | CLI entry point: 20+ subcomandi. SSOT per Gray Matter GUI catalog. Comandi: inspect (status/tree/query/health/doctor), maintenance (chunk/add-node/add-chunks/import/ingest/rename/remove), tuning (config), lifecycle (repair/record-paths/register/deregister/go-standalone/gui). `_run_via_gm()`: routing write tramite single-writer GM |
| `clients.py` | Registrazione MCP client: matrix (claude-desktop, claude-code, cursor, vscode, opencode). Non-distruttivo: backup .neurag-bak, verify-after-write con rollback. `_guard_direct_register()` blocca doppia registrazione se GM gestisce ancora. `CREATE_NO_WINDOW` su Windows |
| `bridge.py` | HTTP bridge launcher: `resolve_neurag_cmd()`, `resolve_proxy_runner()` (mcp-proxy via uvx/uv/pipx), `preflight()`, tunnel launch, default port 8001 |
| `embedder.py` | Embedding textuale: `NullEmbedder` (zero cost), `FastEmbedEmbedder` (384-dim, lazy import). Default model: `paraphrase-multilingual-MiniLM-L12-v2` (allineato con Neuron) |
| `importer.py` | Import bulk da YAML mapping: deterministico, no LLM. `import_mapping(kg, path)`: legge YAML con godnode + nodes list, crea nodi e indicizza file |
| `ingest.py` | Server-side auto-ingest: folder → gerarchia → chunks → links in un colpo. `start_job()`: background thread (own DB connection), max 20 job. `rebuild_links()` a fine ingest |
| `models.py` | Data classes: `Chunk` (text, source, section, chunk_index, tags), `QueryResult` (text, source, section, score, chunk_index) |
| `paths.py` | SSOT tutti i path NeuRAG: `data_dir()` → `~/.local/share/neurag`, `db_path()`, `config_path()`, `source_dir()`, `record_self()` (paths.json per self-knowledge/repair) |
| `reranker.py` | Cross-encoder reranker opzionale: `NullReranker` (identity), `FastEmbedReranker` (TextCrossEncoder). Default model: `Xenova/ms-marco-MiniLM-L-6-v2`. OFF di default |
| `selfcheck.py` | Self-test: 5 check (embedder null routing, lexical search TF-IDF, docx chunker, yaml import, health tiny chunks/orphans) |
| `settings.py` | Config persistente JSON: 3 knobs (rerank bool, rerank_pool int, rerank_model str). `HELP` e `SUGGEST` per GUI self-description |
| `shortcut.py` | Desktop shortcut cross-OS: Windows .lnk (WScript.Shell COM), macOS .command, Linux .desktop. Marker file idempotente. `CREATE_NO_WINDOW` |

---

## 2. Documenti ROOT che parlano di NeuRAG

| File | Rilevanza per NeuRAG |
|------|----------------------|
| `work/audit/NEURAG-TASKS.md` | Task di audit/manutenzione specifici per NeuRAG |
| `work/audit/PIANO-AZIONE.md` | Piano d'azione condiviso (include NeuRAG) |
| `NeuRAGAudit.md` | Audit specifico del componente NeuRAG |
| `ARCHITETTURA.md` | Architettura 3 componenti (NeuRAG è uno dei 3) |
| `DESIGN-RAG-OPTIMIZATION-2026-07-22.md` | Ottimizzazione RAG (NeuRAG) |
| `GRAY-MATTER-COMPENDIUM.md` | Compendio condiviso (include NeuRAG) |
| `FIX-TASKLIST.md` | Tasklist fix (include NeuRAG) |
| `RELEASE-CHECKLIST.md` | Release checklist (include NeuRAG) |
| `docs/OVERVIEW.md` | Overview (NeuRAG = knowledge base) |
| `docs/ARCHITECTURE.md` | Architettura (NeuRAG nel gateway, 3-tier search) |
| `docs/DATA.md` | Schema DB NeuRAG (3 tabelle: nodes, chunks, node_links) |
| `docs/CONFIGURATION.md` | 7 env vars NeuRAG (NEURAG_EMBEDDER, NEURAG_TURSO_*, rerank), paths |
| `docs/TOOLS.md` | 10 MCP tool NeuRAG documentati |
| `docs/TECHNOLOGY.md` | Decisioni tech (Turso per storage, fastembed per embeddings) |
| `docs/EVOLUTION.md` | Evoluzione (NeuRAG introdotto in Era 0) |
| `docs/DEV-DIARY.md` | Diario sviluppo (NeuRAG: v0.2.0→v1.0.0) |
| `docs/TROUBLESHOOTING.md` | Troubleshooting entries su NeuRAG |
| `docs/GETTING-STARTED.md` | Tutorial (knowledge_index → knowledge_add_node → knowledge_add_chunks → knowledge_query) |
| `docs/CLI.md` | CLI reference NeuRAG (entry: `neurag`) |

---

## 3. Architettura Concettuale di NeuRAG

- **Vault gerarchico**: godnode → fundamental → specialization (3 livelli)
- **Chunking adattivo**: AST-aware per Python, regex per Kotlin/Java/TS, plain line splitting
- **Search 3-tier**: trigger match → vector SQL → Python brute-force
- **Cross-linking**: tag_overlap (Jaccard), cross_ref (trigger mentions), semantic (cosine mean)
- **Storage 3-tier**: Cloud Turso → local pyturso → sqlite3
- **Optional components**: embedder (semantica), reranker (precision boost), bridge (HTTP exposure)
- **Gray Matter integration opzionale**: NeuRAG funziona standalone
- **Ingest server-side**: auto-ingest folder → gerarchia → chunks → links in background
