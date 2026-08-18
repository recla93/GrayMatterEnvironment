# DOCTOOLUPDATE — NeuRAG v1.2.2

> Aggiornamento completo della documentazione tool per NeuRAG, il server MCP di knowledge base gerarchica.
> Generato il 2026-07-27. Include esempi di codice reale estratti dal sorgente.

---

## 1. Panoramica

NeuRAG è un server MCP che fornisce una **knowledge base gerarchica** con embedding vettoriali 384-dim. A differenza di Neuron (memoria episodica dei turni), NeuRAG memorizza **conoscenza strutturata**: documenti, codice, paper — organizzati in un albero di nodi gerarchici con chunk di testo collegati.

**Architettura**: Python 3.10–3.14, stdlib-heavy, Turso (pyturso locale o libSQL cloud) con fallback sqlite3. Stessa dimensione vettoriale di Neuron (384-dim) per cross-store bridge.

**Posizione**: `neurag/` — modulo installabile come `neurag`.

---

## 2. Moduli Principali

### 2.1 `models.py` — Dataclass

```python
@dataclass
class Chunk:
    text: str
    source: str        # file path originale
    section: str       # heading o "def function_name"
    chunk_index: int = 0
    tags: list[str] = field(default_factory=list)  # trigger candidates

@dataclass
class QueryResult:
    text: str
    source: str
    section: str
    score: float
    chunk_index: int = 0
```

---

### 2.2 `db.py` — KnowledgeGraph con Turso 3-tier

Database gerarchico con 3 tabelle: `nodes`, `chunks`, `node_links`. Lo schema supporta:
- Albero gerarchico (parent_id + path materializzato)
- Embedding vettoriali 384-dim nei chunks
- Link tra nodi (tag_overlap, cross_ref, semantic)

```python
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    node_type   TEXT    NOT NULL CHECK(node_type IN ('godnode','fundamental','specialization')),
    parent_id   INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    path        TEXT    NOT NULL,   -- materialised path: /BackEndNotes/Java/SpringBoot
    tags        TEXT    DEFAULT '[]',  -- JSON array
    triggers    TEXT    DEFAULT '[]',  -- JSON array
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- Absolute root (id=0, path='/', parent_id=NULL).
INSERT OR IGNORE INTO nodes (id, name, node_type, parent_id, path)
VALUES (0, '/', 'godnode', NULL, '/');

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    source      TEXT,       -- original file path
    section     TEXT,
    chunk_index INTEGER DEFAULT 0,
    embedding   BLOB,       -- 384-dim float32 vector (or NULL if not embedded)
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS node_links (
    source_id   INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id   INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    link_type   TEXT    NOT NULL CHECK(link_type IN ('tag_overlap','cross_ref','semantic')),
    weight      REAL    DEFAULT 1.0,
    evidence    TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (source_id, target_id, link_type)
);
"""
```

**Connection 3-tier**:

```python
# 1. Cloud Turso (NEURAG_TURSO_DATABASE_URL) — multi-machine
# 2. Local pyturso (native vector_distance_cos)
# 3. sqlite3 stdlib (fallback, no vector SQL)

REMOTE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

def _connect(self) -> None:
    if REMOTE_TURSO:
        self._conn = RemoteTursoConnection(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
        self._vector_sql = True
        self._engine_name = "Turso (cloud)"
        return
    conn = _open_local_turso(db_str) if TURSO_AVAILABLE else None
    if conn is not None:
        self._conn = conn
        self._vector_sql = True
        self._engine_name = "Turso (local)"
    # ...
```

**Turso auto-provisioning**: se pyturso non è installato, NeuRAG tenta `pip install pyturso==0.6.1` dalle wheel vendored, fino a `NEURAG_TURSO_ATTEMPTS` volte. Solo allora degrada a sqlite3.

