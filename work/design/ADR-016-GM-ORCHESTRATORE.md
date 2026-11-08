# ADR-016: Gray Matter orchestra fatti, non parole

> Status: **Proposed** — 2026-11-08.
> Relates to: ADR-015 (Neuron salva e richiama fatti), ADR-014 (gli hook di memoria), ADR-013
> (spazi e identità)
> Scope: **Gray Matter**: pulse, flash, bridge, gateway, daemon, hook. NeuRAG avrà il suo ADR; qui
> è fissato solo cosa GM le chiede (§5).

> [!abstract] In sintesi
> - **Cos'è.** GM è l'orchestratore: porta il contesto giusto al modello (pulse e hook), fa
>   affiorare idee e connessioni dimenticate (flash), collega memoria e conoscenza (bridge).
> - **Cosa non va.** Con l'ADR-015 Neuron richiama fatti, GM no. `pulse` legge ancora nomi di nodi,
>   il flash scatta su qualunque messaggio e mostra un nome senza contenuto, e i bridge nascono da
>   quel flash e si rinforzano da soli.
> - **La direzione.** Una sola via di lettura per tutti, costruita sui fatti. Il flash diventa un
>   fatto dormiente pertinente, oppure niente. Un bridge lo scrive solo chi lo afferma.

> [!note] I riferimenti al codice si riferiscono al commit `d7f1027` (branch `feat/adr-015-fatti`).

---

## 1. Contesto

### 1.1 Lo scopo di GM

| Compito | Cosa deve dare |
|---|---|
| **pulse e hook** | il contesto di un messaggio: i fatti di Neuron e la conoscenza di NeuRAG, insieme |
| **flash** | un'idea, una decisione, una connessione che il modello non ha chiesto, ma che c'entra |
| **bridge** | un legame duraturo fra un fatto o un concetto di Neuron e un nodo di NeuRAG |
| **gateway, daemon, hook** | un processo caldo che serve tutti i client, e i due momenti del turno (prima e dopo) |

### 1.2 Cosa fa oggi: le misure

Misure sul daemon installato da `d7f1027` (2026-11-08), con i grafi veri di questo PC.

| # | Difetto | Dove | Misura |
|---|---|---|---|
| 1 | `pulse` legge Neuron con `get_context`, che restituisce link e nomi di nodo | `gray_matter/server.py:684` | «stato delle fasi di ADR-015»: 10 link e 6 nomi, **zero fatti**. `pre_turn` sulla stessa domanda mette per primo il fatto giusto (`#95fad4ed`). |
| 2 | Il flash è un nome di nodo, senza fatto | `neuron/server.py`, `_tool_forgotten` | il flash su una domanda sull'ADR-015 è stato `sorgente canonica, salience=48`: un nome e un numero |
| 3 | La fascia del flash parte sotto il rumore del modello | `neuron/server.py:589`, `MID_BAND = (0.30, 0.75)` | i fuori tema arrivano a 0,46–0,56 sui nomi dei nodi (§3.3 di STATO-LAVORI): «ricetta della carbonara» → flash `sorgente canonica` |
| 4 | Se la fascia è vuota, `forgotten` ripiega sul nodo dormiente **più vecchio**, e GM lo mostra lo stesso | `_tool_forgotten`, ramo `not ranked_by_near` | «che tempo farà domani a Milano?» → `⚡ Flashback: clipboard` |
| 5 | La rete di sicurezza 🧠 rilancia lo stesso `forgotten` ogni N turni | `gray_matter/server.py:326` | stesso rumore dei punti 3 e 4 |
| 6 | Un bridge nasce da solo quando un flash coincide con un risultato della KB: concetto del flash ↔ **testo della domanda** | `gray_matter/server.py:775` | il capo NeuRAG non è un nodo della KB; il capo Neuron può essere il ripiego del punto 4. Sull'altro PC (ADR-014 D3) erano nati `flash↔audit`, `flusso↔docs`. |
| 7 | Un bridge si rinforza quando viene **mostrato**, e a 5 si «promuove» e alza la fiducia del concetto in Neuron | `bridges.py:443`, `server.py:373`, `_PROMOTE_AT = 5` | un bridge che combacia su molti topic si promuove da solo: la stessa bolla dell'ADR-015 §3.6 |
| 8 | Due vie di lettura diverse: `pulse` (get_context, KB, vicini, bridge, flash) e `pre_turn`/`recall` (fatti, puntatore KB, flash) | `server.py:658`, `server.py:1398` | il modello chiama `pulse` in 2 sessioni su 14 (ADR-014 §1.1): la via più ricca è quella che non si usa |
| 9 | Avvio a freddo: dopo l'avvio del daemon il richiamo risponde «no context» per **oltre un minuto** | `neuron/search.py`, riscaldamento in background | misurato oggi: `_recall_vectors.bin` scritto 1–2 min dopo l'avvio; dopo, i fatti arrivano in ~450 ms |
| 10 | Il vecchio `neuron_reminder_hook.py` resta registrato accanto al controllo su `Stop`, e conta come salvati anche i `store_turn` senza fatti | `executor.py`, `_REMINDER_EVENTS` | `~/.claude/settings.json` dopo l'install di oggi |

