# Handoff — `feat/graph-and-chunk-ceiling`

Stato al **2026-07-30**, tre repo sullo stesso branch. Chi riprende parte da qui:
questo file dice cosa è stato fatto, cosa è verificato e cosa resta. Il perché di
ogni scelta sta nei commit e in `DESIGN-EVOLUTION.md` — qui non si duplica.

Sostituisce, per questa sessione, `feat_graph_and_chunk_ceiling__summary.md`
(quello copre P0/P2/P3).

## Test

| Suite | Esito |
|---|---|
| `pytest neurag/tests` | **262 passed**, 1 skipped |
| `pytest gray_matter/tests` | **433 passed**, 1 skipped |
| `pytest neuron/tests` | **312 passed** |

I tre vanno lanciati in **processi separati** (vedi `pytest.ini`): `neuron/tests/_mockdeps.py`
inietta fake in `sys.modules` e in un processo condiviso trapassano ai peer.

Lo skip in gray_matter è la controprova sulla finestra console, valida solo da una
console visibile. Quello in neurag è pre-esistente.

## Fasi

| # | Fase | Stato |
|---|---|---|
| P0 | Turn the graph on | ✅ (sessioni precedenti) |
| P1 | **Tag substrate** | ✅ questa sessione |
| P2 | Encoding / chunk ceiling | ✅ (precedenti) |
| P3 | Retrieval ibrido | ✅ (precedenti) |
| P4 | **Layers** | ✅ questa sessione |
| P5 | Brain — `origin`, Hebbian on confirm, spreading activation | ✅ questa sessione |
| P6 | Cross-tool (solo GM) | 🟡 **2 di 3** — vedi sotto |
| P7 | Installer + GUI | ⬜ parzialmente anticipata (vedi sotto) |

## Cosa è cambiato

### neurag — 10 commit

- **P1 — tag substrate** (`8f6d3ff`). Tabelle `tags` / `node_tags` / `chunk_tags`;
  nome normalizzato come join key; `uses` ricalcolato da `node_tags`, mai
  incrementato; migrazione idempotente dalla colonna JSON legacy con flag
  `meta.tags_migrated`; IDF suppression (`MAX_TAG_NODE_RATIO=0.5`,
  `MIN_TAG_NODE_FLOOR=50`); `build_tag_links` legge l'indice.
  Le colonne legacy `nodes.tags`/`nodes.triggers` restano come read path.
- **P4 — layers** (`540111b`). `nodes.layer`/`last_used` + `_ensure_columns`
  (prima migrazione di colonna del progetto); L1 working set persistito con TTL
  in query **e** in ore; parking per inattività × peso del link, dry run se non
  passi `--apply`; decay per emivita da `meta.decayed_at`; `recall` su tutti i
  layer. CLI: `park`, `unpark`, `decay`, `recall`, `query --deep`.
- **P5 — brain**. `origin` sui link + non-clobber in `upsert_link` (vedi la nota
  su `a05631a` in fondo); `confirm()` Hebbian sulla **conferma**, cooldown 2
  query, promozione a 3/8 come **pavimento** del peso; `spreading_activation` e
  `related_nodes`; MCP `knowledge_confirm` / `knowledge_related`; CLI `confirm` /
  `related`. Più: `tool_names` annunciata a GM ora **derivata** da `_tools()` —
  era scritta a mano e aveva perso `knowledge_neighbors` e `skill`.
- **Fix trovati e chiusi lungo la strada**:
  - `499ea74` un `;` dentro un commento SQL troncava lo schema in silenzio →
    `_split_sql` toglie i commenti prima di tagliare;
  - `f7d34e5` `search()` non aveva una chiave di punteggio stabile → `score` +
    `score_from` (`cosine|bm25|rrf|cross-encoder`) su ogni riga; anche il
    cross-encoder ora riscrive il punteggio in base a cui riordina;
  - `7217a4e` `search()`/`get_chunks()` restituivano il blob del vettore, che
    `--json` serializzava con `default=str`;
  - `d02e145` `status()` conta i `tags`, `health()` conta `dangling_tag_links`
    (le join table non hanno FK: cascade rotto su pyturso 0.6.1);
  - `a05631a` gli installer offrivano `"none" — lexical only` contro una hard
    dependency, **e quel ramo scriveva `embed_model=''`** = default multilingua:
    prometteva zero download e scaricava.

### gray_matter — 8 commit

- `8f78694` la controprova console salta se il runner non ha console propria.
- `3e5af77` / `09a128a` i comandi nuovi di NeuRAG documentati in `catalog.py`
  (bilingue, `what` + `when`).
