# TASK LIST — Neuron (v6.1.2)

> Chirurgica: ogni task indica esattamente cosa toccare, cosa si rompe, cosa serve.

---

## T1. Refactor `server.py` — Estrarre tool handlers

**File toccati:**
- `neuron/src/neuron/server.py` (DIVIDERE)
- `neuron/src/neuron/handlers.py` (NUOVO — tool handlers)
- `neuron/src/neuron/state.py` (NUOVO — stato globale)
- `neuron/src/neuron/__init__.py` (eventuale re-export)

**Cosa fare:**
1. Creare `state.py` con le variabili globali: `_embedder`, `_embed_fn`, `_ctx_cache`, `_domain_state`, `_loop_stats`, `_flash_cooldown`, `_registry`
2. Creare `handlers.py` con tutti i tool handler (`_tool_*`) estratti da `call_tool()`
3. `server.py` diventa router sottile: `call_tool()` → lookup in `handlers` dict → dispatch
4. Mantenere i re-export in `server.py` per backward compat (deprecation warning)

**Dipendenze intaccate:**
- `extraction.py`, `search.py`, `stimulus.py`, `funnel.py`, `curation.py` — tutti importati da `server.py`, ora importano da `state.py`
- `registry.py` — stato spostato in `state.py`
- `models.py` — nessuna modifica
- `config.py` — nessuna modifica

**Collegamenti da tenere a mente:**
- `_S()` lazy import in `search.py` legge lo stato da `server` — va aggiornato per leggere da `state`
- `stimulus.py` usa `_detect_topic_shift()` che dipende da `_domain_state` — spostare in `state`
- I test in `tests/` importano da `neuron.server` — verificare che i re-export funzionino

**Spunto soluzione:**
```python
# state.py
_state: dict = {}  # sostituisce le variabili globali

def get_state() -> dict:
    return _state

# handlers.py
from .state import get_state

def handle_store_turn(args: dict) -> dict:
    s = get_state()
    # ... logica estratta da server.py
    return result

# server.py
HANDLERS = {
    "neuron_store_turn": handle_store_turn,
    "neuron_get_context": handle_get_context,
    # ...
}

async def call_tool(name, arguments):
    handler = HANDLERS.get(name)
    if handler:
        return handler(arguments)
    raise UnknownTool(name)
```

**Evoluzione:**
- Verso plugin system: ogni handler in un file separato, registrato via decorator
- Verso async: i handler possono diventare async se serve parallelismo I/O

**Sforzo**: Alto (2-3 ore)  
**Rischio**: Medio (refactor grossi rompono test)  
**Priorità**: Media (fa bene ma non blocca nulla)

---

## T2. UPDATE atomici per salience

**File toccati:**
- `neuron/src/neuron/models.py` — metodo `Graph.add_node()` o nuovo metodo
- `neuron/src/neuron/db.py` — query UPDATE
- `neuron/src/neuron/server.py` — chiamate a salience update

**Cosa fare:**
Il problema: oggi `survivor.salience += delta` è read-modify-write in memoria. Se due processi scrivono sullo stesso DB, uno perde il delta.

Soluzione: portare il pattern già usato per trust:
```python
# Invece di:
node.salience += delta

# Fare:
db.execute("UPDATE nodes SET salience = MAX(0, salience + ?) WHERE id = ?", (delta, node.id))
```

**Dipendenze intaccate:**
- `models.py` — `Node.salience` diventa una proprietà read-only (il valore è nel DB)
- `db.py` — nuovo metodo `update_salience(node_id, delta)`
- `server.py` — tutti i punti che fanno `node.salience += ...`
- `registry.py` — `_graphs` cache potrebbe servire invalidazione

**Collegamenti da tenere a mente:**
- `Graph.add_link()` usa salience per calcolare weight — va aggiornato
- `Graph.consolidate()` e `_drop_orphans()` leggono salience — OK se read-only
- `Graph.compute_health()` calcola media salience — OK se read-only
- I test che modificano salience in memoria (`test_hebbian.py`, etc.) vanno aggiornati

