# Changelog — NeuRAG

## Unreleased
- **`search()` dice sempre quanto e su che scala**: ogni risultato porta `score`
  e `score_from` (`cosine` | `bm25` | `rrf` | `cross-encoder`). Prima il punteggio
  esisteva solo come `sim`, attaccato dal ramo vettoriale: le righe arrivate da
  BM25 non ne avevano nessuno e il valore RRF della fusione veniva buttato via —
  quindi metà di un ranking ibrido era senza punteggio e l'altra metà portava un
  coseno che non spiegava più l'ordine (visibile su `neurag query --json`). Anche
  il reranker cross-encoder ora riscrive il punteggio in base a cui riordina.
  Le scale non sono confrontabili tra loro: `score_from` serve a leggerle.
  La diversificazione MMR riordina senza ri-assegnare punteggi, quindi con
  `diversify=True` l'ordine non è (deliberatamente) quello dei punteggi.
- **Un `;` dentro un commento SQL non tronca più lo schema**: `SCHEMA_SQL` viene
  tagliato a mano su `;` (nessun backend ha `executescript`) e un punto e virgola
  dentro un `--` spezzava la statement che lo conteneva. `_init_schema` applica
  lo script in un try/except che segna solo `_corrupt`, quindi la tabella
  semplicemente non compariva, in silenzio. `_split_sql` toglie i commenti prima
  di tagliare, usato da entrambi i chiamanti.
- **Tag substrate (DESIGN-EVOLUTION §4, P1)**: un tag smette di essere una
  stringa dentro cinque colonne JSON e diventa una riga. Nuove tabelle `tags`
  (`name` normalizzato, `uses`, `salience`, `last_used`), `node_tags`,
  `chunk_tags` + indici. `add_node`/`add_tags` scrivono entrambi i lati —
  la colonna legacy `nodes.tags` resta il read path finché la migrazione non è
  verificata sui vault reali.
  - **Migrazione idempotente**: al primo open il vault esistente viene
    ribaltato dalla colonna JSON a `node_tags`, poi il flag `meta.tags_migrated`
    salta la scansione. Rieseguirla non scrive nulla.
  - **Normalizzazione = join key**: `Cache`, `cache ` e `CACHE` sono un tag solo.
  - **IDF suppression**: un tag portato da più di metà dei nodi
    (`MAX_TAG_NODE_RATIO=0.5`, sotto `MIN_TAG_NODE_FLOOR=50` nodi non si
    sopprime niente) non genera più coppie candidate. Toglie anche il costo
    O(n²) che il floor Jaccard non toccava: quello limitava le SCRITTURE, non i
    confronti. La misura di similarità è invariata — il tag comune resta nel
    denominatore Jaccard, cambia solo quali coppie vengono considerate.
  - **`build_tag_links` legge `node_tags`**, non più il JSON di ogni nodo.
  - `chunk_tags` popolata da `index_into_node`; il replace per-file cancella le
    righe di join prima dei chunk (niente FK cascade: pyturso 0.6.1).
  - Test: `tests/test_tag_substrate.py` (11), incluso il gate di fase
    "link count invariato rispetto al path JSON legacy".

## 1.2.2
- **`config --json`**: `neurag config list --json` emette i knob strutturati
  (value/default/type/help/suggest) e `config set/get --json` l'esito — così il
  control center legge la config via CLI invece di importare `neurag.settings`.
  `config set` accetta ora il valore vuoto (guard `value is None`).
- **`repair --json`**: elenca le superfici cancellabili (`--wipe-knowledge`,
  `--wipe-config`) con path/stato, per il pannello Repair del control center.
- **`neurag gui` bootstrap reale + wheel d'emergenza OFFLINE**: se Gray Matter
  manca, lo installa nello stesso venv — cartella sorella (dev) → **wheel GM
  vendorata nel package** (`neurag/_gm_vendor/*.whl`, `--find-links` senza rete:
  GM ha solo `mcp` come dep, già presente) → indice pip → `git+https://github.
  com/recla93/gray-matter` — streamando il progresso, poi apre. La wheel va
  ricostruita a ogni release di GM (vedi RELEASE-CHECKLIST). keep-in-sync `neuron`.
- **Guard su `neurag register`**: se GM gestisce ancora NeuRAG (non in
  `unmanaged`), il register DIRETTO si rifiuta (doppia registrazione) e indirizza
  a `neurag go-standalone` o `gray-matter deregister neurag`. Bypass `--force`;
  senza GM nessun guard. keep-in-sync con `neuron/clients.py`.
- **Icona desktop "NeuRAG"** (launcher standalone): l'installer standalone la crea
  già a fine install (`neurag gui --shortcut-only`) e `neurag gui` la ri-assicura
  a ogni apertura. Logica in `neurag/shortcut.py` (copia tool-local cross-OS,
  keep-in-sync con `gray_matter/shortcut.py` — serve senza GM). L'icona punta a
  `neurag gui`, che bootstrappa GM al primo click. Idempotente (marker nel venv).

