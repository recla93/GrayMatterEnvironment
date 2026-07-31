# Handoff — `feat/graph-and-chunk-ceiling`

Stato al **2026-07-30**, tre repo sullo stesso branch. Chi riprende parte da qui:
questo file dice cosa è stato fatto, cosa è verificato e cosa resta. Il perché di
ogni scelta sta nei commit e in `DESIGN-EVOLUTION.md` — qui non si duplica.

Sostituisce, per questa sessione, `feat_graph_and_chunk_ceiling__summary.md`
(quello copre P0/P2/P3).

## Test

| Suite | Esito |
|---|---|
| `pytest neurag/tests` | **347 passed**, 1 skipped |
| `pytest gray_matter/tests` | **433 passed**, 1 skipped |
| `pytest neuron/tests` | **319 passed** |

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
   esplicita (`related` / `knowledge_related`).
   ~~Serve prima il query set, che non esiste ancora come artefatto
   versionato — è il vero blocco.~~ **Il blocco è tolto (2026-07-30):**
   `bench/queries.json` (30 query, IT+EN, metà `identifier` e metà `concept`),
   runner `bench/run.py`, baseline in `bench/results/P5.json`. Ora il cambio si
   misura rilanciando prima e dopo, invece di discuterlo.

   | | recall@5 | mrr@10 |
   |---|---:|---:|
   | tutte (30) | 0.967 | 0.823 |
   | identifier (15) | 1.000 | 0.867 |
   | concept (15) | 0.933 | 0.780 |
   | en (23) | 0.957 | 0.802 |
   | it (7) | 1.000 | 0.893 |

   Da leggere **per kind, mai il totale**: è il totale che nascose la scoperta
   di P3 (il vettoriale puro era a posto sulle parafrasi e falliva in blocco la
   classe degli identificatori). Su questo corpus recall@5 è quasi saturo,
   quindi la metrica con margine — e quella che si muove per prima su una
   regressione — è **MRR@10**.

   **Onestà sul numero.** La v1 del set dava 0.800 con sei miss. Quattro erano
   ground truth scritta stretta (elencava il modulo che implementa e ignorava il
   documento che risponde alla stessa domanda), non fallimenti del recupero, e
   la correzione è stata fatta **dopo** aver visto i risultati — cioè il modo
   esatto in cui un benchmark diventa un ornamento. Dichiarata in `queries.json`
   → `history`, e resa non ripetibile: la metà `identifier` è **ricalcolata da
   disco** da `tests/test_bench_set.py` (expect = ogni file ingerito che
   contiene la stringa, quindi non è negoziabile), la metà `concept` è
   **congelata** perché "risponde alla domanda?" è un giudizio e non si
   meccanizza. Il salto 0.800 → 0.967 misura la mia scrittura, non il retriever.

   **L'unica miss vera è q22**, "which editors and assistants can this be
   plugged into" → `clients.py`: la matrice client è un dict di path di
   configurazione e da nessuna parte c'è la prosa "questi sono gli editor
   supportati", quindi nessuno dei due retriever ci arriva da linguaggio
   naturale. Stessa forma della scoperta di P3 sugli installer non indicizzabili:
   non è il ranking, è che la risposta non esiste come testo.

   **Misurato, ha perso, ed è stato RIMOSSO.** Prima era rimasto spento di
   default; poi la domanda giusta — "quali pezzi sono di troppo?" — ha dato la
   risposta ovvia: un ramo che nessuno esegue sul percorso caldo del recupero è
   manutenzione che la misura non paga. Via `spread`, `_fuse_activation`,
   `SPREAD_SEEDS`/`SPREAD_HOPS` e il macchinario `--ab` del bench.
   `related` / `knowledge_related` restano: è lì che l'attivazione serve
   davvero, cioè quando qualcuno la chiede. Qui sotto resta il **come era
   fatto**, che è ciò che serve per rifarlo se un giorno le precondizioni
   cambiano.
   L'attivazione entrava come **terza classifica** nella fusione RRF: seed = i nodi
   dei migliori 3 chunk, un salto, e il posto di un nodo nell'ordine di
   attivazione vale `1/(K+rank)` per ogni suo chunk candidato. Contributo per
   **nodo** e non per chunk, altrimenti un nodo con 40 chunk nel pool si prende
   40 slot. Riordina soltanto: §5.5 vieta l'attivazione come *generatore*, e il
   pool è largo (4× top_n), quindi il completamento avviene dentro un insieme
   già pertinente.

   | | recall@5 | mrr@10 |
   |---|---:|---:|
   | senza attivazione (spedito) | 0.967 | 0.823 |
   | con attivazione | 0.867 | 0.606 |

   15 query si sono mosse, **13 in giù**. Due ragioni, entrambe proprietà del
   corpus e non dell'idea:
   * **il grafo non porta ancora uso** — tutti gli 80 link sono `origin='auto'`,
     zero conferme. §5.1 argomenta l'attivazione sui pesi **hebbiani**; spargere
     su un grafo solo derivato sparge su struttura che i due retriever hanno già
     letto nel testo;
   * **la distribuzione dei nodi è degenere** — il godnode tiene il 70% dei
     chunk e `tests` un altro 22%, quindi i seed sono quasi sempre gli stessi due
     nodi e il voto è un prior quasi costante che combatte un segnale che dipende
     dalla query. `ingest.py` e `README.md` sono scesi da 3–4 a 10, dietro ai file
     di test che il godnode collega.

   Una volta però ha fatto esattamente quello che promette, e va registrato
   perché è l'unico argomento per riprovarci: q22 non ha nessuna rotta lessicale
   o semantica verso `clients.py` ed è l'unica miss permanente del set —
   l'attivazione l'ha portata a rank 8 dal nulla.
   Chi riprova verifichi **prima** le due precondizioni qui sopra (link davvero
   confermati, distribuzione dei nodi che non siano due secchi) e misuri sul
   set: senza quelle, non è un ri-test, è un altro lancio di dadi. E si misuri
   con due esecuzioni del bench su due stati del codice, non reintroducendo un
   flag — un interruttore permanente per un esperimento è il costo che questa
   rimozione ha tolto.

   Effetto collaterale: **TODO-8 si chiude.** Il doppio arco
   direzionale distorce il ranking solo se l'attivazione entra in `search()`, e
   non ci entra. Torna aperto insieme al ri-test.

   Due dettagli che rendono il numero riproducibile: il corpus è il repo stesso
   (viaggia col commit), e `bench/` viene **tolto dal vault dopo l'ingest** —
   `.json` è indicizzabile, quindi `queries.json` sarebbe finito in un chunk con
   ogni domanda accanto al file che la risponde. La ricerca gira con
   `touch=False`: rispondere alza la salienza dei tag, la salienza alimenta lo
   spreading activation, e un benchmark che scalda il vault che misura smette di
   essere un corpus fisso dopo il primo giro — cosa che riguarda proprio questo
   TODO.