Su questo PC i bridge sono zero e la KB è quasi vuota (88 KB): la qualità dei bridge si misura
sull'altro PC.

### 1.3 Cosa funziona e resta

- Il richiamo dell'hook è **una** richiesta al daemon (ADR-014 D3b), ~450 ms a caldo.
- Il puntatore KB è vettoriale, con soglia, e non conia bridge (ADR-014 D3).
- L'hook `Stop` controlla che il turno abbia salvato i suoi fatti (ADR-015 fase 3).
- IPC autenticato con JWT sul canale dell'utente (ADR-012).

---

## 2. Decisione

**D1. Una sola via di lettura.** `pulse`, il ramo `pre_turn` del gateway e `recall` dell'hook
compongono la stessa risposta con le stesse funzioni: fatti di Neuron (`pre_turn`), puntatore o
estratti di NeuRAG, bridge, flash. `get_context` esce da `pulse`. `pulse` resta come chiamata
esplicita più ricca: con gli estratti della KB invece del solo puntatore.

**D2. Il flash è un fatto, o niente.** Un flash è un fatto attivo di tipo `idea`, `decision` o `fix`
che il messaggio non ha richiamato (sotto la soglia del richiamo o fuori dai primi 3), ma che gli è
vicino sopra un **pavimento assoluto**, e che non si vede da almeno N turni. Si mostra il testo del
fatto con il suo id, non un nome di nodo. Senza un fatto così, nessun flash: niente ripiego sul più
vecchio. Una volta per fatto per sessione, come oggi per concetto.

**D3. Via la rete di sicurezza 🧠.** Esisteva perché il modello saltava il loop. Con l'hook il
richiamo è costante (ADR-014), e la rete rilanciava solo rumore (punti 3–5).

**D4. Un bridge lo scrive solo chi lo afferma.** Il modello con `gray_matter_bridge`, o l'utente.
Niente più bridge automatici da un flash. I due capi si validano: il capo NeuRAG deve essere un
nodo che esiste nella KB, il capo Neuron un concetto o l'id di un fatto.

**D5. Un bridge si rinforza quando si usa, non quando si mostra.** Mostrarlo non conta. Conta il
`confirm` del modello, come per i fatti (ADR-015 D8). Sparisce il `confirm` automatico su Neuron
a 5 visualizzazioni.

**D6. Il daemon parte caldo.** All'avvio il worker di Neuron calcola i vettori del richiamo prima di
rispondere «pronto», usando il file `_recall_vectors.bin` quando c'è. Il primo messaggio dopo un
riavvio trova i fatti.

**D7. L'install toglie il promemoria vecchio** dove installa il memhook: il controllo su `Stop` lo
sostituisce.

**D8. L'elevazione a conoscenza parte dai fatti.** `promote` oggi promuove nodi per fiducia e link,
con i loro episodi. Diventa: fatti `decision`, `fix` e `fact`, attivi, mai superati, abbastanza
vecchi e confermati. **Mai** `user` e `habit`: sono dell'utente, e la KB si condivide (vedi la
richiesta del 2026-11-08 sui fatti personali per identità). Resta un rapporto in prova fino al
comando esplicito. Il dettaglio è nell'ADR di NeuRAG.

---

## 3. Piano

