# Configurazione — variabili d'ambiente, knob e percorsi dati

> Fonte unica di verita per ogni tunable across Neuron, Gray Matter e NeuRAG.
> I valori sono verificati contro il codice sorgente al momento della scrittura.

## Variabili d'ambiente

### Neuron

| Variabile | Default | Dove letta | Scopo |
|---|---|---|---|
| `NS_GRAPHS_DIR` | per-utente (vedi Percorsi dati) | `config.py:63` | Sovrascrive la posizione del graph store |
| `NEURON_SLUG` | `"neuron5"` | `config.py:36` | Nome sottocartella per il graph store (permette v5 accanto a versioni precedenti) |
| `NS_EMBED_MODEL` | `"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` | `server.py:163` | Nome modello embedding (384-dim). Cambiare richiede re-embed completo (`scripts/reembed.py`) |
| `NS_EMBED_DIM` | `"384"` | `models.py:76` | Dimensione vettore embedding. Deve combaciare con `NS_EMBED_MODEL` |
| `NS_CONSOLIDATE_AUTO` | `""` (off) | `server.py:327` | Abilita consolidamento automatico ogni N turni (`"1"`, `"true"`, `"yes"`, `"on"` per abilitare) |
| `NEURON_CONSOLIDATE_EVERY` | `20` | `server.py:328` | Turni tra esecuzioni di consolidamento automatico |
| `NEURON_CONSOLIDATE_PROTECT_SALIENCE` | `8` | `server.py:336` | Soglia salience: nodi a o sopra questa soglia non vengono mai mergiati |
| `NEURON_TOPIC_SHIFT_THRESHOLD` | `0.3` | `server.py:135` | Soglia distanza coseno per il rilevamento del cambio topic |
| `NEURON_TANGENTIAL_EXPIRY_TURNS` | `5` | `models.py:45` | Turni di inattivita prima che i link tangential vengano eliminati |
| `NEURON_SALIENCE_DECAY_THRESHOLD` | `5` | `models.py:47` | Turni di inattivita prima che la salience inizi a decadere |
| `NEURON_SALIENCE_DECAY_AMOUNT` | `1` | `models.py:48` | Punti salience rimossi per tick di decadimento |
| `NEURON_HEBBIAN_COOLDOWN` | `2` | `models.py:54` | Turni minimi tra due conteggi di co-attivazione sullo stesso link |
| `NEURON_HEBBIAN_UPGRADE_MEDIUM` | `3` | `models.py:55` | Conteggio co-attivazione per promuovere tangential a medium |
| `NEURON_HEBBIAN_UPGRADE_STRONG` | `8` | `models.py:56` | Conteggio co-attivazione per promuovere medium a strong |
| `NEURON_DRIFT_COOLDOWN` | `5` | `models.py:61` | Turni minimi tra formazione/rafforzamento dello stesso drift link |
| `NEURON_DRIFT_EXPIRY_TURNS` | `3` | `models.py:62` | Turni di inattivita prima che un drift link venga eliminato |
| `NEURON_SLEEP_IDLE_SECONDS` | `1800` (30 min) | `models.py:67` | Secondi di idle prima che il sleep-mode si attivi al prossimo caricamento |
| `NEURON_STAGE_FRESH_SECONDS` | `21600` (6h) | `models.py:68` | Durata validita dello stimulus preparato durante il sonno |
| `NEURON_EPISODES_PER_NODE` | `5` | `models.py:71` | Max episodi (fatti) per nodo |
| `NEURON_EPISODE_MAX_CHARS` | `200` | `models.py:72` | Max caratteri per episodio (~40 token) |
| `NEURON_MAX_NODES` | `500` | `models.py:80` | Eviction dei nodi con salience piu bassa oltre questo limite |
| `NEURON_USER` | `""` | `server.py:1066` | Tag provenienza per i refs (campo `by` in DB condiviso) |
| `TURSO_DATABASE_URL` | `""` | `db.py:41` | URL database Turso Cloud remoto |
| `TURSO_AUTH_TOKEN` | `""` | `db.py:42` | Token auth Turso Cloud remoto |

### Gray Matter

