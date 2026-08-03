# Il cervello — mappa e criteri

Il sistema (Gray Matter + Neuron + NeuRAG) letto come un cervello. È una
**bussola di progetto, non un'architettura**: serve a decidere dove va una
capacità nuova, non a descrivere il codice. Per *cosa* è stato costruito e
quando, vedi l'Era 6 in `docs/EVOLUTION.it.md`; per i tool, `docs/TOOLS.md`.

I nomi anatomici sono documentazione. Nel codice non compaiono mai.

## Mappa anatomica

| Componente | Nome anatomico | Perché |
|---|---|---|
| Neuron | Ippocampo | memoria episodica, rapida, che decade; consolida verso la corteccia |
| NeuRAG | Neocorteccia (corteccia associativa) | memoria semantica, lenta, permanente, distribuita in chunk |
| Gray Matter | Talamo | hub di smistamento: tutto il traffico passa da qui; gating dell'attenzione, ciclo sonno-veglia |
| Consolidazione (`sleep_maybe`, `promote`) | Sonno ippocampo-corticale | GM promuove Neuron → NeuRAG |
| Flash | REM / sogni | associazioni libere |
| Salience / trust / sentiment | Amigdala | marcatura emotiva (valenza) dei ricordi |
| Budget proattivo | Sistemi attentivi | controllo top-down delle risorse |
| Bridges | Corpo calloso | connettività fra moduli |
| LLM (motore di ragionamento) | Corteccia prefrontale | l'unico che "pensa in tempo reale" e usa la memoria |
| Blackboard (`state`) | Corpo / interocezione | lo stato interno che tiene insieme tutto |

Il cervello reale non ha un orchestratore unico: GM è il più vicino, ma nessuna
mappa 1:1 regge fino in fondo. Dove l'analogia si rompe, vince il codice.

## I tre componenti

### Gray Matter — Talamo

Hub di smistamento: tutto il traffico passa da qui. Il blackboard vive qui, nel
DB di GM (`state.db`, separato da `bridges.db`), perché lo stato condiviso non
può stare nei depositi — sono locali a ogni archivio. La creatività
(`brainstorm`) richiede **entrambi** i depositi, quindi l'orchestrazione è il
posto naturale.

- `state_set` / `state_get` / `state_delta` — key-value con TTL e versioni.
  `state_delta` include le entry scadute: il consumatore deve poter vedere che
  una chiave è decaduta, non solo che è sparita.
- `brainstorm` — nodi lontani (Neuron) + chunk (NeuRAG), ordinati per distanza
  decrescente.

### Neuron — Ippocampo

Memoria episodica: rapida, decade, consolida verso la corteccia. Possiede la
cronologia dei turni (episode, entities, references) e il grafo dei concetti.

Non ha ricevuto **nessun tool nuovo**: focus e pattern-match sono modalità del
retrieval, che è il suo lavoro; pattern-extract nasce dalla cronologia, che è
l'unico posto che la possiede.

### NeuRAG — Neocorteccia

Memoria semantica: lenta, permanente, distribuita in chunk con citazioni. È il
deposito a cui l'ippocampo consolida.

- **La provenienza è la sua firma**: l'unico componente che risponde con
  source e citazioni — conoscenza ancorata, non associazione libera.
- **Integrità del deposito**: health, dedup, coverage.
- **Struttura**: la gerarchia godnode → fundamental → specialization, unica nel
  sistema.

Resta a `semantic` per scelta. Le modalità `esplorativa` e `profonda` sono
progettate ma non aggiunte: un deposito che risponde con provenienza non
guadagna nulla dalla serendipity finché nessuno la chiede.

## Le modalità sono stato, non superficie

La modalità di lavoro è un valore nel blackboard (`cervello/mode`), che il
retrieval di Neuron legge a ogni chiamata. I tool espliciti restano sempre
disponibili: sono operazioni, ortogonali alla modalità.

| Modalità | Strategia del retrieval |
|---|---|
| `semantic` (default) | ranking standard a similarità |
| `focus` | pesa i nodi correlati al compito corrente (`cervello/focus`) |
| `brainstorm` | nodi più distanti: novità sopra rilevanza |
| `pattern` | retrieval + "prossimo passo" se lo stato matcha uno schema |

**Tetto di quattro modalità.** Nuove solo se un caso d'uso reale le chiede. La
modalità cambia il comportamento del flusso, mai i tool.

Regola del collegamento: **Neuron non legge mai il DB di GM.** La modalità
arriva come parametro — standalone la passa il chiamante, con GM la inietta il
proxy. Il `mode` esplicito dell'agente vince sempre sull'iniezione.

## Criterio di appartenenza

Dove va una capacità nuova, in ordine:

1. **Chi ha i dati?** La capacità sta dove stanno i dati — focus e
   pattern-extract in Neuron, integrità e provenienza in NeuRAG.
2. **Tocca più di un componente?** Solo allora è orchestrazione vera, e la fa
   GM: consolidazione, pulse, brainstorm, stato condiviso.

GM copre i limiti **strutturali** (multi-componente, stato condiviso, timing),
non i limiti **di implementazione** — una feature mancante dentro la competenza
di un componente si implementa lì. "Dove non arriva Neuron" non significa
"tutto ciò che è scomodo va in GM", altrimenti GM diventa il blob.

Instradamento nel flusso: verifica → NeuRAG (provenienza); associazione →
Neuron; struttura → NeuRAG (gerarchia).

## Scartato, e perché

Un tool nuovo prima si motiva, poi si costruisce. Se un pezzo mancante è
coperto da uno esistente, si espande quello.

| Pezzo | Perché no |
|---|---|
| `body_status` (vista unica del corpo) | pura aggregazione di `status` + `knowledge_status` + `bridges`: tre chiamate che l'agente può già fare. Un tool per risparmiare un giro non si motiva |
| `evaluate` separato | la valutazione **è** l'ordinamento per distanza dentro `brainstorm`. Un file in meno |
| Quarto server | i pezzi mancanti erano modalità dei tre esistenti, non un componente nuovo |
| `sqld` (daemon Turso) | YAGNI a sessione singola: un processo proprietario per DB |
| Flash on-demand | già coperto da `brainstorm` |

## Aperto

- Il richiamo non è ancora **competitivo**: i concorrenti non si abbassano a
  vicenda al momento del recupero. Test falsificabile: aggiungere memorie
  ridondanti e misurare recall@k — se degrada, l'inibizione manca davvero.
- Ciò che si dimentica è scelto per **età**, non per valore
  (`EPISODES_PER_NODE`): la decisione di tre mesi fa esce per far posto
  all'appunto di ieri.
- Manca una misura. Finché recall@k, MRR e costo per turno non sono numeri,
  ogni modalità nuova si può solo *sperare* che aiuti.
