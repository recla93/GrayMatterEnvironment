# ADR-015: Neuron salva fatti, non parole

> Status: **Proposed** — 2026-11-08.
> Relates to: ADR-014 (gli hook che leggono e controllano la scrittura), ADR-013 (`owner`/`space`
> sulle righe), `STATO-LAVORI-2026-11-08.md` (le misure del §1)
> Scope: **solo Neuron**. NeuRAG e Gray Matter avranno il loro ADR; qui è definito solo il confine
> con loro (§6).

> [!abstract] In sintesi
> - **Cos'è.** Neuron diventa un raccoglitore di episodi: avanzamenti, decisioni, fix, dettagli,
>   idee, informazioni e abitudini dell'utente. Il **fatto** è l'unità di memoria. I concetti sono
>   l'indice per ritrovarlo.
> - **Come funziona.** Il modello scrive i fatti, tipizzati, ognuno con i suoi concetti. Neuron li
>   tiene per sempre: un fatto si aggiorna con uno nuovo che lo supera, non si cancella. La lettura
>   parte dal messaggio e restituisce fatti, non nodi.
> - **A cosa serve.** A non dover ripetere le cose. Oggi Neuron salva parole e attacca i fatti come
>   allegato facoltativo. Quando la parola esce dal grafo, il fatto muore con lei.

> [!note] I riferimenti al codice si riferiscono al commit `b29a186`.

---

## 1. Contesto

### 1.1 Lo scopo di Neuron

Neuron serve a ricordare **cosa è successo e cosa sappiamo dell'utente**, argomento per argomento:

| L'utente vuole salvare | Esempio |
|---|---|
| avanzamenti | «la release 1.7.0 è pubblicata, CI verde» |
| decisioni | «https invece di wss: Turso rifiuta l'handshake ws» |
| fix e debug | «i test falliscono col WAL bloccato: pyturso 0.6.1 nel Python di sistema» |
| dettagli e informazioni | «i grafi vivono in `%LOCALAPPDATA%\GrayMatterEnvironment\neuron\graphs`» |
| aggiornamenti e novità | «la memoria non è più solo su un PC: c'è una copia esterna» |
| idee | «il fatto come unità, i concetti come indice» |
| l'utente e le sue abitudini | «scrive in italiano, vuole il piano prima del codice» |

Il grafo di concetti non è lo scopo. È il modo di ritrovare queste cose.

### 1.2 Oggi è al contrario

Il nodo è l'unità e il fatto (`episode`) è un campo facoltativo di `store_turn`.

| Misura | Valore | Fonte |
|---|---|---|
| Nodi con almeno un fatto, grafo `ai` | 176 su 516 (34%) | PC principale, 2026-11-08 |
| Fatti distinti, grafo `ai` | 149 su 204 turni | idem |
| Nodi con almeno un fatto, grafo `default` | 2 su 127 (3 fatti in 13 turni) | secondo PC, 2026-11-08 |
| `store_turn` con `episode` nella sessione della release 1.7.0 | 0 su 4 | sessione del 5-6/11 |
| Tipo «utente» o «abitudine» | non esiste | schema |

### 1.3 Quattro modi in cui un fatto scritto va perso

Il fatto vive **dentro** il nodo, quindi segue la vita del nodo. E la vita di un nodo è breve per
costruzione: salienza, tetto, consolidamento.

| # | Dove | Cosa succede |
|---|---|---|
| 1 | `models.py:573`, `EPISODES_PER_NODE = 5` | al sesto fatto su un nodo, il più vecchio si cancella. Visto il 6/11: `episode_lost`, turno 122. |
| 2 | `models.py:611`, tetto `MAX_NODES` | il nodo con meno salienza viene sfrattato, e la save cancella i suoi episodi (`models.py:1693`). Il grafo `ai` ha toccato il tetto il 4/11: da lì ogni concetto nuovo ne sfratta uno vecchio. |
| 3 | `models.py:1223`, `_merge_into` | il consolidamento fonde due nodi simili. Gli episodi dell'assorbito **non** passano al sopravvissuto, e la reconcile li cancella (`models.py:1773`). |
| 4 | `models.py:1260`, `_drop_orphans` | il nodo orfano va nel `_graveyard`, che tiene parola, salienza e dominio, **non** gli episodi. Il 12/9 una sola chiamata ha archiviato 255 nodi su 296. |

