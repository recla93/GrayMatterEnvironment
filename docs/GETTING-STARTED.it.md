# Primi passi — tutorial end-to-end

> Install → primo pulse → primo store_turn → primo vault indicizzato → confirm/trust.
> Max 10 minuti di lettura. Ogni passo mostra l'output atteso.

## Prerequisiti

- Python 3.10 o successivo
- Un client AI compatibile con MCP (Claude Desktop, Cursor, VS Code, OpenCode, ecc.)

## Passo 1: installazione

### Opzione A — Installer one-click (consigliato)

**Windows** — doppio clic su `install.cmd` nella root:

```
.\install.ps1
```

**macOS / Linux**:

```sh
sh install.sh
```

Cosa fa: bootstra Python se mancante → un venv condiviso → installa GM + Neuron
+ NeuRAG → registra gateway nei client MCP → scorciatoia Desktop GUI.

### Opzione B — pip (source checkout)

```bash
git clone https://github.com/recla93/Neuron.git
cd Neuron

# Su Windows, aggiungi --find-links neuron/vendor per pyturso:
pip install --find-links neuron/vendor -e gray_matter -e neuron -e neurag

# Su Linux/macOS:
pip install -e gray_matter -e neuron -e neurag
```

### Opzione C — Repo singoli

```bash
pip install neuron neurag gray-matter
gray-matter install --gateway
```

Output atteso:
```
Installing (gateway model)...
  [OK] register: gray-matter added to Claude Desktop
Done. Restart your AI apps.
```

## Passo 2: verifica

```bash
gray-matter doctor
```

Output atteso:
```
Gray-Matter v1.1.2 — awake
  cache: 0 entries | bridges: 0
  [ok] neuron (alive, collab) worker+
  [ok] neurag (alive, collab) worker+
```

Se vedi `[DEAD]`, esegui `gray-matter stop && gray-matter start`.

## Passo 3: il tuo primo pulse

Dal tuo client AI, chiama:
```
gray_matter_pulse(topic="python testing")
```

Output atteso: una risposta testuale che combina il contesto Neuron (può essere
vuoto al primo uso) e i risultati NeuRAG (se hai knowledge indicizzata). Se
entrambi sono vuoti, è normale in un install fresco — la memoria si costruisce
nel tempo.

## Passo 4: persisti la tua prima memoria

Dopo che l'AI risponde a qualcosa di sostanziale, chiama:
```
gray_matter_store_turn(
  topic="python testing",
  keywords=["pytest", "fixtures", "mocking"],
  domain="backend",
  intent="exploration",
  sentiment="neutral"
)
```

Questo persiste i concetti nel grafo di Neuron. Al prossimo pulse su testing,
`pre_turn` поверх这些 keywords.

## Passo 5: carica contesto prima di rispondere

```
pre_turn(topic="python testing", keywords=["pytest"])
```

Restituisce contesto compatto dal grafo. Iniettalo silenziosamente nella risposta.

## Passo 6: indicizza una knowledge base

### Opzione A — Auto-ingest (consigliato)

Il tool `knowledge_ingest` scansiona un'intera directory e crea nodi, chunk,
embedding e link **server-side** in un'unica chiamata:

```
knowledge_ingest(path="/path/to/your/docs", godnode="BackEndNotes")
```

Questo crea:
- Root folder → godnode
- Sottocartelle primo livello → nodi fundamental
- Sottocartelle più profonde → nodi specialization
- File → chunk attaccati al nodo della cartella
- Embedding (se FastEmbed disponibile)
- Cross-link (tag_overlap + cross_ref)

### Opzione B — Passo passo

```
knowledge_index(path="/path/to/your/docs")
```

Restituisce chunk JSON. Poi organizationali:
```
knowledge_add_node(name="MyDocs", node_type="godnode")
knowledge_add_chunks(node_name="MyDocs", chunks=[...i chunk dal passo 1...])
knowledge_rebuild_links()
```

### Opzione C — CLI

```bash
neurag chunk /path/to/your/docs > chunks.json
neurag add-node MyDocs godnode
neurag add-chunks MyDocs --file chunks.json
```

## Passo 7: interroga la tua knowledge

```
knowledge_query(query="come configurare il logging", top_n=3)
```

Restituisce chunk rilevanti dai tuoi documenti indicizzati.

## Passo 8: conferma contesto utile

Quando `pre_turn` o `get_context` surface qualcosa di utile:
```
confirm(keywords=["pytest", "fixtures"], boost=2)
```

Questo rafforza quei concetti affinché compaiano più prominenti nel prossimo retrieval.

## Passo 9: controlla salute grafo

```bash
gray-matter doctor          # salute generale
gray-matter status          # server registrati con lista tool
```

Oppure direttamente:
```
neuron status               # statistiche grafo Neuron
knowledge_status            # statistiche knowledge base NeuRAG
```

Indicatori di salute per Neuron: strong+medium > 40%, nodes/turn tra 3-5,
pre_turn ≈ store_turn.

## Passo 10: smontaggio (opzionale)

```bash
gray-matter uninstall
```

La memoria è preservata a meno che non passi `--purge-data`.

---

## Cosa è successo

1. **Gray Matter** è partito come daemon, ha scoperto Neuron e NeuRAG, ha avviato i worker
2. **Neuron** ha caricato il grafo seed ed è pronto per memorizzare/recuperare concetti
3. **NeuRAG** ha inizializzato il DB knowledge con capability di vector search
4. Ogni `pulse` distribuisce a entrambi i backend in parallelo, unisce i risultati e cache
5. Il loop di memoria (`pre_turn` → risposta → `store_turn`) costruisce il grafo nel tempo
6. I bridge cross-store collegano concetti Neuron a nodi NeuRAG automaticamente
7. I semantic flash surface associazioni laterali ogni N turni
8. La cache contesto (TTL + LRU) velocizza le query ripetute

## Prossimi passi

- [Configurazione](CONFIGURATION.it.md) — regola flash rate, TTL cache, modello embedding
- [Architettura](ARCHITECTURE.it.md) — comprendi gli internals
- [Tools](TOOLS.it.md) — riferimento completo tool
