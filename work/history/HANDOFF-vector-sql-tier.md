# Handoff — fix del tier SQL vettoriale (Neuron + NeuRAG)

Data: 2026-08-05. Sessione: analisi paperdb.app → misura del percorso caldo dei
flash → scoperta e fix di un bug in due repo.

## Stato: due branch pushati, CI da controllare

| repo | branch | commit | versione | test |
|---|---|---|---|---|
| Neuron | `fix/vector-sql-tier` | `a0b7f96` | 6.4.0 → **6.4.1** | 329 passed, 1 skipped |
| NeuRAG | `fix/vector-sql-tier` | `0795757` | 1.3.1 → **1.3.2** | 377 passed, 1 skipped |

PR da aprire (nessuna delle due aperta):
- https://github.com/recla93/Neuron/pull/new/fix/vector-sql-tier
- https://github.com/recla93/NeuRAG/pull/new/fix/vector-sql-tier

## Il bug, in una riga

La SQL di ricerca vettoriale usava `vector_distance_cos(f32blob(x), f32blob(?))`.
`f32blob` non esiste in nessun build libSQL/pyturso (verificato su pyturso 0.6.1:
`Parse error: no such function: f32blob`). `vector_distance_cos` accetta già il
blob. Risultato: la query sollevava a ogni chiamata, un `except` la inghiottiva,
e tutto cadeva sul cosine Python. In entrambi i repo, per porting a mano.

## Cosa cambia davvero, per repo

**Neuron** — due conseguenze, la seconda peggiore della prima:
1. Latenza: 124 ms → 27 ms per turno al cap di 500 nodi, e il costo diventa
   piatto rispetto alla dimensione del grafo. Con il seed conteso da un altro
   processo erano ~1,5 s/turno (il `_drop_seed_connection` nell'except forzava
   la riapertura di 2,8 MB, che finiva nel retry-loop del guard L2).
2. **Correttezza**: il fallback Python itera solo `graph.nodes`, cioè il grafo in
   memoria. Il seed `base_knowledge.db` è consultato SOLO dal tier SQL. Col tier
   morto, le 139 keyword del seed non venivano mai cercate e `_refine_domain`
   ripiegava sui grafi caricati invece che sulla tassonomia dei domini del seed.

**NeuRAG** — solo prestazioni. Verificato su 12 chunk / 5 query con embedding
reali: ranking SQL e Python **identici, 0 divergenze**. Il fallback qui leggeva
la stessa tabella `chunks` con la stessa `where`, quindi nessun buco di dati.

## Da fare, in ordine

1. **CI sui due branch, poi merge.** È il passo che stavi seguendo tu.
2. **Verificare il tier Turso CLOUD.** Non testato: serve `TURSO_DATABASE_URL` +
   `TURSO_AUTH_TOKEN`. Se `f32blob` manca anche lì, il path remoto degradava
   allo stesso modo ma dopo un round-trip di rete. Il codice interessato è
   `RemoteTursoConnection` in `neuron/src/neuron/db.py` e `neurag/db.py:667`.
   Col fix il latch lo gestisce comunque, ma va confermato che ora la query giri.
3. **Campo su Neuron dopo il merge.** I risultati di `_search_embeddings` adesso
   includono il seed, che prima era invisibile. È il comportamento corretto, ma
   è un cambio di comportamento reale sui flash e sui domini: vale un'occhiata a
   qualche turno vero prima di dare per scontato che sia meglio.
4. **Tenere allineati i due file.** `neuron/src/neuron/search.py` e `neurag/db.py`
   sono port a mano l'uno dell'altro, e questo bug è esattamente quel fallimento
   (già documentato in `neurag/db.py:703-707` per un caso precedente: la forma
   sopravvive, il dettaglio no). Il latch ha due nomi diversi per ragioni vere:
   - Neuron: `_vector_sql_ok` su `server.py` + helper `_permanent_vector_failure`
     in `search.py` (due call site: `_search_embeddings`, `_refine_domain`).
   - NeuRAG: attributo di classe `_vector_sql_ok` su `KnowledgeGraph`, check
     inline (un solo call site). Tenuto separato da `_vector_sql`, che significa
     "quale tier è aperto": spegnere quello manda `_ensure_turso` a cercare una
     wheel pyturso da reinstallare.

## Deciso e chiuso — non rifare

**L'idea di partenza** (dopo aver visto paperdb.app): intercettare gli eventi in
stile aspect e precalcolare i flash/stimoli nel DB invece che generarli sul
percorso MCP. **Misurato: non conviene.** Tre ragioni:
- Non esiste push verso il modello. Claude vede qualcosa solo quando chiama un
  tool: un trigger DB non "stimola" nessuno, il flash resta in coda finché
  `pre_turn` non lo legge. La consegna resta MCP comunque.
- Riparato il tier SQL, il guadagno residuo della materializzazione è ~15 ms su
  un turno che dura secondi. Lo 0,3%.
- Il rapporto write/read è 1:1 e il write è già il lato pesante: `_auto_link` fa
  4 `_search_embeddings` in scrittura contro 1 di `_context_window` in lettura.
  Spostare lavoro al write time lo mette dove ce n'è già quattro volte tanto.

Il grafo è cappato a 500 nodi (`MAX_NODES`), quindi lo scan O(N) non esploderà.

## Trappole d'ambiente (costano tempo se le riscopri)

- **NeuRAG non ha un venv proprio.** Ho usato `neuron/.venv/Scripts/python.exe`
  per la sua suite. Il venv di Gray Matter (`%LOCALAPPDATA%\GrayMatterEnvironment\
  graymatter\.venv`) non ha pytest.
- **Il server MCP vivo tiene lock su `base_knowledge.db` e sui graph store.**
  Qualsiasi benchmark che li apre misura la contesa, non il codice: i 306 ms per
  riapertura del seed venivano da lì. Copiare i DB nello scratchpad prima di
  misurare — è quello che distingue "1,5 s/turno" da "3,5 ms/turno".
- `neuron/.venv` importa neuron da `site-packages`, non dai sorgenti. Per
  misurare il codice modificato: `sys.path.insert(0, 'src')`.
- **Il corpus del bench NeuRAG è il repo stesso**: scrivere un CHANGELOG che
  nomina un identificatore ne cambia la ground truth e fa fallire
  `test_bench_set`. Ricalcolare da disco con la logica di `_ingested_files()`.

## Lasciato lì di proposito

`neurag/db.py:2270` — `where.replace(' AND node_id', ' AND node_id')` è un no-op,
sostituisce una stringa con se stessa. Residuo, innocuo, fuori dal giro.
