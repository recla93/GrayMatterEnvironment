# Handoff: Convenzione CONFIRM + Diagnosi sqlite!degraded

*Sessione 2026-08-24 — ambiente Gray-Matter v1.4.0 / Neuron su opencode*

---

## Parte 1 — Convenzione di posizionamento del `confirm`

### Il problema osservato

Nel grafo Neuron la fiducia (`trust`) dei nodi chiave era rimasta a 0.0 nonostante
i richiami fossero stati determinanti più volte nella stessa sessione. Causa: il
passo `confirm(keywords)` veniva quasi sempre saltato (7 `store_turn` contro ~2
`confirm`). Meccanica del fallimento:

1. `confirm` è l'ultimo anello **condizionale** di una catena già lunga
   (`pre_turn` → lavoro → risposta → `store_turn`);
2. quando `store_turn` risponde col suo report di nodi/link creati, il turno è
   psicologicamente chiuso e la conferma resta indietro;
3. il giudizio "il contesto ha davvero influito?" viene rimosso in prudenza
   ("avrei trovato la soluzione comunque") — stima smentita dai fatti della
   sessione: senza il grafo si sarebbe ri-diagnosticato da zero il problema
   Jinja per la terza volta.

### La convenzione concordata

```
pre_turn (richiamo)
   ↓
lavoro (comandi, test, correzioni...)
   ↓
★ VALIDAZIONE EMPIRICA: test verde / errore scomparso / misura ottenuta
   ↓
confirm(keywords usati)      ← qui, confidence piena perché c'è evidenza
   ↓
risposta finale all'utente
   ↓
store_turn                   ← archiviazione del nuovo, chiude il turno
```

### Periché proprio in quel punto

- **Certezza causale**: la certezza che un concetto richiamato fosse giusto non
  arriva quando lo si applica, arriva quando la validazione lo conferma
  (es. `OK in 74s` del manifest manuale sul MoE). In quel punto confidence non è
  opinione ma fatto verificato.
- **Separazione dei gesti mentali**: `confirm` = "chiudo il ragionamento, questo
  sapeva già come si fa"; `store_turn` = "archivio ciò che è nuovo". Due rituali
  distinti non calzano uno sull'altro e non si scambiano più.
- **Coerenza verify-first**: stesso standard delle regole di sviluppo — nessuna
  conclusione senza verifica; la fiducia nella memoria merita lo stesso.

### Regola operativa

- Validazione empirica presente nel turno → `confirm` subito dopo, confidence 1.0.
- Turno puramente conversazionale, nessuna prova → si salta. Meglio poche
  conferme vere che tante vibrate: la fiducia alimentata senza prove inquina il
  ranking dei richiami futuri.

---

## Parte 2 — Diagnosi del flag `db=sqlite!degraded`

### Cosa significa

Neuron sceglie il motore in questo ordine (`neuron/src/neuron/db.py`):

1. **Turso cloud** se `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` sono impostati
   e `libsql_client` installato;
2. **Turso locale** (engine Rust via `import turso`, pyturso);
3. **sqlite3** puro come ultimo resort.

`route()` restituisce `sqlite!degraded` quando il set `DEGRADED_PATHS` non è
vuoto: cioè il processo *sa parlare Turso*, ma per almeno un file
(`graph_<ctx>.db`) la connessione è **caduta su sqlite3** tramite la "L2 guard".
Il degrado è **sticky per processo**: una volta aggiunto il path al set, ogni
`pre_turn` successivo riporta il flag fino al restart del server MCP, anche se
la gara che l'ha causato era un blip una tantum.

### La guardia L2 (causa radice) — ipotesi utente confermata

`_open_local_engine(path)` in `db.py` (~riga 427):

- tiene una cache di connessioni per path;
- su apertura fallita ritenta 3 volte (backoff 50–100 ms, ricrea la cartella
  padre tra i tentativi);
- se fallisce ancora scrive su **stderr** (che nessuno legge):
  `neuron: local Turso open failed (...) after retries — degrading to sqlite3`
  e aggiunge il path a `DEGRADED_PATHS`, aprendo quel file con sqlite3 puro.