```python
def _ensure_turso(self, db_path) -> None:
    """Turso PREFERITO sul vault reale, con fallback documentato.
    
    Se sul vault di default NON siamo su Turso, si prova ad acquisirlo —
    import, e se manca `pip install` dalle wheel vendored — fino a
    NEURAG_TURSO_ATTEMPTS volte; solo allora si degrada a sqlite3
    registrando gli errori (che status/doctor mostrano). Nessun crash.
    """
```

---

### 2.3 `chunker.py` — Chunking adattivo

Il chunking è **meaning-aware**, non un semplice split per righe. Ogni linguaggio ha la sua strategia:

| Tipo | Strategia | Output |
|------|-----------|--------|
| Markdown | Split per heading `##` | 1 chunk per sezione |
| Python | AST: 1 chunk per top-level def/class | tags = nomi simbolo |
| Kotlin/Java/TS/JS/RS/GO | Regex definition-boundary | tags = nomi funzione |
| PDF | 1 chunk per pagina (PyMuPDF) | 1 chunk = 1 pagina |
| DOCX | Split per heading style | tags = heading text |
| Text/YAML/TOML/... | Line-based (max 60 righe) | — |

```python
def chunk_python_ast(filepath: Path) -> list[Chunk]:
    """One chunk per top-level function/class; module-level code grouped.
    
    Decorators are kept with their target. Falls back to line chunking if the
    file doesn't parse (partial edits, non-CPython syntax)."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.split("\n")
    # ... per ogni nodo top-level:
    #   - FunctionDef/ClassDef → chunk dedicato con tags=_tags(node.name)
    #   - Altro → buffer modulo (flushed quando si incontra un def)
```

**Tags e triggers**: ogni chunk code estrae sub-words dal nome del simbolo come trigger candidates. Questo permette al bridge Neuron→NeuRAG di trovare il nodo giusto per un concetto dormiente.

```python
def _subwords(name: str) -> list[str]:
    """snake_case + camelCase -> lowercase sub-words
    (find_node_by_trigger -> find, node, trigger)."""
    words: list[str] = []
    for part in re.split(r"[_\W]+", name):
        words += [w.lower() for w in
                  re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", part)]
    return words

def _tags(name: str, extra: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Trigger candidates from a symbol name (+ optional extra names)."""
    out = [name.lower(), *_subwords(name)]
    # ... filtra stop words, dedup, max 8 tags
```

---

### 2.4 `embedder.py` — Embedder pluggable

Auto-detect: se `fastembed` è importabile (Neuron lo già include), il semantic embedder si attiva da solo. Altrimenti stay lexical-only (NullEmbedder).

```python
_MODEL = (os.environ.get("NEURAG_EMBED_MODEL")
          or os.environ.get("NS_EMBED_MODEL")
          or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
DIM = 384

class NullEmbedder:
    """No embeddings. `embed` returns None → callers use the lexical path."""
    dim = DIM
    available = False
    def embed(self, text: str):
        return None

class FastEmbedEmbedder:
    """Semantic embeddings via fastembed. Lazy: model loads on construction."""
    dim = DIM
    available = True
    def __init__(self, model: str = _MODEL):
        from fastembed import TextEmbedding
        self._m = TextEmbedding(model_name=model)
    def embed(self, text: str) -> list[float]:
        v = next(iter(self._m.embed([text])))
        return [float(x) for x in v]

def get_embedder():
    """Return the embedder per NEURAG_EMBEDDER. auto = fastembed if present else null."""
    choice = os.environ.get("NEURAG_EMBEDDER", "auto").lower()
    if choice in ("auto", "fastembed"):
        try:
            return FastEmbedEmbedder()
        except Exception:
            if choice == "fastembed":
                raise  # explicit request must not silently downgrade
            return NullEmbedder()  # auto: graceful fallback
    return NullEmbedder()
```

---

### 2.5 `reranker.py` — Reranker opzionale

Cross-encoder per second-stage precision. OFF di default (NullReranker = identity). Abilitabile con `neurag config set rerank on`.

