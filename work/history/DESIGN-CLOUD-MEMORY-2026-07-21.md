# ADR-001: Memoria in cloud — GM come terzo store, config di gruppo, fallback senza GM

**Status:** Proposed (design-only, nessun codice ancora)
**Date:** 2026-07-21
**Deciders:** Claudio
**Scope:** Gray Matter + Neuron + NeuRAG (suite-level)

## Decisioni bloccate (2026-07-21, Claudio)
1. **Storage bridge = A** — tabella SQLite/Turso a 3 tier.
2. **Token UNICI** — un solo group token (sicurezza/prevenzione prima di tutto).
3. **Piggyback ON** di default + **GM come rete di sicurezza degli stimoli**: se l'LLM
   dimentica di chiamare i tool Neuron (niente piggyback), GM rilancia lo stimolo nella
   pulse — fallback delle skill contro il "tool dimenticato". **Ogni funzione ha toggle
   + tuning in GUI.**
4. **Nome 3° DB = `gm_bridges`.**
5. **Install-choice = opt-out** (installa GM salvo rifiuto, con warning-deficit).

**Principi operativi:** (i) i flussi restano **separati** (Neuron lavora sul suo, GM
orchestra Neuron+GM quando presente); (ii) **dual implementation sempre** dove ha senso
(quello che vale per Neuron vale per NeuRAG, simmetrico); (iii) ogni feature è
**toggle-abile e tunabile dalla GUI**.

> Piano strutturato per chiudere il "mega buco": in modalità gateway multi-macchina
> gli store (Neuron, NeuRAG) si sincronizzano su cloud, ma i **bridge** — l'unico
> tessuto cross-store — vivono in un JSON locale e non si sincronizzano. In più:
> gestire l'**idempotenza dei 3 tier**, le connessioni, gli **stimoli**, e un
> **fallback senza GM** dove si perdono i collegamenti ma gli stimoli restano.

---

## Contesto

Stato reale oggi (verificato dal codice):

| Componente | Storage | Cloud | Env |
|---|---|---|---|
| Neuron (memoria) | `graph_*.db` | ✅ `RemoteTursoConnection` | `TURSO_DATABASE_URL` |
| NeuRAG (knowledge) | `knowledge.db` | ✅ (port 2026-07-21) | `NEURAG_TURSO_DATABASE_URL` |
| **GM (bridge)** | **`bridges.json` locale** | ❌ **nessun path cloud** | — |

Fatti chiave:
- I **bridge** (concetto Neuron ↔ nodo NeuRAG) sono generati/letti da `gray_matter/bridges.py` su un file JSON in `~/.local/share/gray_matter/bridges.json`. Sono l'unico collegamento tra i due store → in multi-macchina non si propagano.
- Gli **stimoli** hanno il motore **dentro Neuron** (`neuron.stimulus`, T57): topic-shift, auto-linking, flash semantici, **piggyback** (E2.5) appeso alle risposte dei tool Neuron. GM non *genera* stimoli: li *orchestra* cross-store (flash rate-limitato nella pulse, bridge auto-discovery/promozione, "Potrebbe interessarti" via `knowledge_neighbors`).
- Neuron e NeuRAG usano **DB separati** (anche in cloud): GM li connette via bridge.

Forze in gioco: coerenza (un solo pattern a tier), decoupling (ogni tool gira standalone), idempotenza (re-run sicuri, scrittura condivisa concorrente), UX per tutti i tipi di utente (CLI headless + GUI), e la garanzia che **la perdita di GM non spenga gli stimoli**.

---

## Decisione (sommario)

1. **GM diventa il terzo store** con tier `cloud → sqlite locale`, riusando il facade `RemoteTursoConnection`. I bridge passano da JSON a **tabella**, con migrazione one-shot da `bridges.json`.
2. **Config di gruppo Turso:** 1 gruppo, 3 DB (`neuron`/`neurag`/`gm-bridges`), 1 group token. Env: `TURSO_DATABASE_URL`, `NEURAG_TURSO_DATABASE_URL`, `GM_TURSO_DATABASE_URL`; token condiviso via `TURSO_AUTH_TOKEN` (+ override per-componente).
3. **Flow config = CLI motore unico + GUI guscio.** `gray-matter cloud setup` fa tutto (idempotente); il pannello GUI lo invoca e ne streamma l'output. Nessun doppio flusso logico.
4. **Stimoli:** restano di Neuron (piggyback ON di default) → presenti anche senza GM. GM aggiunge solo il layer cross-store. Fallback esplicito documentato.

