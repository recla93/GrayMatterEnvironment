# Audit Performance — Gray Matter Environment

**Data**: 2026-07-20  
**Stato**: Analisi completa dei 3 progetti (Neuron, NeuRAG, Gray Matter)

---

## Executive Summary

L'ecosistema è ben strutturato con tre livelli distinti:
- **NeuRAG**: Knowledge base fattuale (permanente)
- **Neuron**: Memoria episodica/concettuale (apprendimento)
- **Gray Matter**: Orchestratore/gateway

**Problema principale**: Concurrency su Turso condiviso e cold-start model embedding.

---

## 1. Performance Analysis

### 1.1 Latenze Attuali

| Operazione | Latenza | Bottleneck |
|---|---|---|
| Prima `pulse` (cold worker) | 2-5s | Import fastembed nel worker |
| `pulse` (cache miss, warm) | 1-3s | Neuron get_context + NeuRAG query in parallelo |
| `pulse` (cache hit) | <100ms | Solo lookup in-memory |
| `store_turn` | 0.5-1s | Scrittura DB + embedding |
| Flash check | 0.5-1s | `forgotten` + `vector_search` |

### 1.2 Otimizzazioni Implementate

✅ **Pre-warming parallelo** — `_prewarm_workers` in `main()`: attende registrazione, spawn worker + read cheap per caricare fastembed PRIMA del primo pulse.

✅ **Cache singleton** — Istanza unica `_ctx_cache` in `server.py` (F19 risolto).

✅ **IPC length-prefixed fixed** — `_recv_exact` leggere 4 byte di lunghezza poi `readexactly` (F1).

### 1.3 Otimizzazioni Mancanti

| # | Ottimizzazione | Dove | Stato |
|---|---|---|---|
| D2 | Worker pre-warm | `gray_matter/server.py` | ✅ fatto (2026-07-18) |
| D3 | Cache invalidation intelligente | `gray_matter/server.py` | ⬜ TTL dinamico |
| D4 | Store + pre-load async | `gray_matter/server.py` | ⬜ background DURANTE la scrittura |

---

## 2. Token Efficiency

### 2.1 Costi Token per Operazione

| Operazione | Costo |
|---|---|
| query keyword | ~10 |
| chunk restituito | ~80-150 |
| Totale per iniezione | ~300-500 |

### 2.2 Strategie di Ottimizzazione

✅ **Context cache** — `gray-matter_pulse` usa cache per topic già visti.

✅ **Pre-turn/store-turn loop** — Istruzioni incluse in handshake e tool outputs.

❌ **Manca**: Query expansion per aumentare recall senza aumentare prompt.

### 2.3 Raccomandazioni

1. Usare `neuron_find_candidates` PRIMA di `store_turn` per evitare duplicati
2. Limitare i chunk a 3-5 per topic (top_n clamp a [1,10])
3. Usare `gray-matter_pulse` invece di chiamate separate a Neuron/NeuRAG

---

## 3. Pulizia e Manutenzione

### 3.1 Consolidamento Automatico

**Configurazione**:
- `NS_CONSOLIDATE_AUTO=1` per attivare
- Ogni `CONSOLIDATE_EVERY=20` turni
- Soglia similitudine default 0.85

**Problemi**:
- ❌ `dry_run` mancante su `prune` (F4)
- ❌ Consolidamento non considera trust (C2 parzialmente implementato)

### 3.2 Prune dei Tangential Links

**Configurazione**:
- `NEURON_TANGENTIAL_EXPIRY_TURNS=5`
- Drift links: `NEURON_DRIFT_EXPIRY_TURNS=3`

**Audit**: Verificare periodicamente `neuron_summary` per trust/salience ratio.

### 3.3 Manutenzione Inattivi

✅ **Sleep mode** — Se nessun client connesso > 10 minuti:
- Salva stato
- Prune: `neuron_prune()` + dedup
- Sleep: chiude socket, rilascia memoria

---

## 4. Correttezza

### 4.1 Bugs Critici da Risolvere

