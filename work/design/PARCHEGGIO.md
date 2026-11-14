---
title: Parcheggio — funzioni tolte dal codice, con il perché e la condizione per tornare
tags: [parcheggio, registro, scope, neuron, gray-matter]
created: 2026-11-14
status: vivo — una voce entra quando una funzione esce dal codice
---

# Parcheggio

> [!abstract] Le regole
> - **Qui, non nel codice commentato.** Il codice commentato non è testato, marcisce in silenzio
>   e costa a chi legge (anche a un LLM, a token). Il codice resta in git: ogni voce dice da quale
>   commit recuperarlo.
> - **Ogni voce ha una condizione per tornare**, misurabile. Senza quella resta qui.
> - **Si torna riscrivendo**, guardando il vecchio commit: intorno il codice sarà cambiato.

Ultimo commit che contiene tutto ciò che è elencato qui: `8a53ca3` (branch `feat/contratto-io`).

## Serve un modello che giudichi

| Funzione | Cosa faceva | Perché è ferma | Condizione per tornare |
|---|---|---|---|
| **Stimolo 🧠** (Neuron: `stimulus._stimulus_block`, `Graph.stimulus_candidates`, `spark_fact`, lo stimolo pre-caricato nel sonno `take_staged_stimulus`) | A ogni `pre_turn` aggiungeva un fatto "associato" raggiunto camminando sui link, con un bonus per i nodi dormienti o di un altro dominio | Uso 21% (il più basso, ledger 10/11); mostrava fatti fuori tema via link "same turn"; nessun modello giudica se il fatto c'entra | Link con un peso imparato dall'uso (fase 5 del PIANO) **oppure** un giudice di pertinenza gratuito; e una misura sul bench che non alzi il rumore |
| **Modalità focus + blackboard** (Neuron: `modes.focus_boost`, parametri `mode`/`focus` di `pre_turn`; GM: `state.py`, `gray_matter_state_*`, `_inject_neuron_mode`) | Il "talamo" avrebbe scritto il compito attivo sul blackboard e GM l'avrebbe passato a Neuron, che spingeva i nodi vicini al compito | Lo scrittore non è mai esistito: 0 chiavi, mai attiva su un turno vero | I turni registrati con l'esito mostrano che nelle sessioni lunghe il richiamo sbaglia argomento; il focus si ricava da un'euristica gratuita (primo messaggio, branch) e il bench lo premia |
| **Livello decisionale tipo Jev** (solo idea) | Domande tipizzate sullo stato con risposta e probabilità (routing di contesto, controllo di salvataggio, bridge) | A pagamento, solo remoto, in accesso anticipato | Un modello locale gratuito o un budget; prima la stessa interfaccia sull'embedder locale (PIANO-STRATI) |

## Tolte perché non servivano

| Funzione | Cosa faceva | Perché è uscita | Condizione per tornare |
|---|---|---|---|
| **Brainstorm** (GM: `gray_matter_brainstorm`, `_brainstorm_hint`, knob `brainstorm_hint`) e **`around`** (Neuron) | Su un problema: nodi della fascia media (né ovvi né lontani) con i loro fatti, più i chunk vicini della KB | 1 chiamata vera in 53 sessioni, 2.000 caratteri di nodi-documento e 0 fatti, niente usato; il flash ⚡ fa lo stesso lavoro senza chiamata (uso 38%) | Un caso misurato in cui il flash non basta |
| **Log dei turni `turns.jsonl`** (Neuron: `modes.append_turn`) | Topic e keyword di ogni `store_turn`, per la vecchia modalità pattern | La modalità pattern era già tolta il 13/9 (0 previsioni giuste su 155 turni); il log non aveva ora né esito, nessuno lo leggeva | Rinasce come G0 di PIANO-STRATI: turni con ora, vettore del tema ed **esito** |

## Da togliere, in un cambiamento a parte

| Funzione | Perché non ora |
|---|---|
| **Drift link** (Neuron: `form_drift_link`, `drift_links`, i filtri `link_type == "drift"` in `get_context`, il campo `Link.target_context`) | Nei grafi veri sono zero, quindi oggi non fanno nulla. Toglierli tocca il modello dei link e quattro percorsi di `get_context`: è un cambio con un suo rischio e un guadagno di sole righe. Va fatto da solo, con i suoi test. |
