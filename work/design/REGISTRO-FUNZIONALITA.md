---
title: Registro delle funzionalità — cosa c'è, cosa la giustifica, cosa la verifica
tags: [registro, scope, misura, verifica]
created: 2026-11-10
status: vivo — si aggiorna a ogni rilascio
---

# Registro delle funzionalità

> [!abstract] Le regole
> - **Ogni funzionalità ha una riga**: stato, il numero che la giustifica, la prova che la copre,
>   la data dell'ultima verifica d'uso.
> - **Senza numero resta sperimentale**, e una sperimentale nuova nasce spenta di default.
> - **A ogni rilascio si rilegge**: ciò che non muove un numero si spegne o si toglie.
> - **Una fase del [PIANO](PIANO-2026-11-10.md) alla volta**; le idee nuove vanno in fondo, in
>   "Dopo", non nel codice.
> - **Le prove non toccano la memoria vera**: copia del grafo o istanza isolata.

Stati: **base** (resta, giustificata) · **sperimentale** (da misurare) · **spenta** · **da rifare**.
`?` = non lo sappiamo ancora: è il buco da riempire, non un dettaglio.

## Neuron

| Funzionalità | Stato | Numero che la giustifica | Prova | Ultima verifica |
|---|---|---|---|---|
| Fatti append-only, `supersedes` (ADR-015) | base | bench v2: richiamo 55%, rumore 0,95/msg, fuori tema 0 | `neuron/bench`, suite | 10/11 dal vivo |
| Ultima parola su un argomento (`_with_newer`) | base | caso vero risolto; bench rumore +0,09, richiamo invariato | `test_fact_newer`, copia del grafo, dal vivo | 10/11 |
| Fatti già visti esclusi prima del top-3 | base | ? (nessuna misura dedicata) | `test_fact_newer` | 10/11 |
| Profilo user/habit a inizio sessione | base | ? uso nel ledger: 29% | prova dal vivo | 10/11 (inquinato da un test, corretto con #72445067) |
| Stimolo 🧠 | sperimentale | uso 21% (il più basso); rumore bench 0,80 → 0,65 dopo il fix della ripetizione | `test_stimulus_v2` | 12/11: **tolto dalla risposta di `store_turn`** (resta in `pre_turn`; bench rumore 0,95 → 1,0 perché i salvataggi non mettono più fatti in cooldown). Aperto: fatti non pertinenti via link "same turn"; cooldown azzerato a ogni riavvio |
| Gist dei fatti (riga inglese per il modello, testo intero con `pre_turn(topic="#id")`) | sperimentale | −64% token per fatto (tiktoken, 5 fatti veri); ? quota di fatti con gist | `test_search_recall` (gist) | 12/11 |
| Inglese come lingua pivot dei fatti + controllo morbido | sperimentale | bench con fatti inglesi e domande italiane: richiamo 0,545 → 0,515 (1 fatto su 33), fuori tema 4 → 1 (extract); −19% token | `test_pivot_language`, `make_en.py` | 12/11 |
| Spreading activation | sperimentale | ? non misurata da sola | `test_spreading` | ? |
| Link "same turn" automatici | sperimentale | ? — creano i percorsi dello stimolo fuori tema | ? | ? |
| Salienza, trust, decadimento, cimitero | sperimentale | ? | suite | ? |
| Contesti (grafi separati) | base | mono grafo provato e scartato (perdite > guadagni) | suite | ? |

## Gray Matter

| Funzionalità | Stato | Numero che la giustifica | Prova | Ultima verifica |
|---|---|---|---|---|
| Recall dell'hook (daemon, una richiesta) | base | costo 0,4% dei token; uso dei fatti 1–34% | `test_memhook`, 10 recall veri prima/dopo | 10/11 |
| Recall senza contorno (`_trim_for_hook`) | base | 0 fatti persi su 10, −7% caratteri | `test_memhook`, dal vivo | 10/11 |
| Controllo di salvataggio (Stop / `saved`) | base | ? effetto sui fatti salvati non misurato | `test_memhook`, dal vivo no/unknown/yes | 10/11 |
| Hook Claude Code | base | — | dal vivo (questa sessione) | 10/11 |
| Plugin OpenCode 2.x | base | — | dal vivo: recall dopo il ricaricamento, promemoria, niente loop; `smoke --only oc-turn` sull'istanza (promemoria → risposta, salvataggio nella copia) | 12/11 |
| Hook Kimi Code | sperimentale | — | comandi eseguiti con l'input di Kimi; **Kimi vero no** | 10/11 |
| Hook Codex | sperimentale | — | comandi in cmd e PowerShell; **app Codex no** (serve `/hooks`) | 10/11 |
| Flash ⚡ | sperimentale | uso 38% | ? | ? |
| Puntatore KB 📚 | sperimentale | ? uso non misurato | ? | ? |
| Bridge Neuron ↔ NeuRAG | sperimentale | 0 bridge su questo PC; automatici spenti (ADR-016 D4) | `selfcheck` | ? |
| Pulse, brainstorm | sperimentale | ? uso: rari nelle sessioni | ? | ? |
| Control center (GUI) | ? | ? | ? | ? |
| Ledger del risparmio | base (misura) | — | `test_ledger` | 10/11 |
| Istanza isolata (`tools/isolated.py`) | base (prove) | fatto di prova: 1 nella copia, 0 nella memoria vera; hook con l'env isolato → solo il daemon isolato | `isolated.py check`, `test_ipcauth` (pipe per istanza), smoke 10/10 sull'istanza | 12/11 |

## NeuRAG

| Funzionalità | Stato | Numero che la giustifica | Prova | Ultima verifica |
|---|---|---|---|---|
| Ricerca ibrida BM25 + vettori (RRF), chunk con breadcrumb | base | recall@5 0,967 sul vault di prova (31/07) | `neurag/bench` | ? sulla KB vera |
| Peso per data, archivio (ADR-017 D1) | base | rumore italiano 27% → 10% | suite | 8/11 |
| Reranker cross-encoder | spenta | recall invariato, MRR concetti peggio, 17× più lento | bench 31/07 | 31/07 |
| Ingest: cartelle → nodi, tag dai titoli | da rifare | nodi = 57 cartelle, tag rumorosi ("con", "how", "dai") | — | 10/11 |

## Mancano per tutti

- **L'A/B controfattuale**: primo risultato il 12/11 (13 compiti, una corsa): con la memoria −43%
  di chiamate di esplorazione e −26 s per compito, correttezza e token in pari. Mancano le ripetizioni
  e lo scenario fuori dal repo ([MISURA](MISURA-RISPARMIO-2026-11-10.md), livello 2).
- **Il gate prima del push** c'è dal 12/11: `python tools/gate.py && git push`.

## Dopo (idee parcheggiate, non nel codice)

Precaricamento e router fra grafi, paginazione, pesi che imparano dall'uso, bridge a strati con
keyword condivise, digestione NeuRAG in tre tempi, strato procedurale. Ordine e criteri: [PIANO](PIANO-2026-11-10.md).