```python
class NullReranker:
    """No reranking. `rerank` returns the candidates unchanged (identity)."""
    def rerank(self, query: str, candidates: list[dict], top_n: int) -> list[dict]:
        return candidates[:top_n]

class FastEmbedReranker:
    """Cross-encoder rescoring via fastembed.TextCrossEncoder."""
    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self._m = TextCrossEncoder(model_name=model)
    def rerank(self, query: str, candidates: list[dict], top_n: int) -> list[dict]:
        docs = [(c.get("text") or "") for c in candidates]
        scores = list(self._m.rerank(query, docs))
        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:top_n]]
```

---

### 2.6 `ingest.py` — Pipeline automatica folder → grafo

Sposta la grafizzazione dal MODELLO al SERVER: zero token LLM, tutto server-side.

```python
# Mappatura automatica (zero configurazione):
#   - la radice diventa (o riusa) il godnode
#   - cartelle di primo livello → fundamental
#   - sottocartelle → specialization, figlie del nodo della cartella madre
#   - i file finiscono nel nodo della cartella che li contiene

def auto_ingest(kg, root, godnode: str | None = None, say=None) -> dict:
    """Grafizza `root` dentro `kg`. Ritorna il report; `say(riga)` per il progresso."""
    root = Path(root).expanduser().resolve()
    god = (godnode or root.name).strip()
    gn = kg.get_node_by_name(god)
    if gn is None:
        kg.add_node(name=god, node_type="godnode")
    
    node_for = {root: gn["id"]}
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        rel = d.relative_to(root).parts
        if _skippable(rel):
            continue
        parent_id = node_for.get(d.parent)
        ntype = "fundamental" if d.parent == root else "specialization"
        name = d.name
        # ... crea nodo, indice file, collega
```

Il job può girare in background (thread separato) con polling:

```python
# Tool MCP: knowledge_ingest → start_job() → return job_id
# Tool MCP: knowledge_ingest_status → job_text() → progresso
```

---

### 2.7 `server.py` — 14 Tool MCP

Ecco i tool esposti, raggruppati per funzione:

#### Ingest (scrittura)
| Tool | Descrizione |
|------|-------------|
| `knowledge_ingest(path, godnode?)` | Grafizza una cartella intera server-side (background job) |
| `knowledge_ingest_status(job_id?)` | Stato di un job di ingest |
| `knowledge_index(path)` | Chunk un file/cartella senza salvare (ritorna JSON) |
| `knowledge_add_node(name, node_type, ...)` | Crea un nodo nella gerarchia |
| `knowledge_add_chunks(node_name, chunks)` | Attacca chunk esistenti a un nodo |
| `knowledge_import(mapping)` | Bulk-import da YAML mapping |

#### Query (lettura)
| Tool | Descrizione |
|------|-------------|
| `knowledge_query(query, top_n?)` | Cerca chunk rilevanti per topic |
| `knowledge_neighbors(query, depth?, limit?)` | BFS sulla gerarchia di un nodo |
| `knowledge_tree()` | Stampa l'albero gerarchico |

#### Manutenzione
| Tool | Descrizione |
|------|-------------|
| `knowledge_status()` | Stato: engine, node count, chunk count |
| `knowledge_health()` | Audit strutturale (orphan, tiny chunks, duplicates) |
| `knowledge_link_graph()` | Mostra tutti i link tra nodi |
| `knowledge_rebuild_links()` | Ricostruisci link da tags + cross-refs |
| `knowledge_remove_node(name)` | Cancella nodo + subtree |
| `knowledge_rename_node(name, new_name)` | Rinomina nodo + aggiorna path discendenti |

---

## 3. Flusso Dati: knowledge_query

```
1. knowledge_query("Spring Boot annotations")
   → find_node_by_trigger("spring") o get_node_by_name("Spring")
   → search(query, top_n=5):
     a. Se _vector_sql: cosine similarity via SQL (vector_distance_cos)
     b. Se no vector: TF-IDF lexical fallback
   → opzionale: FastEmbedReranker.rerank(query, candidates, top_n)
   → ritorna top-n chunks con score, source, section
```

---

## 4. Triggers e Bridge Neuron→NeuRAG

