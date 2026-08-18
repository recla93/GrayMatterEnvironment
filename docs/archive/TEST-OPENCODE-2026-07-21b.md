# Test plan B per OpenCode — sessione 2026-07-21 pomeriggio (B-STORE, env model, cloud CLI, opt-out, GUI)

> Appendice a `TEST-OPENCODE-2026-07-21.md` (prereq e venv: sez. 0–2 di quello).
> Verifica i cambiamenti nuovi: bridge 3-tier, `.env` GM, `gray-matter cloud`,
> installer opt-out §6, GUI adattiva + dashboard. PowerShell, `.venv-test` attivo
> (gli install sono `-e`: le modifiche sono già live).

---

## B1. Suite complete (numeri aggiornati)
```powershell
cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment"
python -m pytest .\gray_matter\tests -q
# atteso: 46 passed (in sandbox: 43 passed + 3 skip mcp; in locale gli skip passano)
python -m pytest .\gray_matter\tests\test_bridge_promotion.py .\gray_matter\tests\test_cloud_setup.py .\gray_matter\tests\test_env_loader.py -v
# atteso: 10 passed (3 promotion+migrazione, 3 cloud setup, 4 env loader)
python -m pytest .\Neuron\tests -q     # atteso: 272 passed (invariato)
python -m pytest .\Neurag\tests -q     # atteso: 36 passed (invariato)
```

## B2. Bridge store 3-tier (B-STORE) — tabella + migrazione + CLI
```powershell
# store pulito in un GM_HOME temporaneo
$env:GM_HOME = "$env:TEMP\gmtestB"; Remove-Item $env:GM_HOME -Recurse -Force -ErrorAction SilentlyContinue
python -c "from gray_matter import bridges; print(bridges.add_bridge('kafka','event streaming','test')); print(bridges.bridges_for('kafka')[0]['weight'])"
# atteso: True / 2  (add=1, bridges_for rinforza a 2)
Get-ChildItem "$env:GM_HOME\graymatter"     # atteso: bridges.db (NON bridges.json)
gray-matter bridges                          # atteso: 1 bridge, [w=2] kafka <-> event streaming

# migrazione one-shot da JSON legacy
Remove-Item "$env:GM_HOME\graymatter\bridges.db"
'[{"neuron":"kafka","neurag":"streaming","weight":3,"promoted":true}]' |
  Set-Content "$env:GM_HOME\graymatter\bridges.json" -Encoding utf8
python -c "from gray_matter.bridges import all_bridges; print(all_bridges())"
# atteso: 1 riga kafka<->streaming weight 3 promoted 1
Get-ChildItem "$env:GM_HOME\graymatter"     # atteso: bridges.db + bridges.json.migrated
Remove-Item Env:GM_HOME
```

## B3. Env model — `.env` GM caricato dal daemon, ereditato dai worker
```powershell
$env:GM_HOME = "$env:TEMP\gmtestB"
New-Item -Force -ItemType Directory "$env:GM_HOME\graymatter" | Out-Null
"GM_TEST_VAR=hello-from-gm-env" | Set-Content "$env:GM_HOME\graymatter\.env" -Encoding utf8
python -c "import gray_matter, os; print(os.environ.get('GM_TEST_VAR'))"
# atteso: hello-from-gm-env   (l'import del package carica il .env)
python -c "import os; os.environ['GM_TEST_VAR']='real-wins'; import gray_matter; print(os.environ['GM_TEST_VAR'])"
# atteso: real-wins           (l'env reale vince sempre)
python -c "import os; os.environ['GM_NO_DOTENV']='1'; import gray_matter; print(os.environ.get('GM_TEST_VAR'))"
# atteso: None                (opt-out)
# worker inheritance end-to-end: daemon su + un tool via gateway, poi controlla che
# i worker (figli del daemon) esistano — l'ambiente si propaga per eredità Popen.
python -m gray_matter.cli start; python -m gray_matter.cli status
Remove-Item Env:GM_HOME
```

