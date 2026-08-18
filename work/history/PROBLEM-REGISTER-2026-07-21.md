# Problem register — pre-release audit (2026-07-21)

> Inventario verificato dal codice/test, non dai doc vecchi. Tier di test usato
> in sandbox: **sqlite/TF-IDF** (pyturso non installabile qui). Il verdetto sul
> **tier Turso** — quello che conta per L2 e vector SQL — va preso **in locale**.
> SSOT di riferimento: `GRAY-MATTER-COMPENDIUM.md` (più aggiornato di `AUDIT-PERFORMANCE.md`).

Versioni target decise: **Neuron 6.0.0 · NeuRAG 1.0.0 · Gray Matter 1.0.0** (prima release).

---

## Aggiornamento 2026-07-21 (polish + decoupling)

Sintesi dello stato dopo l'intervento. L'inventario originale (sezioni A–E sotto)
resta come traccia; qui il delta.

### ✅ Verifica locale (OpenCode, tier reale) — 2026-07-21
Girato il test plan (`docs/archive/TEST-OPENCODE-2026-07-21.md`) su Windows/Py3.14 con deps reali.
- **Versioni runtime confermate live:** `6.0.0 1.0.0 1.0.0`; `gray-matter` ora riporta v1.0.0.
- **Suite:** Neuron 272 · NeuRAG 36 · GM 38 (in locale gli ex-skip mcp/pyturso passano).
- **Bug reale trovato sul tier pyturso (invisibile in sandbox):** `Neurag.delete_node()`
  andava in **stack overflow C** di pyturso 0.6.1 su `DELETE FROM nodes` con
  `foreign_keys=ON` + FK CASCADE. Fix OpenCode: `PRAGMA foreign_keys=OFF` attorno
  al loop di delete manuale. **Irrobustito** (io) con try/finally per ripristinare
  sempre le FK. `test_cascade_delete_node` verde.
- **search_with_links:** il mio `assert == 2` era tier-fragile (valido solo sul
  lessicale; il vettoriale fastembed ritorna 3). Reso **tier-agnostico** (`>=2` +
  enrichment). Ora verde su entrambi i tier.
- **Architettura chiarita da Claudio:** Neuron e NeuRAG hanno **DB separati**
  (`graph_*.db` vs `knowledge.db`); è GM a connetterli via bridge — anche su cloud
  sono due DB distinti. **Fix conseguente:** il port cloud leggeva `TURSO_DATABASE_URL`
  (la env di Neuron) → collisione sulla tabella `nodes`. Ora NeuRAG legge
  `NEURAG_TURSO_DATABASE_URL` (DB proprio); token condivisibile via
  `NEURAG_TURSO_AUTH_TOKEN` con fallback a `TURSO_AUTH_TOKEN`.
- **Non eseguito:** Turso cloud (no credenziali) e L2 sotto concorrenza reale
  (serve 2 client Desktop+Cowork simultanei) — restano da verificare in locale.

### ✅ Risolto (file, tier sqlite verde)
- **A1/A2/A5 — Versioni:** allineate a 6.0.0 / 1.0.0 / 1.0.0 su pyproject,
  `__version__` (inclusi i due interni stantìi di NeuRAG e GM), badge README,
  tabelle OVERVIEW/CONFIGURATION, voce CHANGELOG per repo. Nota drift in EVOLUTION → risolta.
- **C1 — INSTALL:** creati `docs/INSTALL.md` + `.it` → link rotti di OVERVIEW risolti (0 link rotti).
- **C2 — tool `status`:** aggiunto a `docs/TOOLS.md`/`.it`.
- **C3 — "32→33 tool":** corretto in TECHNOLOGY/EVOLUTION (EN+IT).
- **C4 — CLI `console`/`tunnel`:** FALSO POSITIVO — erano già documentati. Nessuna modifica.
- **E1 — marker COMPENDIUM:** B1–B3 (trust) ⬜→✅ con riferimento a `test_trust.py`; nota su L1.
- **D3 — test GM:** i 2 test mcp ora fanno `importorskip` (skip pulito, non fail).
- **B2 — search_with_links:** test corretto al contratto reale enrich-only (assert 2); design annotato come tech-debt; metodo non esposto come tool.
- **Suite (sqlite):** Neuron 270 · NeuRAG 30 · GM 35 — **0 fallimenti**, 5 skip puliti.

### ✅ Nuovo — Decoupling NeuRAG (wheel)
- `Neurag/vendor/` con recipe di build; `Neurag/.github/workflows/release.yml`
  (job `build-pyturso-win` 3.10–3.14); commento pyproject aggiornato (non più
  "fonte unica Neuron/vendor").