| Fase | Contenuto | Si chiude quando |
|---|---|---|
| **1** ✓ | Flash da fatti con pavimento, senza ripiego; via la rete 🧠 (D2, D3) (§3.1) | sul bench dell'ADR-015: 0 flash sui 5 fuori tema; un flash compare quando c'è un fatto dormiente vicino |
| **2** ✓ | `pulse` sulla via unica (D1) — `3849166` | `pulse` porta gli stessi fatti di `pre_turn` sulla stessa domanda; `get_context` non viene chiamato |
| **3** ✓ | Bridge solo espliciti, validati, rinforzati dall'uso (D4, D5) — `3849166`; il capo Neuron non è ancora validato | test: nessun bridge nasce da un flash; un capo NeuRAG inesistente è rifiutato; mostrarlo non cambia il peso |
| **4** ✓ | Daemon caldo all'avvio (D6) (§3.2) | il primo `recall` dopo un riavvio del daemon porta i fatti |
| **5** ✓ | L'install toglie `neuron_reminder_hook` dove c'è il memhook (D7); in più riavvia il daemon a fine install, nella cartella di GM, e nomina le app da riavviare | dopo un install, `settings.json` ha un solo hook su `Stop` e nessun promemoria — verificato dal vivo il 2026-11-08 |
| **6** ✓ | `promote` per fatti (D8), con l'ADR di NeuRAG (ADR-017 D5) | il rapporto elenca fatti, nessuno `user`/`habit` |

### 3.1 Fase 1: fatta, provata dal vivo

**Neuron.** `forgotten(facts=true, near=…)` restituisce i fatti dormienti **collegati** al topic.
Un fatto entra solo se:
- è un'idea, una decisione o un fix, oppure un fatto migrato (tipo `fact`, fonte `migration`: gli
  episodi vecchi non avevano tipo, e molti sono decisioni e fix);
- non è stato scritto negli ultimi `threshold` turni;
- il richiamo non lo mostra già per lo stesso messaggio, e non è in `exclude`;
- ha punteggio sopra `NEURON_FLASH_MIN_SCORE` = 0,40 (lo stesso punteggio del richiamo);
- **condivide un concetto** con un fatto che il richiamo mostra, oppure il messaggio nomina un suo
  concetto.

Una riga per fatto, `[tipo] testo (concetto) #id`. Senza un fatto così: `No dormant fact near …`.
Anche la modalità per concetti, con `near`, non ripiega più sui nodi più vecchi.

**GM.** `_maybe_flash` chiede `forgotten(facts=true)` con gli id già mostrati in `exclude`, e
mostra `⚡ Flash: [tipo] testo (concetto) #id`, una volta per fatto per sessione. Non accetta mai
`user` e `habit`, qualunque cosa mandi Neuron. Il `recall` dell'hook riserva prima lo spazio per KB,
brainstorm e flash, poi taglia il contesto di memoria. Via la rete di sicurezza 🧠, con le due
manopole `stimulus_safety_net`/`_gap`: un `config.json` che le nomina ancora si carica.

**Perché il legame.** Il primo pavimento, 0,45 senza legame, era pulito sul bench ma non sul grafo
vero, dove tutto parla dello stesso progetto:

| Domanda (grafo `backend`) | Flash a 0,45 senza legame | Con il legame |
|---|---|---|
| «il loader normalizza le maiuscole delle keyword?» | il fatto sul bench (0,49), **che non c'entra** | niente |
| «quale modello gratuito uso con OpenCode?» | l'architettura di mocoder (0,49), debole | niente |
| «come procede il planner di mocoder con i task?» | — | l'architettura di mocoder (#3425c02f), collegata da `mocoder` |
| carbonara, meteo di Milano | niente | niente |

Sui fatti veri un fatto non pertinente del progetto (0,49) supera uno pertinente (0,40): la
somiglianza separa il fuori tema (al massimo 0,27) ma non il rumore interno al progetto. Il legame
per concetto sì.

**Sul bench** (`results/ADR016-F1.json`): flash su 5 dei 20 messaggi, **0 sui 5 fuori tema**, tutti
collegati per concetto («14 processi python» → il fix dei worker sul WAL; `f32blob` → il fix di
pyturso; l'idea dei budget della GUI → l'idea degli eventi; gli eventi → la richiesta unica al
daemon; «GM manda gli hook» → il fix dei processi). Prima della fase 1 ogni fuori tema prendeva un
flash.

**Tre difetti trovati solo dal vivo**, ciascuno con il suo test:
1. sul grafo migrato **nessun** fatto poteva fare da flash: 17 su 17 erano `fact`;
2. GM scartava i flash `[fact]` che Neuron mandava;
3. il flash, ultimo nel testo dell'hook, veniva tagliato dal budget di 1200 caratteri.

### 3.2 Fase 4: fatta, misurata dal vivo