2. **Soglie di parking, con dati veri** (`DESIGN-EVOLUTION §8.1`). Misurato:
   sul repo `neurag/` **nessun nodo con chunk è parcheggiabile**, perché
   `max_link_weight=0.25` sta sotto ogni peso reale (0.458–1.0). Le soglie non
   sono ancora testate sul caso per cui esistono: un vault grande di documenti
   poco correlati. Serve la distribuzione di `MAX(weight)` per nodo su un vault
   personale, **non** su un altro repo.
3. ~~**`chunk_tags` guadagna il suo spazio?**~~ **CHIUSO (2026-07-30): no,
   parcheggiata.** Misurato: 9360 righe per 2117 chunk, ~4.4 per chunk, e
   **nessun lettore in nessuno dei tre repo** — il linking legge `node_tags`,
   l'IDF (`tags.uses`) conta `node_tags`, e il join per tag di Gray Matter passa
   da `node_tag_names`, che è ancora `node_tags`. Costo di scrittura e di disco
   per una join che nessuno faceva. `add_chunk` non la scrive più.
   **Parcheggiata, non cancellata** (I5): tabella e righe esistenti restano, i
   punti di delete continuano a ripulire quelle legacy e `health()` continua a
   sorvegliarle. Il dato è derivato dai tag del chunker, quindi un futuro
   lettore la ripopola con un re-ingest — lì dentro non c'è nessuna fonte di
   verità.
   **Valutato e scartato: cancellare la tabella.** Sarebbe più pulito da
   guardare, ma richiede una migrazione che deve girare su ogni vault esistente
   — rischio reale su tutti, per togliere una perplessità estetica su nessuno.
   Una tabella senza scrittore non costa niente a runtime. La confusione si
   risolve con un commento, che c'è; la migrazione no.
