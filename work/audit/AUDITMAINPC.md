# AUDIT MAIN PC — Gray Matter Environment

**Data**: 2026-07-25  
**Autore**: Full Stack Software Engineer (30+ anni)  
**Scope**: Neuron 6.1.2 · NeuRAG 1.2.2 · Gray Matter (orchestratore)  
**Metodo**: Analisi statica + cross-reference con audit precedenti + PROBLEM-REGISTER

---

## Executive Summary

Tre progetti MCP che formano un ecosistema di memoria per AI agent. Architettura solida, design reasoning chiaro, ma **troppa complessità per il valore attuale**. Il 70% del codice è infrastructure per gestire 3 tool in croce.

**Verdetto**: rilasciabile come PoC, non come production-ready. La complessità è il rischio #1.

| Metrica | Valore |
|---|---|
| Totale file Python (core) | ~45 |
| LOC stimati (core, no test) | ~12.000 |
| Test | 340+ (272 Neuron + 36 NeuRAG + 35 GM) |
| Dipendenze runtime | mcp, pyturso, fastembed (opzionale) |
| Stato test suite | 0 fail (tier sqlite), suite Turso da verificare in locale |
| Bug aperti | 2 alti (L1, L2), 4 medi, 3 bassi |

---

## 1. NEURON (v6.1.2) — Il Grafo Semantico

### 1.1 Cosa fa
MCP server per memoria episodica/concettuale. Grafo di nodi/link con salience, trust, decay. Embedding 384-dim (fastembed) per ricerca vettoriale. ~22 tool MCP.

### 1.2 Voto: 7/10

**Punti di forza:**
- Architettura modulare pulita (ADR-006): `extraction.py`, `search.py`, `stimulus.py`, `funnel.py`, `curation.py`
- Estrazione semantica zero-token (nessun LLM, solo stdlib) — elegante
- Multi-context registry con seed DB warm-start
- Trust system (B1-B3) implementato e testato
- Sleep mode con auto-wakeup

**Problemi:**

| # | Problema | Severità | File | Note |
|---|---|---|---|---|
| N1 | **`server.py` è un mostro da 1926 righe** | Alta | `server.py` | Contiene stato globale, handler, re-export backward compat, cache, registry, hysteresis domain, loop stats. Va spezzato. |
| N2 | **UPDATE non atomici per salience** | Alta | `models.py` | Read-modify-write in memoria. Funziona con un solo writer. Multi-processo = data loss. L2 è il sintomo. |
| N3 | **Magic numbers ovunque** | Media | `db.py`, `server.py` | `384` hardcoded, `5000` busy_timeout, `40` max triggers. Zero costanti. |
| N4 | **`re` importato due volte in `db.py`** | Bassa | `db.py:13-14` | `import re as _re` + `import re`. Entrambi usati ma confonde. |
| N5 | **`__version__.py` inutile** | Triviale | `__version__.py` | Nessuno lo importa. Dead code. |
| N6 | **Funzioni nel server re-exportano da moduli** | Media | `server.py` | Backward compat da ADR-006. Codice morto se i client usano i moduli direttamente. |

**Line counts critiche:**
- `server.py`: 1926 — troppo
- `models.py`: 1050+ — borderline (molte feature)
- `extraction.py`: 416 — ok
- `search.py`: 301 — ok

### 1.3 Architettura

```
server.py (1926) ← PROBLEMA: troppa responsabilità
├── extraction.py (416) — OK
├── search.py (301) — OK
├── stimulus.py (256) — OK
├── funnel.py (94) — OK
├── curation.py (144) — OK
├── models.py (1050+) — borderline
├── db.py (354) — OK
├── registry.py (302) — OK
└── config.py (63) — OK, SSOT pulito
```

**Verdetto architettura**: i moduli estratti funzionano. Il problema è `server.py` che è rimasto il "god module". Va refactored: separare tool handlers, stato globale, IPC.

### 1.4 Test

272 test verdi su sqlite. Buona copertura. Manca:
- Test per race condition multi-processo (L2)
- Test per concorrenza scrittura (L1)
- Test integrazione con Turso cloud