Il commento nel codice descrive esattamente lo scenario: **"quando più
daemon/worker tengono aperto lo stesso `graph_<ctx>.db` e il worker cleara+
ricarica il grafo ad ogni chiamata, `turso.connect()` può fallire in modo
transiente sul WAL/sidecar durante un'apertura concorrente"** (bug interno L2).
Il fallback salva la scrittura (il formato su disco libSQL/sqlite è compatibile)
ma disattiva il vector-SQL nativo (`vector_distance_cos`) per quel path.

### Evidenze raccolte nell'ambiente

- Store attivo: `C:\Users\recla\AppData\Local\neuron\graphs\graph_default.db`.
- `logs\daemon.log` mostra **installazioni miste che importano lo stesso store**:
  codice da `%LOCALAPPDATA%\gray-matter\.venv\Lib\site-packages` *e* da
  `D:\Desktop\Gray Matter Enviroment\` (copia vecchia, ultima modifica 18/08 ore
  15:12 contro le 22:41 del sorgente corretto `GrayMatterEnvironment`).
  Più processi = più aperture concorrenti = la corsa L2 diventa routine.
- Presenza di altri client agent nello stesso ambiente (cartella `.claude`)
  aumenta ulteriormente la concorrenza potenziale.

### Conseguenze pratiche del degrado

Le scritture continuano (formato compatibile), ma il tier vettoriale perde il
SQL nativo e ripiega sul cosine in Python (`cli.py` segnala il tier degradato
anche per NeuRAG). Ricerca semantica funzionante ma meno efficiente e con
comportamento leggermente diverso.

### Soluzioni

**Immediate**
1. Riavviare il server MCP gray-matter (o opencode): `DEGRADED_PATHS` è
   in-memory, il restart ripristina il motore Turso locale.
2. Disciplina single-writer: un solo client alla volta sullo stesso grafo;
   chiudere le altre sessioni agent che puntano allo store.

**Strutturali (nel sorgente `neuron/src/neuron/db.py`)**
3. De-degradazione periodica: invece dello sticky-for-life, ritentare l'apertura
   Turso per i path degradati dopo N secondi (il race è transiente, il degrado
   non dovrebbe esserlo per sempre).
4. Più pazienza prima di arrendersi: aumentare tentativi/backoff del connect
   (3 tentativi in ~300 ms totali sono pochi sotto carico).
5. Serializzare la prima apertura con un lock file cross-processo attorno a
   `_open_local_engine` (single-flight sull'open, non sulle operazioni).

### Problema collaterale trovato (da sistemare a parte)

`daemon.log`: lo store contiene vettori del modello
`sentence-transformers/all-MiniLM-L6-v2` mentre il modello attivo è
`paraphrase-multilingual-MiniLM-L12-v2` (stessa dimensione 384). I vettori
salvati vengono ignorati e ricalcolati col modello attivo. Fix consigliato dal
log stesso: rigenerare con `python scripts/reembed.py` (o fissare fastembed
0.5.1), altrimenti la ricerca semantica lavora con vettori ricomputati on-the-fly.

---

---

## Parte 3 — Connettore interno "wait-list" per le connessioni

### Idea proposta

Un connettore interno che fa da varco unico verso il DB: il punto di ingresso è
uno (Gray-Matter) e GM gestisce — quando presente — concorrenza, attese ed
eventuali lock. Se il tool gira standalone non ci sono problemi (un processo
solo); se girano GM + Neuron + NeuRAG, è GM ad occuparsi di tutto.

### Valutazione

L'idea è solida e attacca la causa radice: la corsa L2 avviene sull'OPEN tra
processi, non sulle operazioni. Trasformare "fallisci-e-degrada" in "metti in
coda" è la cura giusta per un race che si risolve in millisecondi. Inoltre il
progetto già dichiara il principio *single DB writer — never a second process*
ed esiste un worker dedicato: il connettore non inventa un pattern nuovo,
formalizza quello che il codice già promette ma non impone.

### Due condizioni di validità

1. **GM protegge solo ciò che passa per GM.** Il problema attuale nasce proprio
   dal fatto che CLI standalone e server MCP aprono lo stesso file bypassandosi.
   Il connettore deve essere l'unico punto di ingresso per politica: il CLI lo
   instrada attraverso GM oppure viene rifiutato quando GM è attivo (lock
   presente → CLI si accoda o esce con messaggio chiaro).
2. **Una wait-list in-process non vede gli altri processi.** Se due istanze del
   server GM girano (es. opencode + altro agent), ognuna ha la sua coda privata.
   Per la concorrenza inter-processo serve una primitiva di OS: lock file con
   creazione atomica (O_EXCL), tipo `graph_<ctx>.open.lock`, con PID+timestamp
   dentro per ripulire i lock stantii dopo un crash; oppure named mutex Windows.

### Cosa si mette in coda (dettaglio decisivo)

La corsa è sull'apertura (init WAL/sidecar), non sullo stato stabile: una volta
aperto, WAL gestisce bene i reader concorrenti. Quindi:

- LOCK (wait-list) **solo attorno a `_open_local_engine`** → finestra di
  millisecondi;
- operazioni successive libere → throughput intatto;
- clear+reload del grafo sotto lock → secondo momento critico.

Serializzare tutto distruggerebbe le performance senza benefici.

### Forma minima di implementazione

1. Lock OS-level (lockfile o named mutex) attorno all'apertura, con timeout:
   se scade, resta il comportamento attuale (retry → degrado) come paracadute;
2. CLI instradato tramite GM quando GM gira;
3. De-degradazione periodica mantenuta come difesa in profondità.

Il codice esistente aiuta: la cache delle connessioni c'è già, manca solo il
cancelletto davanti.

---

## Parte 4 — Audit lingua: stringhe italiane dove è previsto solo inglese

### Il problema

Le interfacce esterne del progetto (descrizioni dei tool MCP, messaggi di log su
stderr, errori rivisti agli utenti/agent) devono essere in **inglese soltanto**.
L'audit ha trovato stringhe italiane in punti user-facing.

### Evidenze raccolte (file:riga, sorgente `D:\Desktop\GrayMatterEnvironment`)

**User-facing — da tradurre in inglese (priorità):**
- `gray_matter/server.py:473` e `server.py:482` — descrizioni tool MCP del
  blackboard in italiano ("Blackboard: legge key. None se assente o scaduta…",
  "cambi dalla versione since in poi, filtro per prefisso di chiave (scadute
  incluse)"). Sono le description che arrivano ai client MCP.
- `gray_matter/catalog.py:428-430` — help del comando reembed in italiano
  ("Ricalcola i vettori di TUTTI i chunk con il modello di embedding attivo…").
- `gray_matter/clients.py:641` — messaggio errore in italiano
  (`"[!!] {name} non installato: impossibile registrarlo standalone"`).
- Runtime warning su stderr (visto in `daemon.log`): *"store '…graph_default.db'
  ha vettori del modello … ma il modello attivo e' … Vettori salvati IGNORATI
  (ricalcolati col modello attivo). Rigenera: python scripts/reembed.py"* —
  individuare il punto di emissione (probabilmente `neuron/search.py` o modulo
  registry) e tradurre.

**Interno — inconsistenza minore (scelta stilistica da uniformare):**
- Commenti e docstring in italiano sparsi in `gme.py`, `state.py`, `chatgpt.py`,
  vari test (`tests/test_*.py`). Non urgente: non attraversano il confine
  esterno. Decidere una policy unica (tutto inglese consigliato) e applicarla
  in occasione dei prossimi interventi su quei file.

**Collaterale trovato durante l'audit — mojibake nei sorgenti:**
- Caratteri UTF-8 corrotti visibili in almeno due punti (es. testo reso come
  `non <?> importabile` in `gme.py:317` e `state.py`). Sintomo tipico della
  doppia codifica UTF-8 → Windows-1252 → UTF-8 (lo stesso rischio documentato
  nella regola BOM degli AGENTS.md per i file .md). Da riparare con una passata
  di normalizzazione encoding sui file colpiti.

### Regola da fissare

Tutto ciò che esce dal processo (log, stderr, descrizioni MCP, messaggi d'errore)
in inglese; i commenti interni seguono la policy del repo (consigliato inglese
uniforme). Aggiungere un check al pipeline di rilascio: grep dei marker italiani
nei soli punti user-facing prima di ogni tag.

---

*Prossimi passi suggeriti: (1) restart MCP + verifica `route()` = `turso-local`;
(2) reembed; (3) implementare connettore wait-list (Parte 3); (4) tradurre le
stringhe user-facing e riparare il mojibake (Parte 4).*
