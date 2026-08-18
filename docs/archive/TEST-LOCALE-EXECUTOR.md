# Test locale — executor install/uninstall (TODO 2) + repro L2

> PowerShell, dalla radice `Gray Matter Enviroment`, venv attivo.
> Ordine pensato per fermarsi al primo rosso. I comandi `install` scrivono nei
> config reali dei client (backup `.bak` automatico accanto a ogni JSON).

## 0. Prerequisiti (una volta)

```powershell
pip install -e .\gray_matter
pip install -e .\Neuron
pip download pytest -d Neuron\vendor\dev   # vendor per pytest offline in sandbox
```

## 1. Suite pytest

```powershell
python -m pytest gray_matter\tests -q     # attesi ~31 verdi (24 + 7 executor)
python -m pytest Neuron\tests -q          # regressione: attesi 253 verdi
```

## 2. Install — prima dry-run, poi reale

```powershell
gray-matter install --dry-run             # leggere le azioni: reap? register? deploy_hook?
gray-matter install
```

Verifiche post-install (tutti devono esistere / contenere quanto indicato):

```powershell
type $env:LOCALAPPDATA\graymatter\manifest.json          # components + hooks tracciati
dir  $env:USERPROFILE\.claude\hooks\neuron_sessionstart_hook.py
type $env:USERPROFILE\.claude\settings.json              # hooks.SessionStart con il nostro comando, UNA sola entry
dir  $env:USERPROFILE\.claude\plugins\neuron-guard       # plugin cowork copiato
dir  $env:USERPROFILE\.config\opencode\plugins\neuron-handshake.mjs
type $env:USERPROFILE\.config\opencode\opencode.json     # array "plugin" con neuron-handshake
gray-matter doctor                                        # ogni client: solo gray-matter, niente neuron/neuron5/neurag
```

Idempotenza: rilanciare `gray-matter install` → nessun duplicato in
`settings.json` (sempre una sola entry SessionStart) e manifest invariato.

## 3. Handshake nelle app

Riavviare Claude Code / Cowork / OpenCode → a inizio sessione deve comparire la
loop-guidance `pre_turn`/`store_turn` (hook attivo). In Cowork il plugin copiato
potrebbe richiedere l'enable manuale nelle impostazioni.

## 4. Uninstall — solo dry-run per ora

```powershell
gray-matter uninstall --dry-run    # controllare: reap → deregister → remove_hook → remove_code → ask_data
```

NON eseguire l'uninstall reale (l'ambiente serve). L'`ask_data` deve comparire
per graph/bridges/knowledge, mai rimozione silenziosa.

## 5. Repro bug L2 — `store_turn → open: NotFound` (riprodotto oggi via GM)

`pre_turn` funziona, `store_turn` fallisce per tutta la sessione. Serve il traceback:

```powershell
# 1) log del daemon GM mentre fallisce
dir $env:LOCALAPPDATA\graymatter\logs
# rilanciare da Cowork uno store_turn, poi copiare le ultime righe del log più recente

# 2) store isolato direttamente su Neuron (bypassa GM: dice se il bug è di Neuron o del proxy)
$env:NEURON_NO_DOTENV=1; $env:NS_GRAPHS_DIR="$env:TEMP\neuron-l2"
python -c "from neuron.server import *; print('import ok')"   # poi test store via console/pytest mirato
```

Incollare a Fable: output dei comandi, traceback dal log, esito idempotenza.