4. ~~**12 chunk minuscoli**~~ **CHIUSO (2026-07-30).** Non erano cosmetici e non
   erano del markdown: li creava `_split_text`. Il pack greedy chiudeva subito
   dopo l'heading ogni volta che il paragrafo seguente valeva da solo un budget
   intero, quindi `## 7. Verification` diventava un chunk che annuncia un titolo
   e non dice niente. Ora un buffer sotto `MIN_CHUNK_CHARS` viene **portato
   avanti** dentro il candidato sovradimensionato, che la ricorsione ri-taglia a
   un separatore più fine: l'heading viaggia col testo che introduce.
   Portato avanti e non scartato perché un runt è solo *probabilmente* un
   heading, e la volta che è una frase vera scartarlo è perdita silenziosa di
   dati. Verificato sull'albero: 13 runt → **0**, zero chunk fuori budget, e
   `health()["ok"]` è **True** su un vault reale per la prima volta.
   Effetto collaterale misurato: MRR@10 0.809 → **0.823** (concept 0.752 →
   0.780), perché quei chunk occupavano posizioni in classifica.
5. ~~**`_corrupt` è troppo silenzioso.**~~ **CHIUSO (2026-07-30).** Ingoiare gli
   errori di schema in `self._corrupt` era la scelta giusta — serve a far girare
   le diagnostiche invece di far morire tutta la CLI — ed era fatta a metà:
   tutto il resto proseguiva su una connessione senza tabelle e usciva con un
   traceback pyturso grezzo, che nomina il sintomo e nasconde la causa.
   Ora, se il vault non si apre, `self._conn` diventa una `_CorruptConnection`
   che alza `VaultCorrupt` con causa **e** comando di recupero. **Un posto solo**:
   non esiste una funzione da cui passano tutti i metodi, ma esiste un oggetto,
   quindi anche un metodo aggiunto l'anno prossimo è coperto senza che nessuno
   si ricordi di guardarlo. `status`/`health`/`doctor` tornano prima di toccare
   `_conn`, ed è questo che li lascia capaci di raccontarlo; `repair` gira prima
   ancora che il DB venga aperto. CLI e MCP la traducono in un messaggio invece
   che in un crash (`cli.main`, `server.call_tool`).
   Stesso difetto trovato e chiuso **anche in Neuron**, che è il gemello
   keep-in-sync e non aveva mai ricevuto il fix 1.1.1: lì la forma è diversa
   (`corrupt_store_hint` classifica in `db.py`, `server.call_tool` la antepone
   al traceback) perché un `Graph` viene caricato e salvato da molti punti,
   mentre NeuRAG possiede una connessione per tutta la sua vita.
5b. **Il tier sqlite3 non esisteva** (trovato mentre si verificava il punto 5,
   lanciando `neurag status` sul vault vero). `sqlite3.connect` non era chiamato
   da nessuna parte in `db.py`, benché I4, `_ensure_turso`, `status`, `doctor` e
   il ramo di coseno in Python lo descrivano tutti come il tier di degrado. Il
   ramo lasciava `_conn = None` → `_init_schema` falliva su `NoneType` → vault
   **CORROTTO**. Il vault vivo risultava corrotto solo perché il server MCP ne
   teneva il lock pyturso (esclusivo): sqlite3 apre e legge lo stesso file senza
   problemi. Ora `_connect` degrada davvero, `_open_local_turso` riporta il
   motivo, e `open_failure_message()` separa **lock** da **corruzione** — perché
   la cura della seconda è `--wipe-knowledge` e un vault sano ma occupato era a
   un messaggio dall'essere cancellato su consiglio.
   Lezione, la stessa del punto 6: `test_neurag_lock.py` **asseriva il bug**,
   aspettandosi `Turso (pending)` come esito corretto di un lock.
   **Seguito — il fallback aveva tolto una barriera.** Degradando, un secondo
   processo poteva anche **scrivere**: il lock esclusivo di pyturso stava
   facendo rispettare per caso la regola del single-writer, e due motori con due
   WAL diversi sullo stesso file sono corruzione che aspetta. Verificato: il
   processo B scriveva davvero. Ora il tier in prestito (**solo** quando la
   causa è un lock) è `_ReadOnlyConnection`: legge, e su una scrittura alza
   indirizzando al proprietario, dove `_run_via_gm` manda già le scritture.
   Senza pyturso del tutto — cioè NeuRAG standalone (I2) — sqlite3 resta
   normale e scrivibile: quello non è un vault in prestito, è l'unico vault.
   E non si ritenta più un lock: apertura da **2.86s a 1.01s** sul vault vivo,
   contro 1.13s a vault libero.