## B4. `gray-matter cloud` — status/teardown senza rete, setup con turso CLI
```powershell
# senza env né turso: solo status/teardown (innocui)
$env:GM_HOME = "$env:TEMP\gmtestB"
gray-matter cloud status
# atteso: 3 righe [local] neuron/neurag/gm (tier locale)
gray-matter cloud teardown
# atteso: "nessuna env cloud gestita da rimuovere"

# ⚠ VERIFICA NOME SOTTOCOMANDO TOKEN (il codice prova mint poi create):
turso group tokens --help
# se il comando reale NON è né `mint` né `create` → correggere _mint_group_token in gray_matter\cloud.py

# con turso CLI + login (crea/rileva gruppo e 3 DB REALI — ok se già esistenti, è idempotente):
gray-matter cloud setup --group graymatter
# atteso: [ok] su ogni passo; .env scritto in $env:GM_HOME\graymatter\.env; token MAI stampato
gray-matter cloud status        # atteso: 3 righe [cloud]
gray-matter cloud setup --group graymatter
# atteso (2ª run): tutto "esistente (riusato)", "token esistente riusato", .env "già cablato"
Get-Content "$env:GM_HOME\graymatter\.env"   # ispezione: 3 URL + TURSO_AUTH_TOKEN, righe estranee intatte
```

## B5. Bridge su Turso CLOUD (terzo DB `gm_bridges` — mai quello di Neuron/NeuRAG)
```powershell
# dopo B4, oppure a mano:
$env:GM_TURSO_DATABASE_URL = "libsql://<db-gm-bridges>.turso.io"
$env:TURSO_AUTH_TOKEN      = "<group-token>"
python -c "from gray_matter import bridges; print(bridges.REMOTE_TURSO)"          # atteso: True
python -c "from gray_matter import bridges as b; b.add_bridge('cloudtest','nodo remoto','t'); print(b.all_bridges())"
# atteso: riga presente, nessuna eccezione (facade _RemoteConn)
Remove-Item Env:GM_TURSO_DATABASE_URL, Env:TURSO_AUTH_TOKEN -ErrorAction SilentlyContinue
```

## B6. Installer opt-out §6 — parse + standalone + degrade
```powershell
# parse statico dei 4 launcher modificati (obbligatorio: pwsh assente in sandbox)
foreach ($f in ".\Neuron\install.ps1", ".\Neurag\install.ps1") {
  $e=$null; [System.Management.Automation.PSParser]::Tokenize((Get-Content $f -Raw), [ref]$e) | Out-Null
  if ($e.Count) { "FAIL $f — $($e[0].Message)" } else { "OK  $f" }
}
# sh (se hai Git Bash/WSL): sh -n Neuron/install.sh && sh -n Neurag/install.sh

# standalone headless in HOME temporanea (non tocca l'install vero)
$env:NEURON_HOME = "$env:TEMP\neuron-standalone"; $env:GM_OPTIN = "0"
.\Neuron\install.ps1
# atteso: "Installing Neuron STANDALONE...", venv in $env:TEMP\neuron-standalone\.venv,
#         `neuron register --client all` eseguito, exit 0 — NESSUN riferimento a GM
$env:NEURAG_HOME = "$env:TEMP\neurag-standalone"
.\Neurag\install.ps1 --no-gm
# atteso: standalone + doctor + snippet '"neurag": { "command": ".../neurag-mcp.exe" }'
Remove-Item Env:NEURON_HOME, Env:NEURAG_HOME, Env:GM_OPTIN -ErrorAction SilentlyContinue

# prompt interattivo (a mano): .\Neuron\install.ps1 senza flag →
# atteso: warning-deficit + "Install Gray Matter (recommended)? [Y/n]"; 'n' → standalone; INVIO → GM

# degrade §6 (GM non ottenibile → standalone, NON exit 1):
Rename-Item .\gray_matter .\gray_matter_hidden
$env:NEURAG_HOME = "$env:TEMP\neurag-degrade"
.\Neurag\install.ps1 --yes
# atteso: bootstrap fallisce (pre-publish) → "WARNING: could not obtain Gray Matter"
#         → "Falling back to a STANDALONE NeuRAG install" → exit 0
Rename-Item .\gray_matter_hidden .\gray_matter
Remove-Item Env:NEURAG_HOME -ErrorAction SilentlyContinue
```

