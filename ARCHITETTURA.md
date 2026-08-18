# Gray Matter Environment — Architettura

> Documento tecnico sulla suite: Neuron (memoria semantica), NeuRAG (knowledge
> base), Gray Matter (gateway/orchestratore). Aggiornato a luglio 2026.

---

## Visione generale

Gray Matter è un ecosistema **MCP (Model Context Protocol)** che dà agli agenti
AI **memoria persistente** tra le conversazioni. Tre componenti cooperano sotto
un unico gateway:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AI Client                                    │
│  (Claude Desktop, Cursor, OpenCode, Gemini CLI, Windsurf, etc.)    │
│                                                                     │
│  Registra: gray-matter (gateway)                                    │
│  Chiama:   gray_matter_pulse(topic) — memory + knowledge + flash    │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ stdio / TCP
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Gray Matter (Gateway)                             │
│  server.py + _worker.py + registry.py + cache.py + bridges.py      │
│  catalog.py + gme.py + shortcut.py + cli.py + webgui.py            │
│                                                                     │
│  Funzioni:                                                          │
│  • gray_matter_pulse() — unisce memoria + conoscenza + flash        │
│  • Context cache (TTL + LRU) con invalidazione mirata              │
│  • Cross-store bridges (Hebbian promotion/decay)                   │
│  • Semantic flash (associazioni laterali cadenzate)                │
│  • Pass-through per tutti i tool Neuron/NeuRAG                     │
│  • Catalogo comandi GUI (introspect argparse, no liste hardcodate) │
│  • Registry GME (multi-venv, health tracking)                      │
│  • Desktop shortcut (cross-platform: .lnk/.command/.desktop)       │
└───────────────┬─────────────────────────────┬───────────────────────┘
                │ managed worker              │ managed worker
                ▼                             ▼
┌───────────────────────┐       ┌───────────────────────────────────┐
│       Neuron          │       │           NeuRAG                  │
│  v6.1.2               │       │  v1.2.2                           │
│                       │       │                                   │
│  Memoria episodica:   │       │  Knowledge base:                  │
│  • Grafo semantico    │       │  • Gerarchia nodi                 │
│  • 384-dim vectors    │       │  • Chunking AST-aware             │
│  • Salienza + decay   │◄─────►│  • Auto-ingest pipeline           │
│  • Trust scoring      │       │  • Turso auto-provision           │
│  • Hebbian bridges    │       │  • Cross-linking                  │
│  • Semantic flash     │       │  • Reranker (opt-in)              │
│  • Vector search      │       │  • Vector search                  │
└───────────────────────┘       └───────────────────────────────────┘
        │                               │
        └───────────┬───────────────────┘
                    ▼
            ┌───────────────────┐
            │  Turso (libsql)   │
            │  Vettori 384-dim  │
            │  Fallback sqlite3 │
            └───────────────────┘