C'è anche uno spreco che accelera il caso 1. `store_turn` copia il fatto su **ogni** parola chiave
del turno (`server.py:1599`): un turno da 5 parole occupa 5 posti. Lo schema invece dice
«attached to the first keyword». Su un nodo-hub (`ngrx`, `release`) i 5 posti si riempiono in
pochi turni.

### 1.4 La lettura non può restituire ciò che non è scritto

`pre_turn` trova nodi e poi ne mostra gli episodi (`server.py:2317`). Su un nodo senza fatti
mostra solo il nome. Le due soglie del richiamo, `VEC_FALLBACK_DELTA` (`server.py:1194`) e
`FACT_DELTA` (`server.py:129`), sono relative: tengono ciò che sta vicino al migliore, qualunque sia il migliore.
Un messaggio fuori tema riempie comunque i posti (la carbonara arriva a cos 0,559 su
`seed-cachato`).

Dal 15/10 i commit sono andati 15 alla lettura e 2 alla scrittura. Si è tarato il richiamo di una
memoria che non scrive.

---

## 2. Decisione

**D1. Il fatto è l'unità di memoria.** Una tabella `facts`, separata dai nodi. Il fatto ha un suo
id, un tipo, un testo, un vettore e una data. Non dipende da nessun nodo per esistere.

**D2. I concetti sono l'indice.** Una tabella `fact_concepts(fact_id, keyword)`. Un fatto ha da 1 a
5 concetti, e un concetto indicizza tutti i fatti che lo nominano. Il nodo resta quello di oggi
(salienza, link, vettore), ma diventa una **voce d'indice**: sfrattarlo, fonderlo o archiviarlo
tocca l'indice, mai i fatti.

**D3. I fatti hanno un tipo.** Sette tipi, chiusi:

| Tipo | Per cosa | Esempio |
|---|---|---|
| `progress` | avanzamenti, stato dei lavori | «release 1.7.0 pubblicata» |
| `decision` | una scelta e il suo perché | «https invece di wss perché…» |
| `fix` | causa e rimedio di un problema, debug | «WAL bloccato: pyturso 0.6.1» |
| `fact` | dettagli e informazioni stabili | «i grafi stanno in…» |
| `idea` | proposte, direzioni non ancora decise | «fatti come unità» |
| `user` | chi è l'utente, cosa sa, cosa vuole | «lavora su due PC» |
| `habit` | come l'utente lavora, preferenze ripetute | «piano prima del codice» |

Il tipo serve alla lettura (D7) e al confine con NeuRAG (§6). Sette e non di più: un tipo che il
modello non sa scegliere al primo colpo diventa rumore.

**D4. Append-only.** Un fatto non si cancella e non si modifica. Un aggiornamento è un fatto nuovo
con `supersedes = <id del vecchio>`. Il vecchio resta su disco con `status = superseded`, e la
lettura non lo mostra più. Spariscono `EPISODES_PER_NODE` e il taglio a 1,5×: un fatto lungo resta
intero (il budget lo governa la lettura), e si consiglia di restare sotto i 400 caratteri.

Il peso è trascurabile: 10.000 fatti da 400 caratteri, con vettore a 384 dimensioni, stanno sotto
i 25 MB.

**D5. Il fatto lo scrive il modello.** Nessun estrattore sul messaggio. Il modello della sessione
ha già capito il turno ed è già pagato: un fatto costa una frase in output, circa 50 token. Un
secondo modello costerebbe l'intero turno in input a ogni messaggio. Un modello locale gira sulla
GPU che sta morendo.

`store_turn` si riduce a:

```json
{"facts": [
  {"kind": "fix", "text": "…", "concepts": ["pyturso", "wal", "test"]},
  {"kind": "user", "text": "…", "concepts": ["utente"], "supersedes": 41}
]}
```

`topic`, `keywords` e `links` restano facoltativi. I concetti dei fatti diventano nodi con le
regole di curation di oggi (`vet_keywords`). Un `store_turn` senza `facts` è ancora accettato per
una release, e la risposta lo dice: `0 fatti salvati`.