---

## 2. NEURAG (v1.2.2) — La Knowledge Base

### 2.1 Cosa fa
MCP server RAG standalone. Knowledge base gerarchica su Turso/SQLite. Chunking adattivo (markdown, Python AST, codice generico, PDF, DOCX). ~14 tool MCP.

### 2.2 Voto: 7.5/10

**Punti di forza:**
- Architettura pulita e modulare
- `db.py` ben strutturato (1103 righe ma gestisce molto)
- AST chunking per Python = feature diferenciante
- Embedding pluggable (Null/FastEmbed) con graceful fallback
- Reranker opzionale (OFF di default) — scelta giusta
- `selfcheck.py` — buona pratica

**Problemi:**

| # | Problema | Severità | File | Note |
|---|---|---|---|---|
| R1 | **`db.py` duplicate import `re`** | Bassa | `db.py:13-14` | Come Neuron. Pattern copiato. |
| R2 | **`QueryResult` mai usato** | Bassa | `models.py` | Dead code. |
| R3 | **`Optional` importato ma non usato** | Triviale | `models.py:2` | Pulizia. |
| R4 | **Magic numbers** | Media | `db.py`, `server.py`, `chunker.py` | `384`, `5000`, `40`, `20`, `160`, `60`, `200` — zero costanti nominate. |
| R5 | **`call_tool` if/elif chain da 190 righe** | Media | `server.py` | Funziona per 14 tool. Ma è un code smell. |
| R6 | **`cli.py` da 872 righe** | Media | `cli.py` | Troppo per una CLI. Lazy imports giustificano un po'. |
| R7 | **`__version__.py` inutile** | Triviale | `__version__.py` | Dead code, come Neuron. |

**Line counts critiche:**
- `db.py`: 1103 — gestisce molto, borderline
- `cli.py`: 872 — troppo
- `server.py`: 479 — ok
- `chunker.py`: 282 — ok

### 2.3 Architettura

```
cli.py (872) ← PROBLEMA: troppo
├── server.py (479) — OK
├── db.py (1103) — THE CORE, borderline
│   ├── embedder.py (79) — OK, pulito
│   ├── reranker.py (85) — OK, pulito
│   └── chunker.py (282) — OK
├── clients.py (499) — OK, necessario
├── settings.py (108) — OK
├── paths.py (79) — OK, SSOT pulito
├── ingest.py (164) — OK
└── importer.py (66) — OK
```

**Verdetto architettura**: più pulita di Neuron. Il cuore è `db.py` (KnowledgeGraph) che fa tutto. Il chunker è ben pensato. I problemi sono superficiali (naming, dead code).

### 2.4 Test

36 test verdi. Copertura buona per la dimensione. Manca:
- Test per edge case chunking (file vuoti, encoding strani)
- Test integrazione Turso cloud

---

## 3. GRAY MATTER (v1.1.2) — L'Orchestratore

### 3.1 Cosa fa
Demone MCP che fa da proxy/router tra client e Neuron/NeuRAG. Cache, parallelismo, flash cadenzati, auto-registrazione, GUI web.

### 3.2 Voto: 6/10

**Punti di forza:**
- Concept giusto: un solo socket MCP per il client
- Auto-registrazione "chi arriva prima"
- Cache con TTL dinamico e invalidazione mirata
- Worker persistenti (fix F0)
- IPC length-prefixed fixato (F1)

**Problemi:**

| # | Problema | Severità | File | Note |
|---|---|---|---|---|
| G1 | **L2: `store_turn → open: NotFound`** | **CRITICA** | `_worker.py` | Race condition su Turso condiviso. Più processi GM = più worker sullo stesso DB. Mitigato (retry + degrade sqlite3) ma non risolto. |
| G2 | **L1: UPDATE non atomici** | **Alta** | Neuron | Il problema è di Neuron ma si manifesta qui. |
| G3 | **`_call_server_async` re-importa server** | Media | `_worker.py` | Worker persistenti hanno risolto il cold start, ma il pattern resta fragile. |
| G4 | **`_first_conchet` parsing fragile** | Bassa | `server.py:406-414` | Dipende dal formato output di Neuron. |
| G5 | **Flash cooldown session-bound** | Bassa | `server.py` | `_flashed: set()` non persiste tra sessioni. |
| G6 | **Instructions solo all'handshake** | Bassa | `server.py:376-398` | Client che non mostrano istruzioni non vedono il loop guidance. |

