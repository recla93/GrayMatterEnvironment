# Evoluzione

> Come il Gray Matter Environment è arrivato qui. Scritto esaminando il codice
> e i file CHANGELOG. I buchi sono segnati — servono input umani.

---

## Era 0 — Neuron standalone (prima di luglio 2026)

**Cosa esisteva:** Neuron come server MCP standalone. Singolo processo, singolo DB, 18 tool. Gli utenti chiamavano `neuron_pre_turn` e `neuron_store_turn` direttamente. Nessun gateway, nessun orchestrator.

**Cosa si è rotto:** Gli utenti dovevano configurare 2-3 server MCP separatamente (Neuron + NeuRAG + GM opzionale). Ogni assistente AI richiedeva registrazione individuale. Nessun apprendimento cross-store — la memoria episodica di Neuron e la knowledge base di NeuRAG erano isole.

**Cosa rimane:** I 18 tool core di Neuron, il sistema link hebbiani, la gerarchia contesti, il motore storage a 3 livelli. Tutto è ancora la fondazione.

> **[RIEMPI: intervallo versioni esatto, tag di rilascio, incidenti specifici che hanno triggerato il cambio]**

---

## Era 1 — Orchestrator Gray Matter (inizio luglio 2026)

**Idea:** Un singolo server MCP che ripubblica tutti gli tool. Gli utenti si connettono una volta. GM chiama Neuron e NeuRAG in parallelo via worker persistenti.

**Cosa è successo:**
- GM v0.1.0 costruito come orchestrator: `pulse` (context+knowledge parallelo), `bridge` (link cross-store), `status`
- Processi worker (`_worker.py`) hanno rimpiazzato re-import per chiamata (F0)
- IPC via TCP length-prefixed (F1 fixato)

**Cosa si è rotto:**
- F19: La cache singleton veniva ricreata dentro ogni `pulse` — la cache non colpiva mai
- F20: La cache si svuotava al cambio topic — non accumulava mai su topic alternati
- F12: I tool pass-through avevano `inputSchema` vuoto — i client non potevano validare le chiamate tool

**Cosa rimane:** Il pattern gateway, i worker paralleli, l'interfaccia GM a 3 tool.

---

## Era 2 — Flip gateway (2026-07-18)

**Cosa è successo:** `gray-matter register --gateway` ora espelle neuron/neurag da tutti i config client, registra solo GM. Singolo daemon via bind esclusivo (`SO_EXCLUSIVEADDRUSE`). Handshake stdio fixato (`InitializationOptions` ora include capabilities + istruzioni GM). GM serve 33 tool via pass-through con schemi reali (F12).

**Cosa si è rotto:**
- Istanze daemon duplicate (Claude Desktop spawn 2 client MCP da 1 entry)
- L2: `store_turn → open: NotFound` — intermittente, tracciato a `_graphs.clear()` + race WAL tra processi worker concorrenti sullo stesso file DB

**Cosa rimane:** Tutti i client si connettono a un server. Backup `.bak` abilita rollback. Singleton daemon enforceato dal kernel.

---

## Era 3 — Trust + Refs + Progetti (2026-07-20)

**Cosa è successo:**
- Colonna `Node.trust: float` con delta atomico `MAX(0, trust + ?)`
- Tool `confirm(confidence)`: alza trust, propagato in merge/dedup, confidence negativa = refute
- Tabella `refs`: riferimenti file/URL/commit strutturati, append-only, PK naturale
- `project.py`: marker `.neuron/project.json`, path relativi, provenance tracking
- Unificazione installer: `install.ps1` / `install.sh` canonici deleganti a GM

**Cosa rimane:** Trust si integra nel ranking. Refs abilitano provenance file. I progetti isolano la knowledge per-repo.

---

## Era 4 — Knowledge features (2026-07-20)

**Cosa è successo (NeuRAG):**
- `link_graph` + `rebuild_links`: link nodo con pesi ed evidence
- Source attribution nei risultati `knowledge_query` (D1)
- `neighbors`: vicinato BFS, JSON strutturato, solo SQL
- AST chunking: codice chunkato per funzione/classe, tag simboli mergiati nei trigger