---

## 1. Modello a 3 tier + idempotenza (unificato sui 3 componenti)

**Rilevamento tier (identico ovunque):** env cloud presenti → `RemoteTursoConnection`; altrimenti pyturso locale → engine locale (con guardia L2); altrimenti `sqlite3`. Già in Neuron/NeuRAG; **da portare in GM** (bridge).

**Idempotenza — invarianti da rispettare in ogni componente:**
- **Schema:** `CREATE TABLE IF NOT EXISTS` + migrazioni `ALTER` guardate (colonna assente → aggiungi). Mai `DROP`.
- **Open connessione:** `_ensure_parent_dir` + open locale con retry+degrade a sqlite3 (guardia L2, già fatta in Neuron e NeuRAG). Da replicare nel tier bridge.
- **Scrittura concorrente:** upsert atomici (`INSERT ... ON CONFLICT DO UPDATE`) invece di read-modify-write in memoria — chiude il clobber tra due writer (stesso principio della `refs` table di Neuron, L1).
- **Config:** `cloud setup` re-eseguibile: rileva gruppo/DB/token esistenti e **non ricrea**; scrive le env solo se cambiano; backup `.bak` dei file toccati.
- **Freshness worker:** Neuron fa `_graphs.clear()` per rileggere il DB; il tier bridge non deve cachare in RAM in modo che due processi divergano (o legge live, o invalida dopo ogni write).

## 2. Bridge come store — schema + migrazione

Schema `bridges` (chiave naturale case-insensitive, upsert atomico):
```sql
CREATE TABLE IF NOT EXISTS bridges (
  neuron_key TEXT NOT NULL,          -- lower(neuron), per la PK
  neurag_key TEXT NOT NULL,          -- lower(neurag)
  neuron     TEXT NOT NULL,          -- display originale
  neurag     TEXT NOT NULL,
  rationale  TEXT    DEFAULT '',
  weight     REAL    NOT NULL DEFAULT 1,
  created    REAL    NOT NULL,
  last_used  REAL    NOT NULL,
  promoted   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (neuron_key, neurag_key)
);
```
Mappatura delle 4 operazioni attuali (`bridges.py`) → SQL:
- `add_bridge` → `INSERT ... ON CONFLICT(neuron_key,neurag_key) DO UPDATE SET weight=min(weight+1,cap), last_used=?, rationale=COALESCE(NULLIF(rationale,''),excluded.rationale)`. Un solo path di scrittura, idempotente e concorrente-safe.
- `bridges_for(topic)` → il match è **substring bidirezionale** (`n in t or t in n`), non uguaglianza: i bridge sono pochi (decine/centinaia) → `SELECT *` + filtro in Python (semplice, niente indici fragili). Il `_bump` dei match diventa un `UPDATE` batch.
- `decay` → `UPDATE weight = weight-? WHERE last_used < ?` poi `DELETE WHERE weight < ?`.
- `all_bridges` → `SELECT * ORDER BY weight DESC`.

**Migrazione (one-shot, idempotente):** al primo avvio con tabella vuota, se esiste `bridges.json` → importa le righe, poi rinomina `bridges.json` → `bridges.json.migrated`. Se la tabella ha già righe, non fare nulla. Path locale del DB: `~/.local/share/gray_matter/bridges.db` (parità con gli altri store); override `GRAY_MATTER_BRIDGES` continua a valere (se punta a `.json` → modalità legacy file; se `.db` → tabella).

## 3. Env / config del gruppo cloud

| Componente | DB nel gruppo | Env URL | Token |
|---|---|---|---|
| Neuron | `neuron` | `TURSO_DATABASE_URL` | `TURSO_AUTH_TOKEN` |
| NeuRAG | `neurag` | `NEURAG_TURSO_DATABASE_URL` | `NEURAG_TURSO_AUTH_TOKEN` → fallback `TURSO_AUTH_TOKEN` |
| GM bridge | `gm-bridges` | `GM_TURSO_DATABASE_URL` | `GM_TURSO_AUTH_TOKEN` → fallback `TURSO_AUTH_TOKEN` |