## 1.2.1
- **Fix flash CMD (Windows)**: `db.py` (pip install pyturso durante il fallback
  Turso) e `clients.py` (register/deregister via `claude` CLI) ora usano
  `CREATE_NO_WINDOW`. Nel `clients.py` il flag è nel runner di default, così i
  runner iniettati dai test non ricevono `creationflags` a forza.
- **Extra `[gui]`** = `gray-matter`: il control center è UNO (`gray_matter.webgui`);
  `neurag gui` lo bootstrappa se manca. Il runtime MCP resta indipendente da GM
  (import guardato) — verificato: NeuRAG importa e gira con gray_matter assente.

## 1.2.0
- **Registrazione MCP standalone**: nuovo `neurag/clients.py` (clone mirato di
  `neuron/clients.py`, keep-in-sync) — matrice client (claude-desktop,
  claude-code, cursor, vscode, opencode), `register`/`deregister` non
  distruttivi (backup `.neurag-bak`, verify-after-write con rollback, JSONC mai
  riscritto → snippet manuale, Claude Code via `claude mcp add`). Entry via
  `python -m neurag.server`, mai console-script.
- **Nuovi comandi CLI** (gestiti PRIMA del DB): `neurag register`,
  `neurag deregister`, `neurag go-standalone` (registrazione diretta + rilascio
  dal gateway GM se presente, reversibile con `gray-matter register
  --gateway`), `neurag gui` (control center condiviso se GM c'è, altrimenti
  offerta di install — mai silenziosa).
- **Server disaccoppiato da GM**: l'autoregister al gateway salta se NeuRAG è
  in lista `unmanaged` (niente tool pubblicati due volte); senza GM il server
  MCP gira standalone puro (già così, ora verificato).
- **Repair puntuale**: `neurag repair` stampa (o lancia con `--reinstall`) il
  PROPRIO installer con `--force`, risolto dai path registrati
  (`paths.source_dir()`).
- **Installer `--force`**: `install.ps1 -Force` / `install.sh --force` —
  reinstall forzato del pacchetto NeuRAG anche a versione invariata (pattern di
  gray_matter, inoltrato anche al GM installer).

## 1.1.0

### Grafizzazione server-side (`ingest`)
- Nuovo modulo `ingest.py`: cartelle → nodi (radice = godnode, primo livello
  = fundamental, sottocartelle = specialization), file → chunk nel nodo della
  propria cartella, poi embedding e `rebuild_links` — tutto in un colpo,
  senza far passare i chunk dal contesto LLM.
- Tool MCP `knowledge_ingest` (job in background, risponde subito con un id)
  + `knowledge_ingest_status` (progresso/esito). Il job apre una connessione
  DB propria (thread-safe); l'embedder caldo del worker viene riusato.
- CLI `neurag ingest <path> [--godnode X]`: stessa pipeline, sincrona, con
  progresso streamato riga per riga (perfetta dal control center).

### Modifica nodi da CLI/GUI
- `db.rename_node`: rinomina aggiornando il path del sottoalbero intero.
- CLI `rename-node <nome> <nuovo>` e `remove-node <nome>` — compaiono da
  soli nel control center di Gray Matter.

### Alleggerimento import
- `cli.py` (1.0.1): niente import di db/chunker a livello modulo — il
  catalogo GUI legge i comandi senza caricare sqlite/turso/embedder.

## 1.1.3

### Path SSOT (NeuRAG possiede i suoi path) — 2026-07-22
- Nuovo `neurag/paths.py`: unica fonte di verità delle location NeuRAG
  (`data_dir`, `db_path`, `config_path`, `source_dir`). `db.py` e `settings.py`
  ora delegano qui invece di ridefinire i percorsi. Gray Matter li SCOPRE
  chiamando `neurag.paths` (non li hardcoda più). Override `NEURAG_HOME`.
- `neurag record-paths --source <dir>`: NeuRAG registra la propria cartella
  sorgente (self-knowledge) così repair/reinstall la ritrovano. Nascosto in GUI.

## 1.1.2

### Turso preferito con fallback documentato — 2026-07-22
- Sul vault reale (db_path None) se NON siamo su Turso, `KnowledgeGraph` prova
  ad acquisirlo — import, e se manca `pip install pyturso==0.6.1` dalle wheel
  vendored (`--find-links vendor/`) — fino a `NEURAG_TURSO_ATTEMPTS` (default 3)
  volte. Solo dopo degrada a sqlite3 **documentando gli errori** (in `status`
  → `turso_degraded`/`turso_errors`, e in `doctor`). Nessun crash: il fallback
  resta. Escape: `NEURAG_REQUIRE_TURSO=0`; autoinstall off: `NEURAG_TURSO_AUTOINSTALL=0`.
  I DB di test (db_path esplicito) non sono toccati → la suite sqlite resta verde.
- Nuovo comando `neurag repair` (scope solo NeuRAG): wipe selettivo di
  knowledge.db / config, poi promemoria del reinstall forzato. Gestito prima di
  aprire il DB, così funziona anche su vault corrotto/non-Turso.

## 1.1.1

