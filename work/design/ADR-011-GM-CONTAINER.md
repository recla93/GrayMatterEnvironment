# ADR-011: Gray Matter come container dei servizi

> Status: **Proposed** — 2026-10-20
> Relates to: ADR-009 (GME Registry, contratto standalone), ADR-010 (moduli e server esterni)

> [!abstract] In sintesi
> - **Cos'è.** Un **container** possiede il ciclo di vita, le risorse e i permessi dei servizi che
>   ospita. Un **orchestratore** li avvia e smista le chiamate. Oggi Gray Matter è soprattutto il
>   secondo. Questo ADR lo porta verso il primo.
> - **Come funziona.** Ogni servizio dichiara di cosa ha bisogno: uno store, un orario, un budget, dei
>   permessi. Gray Matter glielo **inietta** all'avvio. Ogni servizio resta nel suo processo e sa ancora
>   girare da solo.
> - **A cosa serve.** Le risorse condivise si decidono in un posto solo. Cinque difetti trovati il 18 e
>   il 20 ottobre hanno la stessa forma: una risorsa condivisa gestita da più componenti, ciascuno per
>   conto suo.

> [!note] I numeri di riga si riferiscono al commit `4d7a317`.

---

## 1. Contesto

### 1.1 Le tre dimensioni di Gray Matter

L'immagine di partenza era «da due a tre dimensioni». Tradotta in assi verificabili:

| Asse | Domanda | Stato oggi |
|---|---|---|
| **1. Instradamento** | chi risponde a questa chiamata? | **completo**: dispatch per nome (`gray_matter/server.py:869`), worker per servizio (`:952`), proxy |
| **2. Tempo** | quando gira cosa? | **a pezzi**: warm-up, heartbeat (`:1708`), raccolta dei worker morti (`:1281`), `_sleep_monitor`. Il pianificatore unico è l'ADR-010 §5 |
| **3. Risorse e stato** | cosa può toccare un servizio, e come? | **vuoto**: ogni servizio apre i suoi store, con i suoi flag, lock e transazioni |

Gray Matter oggi vive quasi tutto sul primo asse. L'ADR-010 copre il secondo. Questo ADR copre il terzo.

### 1.2 La prova: cinque difetti con la stessa forma

| # | Difetto | Risorsa condivisa | Chi la gestiva | Stato |
|---|---|---|---|---|
| 1 | **modalità mista dei flag Turso**: un processo senza `multiprocess_wal` apre lo stesso file senza coordinarsi | il file di un grafo o del vault | tre aperture indipendenti | **rischio misurato** il 18/10 (stress test: il processo senza flag apriva il file), mai un danno osservato; evitato con un reinstall a client chiusi |
| 2 | **panic con più thread** sulla stessa connessione (`wal.rs:3590`) | la connessione al vault | nessuno | corretto in `af4120c` con un lock per chiamata |
| 3 | **transazioni mescolate**: il rollback di un ingest cancellava le righe di un altro, senza errori | la transazione della connessione | nessuno | corretto in `4d7a317` |
| 4 | **`decay()` una volta per processo** | il lavoro di manutenzione | ogni processo il suo | corretto in `c5c63ad` |
| 5 | **orologio di idle del daemon fermo** | il tempo di inattività | solo il ramo stdio | corretto in `c5c63ad` |

Nessuno di questi è un errore di logica dentro un servizio. Sono tutti errori di **confine**: nessun
componente aveva la responsabilità della risorsa intera.

### 1.3 La stessa decisione, scritta tre volte

Le correzioni hanno dovuto ripetere la stessa decisione in più posti, con un commento «keep-in-sync»
come unica garanzia:

| Decisione | Copie | Dove |
|---|---|---|
| flag di apertura (`TURSO_OPEN_KW`) | 3 | `neuron/src/neuron/db.py:62`, `neurag/db.py:32`, `gray_matter/bridges.py:80` |
| `PRAGMA busy_timeout=5000` | 3 | `neuron/src/neuron/db.py:628`, `neurag/db.py:165`, `gray_matter/bridges.py:321` |
| proxy thread-safe della connessione | 2, **diverse** | `neurag/db.py:68` (`_ThreadSafeConn`, con la transazione per thread), `neuron/src/neuron/db.py:559` (`_CachedLocalConn`, solo il lock per chiamata) |