Tre casi che il flow deve gestire (idempotenti):
- **(a) Full group:** crea gruppo + 3 DB + group token, scrive le 3 URL + il token.
- **(b) Bring-your-own:** DB/token già esistenti → salta la creazione, cabla solo le env.
- **(c) Parziale:** solo alcuni componenti in cloud; gli altri restano locali (nessuna env → tier locale). Deve restare coerente (es. Neuron cloud + NeuRAG locale è lecito).

Dove finiscono le env: file `.env` che il daemon GM carica e propaga ai worker (i worker ereditano l'ambiente del daemon → NeuRAG/Neuron leggono le proprie). **Da verificare/implementare:** che GM propaghi `NEURAG_TURSO_*`/`GM_TURSO_*` ai worker (oggi Neuron legge il suo `.env`; serve un `.env` a livello GM o l'iniezione esplicita).

## 4. Stimoli — matrice di degradazione (fallback senza GM)

| Stimolo | Proprietario | Con GM | Senza GM (standalone) |
|---|---|---|---|
| Piggyback associativo (nudge sulle risposte tool) | **Neuron** (`stimulus.py`, E2.5) | ✅ | ✅ **preservato** (Neuron lo appende ai suoi tool) |
| `flash` / `forgotten` / spreading activation | **Neuron** (tool nativi) | ✅ | ✅ preservato (il client li chiama) |
| Rilevamento topic-shift + auto-flash | **Neuron** (stimulus) | ✅ | ✅ preservato (GM aggiunge solo il rate-limit di suite) |
| "Potrebbe interessarti" (vicini) | NeuRAG tool `knowledge_neighbors` | ✅ (GM lo chiama in pulse) | ◐ tool presente, ma l'**auto-surface** era di GM → il client deve chiamarlo |
| **Bridge cross-store** (concetto↔nodo) | **GM only** | ✅ | ❌ **perso** (inerente: no GM, no cross-store) |
| Promozione bridge → `confirm` al concetto | GM only | ✅ | ❌ perso |

**Garanzia di design:** il piggyback stimulus di Neuron è **ON di default** e non dipende da GM. Quindi "gli stimoli che oggi gestisce GM" ci sono comunque, perché il motore è in Neuron; GM li *amplifica* cross-store. Ciò che si perde senza GM è solo il **collegamento** tra i due store (bridge) e l'auto-surface dei vicini — coerente con "si perdono i collegamenti ma gli stimoli restano".

## 5. Flow di config — CLI core + GUI guscio

**Core:** `gray-matter cloud setup [--group NAME] [--components neuron,neurag,gm] [--yes]`
Passi idempotenti: (1) verifica `turso` CLI + login; (2) crea/rileva il gruppo; (3) per ogni componente richiesto crea/rileva il DB e ne prende l'URL; (4) crea/riusa un group token; (5) scrive le env nel `.env` GM (backup `.bak`, mai clobber di righe non nostre); (6) ristampa un report `doctor`-like dei tier risultanti. Nessuna credenziale a stdout.
Comandi correlati: `gray-matter cloud status` (che tier è ogni componente), `gray-matter cloud teardown` (solo de-cabla le env, non cancella i DB).

**GUI:** pannello "Turso group" nella webgui che invoca `cloud setup`/`status` e streamma l'output — stesso pattern del form Turso attuale (che delega a `neuron.connect`) e degli installer ("one logic, defined once").

## 6. Scelta all'install — GM raccomandato ma opzionale (consenso informato)

Revisione della postura precedente ("GM sempre presente"): all'install di **Neuron**
o **NeuRAG** l'utente **sceglie** se installare anche GM. Default = sì (raccomandato),
ma può rifiutare e restare standalone. Il bootstrap di GM (locale→GitHub→PyPI) diventa
quindi **opt-in guidato**, non forzato.

- **Warning mostrato** (il "deficit" = la matrice §4): senza GM perdi i **collegamenti
  cross-store** (bridge) e l'auto-surface dei vicini; **mantieni** memoria, knowledge,
  e tutti gli **stimoli nativi** (piggyback, flash, spreading). In una riga:
  *"Neuron/NeuRAG funzionano da soli; GM aggiunge la memoria che collega i due mondi.
  Consigliato installarlo."*
- **Interattivo:** prompt `Install Gray Matter (recommended)? [Y/n]` con il warning sopra.
- **Headless/scriptable:** flag/env per rispondere senza prompt — `--no-gm` / `GM_OPTIN=0`
  (declina), default = installa. Simmetrico per il caso "GM assente": si offre di
  installarlo invece di uscire, ma si può proseguire standalone.