### Fix: DB corrotto non crasha più (diagnostica robusta) — 2026-07-22
- Un `knowledge.db` malformato faceva sollevare `DatabaseError: file is not a
  database` all'apertura (`_init_schema`/PRAGMA) → crashava **ogni** comando
  neurag, non solo `health`, con traceback grezzo nel control center.
- Ora `KnowledgeGraph.__init__` non alza: intercetta la corruzione e la marca
  (`_corrupt`). `status`/`health`/`doctor` la **riportano** ("DB CORROTTO" +
  errore + hint di recovery) con exit 1 pulito, invece di crashare. Vale anche
  per i tool MCP `knowledge_status`/`knowledge_health` (niente più "Internal
  Server Error" a valle).
- Aggiunto `PRAGMA busy_timeout=5000` all'apertura (WAL + busy_timeout: gli
  scrittori si accodano invece di corrompersi — FASE 0 dell'audit).

### Reranker cross-encoder (opt-in, OFF di default) — 2026-07-22
- Nuovo stadio di reranking opzionale: la ricerca recupera un pool più ampio
  di candidati (`rerank_pool`, default 50), poi un cross-encoder li riordina e
  tiene i veri top-n. Pattern RAG standard "retrieve wide, rerank narrow":
  più precisione al costo di latenza + download modello, perciò **spento di
  default** e attivabile per singola install.
- Nuovo `neurag/reranker.py` (`fastembed.TextCrossEncoder`, lazy + fallback
  identico a `embedder.py`: se off o modello assente → `NullReranker`, costo
  zero, nessun download).
- Nuovo `neurag/settings.py` (specchio di `gray_matter/settings.py`): config
  JSON in `~/.local/share/neurag/config.json` — SEPARATO da `knowledge.db`.
  Knob: `rerank` (bool), `rerank_pool` (int), `rerank_model` (str). Env
  `NEURAG_RERANK`/`NEURAG_RERANK_MODEL` hanno la precedenza sul file.
- CLI `neurag config get|set|list` → toggle per **tutte le install**, anche
  NeuRAG standalone. Es.: `neurag config set rerank on`.
- Control center: la card `config` non è più il form grezzo action/key/value —
  è un **pannello Impostazioni** con toggle/select/campi che si salvano subito
  (`webgui.py` `config_knobs`/`config_set` + rendering in `webgui.html`). Vale
  per ogni ambiente con un `config` (Gray Matter e NeuRAG), zero elenchi a mano;
  i knob si auto-descrivono da `settings.HELP`/`SUGGEST`. Per `rerank_model` il
  picker propone il multilingue `jinaai/jina-reranker-v2-base-multilingual`.
- `db.search` refattorizzata in `_retrieve` (stage 1) + rerank opzionale;
  con reranker OFF è un no-op wrapper (comportamento invariato). `status`/
  `doctor` ora mostrano lo stato del reranker.

### Fix da audit OpenCode (2026-07-21)
- `install.ps1`: nel fallback PyPI, exit solo su successo di `gray-matter
  install` → degrade a standalone invece di terminare (fix OpenCode);
  specchiato in `install.sh` (niente `exec`: si prosegue sul fallback).

### Installer — GM opt-out (consenso informato, DESIGN-CLOUD-MEMORY §6)
- `install.sh`/`install.ps1`: Gray Matter non è più forzato — prompt
  `Install Gray Matter (recommended)? [Y/n]` con il deficit esplicito (senza GM
  si perdono solo bridge cross-store e auto-surface dei vicini). Headless:
  `--no-gm` / `GM_OPTIN=0`. Rifiuto → install STANDALONE (venv proprio, doctor
  + snippet MCP `neurag-mcp` per il client). GM non ottenibile (offline) →
  degrada a standalone invece di uscire. Reversibile ri-eseguendo senza `--no-gm`.

## v1.0.0 (2026-07-21)

Prima release stabile. Consolida 0.3.0 (link_graph, rebuild_links, source
attribution nei risultati, vector SQL su Turso, AST chunking, Turso mandatory).
Le API dei tool `knowledge_*` sono considerate stabili.

## v0.3.0 (2026-07-20)

### New features
- `link_graph`: shows all node links with weights and evidence
- `rebuild_links`: clears and rebuilds links from tags + cross-refs
- Source attribution in `knowledge_query` results (D1)

### Database improvements
- Turso mandatory (pyturso==0.6.1) for vector search
- `_FixedEmbedder` test helper for deterministic embeddings

### Installer unification
- Canonical install via `install.ps1` / `install.sh` delegating to GM
- Vendored pyturso wheels (py310-314 win_amd64)

### Documentation
- README.md added
- INSTALL-AI.md (EN) + INSTALL-AI.it.md (IT)
- DESIGN-CROSSLINKS.md

### Tests
- 30+ tests passing (test_node_links, test_vector_sql, test_neighbors)
- Vector SQL test with Turso engine verification

## v0.2.0 (2026-07-18)

- Source attribution in knowledge_query (D1)
- AST chunking + symbol tags → triggers
- knowledge_health L1
- Installer bundle GM + wheels