5c. **Il reranker: lasciato spento, con il criterio per riaccenderlo.** È l'unico
   pezzo opzionale mai misurato — spento di default, tre knob, e un modello da
   scaricare. Non serve scaricarlo per decidere: **un reranker riordina, non
   trova**, quindi il suo tetto è la recall del pool che riceve.

   > **`recall@50` − `recall@5` È il margine del reranker.** Sono le query la
   > cui risposta è già stata pescata ma sta sotto il taglio: le uniche che un
   > riordino può salvare. Divario ≈ 0 → non può fare niente, per definizione.

   Misurato su questo corpus: recall@5 **0.967**, recall@50 **1.000**. Margine =
   **una query** (q22, `clients.py` entra nel pool ma resta sotto il quinto
   posto). Contro 1.11 GB su disco e 50 passaggi di cross-encoder a ogni
   ricerca, pagati per sempre. Quindi no — ma su un vault personale, dove
   recall@5 non sarà satura, quel divario è il segnale da guardare per primo.

   Vincolo che restringe la scelta a uno: l'unico reranker **multilingua**
   disponibile è `jinaai/jina-reranker-v2-base-multilingual` (1.11 GB). Tutti i
   leggeri (0.08–0.15 GB) sono solo inglese, e su un vault IT+EN rivaluterebbero
   chunk italiani con un modello che non li capisce — peggio del non riordinare.
   Non è quindi un problema di "trovarne uno più piccolo".
6. **Trappola da ricordare nei test**: `close()` sul tier Turso **tiene viva la
   connessione in cache** di proposito. Un test che modifica il DB da fuori e poi
   riapre riceve un handle con lo schema vecchio e asserisce su una vista
   stantia — passa qualunque cosa faccia il codice. Serve
   `neurag.db._turso_conn_cache.clear()` per simulare un processo nuovo.
7. **P7 già intaccata**: i comandi nuovi sono nel catalogo ma i pannelli GUI
   per tag e link health non esistono. Nessun knob nuovo è stato introdotto, per
   scelta, quindi i 6 installer non hanno debito.
8. ~~**`node_links` è direzionale**~~ — **non attivo (2026-07-30).** La condizione
   che apriva questo punto era "quando l'attivazione entrerà in `search()`"
   (TODO-1), e l'attivazione è stata misurata e lasciata spenta. Resta vero e
   resta fissato in un test; torna in gioco solo col ri-test di TODO-1.
   Il testo originale, che vale ancora:
   `node_links` è direzionale e `build_crossref_links` crea davvero le due
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
- **Un install editable aggiorna i file, non i processi accesi** — e questo
  cambia cosa vedi nel control center. `status`, `health`, `tree` e `query`
  passano via IPC al daemon GM; `doctor` no, gira in locale. Dopo una modifica a
  `neurag/db.py` i primi quattro rispondono ancora col **codice vecchio** finché
  il worker non viene riavviato, mentre `doctor` mostra subito quello nuovo.
  Verificato guidando la GUI a mano: `doctor` diceva
  `SQLite (read-only: owned by another process)` mentre `status` insisteva su
  `Turso (pending)` + `corrupt: true`. Nessuno dei due mentiva: erano due
  versioni del codice. **Riavviare il worker GM fa parte del verificare la GUI**
  (I7), altrimenti si valida un fix guardando il processo che non ce l'ha.
- Sul vault vivo il lock pyturso è tenuto da un **worker GM**
  (`gray_matter._worker neurag.server`). Il file
  `~/.local/share/neurag/neurag_server.pid` è **stale** — contiene il pid di un
  processo morto — quindi non fidarsi di quello per capire chi ha il lock: si
  guarda la lista dei processi. (Ci sono cascato: avevo scritto qui che il lock
  era di un server standalone, sulla sola fede del pid file.)
- **Il runtime NON è questo albero.** I worker e la GUI girano da
  `%LOCALAPPDATA%\gray-matter\.venv`, dove `neurag`/`neuron` sono **copie
  installate** in `site-packages`, non editable verso `D:\`. `neuron/.venv` —
  quello con cui si lanciano i test — è invece editable e vede subito le
  modifiche. Conseguenza: una correzione può essere verde su tutta la suite e
  **non essere nel prodotto**, e nessun riavvio la porta lì. Serve un
  reinstall nel venv di GM. Controprova rapida, da una cwd *neutra* (la cwd
  entra in `sys.path` e falsa la risposta):
  `…\gray-matter\.venv\Scripts\python.exe -c "import neurag; print(neurag.__file__)"`