```

### Modello di registrazione

I client MCP registrano **solo `gray-matter`** (il gateway). Neuron e NeuRAG
girano come worker gestiti da GM. Ogni progetto può anche girare standalone:

| Modalità | Registrazione client | Chi gestisce |
|---|---|---|
| **Gateway (consigliata)** | `gray-matter` unico entry | GM gestisce Neuron + NeuRAG |
| **Standalone misto** | `gray-matter` + uno diretto | GM gestisce l'altro |
| **Puro standalone** | `neuron` e/o `neurag` diretti | Nessun gateway |

---

## Neuron — Memoria semantica persistente

### Cos'è

Neuron è la **memoria viva** dell'ecosistema. Traccia cosa discuti, costruisce
un grafo semantico, e inietta le connessioni più rilevanti prima di ogni risposta.

### Componenti

Layout **src**: il pacchetto vero è `neuron/src/neuron/` (la cartella `neuron/`
è il repo). I moduli sotto sono il risultato di ADR-006, che ha estratto la
logica da `server.py`.

```
neuron/src/neuron/
├── server.py       # MCP server: 25 tool (_HANDLERS), stato globale, IPC
├── models.py       # Grafo: nodi, link, salienza, trust, decay, persistenza
├── db.py           # Storage 3-tier: Turso cloud → pyturso locale → sqlite3
├── registry.py     # Registry multi-contesto (un DB per contesto)
├── extraction.py   # Estrazione semantica zero-token, deterministica (ADR-006)
├── search.py       # Embedding + ricerca vettoriale ibrida (ADR-006)
├── stimulus.py     # Topic shift, auto-linking, finestra di contesto, flash
├── curation.py     # Gate di qualità sulle keyword in ingresso a store_turn
├── funnel.py       # Skill delivery: playbook e curated rules
├── config.py       # SSOT di path e slug (stdlib-only, zero import neuron)
├── paths.py        # SSOT dei path per-OS di Neuron
├── project.py      # Identità progetto + canonicalizzazione path (shared brain)
├── clients.py      # Registrazione MCP (keep-in-sync con neurag/clients.py)
├── __main__.py     # CLI entry point: dispatch dei subcomandi (tabella COMMANDS)
├── setup.py        # `neuron setup` — lifecycle install/repair/uninstall
├── manage.py       # `neuron manage` — gestione quotidiana del grafo
├── init.py         # `neuron init` — cabla la guidance nel prompt del client
├── console.py      # Diagnostica del grafo in sola lettura (--watch)
├── connect.py      # Collega e testa un DB Turso Cloud
├── bridge.py       # HTTP bridge per connettori remoti (ChatGPT, Perplexity)
├── tunnel.py       # HTTPS pubblico via cloudflared (con bridge)
├── engine.py       # CLI interattiva standalone (NON il percorso MCP di produzione)
├── shortcut.py     # Desktop shortcut (cross-platform)
└── ../../tests/    # Suite di test (289)
```

### Tool MCP (25)

> L'elenco autorevole è `_HANDLERS` in `neuron/src/neuron/server.py`: se i due
> divergono, ha ragione il codice.

| Tool | Funzione |
|---|---|
| `pre_turn` | STEP 1: carica contesto prima di rispondere (status + get_context compatto) |
| `store_turn` | STEP 2: persiste il turno dopo aver risposto (topic, keywords, links, domain, ...) |
| `auto` | POST fallback: extract + topic-shift + auto-link + save in un'unica call |
| `extract` | Estrazione semantica zero-token: keyword, topic, domain dal testo del turno |
| `confirm` | Feedback positivo: conferma utilità del contesto, boosta salienza e trust |
| `dismiss` | Feedback negativo: sopprime associazioni fuorvianti o rumorose (abbassa salienza e trust) |
| `get_context` | Recupera nodi e link correlati a un topic/keyword |
| `find_candidates` | Screening vettoriale: trova keyword simili (prima di store_turn) |
| `vector_search` | Ricerca semantica per cosine similarity |
| `merge` | Fonde nodi duplicati: sposta i link negli alias sul canonico, somma la salienza, cancella gli alias |
| `recall` | Richiama dal graveyard: riporta nel grafo attivo un nodo archiviato |
| `status` | Stato grafo: nodi, link, health, configurazione |
| `summary` | Sommario testuale: top keyword, link recenti, statistiche |
| `forgotten` | Trova concetti non toccati da N turni (decaying salience) |
| `prune` | Pota link tangenziali inattivi |
| `dedup` | Toggle deduplicazione keyword |
| `flash` | Toggle semantic flash |
| `introspect` | Self-model C3: concetti più forti, crescita recente, domini deboli |
| `export` | Export completo grafo come JSON (senza vettori) |
| `reset` | Reset grafo (DESTRUCTIVE, richiede confirm=true) |
| `skill` | Restituisce playbook/curated rules |
| `help` | Lista comandi |
| `switch_context` | Cambia contesto attivo |
| `list_contexts` | Lista tutti i contesti disponibili |
| `consolidate` | Consolida grafo: merge duplicati, archivia orfani |

### Concetti chiave

- **Salienza**: frequenza d'uso × recenza → i concetti frequenti e recenti salgono
- **Trust**: incrementa quando il contesto viene confermato utile
- **Decay**: i concetti dimenticati decadono naturalmente
- **Hebbian bridges**: i collegamenti tra Neuron e NeuRAG si rafforzano con l'uso
- **Semantic flash**: associazioni laterali cadenzate (ogni N turni)
- **Embedding condiviso**: stesso spazio 384-dim di NeuRAG (FastEmbed/BERT)

### Variabili d'ambiente

| Env var | Default | Funzione |
|---|---|---|
| `TURSO_DATABASE_URL` | (empty) | URL Turso remoto — abilita cloud storage |
| `TURSO_AUTH_TOKEN` | (empty) | Token auth Turso |
| `NEURON_NO_DOTENV` | `"0"` | Se `"1"`, salta caricamento `.env` |
| `NS_GRAPHS_DIR` | (home dir) | Directory storage grafi |

---

## NeuRAG — Knowledge base gerarchica

### Cos'è

NeuRAG è il **vault permanente**. A differenza di Neuron, i fatti non decadono
mai — è una biblioteca di riferimento, non una memoria viva.

### Componenti

```
neurag/
├── server.py       # MCP server: 15 tool, Gray-Matter auto-registration
├── db.py           # KnowledgeGraph: 3-tier DB, vector search, node/chunk CRUD
├── chunker.py      # Chunking adattivo: AST (Python), definition-aware (Kotlin/Java/TS/JS), Markdown, PDF, DOCX
├── embedder.py     # NullEmbedder (lexical) / FastEmbedEmbedder (384-dim, shared con Neuron)
├── reranker.py     # NullReranker (OFF) / FastEmbedReranker (cross-encoder, opt-in)
├── ingest.py       # Auto-ingest: folder → nodes → chunks → embeddings → links (server-side)
├── importer.py     # Import bulk da YAML
├── selfcheck.py    # Smoke test deterministici (no model download)
├── models.py       # Data classes: Chunk
├── clients.py      # Registrazione MCP (keep-in-sync con neuron/clients.py)
├── settings.py     # Config persistente (rerank toggle, etc.)
├── paths.py        # SSOT dei path per-OS di NeuRAG
├── cli.py          # CLI entry point (SSOT dei comandi: la GUI ispeziona questo parser)
├── bridge.py       # HTTP bridge per connettori remoti
├── shortcut.py     # Desktop shortcut (cross-platform)
└── tests/          # Suite di test (121)
```

### Tool MCP (15)

| Tool | Funzione |
|---|---|
| `knowledge_add_node` | Crea nodo nella gerarchia (godnode/fundamental/specialization) |
| `knowledge_add_chunks` | Attacca chunk a un nodo |
| `knowledge_index` | Chunkizza file/directory (non salva) |
| `knowledge_query` | Cerca chunk per topic (trigger match → vector search) |
| `knowledge_status` | Stato knowledge base (nodi, chunk, link, engine) |
| `knowledge_tree` | Mostra albero gerarchico |
| `knowledge_health` | Audit strutturale (orfani, gerarchia rotta, chunk vuoti) |
| `knowledge_neighbors` | Neighborhood BFS di un nodo (parent/children/links) |
| `knowledge_link_graph` | Mostra tutti i link con pesi ed evidenza |
| `knowledge_rebuild_links` | Ricostruisci link da tags + cross-ref |
| `knowledge_ingest` | Auto-ingest: intera directory server-side (un solo call) |
| `knowledge_ingest_status` | Stato job di ingest |
| `knowledge_remove_node` | Cancella nodo e sottoalbero |
| `knowledge_rename_node` | Rinomina nodo (aggiorna path materializzato) |
| `knowledge_import` | Import bulk da YAML mapping |

### Gerarchia nodi

```
/                                     (root assoluto, id=0, contenitore)
├── BackEndNotes/                     (godnode — cartella radice)
│   ├── Java/                         (fundamental — area tematica)
│   │   ├── Core/                     (specialization)
│   │   ├── JVM/                      (specialization)
│   │   ├── Spring_Boot/              (specialization)
│   │   └── JPA/                      (specialization)
│   ├── Python/                       (fundamental)
│   │   ├── Core/                     (specialization)
│   │   └── FastAPI/                  (specialization)
│   └── Docker/                       (fundamental)
└── ...
```

- **Root assoluto** (`/`, id=0): contenitore del DB, non è un nodo reale
- **GodNode**: radice di un topic (es. `BackEndNotes`). Figlio di `/`.
- **Fundamental**: area tematica sotto un godnode (es. `Java`)
- **Specialization**: approfondimento specifico (es. `Spring_Boot`)
- **Chunks**: frammenti di file indicizzati, collegati al nodo più specifico

La directory su disco è solo sorgente raw per lo chunker, non appare nel grafo.

### Auto-ingest

Il tool `knowledge_ingest` grafica intere directory **server-side** in un'unica
chiamata — nessun chunk viaggia nel contesto dell'LLM:

```
scan → folder structure → nodes (godnode/fundamental/specialization)
     → chunk per file (AST-aware per codice, heading splits per Markdown)
     → embeddings (se FastEmbed disponibile)
     → rebuild links (tag_overlap + cross_ref)