**Spunto soluzione:**
```python
# db.py
def update_salience(self, node_id: int, delta: float):
    self._conn.execute(
        "UPDATE nodes SET salience = MAX(0, MIN(1.0, salience + ?)) WHERE id = ?",
        (delta, node_id)
    )

# models.py — Node
@property
def salience(self) -> float:
    # Legge dal DB, non dalla cache
    return self._db.get_salience(self.id)
```

**Evoluzione:**
- Stesso pattern per `decay`: i link tangential decadono con UPDATE atomico
- Batch update: `UPDATE nodes SET salience = salience * 0.99 WHERE salience > 0.1` per decay globale

**Sforzo**: Basso (1 ora)  
**Rischio**: Basso (pattern già validato per trust)  
**Priorità**: **ALTA** (blocca multi-writer)

---

## T3. Magic numbers → costanti nominate

**File toccati:**
- `neuron/src/neuron/config.py` — aggiungere costanti
- `neuron/src/neuron/db.py` — sostituire numeri
- `neuron/src/neuron/server.py` — sostituire numeri
- `neuron/src/neuron/models.py` — sostituire numeri

**Cosa fare:**
Creare in `config.py`:
```python
EMBEDDING_DIM = 384
BUSY_TIMEOUT_MS = 5000
MAX_TRIGGERS_PER_NODE = 40
MAX_KEYWORDS_PER_TURN = 20
MAX_CONTEXT_TOKENS = 400
DEPTH_DEFAULT = 1
DEPTH_MAX = 3
TOP_N_DEFAULT = 8
TOP_N_MAX = 10
```

Sostituire ovunque:
- `db.py`: `384` → `EMBEDDING_DIM`, `5000` → `BUSY_TIMEOUT_MS`, `40` → `MAX_TRIGGERS_PER_NODE`
- `server.py`: `400` → `MAX_CONTEXT_TOKENS`, `3` → `DEPTH_MAX`, `10` → `TOP_N_MAX`
- `models.py`: eventuali numeri hardcoded

**Dipendenze intaccate:**
- Nessuna dipendenza rotta — solo rinominazione
- `config.py` è SSOT, zero import circolari

**Collegamenti da tenere a mente:**
- `config.py` usa solo stdlib — non importare da altri moduli neuron
- I test che usano questi valori hardcoded vanno aggiornati

**Spunto soluzione:**
```python
# config.py
EMBEDDING_DIM = env_int("NS_EMBEDDING_DIM", 384)
BUSY_TIMEOUT_MS = env_int("NS_BUSY_TIMEOUT_MS", 5000)
# ...
```

**Evoluzione:**
- Le costanti diventano configurabili via env vars (già il pattern con `env_int`)
- Config file YAML/JSON per override persistente

**Sforzo**: Basso (30 minuti)  
**Rischio**: Zero  
**Priorità**: Bassa (pulizia)

---

## T4. Fix L2 — File lock per store_turn

**File toccati:**
- `neuron/src/neuron/db.py` — nuovo lock
- `gray_matter/_worker.py` — usa il lock

**Cosa fare:**
Il problema: più processi GM aprono lo stesso `graph_*.db` con pyturso. `_graphs.clear()` + reload a ogni call → race su WAL/sidecar.

Soluzione: file lock per processo:
```python
# db.py
import fcntl  # POSIX
# oppure msvcrt.locking su Windows

class LockedConnection:
    def __init__(self, path):
        self._lock_path = path + ".lock"
        self._lock_fd = None
    
    def acquire(self):
        self._lock_fd = open(self._lock_path, 'w')
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX)
    
    def release(self):
        if self._lock_fd:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self._lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
            self._lock_fd.close()
```

**Dipendenze intaccate:**
- `db.py` — `connect()` e `connect_local()` usano `LockedConnection`
- `_worker.py` — non deve più fare `_graphs.clear()` prima di ogni call
- `registry.py` — gestione pool connessioni con lock