- **Reversibile:** se poi installi GM, riprende lui il comando (registra il gateway,
  importa/crea il suo store bridge) — coerente con la GUI adattiva (G3).

Questo rende esplicito il patto: GM non è un requisito tecnico di Neuron/NeuRAG (girano
senza), è un **potenziamento raccomandato**. L'utente decide con i costi chiari davanti.

---

## Opzioni considerate

### Storage bridge — Opzione A: tabella SQLite/Turso (3 tier)
| Dimensione | Valutazione |
|---|---|
| Complessità | Media (refactor `bridges.py` + migrazione) |
| Coerenza | Alta (un solo pattern con gli store) |
| Cloud sync | ✅ nativo |
| Concorrenza | ✅ upsert atomico |

**Pro:** parità piena, riuso `RemoteTursoConnection`, chiude L1-clobber sui bridge. **Contro:** migrazione da JSON, un file `.db` in più.

### Storage bridge — Opzione B: JSON locale + tabella solo in cloud
**Pro:** meno refactor. **Contro:** due code path (JSON vs SQL) da mantenere e testare, drift garantito nel tempo.

### Config flow — CLI-core + GUI-guscio (scelto) vs doppio flusso
Doppio flusso scartato: divergenza inevitabile, l'utente headless (OpenCode/CI) resterebbe fuori. Il guscio è già la convenzione del progetto.

## Trade-off principale
A costa una migrazione una-tantum ma dà coerenza e sync; B risparmia lavoro oggi e lo ripaga in manutenzione. Per un progetto che va in cloud e multi-macchina, la coerenza vince → **si propende per A**, ma la decisione resta a valle di questo doc.

## Conseguenze
- **Più facile:** memoria cross-store condivisa tra macchine; un solo modello mentale (3 store, 3 DB, 1 gruppo); config idempotente e ripetibile; standalone chiaro (stimoli sì, collegamenti no).
- **Più difficile:** GM ora ha stato persistente da versionare/migrare; il daemon deve propagare le env ai worker; test cloud richiedono 3 DB.
- **Da rivedere:** propagazione env GM→worker; se il group token va bene o servono token per-DB; se il piggyback debba diventare configurabile per-tool.

## Action items (piano ordinato per dipendenze)
1. [ ] **Decidere A vs B** per lo storage bridge (default proposto: A).
2. [ ] Schema `bridges` + `_open`/tier in un modulo bridge (riuso `RemoteTursoConnection`; keep-in-sync marker).
3. [ ] Riscrivere le 4 op di `bridges.py` su SQL (upsert atomico) mantenendo l'API pubblica invariata (i chiamanti in `server.py` non cambiano).
4. [ ] Migrazione one-shot `bridges.json` → tabella (+ rename `.migrated`).
5. [ ] Env model: `GM_TURSO_DATABASE_URL` + fallback token; verificare/implementare propagazione daemon→worker.
6. [ ] `gray-matter cloud setup|status|teardown` (CLI core, idempotente).
7. [ ] Pannello GUI "Turso group" che invoca la CLI.
7bis. [ ] Install-choice: prompt GM raccomandato-ma-opzionale + warning-deficit (§6) negli installer Neuron/NeuRAG; flag `--no-gm`/`GM_OPTIN`; il bootstrap diventa opt-in guidato invece di forzato.
8. [ ] `doctor` esteso: mostra il tier di **tutti e 3** (incluso bridge) e se il cross-store è attivo.
9. [ ] Test: migrazione, upsert concorrente sui bridge, tier detection, fallback senza GM (stimoli presenti), e cloud reale (3 DB) via OpenCode.
10. [ ] Docs: ARCHITECTURE/DATA aggiornati (3 store, 3 DB, gruppo), TROUBLESHOOTING (tier misti).

## Domande aperte per Claudio
- **A vs B** sullo storage bridge (propendo A).
- Group token unico va bene per la tua sicurezza, o vuoi token per-DB?
- Il piggyback stimulus deve restare sempre ON, o esporre un toggle per-tool anche standalone?
- `gm-bridges` come nome del 3° DB va bene, o preferisci un naming diverso nel gruppo?
- Install-choice (§6): default **opt-out** (installa GM salvo rifiuto, come ora) o **opt-in** (chiedi sempre)? Propongo opt-out con warning chiaro — meno attrito per il caso raccomandato.
