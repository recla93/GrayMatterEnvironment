# HANDOFF → Claude Code — verso la release (2026-07-21, da sessione Cowork)

> Verità dal codice, non dai doc vecchi. SSOT di stato: `PROBLEM-REGISTER-2026-07-21.md`.
> Target release: **neuron 6.0.0 · neurag 1.0.0 · gray-matter 1.0.0**.
> Questa sessione (Cowork, tier **sqlite** offline) ha chiuso 3 problemi d'installazione
> segnalati da tempo. Il resto va fatto su Windows/Code: build wheel, pwsh, rename
> lowercase, verifica install reale, tag/push. Il sandbox aveva setuptools 59 offline
> → **niente build wheel possibile qui**.

---

## 1. Fatto in questa sessione (verificato, tier sqlite — suite GM 50 passed / 3 skip)

### #3 Hook — gli asset ora viaggiano nel wheel (SSOT dentro `neuron`)
**Root cause:** i 3 asset handshake stavano in `Neuron/clients/` (radice repo, **fuori** dal
package) e il `package-data` di neuron includeva solo `data/*` e `skills/*`. In un install
standalone di GM `_find_clients_root()` non li trovava → `deploy_hook … asset missing`.

- **Spostati** in `Neuron/src/neuron/clients/…` (SSOT dentro il package):
  `claude-code-hook/`, `cowork-plugin/neuron-guard/`, `opencode-plugin/`.
  Gli `*.example.json` restano in `Neuron/clients/` (sono docs, non asset di deploy).
- `Neuron/pyproject.toml` → `package-data.neuron` += glob espliciti per profondità
  (`clients/*` … `clients/*/*/*/*/*`; niente dipendenza da `**`). **Verificato: 7/7 file catturati.**
- `gray_matter/executor.py` → `_find_clients_root()` riscritto: **primario** via
  `importlib.util.find_spec("neuron")` → `<neuron>/clients` (funziona in wheel E in editable);
  sentinel `_has_assets()` per non restituire mai una dir vuota; fallback dev/legacy.
- `gray_matter/install.ps1` → `GM_NEURON_CLIENTS` prova `src\neuron\clients` poi legacy `clients`.
- `gray_matter/tests/test_executor.py` → costante `ASSETS` alla nuova path (fallback legacy).
- **Verificato:** resolver risolve tutti e 3 gli `HOOK_ASSETS`; test executor/installer/paths/uninstaller verdi.

### #1 Launcher — vera scorciatoia Windows `.lnk` (non più `.cmd`)
- `gray_matter/install.ps1`: al posto di `Gray Matter GUI.cmd` crea **`Desktop\Gray Matter.lnk`**
  (via `WScript.Shell`), target **`pythonw.exe`** (niente flash di console), icona generata
  best-effort da `neuron-logo.png` con `System.Drawing` → `%LOCALAPPDATA%\graymatter\gray-matter.ico`,
  fallback all'icona di `python.exe`. Rimuove il vecchio `.cmd`. Se il COM manca → fallback `.cmd`.
- mac/linux (`install.sh`) resta con `.command` (già corretto).
- ⚠ **DA FARE su Windows** (qui niente pwsh): parse-check + prova reale (doppio click → apre GUI, icona ok).

### #2 Comandi GUI — niente più dipendenza dal PATH
**Root cause:** la GUI faceva shell-out ai **console-script** (`gray-matter`/`neuron`/`neurag`),
risolti accanto a `sys.executable`; se non in `Scripts/` (o peer non installati nel venv GM) →
`command not found`. Anche `gray-matter` falliva perché il venv aveva un `webgui.py` pre-fix.

- `gray_matter/webgui.py`: nuovo `_MODULE_FOR` + `_resolve_argv()`. I **nostri** tool diventano
  `[sys.executable, -m, <modulo>]` (`gray-matter`→`gray_matter.cli`, `neuron`→`neuron`,
  `neurag`→`neurag.cli`); i tool **esterni** (git, cloudflared, powershell) restano via `_exe`/PATH.
  Applicato ai 3 punti: `_stream`, `_run_seq`, `_open_terminal`.
- **Verificato:** `_resolve_argv` mappa correttamente; `python -m neurag.cli status`, `-m neuron`,
  `-m gray_matter.cli` funzionano; suite GM 50 passed.

**File toccati:** `Neuron/pyproject.toml`, `Neuron/src/neuron/clients/**` (mossi),
`gray_matter/executor.py`, `gray_matter/install.ps1`, `gray_matter/webgui.py`,
`gray_matter/tests/test_executor.py`.

---

## 2. Da fare su Code (ordine micro→macro)

Nota struttura: `Neuron`, `Neurag`, `gray_matter` sono **3 repo git separati**; la cartella
contenitore `Gray Matter Enviroment` **non** è un repo. Quindi rinominare la cartella `Neuron`→`neuron`
è un rename di filesystem del contenitore, **non** tocca il git interno del repo.

