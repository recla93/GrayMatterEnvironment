# Changelog — NeuRAG

## Unreleased
- **Il benchmark di recupero esiste come artefatto** (`bench/`, DESIGN-EVOLUTION
  §7). Prima i numeri delle fasi (recall@5 67% → 94%) venivano da un set di
  query che viveva dentro una sessione: riproducibile da nessuno, confrontabile
  con niente — ed era il blocco dichiarato per innestare lo spreading activation
  nel ranking.
  - `bench/queries.json`: 30 query IT+EN, metà **identifier** (stringhe esatte:
    la classe su cui il vettoriale puro falliva) e metà **concept** (parafrasi
    senza sovrapposizione lessicale con la risposta). `bench/run.py` riporta
    recall@5 e MRR@10 **per kind e per lingua**: è il totale che aveva nascosto
    la scoperta di P3, e un numero solo non può regredire nel modo che conta.
  - Il corpus è il repo stesso, l'unico che viaggia col commit. `bench/` viene
    **tolto dal vault dopo l'ingest**: `.json` è indicizzabile, quindi
    `queries.json` sarebbe finito in un chunk con ogni domanda accanto al file
    che la risponde. Tolto il nodo, non aggiunta una regola globale su "bench"
    che seguirebbe gli utenti in progetti dove quella cartella è conoscenza.
  - Le query girano con `touch=False`: rispondere alza la salienza dei tag, la
    salienza alimenta lo spreading activation, e un benchmark che scalda il
    vault che misura smette di essere un corpus fisso dopo il primo giro.
  - **Onestà sulla ground truth.** Il primo giro dava 0.800; quattro delle sei
    miss erano ground truth scritta stretta (elencava il modulo che implementa e
    ignorava il documento che risponde), non fallimenti del recupero. La
    correzione è stata fatta *dopo* aver visto i risultati — cioè il modo esatto
    in cui un benchmark diventa un ornamento — quindi è dichiarata in
    `queries.json` → `history` e resa non ripetibile: la metà `identifier` è
    **ricalcolata da disco** da `tests/test_bench_set.py` (expect = ogni file
    ingerito che contiene la stringa: non è negoziabile), la metà `concept` è
    **congelata**, perché "risponde alla domanda?" è un giudizio.
- **Un vault preso in prestito legge e non scrive.** Il fallback sqlite3 qui
  sotto aveva un effetto collaterale che non avevo previsto: il lock esclusivo
  di pyturso stava facendo rispettare **per caso** la regola del single-writer,
  e degradare l'ha tolta di mezzo — due motori con due implementazioni diverse
  del WAL potevano scrivere lo stesso file insieme. Misurato: un secondo
  processo scriveva davvero mentre il primo teneva il lock.
  Ora, **solo nel caso lockato**, la connessione è avvolta in
  `_ReadOnlyConnection`: le letture passano, una scrittura alza `VaultUnavailable`
  e indirizza al processo proprietario, dove `_run_via_gm` già manda le
  scritture. Le letture erano il guadagno, le scritture erano il bug.
  La distinzione è quella che serve: una macchina **senza** pyturso ottiene un
  sqlite3 normale e scrivibile — quello è NeuRAG standalone (I2), non un vault
  in prestito. `_init_schema` viene saltato sul tier in prestito: lo schema lo
  mantiene chi possiede il file, e senza quel salto un `CREATE TABLE IF NOT
  EXISTS` avrebbe colpito la guardia e rimarcato corrotto un vault leggibile.
- **Non si ritenta più un lock.** I retry esistono per una corsa transitoria
  (cartella non ancora pronta); un lock non è transitorio, pyturso lo tiene per
  tutta la vita del processo proprietario. Ritentare era spreco garantito
  proprio nel caso più frequente — ogni comando CLI col server MCP acceso.
  Misurato sul vault vivo: apertura da **2.86s a 1.01s**, contro 1.13s a vault
  libero. Cioè: il percorso lockato non costa più niente in più di quello
  normale. I tentativi registrati passano da 3 a 1.