### ✅ Nuovo — Cloud Turso in NeuRAG (simmetria core)
- Risolta l'asimmetria: `Neurag/db.py` ora ha il tier **cloud** (`TURSO_DATABASE_URL`/
  `TURSO_AUTH_TOKEN` → `RemoteTursoConnection` su libsql-client), come Neuron.
  Facade adattato al pattern NeuRAG (righe name-accessible via `_CompatRow`),
  pragmas no-op remote, batch writes. Extra `[cloud]` = `libsql-client>=0.3.1`
  (stesso pin di Neuron). Guardia L2 `_open_local_turso` anche qui.
- Simmetria verificata: entrambi REMOTE_TURSO + libsql + degrade se manca il
  cloud extra + L2 guard; pin pyturso 0.6.1 e libsql-client 0.3.1 allineati.
- Test: `test_cloud_turso.py` (4, con client libsql finto). Sweep: Neuron 272 ·
  NeuRAG 34 · GM 35, 0 fail. **Path cloud reale da verificare in locale** (Turso live).

### ✅ Nuovo — Flow installer (no dead-end)
- Neuron `install.sh`/`.ps1`: catena bootstrap GM (locale→GitHub release→PyPI→EXIT), come NeuRAG.
- Canonico `gray_matter/install.sh`/`.ps1`: venv, pip-upgrade, GM core e peer ora
  con fallback; i peer degradano con WARNING invece di abortire. EXIT solo su 3
  punti irrecuperabili (no Python, no venv, GM core non installabile).

### ◐ D1/D2 — Toolchain test (documentato, azione locale)
- `vendor/dev` manca `exceptiongroup`/`tomli` per 3.10, e case-sensitivity NeuRAG
  su CI Linux: fix documentato in `ENVIRONMENT.md §2` (comando + `pip install -e .`). Da eseguire in locale.

### ⬜ Resta aperto (bloccante release, come da piano)
- **B1 (L2) — `store_turn → open: NotFound`** su Turso condiviso: ◐ **mitigato
  2026-07-21**. Repro sandbox: il sotto-caso "dir nuova mancante" è già coperto
  da `_ensure_parent_dir`. Aggiunta guardia `db._open_local_engine` (retry 3× +
  degradazione a sqlite3 sullo stesso file) + test `test_l2_open_guard.py` (2).
  Residuo: race multi-processo WAL/sidecar → **verdetto finale sul daemon vivo
  con pyturso reale** (in locale). Suite Neuron: 272 verdi.
- **Build wheel NeuRAG:** da eseguire (compiler locale o CI su tag).
- **Bootstrap remoto installer (B/C):** si attiva solo dopo publish/push di GM
  (oggi nulla su PyPI/GitHub). Path locale già funzionante. `.ps1` da testare in locale.
- **Git & release:** commit/tag/push = ultimo step, dopo il verdetto Turso.

---

## A. Stato release & versioning (bloccante)

| # | Problema | Dove | Stato attuale |
|---|---|---|---|
| A1 | Bump versioni target non applicato | tutti | codice: Neuron 5.6.0, NeuRAG 0.3.0, GM 0.2.0 → da portare a 6.0.0 / 1.0.0 / 1.0.0 |
| A2 | `__version__.py` disallineato dal pyproject | `gray_matter/__version__.py` | dice 0.1.0, pyproject/CHANGELOG dicono 0.2.0. `gray_matter_status` riporta la versione sbagliata |
| A3 | Nessun tag git per le versioni correnti | Neuron / NeuRAG / GM | Neuron ultimo tag `v5.4.2` (manca v5.5.x e v5.6.0); NeuRAG e GM **zero tag** |
| A4 | Niente pushato su origin | tutti | Neuron 11 commit avanti, GM 5, NeuRAG 2; working tree sporchi (docs/, LICENSE, install.cmd/command non tracciati) |
| A5 | Badge versione README stantii | 3 README | Neuron 5.4.0 · NeuRAG 0.2.0 · GM 0.1.0 |

## B. Correttezza & integrità test (bloccante)

