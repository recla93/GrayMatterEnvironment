# Riferimento CLI — tutti i comandi a riga di comando

> Ogni entry point CLI across Neuron, Gray Matter e NeuRAG. Verificati contro il
> codice sorgente. Entry point Gray Matter: `gray-matter`. Neuron: `neuron`. NeuRAG: `neurag`.

---

## CLI Gray Matter

Entry point: `gray-matter` (definito in `gray_matter/cli.py`).

### gray-matter status

Mostra i server registrati, il loro stato, PID, strumenti e modalita di collaborazione.

```
gray-matter status
```

### gray-matter start

Avvia Gray Matter come daemon in background. Polling fino a 3s per il bind della porta.

```
gray-matter start
```

### gray-matter stop

Invia IPC di shutdown al daemon.

```
gray-matter stop
```

### gray-matter ping

Verifica se il daemon e in ascolto su `:9876`.

```
gray-matter ping
```

### gray-matter isolate \<name\>

Esclude un server dal pulse combinato (rimane comunque richiamabile direttamente).

```
gray-matter isolate neuron
gray-matter isolate neurag
```

### gray-matter collaborate \<name\>

Re-inserisce un server nel pulse combinato.

```
gray-matter collaborate neuron
```

### gray-matter mode \<mode\>

Imposta TUTTI i server in `collaborate` o `separate`.

```
gray-matter mode collaborate
gray-matter mode separate
```

### gray-matter gui

Apre il pannello di controllo web. Aggiungi `--classic` per la GUI Tkinter legacy.

```
gray-matter gui
gray-matter gui --classic
```

### gray-matter register

Registra i server installati nei client MCP rilevati. Aggiungi `--gateway` per il modello proxy (registra solo gray-matter, rimuovi neuron/neurag).

```
gray-matter register
gray-matter register --gateway
```

### gray-matter install

Installazione idempotente del gateway: ripulitura orfani, creazione cartelle dati, registrazione GM nei client, deploy hook, scrittura manifest.

```
gray-matter install
gray-matter install --dry-run
```

### gray-matter uninstall

Rimuove Gray Matter. La cancellazione della memoria e interattiva a meno che `--purge-data`.

```
gray-matter uninstall
gray-matter uninstall --purge-data --yes
gray-matter uninstall --dry-run
```

### gray-matter bridges

Elenca i bridge cross-store persistiti (ordinati per peso).

```
gray-matter bridges
```

### gray-matter stats

Mostra i contatori dell'orchestrator: conteggio pulse, tasso hit cache, flash, bridge, latenza media.

```
gray-matter stats
```

### gray-matter doctor

Snapshot salute: server, worker, cache, bridge, tier engine NeuRAG.

```
gray-matter doctor
```

### gray-matter knowledge \<subcmd\>

Gestione knowledge base NeuRAG.

```
gray-matter knowledge status
gray-matter knowledge rebuild-links
gray-matter knowledge link-graph
```

### gray-matter gm-neuron \<tool\> \[args\]

Chiama qualsiasi strumento Neuron tramite l'orchestrator GM.

```
gray-matter gm-neuron pre_turn '{"topic":"kotlin coroutines"}'
gray-matter gm-neuron status
```

### gray-matter gm-neurag \<tool\> \[args\]

Chiama qualsiasi strumento NeuRAG tramite l'orchestrator GM.

```
gray-matter gm-neurag knowledge_query '{"query":"spring boot"}'
gray-matter gm-neurag knowledge_status
```

### gray-matter config \<action\> \[key\] \[value\]

Ottieni, imposta o elenca i knob regolabili.

```
gray-matter config list
gray-matter config get flash_min_gap
gray-matter config set cache_ttl_seconds 120
```

---

## CLI Neuron

Entry point: `neuron` (definito in `neuron/__main__.py`).

Default (nessun sottocomando) avvia il server MCP stdio.

### neuron (nessun arg)

Avvia il server MCP stdio. Accetta flag di isolamento:

| Flag | Scopo |
|---|---|
| `--graphs-dir PATH` | Sovrascrive la posizione dello store (imposta `NS_GRAPHS_DIR`) |
| `--local` | Forza il tier locale: rimuove le credenziali `TURSO_*` |
| `--slug NAME` | Override identita (imposta `NEURON_SLUG`) |