- **Lo spreading activation nel ranking: misurato, e RIMOSSO.** Era rimasto
  spento di default; un ramo inutilizzato sul percorso caldo del recupero è un
  costo di manutenzione che la misura non giustifica, quindi è stato tolto —
  insieme a `spread`, `_fuse_activation`, `SPREAD_SEEDS`/`SPREAD_HOPS` e al
  macchinario `--ab`/`_moved`/`report_ab` del bench che serviva solo a
  confrontarlo. I numeri e il perché restano qui sotto: è la documentazione a
  conservare l'esperimento, non il codice.
  `related` / `knowledge_related` restano intatti — è lì che l'attivazione fa
  quello che sa fare, cioè rispondere a chi la chiede esplicitamente.
  Com'era fatto, per chi volesse rifarlo: entrava come
  **terza classifica** nella fusione RRF — seed = i nodi dei migliori 3 chunk,
  un salto, e il posto di un nodo nell'ordine di attivazione vale `1/(K+rank)`
  per ogni suo chunk candidato. Fuso come classifica e non sommato come
  punteggio, quindi non serve calibrare niente e nessuna gamba può soverchiare
  le altre. Contributo per **nodo**, non per chunk: un nodo con 40 chunk nel
  pool non deve prendersi 40 slot. Riordina soltanto — §5.5 vieta l'attivazione
  come *generatore*.
  Risultato: recall@5 0.967 → 0.867, MRR@10 0.823 → 0.606, 15 query mosse di cui
  **13 in giù**. Due ragioni, entrambe del corpus: ogni link è `origin='auto'`
  (zero conferme, mentre §5.1 argomenta l'attivazione sui pesi *hebbiani*), e la
  distribuzione dei nodi è degenere (il godnode tiene il 70% dei chunk, `tests`
  un altro 22%), quindi il voto è un prior quasi costante contro un segnale che
  dipende dalla query.
  Una cosa l'ha fatta, e va registrata perché è l'unico argomento per
  riprovarci: q22 non ha nessuna rotta lessicale o semantica verso
  `clients.py`, ed è l'unica miss permanente del set — l'attivazione l'ha
  portata a rank 8 dal nulla. Se un giorno si riprova, le precondizioni da
  verificare **prima** sono quelle due qui sopra: link davvero confermati, e
  una distribuzione dei nodi che non siano due secchi. Altrimenti non è un
  ri-test, è un altro lancio di dadi.
- **Il tier sqlite3 ora esiste davvero.** I4 lo chiama "a degraded fallback",
  `_ensure_turso` stampa "degrado a sqlite3", `status`/`doctor` lo riportano e
  `_vector_candidates` ha un ramo di coseno in Python commentato "only the
  sqlite3 tier lands here" — e `sqlite3.connect` non veniva chiamato **da
  nessuna parte** in `db.py`. Il ramo lasciava `_conn = None`, quindi
  `_init_schema` falliva con `'NoneType' object has no attribute 'execute'`,
  l'errore veniva catturato, e il vault risultava **CORROTTO**.
  Ecco come un vault sano veniva diagnosticato come rotto: il server MCP tiene
  un lock pyturso (che è esclusivo), un secondo processo non riusciva ad aprire
  quel tier, e invece di degradare dichiarava il file guasto. sqlite3 apre e
  legge lo stesso identico file senza lamentarsi — misurato sul vault vivo
  mentre il server lo teneva, non supposto.
  Ora `_connect` apre sqlite3 quando pyturso non è utilizzabile, e
  `_open_local_turso` raccoglie il **motivo** invece di ingoiarlo, così `doctor`
  dice "lock" e non "open locale fallito".
  **Lock e corruzione sono problemi opposti** e avevano lo stesso messaggio: il
  primo si risolve da solo quando l'altro processo molla, il secondo solo
  sostituendo il file — e la cura del secondo è `--wipe-knowledge`. Un vault
  sano ma occupato era a un messaggio di distanza dall'essere cancellato su
  consiglio. `open_failure_message()` li distingue, e lo usano sia la guardia
  sia `status()`, così diagnosi ed errore non possono contraddirsi.
  Un test asseriva il bug (`test_neurag_lock.py` si aspettava `Turso (pending)`,
  cioè il processo B senza connessione, come esito corretto di un lock): ora
  asserisce la proprietà più forte — B degrada di un tier e continua a leggere.
  **Neuron non ha mai avuto questo bug**: `_open_local_engine` finisce con
  `return _sqlite3.connect(path)`, la sua "L2 guard". Questo file è la porta
  keep-in-sync di quello e ha perso esattamente l'ultima riga — il modo tipico
  in cui si rompe una porta fatta a mano: la forma sopravvive, la guardia no, e
  i commenti continuano a descrivere l'originale.
- **Un vault corrotto ora lo dice, su ogni superficie.** `_init_schema` ingoia
  gli errori di schema in `self._corrupt` perché le diagnostiche possano girare
  e raccontarlo invece di far morire tutta la CLI — giusto, e fatto a metà:
  `search`, `park` e `query` proseguivano su una connessione senza tabelle e
  uscivano con un "no such table" di pyturso, che nomina il sintomo e nasconde
  la causa. In una sessione quel silenzio ha nascosto **due** errori di schema.
  Ora la connessione viene sostituita da una `_CorruptConnection` che alza
  `VaultCorrupt` con causa e comando di recupero. **Un punto solo**: non c'è una
  funzione da cui passano tutti i metodi, ma c'è un oggetto — quindi un metodo
  aggiunto fra un anno è coperto senza che nessuno se lo ricordi.
  `status`/`health`/`doctor` tornano prima di toccare `_conn` (è ciò che li
  lascia capaci di riportarlo) e `repair` gira prima che il DB si apra.
  `cli.main` e `server.call_tool` la traducono in un messaggio, non in un crash.
- **Un heading non diventa più un chunk da solo.** `_split_text` chiudeva il
  pack greedy subito dopo l'heading ogni volta che il paragrafo seguente valeva
  da solo un budget intero: `## 7. Verification` diventava un chunk che annuncia
  un titolo e non dice niente. Tredici su questo repo, e `health()` li conta
  come *serious* — quindi `ok` era **False** su ogni vault reale e l'intero
  segnale era illeggibile.
  Un buffer sotto `MIN_CHUNK_CHARS` viene ora portato avanti nel candidato
  sovradimensionato, che la ricorsione ri-taglia a un separatore più fine:
  l'heading viaggia col testo che introduce. Portato avanti e non scartato
  perché un runt è solo *probabilmente* un heading, e la volta che è una frase
  vera scartarlo è perdita silenziosa di dati. 13 → **0** runt, zero chunk fuori
  budget, `health()["ok"]` **True** per la prima volta su un vault reale — e
  MRR@10 0.809 → **0.823**, perché quei chunk occupavano posizioni in classifica.
- **`chunk_tags` è parcheggiata** (§8.4 chiedeva di misurarlo a P3 e non fu
  fatto). Misurato: 9360 righe per 2117 chunk e **nessun lettore** in nessuno
  dei tre repo — il linking legge `node_tags`, l'IDF conta `node_tags`, e il
  join per tag di Gray Matter passa da `node_tag_names`, che è ancora
  `node_tags`. `add_chunk` non la scrive più. Parcheggiata e non cancellata
  (I5): tabella e righe legacy restano, i delete continuano a ripulirle e
  `health()` continua a sorvegliarle; il dato è derivato dai tag del chunker,
  quindi un lettore futuro la ripopola con un re-ingest.
- **Il grafo impara, e quello che impara sopravvive (P5, §5.1).**
  - `node_links.origin` separa i link derivati da quelli appresi:
    `rebuild_links()` cancella solo `origin='auto'`, e `upsert_link` rifiuta di
    far sovrascrivere una riga appresa da una derivata (cancellare solo gli auto
    non bastava: i builder ri-upsertano ogni coppia al rientro).
  - **`neurag confirm A B`** (e `knowledge_confirm`): rinforzo Hebbian sulla
    **conferma**, non sul co-recupero. Il recupero costa poco e sbaglia spesso:
    rinforzarlo insegnerebbe al grafo quello che il ranking già crede. Cooldown
    di 2 query per link, promozione a 3 e 8 co-attivazioni.
    Le soglie sono un **pavimento**, non un'assegnazione: i pesi di NeuRAG sono
    float e un overlap può già valere 1.0, quindi assegnare il valore di soglia
    **declasserebbe** un link forte perché è stato confermato. Un link
    rinforzato smette di essere `auto`, altrimenti l'ingest successivo se lo
    riprende. Rinforza solo link che esistono già: crearli resta ai builder,
    come in Neuron.
  - **`neurag related <nodo>`** (e `knowledge_related`): spreading activation a
    k salti, ordinata per forza accumulata invece che per numero di salti.
    Contributo per salto = `attivazione x peso x fattore_salienza x decay`; la
    salienza sta sui tag (§4 l'ha messa lì di proposito), quindi il fattore hub
    di un nodo è la media dei suoi tag. Solo grafo, nessun embedding. I nodi
    parcheggiati restano fuori se non passi `--deep`: un'espansione non deve
    disfare in silenzio il parking di P4.
    **Non** è innestata nel ranking di `search()`: quello è un cambio misurabile
    al recupero e va dietro al set di query del benchmark, non dietro a un
    argomento plausibile.
- **Ogni tool servito è annunciato al gateway.** `main()` passava a Gray Matter
  una lista `tool_names` scritta a mano mentre `list_tools()` costruiva quella
  vera, e aveva divergito **due volte**: `knowledge_neighbors` e `skill` erano
  serviti e dispatchati da release senza che il gateway sapesse che esistevano —
  quindi GM non poteva proxare tool funzionanti, e niente lo diceva. Ora
  entrambe derivano da `_tools()`, come Neuron ricava la sua da
  `_HANDLERS.keys()`, con un test che fallisce se qualcuno riscrive la lista.
- **Gli installer non offrono più di saltare l'embedding.** `fastembed` e
  `pyturso` sono hard dependency del package dalla 1.2.2: un install le ha o
  fallisce, esattamente come in Neuron. I picker però tenevano ancora la voce
  `"none" — Lexical only, no model download` dai tempi in cui `fastembed` era un
  extra opzionale, e il commento sopra spiegava che NeuRAG "è lexical-only senza
  fastembed" e che il modello è obbligatorio "a differenza di Neuron" — due
  affermazioni false da quando quel fix è entrato.
  E quella voce non faceva nemmeno ciò che diceva: scriveva `embed_model = ''`,
  che significa *segui Neuron / default multilingua*. Stampava "no embedding
  model will be downloaded", configurava il modello che aveva appena promesso di
  non scaricare, e lo scaricava al primo uso. La stringa letterale `"none"` che
  `lexical_only_requested()` cerca non veniva scritta da nessuno, quindi la
  modalità lessicale *scelta* era irraggiungibile dall'installer che doveva
  offrirla.
  Il lessicale puro resta dove sta una manopola da esperti:
  `neurag config set embed_model none`. Tolto dal menu, non dal runtime.
  Due test nuovi in `gray_matter/tests/test_installer_parity.py`: nessun
  installer dei tre può offrire di saltare l'embedder, e i due picker dello
  stesso progetto (`.ps1` e `.sh`) devono elencare gli stessi modelli — il
  commento diceva "keep in sync" e non lo verificava niente, mentre rinumerare
  una lista sposta ogni `EM_n` e ogni ramo del `case`.
- **Layer L1-L4 (DESIGN-EVOLUTION §3, P4)**: nessun layer è una tomba. Un nodo
  parcheggiato perde solo il diritto di essere scandito di default — chunk, link
  e tag restano dove sono, e `recall` arriva ovunque.
  - **`neurag park`** riporta i nodi abbastanza inattivi da scendere di layer.
    **Dry run** se non passi `--apply`: i punti di taglio non sono mai stati
    misurati su un corpus vero, e il modo in cui sbagliarli fa danno è una
    libreria che smette silenziosamente di offrire metà di sé. Regola:
    inattività × peso del link (`PARK_RULES`), mai l'età del contenuto. Un nodo
    ben collegato non si parcheggia: raggiungibile è raggiungibile.
  - **`neurag recall`** cerca in tutti i layer. `neurag query --deep` è lo stesso
    con l'intento non dichiarato; anche chiedere un sottoalbero per nome raggiunge
    un nodo dormiente, perché chi lo nomina sa già che esiste.
  - **`neurag decay`** indebolisce peso dei link e salienza dei tag per emivita.
    Il tempo trascorso si legge da `meta.decayed_at`, non dal timestamp di ogni
    riga: lanciarlo due volte in un giorno non è lanciarlo due volte in un anno.
    C'è un pavimento — sotto quello una rotta sarebbe sparita, non debole.
  - **L1**: working set di sessione persistito, TTL in query **e** in ore. Quello
    di Neuron vive in un processo acceso; questo sopravvive al processo, quindi
    senza il bound sull'orologio un vault interrogato due volte a sei mesi di
    distanza avrebbe ancora considerato "caldo" il primo risultato — e siccome il
    working set non si parcheggia mai, una singola query avrebbe protetto un nodo
    per sempre.
  - `search()` marca ciò che risponde (`last_used`, salienza dei tag): è l'unico
    scrittore di `salience`, altrimenti il decay dimezzerebbe un numero che
    nessuno alza. `touch=False` per chi ispeziona invece di consultare.
  - **Prima migrazione di colonna** (`_ensure_columns`): `CREATE TABLE IF NOT
    EXISTS` non tocca una tabella che esiste già, quindi una colonna nuova
    raggiunge un vault vecchio solo di lì. Gli indici girano **dopo**: un indice
    su una colonna appena aggiunta, lasciato in `SCHEMA_SQL`, fallisce con "no
    such column" su ogni vault esistente e — dato che gli errori di schema
    finiscono in `_corrupt` — si porta dietro la migrazione in silenzio.
  - Nessun knob nuovo: costanti e flag CLI, quindi i 6 installer non cambiano.
- **Il substrato dei tag è visibile alle diagnostiche**: `status()` riporta
  `tags`, e `health()` conta `dangling_tag_links` — righe di `node_tags`/
  `chunk_tags` che puntano a id morti. Quelle tabelle non hanno foreign key
  (pyturso 0.6.1 va in stack overflow sui cascade), quindi `delete_node` e il
  re-ingest per file le puliscono a mano: una riga penzolante è esattamente il
  modo in cui quella scelta può rompersi, e l'audit strutturale è il posto dove
  accorgersene.
- **I2 finalmente asserito, non solo dichiarato** (`tests/test_standalone_invariant.py`):
  i peer vengono resi non importabili e i moduli di NeuRAG devono caricare
  comunque. Copre anche una dipendenza introdotta tre moduli più in là, che un
  grep su `^import` non vedrebbe. Non è un divieto di *nominare* un peer: un
  `try/except ImportError` a livello di modulo è il modo corretto di dire che la
  dipendenza è opzionale (`server.py` lo fa con `gray_matter.server`).
- **`search()` e `get_chunks()` non restituiscono più il vettore**: il blob da
  384 float è macchinario di ranking (lo leggono MMR e il fallback coseno dentro
  `db.py`, nessuno fuori), e `neurag query --json` lo serializzava con
  `default=str`, seppellendo i campi leggibili sotto una pagina di byte
  escapati. Tolto ai due confini pubblici, non a ogni stampante. Nel vault resta.
- **`search()` dice sempre quanto e su che scala**: ogni risultato porta `score`
  e `score_from` (`cosine` | `bm25` | `rrf` | `cross-encoder`). Prima il punteggio
  esisteva solo come `sim`, attaccato dal ramo vettoriale: le righe arrivate da
  BM25 non ne avevano nessuno e il valore RRF della fusione veniva buttato via —
  quindi metà di un ranking ibrido era senza punteggio e l'altra metà portava un
  coseno che non spiegava più l'ordine (visibile su `neurag query --json`). Anche
  il reranker cross-encoder ora riscrive il punteggio in base a cui riordina.
  Le scale non sono confrontabili tra loro: `score_from` serve a leggerle.
  La diversificazione MMR riordina senza ri-assegnare punteggi, quindi con
  `diversify=True` l'ordine non è (deliberatamente) quello dei punteggi.
- **Un `;` dentro un commento SQL non tronca più lo schema**: `SCHEMA_SQL` viene
  tagliato a mano su `;` (nessun backend ha `executescript`) e un punto e virgola
  dentro un `--` spezzava la statement che lo conteneva. `_init_schema` applica
  lo script in un try/except che segna solo `_corrupt`, quindi la tabella
  semplicemente non compariva, in silenzio. `_split_sql` toglie i commenti prima
  di tagliare, usato da entrambi i chiamanti.
- **Tag substrate (DESIGN-EVOLUTION §4, P1)**: un tag smette di essere una
  stringa dentro cinque colonne JSON e diventa una riga. Nuove tabelle `tags`
  (`name` normalizzato, `uses`, `salience`, `last_used`), `node_tags`,
  `chunk_tags` + indici. `add_node`/`add_tags` scrivono entrambi i lati —
  la colonna legacy `nodes.tags` resta il read path finché la migrazione non è
  verificata sui vault reali.
  - **Migrazione idempotente**: al primo open il vault esistente viene
    ribaltato dalla colonna JSON a `node_tags`, poi il flag `meta.tags_migrated`
    salta la scansione. Rieseguirla non scrive nulla.
  - **Normalizzazione = join key**: `Cache`, `cache ` e `CACHE` sono un tag solo.
  - **IDF suppression**: un tag portato da più di metà dei nodi
    (`MAX_TAG_NODE_RATIO=0.5`, sotto `MIN_TAG_NODE_FLOOR=50` nodi non si
    sopprime niente) non genera più coppie candidate. Toglie anche il costo
    O(n²) che il floor Jaccard non toccava: quello limitava le SCRITTURE, non i
    confronti. La misura di similarità è invariata — il tag comune resta nel
    denominatore Jaccard, cambia solo quali coppie vengono considerate.
  - **`build_tag_links` legge `node_tags`**, non più il JSON di ogni nodo.
  - `chunk_tags` popolata da `index_into_node`; il replace per-file cancella le
    righe di join prima dei chunk (niente FK cascade: pyturso 0.6.1).
  - Test: `tests/test_tag_substrate.py` (11), incluso il gate di fase
    "link count invariato rispetto al path JSON legacy".

## 1.2.2
- **`config --json`**: `neurag config list --json` emette i knob strutturati
  (value/default/type/help/suggest) e `config set/get --json` l'esito — così il
  control center legge la config via CLI invece di importare `neurag.settings`.
  `config set` accetta ora il valore vuoto (guard `value is None`).
- **`repair --json`**: elenca le superfici cancellabili (`--wipe-knowledge`,
  `--wipe-config`) con path/stato, per il pannello Repair del control center.
- **`neurag gui` bootstrap reale + wheel d'emergenza OFFLINE**: se Gray Matter
  manca, lo installa nello stesso venv — cartella sorella (dev) → **wheel GM
  vendorata nel package** (`neurag/_gm_vendor/*.whl`, `--find-links` senza rete:
  GM ha solo `mcp` come dep, già presente) → indice pip → `git+https://github.
  com/recla93/gray-matter` — streamando il progresso, poi apre. La wheel va
  ricostruita a ogni release di GM (vedi RELEASE-CHECKLIST). keep-in-sync `neuron`.
- **Guard su `neurag register`**: se GM gestisce ancora NeuRAG (non in
  `unmanaged`), il register DIRETTO si rifiuta (doppia registrazione) e indirizza
  a `neurag go-standalone` o `gray-matter deregister neurag`. Bypass `--force`;
  senza GM nessun guard. keep-in-sync con `neuron/clients.py`.
- **Icona desktop "NeuRAG"** (launcher standalone): l'installer standalone la crea
  già a fine install (`neurag gui --shortcut-only`) e `neurag gui` la ri-assicura
  a ogni apertura. Logica in `neurag/shortcut.py` (copia tool-local cross-OS,
  keep-in-sync con `gray_matter/shortcut.py` — serve senza GM). L'icona punta a
  `neurag gui`, che bootstrappa GM al primo click. Idempotente (marker nel venv).

## 1.2.1
- **Fix flash CMD (Windows)**: `db.py` (pip install pyturso durante il fallback
  Turso) e `clients.py` (register/deregister via `claude` CLI) ora usano
  `CREATE_NO_WINDOW`. Nel `clients.py` il flag è nel runner di default, così i
  runner iniettati dai test non ricevono `creationflags` a forza.
- **Extra `[gui]`** = `gray-matter`: il control center è UNO (`gray_matter.webgui`);
  `neurag gui` lo bootstrappa se manca. Il runtime MCP resta indipendente da GM
  (import guardato) — verificato: NeuRAG importa e gira con gray_matter assente.

## 1.2.0
- **Registrazione MCP standalone**: nuovo `neurag/clients.py` (clone mirato di
  `neuron/clients.py`, keep-in-sync) — matrice client (claude-desktop,
  claude-code, cursor, vscode, opencode), `register`/`deregister` non
  distruttivi (backup `.neurag-bak`, verify-after-write con rollback, JSONC mai
  riscritto → snippet manuale, Claude Code via `claude mcp add`). Entry via
  `python -m neurag.server`, mai console-script.
- **Nuovi comandi CLI** (gestiti PRIMA del DB): `neurag register`,
  `neurag deregister`, `neurag go-standalone` (registrazione diretta + rilascio
  dal gateway GM se presente, reversibile con `gray-matter register
  --gateway`), `neurag gui` (control center condiviso se GM c'è, altrimenti
  offerta di install — mai silenziosa).
- **Server disaccoppiato da GM**: l'autoregister al gateway salta se NeuRAG è
  in lista `unmanaged` (niente tool pubblicati due volte); senza GM il server
  MCP gira standalone puro (già così, ora verificato).
- **Repair puntuale**: `neurag repair` stampa (o lancia con `--reinstall`) il
  PROPRIO installer con `--force`, risolto dai path registrati
  (`paths.source_dir()`).
- **Installer `--force`**: `install.ps1 -Force` / `install.sh --force` —
  reinstall forzato del pacchetto NeuRAG anche a versione invariata (pattern di
  gray_matter, inoltrato anche al GM installer).

## 1.1.0

### Grafizzazione server-side (`ingest`)
- Nuovo modulo `ingest.py`: cartelle → nodi (radice = godnode, primo livello
  = fundamental, sottocartelle = specialization), file → chunk nel nodo della
  propria cartella, poi embedding e `rebuild_links` — tutto in un colpo,
  senza far passare i chunk dal contesto LLM.
- Tool MCP `knowledge_ingest` (job in background, risponde subito con un id)
  + `knowledge_ingest_status` (progresso/esito). Il job apre una connessione
  DB propria (thread-safe); l'embedder caldo del worker viene riusato.
- CLI `neurag ingest <path> [--godnode X]`: stessa pipeline, sincrona, con
  progresso streamato riga per riga (perfetta dal control center).

### Modifica nodi da CLI/GUI
- `db.rename_node`: rinomina aggiornando il path del sottoalbero intero.
- CLI `rename-node <nome> <nuovo>` e `remove-node <nome>` — compaiono da
  soli nel control center di Gray Matter.

### Alleggerimento import
- `cli.py` (1.0.1): niente import di db/chunker a livello modulo — il
  catalogo GUI legge i comandi senza caricare sqlite/turso/embedder.

## 1.1.3

### Path SSOT (NeuRAG possiede i suoi path) — 2026-07-22
- Nuovo `neurag/paths.py`: unica fonte di verità delle location NeuRAG
  (`data_dir`, `db_path`, `config_path`, `source_dir`). `db.py` e `settings.py`
  ora delegano qui invece di ridefinire i percorsi. Gray Matter li SCOPRE
  chiamando `neurag.paths` (non li hardcoda più). Override `NEURAG_HOME`.
- `neurag record-paths --source <dir>`: NeuRAG registra la propria cartella
  sorgente (self-knowledge) così repair/reinstall la ritrovano. Nascosto in GUI.

## 1.1.2

### Turso preferito con fallback documentato — 2026-07-22
- Sul vault reale (db_path None) se NON siamo su Turso, `KnowledgeGraph` prova
  ad acquisirlo — import, e se manca `pip install pyturso==0.6.1` dalle wheel
  vendored (`--find-links vendor/`) — fino a `NEURAG_TURSO_ATTEMPTS` (default 3)
  volte. Solo dopo degrada a sqlite3 **documentando gli errori** (in `status`
  → `turso_degraded`/`turso_errors`, e in `doctor`). Nessun crash: il fallback
  resta. Escape: `NEURAG_REQUIRE_TURSO=0`; autoinstall off: `NEURAG_TURSO_AUTOINSTALL=0`.
  I DB di test (db_path esplicito) non sono toccati → la suite sqlite resta verde.
- Nuovo comando `neurag repair` (scope solo NeuRAG): wipe selettivo di
  knowledge.db / config, poi promemoria del reinstall forzato. Gestito prima di
  aprire il DB, così funziona anche su vault corrotto/non-Turso.

## 1.1.1

### Fix: DB corrotto non crasha più (diagnostica robusta) — 2026-07-22
- Un `knowledge.db` malformato faceva sollevare `DatabaseError: file is not a
  database` all'apertura (`_init_schema`/PRAGMA) → crashava **ogni** comando
  neurag, non solo `health`, con traceback grezzo nel control center.
- Ora `KnowledgeGraph.__init__` non alza: intercetta la corruzione e la marca
  (`_corrupt`). `status`/`health`/`doctor` la **riportano** ("DB CORROTTO" +
  errore + hint di recovery) con exit 1 pulito, invece di crashare. Vale anche
  per i tool MCP `knowledge_status`/`knowledge_health` (niente più "Internal
  Server Error" a valle).
- Aggiunto `PRAGMA busy_timeout=5000` all'apertura (WAL + busy_timeout: gli
  scrittori si accodano invece di corrompersi — FASE 0 dell'audit).

### Reranker cross-encoder (opt-in, OFF di default) — 2026-07-22
- Nuovo stadio di reranking opzionale: la ricerca recupera un pool più ampio
  di candidati (`rerank_pool`, default 50), poi un cross-encoder li riordina e
  tiene i veri top-n. Pattern RAG standard "retrieve wide, rerank narrow":
  più precisione al costo di latenza + download modello, perciò **spento di
  default** e attivabile per singola install.
- Nuovo `neurag/reranker.py` (`fastembed.TextCrossEncoder`, lazy + fallback
  identico a `embedder.py`: se off o modello assente → `NullReranker`, costo
  zero, nessun download).
- Nuovo `neurag/settings.py` (specchio di `gray_matter/settings.py`): config
  JSON in `~/.local/share/neurag/config.json` — SEPARATO da `knowledge.db`.
  Knob: `rerank` (bool), `rerank_pool` (int), `rerank_model` (str). Env
  `NEURAG_RERANK`/`NEURAG_RERANK_MODEL` hanno la precedenza sul file.
- CLI `neurag config get|set|list` → toggle per **tutte le install**, anche
  NeuRAG standalone. Es.: `neurag config set rerank on`.
- Control center: la card `config` non è più il form grezzo action/key/value —
  è un **pannello Impostazioni** con toggle/select/campi che si salvano subito
  (`webgui.py` `config_knobs`/`config_set` + rendering in `webgui.html`). Vale
  per ogni ambiente con un `config` (Gray Matter e NeuRAG), zero elenchi a mano;
  i knob si auto-descrivono da `settings.HELP`/`SUGGEST`. Per `rerank_model` il
  picker propone il multilingue `jinaai/jina-reranker-v2-base-multilingual`.
- `db.search` refattorizzata in `_retrieve` (stage 1) + rerank opzionale;
  con reranker OFF è un no-op wrapper (comportamento invariato). `status`/
  `doctor` ora mostrano lo stato del reranker.

### Fix da audit OpenCode (2026-07-21)
- `install.ps1`: nel fallback PyPI, exit solo su successo di `gray-matter
  install` → degrade a standalone invece di terminare (fix OpenCode);
  specchiato in `install.sh` (niente `exec`: si prosegue sul fallback).

### Installer — GM opt-out (consenso informato, DESIGN-CLOUD-MEMORY §6)
- `install.sh`/`install.ps1`: Gray Matter non è più forzato — prompt
  `Install Gray Matter (recommended)? [Y/n]` con il deficit esplicito (senza GM
  si perdono solo bridge cross-store e auto-surface dei vicini). Headless:
  `--no-gm` / `GM_OPTIN=0`. Rifiuto → install STANDALONE (venv proprio, doctor
  + snippet MCP `neurag-mcp` per il client). GM non ottenibile (offline) →
  degrada a standalone invece di uscire. Reversibile ri-eseguendo senza `--no-gm`.

## v1.0.0 (2026-07-21)

Prima release stabile. Consolida 0.3.0 (link_graph, rebuild_links, source
attribution nei risultati, vector SQL su Turso, AST chunking, Turso mandatory).
Le API dei tool `knowledge_*` sono considerate stabili.

## v0.3.0 (2026-07-20)

### New features
- `link_graph`: shows all node links with weights and evidence
- `rebuild_links`: clears and rebuilds links from tags + cross-refs
- Source attribution in `knowledge_query` results (D1)

### Database improvements
- Turso mandatory (pyturso==0.6.1) for vector search
- `_FixedEmbedder` test helper for deterministic embeddings

### Installer unification
- Canonical install via `install.ps1` / `install.sh` delegating to GM
- Vendored pyturso wheels (py310-314 win_amd64)

### Documentation
- README.md added
- INSTALL-AI.md (EN) + INSTALL-AI.it.md (IT)
- DESIGN-CROSSLINKS.md

### Tests
- 30+ tests passing (test_node_links, test_vector_sql, test_neighbors)
- Vector SQL test with Turso engine verification

## v0.2.0 (2026-07-18)

- Source attribution in knowledge_query (D1)
- AST chunking + symbol tags → triggers
- knowledge_health L1
- Installer bundle GM + wheels
