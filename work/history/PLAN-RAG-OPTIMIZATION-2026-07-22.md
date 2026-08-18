# Piano esecutivo — Ottimizzazione RAG (NeuRAG) + fix concorrenza

**Data:** 2026-07-22
**Contesto:** default engine = **TursoLocal** (pyturso/libsql su file locale), embedder fastembed 384-dim (`paraphrase-multilingual-MiniLM-L12-v2`), ricerca attuale brute-force.
**Obiettivo:** chiudere la classe di corruzione dell'audit e alzare qualità/velocità del retrieval **senza aggiungere dipendenze esterne** (FTS5 e ANN sono nativi nel motore già in uso; reranker riusa fastembed già presente).
**Vincolo operativo (ENVIRONMENT.md):** modifiche al DB testate in tmp-dir; niente test distruttivi sul `knowledge.db` reale. Ogni fase su copia.

---

## Ordine di esecuzione (per rapporto sicurezza/impatto)

`Fase 0 (safety)` → `Fase 1 (job persistence)` → `Fase 2 (hybrid FTS5+RRF)` → `Fase 3 (ANN index)` → `Fase 4 (reranker, opt)` → `Fase 5 (guardrail+errori)`.

Le fasi 0-1 sono prerequisiti: senza serializzazione delle scritture, aggiungere indici (FTS5/ANN) che si aggiornano durante l'ingest **peggiora** la concorrenza.

---

## FASE 0 — Concorrenza & safety (prerequisito)

**Causa radice confermata nel codice:** `neurag/server.py:25-32` tiene un singleton `_db` (una connessione) per le chiamate foreground; `neurag/ingest.py:129-148` apre una **seconda** `KnowledgeGraph()` in un daemon thread sullo **stesso file**. `neurag/db.py:298` mette `journal_mode=WAL` ma **manca `busy_timeout`** → due connessioni pyturso sullo stesso file, una che scrive in continuazione, l'altra con letture pesanti (`knowledge_tree`) → "disk image malformed".

### File: `neurag/db.py`
- `_connect()` (righe 271-299): aggiungere `PRAGMA busy_timeout=5000` su **entrambi** i rami (turso locale + sqlite3). Sul tier remoto resta no-op (già gestito da `_REMOTE_NOOP_PRAGMAS`).
- Nuovo modulo-livello: `_WRITE_LOCK = threading.RLock()` (import `threading`). Serializza le scritture **tra connessioni diverse** (singleton + thread ingest) perché è globale al processo, non per-connessione.
- Wrappare in `with _WRITE_LOCK:` il corpo dei metodi di scrittura: `add_node` (315), `add_triggers` (342), `add_chunk` (487), `upsert_link` (534), `delete_node` (383), `rename_node` (412), `build_tag_links` (642), `build_crossref_links` (676), `rebuild_links` (716).

### File: `neurag/ingest.py`
- `start_job._run()` (129-148): la connessione propria del thread resta (regola sqlite thread-affinity) ma le sue scritture passano già per `_WRITE_LOCK` via i metodi di `db.py` — nessun'altra modifica strutturale qui.

**Test (tmp-dir):** `neurag/tests/test_concurrency.py` — thread di ingest + query foreground in parallelo su DB tmp, asserire `PRAGMA integrity_check == ok` a fine corsa.

---

## FASE 1 — Job registry persistente (fix "No such job")

**Problema:** `neurag/ingest.py:117` `JOBS = {}` è in-memory; crash/restart del worker perde il tracking.

### File: `neurag/ingest.py`
- Persistere i job su file **separato** dal `knowledge.db`: `~/.local/share/neurag/jobs.json` (o `jobs.db`). Scrivere su transizione di stato e su checkpoint di avanzamento (ogni N file in `auto_ingest`, riga 89-105, via il callback `say`).
- `JOBS` caricato da disco all'import del modulo; `start_job` e `_run` fanno flush su ogni update.
- Cap `_MAX_JOBS` invariato (righe 118, 125-127) ma applicato anche al file persistito.

