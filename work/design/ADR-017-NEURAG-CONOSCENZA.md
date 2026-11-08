# ADR-017: NeuRAG tiene la conoscenza, i bridge la legano agli episodi

> Status: **Proposed** — 2026-11-08.
> Relates to: ADR-015 (Neuron salva fatti; §6 il confine con NeuRAG), ADR-016 (GM orchestra fatti;
> §5 cosa chiede a NeuRAG; D4, D5, D8), ADR-012 (cosa può indicizzare l'AI)
> Scope: **NeuRAG**, e i bridge che la legano a Neuron. GM e Neuron sono già decisi nei loro ADR.

> [!abstract] In sintesi
> - **Cos'è.** NeuRAG è la conoscenza comprovata e stabile: i documenti del progetto (il *perché*,
>   le decisioni, i processi) e i fatti di Neuron che si sono dimostrati utili. Nella mappa dei
>   cinque strati è lo strato semantico, la neocorteccia.
> - **Come funziona.** L'utente sceglie cosa entra; GM legge la conoscenza con un puntatore di una
>   riga nel richiamo e gli estratti in `pulse`. I **bridge** legano un fatto o un concetto di Neuron
>   a un nodo di NeuRAG: nascono quando qualcuno li afferma o quando un fatto viene promosso.
> - **A cosa serve.** A risparmiare: il modello trova la sezione giusta di un documento invece di
>   rileggere file interi, e dagli episodi arriva alla conoscenza che li spiega.

> [!note] I riferimenti al codice si riferiscono al branch `feat/adr-015-fatti` dopo `1a26a26`.

---

## 1. Contesto

### 1.1 Lo scopo

L'utente, 2026-11-08: NeuRAG deve avere la conoscenza e, tramite i bridge, collegarsi agli episodi.
L'obiettivo di tutta la suite è il risparmio: più si usa, più token risparmia, e i ricordi aiutano a
lavorare meglio.

| Store | Contiene | Cambia |
|---|---|---|
| Neuron (ADR-015) | episodi: fatti tipizzati, append-only | a ogni turno |
| NeuRAG | conoscenza: documenti scelti dall'utente, fatti promossi | quando cambia un documento o si promuove |
| bridge (GM) | il legame fra un fatto/concetto e un nodo | quando qualcuno lo afferma o si promuove |

### 1.2 Cosa abbiamo misurato

Sul PC di sviluppo la KB era **vuota** (1 nodo, 0 chunk, file del 2026-11-08 00:57, nessun
backup): puntatore, estratti di `pulse` e bridge non avevano niente su cui lavorare. Ingerito il
repo (solo documenti, 110 file):

| # | Misura | Valore |
|---|---|---|
| 1 | `neurag ingest` dalla CLI, con GM acceso | **rifiutato**: passava dal worker di GM e incontrava il controllo delle radici pensato per l'AI (ADR-012 F3) — corretto, §3.1 |
| 2 | Velocità dell'ingest, CPU | ~70 chunk/minuto alla prima volta; ~3000 chunk in ~45 min. Un re-ingest riusa i vettori dei chunk invariati |
| 3 | Richiamo, 8 domande in **inglese** sui documenti in inglese | hit@1 4/8, hit@5 7/8, rumore 1/40 |
| 4 | Le stesse 8 domande in **italiano**, KB a metà | hit@1 3/8, hit@5 5/8, rumore ~30% (CHANGELOG, audit, handoff) |
| 5 | 14 domande in italiano, KB intera (5838 chunk, 608 link) | hit@1 6/14, hit@5 11/14, **rumore 27%**: 12 risultati su 19 dalla storia (`work/history`), documenti vecchi in italiano che battono quelli attuali in inglese |
| 6 | Le stesse 14, tolti `work/history`, `work/audit`, `work/summaries` (4209 chunk) | **hit@1 8/14, hit@5 12/14, rumore 10%** (solo CHANGELOG); le 8 in inglese invariate |
| 7 | Il puntatore dell'hook (messaggio dell'utente, soglia 0,55) | KB a metà: 4 su 6 sbagliati sopra soglia; KB pulita: 7-8 utili su 10 |
| 8 | L'etichetta del puntatore | fino a cinque titoli concatenati, ~70 token a messaggio |
| 9 | Costo di una `knowledge_query` con `top_n=5` | ~2000 caratteri, ~500 token; ~250-350 ms |
| 10 | Bridge sul PC | 0: nascevano solo a mano, e prima di ADR-016 da un flash |
| 11 | `knowledge_neighbors("design")` | rispondeva `docs`: il trigger di un altro nodo vinceva sul nome esatto |