**Collegamenti da tenere a mente:**
- pyturso 0.6.1 ha il suo lock interno — verificare che non conflicci
- Il lock va acquisito PRIMA dell'operazione, rilasciato DOPO
- Timeout lock: se un processo crasha con il lock, gli altri restano bloccati → servono timeout

**Spunto soluzione alternativa:**
Invece di file lock, usare un **processo singolo** per il DB:
- GM avvia un singolo worker per ogni DB
- Gli altri processi parlano al worker via IPC
- Elimina il problema alla radice

**Evoluzione:**
- Server mode: un solo processo Neuron gestisce il DB, gli altri sono client
- Turso cloud: write isolation nativo (ogni client ha la sua connessione)

**Sforzo**: Medio (2 ore)  
**Rischio**: Medio (lock su Windows è diverso da POSIX)  
**Priorità**: **ALTA** (blocca release)

---

## T5. Rimuovere dead code

**File toccati:**
- `neuron/src/neuron/__version__.py` — CANCELLARE
- `neuron/src/neuron/server.py` — rimuovere re-export deprecati

**Cosa fare:**
1. Cancellare `__version__.py` (nessuno lo importa)
2. In `server.py`, marcare i re-export con deprecation warning:
```python
# Deprecation warning per backward compat
import warnings
def __getattr__(name):
    if name in _DEPRECATED_EXPORTS:
        warnings.warn(f"{name} moved to {module}. Import from there.", DeprecationWarning)
        return _DEPRECATED_EXPORTS[name]
    raise AttributeError(name)
```

**Dipendenze intaccate:**
- Nessuna — `__version__` è in `__init__.py` (SSOT)
- I re-export servono per backward compat: non cancellare subito

**Collegamenti da tenere a mente:**
- Alcuni test potrebbero importare da `neuron.server` direttamente — verificare

**Sforzo**: Triviale (10 minuti)  
**Rischio**: Zero  
**Priorità**: Triviale

---

## T6. Consolidare import `re` in `db.py`

**File toccati:**
- `neuron/src/neuron/db.py`

**Cosa fare:**
Rimuovere `import re as _re` (linea 13) e usare solo `import re` (linea 14). Rinominare le chiamate da `_re.xxx` a `re.xxx`.

**Dipendenze intaccate:**
- Nessuna

**Sforzo**: Triviale (5 minuti)  
**Rischio**: Zero  
**Priorità**: Triviale

---

## IDEE PER MIGLIORARE NEURON

### Idea 1: Plugin system per tool
Ogni tool handler in un file separato, registrato via decorator:
```python
@register_tool("neuron_store_turn")
def handle_store_turn(args): ...
```
Vantaggio: aggiungere tool senza toccare `server.py`.  
Sforzo: Alto.  
Valore: Medio (oggi i 22 tool bastano).

### Idea 2: Async I/O
Il server MCP è sync. Con async, le operazioni DB e embedding possono essere non-bloccanti.  
Vantaggio: migliora latenza con molti client.  
Sforzo: Alto.  
Valore: Basso (un solo client alla volta).

### Idea 3: Embedding lazy con cache LRU
Oggi l'embedding viene calcolato a ogni `store_turn`. Con cache LRU, lo stesso testo non viene re-embedded.  
Vantaggio: -50% latenza su turni ripetuti.  
Sforzo: Basso.  
Valore: Medio.

### Idea 4: Graph serialization binario
Oggi il grafo è in SQLite con BLOB. Un formato binario custom (msgpack/protobuf) potrebbe essere più veloce per il caricamento.  
Vantaggio: -30% cold start.  
Sforzo: Alto.  
Valore: Basso (SQLite va già bene).

### Idea 5: Multi-tenant nativo
Oggi il multi-context è gestito dal registry. Un supporto nativo con namespace nel DB eliminerebbe la complessità del registry.  
Vantaggio: meno codice, meno bug.  
Sforzo: Alto.  
Valore: Medio.

---

*Fine task list Neuron.*
