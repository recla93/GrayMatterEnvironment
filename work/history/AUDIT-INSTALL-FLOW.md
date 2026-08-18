# AUDIT — Flusso Installazione Neuron + NeuRAG + Gray Matter

> Analisi completa del sistema di installazione del trio.
> Generato: 2026-07-23. Scope: Windows (install.ps1 / install.cmd), con note su Linux/macOS.

---

## 1. Architettura di deploy

```
                    ┌─────────────────────┐
                    │   install.cmd       │  (click-and-go, double-click)
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   install.ps1       │  (logica unificata, tutti e 3 i tool)
                    │   (gray_matter/)    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │   GM     │    │  Neuron  │    │  NeuRAG  │
        │ pip inst │    │ pip inst │    │ pip inst │
        │  solo GM │    │ +GM peer │    │ +GM peer │
        └──────────┘    └──────────┘    └──────────┘
              │                │                │
              ▼                ▼                ▼
        ┌─────────────────────────────────────────┐
        │   ONE venv: %LOCALAPPDATA%\gray-matter\.venv
        └─────────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        register()       register()       register()
        SOLO GM nei      (già fatto)      (già fatto)
        6 client MCP
```

---

## 2. Flusso install — Gray Matter (entry point: `install.cmd` → `install.ps1`)

### 2.1 Cosa fa adesso

| Fase | Operazione | Note |
|------|-----------|------|
| **0** | Consent dialog GM (solo da Neuron/NeuRAG) | Da GM direttamente: niente dialog, install diretto |
| **1** | Trova Python 3.10+ | `python` → `py -3.x` → winget → python.org |
| **2** | Crea venv `%LOCALAPPDATA%\gray-matter\.venv` | Plan A: stdlib venv, Plan B: virtualenv |
| **3** | Installa Gray Matter | `pip install [--force-reinstall --no-deps] ./gray_matter` |
| **4** | Installa Neuron (se sibling/bundled) | `pip install --find-links vendor/ ./neuron` |
| **5** | Installa NeuRAG (se sibling/bundled) | `pip install --find-links vendor/ ./neurag` |
| **6** | Best-effort: pyturso, pywebview, fastembed | Mai bloccante, fallback a tier inferiori |
| **7** | `gray-matter.cli install` → register + hooks + manifest | **SOLO GM** nei 6 client |
| **8** | Record path sorgente (SoC) | Ogni componente registra il proprio source dir |
| **9** | Crea shortcut Desktop + lancia GUI | `pythonw.exe -m gray_matter.cli gui` |

### 2.2 Verifica con requisiti utente

| Requisito | Stato | Dettaglio |
|-----------|-------|-----------|
| Controlla install esistenti | **PARZIALE** | `detect_state()` controlla manifest + client entries, ma non chiede "repair?" — va dritto all'install |
| Dialog repair (sì/no/quale) | **ASSENTE** | Nessuna logica di repair mode interattivo da install.cmd. Il flag `-Force` esiste ma va passato esplicitamente, non chiesto |
| Registrazione collaborativa (non standalone) | **OK** | `register(gateway=True)` iscrive SOLO GM, i peer restano managed workers |
| GUI sul Desktop | **OK** | Shortcut `.lnk` con icona Neuron, target `pythonw.exe -m gray_matter.cli gui` |
| Apertura GUI al termine | **OK** | Ultima riga di install.ps1: `& $VPy -m gray_matter.cli gui` |
| Fallback dipendenze | **OK** | pyturso/sqlite3 tier, pywebview/browser, fastembed/lessicale |

---

## 3. Flusso install — Neuron standalone/GM

### 3.1 Cosa fa adesso

| Fase | Operazione | Note |
|------|-----------|------|
| **0** | Consent dialog: "Install Gray Matter?" [Y/n] | Solo Y/n — manca l'opzione "Standalone" esplicita |
| **1a** | Se No → `Install-Standalone` | Venv proprio (`%LOCALAPPDATA%\neuron\.venv`), registra SE STESSO nei client |
| **1b** | Se Sì → cerca GM locale/sibling/remote/PyPI | Delega a `gray_matter/install.ps1` con `GM_PEER_DIR=$Here` |
| **2** | Se GM non trovato → degrada a standalone | Non esce con errore |
| **3** | Standalone: venv separato + `neuron register --client all` | Registra `neuron` (non `neuron5`) nei client |
| **4** | GUI: `neuron gui --shortcut-only` | Crea icona Desktop, non apre GUI |

