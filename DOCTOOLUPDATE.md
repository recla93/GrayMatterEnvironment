# DOCTOOLUPDATE — Gray Matter v1.1.2

> Aggiornamento completo della documentazione tool per Gray Matter, il gateway MCP orchestrator.
> Generato il 2026-07-27. Include esempi di codice reale estratti dal sorgente.

---

## 1. Panoramica

Gray Matter è un **gateway MCP** che orchestra Neuron (memoria semantica) e NeuRAG (knowledge base) dietro un unico endpoint. Il client AI vede un unico server con tutti i tool combinati; Gray Matter fa da proxy, gestisce workers persistenti, cache, ponti cross-store e il control center (GUI + CLI).

**Architettura**: Python 3.10–3.14, MCP stdio server + IPC TCP per daemon mode. Due workers persistenti (uno per Neuron, uno per NeuRAG) con modello fastembed warm.

**Posizione**: `gray_matter/` — modulo installabile come `gray_matter`.

---

## 2. Architettura del Sistema

```
Client AI (Claude, Cursor, ...)
    │  MCP stdio
    ▼
┌─────────────────────────┐
│    Gray Matter Server    │  ← proxy + orchestrator
│  (gray_matter/server.py)│
├─────────────────────────┤
│  Router (tool → worker) │
│  Cache (TTL + LRU)      │
│  Bridges (Hebbian)      │
│  Flash (semantic)       │
├────────┬────────────────┤
│ Worker │    Worker      │  ← persistenti, fastembed warm
│ Neuron │    NeuRAG      │
│ (PID)  │    (PID)       │
└────────┴────────────────┘
```

---

## 3. Moduli Principali

### 3.1 `server.py` — MCP Server + IPC

Il server principale accetta tool call via MCP stdio e le instrada ai worker giusti.

```python
app = Server("gray-matter", version=__version__)

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Tool list: combinazione dei tool di Neuron + NeuRAG + GM propri."""
    # ...

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Router: ogni tool viene instradato al worker corretto."""
    # Se il tool è di Neuron → _call_worker("neuron", name, args)
    # Se il tool è di NeuRAG → _call_worker("neurag", name, args)
    # Se il tool è di GM → esecuzione diretta
```

**IPC Protocol** (server ↔ daemon):

```python
def _send_ipc(data: dict) -> dict:
    """Invia un messaggio JSON IPC al processo Gray-Matter locale."""
    payload = json.dumps(data).encode("utf-8")
    length = struct.pack("!I", len(payload))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(3.0)
        s.connect((GRAY_MATTER_HOST, resolve_port()))
        s.sendall(length + payload)
        hdr = _recv_exact(s, 4)
        resp_len = struct.unpack("!I", hdr)[0]
        resp_data = _recv_exact(s, resp_len)
        return json.loads(resp_data.decode("utf-8"))
```

**Auto-register**: quando Neuron o NeuRAG si avvian standalone, si registrano con Gray Matter:

```python
def autoregister(name: str, tool_names: list[str]) -> bool:
    """Auto-register con un Gray-Matter in esecuzione. Ritorna True se ok.
    Se Gray-Matter non gira, lo spawna prima."""
```

---

### 3.2 `_worker.py` — Worker persistenti

Ogni server (Neuron, NeuRAG) gira in un **worker persistente**: il modulo viene importato una sola volta, il modello fastembed resta caldo.

```python
def main() -> None:
    mod = importlib.import_module(sys.argv[1])   # es. "neuron.server"
    app = mod.app
    loop = asyncio.new_event_loop()
    for line in sys.stdin:
        req = json.loads(line)
        # Schema introspection:
        if req.get("op") == "list_tools":
            lt = app.request_handlers[_mcp_types.ListToolsRequest]
            lresp = loop.run_until_complete(lt(_mcp_types.ListToolsRequest(method="tools/list")))
            tools = [{"name": t.name, "description": t.description,
                      "inputSchema": t.inputSchema} for t in lres.tools]
            sys.stdout.write(json.dumps({"ok": True, "tools": tools}) + "\n")
            continue
        # Tool call:
        handler = app.request_handlers[_mcp_types.CallToolRequest]
        mcp_req = _mcp_types.CallToolRequest(
            params=_mcp_types.CallToolRequestParams(
                name=req["tool"], arguments=req.get("args", {})
            )
        )
        resp = loop.run_until_complete(handler(mcp_req))
        text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
        sys.stdout.write(json.dumps({"ok": True, "text": text, "ms": ...}) + "\n")
```