**D6. Neuron segnala i doppioni, non li fonde.** Alla scrittura confronta il fatto nuovo con i
fatti attivi dello stesso tipo e con gli stessi concetti. Sopra una soglia di somiglianza risponde
`simile a #41: …`. Decide il modello, con `supersedes`. Fondere in automatico è il caso 3 del §1.3
in un'altra forma.

**D7. La lettura restituisce fatti.** `pre_turn` (e il `recall` dell'hook) fa due cose:

1. **Sempre**: i fatti attivi `user` e `habit` del contesto, entro un budget fisso, come
   `MEMORY.md`.
2. **Per pertinenza**: i fatti che corrispondono al messaggio. Il punteggio somma la vicinanza
   vettoriale col testo del fatto e l'attivazione dei suoi concetti, propagata sui link
   (`spreading_activation`, `models.py:846`, oggi usata solo per lo stimolo 🧠). Una **soglia
   assoluta**: sotto, niente, anche se i posti restano vuoti.

Un fatto già mostrato in questa sessione non torna. Se due fatti si superano, si mostra l'ultimo.

**D8. La conferma passa al fatto.** Oggi `IMPLICIT_CONFIRM` (`server.py:1635`) premia un **nodo**
servito e poi riusato, e così inclina il grafo. Il segnale va sul fatto: mostrato e poi citato o
superato vuol dire usato. Il nodo guadagna salienza solo quando un fatto nuovo lo nomina.

---

## 3. Le tre domande

### 3.1 Come salvare

```sql
CREATE TABLE facts (
  context    TEXT NOT NULL,
  id         TEXT NOT NULL,      -- 8 cifre esadecimali casuali, vedi sotto
  kind       TEXT NOT NULL,      -- progress|decision|fix|fact|idea|user|habit
  text       TEXT NOT NULL,
  turn       INTEGER, created_at TEXT NOT NULL,
  source     TEXT NOT NULL,      -- model | migration
  supersedes TEXT,
  status     TEXT NOT NULL DEFAULT 'active',   -- active|superseded
  owner TEXT DEFAULT '', space TEXT DEFAULT '',
  PRIMARY KEY (context, id));
CREATE TABLE fact_concepts (context TEXT, fact_id TEXT, keyword TEXT,
  PRIMARY KEY (context, fact_id, keyword));
```

*Corretto in fase 1 (2026-11-08).* L'id è un testo casuale e non un `AUTOINCREMENT`: il modello lo
deve leggere prima che la riga esista, e su uno store cloud condiviso due scrittori non possono
contarlo in memoria senza scontrarsi. `session` non c'è: Neuron non conosce la sessione, e l'hook
`Stop` della fase 3 lavora sul turno. `fact_vectors` è rinviata alla fase 2, insieme alla lettura
che la usa: oggi i vettori dei fatti li tiene già la cache del richiamo (`_recall_vectors.bin`).

Le regole che chiudono i quattro casi del §1.3:

| Caso | Regola nuova |
|---|---|
| tetto per nodo | non esiste più |
| nodo sfrattato | la save cancella nodo, vettore e link. Le righe `fact_concepts` restano: alla prossima scrittura del concetto il nodo rinasce e ritrova i suoi fatti. |
| merge | `fact_concepts` dell'assorbito viene ripuntato sul sopravvissuto |
| orfano | come lo sfratto |

`owner` e `space` seguono l'ADR-013: si scrivono all'INSERT e non cambiano.

### 3.2 Come estrarre senza spendere

Non si estrae dal messaggio. Si scrive il fatto quando c'è:

| Chi | Cosa fa | Costo |
|---|---|---|
| il modello | scrive 0–3 fatti per turno con tipo e concetti | ~50 token per fatto, in output |
| Neuron | calcola un vettore per fatto, alla scrittura | un embedding col modello già caricato: ~8 ms su CPU (20 frasi in 0,17 s, MiniLM via fastembed, 8/11) |
| l'hook `Stop` (ADR-014, lato GM) | controlla che un turno sostanzioso abbia scritto almeno un fatto; se manca, rimanda il modello al lavoro una volta sola (`decision: block`, `stop_hook_active` contro i cicli) | una richiesta IPC |

*Corretto in fase 3 (2026-11-08).* Neuron non espone niente: l'hook legge il transcript che Claude
Code gli passa, dove ogni `store_turn` è scritto con i suoi argomenti. Funziona anche a daemon
spento, e Neuron non deve conoscere la sessione. La regola sul turno «sostanzioso» è nel §7.4.

Il `save` del memhook (ADR-014 D4), che salva un episodio sulle parole già nodi, si ferma. Era un
estrattore sul messaggio con il vocabolario chiuso: 4 messaggi su 5 non salvavano niente.

### 3.3 Come rendere tutto più efficiente

| Regola | Effetto |
|---|---|
| una sola richiesta per lettura (c'è già, `action: "recall"`) | ~330 ms, di cui ~310 per la KB |
| soglia assoluta sui fatti | un messaggio fuori tema costa 0 token |
| niente fatti già mostrati nella sessione | il contesto non si ripete |
| `user` e `habit` con un budget fisso, separato | non spingono fuori i fatti pertinenti |
| schema di `store_turn` ridotto (D5) | meno token per ogni chiamata di scrittura |
| tolto il promemoria «→ next: pre_turn; confirm…» dalla risposta | a ogni turno, quando c'è l'hook |
| nella lettura il messaggio intero va al vettore; `extract` serve solo a trovare i nomi di nodi presenti nel testo | la lista di 472 stopword smette di decidere cosa entra nel grafo |

---

## 4. Il disegno

```
turno del modello
   │
   ▼  store_turn {facts:[{kind, text, concepts, supersedes?}]}
   │    per ogni fatto:
   │      curation dei concetti (vet_keywords) → nodi nuovi o esistenti
   │      INSERT facts, fact_concepts, fact_vectors
   │      se supersedes: UPDATE facts SET status='superseded' WHERE id=…
   │      doppioni attivi stesso tipo e concetti → «simile a #id» nella risposta
   │    salienza +1 ai concetti nominati; link come oggi
   ▼
hook Stop → facts_written(session, turn)? → se 0 e turno sostanzioso: block, una volta

messaggio dell'utente
   │
   ▼  recall / pre_turn
        A. fatti attivi user + habit                      (budget fisso)
        B. vettore(messaggio) ⋅ fact_vectors               ┐
           nomi di nodi nel messaggio → spreading_activation├→ punteggio
           sopra la soglia assoluta, non già mostrati       ┘
        → righe «[tipo] testo  (concetti)»
```

---

## 5. Migrazione

| Da | A |
|---|---|
| righe `episodes` con lo stesso testo su più parole | **un** fatto, con quelle parole come concetti |
| `turn` dell'episodio | `turn` del fatto; `created_at` = data della migrazione |
| tipo | `fact`: il tipo vero non si può indovinare. Correggerlo è un `supersedes`. |
| `source` | `migration` |

La tabella `episodes` resta in sola lettura per una release, poi si toglie. Prima della migrazione
si fa il backup (`_backups`, già giornaliero) e **una copia fuori dalla macchina**.

---

## 6. Confine con NeuRAG e Gray Matter

Queste cose non le decide questo ADR. Qui si fissa solo cosa Neuron offre agli altri due.

| Verso | Neuron offre | Lo decide |
|---|---|---|
| NeuRAG (conoscenza comprovata) | i fatti `decision`, `fix` e `fact` attivi, mai superati, confermati (D8) o più vecchi di N giorni, come candidati all'elevazione. Una volta elevato, il fatto resta in Neuron con un puntatore alla voce NeuRAG. | ADR NeuRAG |
| GM (orchestratore) | `facts_written` per l'hook `Stop`; i fatti `idea` come materia per il flash; i concetti per i bridge | ADR GM |

---

## 7. Piano

| Fase | Contenuto | Si chiude quando |
|---|---|---|
| **0** ✓ | Set di valutazione: 20 messaggi veri, ciascuno con i fatti che il richiamo deve portare, e 5 fuori tema che non devono portare niente | il file esiste e un comando lo misura: fatti attesi trovati, fatti mostrati sui fuori tema (§7.1) |
| **1** ✓ | Tabelle `facts`, la migrazione, il nuovo `store_turn` (con `episode` accettato come un fatto `fact`). Sfratto, merge e orfani non toccano più i fatti. | un test per ciascuno dei quattro casi del §1.3; la migrazione del grafo `ai` dà 149 fatti (§7.2) |
| **2** ✓ | Lettura per fatti in `pre_turn` e in `_hook_recall`, con la soglia assoluta tarata sul set della fase 0 (§7.3) | sul set della fase 0: oltre il 45% di fatti trovati e oltre 10/20 messaggi completi, 0 fatti sui fuori tema |
| **3** (codice ✓) | Hook `Stop` che controlla (lato GM), via il promemoria nella risposta, stop al `save` del memhook (§7.4) | una settimana d'uso: ogni turno sostanzioso ha almeno un fatto — **da verificare dal vivo** |
| **4** (in parte) | `user` e `habit` sempre presenti (D7.1 ✓ `b453c08`, un fatto non torna nella sessione `dc54c19`), segnalazione dei doppioni (D6 ✓ `0392b5b`), conferma sul fatto (D8: aperta, serve una scelta di progetto) | una sessione nuova su un altro PC parte sapendo chi è l'utente |

Prima della fase 0 non si tara niente. L'8/11 una misura su due campioni si è rivelata sbagliata
un'ora dopo.

### 7.1 Fase 0: fatta, la baseline

Il set è `neuron/bench/recall.json` (v1): 30 fatti veri con i sette tipi, 20 messaggi veri dai
transcript, 5 fuori tema inventati. Il comando è `python neuron/bench/run.py`: scrive la memoria
con `store_turn` in una cartella temporanea, poi interroga come fa l'hook, col modello di embedding
vero. `tests/test_bench_recall_set.py` controlla che il set resti coerente. Il risultato è in
`neuron/bench/results/F0-baseline.json`, e due run danno file identici.

| Lettura | Fatti trovati | Messaggi completi | Rumore | Fatti sui fuori tema | Caratteri per richiamo |
|---|---|---|---|---|---|
| `extract` → `pre_turn` (committato, `b29a186`) | 45% (14/31) | 9/20 | 0,75 per messaggio | 5 | 648 |
| messaggio intero come topic (non committato) | 45% (14/31) | 10/20 | 0,9 per messaggio | 3 | 699 |

Cosa dice:

- **Più di metà dei fatti attesi non arriva**, anche se sono tutti scritti (30 su 30 nel grafo).
  Mancano soprattutto i fatti di stato (`p1`–`p3` su «controlliamo lo stato di GM») e le
  abitudini (`u2` su «pusha, la CI la controllo io»): è il caso di D7.1, i fatti `user` e `habit`
  sempre presenti.
- **I fuori tema non tacciono.** La carbonara porta 2–3 fatti (`k1`, `z4`, `u1`): serve la soglia
  assoluta di D7.
- **Le due letture pareggiano.** La modifica al richiamo non committata non migliora né peggiora:
  la scelta si fa su altro (toglie una chiamata IPC).
- **Il set non mette alla prova la scrittura.** Con un fatto per turno e 30 turni nessuno dei
  quattro casi del §1.3 scatta. Le perdite di scrittura le coprono i test della fase 1, non questo
  bench.

### 7.2 Fase 1: fatta

| Cosa | Dove |
|---|---|
| fatti in tabella propria, append-only; `g.episodes` diventa l'indice derivato dei fatti attivi, così `pre_turn`, la ricerca, l'export e `promote` di GM leggono come prima | `models.py`, `add_fact`, `_save_facts` |
| i quattro casi del §1.3, attraverso save e load veri | `tests/test_episodes.py`, `test_1_…` – `test_4_…` |
| `store_turn(facts=[…])`, `supersedes`, `facts: 0 saved`, `#id` in `pre_turn` | `server.py`, `tests/test_store_turn_contract.py` |
| migrazione al caricamento, una volta sola, tabella `episodes` mai riscritta | `Graph.import_episodes`, `test_legacy_episodes_become_one_fact_per_text` |

Limiti di scrittura scelti in fase 1: al massimo 5 fatti per turno, 5 concetti per fatto, taglio di
sicurezza a 2000 caratteri. Più concetti del tetto di 8 keyword per turno non fanno perdere il turno:
le keyword in più si scartano con una nota, e i fatti tengono i concetti rimasti.

**Migrazione provata** su una copia dei grafi di questo PC, scritti da Neuron 6.4.5: `default` da 5
righe a 3 fatti (lo stesso testo stava due volte sullo stesso nodo), `backend` da 16 a 16; dopo il
salvataggio un secondo caricamento non rimigra niente. **Il grafo `ai` (149 fatti attesi) è
sull'altro PC: il criterio resta da verificare lì.**

**Il bench** (`results/F1.json`) scrive ora con la chiamata nuova, `facts` tipizzati senza topic né
keyword:

| Lettura | Fatti trovati | Messaggi completi | Rumore | Fuori tema | Caratteri |
|---|---|---|---|---|---|
| `extract` → `pre_turn` | 45% (=) | 9/20 (=) | 0,55 (era 0,75) | 1 (era 5) | 596 |
| messaggio intero | 45% (=) | 10/20 (=) | 0,7 (era 0,9) | 0 (era 3) | 638 |

La lettura non è cambiata, quindi i fatti trovati non si muovono. Il rumore scende perché il topic
del nodo ora è il testo del fatto e non l'elenco delle parole, e la ricerca vettoriale giudica meglio.

### 7.3 Fase 2: fatta

`pre_turn` cerca fra **tutti** i fatti attivi, non fra quelli dei primi tre nodi
(`search._search_facts`). Il punteggio è il coseno fra il messaggio e `concetti. frase`, più un
bonus di 0,20 quando il messaggio nomina uno dei concetti del fatto (la parola, o il suo inizio con
al massimo tre lettere in più: `push` → `pusha`, `wheel` → `wheels`). Poi una soglia assoluta a
0,40, un taglio relativo a 0,15 dal migliore, al massimo 3 fatti. I fatti vengono per primi nella
risposta, con tipo, concetto e id, e la soppressione dei nodi irrilevanti non li tocca: hanno già
la loro soglia. Senza un modello di embedding si torna ai fatti più recenti dei primi nodi.

Taratura, sul set della fase 0, con il messaggio vero come domanda:

| Regola | Fatti trovati | Messaggi completi | Rumore | Fuori tema |
|---|---|---|---|---|
| solo vettore per fatto, soglia 0,40 | 16/31 | 10/20 | 1,10 | 0 |
| + bonus del concetto nominato 0,20 | 19/31 | 12/20 | 1,30 | 0 |
| + taglio relativo 0,15 (scelta) | 17/31 | 12/20 | 0,50 | 0 |

I valori stanno su un altopiano: bonus fra 0,15 e 0,25 e soglia fra 0,35 e 0,40 danno tutti fra
15 e 21 fatti trovati, e zero fuori tema. Il fuori tema più vicino a un fatto arriva a 0,29. Le
quattro manopole sono variabili d'ambiente (`NEURON_FACT_MIN_SCORE`, `_NAMED_BONUS`, `_DELTA`,
`_RECALL_K`). **Sono tarate sullo stesso set su cui si misurano**: con 20 messaggi il rischio di
adattarsi al set c'è, e il prossimo passo che lo riduce è allargarlo.

Il bench (`results/F2.json`), attraverso il percorso vero (`store_turn`, poi `pre_turn`):

| Lettura | Fatti trovati | Messaggi completi | Rumore | Fuori tema |
|---|---|---|---|---|
| messaggio intero (F1 → F2) | 45% → **52%** (16/31) | 10 → **11**/20 | 0,70 → 0,50 | 0 → 0 |
| `extract` → `pre_turn` (F1 → F2) | 45% → 39% | 9 → 9/20 | 0,55 → 0,45 | 1 → 4 |

Con la lettura per fatti, **il messaggio intero vince**, e chiude la decisione rimasta aperta
dall'8/11: la modifica non committata al richiamo (`_hook_recall` manda il messaggio come topic) si
tiene. `extract` peggiora per un motivo preciso: la sua domanda è una lista di parole ripetute
(`milano tempo fara domani milano tempo fara domani`), e una lista di parole somiglia al fatto che
parla di stopword (cos 0,41-0,43). Lo stesso rischio ce l'ha un `pre_turn` chiamato dal modello con
un topic di tre parole: non misurato.

**Cosa resta mancato**, e perché:

| Messaggio | Fatti attesi persi | Perché |
|---|---|---|
| «controlliamo lo stato di GM» | `p1`, `p2`, `p3` | una domanda sullo stato non somiglia a nessun fatto di stato e non ne nomina i concetti: serve la regola «gli ultimi avanzamenti» (fase 4) |
| «bisogna fixare la suite» | `x1`, `k2` | idem, e «suite» qui vuol dire il prodotto, non i test: il set lo conta come mancato |
| «siamo in un altro PC» | `u1`, `p3` | sono fatti `user`: la fase 4 li porta sempre |

### 7.4 Fase 3: il codice c'è, la prova dal vivo no

`memhook.py save` (sull'evento `Stop`, già registrato dall'install) non estrae più parole: controlla
che il turno abbia salvato un fatto. Legge il transcript dall'ultimo messaggio vero dell'utente e
rimanda il modello al lavoro **una volta** (`{"decision": "block", "reason": …}`) quando:

| Condizione | Perché |
|---|---|
| il messaggio è vero: non un `ok`/`grazie`, non un `/comando`, non sotto i 12 caratteri | stesso filtro del richiamo |
| il turno ha lavorato (almeno uno strumento che non sia di memoria) o ha risposto con almeno 600 caratteri | una risposta di due righe non ha niente da ricordare |
| nessun `store_turn` dopo quel messaggio porta `facts` o `episode` | un `store_turn` con sole keyword salva parole |
| non è già il secondo `Stop` (`stop_hook_active`) | niente cicli: al secondo giro il modello chiude anche senza salvare |

Il messaggio dice cosa salvare e che, se non c'è niente, si chiude e basta. Costo: un giro del
modello in più nei turni sostanziosi senza fatti, e solo in quelli.

Tolto anche il promemoria «→ next: pre_turn; confirm…» in coda a ogni risposta di `store_turn`:
il giro successivo lo avviano le istruzioni di sessione e gli hook.

Non toccato: il vecchio `neuron_reminder_hook.py` («N turni dall'ultimo store_turn») resta
registrato dove l'install lo mette. Con il controllo su `Stop` è doppio, e conta ancora i
`store_turn` senza fatti: va tolto nell'install, che va provato dal vivo.

**Le istruzioni ai modelli** dicevano ovunque `store_turn(topic, keywords, links)`: con quelle,
nessun modello avrebbe mai mandato un fatto. Ora dicono `store_turn(facts=[{kind, text,
concepts}])` e cosa salvare, nello stesso modo dappertutto: la coda di `pre_turn`, `help`, gli
hook di Claude Code e Cowork, il plugin OpenCode, le istruzioni del gateway di GM, il playbook e
l'opener, in tutte le copie. Arrivano all'utente solo dopo una reinstallazione, perché gli hook
installati sono copie.

Trovato in fase 0: oltre 64 testi nuovi, i vettori del richiamo si calcolano in un thread in
background (`search.py:402`), e fino ad allora la ricerca vettoriale non restituisce niente. Il bench
aspetta il riscaldamento; un daemon appena avviato su un grafo nuovo no.

## 8. Cosa non copre

- **Il tipo giusto.** Lo sceglie il modello e a volte sbaglierà. Il rimedio è il `supersedes`, non
  un classificatore.
- **La memoria su un solo PC.** I fatti diventano più preziosi e restano in un file locale. La
  copia fuori dalla macchina è un passo operativo, non di design: va fatta prima della fase 1.
- **Le soglie.** Questo ADR dice che la soglia è assoluta, non quanto vale. Il valore viene dalla
  fase 0.

## 9. Alternative scartate

| Alternativa | Perché no |
|---|---|
| Alzare `EPISODES_PER_NODE` e `MAX_NODES` | sposta il tetto, non toglie il legame fra la vita del fatto e quella della parola |
| Migliorare `extract` (più stopword, lemmatizzazione) | i verbi italiani sono un insieme aperto; e un estrattore sul messaggio salva parole, non fatti |
| Un secondo modello che estrae i fatti dal turno | paga l'intero turno in input a ogni messaggio; quello locale gira sulla GPU che sta morendo |
| Fondere i fatti simili in automatico | è la perdita del merge (§1.3, caso 3) spostata sui fatti |
| Tenere il grafo come unità e mettere i fatti nei metadati del nodo | è il disegno di oggi |