## B7. GUI adattiva + dashboard (manuale, ~5 min)
```powershell
gray-matter gui
```
- [ ] **Dashboard…** (in cima alla sidebar): componenti ✓, versioni (gray-matter/
      neuron/neurag), stato orchestrator, Activity (pulses/cache/flashes/workers),
      Bridges, righe Tier per componente. Con daemon SPENTO: pannello pieno lo
      stesso, "offline — Start it...".
- [ ] Sidebar: sezione **Memory (Neuron)** (6 voci) e **Knowledge (NeuRAG)**
      (status/tree/query/import/health/doctor) — ogni voce scrive nel log.
- [ ] Orchestrator card: **Full suite** / **Standalone (no bridge)** / Bridges /
      Stats / Doctor. Standalone → `gray-matter status` mostra i server ISOLATED;
      Full suite li riporta collab.
- [ ] **Cloud group…**: Setup/Status/Teardown streammano la CLI nel log.
- [ ] Turso setup… → Save: il log dice "saved to ...\graymatter\.env — restart
      Gray-Matter" (non più cwd).
- [ ] **Adattività**: `pip uninstall neurag -y` → riapri la GUI → card Vault e
      sezione Knowledge SPARITE, Ecosystem mostra "Install" per NeuRAG. Poi
      `pip install -e .\Neurag[dev,turso,cloud,semantic] --find-links .\Neurag\vendor --find-links .\Neuron\vendor`
      → tutto ricompare.

## B8. Cloud senza CLI (`wire`) + install CLI offerta (aggiunti post-audit)
```powershell
# wire: BYO senza turso CLI — parziale, probe, token mai in output
python -m pytest .\gray_matter\tests\test_cloud_setup.py -v   # atteso: 6 passed
$env:GM_HOME = "$env:TEMP\gmtestB"
gray-matter cloud wire --neuron-url "libsql://<db-neuron>.turso.io" --token "<token>"
# atteso: [ok] URL cablata / [ok] probe verified / .env aggiornato / status [cloud] neuron
gray-matter cloud wire --neuron-url "ftp://nope" --token x
# atteso: [!!] URL non valida, exit 1, .env NON toccato per neuron

# install CLI offerta di default (opt-out) — ⚠ VERIFICA CHIAVE:
gray-matter cloud setup --no-cli-install
# atteso (senza turso sul PATH): [!!] turso CLI non trovata + CLI_GUIDE (niente prompt)
gray-matter cloud setup --yes
# atteso: lancia l'installer ufficiale pinnato v0.7.0-pre.22 → "turso CLI installata";
# VERIFICA: turso --version funziona (PATH aggiornato? magari serve nuova shell);
# poi `turso auth login` e setup completo. Se la release/URL non esiste più →
# aggiornare GM_TURSO_CLI_VERSION (o il default in gray_matter\cloud.py).
gray-matter cloud status
Remove-Item Env:GM_HOME
```
- [ ] GUI → Cloud group…: "Install CLI" (con confirm) streamma l'installer; "Guide"
      stampa i comandi; sezione "Manual — NO turso CLI": 3 URL + token → Wire →
      "Wired — restart Gray-Matter"; token svuotato dal campo dopo il save.

---

### Checklist di accettazione (sessione B)
- [ ] GM suite 46 passed; i 10 test nuovi verdi (B1)
- [ ] bridges.db + migrazione one-shot + `gray-matter bridges` ok (B2)
- [ ] `.env` GM: caricato all'import, real-env vince, opt-out ok (B3)
- [ ] `cloud status/teardown` innocui; `setup` idempotente 2 run; nome sottocomando token CONFERMATO o corretto (B4)
- [ ] bridge su Turso cloud (DB `gm_bridges` proprio) (B5)
- [ ] 4 launcher: parse ok, standalone headless ok, prompt ok, degrade senza exit 1 (B6)
- [ ] GUI: dashboard piena anche a daemon spento; sezioni adattive; bottoni modalità (B7)