**Cosa è successo (GM):**
- Pre-warm worker (`_prewarm_workers`: spawn + read cheap all'avvio)
- Buffer multi-turn (`_topic_buffer` deque di 3): espande query NeuRAG con contesto recente
- TTL cache dinamico: +50% per hit, cap 3x, heat preservato al refresh
- Knowledge proattiva: `neighbors` a depth 2 aggiunto come "Potrebbe interessarti: ..."

**Cosa rimane:** Il layer knowledge è completo per v1. Futuro: indicizzazione incrementale (D5), feedback loop.

---

## Era 5 — Documentazione + Release prep (2026-07-20)

**Cosa è successo:**
- DOCS-GUIDELINES.md scritto (verità dal codice, singola fonte, nessuna duplicazione)
- Doc a livello suite creati: 8 ENG + 8 ITA (OVERVIEW, ARCHITECTURE, CONFIGURATION, TOOLS, CLI, DATA, TROUBLESHOOTING, GETTING-STARTED)
- Doc per-project distribuiti
- Sapienziali (TECHNOLOGY, EVOLUTION, PROCESS) — questo documento è uno di essi
- Drift versione risolto (2026-07-21): versioni unificate a Neuron 6.0.0, NeuRAG 1.0.0, Gray Matter 1.0.0 su pyproject, `__version__`, README e docs

> **[RIEMPI: nomi tag di rilascio, date esatte per ere 0-1, incidenti non elencati]**

---

## Era 6 — Cervello nei server reali (2026-08-03)

**Cosa è successo:** La visione "cervello" è passata dai mock ai server reali, in 4 step verificati con test MCP runtime:
- `gray_matter/state.py`: blackboard sqlite con 3 tool (`state_set`/`state_get`/`state_delta`), TTL sulle chiavi
- `neuron/src/neuron/modes.py`: 4 modalità di retrieval (semantic default, focus, brainstorm, pattern), innestate in `_resolve_context` con 6° ritorno `pattern_hits`; pattern basato sul log append-only `turns.jsonl` (il design `patterns.json` da `nd.turn` era buggy: `nd.turn` è il turno di *creazione* del nodo, non l'ultimo tocco)
- Iniezione dal proxy GM: `_inject_neuron_mode` legge `cervello/mode` + `cervello/focus` dal blackboard e li inietta in get_context/pre_turn (il mode esplicito dell'agente vince)
- `gray_matter_brainstorm`: pool da nodi Neuron (distanza 1−cos) + chunk NeuRAG (rank come proxy), ordinati per distanza decrescente
- Reinstall con `install.ps1 -Force`: tool nuovi attivi in produzione, memoria preservata. Attenzione: quella reinstallazione si dichiarava `gray-matter 1.3.0 / neuron 6.3.0`, ma quelle versioni **non contengono il cervello** — era stato scritto dopo il tag. Le stringhe hanno smesso di nominare due basi di codice diverse con il rilascio qui sotto
- Reembed vettori: mismatch modello embedding (vettori all-MiniLM-L6 vs modello attivo multilingual) risolto con `scripts/reembed.py`; fix bug unicode (freccia → crasha console cp1252)

**Rilasciato come** Neuron 6.4.0, Gray Matter 1.4.0, NeuRAG 1.3.1. Lo stesso
rilascio ha sanato due cose che il precedente aveva spedito sbagliate: il
`__version__` di Neuron era fermo a `6.2.0` mentre `pyproject.toml` diceva
`6.3.0`, e le wheel di Gray Matter vendorizzate dentro `neuron/` e `neurag/`
erano rimaste a 1.2.0 — il test che sorveglia esattamente questo era rosso.

In più, `pre_turn` non consegna più i fatti di un nodo solo: erano gli episodi
di `nodes_pt[0]`, con entrambi i numeri costanti letterali, quindi ogni
concetto in più era un concorrente in più per l'unico posto disponibile. Ora
vengono dai primi `fact_nodes` nodi (default 3), ognuno attribuito.

**Cosa rimane:** il degrado Turso→sqlite3 (L2 guard) è un fallback per-processo, mai attivo in produzione a sessione singola (un processo proprietario per ogni DB).

**Idee future emerse dai test di creatività (2026-08-03):**
- Manutenzione come tool dei worker (reembed/backup/checkpoint via MCP) → elimina il lock nei casi di manutenzione
- Explainability on-demand (flag `why` su get_context/pre_turn: quale link/episode/salience ha fatto emergere un nodo) — i dati esistono già (references, episode)
- Routing del pulse guidato dal blackboard (mode → instradamento: pattern→log turni, brainstorm→distanza, focus→task attivo)
- Checkpoint WAL allo shutdown (PRAGMA wal_checkpoint(TRUNCATE))
- Scartate: sqld daemon (YAGNI a sessione singola), flash on-demand (già coperto da brainstorm), `body_status` (pura aggregazione di tre chiamate che l'agente può già fare)

Per la mappa anatomica e il criterio che decide a quale componente spetta una
capacità nuova: `gray_matter/docs/CERVELLO.md`. Il vault `brain/` non esiste
più — stava fuori da ogni repo.

---

## Thread aperti

| Thread | Stato | Prossimo |
|---|---|---|
| Race WAL daemon L2 | Intermittente, causa radice identificata | Respawn worker on failure, o rimozione `_graphs.clear()` |
| Indicizzazione incrementale (D5) | Non iniziato | watchdog/mtime su `neurag watch <dir>` |
| Feedback loop (B1-B4) | Parzialmente implementato (trust in) | Bridge auto-learning completo, Neuron `confirm` → salience feedback da GM |
| Embedding multilingue | Modello inglese, accettabile su ITA | Considerare `multilingual-e5-small` se la qualità diventa un problema |
| Allineamento versioni | Drift tra file | Riconciliare RELEASE-CHECKLIST vs README vs pyproject |
| Lock Turso in manutenzione | Coperto da L2 guard | Tool di manutenzione nei worker (reembed/backup via MCP); sqld se multi-sessione |
| Explainability retrieval | Non iniziato | Flag `why` su get_context/pre_turn (link, episode, salience) |
| Routing del pulse da blackboard | Non iniziato | mode → instradamento nel pulse |
| Reembed vettori neuron | Fatto (2026-08-03) | `--all` per i contesti inattivi (arredamento, frontend, veicoli) se serviranno |
