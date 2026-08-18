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
| [`../ARCHITETTURA.md`](../ARCHITETTURA.md) | Architettura dei tre componenti, tool MCP, storage |
| [`../INSTALLER-UX.md`](../INSTALLER-UX.md) | Spec di deploy: registrazione, path per-OS, manifest |
| [`../ENVIRONMENT.md`](../ENVIRONMENT.md) | Regole d'ambiente per lavorarci sopra |
| [`../GRAY-MATTER-COMPENDIUM.md`](../GRAY-MATTER-COMPENDIUM.md) | Bug, fix, stato — l'SSOT fra sessioni |

> Il compendio stava in `work/history/` pur essendo citato ovunque come fonte di
> verità corrente: è il motivo per cui il link nel README era rotto. Ora sta
> alla radice, con gli altri documenti vivi.

## Regola pratica

Un documento datato nel nome (`*-2026-07-21.md`) o che descrive un lavoro
concluso appartiene a `history/`. Se descrive come stanno le cose **oggi**, o
va aggiornato quando cambia il codice, non appartiene a `work/` affatto.