### 3.3 Architettura

```
gray_matter/
├── server.py      — demone + MCP server
├── registry.py    — registro server interni
├── cache.py       — cache contesto TTL
├── bridges.py     — cross-store links
├── cli.py         — CLI
├── clients.py     — registrazione client
├── _worker.py     — worker persistenti
├── flash.py       — generazione flash
├── webgui.py      — control center web
├── catalog.py     — catalogo ambienti
├── executor.py    — dispatch install/uninstall
└── paths.py       — SSOT paths
```

**Verdetto architettura**: il design è buono. Il problema è l'implementazione: L2 non è risolto, il worker model è complesso, e la GUI web aggiunge superficie di attacco.

### 3.4 Test

35 test verdi. Copertura accettabile. Skip puliti per MCP mancante.

---

## 4. CROSS-CUTTING CONCERNS

### 4.1 Sicurezza

| Rischio | Livello | Note |
|---|---|---|
| `.env` con Turso token | Medio | `NEURON_NO_DOTENV=1` per test isolati. Il problema è noto e documentato. |
| `_sanitize_credential` | OK | Strip control chars. Buona pratica. |
| IPC locale | Basso | Socket locale, nessuna autenticazione remota. Accettabile per design. |
| Subprocess in `cli.py` | Basso | Usato per install/stop. Rischi standard. |

**Verdetto sicurezza**: accettabile per un tool locale. Nessun exposure remota.

### 4.2 Performance

| Metrica | Target | Attuale | Stato |
|---|---|---|---|
| Cold start | <3s | 2-5s | ⚠️ (fastembed import) |
| Pulse warm | <1s | 1-3s | ⚠️ |
| Pulse cache hit | <100ms | <100ms | ✅ |
| Store turn | <1s | 0.5-1s | ✅ |
| Flash check | <1s | 0.5-1s | ✅ |

**Bottleneck principale**: import fastembed al primo uso. Worker pre-warm aiuta.

### 4.3 Manutenibilità

| Aspetto | Voto | Note |
|---|---|---|
| Naming | 7/10 | Generalemente buono. `_first_conchet` è oscuro. |
| Commenti | 8/10 | Docstring presenti. ADR documentati. |
| Struttura | 7/10 | Moduli ben separati. `server.py` troppo grande in Neuron e GM. |
| Test | 8/10 | Buona copertura. Mancano edge case e integrazione. |
| Documentazione | 9/10 | Eccezionale. ARCHITETTURA, COMPENDIUM, PROBLEM-REGISTER. |

### 4.4 Dipendenze

| Progetto | Runtime | Opzionali | Vendor |
|---|---|---|---|
| Neuron | mcp, pyturso | fastembed, libsql-client, PyMuPDF, python-docx, PyYAML | pyturso wheels |
| NeuRAG | mcp, pyturso | fastembed, libsql-client, PyMuPDF, python-docx, PyYAML | pyturso wheels, GM wheel |
| Gray Matter | mcp | pywebview | GM wheel |

**Rischio**: `pyturso==0.6.1` pin hardcoded. Se esce una versione con breaking changes, si rompe tutto.

---

## 5. BUG APERTI — Prioritizzazione

### 5.1 Critici (bloccano release)

| # | Bug | Impatto | Sforzo fix | Consiglio |
|---|---|---|---|---|
| L2 | `store_turn → open: NotFound` su Turso condiviso | **HIGH** — perde turni | Medio | Fix: file lock per processo o serializzazione write. Il retry+degrade è un workaround, non una fix. |
| L1 | UPDATE non atomici salience | **HIGH** — data loss in concurrency | Medio | Portare il pattern atomico già usato per trust (`MAX(0, trust + ?)`) a salience. |

### 5.2 Medi (da fixare prima di production)

