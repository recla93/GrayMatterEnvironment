# Architettura — design interno e flusso dati

> Come i tre componenti si collegano, cosa succede durante un pulse, e le
> decisioni di design fondamentali con la loro rationale.

## Architettura di sistema

```
                    Client AI (Claude Desktop, Cursor, VS Code, ...)
                               |
                               | stdio (protocollo MCP)
                               v
                    +----------------------+
                    |   Gray Matter (GM)   |  <-- server.py
                    |  Orchestrator/Proxy  |
                    |                      |
                    |  ContextCache (LRU)  |  <-- cache.py
                    |  Bridges Store       |  <-- bridges.py
                    |  Registry            |  <-- registry.py
                    +----------+-----------+
                               |
                    +----------+-----------+
                    |   TCP IPC (:9876)    |  <-- CLI, GUI
                    +---------------------+

                    +----------------------+
                    |  Worker Persistenti  |  <-- _worker.py
                    |  (uno per sub-server)|
                    |                      |
                    |  +--------+ +------+ |
                    |  | Neuron | |NeuRAG| |
                    |  | worker | |worker| |
                    |  +---+----+ +--+---+ |
                    +------+---------+-----+
                           |         |
                      neuron.server  neurag.server
```

## Modello gateway

Il client MCP si connette a **un solo server**: Gray Matter. GM scopre autonomamente i sub-server installati (Neuron, NeuRAG) via `importlib.util.find_spec()`, recupera gli schemi reali dei loro strumenti dai worker persistenti, e li ripubblica con i nomi originali. Il client vede tutti gli strumenti di tutti i progetti come se fossero un unico server.

I sub-server girano come **worker subprocess long-lived** (`_worker.py`). Ogni worker:
- Importa il modulo server una volta sola (il modello fastembed resta caldo)
- Legge linee JSON su stdin, scrive risposte JSON su stdout
- E serializzato per-worker via `asyncio.Lock` per evitare interfluenze sulle pipe

Una versione precedente creava un nuovo subprocess per ogni chiamata. Il modello worker persistenti mantiene caldo il modello embedding costoso e evita la latenza di cold-start.

## Flusso dati: un pulse

1. Il client chiama `gray_matter_pulse(topic="kotlin coroutines")`
2. Controlla la `ContextCache` — se hit, restituisce la risposta cachata immediatamente
3. Se miss, distribuisce in parallelo:
   - Neuron `get_context(topic, depth=1)` — recupero memoria semantica
   - NeuRAG `knowledge_query(rag_query, top_n)` — ricerca knowledge base. La query viene espansa con gli ultimi 3 topic da un buffer conversazionale per il recall multi-turn
4. Unisce i risultati con separatore `---`
5. Allega i **bridge** cross-store rilevanti (link tra concetti Neuron e nodi NeuRAG). Se un bridge raggiunge peso 5+, auto-confirm del concetto Neuron (boost salience)
6. Se NeuRAG ha avuto un hit, recupera **vicini proattivi** (vicini strutturati a depth-2 non gia presenti nella risposta)
7. Lancia **Flash** ai cambio di topic: chiama Neuron `forgotten(threshold=5, near=topic)` per far emergere concetti dormienti a fascia media. Rate-limited (min 3 pulse + cooldown per concetto)
8. Se il flash ha surfaceato un concetto dormiente E NeuRAG ha avuto un hit, crea automaticamente un bridge cross-store (auto-discovery v3b)
9. Mette in cache la risposta, registra le statistiche di latenza, restituisce

## Decisioni di design fondamentali

### Apprendimento hebbiano dei bridge

I bridge cross-store rafforzano il loro peso ad ogni esposizione nel pulse (+1, cap a 1000). I bridge inutilizzati decadono durante i periodi di idle (peso -1 dopo 7 giorni, eliminati sotto 1.0). A peso >= 5, il concetto Neuron riceve un auto-confirm. Questa e la memoria propria dell'orchestrator che impara dall'uso.

### TTL dinamico della cache