L'ultima riga è il punto. Le due copie si sono già **separate**: NeuRAG ha la transazione per thread,
Neuron no. Oggi a Neuron non serve, perché le chiamate gli arrivano una alla volta dalla pipe del worker.
Ma la differenza non è scritta da nessuna parte come scelta: è solo il punto in cui si è fermata la
correzione.

---

## 2. Decisione

Gray Matter diventa il **container** dei servizi sul terzo asse. Fornisce le risorse condivise invece di
lasciarle a ciascun servizio. Lo fa con due regole che non si trattano:

1. **Iniettare, non assorbire** (§4).
2. **Processi isolati** (§5).

### 2.1 Il riferimento: il container dei servlet e Spring

- Un **load balancer** (Nginx davanti a Tomcat) smista le richieste. È il Gray Matter di oggi.
- Un **container di servlet** chiama `init()`, `service()` e `destroy()` e gestisce i thread. Il
  servlet non apre la connessione al database: la riceve dal container come `DataSource`, via JNDI, con
  pool e transazioni già decisi.
- **Spring** fa lo stesso con l'*inversione del controllo*: un bean dichiara le sue dipendenze e il
  container gliele inietta. `@Transactional` è il container che decide la transazione al posto del
  codice. È quello che `4d7a317` ha scritto a mano dentro NeuRAG.

> [!tip] Il modello
> **Inversione del controllo: il componente dichiara di cosa ha bisogno, il contenitore glielo
> fornisce.** Qui ci si arriva dal basso, da cinque difetti con la stessa forma, non da un principio.

---

## 3. Il terzo asse: cosa fornisce il container

### 3.1 Definizione

Una **risorsa del container** è una decisione che vale per più servizi e che deve avere **un solo
valore** in un dato momento sulla macchina.

### 3.2 Le risorse

| Risorsa | Contenuto | Oggi | Fase |
|---|---|---|---|
| **Profilo di apertura degli store** | flag di apertura, `busy_timeout`, politica dei thread, politica delle transazioni | in ogni servizio | **E1** (§6) |
| **Orario** | quando gira il lavoro periodico e di idle | in ogni processo | ADR-010 §5 |
| **Budget di contesto** | quanti caratteri ogni servizio aggiunge a un turno | parziale (`proactive_budget_chars`) | ADR-010 §4 |
| **Permessi** | cosa un servizio o un server esterno può toccare | assente | ADR-010 §7, poi E3 |
| **Supervisione** | riavvio, limiti, stato visibile | riavvio su richiesta senza limiti | **E2** (§5.3) |

### 3.3 Come si inietta fra processi

I servizi sono processi separati (§5), quindi non si iniettano oggetti, ma **configurazione**:

1. Gray Matter calcola il **profilo di runtime**, un JSON con versione:

   ```json
   {"v": 1,
    "store": {"open_kw": {"vfs": "experimental_win_iocp",
                          "experimental_features": "multiprocess_wal"},
              "busy_timeout_ms": 5000,
              "threads": "tx-per-thread"}}
   ```

2. Lo passa al worker alla nascita, nella variabile d'ambiente `GM_RUNTIME`. Oggi `_worker_for` avvia
   il worker con `subprocess.Popen` senza un `env` esplicito (`gray_matter/server.py:962`): è il punto
   esatto in cui aggiungerlo.
3. Il servizio lo legge una volta all'import, accanto ai suoi valori di default (§4).
4. Il servizio **riporta** il profilo effettivo nel suo `status`, così il doctor può confrontare ciò che
   Gray Matter ha deciso con ciò che il servizio sta usando davvero.

Il punto 4 rende misurabile la modalità mista: se un servizio usa un profilo diverso da quello deciso,
il doctor lo dice per nome.

---

## 4. Iniettare, non assorbire

### 4.1 La regola

**Un servizio accetta le risorse dal container, ma sa procurarsele da solo quando gira standalone.**

È la regola di Spring: un bean resta un oggetto Java normale, testabile senza container. Qui vuol dire
che il contratto standalone dell'ADR-009 resta intatto. Neuron e NeuRAG si installano e girano senza
Gray Matter, esattamente come oggi.

### 4.2 Come si traduce

| Risorsa | Standalone | Sotto Gray Matter |
|---|---|---|
| profilo di apertura | i default del servizio (`TURSO_OPEN_KW` attuale) | `GM_RUNTIME.store` |
| orario | il servizio non fa lavoro periodico, o lo fa nel suo processo | il pianificatore del daemon |
| budget | nessuno: il servizio risponde solo a ciò che gli si chiede | l'arbitro dell'ADR-010 |
| supervisione | nessuna: è il client a lanciare il servizio | Gray Matter |