| Variabile | Default | Dove letta | Scopo |
|---|---|---|---|
| `GM_HOME` | `%LOCALAPPDATA%/gray_matter` (Win) o `~/.local/share/gray_matter` (Linux) | `paths.py` | Directory radice per tutti i dati di GM |
| `GM_PREWARM` | `"1"` se `prewarm` e True | `server.py` | Disabilita il pre-warming degli worker all'avvio (`"0"` per saltare) |
| `GM_NEURON_CLIENTS` | (rilevato automaticamente) | `executor.py` | Sovrascrive il percorso degli asset client Neuron |
| `GM_GUI_NOBROWSER` | (non impostata) | `webgui.py` | Se impostata, non apre il browser per la web GUI |
| `GM_GUI_SELFTEST` | (non impostata) | `webgui.py` | Se impostata, chiude il webview dopo 1s (testing) |
| `GM_TURSO_DATABASE_URL` | (vuoto) | `bridges.py` | Tier cloud per i bridge GM — DB Turso PROPRIO (`gm_bridges`), mai quello di Neuron/NeuRAG |
| `GM_TURSO_AUTH_TOKEN` | fallback su `TURSO_AUTH_TOKEN` | `bridges.py` | Token per il DB bridge (può essere il group token condiviso) |
| `GRAY_MATTER_BRIDGES` | `<GM_HOME>/bridges.db` | `bridges.py` | Override path store bridge locale (un valore legacy `.json` migra una volta nel `.db` affiancato) |
| `GM_ENV_FILE` | `<GM_HOME>/.env` | `_env.py` | Path esplicito del `.env` a livello GM |
| `GM_NO_DOTENV` | (non impostata) | `_env.py` | Se impostata, salta il caricamento del `.env` GM |

Il daemon GM carica `<GM_HOME>/.env` all'avvio (l'env reale vince sempre;
disabilitato sotto pytest). I worker spawnati ereditano l'environment del
daemon, quindi un solo file può portare le credenziali cloud dell'intero trio:
`TURSO_*` (Neuron), `NEURAG_TURSO_*` (NeuRAG), `GM_TURSO_*` (bridge) — tre
database SEPARATI, un group token condiviso opzionale. Due strade, entrambe
idempotenti: `gray-matter cloud setup` auto-provisiona gruppo/DB/token — se la
turso CLI manca la offre lui (installer ufficiale, pinnato via
`GM_TURSO_CLI_VERSION`; opt-out `--no-cli-install` / `GM_TURSO_CLI_INSTALL=0`,
guida manuale se rifiuti) — mentre `gray-matter cloud wire --neuron-url …
--neurag-url … --gm-url …` NON richiede la turso CLI — incolli le URL (e un
token) dal dashboard Turso; il cablaggio parziale è lecito. Il pannello GUI
"Cloud group…" espone entrambe. `cloud status` riporta il tier di ogni
componente; `cloud teardown` de-cabla le env senza toccare i DB cloud.

### NeuRAG

| Variabile | Default | Dove letta | Scopo |
|---|---|---|---|
| `NEURAG_EMBEDDER` | `"auto"` | `embedder.py:56` | Selezione embedder: `auto` (fastembed se disponibile), `fastembed` (strict), `null` (solo lessicale) |
| `NEURAG_EMBED_MODEL` | `"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` | `embedder.py:20` | Sovrascrive il nome modello FastEmbed |
| `NS_EMBED_MODEL` | (stessa di sopra) | `embedder.py:21` | Condivisa con Neuron — un singolo env governa entrambi |
| `NEURAG_TURSO_DATABASE_URL` | (vuoto) | `db.py` | URL Turso Cloud remoto — DB PROPRIO di NeuRAG (mai quello di Neuron: collidono su `nodes`) |
| `NEURAG_TURSO_AUTH_TOKEN` | fallback su `TURSO_AUTH_TOKEN` | `db.py` | Token auth (può essere il group token condiviso) |

## Knob di configurazione Gray Matter

Gestiti via `gray-matter config get|set|list`. Memorizzati in `config.json` dentro `GM_HOME`.