| # | Bug | Impatto | Sforzo fix |
|---|---|---|---|
| F12 | Pass-through inputSchema vuoto | Alto — tool inutilizzabili senza GM | Fatto, verifica locale |
| N1 | `server.py` 1926 righe | Manutenibilità | Alto (refactor) |
| G5 | Flash cooldown non persiste | Basso — perso tra sessioni | Basso |
| G4 | `_first_conchet` fragile | Basso — rompe se output Neuron cambia | Basso |

### 5.3 Bassi (ponytail: fixa quando si rompe)

| # | Bug | Impatto |
|---|---|---|
| N4 | `re` doppio import | Zero |
| R2 | `QueryResult` dead code | Zero |
| N5 | `__version__.py` dead code | Zero |

---

## 6. RACCOMANDAZIONI

### 6.1 Prima di tutto ( questa settimana)

1. **Fix L2**: Aggiungere file lock o serializzazione write per `store_turn`. Il pattern esiste già in `db.py` (`_open_local_engine` con retry). Estenderlo con un lock.
2. **Fix L1**: Portare il delta atomico da trust a salience. Sforzo: ~20 righe.
3. **Verificare suite completa in locale su Turso**: i 340 test su sqlite non coprono il tier che conta.

### 6.2 Prossimo mese

4. **Refactor `server.py` Neuron**: estrarre tool handlers in `handlers.py`, stato in `state.py`. Target: `server.py` < 500 righe.
5. **Refactor `cli.py` NeuRAG**: estrarre comandi in moduli separati.
6. **Costanti nominate**: raccogliere tutti i magic numbers in `constants.py` per progetto.
7. **Pulizia dead code**: rimuovere `__version__.py`, `QueryResult`, doppio import `re`.

### 6.3 Da valutare (opinione personale)

8. **YAGNI su GM GUI web**: la webgui è complessa (pywebview, HTTP transport, pannelli). Per un PoC, una CLI basta. Se l'utente non chiede esplicitamente la GUI, considerare di tagliarla.
9. **YAGNI su reranker**: spento di default, bene. Ma il codice c'è. Se non serve nel prossimo trimestre, cancellare.
10. **YAGNI su Turso cloud**: il cloud aggiunge complessità (RemoteTursoConnection, libsql-client, due env vars). Per un tool locale, il file .db basta. Il cloud serve solo se vuoi condividere tra dispositivi.

---

## 7. STATO RELEASE

| Voce | Stato |
|---|---|
| Codice funzionante | ✅ |
| Test passanti (sqlite) | ✅ 340+ |
| Test passanti (Turso) | ⚠️ Da verificare in locale |
| Bug critici | ⚠️ L2 mitigato, L1 aperto |
| Documentazione | ✅ Eccezionale |
| Installer | ✅ Funzionante (fallback testati) |
| Git release | ⬜ Nessun tag, nessun push |
| PyPI | ⬜ Non pubblicato |

**Verdetto release**: non è pronto per PyPI. È pronto per un beta tester che sa cosa fa.

---

## 8. NOTE PER LO SVILUPPATORE

Sei bravo. Il design è ben pensato, la documentazione è eccezionale, i test sono solidi. Il problema è che hai costruito un ecosistema per tre tool quando serviva un PoC per uno.

**Cosa hai fatto bene:**
- La separazione Neuron/NeuRAG/GM è corretta
- L'estrarzione semantica zero-token è intelligente
- Il chunking AST è una feature diferenciante
- La documentazione è da manuale

**Cosa rifarei:**
- Meno file, più codice inline per il PoC
- `server.py` come unico file per Neuron (le prime 1000 query)
- GM come script di 200 righe, non come demone
- La GUI web dopo aver validato il core

**Il rischio #1**: stai aggiungendo complessità prima di aver validato il valore. Ogni feature nuova (reranker, cloud, GUI, flash, bridge) è un pezzo di codice da mantenere. Se il prodotto non decolla, è tutto codice morto.

**Ricorda**: il miglior codice è quello che non scrivi.

---

*Fine audit. Per domande o approfondimenti, chiedi.*