### 4.3 Quello che resta duplicato, onestamente

I **default** restano tre copie, una per servizio, perché un servizio standalone non può importarli da
un pacchetto vicino. Cambia però cosa decidono:
- oggi le tre copie sono **la** decisione, e devono coincidere per non creare la modalità mista;
- dopo E1, sotto Gray Matter decide il profilo iniettato, e le tre copie valgono solo standalone, dove
  ogni servizio è l'unico ad aprire i suoi file.

La duplicazione resta, il rischio no.

### 4.4 Come si verifica

Il workflow **Standalone** della CI installa e prova ogni peer da solo a ogni push su `main`. È già la
prova automatica che l'iniezione non abbia assorbito niente: se un peer smette di funzionare senza
`GM_RUNTIME`, quel workflow diventa rosso.

---

## 5. Isolamento dei processi

### 5.1 La regola

**Container vuol dire controllo, non convivenza nella stessa memoria.** Ogni servizio resta nel suo
processo, come oggi.

### 5.2 La prova che l'isolamento serve

Il 20/10 pyturso è andato in panic due volte dentro il worker di NeuRAG (`wal.rs:3590`,
`pager.rs:3755`). È morto **solo** quel worker. Il daemon e il worker di Neuron sono rimasti vivi, e la
chiamata successiva ha rilanciato NeuRAG. Con i servizi nello stesso processo del daemon, quel panic
avrebbe spento tutta la suite e tutti i client collegati.

È il modello di Kubernetes: il cluster decide tutto, ma ogni container gira nel suo processo e il suo
crash non trascina gli altri.

### 5.3 La supervisione che manca

Oggi un worker morto viene rilanciato alla chiamata successiva (`_worker_for`, `gray_matter/server.py:952`),
**senza limiti**. Un servizio che va in crash a ogni avvio viene rilanciato a ogni chiamata, e il
client vede solo errori diversi.

| Regola | Riferimento |
|---|---|
| contatore dei crash per servizio, visibile nel doctor | — |
| dopo 3 crash in 5 minuti, il servizio passa a `failed` e smette di essere rilanciato | il `CrashLoopBackOff` di Kubernetes |
| un servizio `failed` torna attivo con `gray-matter start` o dalla GUI | — |
| un crash con una riga `panicked at` nel log viene riportato nel doctor con quella riga | il caso del 20/10, trovato solo leggendo `daemon.log` |
| i job di un servizio morto risultano `lost`, non spariscono | il 20/10 lo status diceva «No such job» |

---

## 6. Primo esperimento: E1, il profilo di apertura iniettato

### 6.1 Perché questo per primo