| Chiave | Default | Tipo | Scopo |
|---|---|---|---|
| `stimulus_safety_net` | `true` | bool | GM rilancia lo stimolo quando il piggyback di Neuron tace (LLM ha dimenticato i tool) |
| `stimulus_safety_gap` | `5` | int | Turni-tool senza 🧠/⚡ prima che scatti la rete di sicurezza |
| `flash_min_gap` | `3` | int | Puls minimi tra eventi flash (anti-spam) |
| `cache_ttl_seconds` | `60` | float | TTL base per la context cache |
| `cache_max_size` | `100` | int | Cap LRU per la context cache |
| `prewarm` | `true` | bool | Pre-warm degli worker persistenti all'avvio |
| `heartbeat_interval` | `5.0` | float | Intervallo ping liveness server (secondi) |
| `idle_sleep_timeout` | `600.0` | float | Secondi di idle prima che i server vengano marcati come sleeping |

## Knob di configurazione NeuRAG

Gestiti via `neurag config get|set|list` (e, se Gray Matter è installato, dal control center — una **card Impostazioni** dedicata rende ogni knob come toggle/picker che si salva al volo; i knob si auto-descrivono da `settings.HELP`/`SUGGEST`). Memorizzati in `~/.local/share/neurag/config.json`, file **separato da `knowledge.db`** così una ricostruzione del DB non tocca mai le impostazioni. Vale per ogni install, anche NeuRAG standalone.

| Chiave | Default | Tipo | Scopo |
|---|---|---|---|

Lo stadio di rerank cross-encoder è stato rimosso a luglio 2026: misurato sul benchmark lasciava recall@5 invariata, peggiorava la metà *concept* di MRR (0.780 → 0.741) e costava 17x di latenza (397ms → 6815ms per query). La regola da tenere: `recall@50 − recall@5` è il tetto di qualunque reranker, perché riordina e non trova — misurala prima di rimetterne uno.

## Percorsi dati

### Graph store Neuron

Risolto da `config.py:graphs_dir()`:

| SO | Percorso predefinito |
|---|---|
| Windows | `%LOCALAPPDATA%\neuron5\graphs\` |
| Linux | `~/.local/share/neuron5/graphs/` |

Sovrascrivere con `NS_GRAPHS_DIR`. Ogni contesto ha il suo file: `graph_<context>.db`.

### Dati Gray Matter

Radice: `GM_HOME` (`%LOCALAPPDATA%\gray_matter` su Windows, `~/.local/share/gray_matter` su Linux).

| File/Cartella | Scopo |
|---|---|
| `config.json` | Override dei knob (solo le differenze dal default) |
| `bridges.json` | Link cross-store bridge |
| `manifest.json` | Manifest install: server installati, hook, percorsi dati |

### Dati NeuRAG

| SO | Percorso predefinito |
|---|---|
| Tutti | `~/.local/share/neurag/knowledge.db` |

Sovrascrivere passando `db_path` a `KnowledgeGraph()`.

## Livelli di storage (degradazione)

### Neuron

| Livello | Engine | Ricerca vettoriale | Quando |
|---|---|---|---|
| Turso remoto (cloud) | libsql-client | SQL `vector_distance_cos()` | `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` impostati, `libsql-client` installato |
| pyturso locale | pyturso | SQL `vector_distance_cos()` | pyturso installato, nessuna credenziale cloud |
| Fallback SQLite | sqlite3 | Cosine Python brute-force | Ne pyturso ne cloud disponibili |

Verificare il livello corrente: l'output di `neuron status` mostra `Engine: Turso (cloud)`, `Turso (local)` o `SQLite`.

### NeuRAG

| Livello | Engine | Ricerca vettoriale | Quando |
|---|---|---|---|
| pyturso locale | pyturso | SQL `vector_distance_cos()` | pyturso installato |
| Fallback SQLite | sqlite3 | Cosine Python brute-force o TF-IDF | pyturso non disponibile |

Verificare il livello: `gray-matter doctor` mostra `NeuRAG vector tier DEGRADED` quando su sqlite3.

## Riferimento versioni

Al momento della scrittura (luglio 2026):

| Componente | Versione | Fonte |
|---|---|---|
| Neuron | 6.1.0 | `pyproject.toml` |
| Gray Matter | 1.1.0 | `__version__.py` |
| NeuRAG | 1.2.0 | `pyproject.toml` |
| Protocollo MCP | >=1.28.0,<2.0 | `pyproject.toml` Neuron |
| pyturso | ==0.6.1 | `pyproject.toml` Neuron (pinned) |
| fastembed | >=0.5.0,<1.0 | `pyproject.toml` Neuron |