```
neuron
neuron --graphs-dir ./my-store --local
```

### neuron init

Configurazione client (nessun import pesante del server). Delega a `neuron/init.py`.

```
neuron init
```

### neuron register

Registra il server MCP nei client AI rilevati. Delega a `neuron/clients.py`.

```
neuron register
```

### neuron doctor

Diagnostica e riparazione registrazioni client. Delega a `neuron/clients.py`.

```
neuron doctor
```

### neuron consolidate

Fondi nodi quasi-duplicati + archivia orfani. Puo mirare un contesto specifico.

```
neuron consolidate
neuron consolidate --context java/spring
neuron consolidate --no-merge --sim-threshold 0.9
```

| Flag | Default | Descrizione |
|---|---|---|
| `--context` | tutti i contesti | Mirare un singolo contesto |
| `--no-merge` | false | Saltare il merge di quasi-duplicati |
| `--no-drop-orphans` | false | Saltare l'archiviazione degli orfani |
| `--sim-threshold` | 0.85 | Soglia coseno per il merge |

### neuron setup

CLI per il ciclo di vita (install, update, uninstall). Delega a `neuron/setup.py`.

```
neuron setup
```

### neuron manage

CLI per la gestione quotidiana. Delega a `neuron/manage.py`.

```
neuron manage
```

### neuron bridge

Espone il server stdio su HTTP per connector remoti. Delega a `neuron/bridge.py`.

```
neuron bridge
```

### neuron connect

Connetti e testa un DB Turso Cloud, poi salva in `.env`. Delega a `neuron/connect.py`.

```
neuron connect
```

### neuron console

Diagnostica grafo read-only. Aggiungi `--watch` per seguire.

```
neuron console
neuron console --watch
```

### neuron tunnel

HTTPS pubblico via cloudflared (si abbina a bridge). Delega a `neuron/tunnel.py`.

```
neuron tunnel
```

### neuron gui

Hub visuale Tkinter (anche l'eseguibile windowed `neuron-gui`). Delega a `neuron/gui.py`.

```
neuron gui
```

---

## CLI NeuRAG

Entry point: `neurag` (definito in `neurag/cli.py`).

### neurag status

Mostra lo stato della knowledge base: engine, percorso DB, conteggio nodi, chunk, embedded.

```
neurag status
```

### neurag chunk \<path\>

Dividi un file o directory in stdout come JSON (non salva).

```
neurag chunk ./my-docs
neurag chunk README.md
```

### neurag add-node \<name\> \<type\>

Aggiungi un nodo alla gerarchia.

```
neurag add-node Java godnode
neurag add-node Spring_Boot fundamental --parent Java --triggers spring boot microservices
```

| Flag | Descrizione |
|---|---|
| `--parent` | Nome nodo padre (obbligatorio per fundamental/specialization) |
| `--triggers` | Parole chiave trigger (separate da spazio) |

### neurag add-chunks \<node\>

Allega chunk da JSON (stdin o file) a un nodo.

```
neurag add-chunks Java --file chunks.json
echo '[{"text":"...","source":"..."}]' | neurag add-chunks Java
```

| Flag | Descrizione |
|---|---|
| `--file` | File JSON con array di chunk (default: stdin) |

### neurag query \<query\>

Cerca nella knowledge base. Match trigger prima, poi fallback a lessicale/vettoriale.

```
neurag query "spring boot configuration"
neurag query "kotlin coroutines" --top-n 3 --json
```

| Flag | Default | Descrizione |
|---|---|---|
| `--top-n` | 5 | Numero di risultati |
| `--json` | false | Output come JSON |

### neurag tree

Stampa l'albero completo dei nodi.

```
neurag tree
```

### neurag import \<mapping\>

Importazione massiva da file YAML.

```
neurag import mapping.yaml
```

### neurag health

Audit strutturale: controllo integrita (gerarchia rotta, chunk vuoti, duplicati).

```
neurag health
```

---

## Prossimi passi

- [Strumenti MCP](TOOLS.it.md) — firme complete degli strumenti
- [Configurazione](CONFIGURATION.it.md) — env var e knob
- [Risoluzione problemi](TROUBLESHOOTING.it.md) — problemi comuni
