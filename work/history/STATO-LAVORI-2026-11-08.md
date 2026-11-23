# Stato dei lavori — 2026-11-08

> [!abstract] In sintesi
> - **Dove siamo.** Release 1.7.0 pubblicata, verde e installata. Il memhook ora si aggancia
>   dall'install (commit `b29a186`, **non spinto**). Una modifica al richiamo è installata ma
>   **non committata**.
> - **Cosa è emerso.** Il rumore del richiamo non è un problema di soglie: la memoria salva parole,
>   non fatti. Il lavoro recente è andato quasi tutto sulla lettura.
> - **Cosa resta.** Scrivere l'ADR-015 (memoria a fatti tipizzati) rispondendo a tre domande:
>   come salvare, come estrarre senza spendere, come rendere tutto più efficiente.

> [!warning] Rischio aperto
> La memoria di GM vive **solo su questo PC**: `neuron: local`, nessun Turso cloud, i backup in
> `%LOCALAPPDATA%\GrayMatterEnvironment\backups` sullo stesso disco. Grafi 24 MB, NeuRAG 65 MB.
> La scheda video sta morendo: serve una copia fuori dalla macchina prima di tutto il resto.

---

## 1. Release e installazione

| Cosa | Stato |
|---|---|
| Versioni | gray_matter 1.7.0, neuron 6.9.0, neurag 1.7.1 (commit `672bf01`) |
| CI | CI, Release, Standalone, Mirror: tutti verdi |
| venv installato | 1.7.0 / 6.9.0 / 1.7.1, `install.ps1 -Force` del 6/11 |
| doctor | v1.7.0 awake, neuron e neurag alive, cross-store ACTIVE |
| Suite locale | neuron 434, gray_matter 676 (poi 678), neurag 423; 0 falliti |

Il primo `doctor` subito dopo l'avvio non elenca neurag: il worker sta ancora caricando.

## 2. Cosa c'è nel repo e cosa no

| Modifica | Dove | Stato |
|---|---|---|
| L'install aggancia il memhook (ADR-014 fase 2) | `executor.py`, `test_handshake.py`, CHANGELOG | commit `b29a186` su `main`, **non spinto** |
| Il richiamo usa il messaggio intero come topic | `server.py` (`_hook_recall`), `test_hook_recall.py` | **non committato**, ma installato nel venv |
| ADR-015 | — | non scritto |

Il memhook è agganciato in `~/.claude/settings.json`: `recall` su `UserPromptSubmit`, `save`
(dry-run) su `Stop`, con `-I`. Backup del vecchio `settings.json` nello scratchpad di sessione.

La modifica al richiamo non migliora la qualità (pareggio su 5 messaggi) ma toglie una chiamata
IPC. Da tenere o buttare dopo l'ADR-015.

## 3. Cosa è emerso, con le misure

### 3.1 La release 1.7.0 era finita in GM senza fatti

La sessione del 5-6/11 ha fatto 4 `store_turn` su 26 messaggi, tutti senza `episode`. Il nodo
`release` esisteva, il fatto no. Il dettaglio era solo nella memoria a file di Claude Code, che si
carica da sola e quindi vince sempre.

### 3.2 L'estrattore è una lista chiusa

`neuron extract` filtra con 472 stopword. Su 5 messaggi reali: circa 6 concetti su 25 parole, il
resto saluti, verbi e frammenti (`ciao`, `visto`, `dovremmo`, `dell`). I verbi italiani sono un
insieme aperto: la lista non migliora con l'uso.

### 3.3 Il fallback vettoriale non ha soglia assoluta

`pre_turn` tiene i nodi entro 0,20 dal migliore, qualunque sia il migliore. E il rumore di fondo
del modello (MiniLM multilingue) è alto:

| Messaggio | Primo nodo | cos |
|---|---|---|
| ricetta della carbonara con guanciale | `seed-cachato` | 0,559 |
| Esegui il commit delle modifiche… | `changelog` | 0,554 |
| Ciao Claude! … Come va la suite? | `nota-vs-contenuto` | 0,466 |
| come va la suite di test? | `test-isolation` | 0,660 |