- `6ce9f6a` parity: nessun installer può offrire di saltare l'embedder; i picker
  `.ps1` e `.sh` dello stesso progetto devono elencare gli stessi modelli.
- `15ff245` bridge: match su token interi + join per identità di tag.
- `8fde365` il contesto iniettato diventa un budget (vedi sezione sotto).
- `3df68a5` anche la memoria è regolabile (`memory_max_tokens`).
- `abdff11` `gray-matter promote`: consolidazione CLS, dry run di default.

### neuron — 1 commit, 3 file, +98

- `9824417` stesso splitter naive di neurag, difetto **latente** (gli schemi di
  Neuron non hanno commenti SQL). Fixato su entrambi i lati perché il marker
  keep-in-sync porta il prossimo a copiare da qui.

## Verifiche fatte a mano, oltre ai test

- **Migrazione P1 a scala**: vault da 2117 chunk retrocesso a pre-P1 e riaperto →
  triple `(nodo, tag, uses)` identiche, link `tag_overlap` identico, idempotente
  alla seconda riapertura.
- **Gradiente P4 end-to-end**: nodo con contenuto parcheggiato → `query` non lo
  trova, `recall` sì, `unpark` restituisce contenuto byte-identico.
- **Installer**: `sh -n` su `install.sh`, parser PowerShell su `install.ps1`,
  line ending invariati.
- Due test che **passavano sul codice rotto** sono stati corretti e ri-verificati
  reintroducendo il bug (vedi TODO-6 per la lezione generale).

## P6 — dove si è arrivati

La riga di fase chiede tre cose. Una è fatta, due no.

1. ✅ **I bridge fanno join su identità di tag** (`15ff245` GM, `b8f1d17` neurag).
   `bridges_for` matchava con `endpoint in topic or topic in endpoint`: `ast`
   matchava "fastembed install", `cache` matchava "cached". E siccome far emergere
   un bridge in una pulse lo **rinforza**, un bridge rumoroso si promuoveva da
   solo. Ora: run di token interi, più il join per identità sui nomi canonici dei
   tag, che NeuRAG manda a bordo della risposta `knowledge_neighbors` già
   richiesta dalla pulse (nessun round-trip in più, solo un riordino).
2. ✅ **Consolidazione CLS Neuron→NeuRAG** (§5.3) — `gray-matter promote`,
   dry run se non passi `--apply`. Soglie in `PROMOTE_RULES`: tre pavimenti in
   AND (salienza 5, trust 0.5, età 50 turni), il prodotto ordina il report. I tag
   viaggiano col concetto, quindi la promozione è un join e non un orfano.
   Da misurare su un grafo vissuto prima di fidarsi delle soglie.

3. ⬜ **Stimoli arricchiti con knowledge**. Oggi GM ha solo la *safety net* dello
   stimulus (`stimulus_safety_net`/`_gap`): rilancia lo stimolo di Neuron se tace,
   ma non gli attacca niente da NeuRAG. Lo stimolo esce come lo ha fatto Neuron.
   Attenzione: qualunque arricchimento qui **spende dal budget proattivo** — è la
   stessa superficie, non una in più.

## Il budget di iniezione

Aggiunto perché la domanda "se iniettiamo troppa knowledge non si prende molto
contesto?" aveva come risposta misurata **no, non lo stavamo gestendo**.

Caso peggiore misurato prima: **~6200 token** iniettati in una pulse, di cui
~5100 dai soli bridge, senza alcun tetto — e siccome mostrare un bridge lo
rinforza, un match di massa era anche una promozione di massa. Il join per
identità di tag aveva reso quel caso *più* facile da raggiungere.

Ora sono tre manopole, tutte nella card della GUI (`gray-matter config`):

| knob | default | cosa limita |
|---|---|---|
| `memory_max_tokens` | 400 | contesto di memoria (Neuron `get_context`) |
| `knowledge_top_n` | 5 | chunk di vault (~292 token misurati; 10 → ~689) |
| `proactive_budget_chars` | 800 | bridge + vicini + flash. `0` = niente proattivo |

Pulse tipica ora **~700 token**. Il budget si applica per blocco (mai un taglio a
metà frase), il flash ha priorità sui bridge perché è l'unico proattivo che non
si può ri-ottenere chiedendo, e il razionale di un bridge viene troncato a 80
caratteri nell'iniezione (lo store ne accetta 500 perché lì è documentazione).

## TODO

Ordinati per come li affronterei.