**Freshness TTL**: prima il grafo veniva svuotato a OGNI chiamata (collo di rete su Turso cloud). Ora si rilegge al massimo ogni 5 secondi:

```python
_FRESH_TTL = float(os.environ.get("GM_WORKER_FRESH_TTL", "5"))
```

---

### 3.3 `cache.py` — Context Cache (TTL + LRU)

Cache per i risultati di `pre_turn` e `gray_matter_pulse`:

```python
class ContextCache:
    """TTL + LRU cache per i risultati di contesto.
    
    TTL: i risultati scadono dopo cache_ttl_seconds (default 60s).
    LRU: max cache_max_size entry (default 100). Quando il cap è raggiunto,
    l'entry meno recentemente usata viene rimossa.
    """
    def get(self, key: str) -> str | None:
        """Restituisce il cached result o None se scaduto/assente."""
    def set(self, key: str, value: str) -> None:
        """Salva un result nella cache."""
```

---

### 3.4 `bridges.py` — Ponti Hebbian cross-store

Collega concetti Neuron a nodi NeuRAG con peso che si rafforza ad ogni uso (apprendimento di Hebb):

```python
def gray_matter_bridge(neuron_concept: str, neurag_node: str, rationale: str) -> str:
    """Persiste un ponte cross-store: un link tra un concetto Neuron e un nodo
    NeuRAG che l'orchestrator ha trovato correlato. Richiamato nei pulse futuri
    su entrambi gli endpoint."""
```

I ponti vengono:
1. Creati quando il pulse trova una correlazione
2. Rafforzati ad ogni uso (peso Hebbiano)
3. Recuperati nei pulse futuri (su entrambi gli endpoint)
4. Trasferibili tra locale e cloud (`bridges-transfer`)

---

### 3.5 `registry.py` — Server Registry

Registra i server MCP disponibili (Neuron, NeuRAG, Gray Matter):

```python
@dataclass
class ServerEntry:
    name: str
    module: str           # es. "neuron.server"
    tool_names: list[str]
    pid: int | None = None
    socket_path: str = ""
    registered_at: str = ""

class Registry:
    """Gestisce le entry dei server registrati."""
    def register(self, entry: ServerEntry) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> ServerEntry | None: ...
    def list(self) -> list[ServerEntry]: ...
```

---

### 3.6 `executor.py` — Install/Uninstall/Repair

Gestisce il ciclo di vita dell'installazione:

```python
def install(slug: str, python_exe: str) -> list[Result]:
    """Installa/ripara Gray Matter: registra nei client AI, collega Neuron e NeuRAG."""

def uninstall(slug: str) -> list[Result]:
    """Rimuove Gray Matter dai client. Chiede cosa fare della memoria."""

def repair(slug: str, python_exe: str, what_to_delete: dict) -> list[Result]:
    """Reinstall pulito: scegli cosa cancellare (memoria, knowledge, bridges, config)
    e cosa tenere, poi reinstalla forzato bypassando il check di versione."""
```

---

### 3.7 `settings.py` — Configurazione

Tutti i parametri tunabili in un unico JSON config:

```python
DEFAULTS = {
    "flash_min_gap": 3,           # pulses tra i flash (anti-spam)
    "stimulus_safety_net": True,  # GM ri-lancia lo stimulus se Neuron si silenzia
    "stimulus_safety_gap": 5,     # tool turns senza neuron prima del safety net
    "cache_ttl_seconds": 60,      # TTL context cache
    "cache_max_size": 100,        # LRU cap context cache
    "prewarm": True,              # pre-warm workers all'avvio
    "heartbeat_interval": 5.0,    # ping liveness server (s)
    "idle_sleep_timeout": 600.0,  # timeout idle prima dello sleep (s)
    "unmanaged": "",              # tool usciti dal gateway (go-standalone)
}

def set(key: str, value) -> dict:
    """Set un knob noto (type-coerced), persiste solo gli override, ritorna merged."""
```

---

### 3.8 `gme.py` — Tool Registry (GME)

SSOT per la scoperta dei tool e l'esecuzione multi-venv. Ogni tool scrive un JSON qui dopo l'install.

