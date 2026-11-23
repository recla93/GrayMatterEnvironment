# work/ — materiale di lavoro, non documentazione di rilascio

Qui sta ciò che serve a **chi sviluppa la suite**: audit, piani, design, storia
delle decisioni. Non è la documentazione per chi *usa* Gray Matter — quella è
in [`docs/`](../docs/) e nei quattro documenti canonici alla radice.

La distinzione è il punto: prima tutto questo stava mescolato alla radice, e
un audit di due settimane fa aveva lo stesso peso visivo del README.

| Cartella | Cosa c'è | Quanto invecchia |
|---|---|---|
| [`design/`](design/) | ADR e piani d'implementazione (registry GME, refactor install/GUI) | Poco: le decisioni restano |
| [`history/`](history/) | Audit, handoff e design conclusi, più gli screenshot | Sono già passato: si consultano, non si aggiornano |
| [`summaries/`](summaries/) | Mappe della documentazione, un file per progetto | Media: da rigenerare quando i doc si spostano |

## Cosa NON sta qui

Alla radice restano i documenti che descrivono la suite **com'è adesso**, e che
si aggiornano insieme al codice:

| Documento | Cosa fissa |
|---|---|
| [`../README.md`](../README.md) | Punto d'ingresso: cos'è, come si installa |
| [`../docs/`](../docs/) | Documentazione per chi usa la suite, architettura compresa |
| [`../INSTALLER-UX.md`](../INSTALLER-UX.md) | Spec di deploy: registrazione, path per-OS, manifest |
| [`../ENVIRONMENT.md`](../ENVIRONMENT.md) | Regole d'ambiente per lavorarci sopra |

## Dov'è lo stato dei lavori oggi

Non in un file di `work/`. Ogni piano, TODO o handoff datato invecchia in pochi
giorni e, letto dopo, racconta uno stato falso (successo il 2026-11-23: una
sessione è ripartita dal piano del 16/11 invece che dall'handoff del 19/11).

| Domanda | Dove si legge |
|---|---|
| Dove si è fermato il lavoro, cosa viene dopo | la memoria di Neuron, contesto **`backend`**: l'ultimo fatto `progress` / handoff (la riga `last:` a inizio sessione) |
| Cosa è stato fatto | `git log` e i `CHANGELOG.md` |
| Perché è fatto così | gli ADR di [`design/`](design/) |

Se il contesto attivo di Neuron è un altro (un esperimento, un altro
progetto), lo stato di GM **non emerge**: prima `switch_context('backend')`.

I piani e gli handoff datati vanno direttamente in [`history/`](history/).
Il vecchio compendio e `ARCHITETTURA.md` sono stati ritirati il 2026-10-26.

## Regola pratica

Un documento datato nel nome (`*-2026-07-21.md`) o che descrive un lavoro
concluso appartiene a `history/`. Se descrive come stanno le cose **oggi**, o
va aggiornato quando cambia il codice, non appartiene a `work/` affatto.
