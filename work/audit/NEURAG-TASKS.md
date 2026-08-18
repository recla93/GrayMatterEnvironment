# TASK LIST — NeuRAG (v1.2.2)

> Chirurgica: ogni task indica esattamente cosa toccare, cosa si rompe, cosa serve.

---

## T1. Refactor `cli.py` — Estrarre comandi

**File toccati:**
- `neurag/cli.py` (DIVIDERE)
- `neurag/commands/` (NUOVO — cartella comandi)
- `neurag/commands/ingest.py` (NUOVO)
- `neurag/commands/query.py` (NUOVO)
- `neurag/commands/node.py` (NUOVO)
- `neurag/commands/status.py` (NUOVO)
- `neurag/commands/repair.py` (NUOVO)
- `neurag/commands/install.py` (NUOVO)

**Cosa fare:**
1. Creare `neurag/commands/` con un file per gruppo di comandi
2. Ogni file espone una funzione `register(subparsers)` che aggiunge i comandi
3. `cli.py` diventa router: importa i moduli, chiama `register()`, dispatcha
4. Lazy imports nei moduli comandi (già il pattern attuale in `cli.py`)

**Dipendenze intaccate:**
- `db.py` — nessuna modifica
- `server.py` — nessuna modifica
- `clients.py` — nessuna modifica
- `pyproject.toml` — entry point `[cli]` invariato

**Collegamenti da tenere a mente:**
- La GUI (`webgui.py`) chiama `python -m neurag.cli <cmd> --json` — verificare che i comandi newali siano raggiungibili
- `gray_matter/executor.py` chiama neurag via subprocess — i comandi devono restare compatibili
- Gli script `install.sh`/`.ps1` invocano `neurag start|stop|repair`

**Spunto soluzione:**
```python
# commands/node.py
def register(subparsers):
    p = subparsers.add_parser("add-node", help="Aggiunge un nodo")
    p.add_argument("name")
    p.add_argument("--type", default="specialization")
    p.add_argument("--parent")
    # ...
    return p

def run(args):
    from neurag.db import KnowledgeGraph
    kg = KnowledgeGraph()
    kg.add_node(args.name, args.type, args.parent)
    print(json.dumps({"ok": True, "name": args.name}))

# cli.py
from neurag.commands import node, query, ingest, status

def build_parser():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    node.register(sub)
    query.register(sub)
    ingest.register(sub)
    status.register(sub)
    return parser
```

**Evoluzione:**
- Plugin system: i comandi in file esterni (`.opencode/command/`)
- Comandi async: `asyncio.run(cmd.run(args))`

**Sforzo**: Alto (2-3 ore)  
**Rischio**: Medio (refactor grossi rompono test)  
**Priorità**: Media (fa bene ma non blocca nulla)

---

## T2. Refactor `db.py` — Estrarre search logic

**File toccati:**
- `neurag/db.py` (RIDURRE)
- `neurag/search.py` (NUOVO — search logic)
- `neurag/graph.py` (NUOVO — graph operations)

**Cosa fare:**
1. Estrarre `search()`, `_retrieve()`, `_rank_lexical()`, `_get_embedding()`, `_cosine_sim()` in `search.py`
2. Estrarre `add_node()`, `get_node()`, `get_children()`, `delete_node()`, ecc. in `graph.py`
3. `db.py` diventa connection manager + schema init

**Dipendenze intaccate:**
- `server.py` — importa da `db.py` oggi; ora importa da `search.py` e `graph.py`
- `ingest.py` — importa `KnowledgeGraph` da `db.py`
- `chunker.py` — nessuna modifica
- `embedder.py` — nessuna modifica

**Collegamenti da tenere a mente:**
- `KnowledgeGraph` è una classe unica oggi — dividerla richiede di passare la connessione
- Pattern: `SearchEngine(conn)` e `GraphManager(conn)` condividono la stessa connessione

**Spunto soluzione:**
```python
# search.py
class SearchEngine:
    def __init__(self, conn, embedder):
        self._conn = conn
        self._embedder = embedder
    
    def search(self, query, top_n=5, path_filter=None):
        # logica estratta da db.py
        pass

# graph.py
class GraphManager:
    def __init__(self, conn):
        self._conn = conn
    
    def add_node(self, name, node_type, parent_id=None):
        # logica estratta da db.py
        pass

# db.py
class KnowledgeGraph:
    def __init__(self, db_path=None):
        self._conn = self._connect(db_path)
        self.graph = GraphManager(self._conn)
        self.search = SearchEngine(self._conn, self._embedder)
```

**Evoluzione:**
- Repository pattern: `NodeRepository`, `ChunkRepository`, `LinkRepository`
- Unit of Work: transazioni esplicite

**Sforzo**: Alto (3 ore)  
**Rischio**: Medio  
**Priorità**: Media

---

## T3. Magic numbers → costanti nominate

**File toccati:**
- `neurag/settings.py` — aggiungere costanti (o nuovo file `constants.py`)
- `neurag/db.py` — sostituire numeri
- `neurag/server.py` — sostituire numeri
- `neurag/chunker.py` — sostituire numeri

**Cosa fare:**
Creare `constants.py`:
```python
EMBEDDING_DIM = 384
BUSY_TIMEOUT_MS = 5000
MAX_TRIGGERS_PER_NODE = 40
MIN_CHUNK_TEXT_LENGTH = 20
MAX_CHUNK_LINES = 60
HARD_CAP_CODE_CHUNKS = 160
MAX_TAGS_PER_CHUNK = 8
MAX_PHRASE_TAGS = 6
QUERY_TRUNCATION = 200
MAX_DEPTH_DEFAULT = 3
MAX_LIMIT_DEFAULT = 20
MAX_NEIGHBOR_DEPTH = 5
MAX_NEIGHBOR_LIMIT = 20
```