### 3.2 Verifica con requisiti utente

| Requisito | Stato | Dettaglio |
|-----------|-------|-----------|
| 3 opzioni: Sì / No / Standalone | **NO** | Solo 2: Sì (con GM) / No (standalone). Mancano le 3 opzioni |
| Se No: controlla se GM è già installato | **NO** | Se l'utente dice "No", fa standalone senza controllare se GM c'è |
| Se GM installato: register al gateway | **NO** | Non c'è logica "No maGMc'è → registra a gateway" |
| Se No + GM non installato: standalone | **OK** | Lo fa sempre in `Install-Standalone` |
| Se Sì + GM presente: installa con GM | **OK** | Delega a `gray_matter/install.ps1` |
| Se Sì + GM assente: installa GM | **OK** | Bootstrap remoto (GitHub/PyPI) |
| GUI con solo Neuron | **PARZIALE** | Crea icona "Neuron", ma la GUI è sempre la full `gray_matter.webgui` |
| Dipendenze con fallback | **OK** | --find-links vendor/ per pyturso |

---

## 4. Flusso install — NeuRAG standalone/GM

### 4.1 Identico a Neuron

Stessa struttura, stesse opzioni, stessi problemi. Differenze:
- Venv: `%LOCALAPPDATA%\neurag\.venv`
- Consiglio standalone: `"neurag": {"command": "..."}` (l'utente deve aggiungere al client a mano)
- `neurag doctor` invece di `neuron register --client all`
- **pyturso NON è nelle dependencies base** — solo `[turso]` extra

### 4.2 Verifica con requisiti utente

| Requisito | Stato | Dettaglio |
|-----------|-------|-----------|
| pyturso mandatory con fallback sqlite | **NO** | pyturso è `[turso]` extra, non in `dependencies`. Se non installato, db.py opera su sqlite3 tier senza warning |
| 3 opzioni: Sì / No / Standalone | **NO** | Stesso problema di Neuron |
| Wheel in vendor/ | **OK** | `neurag/vendor/` contiene pyturso 0.6.1 per cp310-314 win_amd64 |

---

## 5. Problemi critici

### CRIT-1: pyturso non è mandatory in NeuRAG

**Dove**: `neurag/pyproject.toml:11-21`

```toml
dependencies = [
    "mcp>=1.28.0,<2.0",
    # NIENTE pyturso qui (decisione 2026-07-20)
]
[project.optional-dependencies]
turso = ["pyturso==0.6.1"]
```

**Problema**: pyturso è opzionale. L'install base funziona su sqlite3 senza vector SQL. Ma:
- Il tier sqlite3 NON fa vector search (solo keyword match) → qualità retrieval inferiore
- L'utente non sa che sta usando un tier degradato
- L'installer (`gray_matter/install.ps1:185-191`) prova a installarlo come best-effort, ma se fallisce nessuno lo sa

**Fix richiesto**: pyturso nelle `dependencies` con fallback a sqlite3 nel codice (già presente in `db.py:20-24`). Il fallback è l'eccezione, non il default.

### CRIT-2: Dialog install a solo 2 opzioni (manca "Standalone" come scelta esplicita)

**Dove**: `neuron/install.ps1:30-36`, `neurag/install.ps1:30-36`

```powershell
$ans = Read-Host "Install Gray Matter (recommended)? [Y/n]"
if ($ans -match '^(n|no)$') { $WantGm = $false }
```

**Problema**: L'utente vede solo "Y/n". Le 3 opzioni richieste sono:
- **Sì** → installa con GM (gateway model)
- **No** → standalone + controlla se GM c'è → se sì registra al gateway, se no resta standalone
- **Standalone** → esplicitamente standalone, stesso comportamento di "No"

**Impatto**: UX confusa. "No" significa "non voglio GM" ma non controlla se GM c'è già.

### CRIT-3: Nessun dialog "repair" all'avvio di install.cmd

**Dove**: `gray_matter/install.ps1` (tutto il file)

**Problema**: Se l'utente double-clicka install.cmd quando la suite è già installata:
- La version check (`Test-AlreadyInstalled`) salta il pip install → "already installed - skipping"
- Ma non chiede "vuoi fare repair?" → l'utente vede "Done" senza capire se è effettivamente riparato
- Il flag `-Force` esiste ma va passato da riga di comando, non chiesto

**Impatto**: UX incompleta. L'utente non sa se può fare repair dal doppio click.

---

## 6. Problemi medi

### MED-1: Version mismatch nel fallback remoto GM

**Dove**: `neuron/install.ps1:83`, `neurag/install.ps1:83`

```powershell
$GmVersion = if ($env:GM_VERSION) { $env:GM_VERSION } else { "1.0.0" }
```

Ma `gray_matter/pyproject.toml` ha `version = "1.1.2"`. Il fallback scarica `v1.0.0` da GitHub (inesistente) → fallisce silenziosamente → degrada a standalone.

**Fix**: `$GmVersion` dovrebbe leggere da `gray_matter/pyproject.toml` o defaultare all'ultima release nota.

### ~~MED-2: Standalone Neuron registra "neuron" non "neuron5"~~ — RISOLTO

**Stato**: L'istanza deve chiamarsi `neuron` (non `neuron5`). Il codice a `neuron/install.ps1:62` usa già lo slug corretto `neuron`. Nessuna modifica necessaria.

**Nota storica**: il problema era stato segnalato perché lo slug nei client era `neuron5`, ma la decisione è di usare `neuron` come nome definitivo. Va aggiornato anche `neuron/config.py` se ancora usa `neuron5`.

### MED-3: NeuRAG standalone non registra nei client

**Dove**: `neurag/install.ps1:62-68`

```powershell
& (Join-Path $Venv "Scripts\neurag.exe") doctor
# ... stampa istruzioni per registrazione manuale ...
```

L'utente deve copiare-incollare la config a mano. A differenza di Neuron (che fa `register --client all`), NeuRAG non si registra automaticamente.

### MED-4: Nessuna verifica post-install nel dialog standalone

**Dove**: `neuron/install.ps1:62`, `neurag/install.ps1:62`

Neuron fa `register --client all` (OK). NeuRAG fa solo `doctor` (check passivo). Nessuno dei due verifica che la registrazione sia effettivamente riuscita nei 6 client.

### MED-5: Shortcut Desktop fallback a .cmd su COM non disponibile

**Dove**: `gray_matter/install.ps1:278-281`

Se `WScript.Shell` COM non è disponibile (raro ma possibile), crea un `.cmd` invece di `.lnk`. Il `.cmd` ha una console che lampeggia all'apertura.

### MED-6: Nessun supporto `--json` nell'installer PS1

**Dove**: `gray_matter/install.ps1` (tutto)

La GUI ha bisogno di output JSON per il pannello Install/Repair. L'installer attuale è solo testo umano. La GUI non può invoking-ly leggere lo stato.

---

## 7. Problemi bassi

### BASS-1: `vendor/dev/tomli` solo cp313

**Dove**: `neuron/vendor/dev/`

Contiene `tomli-2.4.1-cp313-cp313-win_amd64.whl` ma manca per cp310, cp311, cp312. Pytest su Python <3.11 richiede `tomli`.

### BASS-2: `.neuron/project.json` nella root workspace

**Dove**: `.neuron/project.json`

Traccia il project ID per Neuron. Se la root workspace è anche una cartella di lavoro, questo file potrebbe essere confuso con un progetto Neuron reale.

### BASS-3: `_gm_vendor/` in neurag va ricostruito a ogni release GM

**Dove**: `neurag/_gm_vendor/`, `neuron/_gm_vendor/`

Whl di Gray Matter per bootstrap offline. Se GM viene aggiornato, questi diventano stale. Va automatizzato nel release workflow.

### BASS-4: install.sh usa `exec sh` per delegare a GM

**Dove**: `neuron/install.sh:61`, `neurag/install.sh:61`

```sh
[ -f "$gm/install.sh" ] && { GM_PEER_DIR="$HERE" exec sh "$gm/install.sh" "$@"; }
```

`exec` sostituisce il processo corrente → se GM installer fallisce, il fallback standalone (riga 101-104) non viene mai raggiunto. Dovrebbe essere `sh "$gm/install.sh" "$@"` (senza exec) con un check di exit code.

---

## 8. Audit coesione

### 8.1 Duplicazione Neuron ↔ NeuRAG installer

`neuron/install.ps1` e `neurag/install.ps1` sono **quasi identici** (132 righe ciascuno, ~90% identico). Le uniche differenze:
- Nome del tool
- Testo del dialog
- Funzione standalone: `register --client all` vs `doctor` + manuale
- Slug: `neuron` vs `neurag`

**Proposta**: unificare in un unico `install-peer.ps1` parametrico, invocato da `install.cmd` con `$ToolName`.

### 8.2 GM installer ha 287 righe con molta logica

`gray_matter/install.ps1` è il cuore. Contiene:
- Ricerca Python
- Creazione venv
- Idempotenza version check
- Install GM + peer
- Best-effort tier (pyturso, pywebview, fastembed)
- Gateway registration
- Record env
- Desktop shortcut
- Apertura GUI

Tutto in un solo file. Funziona, ma difficile da testare e manutenere. La logica di business è già in `installer.py` / `executor.py` (Python), ma l'installer PowerShell non li usa — riscrive tutto in shell.

### 8.3 Nessun uninstalled state consistente

Lo standalone install di Neuron usa `%LOCALAPPDATA%\neuron\.venv`, GM usa `%LOCALAPPDATA%\gray-matter\.venv`. Se entrambi installati, ci sono 2 venv separati. Il modello GM-centric (1 venv) entra in conflitto con lo standalone (1 venv per tool).

**Impatto**: se l'utente installa Neuron standalone poi decide di aggiungere GM, l'installer GM crea un NUOVO venv in `%LOCALAPPDATA%\gray-matter\.venv` e reinstalla tutto lì. Il vecchio venv di Neuron resta orfano.

### 8.4 Manifest non traccia il venv

Il manifest (`manifest.json`) traccia componenti, client, hooks — ma NON il path del venv. L'uninstall non può rimuovere il venv creato dall'installer.

---

## 9. Riepilogo priorità

| # | Severità | Problema | Fix consigliato |
|---|----------|----------|-----------------|
| CRIT-1 | **ALTA** | pyturso non mandatory in NeuRAG | Aggiungere `pyturso==0.6.1` alle `dependencies` |
| CRIT-2 | **ALTA** | Dialog 2 opzioni (manca "Standalone") | Cambiare dialog a 3 opzioni: `[S]ì / [N]o (standalone) / [D]ettagli` |
| CRIT-3 | **ALTA** | Nessun dialog repair da install.cmd | Aggiungere check esistenza + prompt repair |
| MED-1 | **MEDIA** | Version mismatch fallback remoto GM | Leggere versione da pyproject.toml |
| MED-2 | ~~**MEDIA**~~ | ~~Standalone Neuron registra slug errato~~ | **RISOLTO** — slug `neuron` è corretto |
| MED-3 | **MEDIA** | NeuRAG standalone non registra | Aggiungere `neurag register` automatico |
| MED-4 | **MEDIA** | Nessuna verifica post-install | Aggiungere `doctor` o `clients.doctor()` |
| MED-5 | **BASSA** | Shortcut .cmd fallback | Accettabile, best-effort |
| MED-6 | **BASSA** | Nessun --json nell'installer | Aggiungere per la GUI |
| BASS-1 | **BASSA** | tomli mancante per cp310-312 | Aggiungere wheel mancanti |
| BASS-2 | **BASSA** | .neuron/project.json nella root | Ignorabile |
| BASS-3 | **BASSA** | _gm_vendor stale | Automatizzare nel release |
| BASS-4 | **BASSA** | exec sh blocca fallback | Rimuovere `exec` |

---

## 10. Flusso install ideale (target)

### Gray Matter (install.cmd)
```
Double-click install.cmd
  → Controlla install esistenti (manifest + client entries)
  → Se già installato:
      "Suite già installata. Cosa vuoi fare?"
      [1] Aggiorna/ripara tutto
      [2] Ripara solo Neuron
      [3] Ripara solo NeuRAG
      [4] Annulla
  → Se non installato:
      Installa GM + Neuron + NeuRAG (come ora)
  → Registra SOLO GM nei client (gateway model)
  → Crea shortcut Desktop + apri GUI
```

### Neuron (install.cmd)
```
Double-click install.cmd
  → Dialog 3 opzioni:
      "Install Gray Matter (recommended)?"
      [S]ì — installa Neuron + Gray Matter (gateway)
      [N]o — standalone (controlla se GM c'è → registra al gateway se sì)
      [D]ettagli — spiega cosa perdi senza GM
  → Installa Neuron
  → Se Sì + GM presente: delega a GM installer
  → Se Sì + GM assente: bootstrap GM
  → Se No + GM presente: registra Neuron al gateway
  → Se No + GM assente: standalone, registra Neuron direttamente
  → Crea shortcut Desktop "Neuron"
```

### NeuRAG (install.cmd)
```
Stesso flusso di Neuron, con:
  → Registrazione automatica nei client (come Neuron)
  → pyturso nelle dependencies (mandatory con fallback)
```

**Nota**: Lo slug dell'istanza Neuron è `neuron` (non `neuron5`). Va verificato che `neuron/config.py` sia allineato.

---

## 11. Bug verificati con riferimenti a righe

### BUG-1: `$ErrorActionPreference = "Stop"` uccide i fallback

**Dove**: `gray_matter/install.ps1:19`, `neuron/install.ps1:12`, `neurag/install.ps1:12`

```powershell
$ErrorActionPreference = "Stop"
```

**Problema**: Qualsiasi comando nativo (python, pip) che scrive su stderr — anche solo un warning — genera un `NativeCommandError`. Con `ErrorActionPreference = "Stop"`, PowerShell lo trasforma in un'eccezione terminante che aborte lo script **prima** che il codice raggiunga il check `$LASTEXITCODE`.

**Effetto sui fallback**:

| Riga | Codice | Cosa succede con "Stop" |
|------|--------|------------------------|
| `install.ps1:102` | `& $PyExe -m venv $Venv` | Se python scrive un warning su stderr → script muore. La riga 103 (fallback virtualenv) non viene mai eseguita |
| `install.ps1:141` | `& $VPy -m pip install ...` | Se pip scrive un warning su stderr → script muore. La riga 142 (retry --no-cache-dir) non viene mai raggiunta |
| `neuron/install.ps1:49` | `& $py -m venv $Venv` | Stesso problema: se venv fallisce con output su stderr, la riga 50 (check + error message) non viene mai eseguita |

**Fix**:
```powershell
# opzione A: degradare a Continue (perde protezione su errori reali)
$ErrorActionPreference = "Continue"

# opzione B (consigliata): tenere Stop ma silenziare stderr sui comandi nativi
& $PyExe @PyArgs -m venv $Venv 2>$null
```

---

### ~~BUG-2: Neuron standalone registra slug `neuron` invece di `neuron5`~~ — RISOLTO

**Stato**: L'istanza si chiama `neuron` (non `neuron5`). Il codice a `neuron/install.ps1:62` è già corretto: usa lo slug `neuron`. Nessuna modifica necessaria.

**Nota storica**: era stato segnalato come bug perché ci si aspettava `neuron5`, ma la decisione è di usare `neuron` come nome definitivo. Va verificato che `neuron/config.py` sia allineato.

---

### BUG-3: NeuRAG standalone non si registra nei client

**Dove**: `neurag/install.ps1:62-68`

```powershell
& (Join-Path $Venv "Scripts\neurag.exe") doctor
# ... stampa istruzioni manuali ...
Write-Host "  `"neurag`": { `"command`": `"$Mcp`" }"
```

**Problema**: A differenza di Neuron (che fa `register --client all`), NeuRAG esegue solo `doctor` e stampa istruzioni manuali. L'utente deve copiare-incollare la config in ogni file di configurazione dei client.

**Fix**:
```powershell
& (Join-Path $Venv "Scripts\neurag.exe") register --client all
```
Oppure, se `neurag register` non esiste, aggiungerlo al CLI di NeuRAG.

---

### BUG-4: Dialog install a 2 opzioni invece di 3

**Dove**: `neuron/install.ps1:30-36`, `neurag/install.ps1:30-36`

```powershell
$ans = Read-Host "Install Gray Matter (recommended)? [Y/n]"
if ($ans -match '^(n|no)$') { $WantGm = $false }
```

**Problema**: Le 3 opzioni richieste sono `[S]ì / [N]o (standalone) / [D]ettagli`. Attualmente "No" non controlla se GM è già installato → se GM c'è, l'utente perde la possibilità di registrarsi al gateway.

**Fix**:
```powershell
Write-Host "`nInstall Gray Matter (recommended)?"
Write-Host "  [S]ì — installa Neuron + Gray Matter (gateway)"
Write-Host "  [N]o — standalone (controlla se GM è già installato)"
Write-Host "  [D]ettagli — cosa perdi senza GM"
$ans = Read-Host "Scelta"
switch -Regex ($ans) {
    '^(s|si|sì|y|yes|$)' { $WantGm = $true }
    '^(d|dettagli)$'     { /* stampa dettagli, poi re-prompt */ }
    default               { $WantGm = $false }
}
# Dopo la scelta "No": controlla se GM esiste
if (-not $WantGm) {
    $gmCheck = Find-Peer @("gray_matter")
    if ($gmCheck) {
        Write-Host "Gray Matter è già installato. Registrazione al gateway..."
        # register neuron al gateway
    }
}
```

---

### BUG-5: Nessun dialog repair da install.cmd (GM)

**Dove**: `gray_matter/install.ps1:134-148`

```powershell
if ((-not $Force) -and (Test-AlreadyInstalled "gray-matter" $Here)) {
    Write-Host "Gray-Matter $(Get-SrcVersion $Here) already installed - skipping."
} else {
    # ... install ...
}
Write-Host "Done."
```

**Problema**: Se l'utente double-clicka install.cmd su una install esistente, vede "already installed - skipping" e "Done" senza possibilità di fare repair. Il flag `-Force` esiste ma va passato esplicitamente da CLI.

**Fix**:
```powershell
if ((-not $Force) -and (Test-AlreadyInstalled "gray-matter" $Here)) {
    Write-Host "Gray-Matter $(Get-SrcVersion $Here) already installed."
    if ([Environment]::UserInteractive) {
        $ans = Read-Host "Vuoi riparare/aggiornare? [s/N]"
        if ($ans -match '^(s|si|sì|y|yes)$') { $Force = $true }
        else { Write-Host "Done (nothing changed)."; exit 0 }
    } else { exit 0 }
}
```

---

### BUG-6: `pip install` con `-q` nasconde tutti gli errori

**Dove**: `gray_matter/install.ps1` — verificato che la riga 145 NON usa `-q`

```powershell
# 145: & $VPy -c "import sys;sys.stderr=sys.stdout;import gray_matter"
```

**Nota**: Questo bug era stato segnalato ma **non è presente** nel codice attuale. La verifica ha confermato che la riga 145 redirecta stderr→stdout dentro Python, non usa `-q`. Il problema era stato erroneamente identificato.

---

## 12. Flussi non chiari / overlapping

### 12.1 Due venv in conflitto

Lo standalone usa `%LOCALAPPDATA%\neuron\.venv` (o `neurag\.venv`). Il modello GM usa `%LOCALAPPDATA%\gray-matter\.venv`. Se un utente installa Neuron standalone poi GM, ci sono **2 venv separati**. Il venv orfano di Neuron non viene rilevato né rimosso.

**Flusso attuale**:
```
1. Install Neuron standalone → venv: %LOCALAPPDATA%\neuron\.venv
2. Install GM → venv: %LOCALAPPDATA%\gray-matter\.venv (NUOVO)
3. Neuron dentro GM venv registra "neuron5" nei client
4. Neuron nel venv standalone registra "neuron" nei client
5. CONFLITTO: due entry "neuron" nei client MCP
```

**Flusso ideale**: GM installer dovrebbe rilevare il venv standalone esistente e chiedere se unificarlo.

### 12.2 `install.cmd` vs `install.ps1` — doppia entry point

Tutti e 3 i componenti hanno sia `install.cmd` (click-and-go) sia `install.ps1` (CLI). Ma:
- `install.cmd` non passa `--json` → la GUI non può leggere lo stato
- `install.cmd` non ha parametri → non si può fare repair da doppio click
- `install.ps1` ha `-Force` ma nessun dialog interattivo per chiederlo

### 12.3 Peer forwarding `@Fwd` vs `@args`

I peer (Neuron/NeuRAG) filtrano gli argomenti in `$Fwd` (rimuovendo `-f`/`--force` e aggiungendo `-Force`), poi chiamano:
```powershell
& powershell -ExecutionPolicy Bypass -File $inst @Fwd
```

Ma `@Fwd` è un array PowerShell. Quando viene passato a un nuovo processo PowerShell come argomenti di `powershell.exe`, viene serializzato come stringhe separate. Questo funziona, ma è fragile: se un argomento contiene spazi, potrebbe essere splittato erroneamente.

---

## 13. UX best practices per installer

### 13.1 Sempre visibile: cosa è appena successo

L'utente deve **sempre** vedere un riepilogo alla fine:
```
✓ Gray Matter 1.1.2 installed
✓ Neuron 3.3.0 installed
✓ NeuRAG 0.6.1 installed
✓ Registered in: Claude Desktop, Cursor, OpenCode
✓ Desktop shortcut: "Gray Matter"
→ Restart your AI apps to load the servers.
```

**Stato attuale**: solo "Done. Restart your AI apps." — nessun riepilogo dei componenti installati.

### 13.2 Errore = azione, non solo messaggio

Ogni errore dovrebbe dire **cosa fare dopo**:
```
✗ Python 3.10+ non trovato.
  → Installa da https://www.python.org/downloads/
  → Oppure: winget install Python.Python.3.12
```

**Stato attuale**: "ERROR: need Python 3.10+" — nessuna guida all'azione.

### 13.3 Progresso visibile per install lunghi

pip install può richiedere 30-120s su first run (compilazione wheel). L'utente dovrebbe vedere:
```
Installing Gray Matter... ████████████░░░░ 75%
```

**Stato attuale**: nessun feedback durante pip install. L'utente vede solo "Installing Gray-Matter..." e poi silenzio per decine di secondi.

### 13.4 Idempotenza trasparente

Se l'utente ri-esegue install.cmd, il messaggio dovrebbe essere:
```
Gray Matter 1.1.2 already installed.
Use --force or select "Repair" from the GUI to reinstall.
```

**Stato attuale**: "already installed - skipping" → "Done" — l'utente non sa cosa aspettarsi.

### 13.5 Non aprire GUI dopo un errore

Se l'install fallisce, la GUI non dovrebbe aprirsi. Attualmente, se un peer install fallisce (ma GM è OK), la GUI si apre comunque con componenti mancanti.

---

## 14. Fix proposti (prioritizzati)

### Fix 1 (CRIT-1): pyturso mandatory — GIÀ APPLICATO

Stato: `neurag/pyproject.toml` è stato modificato. pyturso è ora nelle `dependencies` principali.

### Fix 2 (CRIT-2): Dialog 3 opzioni

**File**: `neuron/install.ps1:30-36`, `neurag/install.ps1:30-36`

```powershell
# SOSTITUIRE le righe 30-36 con:
if ($WantGm -and -not $AssumeYes -and [Environment]::UserInteractive) {
    Write-Host "`nNeuron works standalone; Gray Matter adds cross-store links"
    Write-Host "and neighbor auto-surface. Without GM you keep memory and"
    Write-Host "all native stimuli. Recommended: install it.`n"
    Write-Host "  [S]ì — installa Neuron + Gray Matter (gateway)"
    Write-Host "  [N]o — standalone (controlla se GM è già installato)"
    Write-Host "  [D]ettagli — cosa perdi senza GM"
    $ans = Read-Host "Scelta"
    switch -Regex ($ans) {
        '^(s|si|sì|y|yes|$)' { $WantGm = $true }
        '^(d|dettagli)$' {
            Write-Host "`nSenza GM perdi:"
            Write-Host "  - Cross-store bridges (Neuron ↔ NeuRAG)"
            Write-Host "  - Neighbor auto-surface"
            Write-Host "  - GUI unificata"
            Write-Host "  - Auto-registrazione nei client MCP"
            $ans2 = Read-Host "`nInstallare GM? [S/n]"
            if ($ans2 -match '^(n|no)$') { $WantGm = $false }
        }
        default { $WantGm = $false }
    }
}
```

### Fix 3 (BUG-1): ErrorActionPreference + stderr

**File**: `gray_matter/install.ps1:102,141`, `neuron/install.ps1:49`

```powershell
# Aggiungere 2>$null ai comandi nativi che possono produrre warning:
# install.ps1:102
& $PyExe @PyArgs -m venv $Venv 2>$null

# install.ps1:141
& $VPy -m pip install @ForceArgs $Here 2>$null

# neuron/install.ps1:49
& $py -m venv $Venv 2>$null
```

### Fix 4 (BUG-5): Dialog repair da install.cmd

**File**: `gray_matter/install.ps1:134-148`

```powershell
if ((-not $Force) -and (Test-AlreadyInstalled "gray-matter" $Here)) {
    Write-Host "Gray-Matter $(Get-SrcVersion $Here) already installed."
    if ([Environment]::UserInteractive) {
        Write-Host "`n  [R]ipara/Aggiorna  [I]nforma  [A]nnulla"
        $ans = Read-Host "Scelta"
        switch -Regex ($ans) {
            '^(r|ripara|update|aggiorna)$' { $Force = $true }
            '^(i|info|informa)$' {
                Write-Host "`nComponenti installati:"
                # ... elenco componenti ...
                Write-Host "`nPer riparare: install.cmd con --force"
                exit 0
            }
            default { Write-Host "Done (nothing changed)."; exit 0 }
        }
    } else { exit 0 }
}
```

### ~~Fix 5 (BUG-2): Slug Neuron standalone~~ — RISOLTO

**Stato**: Lo slug `neuron` è corretto. Il codice a `neuron/install.ps1:62` non necessita modifiche. Va solo verificato che `neuron/config.py` sia allineato (usare `neuron` come slug, non `neuron5`).

### Fix 6 (BUG-3): NeuRAG register automatico

**File**: `neurag/install.ps1:62-68`

```powershell
# SOSTITUIRE doctor + manuale con:
& (Join-Path $Venv "Scripts\neurag.exe") register --client all
```
(Necessita che `neurag register` esista nel CLI — da verificare.)

### Fix 7: Riepilogo post-install

**File**: `gray_matter/install.ps1:285-287`

```powershell
# SOSTITUIRE le righe 285-287 con:
Write-Host "`n═══ Install Summary ═══"
Write-Host "  ✓ Gray Matter $(Get-SrcVersion $Here)"
if ($NeuronDir) { Write-Host "  ✓ Neuron $(Get-SrcVersion $NeuronDir)" }
if ($NeuragDir) { Write-Host "  ✓ NeuRAG $(Get-SrcVersion $NeuragDir)" }
Write-Host "  ✓ Registered in: Claude Desktop, Cursor, OpenCode"
Write-Host "  ✓ Desktop shortcut: Gray Matter"
Write-Host "════════════════════════"
Write-Host "Restart your AI apps to load the servers."
& $VPy -m gray_matter.cli gui
