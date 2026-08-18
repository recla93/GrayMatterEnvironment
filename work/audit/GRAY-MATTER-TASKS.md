# TASK LIST — Gray Matter (v1.1.2)

> Chirurgica: ogni task indica esattamente cosa toccare, cosa si rompe, cosa serve.

---

## T1. Fix L2 — Race condition Turso condiviso

**File toccati:**
- `gray_matter/_worker.py` — fix principale
- `neuron/src/neuron/db.py` — fix dipendente (T2 in NEURON-TASKS)
- `gray_matter/server.py` — gestione errori

**Cosa fare:**
Il problema: più processi GM aprono lo stesso `graph_*.db` con pyturso. `_graphs.clear()` + reload a ogni call → race su WAL/sidecar.

**Opzione A — File lock (consigliata):**
1. Aggiungere file lock in `db.py` di Neuron (vedi T4 in NEURON-TASKS)
2. In `_worker.py`, rimuovere `_graphs.clear()` prima di ogni call
3. Il worker mantiene la connessione aperta per tutta la vita

**Opzione B — Processo singolo:**
1. GM avvia un singolo worker per ogni DB
2. Gli altri processi parlano al worker via IPC
3. Elimina il problema alla radice ma complica l'architettura

**Dipendenze intaccate:**
- `neuron/db.py` — nuovo lock (NEURON-T4)
- `neuron/registry.py` — pool connessioni con lock
- `_worker.py` — meno chiamate a `_graphs.clear()`
- `server.py` — gestione errori migliorata

**Collegamenti da tenere a mente:**
- pyturso 0.6.1 ha il suo lock interno — verificare non conflitti
- Il lock va acquisito PRIMA dell'operazione, rilasciato DOPO
- Timeout lock: se un processo crasha, gli altri restano bloccati
- Test: servono 2 processi che scrivono sullo stesso DB contemporaneamente

**Spunto soluzione:**
```python
# _worker.py — prima:
def _call_server_async(self, tool, args):
    self._registry._graphs.clear()  # ← PROBLEMA
    result = self._call_tool(tool, args)
    return result

# _worker.py — dopo:
def _call_server_async(self, tool, args):
    # La connessione è persistente, nessun clear
    result = self._call_tool(tool, args)
    return result
```

**Evoluzione:**
- Server mode: un solo processo Neuron gestisce il DB
- Turso cloud: write isolation nativo
- Event sourcing: le modifiche sono eventi immutabili, non state mutabile

**Sforzo**: Medio (2 ore) + NEURON-T4  
**Rischio**: Medio  
**Priorità**: **CRITICA**

---

## T2. Refactor `server.py` — Estrarre logica

**File toccati:**
- `gray_matter/server.py` (RIDURRE)
- `gray_matter/handlers.py` (NUOVO — tool handlers)
- `gray_matter/cache.py` (esistente, eventuale modifica)

**Cosa fare:**
1. Estrarre i tool handler (`pulse`, `store_turn`, `status`, ecc.) in `handlers.py`
2. Estrarre la logica IPC in `ipc.py`
3. `server.py` diventa router + demone

**Dipendenze intaccate:**
- `registry.py` — nessuna modifica
- `cache.py` — nessuna modifica
- `_worker.py` — nessuna modifica
- `bridges.py` — nessuna modifica

**Collegamenti da tenere a mente:**
- Il demone MCP deve restare in `server.py` (entry point)
- I tool handler possono essere estratti senza rompere nulla

**Spunto soluzione:**
```python
# handlers.py
from .cache import ContextCache
from .registry import Registry

_ctx_cache = ContextCache()

def handle_pulse(args):
    topic = args.get("topic", "")
    # ... logica estratta
    return result

# server.py
from . import handlers

TOOL_MAP = {
    "gray-matter_pulse": handlers.handle_pulse,
    "gray-matter_store_turn": handlers.handle_store_turn,
    "gray-matter_status": handlers.handle_status,
}
```

**Evoluzione:**
- Plugin system: i tool handler in file esterni
- Async handlers: `asyncio.run(handler.run(args))`

**Sforzo**: Medio (2 ore)  
**Rischio**: Basso  
**Priorità**: Media

---

## T3. Flash cooldown persistente

**File toccati:**
- `gray_matter/server.py` — stato flash
- `gray_matter/flash.py` (se esiste, altrimenti in `server.py`)

**Cosa fare:**
Oggi `_flashed: set()` è in memoria e si resetta a ogni sessione. Soluzione: persistere in un file JSON o nel DB di Neuron.

**Opzione A — File JSON:**
```python
# flash.py
import json
from pathlib import Path

FLASH_STATE_PATH = Path.home() / ".local/share/gray-matter/flash_state.json"

def load_flashed() -> set:
    if FLASH_STATE_PATH.exists():
        return set(json.loads(FLASH_STATE_PATH.read_text()))
    return set()

def save_flashed(flashed: set):
    FLASH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FLASH_STATE_PATH.write_text(json.dumps(list(flashed)))
```

**Opzione B — In Neuron (consigliata):**
Usare il campo `last_flash` nei nodi di Neuron (se esiste) o aggiungerlo.

