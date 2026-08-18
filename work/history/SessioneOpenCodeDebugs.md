# Handoff — SessioneOpenCodeDebugs

Stato al **2026-08-05** — sessione di audit/fix sul progetto **Gray Matter** (3 repo condivisi: `neuron`, `neurag`, `gray_matter`, un solo venv, branch GME).
Tutte le modifiche delle **due ondate di fix sono NON committate** nei 3 repo.

Chi riprende parte da qui: questo file dice cosa è stato fatto, come è stato fix e cosa resta.

---

## Indice

1. [Contesto](#contesto)
2. [Ondata 1 — Fix di robustezza e sicurezza](#ondata-1--fix-di-robustezza-e-sicurezza)
3. [Ondata 2 — Fix installer, deploy e hardening](#ondata-2--fix-installer-deploy-e-hardening)
4. [Test](#test)
5. [Verifiche](#verifiche)
6. [Piano evolutivo — Working Memory tier](#piano-evolutivo--working-memory-tier)
7. [Come si lanciano le suite](#come-si-lanciano-le-suite)

---

## Contesto

| Repo | Ruolo |
|---|---|
| `neuron` | memoria semantica (graph con E-tiers, session cache, drift links) |
| `neurag` | knowledge base vettoriale (vault, chunks, RRF retrieval) |
| `gray_matter` | gateway MCP + orchestratore + installer + GUI web |

Ambiente di test:
- venv: `C:\Users\recla\Desktop\Gray Matter Enviroment\neuron\.venv\Scripts\python.exe` (3 repo editable)
- `PYTHONPATH` = parent `C:\Users\recla\Desktop\Gray Matter Enviroment`

---

## Ondata 1 — Fix di robustezza e sicurezza

### 1.1 `claude mcp add` — entry già esistente non più "successo idempotente" (3 repo)
**Problema**: `claude mcp add` rifiuta le entry già presenti. Trattarle come successo idempotente lasciava la entry **VECCHIA**, che può puntare a un venv stantio.
**Fix**: alla risposta `"already exists"` → `claude mcp remove` + nuovo `mcp add` (riscrittura).
- `neuron/src/neuron/clients.py`, `neurag/clients.py`, `gray_matter/clients.py`
- annotazione `keep-in-sync` nei commenti.

### 1.2 `_claude_argv` — shim `.cmd` su Windows (neuron)
**Problema**: `claude` è uno shim `.cmd` (npm); `CreateProcess` non esegue i `.cmd` → registration CLI falliva su Windows.
**Fix**: wrapper `_claude_argv(*args)` che su `os.name == "nt"` e estensione `.cmd/.bat` costruisce `["cmd", "/c", ...]`. (gray_matter/neurag già lo avevano dal 2026-07-21; neuron lo riceve ora in keep-in-sync.)

### 1.3 `_tool_auto` — link cross-context (neuron/server.py, E3.1)
**Problema**: i link cross-context venivano creati con `add_link(...)` — o come **self-link** (`kw`→`kw`, che `add_link` scarta silenziosamente → no-op), o come edge **intra-graph** verso un nodo che vive in un altro context.
**Fix**: uso di `g.form_drift_link(kw, ckw, alt_dom, turn)` — `get_active_links` filtra i drift, `drift_links()` li riporta nelle query di contesto profondo.

### 1.4 `_consolidate_cli` — context su disco (neuron/__main__.py)
**Problema**: `list_contexts()` vede solo i graph lazy-loaded (processo nuovo = solo "default"), quindi `--context` consolidava solo default e saltava i context creati via `switch`.
**Fix**: enumerazione da `manage._contexts()` (come fa `manage`), non dalla registry live.

### 1.5 `bridges.py` — path SSOT (gray_matter)
**Problema**: path hardcoded `~/.local/share/gray_matter/bridges.db` divergeva da `paths.gm_bridges()` → lo store reale non veniva mai offerto al wipe né rimosso all'uninstall.
**Fix**: delegazione a `from gray_matter import paths; paths.gm_bridges()`.

### 1.6 `_sync_manifest_clients` — manifest aggiornato da `register_flow` (gray_matter/clients.py)
**Problema**: l'installer scrive il manifest, ma `cli register`/GUI passano da `register_flow` che lasciava `clients` stantio → un uninstall deregistrava solo l'ultimo client e orfanizzava gli altri.
**Fix**: dopo `register()`, union dei client `ok` nel manifest esistente (mai drop delle entry precedenti, `only` può essere un sottoinsieme).

### 1.7 `_remove_code` — token cloud rimosso (gray_matter/executor.py)
**Problema**: `.env` (Turso token) vive in `gm_home()` ma non era nella lista target → l'uninstall lasciava le credenziali su disco.
**Fix**: aggiunto `cloud.default_env_file()` ai target.

### 1.8 Test — isolamento dei path reali (gray_matter/tests)
**Problema**: i test che chiamano `clients.register()` toccavano i config REALI della macchina (7 config corrotti con `/fake/python`).
**Fix**: fixture `home(tmp_path, monkeypatch)` che mocka `HOME`/`USERPROFILE`/`APPDATA`/`LOCALAPPDATA`/`XDG_DATA_HOME`.

---

## Ondata 2 — Fix installer, deploy e hardening

Legenda codici: **I**=installer, **n**=neuron, **S**=sicurezza, **F**=flusso.

### I2 — Apostrofo nel nome modello embed → via env var (ps1+sh, 3 repo)
**Problema**: nome modello con apostrofo chiudeva il literal Python interpolato nella stringa → scelta persa in silenzio.
**Fix**: il valore passa dall'**ambiente** (`NS_EMBED_NAME_SAVE`/`NS_EMBED_DIM_SAVE`), mai interpolato nel sorgente.
- `neuron/install.ps1` (`set_user_env(NS_EMBED_MODEL=os.environ[...])`), `neurag/install.ps1` (`settings.set('embed_model', ...)`), `gray_matter/install.ps1`, e gli sh corrispondenti.

### I3 — `--no-deps` solo con mcp presente (ps1+sh, 3 repo)
**Problema**: `--force-reinstall --no-deps` su venv fresco (primo install, `-Clear`, repair "clean") → `mcp` mancante → install inutilizzabile al primo run. `mcp` è la sola shared dep hard.
**Fix**: gate `Test-HasMCP`/`has_mcp()` (probe su `importlib.util.find_spec('mcp')`) valutato **al momento dell'uso** (tra il check e l'install il venv può essere ricostruito). `Get-RepairArgs`/`repair_args()` restituiscono `--force-reinstall --no-deps` solo se `Force && mcp`.
- In GM ps1: aggiunta opzione **`[C]lean`** peer (rimozione venv + ricostruzione + reinstall GM per primo).

### I4 — Terminatore affermativo per l'install (GM sh)
**Problema**: se `$GM_VER` non si legge, l'interprete non parte → un terminatore `[OK]` finto non distingueva "riuscito" da "morto".
**Fix**: `[X] INSTALL FAILED` + messaggio + **`exit 1`** quando `GM_VER` è vuoto.

### I5 — Tier pywebview (GM sh)
**Fix**: install best-effort di `pywebview>=5.0` → GUI nativa; se manca, la GUI degrada al browser (comportamento pre-esistente).

### I6 — Degrade con WARNING al posto di `exit $LASTEXITCODE` (ps1 dei peer)
**Problema**: il fallimento dell'installer GM faceva uscire con codice di errore anche quando esistevano path di fallback.
**Fix** (4 punti in neuron/neurag install.ps1): `if ($LASTEXITCODE -eq 0) { exit 0 }` altrimenti `WARNING: GM installer failed ... continuing with the fallback paths` + `break`.

### I7 — `-y/--yes`/`GM_YES`/`ASSUME_YES` unico gate per i prompt
**Fix**: ogni prompt (modalità, modello, register) è coperto da un unico gate non-interattivo. `GM_YES` env è il contratto ps1/sh (`$env:GM_YES` / `${GM_YES:-0}`).

### n11 — `invoke_tool()` fallback `python -m` (sh dei peer)
**Problema**: console-script mancante nel venv → fail immediato su `register`/`doctor`/`--version`.
**Fix**: helper `invoke_tool $exe $mod ...`: usa `$VENV/bin/$exe` se esiste, altrimenti degrade a `python -m $mod` con avviso.

### n12 — `GM_EMBED_MODEL` esportato prima della delega (neuron/sh)
**Problema**: in coupled mode a scegliere il modello è GM (`gm_select_embed_model`), che lo legge da `GM_EMBED_MODEL` — senza export la scelta spariva in tutti e 3 i path gateway.
**Fix**: `[ -n "$EMBED_MODEL" ] && export GM_EMBED_MODEL="$EMBED_MODEL"`.

### Fix HookSrc — path spezzato (ps1 neuron+neurag)
**Fix**: `Join-Path $Venv "Lib\site-packages\neuron\clients\deploy_hooks.py"` (la stringa era troncata da un newline, risultava in `...site-packages\euron\...`).

### S2 — `_register_json` hardening (gray_matter/clients.py)
- **ensure_ascii=False**: path con accenti non diventano `\uXXXX` (i client possono rifiutarli).
- **root non-oggetto**: JSON valido ma root stringa/lista/numero → errore pulito (`action: "error"`), file **non toccato** (prima esplodeva su `setdefault`).
- **Verify-after-write + rollback**: rilettura con `json.loads` + navigazione dei keys; se il server non è presente → restore dal `.bak` e `error`.

### S3 — `_scrub_codex_plugins` rimuove anche la cache mirror (gray_matter/executor.py)
**Fix**: la scrub di `~/.codex/config.toml` ora rimuove anche `~/.codex/plugins/cache/claude-cowork/neuron-guard` (il mirror di `deploy_hooks.deploy_cowork`) — altrimenti il modello raggiungeva tool che non esistono più. Il file config.toml non viene mai cancellato, solo il blocco `[plugins."neuron-guard@claude-cowork"]`.

### S4 — webgui: `neurag_url` senza fallback a `TURSO_DATABASE_URL` (gray_matter/webgui.py)
**Problema**: NeuRAG legge **solo** `NEURAG_TURSO_DATABASE_URL` (db.py:45); il fallback a `TURSO_DATABASE_URL` di Neuron riportava come "configured" il DB sbagliato. Solo il token può essere condiviso (db.py:46).
**Fix**: `os.environ.get("NEURAG_TURSO_DATABASE_URL", "")`.

### F5 — `do_POST` guardia prima del `getattr` (gray_matter/webgui.py)
**Problema**: `getattr(api, name, ...)` girava su input arbitrario (path non `/api/`, nomi con `_`).
**Fix**: guardia **prima** del lookup: `not self.path.startswith("/api/") or name.startswith("_")` → 404 JSON.

### Codex deploy (gray_matter) — corredo di S3
- `executor.py`: `_deploy_codex` — mirror del plugin cowork (`neuron-guard`) nel cache Codex + enable in `~/.codex/config.toml` (upsert sezionale con `_toml_upsert_section`), prune dei file stantii.
- `installer.py`: `HOOK_ASSETS["codex"] = "cowork-plugin/neuron-guard"`.
- Test: `test_deploy_hook_codex` (mirror + enable + idempotenza).

### Range Python GM — nessun fix
Valutato `>=3.10`: puro Python con pyproject, nessuna estensione C → un upper bound creerebbe solo un blocco artificiale.

---

## Test

| Item | Esito |
|---|---|
| Fix test pre-esistente | `gray_matter/tests/test_executor.py:200-201` → `remove_venv=False` in `test_uninstall_purge_wipes_data_without_asking` |
| Suite GM completa | **524 passed, 1 skipped, 0 failed** |
| Skip pre-esistente | controprova finestra console (valida solo da console visibile) |

Perché il fix del test: il codice è giusto — il venv è **condiviso coi peer** e `purge_data` non deve toccarlo (commento in `gray_matter/executor.py:791-795`); era il test a essere fragile perché non isolava il venv reale.

Test aggiunti in questa sessione:
- `test_register_json_non_dict_root_returns_error_not_crash`
- `test_deploy_hook_codex` (mirror + enable + idempotente)
- fixture `home` (isolamento config reali)

---

## Verifiche

- 3 × `install.ps1` → parse OK (Parser PowerShell)
- 3 × `install.sh` → `bash -n` OK
- `clients.py`, `executor.py`, `webgui.py` → `py_compile` OK
- Suite GM: 524 passed / 1 skipped

---

## Piano evolutivo — Working Memory tier

**Design approvato** (decisioni dell'utente in sessione). Niente è ancora implementato — è il prossimo blocco di lavoro.

### Premessa chiave
La working memory di Neuron **esiste già**: è la **session cache** del graph (`models.py:423` `cache_add`, persistita nel meta a `:1443`, TTL in turni `SESSION_CACHE_TURNS=10` a `models.py:89`, popolata da `store_turn` a `server.py:1413`). Il gap è che `_resolve_context` **non la legge**. Quindi niente secondo store né buffer: solo collegamento.

### A — Neuron: WM collegata al retrieval
- **A1** `_resolve_context` (server.py:973): dopo `top_nodes`/`related_links`, aggiungere i keyword della session cache non scaduti come sezione `recent` (addendum, non ranking — per non inquinare contesti non correlati).
- **A2** Refresh: verificare chi chiama `cache_expire`; far sì che le keyword toccate da pre_turn/confirm/query vengano refreshati (usato → recente).

### B — NeuRAG: uso + correzioni
- **B1** Schema `chunks` (db.py:390): `use_count`, `last_used`, `corrected` — pattern ALTER-safe come `node_links` (db.py:477-478).
- **B2** Uso: `_retrieve` incrementa `use_count`/`last_used` sui top-N ritornati (best-effort, mai bloccante sul path caldo).
- **B3** Ranking: `corrected=1` → override (il chunk corretto precede i fratelli non corretti); `use_count` → piccolo boost stabile con kill-switch env var.
  **Guardia**: il changelog documenta che il terzo leg a spreading activation nel retrieval degradò recall@5 0.967→0.867 (db.py:2300). Il boost di uso deve essere **minimale** — peso che rimescola il ranking = regressione.
- **B4** `knowledge_correct` (cli + server MCP): aggiorna `chunks.text`, set `corrected=1`, ricalcola embedding.

### C — GM orchestrazione
- **C1** Registrare `knowledge_correct` nei tool GM + worker mutante (pattern dei tool `knowledge_*` esistenti).

### Da decidere
- B3: boost di uso **minimale safe** (proposta) oppure uso con peso maggiore nel ranking (rischio regressione). **Non serve toccare** `gray_matter/server.py` per A (passa da neuron internamente).

---

## Piano evolutivo — Goal Neuron (concentrazione)

**Design approvato** (decisioni dell'utente in sessione). Il goal è specifico di Neuron: attivo durante l'uso, resta finché non completo, serve a dare concentrazione e non divagare — analogo al summary di compaction.

### Concetto
- **Focus ≠ Goal**: focus è la modalità di retrieval ("di cosa mi serve"); goal è la direzione ("verso cosa sto andando"). Il goal vive in Neuron, è iniettato nel contesto, resta finché `done`.
- Persistenza: blocco `goal` nel meta del graph (come `session_cache`, models.py:1443) — `{text, status: active|done, progress_note, updated_turn}`. Uno attivo per context.

### Iniezione — 3 livelli di emissione (evitare troppe injection)

| Livello | Contenuto | Costo |
|---|---|---|
| `full` | `GOAL[active]: <testo> — progress: <nota>` | ~30-60 token |
| `pointer` | `g→ <slug 2-4 parole>` | ~8-12 token |
| `none` | — | 0 |

| Evento | Emissione |
|---|---|
| Goal settato/modificato/progress aggiornato in questo turno | `full` |
| `turn % NEURON_GOAL_EVERY == 0` (default **5**) | `full` (refresh, include le note accumulate) |
| Altrimenti | `pointer` |
| `status → done` | `full` una volta, poi goal rilasciato → `none` |
| Nessun goal attivo | `none` |

**Perché `pointer` e non `none` tra i full**: a 8-12 token è quasi gratis e garantisce che anche un turno post-compaction sappia che il goal esiste. `none` è l'ipotesi pura (inject ogni N); `pointer` è la rete di sicurezza. Entrambi testabili.

### Knob di test
- `NEURON_GOAL_EVERY` — cadenza refresh `full` (default 5).
- `NEURON_GOAL_POINTER=0` — spegne il pointer → comportamento puro "inject ogni N".

### Regole di vita
- Il goal **non scade per inattività** (a differenza della WM con TTL) — resta fino a `done`.
- `done` → il goal diventa un **episodio** su un nodo (storia conservata, smette di essere iniettato).
- Goal + WM coesistono: WM inietta `recent` (memoria), il goal inietta direzione (pointer/full) — due righe separate, nessun conflitto.
- Multi-context: un goal per context; i context ereditati mostrano il goal del parent come pointer.

### Aggiornamento
Campo opzionale in `store_turn` (`goal_text`, `goal_status`, `goal_progress`) — l'LLM lo aggiorna quando fa progressi; `status=done` lo rilascia. Zero tool nuovi.

---

## Piano evolutivo — Cloud / Server

**Dopo la working memory (A/B/C) e il goal.** Obiettivo: hostare la suite su un server, farla lavorare al massimo con un team.

### Stato attuale (già pronto)
- **Dati cloud**: neuron e neurag già supportano remote Turso (stesso pattern: neuron db.py:43-45 `TURSO_DATABASE_URL`, neurag db.py:45-48 `NEURAG_TURSO_DATABASE_URL`; `REMOTE_TURSO` gate su URL+token).
- **Config**: `gray-matter cloud` CLI (gruppo Turso, 3 DB: neuron/neurag/gm-bridges, token di gruppo, idempotente, nessuna credenziale a stdout).
- **Gap**: transport è MCP **stdio** (neuron server.py:48, gm server.py:3) + IPC/port-file locale per il control center — niente rete, niente server persistente, niente team.

### Fasi
- **C1 Dati in cloud** (quasi pronto): completare la catena `gray-matter cloud` → venv server con extra `cloud` (libsql-client); verificare `VECTOR_SQL_SUPPORTED` remoto (neuron) e fallback RRF su NeuRAG remoto.
- **C2 Trasporto di rete**: aggiungere transport SSE/HTTP al gateway GM (stdio resta per client locali). Prerequisito per un team che raggiunge la memoria da remoto.
- **C3 Server persistente**: run come servizio (systemd / Win service), healthcheck, log, autenticazione del transport, più client connessi.

### Team (da TencentDB-Agent-Memory, dopo C2)
- Modello: `team` → `agent` (ruolo) → `loadout` (quali asset di memoria riceve). Mappa sul nostro stack: NeuRAG nodes/chunks = assets; loadout = set di context/tier aperti per agente.
- Ownership/version/visibility/ACL: dopo, se serve davvero (Tencent ha `private/team/restricted/agent`).

### Riferimento ispiratore
[TencentDB-Agent-Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory) (branch `feat/server_team`): team memory hub, layer L0-L3, loadout per agente, "You · Set goals / Make decisions".

---

## Come si lanciano le suite

```
& "C:\Users\recla\Desktop\Gray Matter Enviroment\neuron\.venv\Scripts\python.exe" -m pytest gray_matter/tests
```
Con `PYTHONPATH` = `C:\Users\recla\Desktop\Gray Matter Enviroment`. Le 3 suite (neuron/neurag/gray_matter) vanno in **processi separati** (`neuron/tests/_mockdeps.py` inietta fake in `sys.modules` che trapassano ai peer in un processo condiviso).

Dopo ogni edit di file `.md` con contenuto italiano: riapplicare UTF-8 con BOM (vedi AGENTS.md).