Ogni nodo ha una lista `triggers` (JSON array) usata da `find_node_by_trigger()`. Quando Neuron store_turn introduce un nuovo concetto, il bridge (in `gray_matter/bridges.py`) cerca un nodo NeuRAG i cui triggers matchano il keyword.

```python
def find_node_by_trigger(self, keyword: str) -> Optional[dict]:
    """Find a node whose triggers list contains the given keyword."""
    rows = self._conn.execute(
        "SELECT * FROM nodes WHERE triggers LIKE ?",
        (f'%"{keyword}"%',)
    ).fetchall()
    if rows:
        return dict(rows[0])
    return None
```

---

## 5. Persistenza e Deployment

**Locale**: SQLite WAL mode, file unico per vault (`knowledge.db`). pyturso con connection cache (lock exclusive su Windows).

**Cloud**: `NEURAG_TURSO_DATABASE_URL` + `NEURAG_TURSO_AUTH_TOKEN` (o fallback a `TURSO_AUTH_TOKEN`). Schema separato da Neuron (stessa tabella `nodes` ma schema diverso — NON condividere il DB).

**Auto-install**: NeuRAG include wheel pyturso in `vendor/` e può installarlo automaticamente se assente.

---

## 6. Variabili d'Ambiente Chiave

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `NEURAG_TURSO_DATABASE_URL` | — | URL database Turso Cloud (proprio, non condiviso con Neuron) |
| `NEURAG_TURSO_AUTH_TOKEN` | — | Token Turso (fallback a `TURSO_AUTH_TOKEN`) |
| `NEURAG_EMBEDDER` | `auto` | `auto` \| `fastembed` \| `null` |
| `NEURAG_EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Modello embedding (stesso di Neuron) |
| `NEURAG_RERANK` | `off` | Abilita cross-encoder reranker |
| `NEURAG_RERANK_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Modello reranker |
| `NEURAG_REQUIRE_TURSO` | `1` | Se 0, salta auto-install Turso |
| `NEURAG_TURSO_ATTEMPTS` | `3` | Tentativi auto-install prima del fallback |
| `NEURAG_TURSO_AUTOINSTALL` | `1` | Se 0, non tenta pip install automatico |

---

## 7. Self-Check

NeuRAG include `selfcheck.py` per verifiche deterministiche (nessun modello richiesto):

```python
# python neurag/selfcheck.py (dalla cartella neurag/)
def check_lexical_search() -> None:
    """Verifica TF-IDF: chunk on-topic deve rankare primo."""
    kg = KnowledgeGraph(tmp)
    god = kg.add_node("Java", "godnode")
    n = kg.add_node("Concurrency", "fundamental", parent_id=god)
    kg.add_chunk(n, "Threads and locks manage concurrent access in the JVM.")
    kg.add_chunk(n, "Garbage collection reclaims unused heap memory.")
    kg.add_chunk(n, "A ForkJoinPool schedules parallel tasks across threads.")
    
    top = kg.search("threads concurrent", top_n=2)
    assert "concurrent" in top[0]["text"].lower()
```

---

## 8. Sicurezza

- `NEURAG_TURSO_AUTH_TOKEN` sanitizzato (strip control chars, fix header injection)
- DB cloud separato da Neuron (schema incompatibile)
- WAL mode + busy_timeout=5000ms per concorrenza
- FK enforcement disabilitato solo temporaneamente durante delete ricorsivo (workaround bug pyturso 0.6.1)
- Corrupted DB flagga ma non crasha (status/health mostrano l'errore)

---

## 9. Cross-References

- `docs/DESIGN-CROSSLINKS.md` — design dei cross-store links
- `neuron/` — partner server (memoria episodica, stesso spazio 384-dim)
- `gray_matter/` — gateway orchestrator (NeuRAG è sotto-server)
- `CHANGELOG.md` — storico modifiche

---

*Documento generato automaticamente dal sorgente. Ultimo aggiornamento: NeuRAG v1.2.2.*