```

Mapping automatico:
- Root folder → godnode
- Sottocartelle primo livello → fundamental
- Sottocartelle più profonde → specialization (figlio del nodo cartella parent)
- File → chunk attaccati al nodo della cartella

Directory nascoste/build (`__pycache__`, `node_modules`, `.venv`, etc.) sono saltate.

### Turso auto-provision

NeuRAG **preferisce Turso** per vector SQL nativo. Se pyturso non è installato,
NeuRAG tenta di installarlo automaticamente da wheel bundled (fino a `NEURAG_TURSO_ATTEMPTS`
volte). Solo dopo aver esaurito i tentativi degrada a sqlite3 — con logging completo
visibile via `knowledge_status`.

### Variabili d'ambiente

| Env var | Default | Funzione |
|---|---|---|
| `NEURAG_EMBEDDER` | `"auto"` | Embedder: `auto` (fastembed se installato) / `fastembed` / `null` |
| `NEURAG_EMBED_MODEL` | `"paraphrase-multilingual-MiniLM-L12-v2"` | Modello FastEmbed (384-dim, multilingue IT/EN) |
| `NEURAG_RERANK` | `"off"` | Reranker cross-encoder: `on` / `off` |
| `NEURAG_RERANK_MODEL` | `"Xenova/ms-marco-MiniLM-L-6-v2"` | Modello reranker |
| `NEURAG_TURSO_DATABASE_URL` | (empty) | URL Turso remoto (SEPARATO da Neuron!) |
| `NEURAG_TURSO_AUTH_TOKEN` | (empty) | Token auth NeuRAG Turso |
| `NEURAG_REQUIRE_TURSO` | `"1"` | Se `"0"`, salta auto-install di pyturso |
| `NEURAG_TURSO_ATTEMPTS` | `"3"` | Tentativi auto-install prima del fallback sqlite3 |
| `NEURAG_TURSO_AUTOINSTALL` | `"1"` | Se `"0"`, non tenta `pip install` automaticamente |

> **Importante:** NeuRAG ha il suo **proprio** database Turso. NON deve condividere
> un URL con Neuron (schema `nodes` diverso). Usa env vars `NEURAG_TURSO_*`, non `TURSO_*`.

---

## Gray Matter — Gateway/Orchestratore

### Cos'è

Gray Matter è il **cervello** che lega tutto insieme. I client vedono solo GM;
gestisce Neuron e NeuRAG come worker interni.

### Componenti

```
gray_matter/
├── server.py          # MCP server + daemon: pulse, bridges, flash, pass-through
├── _worker.py         # Worker subprocess persistente (importa server module una volta)
├── registry.py        # Registro server: liveness, tool schema, collaborative flags
├── cache.py           # Cache contesto TTL + LRU con invalidazione mirata
├── bridges.py         # Persistenza bridge cross-store + Hebbian promotion/decay
├── executor.py        # Install/uninstall effettivi (scrive file, registra client)
├── installer.py       # Piano install puro (no side effects)
├── uninstaller.py     # Piano uninstall puro (no side effects)
├── clients.py         # Rilevamento + registrazione config MCP client
├── settings.py        # Knobs (flash rate, cache TTL, prewarm, ...)
├── catalog.py         # Catalogo comandi GUI (introspect argparse, no liste hardcodate)
├── gme.py             # Registry GME: discovery multi-venv, health tracking
├── shortcut.py        # Desktop shortcut (cross-platform: .lnk/.command/.desktop)
├── cli.py             # CLI entry point (25+ comandi) + SSOT dell'IPC (host, porta,
│                      #   _send_ipc, _recv_exact: server.py importa da qui)
├── paths.py           # SSOT dei path per-OS della suite
├── cloud.py           # Turso cloud: setup, wire, status, teardown
├── webgui.py          # Control center web (pywebview)
├── gui.py             # Control center legacy Tkinter (DEPRECATO)
├── bridge.py          # HTTP bridge per connettori remoti (ChatGPT, Perplexity)
├── _env.py            # Sanitizzazione credenziali (shared con Neuron/NeuRAG)
└── tests/             # Suite di test (238)
```

### Tool MCP (30+)

| Tool | Funzione |
|---|---|
| `gray_matter_pulse` | Pre-contesto + chunk knowledge + flash in un'unica call |
| `gray_matter_store_turn` | Persiste turno + precarica cache |
| `gray_matter_status` | Stato Gray Matter e server registrati |
| `gray_matter_auto` | POST fallback: extract + topic-shift + auto-link + save |
| `gray_matter_confirm` | Feedback: conferma utilità del contesto |
| `gray_matter_extract` | Estrazione semantica automatica (keyword, topic, domain, ...) |
| `gray_matter_find_candidates` | Screening vettoriale: trova keyword simili |
| `gray_matter_vector_search` | Ricerca semantica per cosine similarity |
| `gray_matter_switch_context` | Cambia contesto attivo |
| `gray_matter_list_contexts` | Lista tutti i contesti |
| `gray_matter_get_context` | Recupera nodi correlati |
| `gray_matter_forgotten` | Trova concetti dormienti |
| `gray_matter_prune` | Pota link inattivi |
| `gray_matter_dedup` | Toggle deduplicazione |
| `gray_matter_flash` | Toggle semantic flash |
| `gray_matter_summary` | Sommario grafo |
| `gray_matter_export` | Export grafo JSON |
| `gray_matter_reset` | Reset grafo (DESTRUCTIVE) |
| `gray_matter_introspect` | Self-model C3 |
| `gray_matter_gray_matter_bridge` | Persisti bridge cross-store |
| `gray_matter_knowledge_*` | Pass-through per tool NeuRAG |
| `neuron_*` | Pass-through per tool Neuron |

### Concetti chiave

- **Daemon singleton** sulla porta 9876 (exclusive bind su Windows via `SO_EXCLUSIVEADDRUSE`)
- **Worker persistenti**: i subprocess importano il server module una volta sola
- **Catalog SSOT**: la GUI legge comandi da argparse di ogni tool — nuovi sotto-comandi
  appaiono automaticamente senza toccare il codice GUI
- **GME registry**: ogni tool scrive un file JSON dopo install; la GUI legge questi
  per trovare il Python corretto per ogni tool (supporto multi-venv)
- **Cross-store bridges**: connessioni Hebbian tra concetti Neuron e nodi NeuRAG
  che si rafforzano quando usati insieme

### Flusso `gray_matter_pulse`

```
Client → gray_matter_pulse(topic="Java bytecode")
│
├─ Cache hit per topic? → usa cache, salta get_context
├─ Cache miss → chiama neuron_get_context() + knowledge_query() IN PARALLELO
│               (se un server non è registrato, salta silenziosamente)
│
├─ Attende max(N, R) — la più lenta delle due
├─ Unifica: contesto grafo + chunk knowledge
├─ Flash check: contatore interno % 5 == 0?
│   ├─ Sì → neuron_forgotten(near=topic) → associazioni laterali
│   └─ No → salta
│
├─ Salva in cache: topic → (contesto + chunk)
└─ Risponde: contesto + chunk + [eventuali flash]
```

### Variabili d'ambiente

| Env var | Default | Funzione |
|---|---|---|
| `GM_FLASH_RATE` | `0.15` | Probabilità semantic flash per turno |
| `GM_CACHE_TTL` | `3600` | TTL cache contesto in secondi |
| `GM_CACHE_MAX` | `128` | Massimo entries cache |
| `GM_PREWARM` | `"1"` | Pre-warm modelli all'avvio |
| `GM_DAEMON_PORT` | `9876` | Porta listener daemon |

---

## CLI reference (riepilogo)

### Gray Matter (25+ comandi)

```bash
gray-matter install [--dry-run]          # Idempotent gateway install
gray-matter uninstall [--purge-data]     # Remove gateway (interactive on memory)
gray-matter repair                       # Clean reinstall: scegli cosa cancellare
gray-matter start / stop                 # Avvia/ferma daemon
gray-matter ping / status / doctor       # Diagnostica
gray-matter stats                        # Contatori: cache hit, flash, bridges, latenza
gray-matter logs                         # Mostra log daemon
gray-matter register [--gateway]         # Registra gateway nei client MCP
gray-matter deregister <tool>            # Rilascia tool dal gateway
gray-matter link <tool>                  # Ri-attacca tool standalone al gateway
gray-matter config list / get / set      # Gestione knobs
gray-matter cloud                        # Connetti a Turso Cloud (interactive)
gray-matter mode <collaborate|separate>  # Modalità tutti server
gray-matter isolate / collaborate <name> # Escludi/includi server dal pulse
gray-matter knowledge status / tree      # Knowledge base status
gray-matter knowledge rebuild-links      # Ricostruisci cross-links
gray-matter knowledge link-graph         # Mostra grafo link
gray-matter bridges / bridges-transfer   # Gestione bridge cross-store
gray-matter bridge                       # Espone suite via HTTP
gray-matter gui [--classic]              # Apri control center web
gray-matter gm-neuron / gm-neurag        # Chiama tool via gateway (testing)
```

### Neuron

```bash
neuron register / deregister             # Registra/deregistra standalone
neuron go-standalone                     # Esci dal gateway, registra diretto
neuron gui [--shortcut-only]             # Apri control center (bootstrappa GM se serve)
neuron repair [--reinstall] [--wipe-memory]  # Ripara installazione
```

### NeuRAG

```bash
neurag register / deregister             # Registra/deregistra standalone
neurag go-standalone                     # Esci dal gateway, registra diretto
neurag gui [--shortcut-only]             # Apri control center (bootstrappa GM se serve)
neurag repair [--reinstall] [--wipe-knowledge]  # Ripara installazione
neurag config list / get / set           # Gestione knobs
```

---

## Storage

### Neuron

| Dati | Path | Descrizione |
|---|---|---|
| Grafi | `<data-dir>/neuron5/graphs/graph_<context>.db` | DB per contesto (default, java/spring, ...) |
| `.env` | `neuron/.env` | Credenziali Turso (opzionale) |

### NeuRAG

| Dati | Path | Descrizione |
|---|---|---|
| Knowledge | `<data-dir>/neurag/knowledge.db` | SQLite/Turso (nodi, chunk, link) |
| Config | `<data-dir>/neurag/config.json` | Impostazioni persistenti (rerank, etc.) |

### Gray Matter

| Dati | Path | Descrizione |
|---|---|---|
| Registry | `<data-dir>/gray_matter/registry.json` | Server registrati |
| Cache | In-memory (TTL + LRU) | Cache contesto |
| Bridges | `<data-dir>/gray_matter/bridges.json` | Bridge cross-store |
| Manifest | `<data-dir>/gray_matter/manifest.json` | File gestiti da install |
| Config | `<data-dir>/gray_matter/settings.json` | Knobs |

---

## Sicurezza

- **PolyForm Noncommercial 1.0.0** per tutti i progetti
- **Credenziali Turso**: mai esposte nel grafo; sanitizzazione in `_env.py`
- **Daemon port**: exclusive bind su Windows, non accessibile da rete
- **No secrets in log**: `_env.py` filtra token/password dai log
- **Install manifest**: traccia ogni file modificato per uninstall pulito
- **`.bak` backup**: ogni modifica ai config client preserva il backup
