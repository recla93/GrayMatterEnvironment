---
title: I cinque strati della memoria — mappa su Gray Matter
tags: [memoria, cervello, neuron, neurag, gray-matter, progetto]
created: 2026-11-03
status: idea — niente è implementato
---

# I cinque strati della memoria — mappa su Gray Matter

> [!abstract] In sintesi
> - **Cos'è.** Lo schema classico della memoria di un agente in cinque strati: working, episodic,
>   semantic, procedural, meta. Questa scheda lo confronta con quello che GM fa oggi.
> - **Come funziona.** Ogni strato si **legge** quando l'agente pianifica e si **scrive** dopo il
>   turno. Il meta-strato lavora fuori linea, sugli altri quattro.
> - **A cosa serve.** A vedere cosa manca e in che ordine farlo. Due cose mancano: un episodico che
>   non si cancella e uno strato procedurale.

> [!info] Da dove nasce
> Uno schema esterno («The 5 layers of agent memory») confrontato con il codice il 2026-11-03. È una
> bussola come `gray_matter/docs/CERVELLO.md`, non un piano: nessuna fase è in calendario.

---

## 1. Lo schema

| Strato | Cosa contiene | Quando si scrive | Senza di lui |
|---|---|---|---|
| 1 Working | lo stato del turno corrente | durante il turno | — |
| 2 Episodic | tracce append-only di cosa è successo | subito dopo il turno, sincrono | ogni sessione sembra la prima |
| 3 Semantic | entità con attributi tipizzati | job di estrazione sugli episodi, asincrono | le ricerche restituiscono contraddizioni |
| 4 Procedural | registro versionato di procedure, indicizzato per tipo di compito | riflessione sugli episodi passati, a lotti | l'agente non migliora mai |
| 5 Meta | controllo sugli altri quattro: archivia, deduplica, depreca, fa decadere | a orario o a soglia | lo stack marcisce |

## 2. GM oggi, strato per strato

| Strato | In GM oggi | Stato |
|---|---|---|
| 1 Working | contesto dell'LLM + blackboard (`cervello/focus`, `cervello/mode`) | c'è |
| 2 Episodic | tabella `episodes` di Neuron | **non è append-only** |
| 3 Semantic | grafo dei concetti di Neuron + NeuRAG, collegati da `promote` | c'è, senza attributi tipizzati |
| 4 Procedural | — | manca |
| 5 Meta | tick in idle del daemon, `sleep_maybe`, decadimento della salienza, `_graveyard`, dedup semantica, `bridges.decay` | a pezzi |

### 2.1 Il buco che blocca gli altri: lo strato 2

Riscontro sul codice:

- `neuron/src/neuron/models.py` — `episodes` ha chiave `(context, keyword, turn)`: un episodio è
  legato alla keyword, non al turno in cui è nato.
- `neuron/src/neuron/models.py` — `EPISODES_PER_NODE = 5`: oltre il quinto, il più vecchio viene
  cancellato.

È lo stesso punto aperto di CERVELLO.md: si dimentica per **età**, non per valore.

Gli strati 3 e 4 si costruiscono **leggendo gli episodi**. Se gli episodi spariscono, non hanno
materiale.

## 3. Il percorso

In ordine di dipendenza. Ogni passo regge da solo.

1. **Episodico append-only.** Un log dei turni che non si cancella. Il limite di cinque resta su
   **cosa si mostra** nel `pre_turn`, non su cosa si conserva. Passo piccolo, sblocca il resto.
2. **Una misura.** recall@k, MRR e costo per turno su turni reali. Il parere esterno del 26/10
   segnala che manca una misura end-to-end del beneficio. Senza, ogni strato nuovo si può solo
   sperare che aiuti.
3. **Procedurale = il subconscio.** La [SUBCONSCIO-SPEC](SUBCONSCIO-SPEC-2026-10-20.md) è già
   questo strato:
   - la ruminazione in idle è il *reflection pass*;
   - le lezioni `candidate → active → rule → retired` sono il registro versionato;
   - manca l'indice per **tipo di compito**, perché il `pre_turn` richiami la procedura giusta.
4. **Meta = il sonno di GM, esteso.** Oggi fa decadimento e promozione. Da aggiungere:
   - oblio per **valore**, dagli esiti e dai `confirm`/`dismiss`;
   - deprecazione dei fatti contraddetti.
5. **Semantico tipizzato.** Per ultimo. È lo stesso meccanismo della mappa `tipo:nome` di
   Enterprise: entità con attributi, non solo keyword.

## 4. Confini

- **Federazione ≠ strati.** I cervelli federati di Enterprise si **affiancano**. Qui si costruiscono
  gli strati **dentro** un cervello. Ogni cervello della federazione avrebbe i suoi cinque.
- **La mappa anatomica non cambia.** Neuron resta l'ippocampo, NeuRAG la neocorteccia. Lo schema
  mette lo strato semantico nel lobo temporale e GM lo divide fra i due: dove l'analogia si rompe,
  vince il codice.
- **Prima la solidità.** IDEAS.md mette davanti a tutto una suite solida. Il passo 1 è il solo da
  considerare prima di avere la misura del passo 2.