### A. Rename lowercase delle cartelle (fix D2 case-sensitivity)
Perché: `Neurag` (cartella) vs `neurag` (import) rompe collection test e `python -m neurag.cli` su
Linux/CI (su Windows è mascherato dal filesystem case-insensitive). Su Windows il rename **case-only**
richiede il doppio passo:

```powershell
cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment"
Rename-Item Neuron neuron_tmp; Rename-Item neuron_tmp neuron
Rename-Item Neurag neurag_tmp; Rename-Item neurag_tmp neurag
```

Poi allinea i riferimenti case-sensitive dentro **gray_matter** (oggi ancora `"Neuron"`/`"Neurag"`):
- `gray_matter/executor.py` → i fallback dev-layout (righe ~252–266) `"Neuron"` → `"neuron"`.
- `gray_matter/webgui.py` → `_PEERS["neuron"]["dir"]` (`"Neuron"`→`"neuron"`) e `vendor = _ENV_ROOT / "Neuron" / "vendor"` (riga ~379).
- `gray_matter/tests/test_executor.py` → `REPO / "Neuron" / …` → `"neuron"`.

(Non bloccano l'install reale — il resolver primario è `importlib` — ma vanno messi coerenti.)

### B. Build dei 3 wheel (setuptools≥68 + `build`)
- **neuron:** `cd neuron && python -m build --wheel`. Poi **verifica che gli asset ci siano**:
  ```python
  import zipfile, glob
  z = zipfile.ZipFile(glob.glob('dist/*.whl')[-1])
  hits = [n for n in z.namelist() if '/clients/' in n]
  assert len(hits) == 7, hits          # 7 file handshake attesi
  print('OK clients nel wheel:', len(hits))
  ```
- **neurag:** build con **pyturso vendored** (vedi `neurag/vendor/` + `neurag/.github/workflows/release.yml`,
  job `build-pyturso-win` 3.10–3.14). Locale: `pip install --no-index --find-links vendor pyturso` →
  `python -m build --wheel`. Extra `[cloud]`/`[embed]` da pyproject.
- **gm:** `cd gray_matter && python -m build --wheel` (deve spedire `webgui.html`).

### C. pwsh parse-check + prova launcher (mia modifica `.lnk`)
```powershell
[System.Management.Automation.Language.Parser]::ParseFile(
  "gray_matter\install.ps1", [ref]$null, [ref]$errs); $errs
```
Poi install reale e conferma `Desktop\Gray Matter.lnk` (doppio click apre GUI, icona corretta).

### D. Verifica install reale dei 3 fix (venv pulito, i 3 wheel installati)
`python -m gray_matter.cli install` →
- **deploy_hook = OK** per claude-code / cowork / opencode (niente `asset missing`); controlla
  `~/.claude/hooks/neuron_sessionstart_hook.py` + `settings.json`, plugin cowork, plugin opencode + `opencode.json`.
- **GUI:** Start/Stop/Bridge/Tunnel/`neurag status`/`neuron overview` → non più `command not found`.

### E. Blocker di correttezza aperti (dal PROBLEM-REGISTER, tier Turso/locale)
- **B1 (L2)** `store_turn → open: NotFound` su Turso condiviso: verdetto finale sul **daemon vivo con
  pyturso reale** (race multi-processo WAL/sidecar) + **L2 sotto 2 client** (Desktop+Cowork) simultanei.
- **Cloud Turso reale:** DB separati — `TURSO_*` (neuron) vs `NEURAG_TURSO_*`/`GM_TURSO_*` (neurag/bridge) —
  da provare con credenziali vere.

### F. Git / tag / push (ULTIMO, dopo tutto verde)
Commit dei working tree (docs, LICENSE, install.*), poi tag `v6.0.0` (neuron) · `v1.0.0` (neurag) ·
`v1.0.0` (gm) → attivano i `release.yml`.

---

## 3. Cosa mi serve indietro (verdetti da riportare)
1. Esito **deploy_hook** reale sui 3 client dopo build+install.
2. **pwsh** parse-check `install.ps1` verde + conferma `.lnk` (icona).
3. Verdetto **B1/L2** e **cloud reale** (gli unici blocker di correttezza rimasti).

## 4. Note / rischi
- "rinomina tutto in lowercase": le **cartelle** sono in §A (funzionale, fallo). I **doc in CAPS**
  (`ARCHITETTURA.md`, `HANDOFF-*`, `AUDIT-*`, …) sono cosmetici e hanno link incrociati → consiglio un
  **pass separato** con aggiornamento dei link, non insieme alla release.
- Sandbox = solo tier sqlite; il verdetto Turso/L2/cloud è **solo locale**.
