# ADR-014: Il loop di memoria lo fa l'ambiente, non il modello

> Status: **Proposed** — 2026-11-05. Mock sul branch `feat/hook-memoria`.
> Relates to: ADR-012 (l'IPC autenticato che l'hook usa), `gray_matter/server.py` (il ramo
> `pre_turn` del gateway, che resta il ripiego)

> [!abstract] In sintesi
> - **Cos'è.** Due hook di Claude Code fanno il lavoro di memoria che oggi chiediamo al modello:
>   uno porta il contesto prima della risposta, l'altro registra il turno quando la risposta finisce.
> - **Come funziona.** L'hook è un processo: parla col daemon di GM via IPC, come fanno la CLI e la
>   GUI, e restituisce il risultato a Claude Code come contesto. Il modello trova il ricordo già lì.
> - **A cosa serve.** Un ricordo che il modello deve chiedere non è un ricordo spontaneo, e un loop
>   che il modello deve ricordarsi di eseguire salta. Spostarlo nell'ambiente lo rende costante e
>   costa meno token.

> [!note] I riferimenti al codice si riferiscono al commit `dccc5ec`.

---

## 1. Contesto

### 1.1 Il loop dipende dalla memoria del modello

Il loop di GM chiede due azioni a ogni turno: `pre_turn` prima di rispondere, `store_turn` dopo.
Oggi le fa il modello, e le salta.

| Osservazione | Fonte |
|---|---|
| «The model calls pre_turn every turn and pulse never» | `gray_matter/server.py:403`, 2026-09-12 |
| un solo `store_turn` in una sessione di ~15 turni | `neuron_reminder_hook.py`, 2026-09-04 |
| un `pre_turn` e un `store_turn` su 9 messaggi | sessione del 2026-11-05 |
| `gray_matter_pulse` chiamato in 2 sessioni su 14 | transcript del progetto, 2026-11-05 |

### 1.2 Il flash vive dove il modello non va

Il ⚡ flashback di GM nasce solo dentro `gray_matter_pulse` (`server.py:816`). Il modello chiama
`pre_turn`, quindi il flash del gateway non scatta mai. Gli stimoli 🧠 di Neuron arrivano, perché
viaggiano sulle risposte di `pre_turn` e `store_turn`: ma solo nei turni in cui il modello le chiama.

### 1.3 Ponytail mostra il meccanismo

Ponytail è sempre attivo senza chiamare strumenti: un hook `SessionStart` inietta le regole
all'avvio e dopo ogni compattazione. Le sue regole sono testo, e il testo basta iniettarlo.
Il loop di GM è fatto di **azioni**. Un hook di tipo `command` è un programma, quindi può eseguirle.

## 2. Decisione

**D1. La lettura la fa l'hook `UserPromptSubmit`.** A ogni messaggio vero dell'utente l'hook chiede
al daemon il contesto e lo restituisce come `additionalContext`. Il modello non chiama `pre_turn`.

**D2. Il flash è parte della lettura.** Lo stesso hook chiede `forgotten(near=messaggio)` e aggiunge
un concetto dormiente, una volta per sessione per concetto. Così «ne abbiamo già parlato» scatta prima
che il modello legga il messaggio.

**D3. La KB entra come puntatore, non come estratto.** È la stessa regola del gateway
(`server.py:402`): una ricerca per nome in SQL, mai vettoriale, e una riga sola. Il contenuto costa
token e tempo, il puntatore no. Misurato: `knowledge_query` 320–350 ms, `knowledge_neighbors` 23 ms.

**D3b. Il daemon compone, l'hook consegna.** L'hook fa **una** richiesta IPC (`action: "recall"`).
Il daemon, già caldo, compone contesto, puntatore KB, suggerimento di brainstorm e flash con le
funzioni che il gateway usa per `pre_turn` (`server._hook_recall`). La logica vive in un posto solo,
e l'hook non deve importare né thread né parser.

**D4. Il salvataggio automatico non conia concetti.** L'estrazione di Neuron è euristica, e sul vivo
produce parole vuote:

```
extract("Il flash era gestito da GM in prima battuta: se parliamo di qualcosa…")
→ keywords: pulse, parliamo, qualcosa, flash, chiamare, battuta
```

Con un tetto a 1000 concetti, `parliamo` e `qualcosa` sono rumore che occupa posto. L'hook `Stop`
quindi tiene solo le parole che sono **già** nomi di nodi, e su quelle registra l'episodio.
Il modello resta l'unico che crea concetti e link tipizzati.

**D5. Il giudizio resta al modello.** `store_turn` con link tipizzati, `confirm`, `dismiss`,
`brainstorm`: servono a capire, e l'hook non capisce. L'hook toglie al modello la parte meccanica,
non quella di giudizio.

**D6. Il gateway resta il ripiego.** L'app desktop e gli altri client non hanno hook. Per loro
`pre_turn` resta lo strumento, e il flash va portato anche nel suo ramo del gateway (`server.py:902`).

## 3. Il disegno

```
messaggio dell'utente
   │
   ▼  hook UserPromptSubmit  (gray_matter/memhook.py recall)
   │    1. filtro: comandi, conferme brevi, testo vuoto → niente
   │    2. UNA richiesta IPC: {"action": "recall", "prompt", "session"}
   │         daemon (server._hook_recall):
   │           neuron.extract(messaggio)            → topic e parole chiave
   │           in parallelo:
   │             neuron.pre_turn(topic, keywords)   → contesto + stimoli 🧠
   │             _knowledge_hint (SQL)              → puntatore 📚
   │             _maybe_flash → neuron.forgotten    → flash ⚡, una volta per concetto per sessione
   │    3. budget in caratteri, poi additionalContext
   ▼
modello: risponde con il contesto già presente
   │
   ▼  hook Stop  (gray_matter/memhook.py save)
        se il modello ha già chiamato store_turn in questo turno → niente
        altrimenti extract → solo nomi di nodi esistenti → episodio
        (nel mock: dry-run, scrive cosa salverebbe in logs/memhook-save.jsonl)
```