```python
# Location:
#   Windows: %LOCALAPPDATA%\GrayMatterEnvironment\
#   macOS:   ~/Library/Application Support/GrayMatterEnvironment/
#   Linux:   ~/.local/share/GrayMatterEnvironment/

def write_tool(tool_info: dict) -> None:
    """Scrive le info di un tool (python path, venv, status, health)."""

def read_tool(key: str) -> dict | None:
    """Legge le info di un tool."""

def list_tools() -> list[dict]:
    """Lista tutti i tool installati."""
```

---

### 3.9 `catalog.py` — Catalogo ambienti

SSOT per la GUI: legge i comandi dalle CLI esistenti (introspezione argparse) senza mantenere elenchi paralleli.

```python
GROUPS = (
    ("lifecycle",   "Ciclo di vita"),
    ("maintenance", "Manutenzione"),
    ("inspect",     "Ispezione"),
    ("tuning",      "Regolazione"),
    ("other",       "Altro"),
)

# Comandi che la GUI non mostra (aprirebbero un'altra GUI)
GUI_HIDDEN = {("gray-matter", "gui"), ("neuron", "gui"), ("neurag", "gui")}

# Comandi interattivi: la GUI li apre in un terminale vero
INTERACTIVE = {("gray-matter", "cloud"),
               ("neuron", "setup"), ("neuron", "manage"), ("neuron", "connect")}

HELP_IT = {
    ("gray-matter", "install"):   "Installa/ripara il gateway...",
    ("gray-matter", "uninstall"): "Rimuove Gray Matter dai client...",
    # ... 30+ comandi descritti
}
```

---

### 3.10 `cli.py` — CLI (24+ comandi)

```python
# Comandi principali:
# gray-matter install/uninstall/repair   — ciclo di vita
# gray-matter start/stop/status/ping     — daemon
# gray-matter register/deregister/link   — gestione client
# gray-matter config                     — tunable knobs
# gray-matter cloud                      — Turso setup
# gray-matter bridges/bridges-transfer   — cross-store
# gray-matter knowledge                  — manutenzione knowledge base
# gray-matter doctor/stats/logs          — diagnostica
# gray-matter gui                        — control center
# gray-matter bridge                     — HTTP bridge per connettori remoti
```

---

### 3.11 `shortcut.py` — Icona desktop

Cross-platform (Windows .lnk, macOS .command, Linux .desktop):

```python
def ensure_desktop_shortcut(tool: str, label: str, module_args: list[str],
                            description: str = "") -> bool:
    """Crea (una volta per installazione) un'icona desktop.
    Se il marker esiste ma il file è stato cancellato, ricrea.
    Non solleva mai: un fallimento non deve impedire l'apertura della GUI."""
```

---

## 4. Tool MCP Esposti

Gray Matter combina i tool di Neuron + NeuRAG + tool propri. Ecco i tool **propri** di GM:

### Memory Loop (pulse)
| Tool | Descrizione |
|------|-------------|
| `gray_matter_pulse(topic, top_n?)` | Pre-contesto + chunk knowledge + flash in un'unica chiamata |
| `gray_matter_auto(text)` | Extract + save automatico (0 token) |
| `gray_matter_status()` | Stato: server registrati, cache, contatori |

### Memory Management
| Tool | Descrizione |
|------|-------------|
| `pre_turn(topic, keywords, max_tokens?)` | Carica contesto (status + get_context compatto) |
| `store_turn(topic, keywords, domain, intent, sentiment, ...)` | Salva un turno curato |
| `gray_matter_confirm(keywords, boost?, confidence?)` | Feedback: boost salienza keyword utili |
| `gray_matter_forgotten(threshold?, top_n?, near?)` | Keyword non toccate da N turni |
| `gray_matter_find_candidates(keywords, top_n?)` | Screening: trova keyword simili prima di store |
| `gray_matter_vector_search(keywords, top_n?)` | Ricerca per similarità coseno |
| `gray_matter_switch_context(context)` | Cambia contesto attivo |
| `gray_matter_list_contexts()` | Lista tutti i contesti |

