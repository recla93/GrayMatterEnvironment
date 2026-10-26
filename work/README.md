# work/ — materiale di lavoro, non documentazione di rilascio

Qui sta ciò che serve a **chi sviluppa la suite**: audit, piani, design, storia
delle decisioni. Non è la documentazione per chi *usa* Gray Matter — quella è
in [`docs/`](../docs/) e nei quattro documenti canonici alla radice.

La distinzione è il punto: prima tutto questo stava mescolato alla radice, e
un audit di due settimane fa aveva lo stesso peso visivo del README.

| Cartella | Cosa c'è | Quanto invecchia |
|---|---|---|
| [`audit/`](audit/) | Audit dello stato del codice e le tasklist che ne derivano | Molto: fotografa un momento preciso |
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

Lo stato del progetto non sta in un documento a mano: sta nei `CHANGELOG.md`,
negli ADR di [`design/`](design/) e in `git log` (vedi `docs/PROCESS.md`). Il
vecchio compendio e `ARCHITETTURA.md` sono stati ritirati il 2026-10-26.

## Regola pratica

Un documento datato nel nome (`*-2026-07-21.md`) o che descrive un lavoro
concluso appartiene a `history/`. Se descrive come stanno le cose **oggi**, o
va aggiornato quando cambia il codice, non appartiene a `work/` affatto.