| # | Bug | File | Impatto | Stato |
|---|---|---|---|---|
| L1 | UPDATE atomici Neuron | `Neuron/src/neuron/server.py` | **Alta** | ⬜ |
| L2 | `store_turn → open: NotFound` | `gray_matter/_worker.py` | **Alta** | ⬜ |
| L3 | `install.ps1` bundle GM | `Neurag/install.ps1` | Media | ⬜ |
| F4 | DRY-run su `prune` | Neuron | Media | ⬜ |
| F15 | `_first_conchet` parsing fragile | `server.py:406-414` | Basso | ⬜ |

### 4.2 Race Condition su Turso Condiviso

**Problema**: Più processi GM = più worker pyturso sullo STESSO `graph_*.db`

**Symptom**: `store_turn` fallisce con `open: NotFound`

**Cause**: `_graphs.clear()`+reload a ogni call → race su file WAL/sidecar

**Soluzione Proposta**:
1. Lock file a livello di processo
2. Ou serializzare le operazioni write
3. Considerare Turso Cloud per write isolation

### 4.3 Validazione Dati

✅ **Bridge validation** — `_clean` + `_valid_endpoint` (F4, F22)

✅ **Topic validation** — coerce/strip/collapse/cap (F23)

❌ **Chunk validation** — Manca controlli su:
- Chunk vuoti (< 20 char)
- Chunk senza source
- Nomi nodi duplicati

---

## 5. Struttura e Organizzazione

### 5.1 Directory Corrente

```
Gray Matter Enviroment/
├── gray_matter/         MCP orchestratore
│   ├── server.py        demone GM
│   ├── registry.py      registro server
│   ├── cache.py         cache contesto TTL
│   ├── bridges.py       cross-store links
│   ├── cli.py           CLI
│   ├── clients.py       registrazione client
│   ├── _worker.py       worker persistenti
│   └── tests/
├── Neuron/              MCP grafo semantico
│   ├── src/neuron/
│   │   ├── server.py    grafo nodi/link
│   │   ├── db.py        layer DB
│   │   ├── models.py    Node, Link, Graph
│   │   ├── registry.py  GraphRegistry
│   │   └── ...
│   └── tests/
├── Neurag/              MCP knowledge base
│   ├── server.py        server MCP
│   ├── db.py            KnowledgeGraph
│   ├── chunker.py       adaptive chunking
│   ├── embedder.py      Null/FastEmbed
│   └── tests/
└── ARCHITETTURA.md      documentazione
```

### 5.2 Pulizia Raccomandata

1. **Rimuovere** `Neuron/install.sh` al root (superato da `Neurag/install.sh`)
2. **Unificare** conftest in un unico file condiviso
3. **Aggiornare** `install.ps1` Windows con bundle GM

---

## 6. Raccomandazioni Prioritarie

### Fase 1 — Critica (da fare subito)

1. **Fix L1**: Implementare UPDATE atomici in Neuron (salience + trust delta)
2. **Fix L2**: Diagnosticare e fixare il bug `store_turn → open: NotFound`
3. **Aggiungere** test per race condition su Turso condiviso

### Fase 2 — Importante (medo termine mese)

1. **Implementare** `dry_run` su `prune`
2. **Aggiungere** validazione chunk a ingresso
3. **Implementare** TTL dinamico per cache

### Fase 3 — Miglioramento (prossimo trimestre)

1. **Knowledge proattiva** (D3)
2. **Multi-turn nel RAG** (D4)
3. **Incremental indexing** con watchdog (D5)
4. **`gray-matter logs --follow`** (E2)

---

## 7. Metriche di Salute

### 7.1 Controlli da Eseguire

```bash
# Test principali
python -m pytest Neuron/tests gray_matter/tests Neurag/tests -q

# Verifica cache
gray-matter stats | grep cache_hit_rate

# Verifica salute grafo
neuron summary | grep "strong_medium_pct"

# Verifica knowledge vault
neurag knowledge_health
```

### 7.2 Soglie di Allarme

| Metrica | Soglia | Azione |
|---|---|---|
| Cache hit rate | < 20% | Verificare TTL |
| Strong+medium ratio | < 40% | Verificare Hebbian |
| Pruned/total | > 50% | Verificare decay |
| Nodes per turn | > 8 | Verificare curation |

---

## 8. Cose "Wow" nel Codice

### 8.1 Hebbian Reinforcement con Decay
**File**: `Neuron/src/neuron/models.py:543-571`

```python
def reinforce_coactivation(self, keywords, turn: int | None = None) -> list[Link]:
    # "neurons that fire together wire together"
    # Promuove weight monotonicamente: tangential → medium → strong
```