I punti 4-6 sono i più importanti. I documenti sono stati portati in inglese; l'utente scrive in
italiano; il modello di embedding (`paraphrase-multilingual-MiniLM-L12-v2`) è multilingue, ma fra
lingue diverse perde abbastanza da far vincere i testi nella stessa lingua della domanda anche
quando sono vecchi (la storia) o nominano tutto (i CHANGELOG). Tolta la storia, il rumore passa dal
27% al 10%.

### 1.3 Cosa funziona e resta

- **Solo documenti** di default (`.md .txt .pdf .docx`): il codice è compito di grep e Read.
- **Il nodo dalla cartella**, i chunk dai file, i vettori calcolati una volta.
- **Il controllo delle radici per l'AI** (ADR-012 F3): resta per ogni chiamata MCP.

---

## 2. Decisione

**D1. La conoscenza è datata; la storia è archivio, non rumore.** (Proposta dell'utente,
2026-11-08.) Il difetto dei documenti storici non è esserci: è che un chunk non sa di quando è, e
un documento di luglio pesa quanto uno di oggi. Quindi:

1. ogni chunk porta la **data del suo documento** (la data nel nome o nell'intestazione, se c'è;
   altrimenti l'ultima modifica), non quella dell'ingest (`created_at` oggi è questa);
2. la ricerca normale preferisce il recente: a parità di somiglianza vince il documento più nuovo;
3. ciò che è storia (per data, o perché l'utente lo dichiara) va al **livello d'archivio** che
   NeuRAG ha già (`layer` 3/4: non scandito di default, mai cancellato, contenuto intatto);
4. `knowledge_query(archive=true)` lo raggiunge: è `db.recall()`, che esiste e nessuno strumento
   espone.

Misura che lo giustifica: tolta la storia, il rumore sulle domande in italiano passa dal 27% al
10%. Con l'archivio lo stesso guadagno si ottiene senza perdere niente.

**D2. L'utente sceglie cosa entra; la sua CLI e la sua GUI non sono l'AI.** Un ingest lanciato
dall'utente non è vincolato alle radici dichiarate per l'AI. Il segnale viaggia fuori dagli
argomenti dello strumento (§3.1), quindi nessuna chiamata MCP lo può falsificare.

**D3. La query va nella lingua dei documenti.** Lo schema di `knowledge_query` lo dice al modello,
che sa tradurre. Il puntatore dell'hook, che usa il messaggio dell'utente così com'è, è un
suggerimento debole: si alza la soglia o si spegne finché un modello migliore non lo regge (D7).

**D4. Il bridge lega episodi e conoscenza.** Un capo è un concetto o l'id di un fatto (`#id`),
l'altro un nodo NeuRAG che esiste (ADR-016 D4). Nasce in due modi soli:

1. **affermato**: il modello o l'utente con `gray_matter_bridge`;
2. **per provenienza**: un fatto promosso (D5) riceve `#id ↔ nodo`.

Mostrarlo lo tiene vivo, riaffermarlo lo rafforza (ADR-016 D5).

**D5. La conoscenza nasce anche dagli episodi.** `promote` porta in NeuRAG i fatti `decision`,
`fix` e `fact` attivi, abbastanza vecchi e confermati almeno una volta (ADR-015 D8), mai `user` e
`habit`. Ogni fatto diventa un chunk con la sua provenienza (`neuron:#id`) e il suo bridge.
Resta un rapporto finché l'utente non chiede `--apply`.

**D6. La lettura costa poco.** Il richiamo di ogni messaggio porta al massimo una riga di
puntatore e due righe di bridge; gli estratti solo su richiesta (`knowledge_query`, `pulse`).
Il modello chiede 2-3 risultati, non 5: ogni risultato costa ~100 token.

**D8. Tag bilingui e gerarchici.** (Proposta dell'utente, 2026-11-08.) Ogni chunk sa la sua
lingua; un tag ha la sua controparte nell'altra lingua (`memoria` ↔ `memory`), così una domanda in
italiano arriva ai documenti in inglese per tag anche dove il vettore perde (§1.2, punti 3-6). I
tag sono **gerarchici**, a matrioska: `memoria > neuron > fatti`, e un nodo eredita i tag dei
genitori. La tabella `tags` (un atomo, un nome normalizzato) è già il posto: mancano la lingua, la
controparte e il genitore.

**D7. Il documento è l'unità.** Oggi un nodo è una cartella: un bridge verso una cartella dice
poco. Il nodo per documento (specializzazione sotto la cartella) rende i bridge e il puntatore
precisi. Si fa insieme alla prova di un modello di embedding multilingue migliore, perché
entrambi richiedono un re-ingest.

---

## 3. Piano

| Fase | Cosa | Criterio che la chiude |
|---|---|---|
| **1** ✓ | L'ingest dell'utente con GM acceso (D2); `promote` per fatti con bridge di provenienza (D5); bridge nel richiamo dell'hook (D4) | `neurag ingest <repo>` parte con GM acceso; un fatto promosso compare con il suo 🔗 nel richiamo |
| **2** (in parte) | Contenuto (D1) e lingua (D3): sulla KB di questo PC la storia è fuori (rumore 27% → 10%), lo schema di `knowledge_query` chiede la lingua dei documenti, l'etichetta del puntatore è l'ultimo titolo. Restano: i CHANGELOG fuori di default, un modo per escludere file all'ingest | sul banco italiano il rumore scende sotto il 5% e il puntatore non indica mai il documento sbagliato sopra soglia |
| **2b** ✓ | Conoscenza datata e archivio (D1) — `5e3c557`: `doc_date` su ogni chunk, il recente vince a parità, `neurag archive` / `knowledge_archive`, `knowledge_query(archive=true)` con data e [archive] nei risultati | misurato: 5882 chunk datati; storia archiviata (non cancellata): domande in italiano hit@5 12/14 e rumore 10% (era 27%), e `archive=true` ritrova `GrayMatterAudit` e i riepiloghi |
| **3** | Il documento come nodo (D7), tag bilingui e gerarchici (D8), un modello multilingue a confronto | hit@5 italiano ≥ inglese di oggi (7/8) |
| **4** | Ingest incrementale: solo i file cambiati (mtime + hash) | un re-ingest senza modifiche dura secondi |

### 3.1 Fase 1: fatta

- **Ingest dell'utente.** `neurag ingest` con GM acceso passa da `_run_via_gm` → azione IPC
  `gm-neurag` del daemon (autenticata dal token). Solo lì il daemon manda `user: true` al worker,
  fuori dagli argomenti; il worker imposta una `contextvar` (`neurag.ingest.USER_INITIATED`) e
  `ai_ingest_refusal` salta le radici, mai le chiavi. Le chiamate MCP (gateway, bridge HTTP) non
  passano mai di lì. La CLI ora inoltra anche `--code`.
- **`promote` per fatti** (`gray_matter/promote.py`, `_do_promote`): candidati dai fatti, un nodo
  per primo concetto sotto «memoria promossa», un chunk per fatto con `neuron:#id`, un bridge
  `#id ↔ nodo`. Un fatto con il suo bridge non viene ripromosso; un nodo esistente si riusa.
- **Bridge nel richiamo**: l'hook mostra fino a 2 bridge che combaciano col messaggio o con gli id
  dei fatti appena mostrati. Provato dal vivo: `adr-015 ↔ design` salvato col nome esatto, un
  refuso rifiutato, e il richiamo su «adr-015» porta la riga 🔗.
- **Nome esatto prima del trigger** in `knowledge_neighbors` (punto 11), da cui dipende D4.

---

## 4. Cosa non copre

- **Il codice nella KB**: resta fuori di default (`--code` per un albero che lo è davvero).
- **La condivisione della KB fra utenti**: ADR-013.
- **Il modello di embedding di Neuron**: cambiarlo per NeuRAG non obbliga Neuron, ma il
  puntatore e i bridge confrontano testi dei due mondi; la fase 3 lo misura.

## 5. Alternative scartate

| Alternativa | Perché no |
|---|---|
| Bridge automatici da somiglianza (flash ↔ KB) | ADR-016 D4: nascevano verso il testo della domanda e si rinforzavano da soli |
| Tradurre i documenti in italiano | la convenzione del repo è l'inglese; il problema è la query, non il documento |
| Abbassare la soglia del puntatore | più puntatori sbagliati: costano token e attenzione |