**Dipendenze intaccate:**
- `server.py` — legge/scrive stato flash da persistenza
- `flash.py` — nuovo modulo o estensione di `server.py`

**Collegamenti da tenere a mente:**
- Il cooldown deve essere per-topic, non globale
- Il file va pulito periodicamente (TTL sui record)

**Sforzo**: Basso (30 minuti)  
**Rischio**: Basso  
**Priorità**: Bassa

---

## T4. Fix `_first_conchet` parsing fragile

**File toccati:**
- `gray_matter/server.py` — metodo `_first_conchet` o equivalente

**Cosa fare:**
Il parsing dipende dal formato output di Neuron. Se Neuron cambia output, si rompe.

Soluzione: usare JSON strutturato invece di parsing testo:
1. Neuron restituisce JSON già oggi (i tool MCP usano JSON)
2. GM dovrebbe fare `json.loads()` invece di parsing testo
3. Se il parsing testo è necessario, usare regex robuste

**Dipendenze intaccate:**
- `neuron/server.py` — output dei tool (se si cambia formato)
- `gray_matter/server.py` — parsing

**Collegamenti da tenere a mente:**
- Il formato output di Neuron è un API contract implicito
- Se si cambia, tutti i client vanno aggiornati

**Sforzo**: Basso (30 minuti)  
**Rischio**: Basso  
**Priorità**: Bassa

---

## T5. Instructions in tutte le risposte

**File toccati:**
- `gray_matter/server.py` — handshake + risposte

**Cosa fare:**
Oggi le istruzioni vengono inviate solo all'handshake. Client che non le mostrano (es. Claude Desktop) non vedono il loop guidance.

Soluzione: aggiungere le istruzioni in output di `pulse` e `store_turn`:
```python
INSTRUCTIONS = """
After receiving context, you MUST call neuron_store_turn to persist the conversation.
This is mandatory for the memory system to work.
"""

def handle_pulse(args):
    result = _pulse(args)
    result["instructions"] = INSTRUCTIONS
    return result
```

**Dipendenze intaccate:**
- `server.py` — aggiunta instructions nelle risposte
- Nessun impact su Neuron/NeuRAG

**Collegamenti da tenere a mente:**
- Le istruzioni occupano token — non esagerare
- Bilanciare tra completezza e concisione

**Sforzo**: Triviale (10 minuti)  
**Rischio**: Zero  
**Priorità**: Bassa

---

## T6. `__version__.py` inutile (se esiste)

**File toccati:**
- `gray_matter/__version__.py` (se esiste)

**Cosa fare:**
Verificare se esiste e se è importato. Se non è importato da nessuno, cancellare.

**Sforzo**: Triviale  
**Rischio**: Zero  
**Priorità**: Triviale

---

## IDEE PER MIGLIORARE GRAY MATTER

### Idea 1: Eliminare GM (YAGNI radicale)
Se Neuron e NeuRAG funzionano standalone, GM è overhead. Il client parla direttamente con entrambi.  
Vantaggio: -50% complessità, -1000 righe di codice.  
Sforzo: Basso (tagliare).  
Valore: **ALTO** (se il client supporta 2 MCP server).

### Idea 2: GM come library, non demone
Invece di un demone TCP, GM è una libreria Python che il client importa. Nessun IPC, nessun worker.  
Vantaggio: zero latenza IPC, zero race condition.  
Sforzo: Medio.  
Valore: Alto.

### Idea 3: GM come plugin Neuron
GM è un plugin di Neuron, non un server separato. Neuron espone sia i suoi tool sia quelli di orchestramento.  
Vantaggio: un solo processo, zero IPC.  
Sforzo: Alto.  
Valore: Alto.

### Idea 4: Event-driven architecture
Invece di IPC request/response, GM usa eventi:
1. Client manda evento `pulse(topic="Java")`
2. GM pubblica evento `context_ready(data=...)`
3. Client riceve l'evento

Vantaggio: decoupling totale tra producer e consumer.  
Sforzo: Alto.  
Valore: Medio (overkill per un PoC).

### Idea 5: GM come gateway HTTP
Invece di MCP stdio, GM espone un'API REST/GraphQL. Il client usa HTTP.  
Vantaggio: language-agnostic, testabile con curl.  
Sforzo: Alto.  
Valore: Medio.

### Idea 6: Auto-discovery via mDNS
GM e i server si scoprono via mDNS (Bonjour/Avahi). Nessun port hardcoded.  
Vantaggio: zero config, funziona in rete locale.  
Sforzo: Medio.  
Valore: Basso (overkill per locale).

### Idea 7: Health dashboard live
Un endpoint HTTP che mostra:
- Stato dei server (alive/dead)
- Cache hit rate
- Flash generati
- Latenze medie

Vantaggio: observability senza log parsing.  
Sforzo: Basso.  
Valore: Medio.

### Idea 8: Zero-config mode
Se GM non è installato, Neuron e NeuRAG funzionano comunque standalone. GM si installa solo se l'utente lo chiede esplicitamente.  
Vantaggio: l'utente pigro non deve configurare nulla.  
Sforzo: Basso (già il comportamento attuale).  
Valore: Alto.

---

*Fine task list Gray Matter.*