**Dipendenze intaccate:**
- Nessuna dipendenza rotta
- `constants.py` è SSOT, zero import circolari

**Collegamenti da tenere a mente:**
- `embedder.py` ha `DIM = 384` — allineare a `constants.EMBEDDING_DIM`
- I test che usano valori hardcoded vanno aggiornati

**Sforzo**: Basso (30 minuti)  
**Rischio**: Zero  
**Priorità**: Bassa (pulizia)

---

## T4. Fix duplicate import `re` in `db.py`

**File toccati:**
- `neurag/db.py`

**Cosa fare:**
Rimuovere `import re as _re` (linea 13) e usare solo `import re` (linea 14). Rinominare le chiamate.

**Sforzo**: Triviale (5 minuti)  
**Rischio**: Zero  
**Priorità**: Triviale

---

## T5. Rimuovere dead code

**File toccati:**
- `neurag/__version__.py` — CANCELLARE
- `neurag/models.py` — rimuovere `QueryResult`

**Cosa fare:**
1. Cancellare `__version__.py` (nessuno lo importa)
2. Rimuovere `QueryResult` da `models.py` (mai usato)
3. Rimuovere `Optional` da import in `models.py`

**Dipendenze intaccate:**
- Nessuna — `__version__` è in `__init__.py`
- `QueryResult` non è mai importato

**Sforzo**: Triviale (10 minuti)  
**Rischio**: Zero  
**Priorità**: Triviale

---

## T6. Validazione chunk all'ingest

**File toccati:**
- `neurag/db.py` — metodo `add_chunk()` o nuovo metodo
- `neurag/chunker.py` — validazione output
- `neurag/server.py` — gestione errori

**Cosa fare:**
Aggiungere validazione prima di scrivere chunk:
```python
def _validate_chunk(chunk: Chunk) -> bool:
    if not chunk.text or len(chunk.text) < MIN_CHUNK_TEXT_LENGTH:
        return False
    if not chunk.source:
        return False
    return True
```

In `add_chunk()`:
```python
def add_chunk(self, node_id, chunk):
    if not _validate_chunk(chunk):
        return {"ok": False, "error": "invalid chunk"}
    # ... proceed
```

**Dipendenze intaccate:**
- `ingest.py` — la validazione è trasparente
- `server.py` — i tool `knowledge_add_chunks` e `knowledge_import` restituiscono errori più chiari

**Collegamenti da tenere a mente:**
- Il chunker produce `Chunk` objects — la validazione è un gate
- Non rompere l'ingest esistente — i chunk validi passano, gli invalidi vengono scartati con warning

**Sforzo**: Basso (30 minuti)  
**Rischio**: Basso  
**Priorità**: Media

---

## T7. `__version__.py` inutile

**File toccati:**
- `neurag/__version__.py`

**Cosa fare:**
Cancellare il file. `__version__` è già in `__init__.py`.

**Sforzo**: Triviale  
**Rischio**: Zero  
**Priorità**: Triviale

---

## IDEE PER MIGLIORARE NEURAG

### Idea 1: AST chunking per più linguaggi
Oggi il chunking AST funziona solo per Python. Estendere a:
- Kotlin (parser tree via `kotlin-compiler` o regex)
- Java (stessa cosa)
- TypeScript/JavaScript (AST via `tree-sitter`)

Vantaggio: chunking preciso per i linguaggi backend principali.  
Sforzo: Alto.  
Valore: Alto (feature diferenciante).

### Idea 2: Incremental indexing con watchdog
`neurag watch <dir>` con `watchdog` per re-indicizzare automaticamente i file modificati.  
Vantaggio: il vault resta aggiornato senza re-indicizzare manualmente.  
Sforzo: Medio.  
Valore: Medio.

### Idea 3: Chunk dedup
Prima di scrivere un chunk, controllare se esiste già un chunk simile (coseno > 0.95). Se sì, skippare.  
Vantaggio: riduce dimensione DB e rumore nella search.  
Sforzo: Basso.  
Valore: Medio.

### Idea 4: Source attribution migliorata
Oggi `knowledge_query` restituisce `source` del chunk. Estendere con:
- Linea iniziale/fine del chunk nel file originale
- Link diretto al file (se il client lo supporta)
- Highlight delle parole chiave nel testo

Vantaggio: il LLM sa esattamente da dove viene l'informazione.  
Sforzo: Basso.  
Valore: Alto.

### Idea 5: Query expansion con trigger
Oggi cerca la query esatta. Estendere con:
1. La query matcha un trigger → naviga l'albero (già fatto)
2. La query non matcha → espande con synonyms/related terms dal grafo
3. Fallback a vector search

Vantaggio: migliora recall su query vague.  
Sforzo: Medio.  
Valore: Alto.

### Idea 6: Multi-format export
Esportare la knowledge base in:
- Markdown (per leggere offline)
- JSON (per migrare)
- GraphQL (per API)

Vantaggio: il vault non è lock-inato in Turso.  
Sforzo: Medio.  
Valore: Basso (YAGNI ora).

### Idea 7: Knowledge graph visualization
Un comando `neurag visualize` che genera un grafo HTML interattivo (D3.js o Mermaid).  
Vantaggio: capire la struttura del vault a colpo d'occhio.  
Sforzo: Medio.  
Valore: Medio.

---

*Fine task list NeuRAG.*
