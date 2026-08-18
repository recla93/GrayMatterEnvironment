# Risoluzione problemi — sintomi, diagnosi, soluzioni

> Problem comuni across Neuron, Gray Matter e NeuRAG. Ogni voce: sintomo →
> come diagnosticare → come risolvere.

## Gray Matter non in esecuzione

**Sintomo:** `gray-matter status` restituisce "Gray-Matter not running".

**Diagnosi:** `gray-matter ping` — verifica se il daemon e in ascolto su `:9876`.

**Soluzione:** `gray-matter start`. Se fallisce il bind, controlla processi bloccati: su Windows `netstat -ano | findstr 9876`, su Linux `lsof -i :9876`. Uccidi il processo bloccato, poi `gray-matter start`.

## Nessun server visibile in gray-matter status

**Sintomo:** `gray-matter status` mostra 0 server.

**Diagnosi:** `gray-matter doctor` — mostra quali server sono registrati e vivi.

**Soluzione:** Assicurati che Neuron e/o NeuRAG siano installati (`pip install neuron`, `pip install neurag`). Poi `gray-matter install` o `gray-matter register --gateway` per registrare di nuovo.

## Pulse restituisce "No servers available"

**Sintomo:** `gray_matter_pulse` restituisce "No servers available for pulse."

**Diagnosi:** `gray-matter status` — controlla se neuron/neurag sono elencati e vivi. Se elencati ma morti, controlla lo stato del worker subprocess.

**Soluzione:** `gray-matter stop` poi `gray-matter start` per riavviare tutti i worker. Se un server specifico continua a morire, controlla i log (stderr del worker subprocess).

## Worker subprocess muore ripetutamente

**Sintomo:** `gray-matter doctor` mostra `[DEAD] neuron` o `[DEAD] neurag`.

**Diagnosi:** Esegui il server direttamente per vedere l'errore:
```bash
# Neuron
python -m neuron

# NeuRAG
neurag-mcp
```

**Soluzione:** Cause piu comuni:
- Dipendenza mancante: `pip install neuron` o `pip install neurag`
- pyturso: installa dai wheel vendored (`Neuron/vendor/`)
- Seed DB mancante: reinstalla il package

## NeuRAG vector tier DEGRADED

**Sintomo:** `gray-matter doctor` mostra `[!!] NeuRAG vector tier DEGRADED (sqlite3, Python cosine)`.

**Diagnosi:** pyturso non e installato. NeuRAG degrada a sqlite3 + cosine Python brute-force.

**Soluzione:** Installa pyturso dai wheel vendored: `pip install Neuron/vendor/pyturso-0.6.1-*.whl` (specifico per piattaforma). Il tier completo dà `vector_distance_cos()` SQL nativo.

## Errore "open: NotFound" (bug L2)

**Sintomo:** Una chiamata a un tool restituisce `[tool_name] error: open: NotFound` senza info su file o riga.

**Diagnosi:** Questo e un bug noto della libreria MCP che ingoia i traceback. L'errore si verifica quando il livello protocollo MCP fallisce nell'aprire una risorsa.

**Soluzione:** Verifica che l'URI della risorsa richiesta esista. Per le skill Neuron, gli URI sono `neuron://skill/playbook` e `neuron://skill/curated`. Riavvia il server MCP se il problema persiste.

## Grafo appare vuoto dopo installazione

**Sintomo:** `neuron status` mostra 0 nodi su un'installazione fresca.

**Diagnosi:** Controlla il percorso del graph store: `neuron console` mostra la posizione dello store attivo. Verifica che il seed DB esista al `data/base_knowledge.db` del package.

**Soluzione:** Il seed DB viene caricato alla prima chiamata a `get_context` o `pre_turn`. Chiama `neuron status` o `pre_turn(topic="test")` per triggerare l'inizializzazione. Se ancora vuoto, reinstalla: `pip install --force-reinstall neuron`.

## Il client non vede gli strumenti Neuron/NeuRAG

**Sintomo:** Il tuo client AI mostra solo gli strumenti Gray Matter, non quelli pass-through da Neuron/NeuRAG.

**Diagnosi:** `gray-matter status` — controlla se neuron/neurag sono elencati con i loro strumenti. Se la colonna strumenti e vuota, il worker non ha risposto a `list_tools`.

**Soluzione:**
1. `gray-matter stop && gray-matter start` — riavvia i worker
2. Se ancora vuoto, controlla che neuron/neurag siano importabili: `python -c "import neuron; import neurag"`
3. Registra di nuovo: `gray-matter register --gateway`

## Doppio daemon GM

**Sintomo:** `gray-matter status` mostra voci multiple o comportamento inaspettato.

**Diagnosi:** `gray-matter ping` potrebbe avere successo ma il daemon sbagliato sta gestendo le richieste.

**Soluzione:** `gray-matter stop` (invia shutdown al daemon su :9876). Attendi 2s. `gray-matter start`.

## Cache restituisce risultati stale

**Sintomo:** Pulse restituisce informazioni vecchie anche dopo aver aggiornato la knowledge base.

**Diagnosi:** La context cache (`cache_ttl_seconds`, default 60s) potrebbe servire una risposta cachata.

**Soluzione:** Attendi la scadenza del TTL, o riavvia Gray Matter (`gray-matter stop && gray-matter start`). Per freschezza immediata: `gray-matter config set cache_ttl_seconds 0` (poi rimetti a 60 dopo).

## Store Neuron ha smesso di persistere turni (Turso Cloud)

**Sintomo:** `neuron status` mostra nodi ma `pre_turn` non li surface mai.

**Diagnosi:** La connessione Turso remota potrebbe essere caduta silenziosamente. Verifica con `neuron connect` (testa la connessione).

**Soluzione:** La logica `_reconnect` dovrebbe gestire automaticamente questo (T76). Se non lo fa, `gray-matter stop && gray-matter start` ricrea il worker con una connessione fresca. Per problemi persistenti, verifica che `TURSO_AUTH_TOKEN` non sia scaduto.

## Mismatch dimensione embedding

**Sintomo:** Errore sulla dimensione dell'embedding che non corrisponde a `VECTOR_DIM` (384).

**Diagnosi:** Il grafo e stato creato con un diverso `NS_EMBED_MODEL` (diversa dimensione). I vettori di modelli diversi NON sono confrontabili.

**Soluzione:** Re-embed completo: `python scripts/reembed.py` (nel repo Neuron). Questo rigenera tutti i vettori con il modello corrente. Cambiare `NS_EMBED_MODEL` senza re-embed corrompe i risultati di ricerca.

## Health check NeuRAG mostra problemi

**Sintomo:** `neurag health` o `knowledge_health` segnala problemi serii.

**Diagnosi:** Problemi comuni:
- **Gerarchia rotta:** un nodo fa riferimento a un padre che non esiste
- **Chunk vuoti:** chunk con solo spazi
- **Nomi nodo duplicati:** due nodi con lo stesso nome

**Soluzione:** Questi sono problemi di integrita dei dati. Usa `knowledge_health` per identificare i nodi coinvolti, poi correggi manualmente via `knowledge_add_node` / `knowledge_add_chunks`. Non c'e riparazione automatica.

---

## Prossimi passi

- [Configurazione](CONFIGURATION.it.md) — controlla env var e default
- [Dati](DATA.it.md) — capire cosa e memorizzato dove
- [Architettura](ARCHITECTURE.it.md) — capire perche le cose funzionano cosi