Un messaggio fuori tema supera un abbinamento giusto. Le chiacchiere diluiscono il significato.

### 3.4 Il grafo è fatto di parole

| Misura (grafo `ai`) | Valore |
|---|---|
| Nodi | 516 |
| Nodi con almeno un fatto | 176 (34%) |
| Fatti distinti | 149 su 204 turni |
| Fatti per nodo | massimo 5, il più vecchio viene cancellato |
| Tipo «utente» o «abitudine» | non esiste |

### 3.5 Il lavoro è andato sulla lettura

Commit dal 15/10, classificati a grandi linee sul titolo: 15 lettura (richiamo, flash, KB, soglie,
bridge), 9 install/release, 4 docs, 12 altro, **2 scrittura**.

`spreading_activation` esiste (`neuron/models.py:846`) ma la usa solo lo stimolo `🧠 staged`, non
`pre_turn`.

### 3.6 Vocabolario chiuso

Il `save` del memhook tiene solo parole già nodi: su 5 messaggi, 4 non salverebbero niente. Un
filtro che decide sia cosa vedi sia cosa impari si autoalimenta (come una filter bubble). Il
richiamo invece legge soltanto, ma inclina il grafo: un nodo servito e poi riusato guadagna +0,25
di fiducia (`IMPLICIT_CONFIRM`, `neuron/server.py:1635`).

## 4. La direzione concordata

L'obiettivo di Neuron e GM: salvare fix, idee, fatti, ricordi, cose importanti, abitudini e
informazioni sull'utente, per non doverli ripetere.

1. **Il fatto è l'unità di memoria, i concetti sono l'indice.** Oggi è il contrario.
2. **Fatti tipizzati:** fix, decisione, idea, fatto, ricordo, abitudine, utente.
3. **Append-only:** i fatti si consolidano o si superano, non si cancellano.
4. **Scrittura garantita:** il fatto lo scrive il modello; l'hook `Stop` controlla che ci sia
   (`decision: block`, con `stop_hook_active` contro i cicli).
5. **Lettura per attivazione:** dai concetti del messaggio a **fatti**, non a nodi. Utente e
   abitudini sempre presenti, come `MEMORY.md`.

Il lavoro sulle soglie del richiamo resta fermo finché la scrittura non regge.

## 5. Le tre domande aperte per l'ADR-015

| Domanda | Punto di partenza |
|---|---|
| **Come salvare?** | Tabella di fatti append-only (tipo, testo, turno, sessione, `supersedes`) più un indice fatto→concetti. I concetti li sceglie il modello quando scrive il fatto: nessun estrattore sul messaggio. Migrare i 149 episodi esistenti. |
| **Come estrarre senza spendere?** | L'estrattore intelligente c'è già ed è pagato: il modello della sessione. Un fatto costa una frase in output, circa 50 token. Un secondo modello per estrarre costerebbe l'intero turno in input a ogni messaggio. Il modello locale non è un'opzione: gira sulla GPU che sta morendo. |
| **Come rendere tutto più efficiente?** | Una richiesta per lettura (c'è già, ~330 ms, di cui ~310 per la KB). Niente contesto sotto soglia. Niente fatti già mostrati nella sessione. Lo schema di `store_turn` ridotto a `{fatti: [{tipo, testo, concetti}]}`. Il promemoria "→ store_turn" tolto quando l'hook `Stop` controlla. |

**Prima di tarare qualunque cosa:** un set di valutazione di messaggi veri con i fatti attesi.
Oggi una misura su 2 campioni si è rivelata sbagliata un'ora dopo.

## 6. Prossimi passi, in ordine

1. **Copiare fuori dalla macchina** grafi, NeuRAG e `~/.claude` (memoria, hook, settings).
2. **Spingere `b29a186`** e decidere della modifica al richiamo.
3. **Scrivere l'ADR-015** sulle tre domande del §5.
4. Costruire il set di valutazione.
5. Solo dopo: implementare.