### 3.1 Regole di costo

| Regola | Perché |
|---|---|
| nessuna chiamata se il daemon non risponde | l'hook non deve mai avviare worker: è il lavoro del daemon |
| timeout per chiamata 2,5 s, l'hook esce in silenzio | un ricordo in ritardo vale meno di un messaggio in ritardo |
| budget di 1200 caratteri (~300 token) | è il tetto di oggi di `pre_turn` più due righe |
| messaggi sotto i 12 caratteri, `ok`, `sì`, `grazie`, `/comandi` saltati | non hanno niente da richiamare |
| flash una volta per concetto per sessione | lo stesso ricordo ripetuto insegna a ignorarlo |

### 3.2 Misure sul daemon vero (2026-11-05)

**Prima versione** (quattro richieste dall'hook, KB vettoriale), fase per fase:

```
avvio python -I                 145 ms
import (json, concurrent, cli)  170 ms   ← concurrent.futures da solo 50 ms (logging, traceback)
extract                          13 ms
parallelo: pre_turn 78, forgotten 82, knowledge_query 335
processo intero                 692 ms   (785 a freddo)
```

**Seconda versione** (una richiesta, KB in SQL). I pezzi del percorso critico, misurati sul daemon:

```
import json+cli+ipcauth          82 ms
giro 2: extract 13  pre_turn 25  forgotten  8  kb-SQL 23  → ~45 ms
giro 3: extract 12  pre_turn 16  forgotten  5  kb-SQL 23  → ~33 ms
```

Stima per messaggio: 145 + 82 + 35–120 ≈ **260–350 ms**, contro 692. `pre_turn` e `forgotten`
vanno entrambi a Neuron, e il lucchetto per server li serializza: la somma, non il massimo.
La misura end-to-end aspetta un daemon con il codice del branch.

**Il pavimento è l'avvio di Python**: circa 230 ms fra interprete e import, su cui il daemon non
può niente. `-S` ne toglie circa 30, al prezzo di un `sys.path` scritto a mano: non vale ancora.

## 4. Cosa cambia per chi usa la suite

| Chi | Prima | Dopo |
|---|---|---|
| Utente | il ricordo arriva se il modello si ricorda di chiederlo | arriva sempre, mezzo secondo dopo l'invio |
| Modello | 1–2 chiamate di loop per turno, con i loro schemi | nessuna per leggere; `store_turn` solo quando c'è qualcosa da dire |
| Token | `pre_turn` + risposta, quando c'è | solo la risposta, quando c'è qualcosa di pertinente |

## 5. Piano

| Fase | Contenuto | Si dimostra con |
|---|---|---|
| **1** (mock) | `memhook.py recall` e `save` in dry-run, test unitari | misure di latenza; il log del dry-run su una settimana d'uso |
| **2** | installazione dall'installer, `SessionStart` che non chiede più `pre_turn` se l'hook è attivo | una sessione senza chiamate di loop, con contesto presente a ogni messaggio |
| **3** | `save` attivo sui nodi esistenti | episodi registrati senza nodi nuovi; nessun doppio salvataggio con `store_turn` |
| **4** | flash nel ramo `pre_turn` del gateway, per i client senza hook | l'app desktop riceve ⚡ senza `pulse` |

**Stato al 2026-11-05**, sul branch `feat/hook-memoria`:

- fase 1 fatta: `recall` attivo come una richiesta sola al daemon, `save` in dry-run;
- fase 4 fatta: `call_tool("pre_turn")` porta il flash (`test_a_gateway_pre_turn_carries_the_flash_too`);
- fasi 2 e 3 aperte: aspettano l'aggancio degli hook in `~/.claude/settings.json` e una settimana di
  log del dry-run;
- corretto lungo la strada: la pausa del flash per concetto usava come chiave il testo con il topic,
  e lo stesso concetto tornava a ogni cambio d'argomento.

## 6. Cosa non copre

- **I client senza hook.** Per loro vale la fase 4: il gateway resta il percorso.
- **La qualità del contesto.** L'hook porta quello che `pre_turn` sa trovare. Se il grafo ha salvato
  male (un nodo senza fatti, salienza 0), l'hook porta poco: il rimedio sta nel salvataggio.

## 7. Alternative scartate

| Alternativa | Perché no |
|---|---|
| Rinominare gli strumenti con il prefisso del figlio (`neuron_pre_turn`) | rende visibile il percorso, ma non cambia chi deve ricordarsi la chiamata |
| Togliere `pre_turn` e imporre `pulse` | va contro la chiamata che il modello fa davvero, e perde quello che `pre_turn` ha in più |
| Salvataggio automatico con l'estrazione così com'è | conia concetti vuoti in un grafo con il tetto |
| Iniettare il contesto anche nei sottoagenti | raddoppia il costo senza una misura che lo giustifichi |

## 8. Domande aperte

- **Il flash nel daemon condivide il passo fra sessioni.** `_last_topic` e il passo minimo
  (`flash_min_gap`) sono del processo: due sessioni aperte insieme si spostano il turno a vicenda.
  La pausa per concetto, invece, è già per sessione.
- **Topic per `pre_turn`.** Il messaggio intero o il topic dell'estrazione: va misurato quale porta
  più nodi pertinenti.