**Perché è bello**: Implementa il principio neurologico con cooldown e soglie:
- `HEBBIAN_COOLDOWN = 2`: min turns tra due incrementi
- `HEBBIAN_UPGRADE_MEDIUM = 3`: tangential → medium
- `HEBBIAN_UPGRADE_STRONG = 8`: medium → strong

### 8.2 Context-Aware Database Schema
**File**: `Neuron/src/neuron/models.py:905-954`

La migrazione automatica aggiunge colonna `context` e ricostruisce indici. Supporta:
- **Local file**: ogni contesto = file separato
- **Turso Cloud**: context column per condividere il database

### 8.3 Stimulus Engine con Spreading Activation
**File**: `Neuron/src/neuron/models.py:678-720`

```python
def spreading_activation(self, seeds, k=2, decay=0.5, min_activation=0.01)
```

**Perché è bello**: Genera stimoli associative "flashback" con:
- Decay (0.5 per hop)
- Salience factor (nodi salienti = hub)
- Tracking del percorso per interpretability

### 8.4 Bridge Auto-Learning Hebbian
**File**: `gray_matter/bridges.py:65-94`

```python
def add_bridge(neuron_concept, neurag_node, rationale=""):
    # Idempotent, con weight reinforcement
    # Valuta lunghezza, auto-bridge, oversized blobs
```

---

## 9. Consigli di Implementazione

### 9.1 Implementa F4: DRY-run su prune
Aggiungi in `Neuron/src/neuron/server.py`:

```python
Tool(
    name="prune",
    inputSchema={
        "type": "object",
        "properties": {
            "context": {"type": "string", "default": ""},
            "dry_run": {"type": "boolean", "description": "Show what would be pruned without deleting", "default": False}
        }
    }
)
```

### 9.2 Aggiungi Query Expansion (D3 mancante)
In `gray_matter/server.py`, prima della ricerca:

```python
# Recupera trigger del nodo per espandere la query
if neuron_node:
    expanded_query = f"{topic} OR {' OR '.join(node['triggers'][:3])}"
```

### 9.3 Implementa Knowledge Proattiva (D3)
Dopo `pulse`, cerca nodi NeuRAG correlati non nel risultato:

```python
# Usa knowledge_query con depth=2
related_nodes = db.get_descendants(node_id)
if related_nodes:
    response += f"\n\nPotrebbe interessarti: {', '.join(n['name'] for n in related_nodes[:3])}"
```

### 9.4 TTL Dinamico per Cache
In `gray_matter/cache.py`:

```python
def get(self, topic: str) -> Optional[str]:
    # Topic caldi = TTL più lungo
    ttl = self._ttl * (1.5 if topic in self._hot_topics else 1.0)
    # ...
```

### 9.5 Batch Operations
`store_turn` e `knowledge_add_chunks` potrebbero beneficiare di:

```python
# Batch insert con single transaction
conn.executemany("INSERT INTO nodes ...", rows_batch)
```

---

## 10. Cose da Considerare per il Futuro

### 10.1 Vector Search su Turso Cloud
Attualmente usa `vector_distance_cos` in Turso locale. Per cloud:
- Verificare se il driver `libsql-client` supporta l'operatore
- Fallback a Python cosine se non disponibile

### 10.2 Compressione Embedding
I vettori 384-dim sono serializzati come blob. Considera:
- Compressione gzip sui blob
- Store solo embedding per nodi "salient"

### 10.3 WebSocket Transport
Per NeuRAG su cloud, considera `websocket://` invece di `https://` per lower latency.

---

## 11. Conclusioni

L'ecosistema Gray Matter è ben progettato ma richiede attenzione su:

1. **Concurrency**: La chiave per la scalabilità è risolvere le race condition su Turso
2. **Cold start**: Il pre-warming aiuta ma il modello è pesante
3. **Token efficiency**: La cache funziona bene, ma manca query expansion
4. **Manutenzione**: Consolidamento automatico richiede tuning

**Prossimo passo**: Focus su L1 e L2 per garantire correttezza dei dati prima di scalare.

**Cose davvero interessanti**:
- Hebbian reinforcement con decay
- Context-aware schema migration
- Stimulus engine con spreading activation
- Bridge auto-learning Hebbian