**Dove andava il tempo.** Un testo del richiamo fino a 128 token costa ~120 ms su questa CPU a 4
core (137 testi in 16,6 s; una frase corta ~8 ms; più thread: 15,5 s). Con la cache vuota il
richiamo aspettava tutti i testi, dei nodi e dei fatti, e il daemon caricava il modello solo al
primo messaggio: il riscaldamento di Neuron era `status`, che carica il grafo e basta.

**Cosa cambia.**
- Il daemon scalda Neuron con `forgotten(facts=true)`: modello e vettori all'avvio, senza effetti
  collaterali (`pre_turn` consumerebbe lo stimolo in attesa).
- I fatti si calcolano per primi, a blocchi da 16: diventano usabili mentre i testi dei nodi
  finiscono in background.
- `store_turn` calcola il vettore dei fatti nuovi alla scrittura (ADR-015 §3.2): il richiamo dopo
  li trova sempre.
- Al massimo 8 testi in linea (erano 64, cioè ~8 s di blocco, oltre il timeout dell'hook).

**Misura** (daemon fermato, cache `_recall_vectors.bin` tolta, grafo `backend`):

| | Prima | Dopo |
|---|---|---|
| primo richiamo con fatti dall'avvio del daemon | 44 s | **16 s** |
| richiamo a caldo, nel daemon | ~140 ms | ~100 ms |

I 16 s sono quasi tutti fissi: import di Neuron (~4 s), modello (~1,6 s), fatti (~3 s). Ora che
l'install riavvia il daemon, passano di solito prima che il client venga riaperto. Una richiesta
arrivata a worker ancora in caricamento ha atteso 5 s: dall'hook, al massimo 2,5 s e poi niente
contesto.

**I tempi a caldo** (hook completo ~500 ms): ~220 ms avvio di Python (l'interprete del venv su
Windows è un redirector, due processi), ~70 ms di import, ~140 ms nel daemon (KB 133 ms,
`pre_turn` 30 ms, in parallelo). Più di metà è l'avvio del processo dell'hook, non il lavoro.

### 3.3 Prova d'uso prima del commit (2026-11-08)

Regola da oggi: niente commit senza una prova d'uso, niente push di una release se nell'uso qualcosa
si rompe. La prova gira sull'installato, come lo usa un client:

- **un client MCP** avviato col comando registrato in `~/.claude.json`, dalla cartella del progetto
  e dalla radice del repo. Fatti salvati, richiamati, superati; fuori tema; flash; `pulse`; un
  fatto incompleto;
- **gli hook** lanciati con i comandi di `~/.claude/settings.json` e i payload di Claude Code:
  SessionStart, recall, Stop su un transcript con `store_turn(facts)` passato dal gateway.

La prima passata ha trovato quattro difetti che le suite non vedevano:

| Difetto | Correzione |
|---|---|
| la libreria MCP valida lo schema prima di Neuron: un fatto senza `concepts` faceva rifiutare tutta la chiamata | per ogni fatto è obbligatorio solo `text` |
| «committare» non nominava il concetto `commit` (desinenza di 4 lettere) | radice di 5+ lettere: qualunque desinenza; più corta: fino a 4 |
| la nota sul fatto scartato veniva tagliata dalle note sulle keyword | le note sui fatti vengono prima |
| i client avviano il server con `-m` nella cartella del progetto: dalla radice del repo GM importava il sorgente | registrazioni con `python -I -m …` |

Seconda passata: pulita. **Lacuna nota**, non un difetto di questo lavoro: un'abitudine salvata
arriva solo se la domanda le somiglia («possiamo committare?» porta l'abitudine sul commit a 0,33,
sotto la soglia). È la fase 4 dell'ADR-015: `user` e `habit` sempre presenti, all'avvio della
sessione come `MEMORY.md`.

## 4. Cosa non copre

- **I fatti personali per identità** (la richiesta del 2026-11-08): `user` e `habit` legati al
  `sub` verificato, mai mostrati ad altri, mai in uno store condiviso. Va con l'ADR-013: è il
  prossimo passo dopo queste fasi.
- **La qualità dei bridge esistenti**: si misura sull'altro PC, dove ci sono.

## 5. Cosa GM chiede a NeuRAG

| GM ha bisogno di | Perché |
|---|---|
| sapere se un nodo esiste, per nome o id | validare il capo di un bridge (D4) |
| ricevere fatti promossi con tipo, testo, concetti e provenienza (id del fatto) | l'elevazione (D8) |