### Graph Maintenance
| Tool | Descrizione |
|------|-------------|
| `gray_matter_consolidate()` | Fonde duplicati + archivia orfani |
| `gray_matter_prune(dry_run?)` | Rimuovi link tangenziali |
| `gray_matter_merge(canonical, aliases)` | Unifica keyword duplicate |
| `gray_matter_dedup(enable?)` | Toggle deduplicazione |
| `gray_matter_flash()` | Toggle semantic flashbacks |
| `gray_matter_export()` | Esporta grafo completo JSON |
| `gray_matter_reset(confirm)` | Reset distruttivo |
| `gray_matter_summary()` | Riepilogo testuale |
| `gray_matter_introspect()` | Self-model C3 |

### Cross-Store
| Tool | Descrizione |
|------|-------------|
| `gray_matter_bridge(neuron_concept, neurag_node, rationale)` | Crea ponte cross-store |

---

## 5. Flusso: gray_matter_pulse

Il pulse è l'entry point principale per il memory loop:

```
1. gray_matter_pulse(topic="Spring Boot", top_n=5)
   │
   ├── neuron_get_context(topic, depth=1)   ← dalla cache o dal worker Neuron
   ├── neurag_query(query=topic, top_n=5)   ← dalla cache o dal worker NeuRAG
   │
   ├── Cache check: se entrambi i risultati sono nella TTL cache → ritorna cached
   │
   ├── Se non cached:
   │   ├── Esegui entrambe le query in parallelo (asyncio.gather)
   │   ├── Unisci risultati
   │   ├── Se flash abilitato: controlla flash trigger
   │   ├── Salva in cache (TTL + LRU)
   │   └── Ritorna risultato unito
   │
   └── Se flash scatenato: neurag_query con lateral keywords (serendipity)
```

---

## 6. Daemon Mode

Gray Matter può girare come daemon background:

```
gray-matter start   → spawn daemon (background process)
gray-matter stop    → ferma il daemon
gray-matter status  → stato daemon + server registrati
gray-matter logs    → ultime righe del log
```

Il daemon:
1. Ascolta su IPC TCP (host:port da config)
2. Spawn worker Neuron + NeuRAG (persistenti)
3. Gestisce heartbeat per monitorare i worker
4. Ripristina i worker crashati
5. Gestisce idle sleep timeout

---

## 7. Deploy e Configurazione

### Installazione
```bash
gray-matter install    # registra nei client + collega Neuron/NeuRAG
gray-matter start      # avvia daemon
```

### Configurazione
```bash
gray-matter config list              # mostra tutti i knob
gray-matter config set flash_min_gap 5   # modifica un knob
gray-matter config get cache_ttl_seconds  # legge un knob
```

### Turso Cloud
```bash
gray-matter cloud     # setup interattivo (URL + token)
```

### Standalone vs Gateway
```bash
gray-matter deregister neuron   # Neuron diventa standalone (doppia registrazione)
gray-matter link neuron         # Neuron torna sotto il gateway
```

---

## 8. Variabili d'Ambiente Chiave

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `GM_HOST` | `127.0.0.1` | Host IPC daemon |
| `GM_PORT` | `28789` | Porta IPC daemon |
| `GM_WORKER_FRESH_TTL` | `5` | TTL freshness cache worker (s) |
| `GM_LOG_LEVEL` | `INFO` | Livello log daemon |
| `TURSO_DATABASE_URL` | — | URL Turso (condiviso per i cred) |
| `TURSO_AUTH_TOKEN` | — | Token Turso |
| `NEURAG_TURSO_DATABASE_URL` | — | URL Turso NeuRAG (separato) |

---

## 9. Sicurezza

- Nessun endpoint esposto in produzione (solo IPC localhost)
- Token mai loggati o esposti
- Credenziali in `.env` con permessi ristretti
- Sanitizzazione control chars (fix header injection)
- Backup prima di ogni scrittura su config
- JSONC mai riscritto (perderebbe i commenti)
- Reset richiede `confirm=true`
- Daemon con heartbeat timeout (15s) → worker morti vengono ripristinati

---

## 10. Cross-References

- `neuron/` — sotto-server memoria semantica
- `neurag/` — sotto-server knowledge base
- `gray_matter/docs/` — documentazione GM
- `gray_matter/tests/` — test suite
- `work/audit/` — audit trail
- `docs/` — documentazione di sistema

---

*Documento generato automaticamente dal sorgente. Ultimo aggiornamento: Gray Matter v1.1.2.*
