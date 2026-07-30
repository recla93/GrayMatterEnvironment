# Handoff — `feat/graph-and-chunk-ceiling`

Stato al **2026-07-30**, tre repo sullo stesso branch. Chi riprende parte da qui:
questo file dice cosa è stato fatto, cosa è verificato e cosa resta. Il perché di
ogni scelta sta nei commit e in `DESIGN-EVOLUTION.md` — qui non si duplica.

Sostituisce, per questa sessione, `feat_graph_and_chunk_ceiling__summary.md`
(quello copre P0/P2/P3).

## Test

| Suite | Esito |
|---|---|
| `pytest neurag/tests` | **239 passed**, 1 skipped |
| `pytest gray_matter/tests` | **383 passed**, 1 skipped |
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
| P5 | Brain — `origin`, Hebbian on confirm, spreading activation | ⬜ **prossima** |
| P6 | Cross-tool (solo GM) | ⬜ |
| P7 | Installer + GUI | ⬜ parzialmente anticipata (vedi sotto) |

## Cosa è cambiato

### neurag — 8 commit, 12 file, +1688/-100

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

### gray_matter — 3 commit, 3 file, +105

- `3e5af77` i 4 comandi nuovi documentati in `catalog.py` (bilingue, `what` + `when`).
- `6ce9f6a` parity: nessun installer può offrire di saltare l'embedder; i picker
  `.ps1` e `.sh` dello stesso progetto devono elencare gli stessi modelli.
- `8f78694` la controprova console salta se il runner non ha console propria.

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

## TODO

Ordinati per come li affronterei.

1. **P5 — Brain.** Colonna `origin` sui link, Hebbian on confirm, spreading
   activation. Gate: *i link curati sopravvivono al re-ingest* — oggi
   `rebuild_links()` fa `DELETE FROM node_links` e ricostruisce, quindi qualunque
   link curato a mano viene perso. È il primo pezzo da sistemare.
   `tags.salience` ha già uno scrittore (`touch_nodes`) e un decay, quindi la
   metà Hebbian ha dove appoggiarsi.
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
7. **P7 già intaccata**: i 4 comandi nuovi sono nel catalogo ma i pannelli GUI
   per tag e link health non esistono. Nessun knob nuovo è stato introdotto, per
   scelta, quindi i 6 installer non hanno debito.

## Da sapere sull'ambiente

- I tre package **non erano installati** per `C:\Python314`: 6 delle 7 failure
  iniziali erano solo quello. `pip install -e ./neuron ./gray_matter ./neurag --no-deps`.
- Il vault NeuRAG vivo (`~/.local/share/neurag/knowledge.db`) è **vuoto** (solo la
  root): le verifiche a scala girano su vault di scratch, non su quello.
- Con GM attivo, `neurag <cmd>` viene instradato al worker persistente di GM
  (`_run_via_gm`, single-writer lock): **`NEURAG_HOME` viene ignorato**. Per
  pilotare un vault alternativo si passa dal percorso locale.