1. **Innestare lo spreading activation nel ranking di `search()`**, che è
   l'unico pezzo di P5 lasciato fuori di proposito: è un cambio misurabile al
   recupero e va dietro al **set di ~30 query del benchmark** (§7), non dietro a
   un argomento plausibile. Oggi l'attivazione è raggiungibile solo su richiesta
   esplicita (`related` / `knowledge_related`). Serve prima il query set, che non
   esiste ancora come artefatto versionato — è il vero blocco.
2. **Soglie di parking, con dati veri** (`DESIGN-EVOLUTION §8.1`). Misurato:
   sul repo `neurag/` **nessun nodo con chunk è parcheggiabile**, perché
   `max_link_weight=0.25` sta sotto ogni peso reale (0.458–1.0). Le soglie non
   sono ancora testate sul caso per cui esistono: un vault grande di documenti
   poco correlati. Serve la distribuzione di `MAX(weight)` per nodo su un vault
   personale, **non** su un altro repo.
3. **`chunk_tags` guadagna il suo spazio?** (`§8.4`) 9360 righe per 2117 chunk,
   ~4.4 per chunk, e **nessun consumatore**. Il design diceva di misurarlo a P3.
   O trova un lettore in P5/P6, o si parcheggia la tabella.
4. **12 chunk minuscoli** su markdown (heading senza corpo) segnalati da
   `health` come *serious*. Cosmetico lato chunker, pre-esistente, ma tiene
   `health()["ok"]` a `False` su ogni vault reale — quindi il segnale è inutile
   finché non si sistema.
5. **`_corrupt` è troppo silenzioso.** `_init_schema` inghiotte ogni errore di
   schema in `self._corrupt` e solo `status`/`health` lo raccontano. In questa
   sessione ha nascosto **due** errori di schema; il secondo l'ho trovato solo
   guidando la CLI. Almeno: `search`/`park`/`query` dovrebbero dire "vault
   corrotto, lancia `neurag doctor`" invece di esplodere con un traceback pyturso.
6. **Trappola da ricordare nei test**: `close()` sul tier Turso **tiene viva la
   connessione in cache** di proposito. Un test che modifica il DB da fuori e poi
   riapre riceve un handle con lo schema vecchio e asserisce su una vista
   stantia — passa qualunque cosa faccia il codice. Serve
   `neurag.db._turso_conn_cache.clear()` per simulare un processo nuovo.
7. **P7 già intaccata**: i comandi nuovi sono nel catalogo ma i pannelli GUI
   per tag e link health non esistono. Nessun knob nuovo è stato introdotto, per
   scelta, quindi i 6 installer non hanno debito.
8. **`node_links` è direzionale** e `build_crossref_links` crea davvero le due
   righe: `(A,B)` e `(B,A)` sono chiavi distinte. È semanticamente corretto —
   "A parla di B" non è "B parla di A" — ma vuol dire che una coppia contribuisce
   **due archi** allo spreading activation, con pesi diversi. Comportamento
   fissato in un test (`test_a_directional_pair_is_reinforced_in_each_direction_on_its_own`),
   non un bug; da rivedere solo se il doppio arco distorce il ranking quando
   l'attivazione entrerà in `search()` (TODO-1).

## Nota sul commit `a05631a`

Quel commit ha per messaggio il fix degli installer ma contiene anche 41 righe in
`db.py` — la colonna `origin`, `co_activation_count`, `last_coactivation`, il
non-clobber in `upsert_link` e `rebuild_links` che cancella solo gli `auto`, cioè
il primo pezzo di P5. Sono arrivate nel working tree mentre si lavorava sugli
installer e un `git add -A` le ha inglobate. Il codice è corretto (verificato e
ora coperto da `tests/test_hebbian.py`), ma il messaggio di quel commit non lo
descrive: chi cerca l'origine di `origin` in `git log` non lo trova dove
dovrebbe. Da qui in avanti: `git status` prima di ogni `add`.

## Da sapere sull'ambiente

- I tre package **non erano installati** per `C:\Python314`: 6 delle 7 failure
  iniziali erano solo quello. `pip install -e ./neuron ./gray_matter ./neurag --no-deps`.
- Il vault NeuRAG vivo (`~/.local/share/neurag/knowledge.db`) è **vuoto** (solo la
  root): le verifiche a scala girano su vault di scratch, non su quello.
- Con GM attivo, `neurag <cmd>` viene instradato al worker persistente di GM
  (`_run_via_gm`, single-writer lock): **`NEURAG_HOME` viene ignorato**. Per
  pilotare un vault alternativo si passa dal percorso locale.