### File: `neurag/server.py`
- `knowledge_ingest_status` (222-233): nessuna modifica logica — legge `JOBS` che ora è idratato da disco. Verificare solo che l'import ricarichi.

**Test:** avviare job, simulare re-import del modulo, `knowledge_ingest_status(job_id)` deve ancora trovarlo.

---

## FASE 2 — Hybrid search FTS5(BM25) + vettoriale, fusi con RRF (qualità)

**Perché:** oggi il lessicale (`_rank_lexical`, 805-822) è solo fallback quando manca l'embedder, mai fuso col semantico. BM25 recupera exact-match (nomi simboli, codici) dove i vettori sbagliano. FTS5+bm25 **confermati disponibili** anche nel tier sqlite3.

### File: `neurag/db.py`
- `SCHEMA_SQL` (183-227): aggiungere virtual table FTS5 esterna-content:
  `CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');`
  + probe di capability in `_connect` (alcune build libsql potrebbero non avere FTS5 → flag `self._fts = True/False`, se assente si degrada al solo vettoriale).
- `add_chunk` (487-498): dopo l'insert su `chunks`, sync su `chunks_fts` (insert su external-content: `INSERT INTO chunks_fts(rowid, text) VALUES(?,?)`).
- `delete_node` (383-410): eliminare anche le righe FTS dei chunk rimossi.
- Nuovo metodo `_search_bm25(query, k)`: `SELECT rowid ... FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?`.
- Nuovo helper `_rrf_fuse(vec_ranked, bm25_ranked, k=60, top_n)`: fusione rank-only (nessuna normalizzazione di score).
- `search()` (774-803): calcolare top-k vettoriale **e** top-k BM25, fondere con `_rrf_fuse`. Quando l'embedder è null → solo BM25 (già meglio del TF-IDF-lite attuale).
- Nuovo metodo/tool di backfill `reindex_fts()`: popolare `chunks_fts` dai chunk esistenti (una tantum, migrazione).

### File: `neurag/server.py`
- `knowledge_query` (298-325): nessuna modifica — chiama già `db.search()`. Opzionale: esporre nuovo tool `knowledge_reindex` (backfill FTS/ANN) nella lista `tool_names` (357-369) + dispatch.

**Test:** `test_hybrid_search.py` — query exact-term (nome funzione) deve rankare sopra il match semantico puro; RRF deterministico.

---

## FASE 3 — Vector index nativo ANN (LM-DiskANN) (velocità)

**Perché:** `search()` (784-790) fa full-scan `vector_distance_cos` su tutti i chunk = O(N). libsql locale supporta ANN nativo via `libsql_vector_idx()` + `vector_top_k()`.

**Rischio più alto → gate esplicito + migrazione su copia.** Caveat: maturità pyturso 0.6.1 (storico bug FK cascade, vedi `db.py:388`). Solo tier turso; il tier sqlite3 mantiene il brute-force.

### File: `neurag/db.py`
- Storage embedding: passare da BLOB grezzo (`_pack_vec` struct.pack, 758-760) a `F32_BLOB(384)` con `vector32(?)` in insert. Colonna `embedding` in `SCHEMA_SQL` (206) → `F32_BLOB(384)` sul tier turso.
- `SCHEMA_SQL`/migrazione: `CREATE INDEX chunks_vec_idx ON chunks(libsql_vector_idx(embedding))` **solo se** `self._vector_sql` (tier turso locale/cloud).
- `add_chunk` (487-498): insert con `vector32(?)` sul tier turso.
- `search()` (782-803): sul tier turso usare `vector_top_k('chunks_vec_idx', vector32(?), ?)` in JOIN con `chunks`; fallback trasparente al ramo Python esistente su sqlite3 (già presente, 795-803).
- Migrazione `reindex_ann()`: i BLOB attuali sono float32 raw → ri-embed o conversione. Gate dietro flag/versione, eseguire su copia del DB.
- ANN è approssimato: per KB piccole (< ~qualche migliaio di chunk) tenere l'esatto; sopra soglia usare ANN. Soglia configurabile.