| # | Problema | Dove | Severità |
|---|---|---|---|
| B1 | **L2 — `store_turn → open: NotFound`** | `gray_matter/_worker.py` + Neuron su Turso condiviso | **ALTA, aperto**. Race: più worker GM fanno `_graphs.clear()`+reload sullo stesso `graph_*.db` → conflitto WAL/sidecar. Si manifesta **solo su Turso condiviso** nel turno che fa scattare lo switch di context; **mai** su sqlite/one-shot. Nessun test automatico lo copre oggi |
| B2 | `search_with_links`: test rotto + divergenza design/codice + metodo non esposto | `Neurag/db.py`, `Neurag/tests/test_node_links.py`, `DESIGN-CROSSLINKS.md §6` | media. Test attende 3, reale 2 (corretto). Design = espansione via link; impl = solo enrich. Non è wired a nessun tool MCP. **Decisione in sospeso** |
| B3 | Verdetto test solo su tier sqlite | tutti | I run in sandbox (Neuron 270✅, NeuRAG 29✅/1 rotto, GM 35✅) sono primo filtro. Turso tier (L2, `test_vector_sql`) va girato in locale con pyturso + credenziali |

## C. Allineamento documentazione

| # | Problema | Dove |
|---|---|---|
| C1 | `INSTALL.md` / `INSTALL.it.md` mancanti ma linkati (link rotti) | `docs/OVERVIEW.md`, `docs/OVERVIEW.it.md`. INSTALL è file richiesto da DOCS-GUIDELINES |
| C2 | Tool Neuron `status` non documentato | `docs/TOOLS.md` (22 tool documentati vs 23 reali) |
| C3 | "32 tools" errato → reale **33** (23 Neuron + 10 NeuRAG) | `docs/TECHNOLOGY.md`, `docs/EVOLUTION.md` (cascata da C2) |
| C4 | CLI Neuron `console` e `tunnel` non documentati | `docs/CLI.md` |
| C5 | Struttura doc diverge dalle DOCS-GUIDELINES | guidelines = docs/ per-repo (8 file); reale = `docs/` unificato alla root + stub per-repo che linkano. Scelta coerente ma da riconciliare nelle guidelines |

## D. Toolchain test & CI

| # | Problema | Dove |
|---|---|---|
| D1 | `vendor/dev` incompleto per Python 3.10 | `Neuron/vendor/dev/` manca `exceptiongroup` e `tomli` (richiesti da ENVIRONMENT.md); pytest offline non parte su 3.10 senza shim. `gray_matter` e `Neurag` non hanno un proprio `vendor/dev` |
| D2 | Case-sensitivity nome pacchetto NeuRAG | cartella `Neurag` vs import `neurag` → collection test fallisce su Linux/CI senza `pip install -e .` o rename |
| D3 | 2 test GM falliscono invece di skippare senza `mcp` | `gray_matter/tests/test_gateway_flip.py`, `test_installer.py` → dovrebbero usare `importorskip` |
| D4 | `AUDIT-PERFORMANCE.md` stantìo | lista F4 e L1 come aperti benché fatti; usare il COMPENDIUM come SSOT |

## E. Incoerenze interne alla SSOT

| # | Problema | Dove |
|---|---|---|
| E1 | Marker di stato contraddittori | `GRAY-MATTER-COMPENDIUM.md`: Fase B (B1–B3 trust) e L1 marcati ⬜ nelle tabelle, ma TODO-3 + sezione "Fix" + test presenti e verdi (`test_trust.py`, `test_refs_table.py`) mostrano che sono fatti. Allineare i marker |

---

## Performance
Non misurabile in sandbox (serve fastembed + Turso reali). Baseline documentati:
primo `pulse` cold 2–5s · warm 1–3s · cache hit <100ms · `store_turn` 0.5–1s.
Da riconfermare in locale sul tier Turso.

## Cosa è invece a posto (verificato)
- Neuron: **270/270** test verdi (tier sqlite).
- Trust B1–B3, refs table (L1), prune `dry_run` (F4): implementati e testati.
- CLI `gray-matter`: 18 comandi, tutti documentati.
- Housekeeping fatto: `install.sh` alla root rimosso; knowledge_health L1 (F1); knowledge_neighbors (D3).

## Ordine consigliato verso la release
1. **B1 (L2)** — riprodurre e chiudere su Turso condiviso in locale; è l'unico bug di correttezza alto ancora aperto.
2. **B2** — decidere enrich-only vs espansione; sistemare il test in ogni caso.
3. **D1/D2/D3** — sistemare la toolchain offline così la suite gira in CI.
4. Girare la **suite completa in locale sul tier Turso** (Neuron + NeuRAG + i 2 test `mcp` di GM).
5. **A1–A2, A5, C1–C4** — bump versioni + README + doc.
6. **A3–A4** — tag + push (ultimo step).
