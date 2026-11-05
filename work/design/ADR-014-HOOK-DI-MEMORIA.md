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

**D3. La KB entra come puntatore, non come estratto.** Una riga con la fonte e il punteggio, sopra
una soglia. È la stessa regola del gateway (`server.py:402`): il contenuto costa token, il puntatore no.

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
   │    2. extract(messaggio)                       → parole chiave
   │    3. in parallelo, via IPC al daemon:
   │         neuron.pre_turn(topic, keywords)       → contesto + stimoli 🧠
   │         neuron.forgotten(near=messaggio)       → flash ⚡
   │         neurag.knowledge_query(top_n=1)        → puntatore 📚 se cos ≥ soglia
   │    4. budget in caratteri, poi additionalContext
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

Tre chiamate in parallelo da un processo esterno, come farebbe l'hook:

```
giro 1: totale 354 ms -> pre_turn 229ms, forgotten 63ms, knowledge_query 352ms
giro 2: totale 320 ms -> pre_turn  59ms, forgotten 64ms, knowledge_query 320ms
```

Avvio di Python più import di `gray_matter.cli`: circa 180 ms. `extract`: 14–86 ms.
In tutto circa mezzo secondo per messaggio.

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

- **Soglia della KB.** 0,55 è una stima: va tarata sul log.
- **Topic per `pre_turn`.** Il messaggio intero o il topic dell'estrazione: va misurato quale porta
  più nodi pertinenti.