- È **piccolo**: una variabile d'ambiente, tre letture, una riga nello `status`.
- Toglie un **rischio reale**: il difetto 1 del §1.2.
- È **reversibile**: senza `GM_RUNTIME` tutto si comporta come oggi.
- **Mette alla prova le due regole** in un colpo: iniettare senza assorbire (lo Standalone deve restare
  verde) e processi isolati (l'iniezione passa da un confine di processo).

### 6.2 Cosa cambia

| Dove | Cambio |
|---|---|
| Gray Matter | un punto solo calcola il profilo: oggi uguale ai default, con il knob `turso_multiprocess` (default acceso su Windows) |
| `_worker_for` | `subprocess.Popen(..., env={**os.environ, "GM_RUNTIME": json.dumps(profilo)})` |
| `neuron/db.py`, `neurag/db.py` | `TURSO_OPEN_KW` e `busy_timeout` vengono dal profilo se c'è, altrimenti dai default |
| `gray_matter/bridges.py` | legge lo stesso profilo dal suo processo, senza variabile d'ambiente |
| `status` di Neuron e NeuRAG | una riga con il profilo effettivo |
| doctor | confronta il profilo deciso con quelli riportati dai worker |

**Una conseguenza da notare.** Il 18/10 avevo scartato un knob per spegnere il multiprocesso: con tre
punti di decisione, un knob impostato in un processo solo avrebbe **creato** la modalità mista. Con
un'unica fonte il knob diventa sicuro, perché vale per tutti i processi o per nessuno.

### 6.3 Criteri d'uscita

1. Un test avvia un worker con `GM_RUNTIME` e verifica nel suo `status` il profilo ricevuto.
2. Un test senza `GM_RUNTIME` verifica i default, cioè il comportamento standalone.
3. Cambiare il knob cambia il profilo di **tutti e tre** i punti di apertura dopo un riavvio, e il
   doctor lo mostra.
4. Un worker avviato con un profilo diverso da quello deciso fa apparire una riga rossa nel doctor, con
   il nome del servizio.
5. CI, Mirror e Standalone verdi.

### 6.4 Gli esperimenti successivi

| Esperimento | Cosa | Dipende da |
|---|---|---|
| **E2** | supervisione: contatore crash, `failed`, job `lost`, panic nel doctor (§5.3) | niente |
| **E3** | permessi: un servizio dichiara gli store che apre, e il container rifiuta gli altri | E1 |
| **E4** | la politica delle transazioni nel profilo: Neuron e NeuRAG con la stessa, decisa una volta | E1 |

---

## 7. Cosa questa decisione non fa

- **Non** porta il codice di Neuron e NeuRAG dentro Gray Matter. I pacchetti restano separati.
- **Non** mette i servizi nello stesso processo.
- **Non** rende Gray Matter obbligatorio: lo standalone resta un percorso di prima classe.
- **Non** sostituisce l'ADR-010: lo completa. L'ADR-010 copre il tempo e le estensioni, questo le
  risorse.

---

## 8. Conseguenze

**Positive**
- Una decisione su una risorsa condivisa si prende una volta, e il doctor può verificare che tutti la
  stiano usando.
- La modalità mista diventa misurabile e, sotto Gray Matter, impossibile per costruzione.
- I crash diventano visibili e limitati, invece di essere rilanciati in silenzio.

**Negative**
- Più cose passano dal centro: un difetto nel calcolo del profilo colpisce tutti i servizi insieme.
  Mitigazione: il profilo è un JSON piccolo e con versione, riportato da ogni servizio e controllato dal
  doctor.
- Due percorsi di configurazione, iniettato e default, da tenere entrambi provati. Mitigazione: il
  workflow Standalone per i default, i test di E1 per l'iniezione.

---

## 9. Alternative scartate

| Alternativa | Perché no |
|---|---|
| Restare orchestratore e continuare con i «keep-in-sync» | il §1.3 mostra che le copie si separano già |
| Un pacchetto comune `gm-runtime` importato da tutti | viola il contratto standalone: un peer dipenderebbe da un pacchetto della suite |
| Servizi nello stesso processo del daemon | un panic nativo spegnerebbe tutto (§5.2) |
| Un servizio di database centrale (per esempio `sqld`) | sposta il problema in un processo in più da installare e supervisionare; da rivalutare se il WAL multiprocesso, ancora `experimental`, non regge |

---

## 10. Domande aperte

1. **Il profilo cambia a caldo?** Oggi no: si legge all'import. Cambiare un flag richiede di riavviare i
   worker. Basta, o serve un messaggio di ricarica?
2. **I client senza Gray Matter davanti.** Un client che lancia Neuron direttamente, mentre Gray Matter
   gira, apre gli stessi file con i default. Coincidono con il profilo solo finché nessuno cambia il
   knob. Va scritto nel doctor? Va impedito?
3. **Neuron e la transazione per thread.** Oggi non serve, perché le chiamate arrivano una alla volta.
   Se un modulo dell'ADR-010 iniziasse a usare Neuron da un thread in background, servirebbe subito. È
   un motivo per anticipare E4?
4. **Il nome.** «Container» richiama Docker. Va bene, o crea aspettative sbagliate su immagini e
   isolamento a livello di sistema operativo?

---

## 11. Sintesi in sette righe

1. Gray Matter oggi è completo sull'instradamento, a pezzi sul tempo, assente sulle risorse.
2. Cinque difetti in due giorni hanno la stessa forma: una risorsa condivisa senza un responsabile.
3. Il container fornisce le risorse condivise; i servizi le dichiarano.
4. Iniettare, non assorbire: ogni servizio sa ancora girare da solo, e lo Standalone in CI lo prova.
5. Processi isolati: il panic del 20/10 ha ucciso un worker solo, ed è così che deve restare.
6. Il primo passo è il profilo di apertura iniettato con `GM_RUNTIME`: piccolo, reversibile, misurabile.
7. Con una fonte sola, un knob per il multiprocesso diventa sicuro invece che pericoloso.
