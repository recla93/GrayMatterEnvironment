# Gray Matter Environment — panoramica

> Il Gray Matter Environment è una suite di tre strumenti MCP che danno agli
> assistenti AI memoria persistente e una knowledge base strutturata. Un gateway,
> tutta la potenza.

## Cos'è

Gray Matter è un **gateway/proxy** che si piazza tra il tuo client AI (Claude Desktop, Cursor, VS Code, OpenCode, Gemini CLI, Windsurf, ecc.) e due backend specializzati:

- **Neuron** — memoria semantica persistente. Un grafo di concetti che ricorda cosa conta tra le sessioni: keyword, link, domini, salienza, fiducia, embeddings 384-dim. Impara dall'uso e fa decadere naturalmente i concetti dimenticati.
- **NeuRAG** — knowledge base gerarchica. Un vault strutturato di documenti suddivisi in chunk con ricerca vettoriale, organizzato in un albero godnode/fundamental/specialization. Features: auto-ingest, chunking AST-aware, Turso auto-provision, cross-linking.

Il client si connette a **un solo server MCP** (Gray Matter). GM scopre, gestisce e fa da proxy a Neuron e NeuRAG come worker subprocess. Ottieni la potenza di tre strumenti con una singola entry di configurazione.

## Quando usarlo

- Vuoi che il tuo assistente AI **ricordi** tra le sessioni (non partire freddo ogni volta)
- Hai una **knowledge base** (documenti, note, codice) che vuoi che l'assistente cerchi
- Vuoi **intelligenza cross-store**: la memoria di Neuron arricchisce la ricerca di NeuRAG, e viceversa
- Vuoi **semantic flash** — associazioni laterali che simulano il pensiero analogico
- Vuoi **auto-ingest** — scansiona una cartella e costruisci una knowledge base automaticamente

## Come si incastra

```
Client AI (Claude Desktop, Cursor, VS Code, OpenCode, ...)
    |
    | stdio (protocollo MCP)
    v
Gray Matter (gateway/orchestrator)
    |
    +-- Neuron (memoria semantica)     -- worker subprocess persistente
    +-- NeuRAG (knowledge base)        -- worker subprocess persistente
```

Il modello gateway significa:
- Una sola entry di server MCP nella configurazione del client
- Un solo processo da avviare
- Scoperta automatica dei sub-server (Neuron e NeuRAG vengono rilevati via `importlib`)
- Worker persistenti che mantengono caldi i modelli costosi (fastembed)
- **Bridge cross-store** che collegano i concetti di Neuron ai nodi di NeuRAG (Hebbian promotion/decay)
- **Cache contesto** (TTL + LRU) con invalidazione mirata che velocizza le query ripetute
- **Semantic flash** che surface associazioni laterali ogni N turni
- **Catalog** che introspecta argparse di ogni tool — nuovi comandi CLI appaiono nella GUI automaticamente
- **Registry GME** che traccia la salute across venv multipli per installazioni multi-tool
- **Scorciatoie Desktop** (cross-platform: .lnk/.command/.desktop) per accesso con un click

## Primi passi

### Installer one-click (consigliato)

**Windows** — doppio clic su `install.cmd`:
```powershell
.\install.ps1
```

**macOS / Linux**:
```sh
sh install.sh
```

### Verifica

```bash
gray-matter doctor                              # snapshot salute
gray-matter status                              # server registrati con lista tool
```

### Usa dal tuo client AI

```
gray_matter_pulse(topic="il tuo topic")        # chiamata unificata memory + knowledge
```

### Oppure standalone

```bash
# Solo Neuron
pip install neuron
neuron register

# Solo NeuRAG
pip install neurag
python -m neurag.server
```

## Progetti

| Progetto | Ruolo | Versione | Licenza |
|---|---|---|---|
| Gray Matter | Gateway/orchestratore | 1.1.2 | PolyForm Noncommercial 1.0.0 |
| Neuron | Memoria semantica | 6.1.2 | PolyForm Noncommercial 1.0.0 |
| NeuRAG | Knowledge base | 1.2.2 | PolyForm Noncommercial 1.0.0 |

## Mappa documentazione

### A livello suite
| Documento | Cosa copre |
|---|---|
| [ARCHITETTURA.md](../ARCHITETTURA.md) | Deep dive architettura (tutti e tre i progetti) |
| [INSTALL.md](INSTALL.it.md) | Installazione per umani e agenti AI |
| [GETTING-STARTED.md](GETTING-STARTED.it.md) | Tutorial end-to-end (10 min) |
| [TOOLS.md](TOOLS.it.md) | Riferimento completo tool MCP |
| [CLI.md](CLI.it.md) | Tutti i comandi command-line |
| [CONFIGURATION.md](CONFIGURATION.it.md) | Variabili d'ambiente e config knobs |
| [ARCHITECTURE.md](ARCHITECTURE.it.md) | Design interno e flusso dati |
| [DATA.md](DATA.it.md) | Schema database e path storage |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.it.md) | Problemi comuni e fix |
| [TECHNOLOGY.md](TECHNOLOGY.it.md) | Scelte tecnologiche: perché ogni tool è stato scelto |
| [EVOLUTION.md](EVOLUTION.it.md) | Come il progetto è arrivato qui, era per era |
| [PROCESS.md](PROCESS.it.md) | Come lavora il team, lezioni imparate |

### Per progetto
| Progetto | Docs |
|---|---|
| Neuron | [README](../neuron/README.md) • [INSTALL-AI](../neuron/INSTALL-AI.md) • [DOCTOOLUPDATE](../neuron/DOCTOOLUPDATE.md) |
| NeuRAG | [README](../neurag/README.md) • [INSTALL-AI](../neurag/INSTALL-AI.md) • [DOCTOOLUPDATE](../neurag/DOCTOOLUPDATE.md) |
| Gray Matter | [README](../gray_matter/README.md) • [INSTALL-AI](../gray_matter/INSTALL-AI.md) • [DOCTOOLUPDATE](../gray_matter/DOCTOOLUPDATE.md) |

---

## Prossimi passi

- [Installazione](INSTALL.it.md) — avvialo
- [Primi passi](GETTING-STARTED.it.md) — tutorial end-to-end (10 min)
- [Architettura](../ARCHITETTURA.md) — comprendi gli internals
- [Scelte tecnologiche](TECHNOLOGY.it.md) — perché ogni tool è stato scelto