I topic frequenti (spesso richiesti) guadagnano TTL di cache piu lunghi via estensione lineare: `TTL base * (1 + 0.5 * hits)`, cap a 3x. Un topic che viene colpito 4+ volte vive 3x piu a lungo di uno freddo.

### Isteresi del contesto

Il cervello non fa hard-reset del contesto ogni volta che un topic viene menzionato una volta. Neuron cambia il grafo attivo solo dopo `CONTEXT_SWITCH_THRESHOLD` (default 2) turni consecutivi che signalano lo stesso dominio non-attivo. I turni di feedback/clarification resettano il contatore.

### Split pianifica/esecutore per install/uninstall

`installer.plan()` e `uninstaller.plan()` sono funzioni pure (testabili, nessun side effect). `executor.py` e il sottile livello effectful. La memoria (grafo, DB, bridge) non viene mai cancellata senza consenso esplicito dell'utente.

### Stdlib prima

L'unica dipendenza runtime di Gray Matter e `mcp>=1.28.0,<2.0`. Il resto e stdlib: `argparse` (non click/typer), `json` (non pydantic per le settings), `http.server` (per la webgui), `tkinter` (per la GUI legacy), `socket`+`struct` (per IPC), `OrderedDict` (per LRU cache).

### Neuron: ranking di recupero composito

Il rank di un nodo mescola quattro segnali (ADR-003):

| Segnale | Peso | Cosa misura |
|---|---|---|
| `sim` | 0.5 | Similarita coseno con la query |
| `salience` | 0.3 | Rinforzo hebbiano (cosa conta) |
| `recency` | 0.2 | Quanto recentemente il nodo e stato attivo |
| `trust` | 0.1 | Fiducia dai segnali confirm/refute |

### NeuRAG: fallback ricerca a tre livelli

1. **Match trigger** — lookup SQL istantaneo via array triggers JSON
2. **Vector SQL** — `vector_distance_cos()` su Turso (quando pyturso disponibile)
3. **Cosine Python / TF-IDF** — fallback brute-force quando nessun vector SQL

Degradazione trasparente: l'utente non vede quale livello e attivo.

### NeuRAG: indicizzazione con LLM nel loop

`knowledge_index` solo suddivide e restituisce JSON. L'LLM decide dove piazzare i chunk nella gerarchia via `knowledge_add_node` + `knowledge_add_chunks`. Questo tiene l'umano/LLM in controllo della tassonomia.

## Protocollo IPC

Gray Matter espone un listener IPC TCP su `127.0.0.1:9876`. Usato dalla CLI e GUI per la gestione del daemon. Protocollo: prefisso lunghezza 4 byte big-endian + payload JSON.

| Azione IPC | Scopo |
|---|---|
| `register` | Registrare un sub-server con i suoi strumenti |
| `heartbeat` | Ping di keep-alive dai sub-server |
| `unregister` | Rimuovere un server |
| `isolate` / `collaborate` | Attivare/disattivare la partecipazione di un server al pulse |
| `mode` | Impostare tutti i server in collaborate o separate |
| `status` | Dump del registry |
| `stats` | Contatori dell'orchestrator |
| `doctor` | Snapshot salute |
| `knowledge_cmd` | Delegare a strumenti NeuRAG |
| `gm-neuron` / `gm-neurag` | Chiamare strumenti arbitrari su un sub-server specifico |
| `shutdown` | Stop graduale del daemon |

## Task in background (asyncio)

| Task | Scopo |
|---|---|
| `_ipc_listener` | Server TCP su :9876 per IPC |
| `_heartbeat_monitor` | Marca i server come morti se perdono heartbeat >15s |
| `_sleep_monitor` | Marca tutti i server come sleeping dopo timeout idle; esegue decay bridge |
| `_reap_dead_workers` | Uccide i worker subprocess per i server marcati come morti |
| `_prewarm_workers` | Spawn worker e lancia una lettura economa per riscaldare i modelli all'avvio |

---

## Prossimi passi

- [Dati](DATA.it.md) — schemi database
- [Strumenti](TOOLS.it.md) — cosa fa ogni strumento
- [Configurazione](CONFIGURATION.it.md) — tunables