**Test:** `test_ann_index.py` — recall ANN vs brute-force su dataset sintetico ≥ 0.95; verifica che l'update dell'indice durante insert non corrompa (integrity_check).

---

## FASE 4 — Reranker cross-encoder (opzionale, dietro toggle)

**Default OFF** (`NEURAG_RERANK=off`), coerente con "senza perdere troppo" (aggiunge latenza).

### File: `neurag/embedder.py` (o nuovo `neurag/reranker.py`)
- Aggiungere classe `FastEmbedReranker` (fastembed `TextCrossEncoder`, es. `bge-reranker-base`), lazy-load come `FastEmbedEmbedder` (37-51). Env `NEURAG_RERANK = off (default) | on`, modello via `NEURAG_RERANK_MODEL`.
- Factory `get_reranker()` analoga a `get_embedder()` (54-66), degrada a no-op se assente.

### File: `neurag/db.py`
- `search()` / `search_with_links` (724-750): se reranker attivo, recuperare top ~50 via RRF poi rerank ai `top_n` finali.

**Test:** routing off = identità (nessun rerank); on = riordino coerente.

---

## FASE 5 — Guardrail ingest + error handling strutturato

**File: `neurag/server.py`**
- `call_tool` (188-352): prima di `consolidate`/`knowledge_add_node`/`knowledge_add_chunks`/`knowledge_rebuild_links` quando esiste un job `state=='running'` (da `ingest.JOBS`), **accodare o rifiutare** con messaggio chiaro invece di eseguire in concorrenza.
- Intercettare le eccezioni SQLite (corruption/lock) nei rami di scrittura e restituirle come TextContent strutturato ("engine busy / DB error: …"), non lasciarle risalire.

**File: `gray_matter/_worker.py`**
- Verificare che l'eccezione del tool sia catturata e ritornata come `{"ok": false, "error", "trace"}` (il gateway `server.py:573-577` la propaga già come errore strutturato). Assicurarsi che la corruption non uccida il worker silenziosamente → è quella che diventa l'"Internal Server Error" lato OpenCode.

**File: `gray_matter/server.py`**
- `_call_server_async` (542-585): già serializza per-pipe e gestisce timeout/kill. Nessuna modifica strutturale; solo assicurarsi che l'errore strutturato del worker arrivi al client come tool-error, non generico.

---

## Recovery del DB attuale (una tantum, fuori dalle fasi)

Il `knowledge.db` corrente è corrotto: `PRAGMA integrity_check` per stimare il danno, poi **re-ingest da zero** delle fonti (i file su disco sono intatti, solo il derivato è corrotto). Da fare dopo Fase 0-1 così il re-ingest gira già serializzato e tracciato.

---

## Riepilogo file toccati

| File | Fasi | Natura |
|---|---|---|
| `neurag/db.py` | 0,2,3,4 | busy_timeout, write-lock, FTS5, RRF, ANN, hook reranker |
| `neurag/ingest.py` | 0,1 | job persistence, checkpoint |
| `neurag/server.py` | 1,2,5 | tool reindex, guardrail, error handling |
| `neurag/embedder.py` (+ `reranker.py`) | 4 | reranker factory |
| `gray_matter/_worker.py` | 5 | error propagation |
| `gray_matter/server.py` | 5 | verifica error strutturato (probabile no-op) |
| `neurag/tests/*` | 0-4 | test_concurrency, test_hybrid_search, test_ann_index, reranker |
| `neurag/__init__.py` + `CHANGELOG.md` | tutte | bump versione + changelog |
| `docs/TECHNOLOGY.md`, `docs/DATA.md`, `GRAY-MATTER-COMPENDIUM.md` | tutte | aggiornare architettura retrieval |
| `audit_gray-matter_corruption.md` | — | correggere: `store_turn` scrive su Neuron (non co-writer); su knowledge.db 1 writer + letture concorrenti |

## Zero nuove dipendenze runtime
FTS5 e ANN sono nativi (SQLite/libsql già in uso). Il reranker riusa `fastembed` già presente. Nessun servizio esterno, resta single-file locale.
