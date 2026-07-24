# Gray-Matter TOTAL installer for Windows ??? one entry point for the whole
# environment. Installs Gray-Matter plus whichever peers (Neuron, NeuRAG) sit
# next to it into ONE shared venv, registers them in your MCP clients, and opens
# the control center.
#
# One venv (not pipx-isolated) on purpose: a single interpreter must import all
# three. pyturso installs from the prebuilt wheels in Neuron\vendor
# (--find-links) so no Rust/MSVC toolchain is needed.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Opt out of a peer:  $env:GM_NO_NEURON=1  /  $env:GM_NO_NEURAG=1
#
# Repair mode:  -Force  ??? bypass the version-skip idempotence and reinstall the
# code even at the same version (pip --force-reinstall --no-deps). This is what
# the GUI "Ripara" button uses: code-only changes (same version) were otherwise
# never reinstalled ("already installed - skipping").
param([switch]$Force)
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
# In repair mode force pip to reinstall the package code even if the version is
# unchanged; --no-deps keeps it fast (heavy deps like fastembed/pyturso stay).
$ForceArgs = @(); if ($Force) { $ForceArgs = @("--force-reinstall", "--no-deps") }
# Il repo GM (zip GitHub) bundle-a i tool come sottocartelle: cerca prima
# DENTRO il repo ($Here), poi come sibling ($Root, checkout multi-repo).
function Find-Peer([string[]]$names) {
    foreach ($n in $names) {
        foreach ($base in @($Here, $Root)) {
            $d = Join-Path $base $n
            if (Test-Path (Join-Path $d "pyproject.toml")) { return $d }
        }
    }
    return $null
}
$NeuronDir = Find-Peer @("neuron", "Neuron")
$NeuragDir = Find-Peer @("neurag", "Neurag")
# Wheel offline (pyturso non ha wheel win_amd64 su PyPI): si prendono da OGNI
# vendor presente, non da quella di Neuron. I tre tool sono standalone ??? dare
# per scontata `neuron/vendor` lasciava un install GM+NeuRAG senza wheel, cio??
# NeuRAG degradato a sqlite3 proprio dove serve il vector SQL. pip accetta
# --find-links ripetuto: si passano tutte, vince chi ha la wheel giusta.
function Get-FindLinks([string[]]$dirs) {
    $out = @()
    foreach ($d in $dirs) {
        if ($d) {
            $v = Join-Path $d "vendor"
            if (Test-Path $v) { $out += @("--find-links", $v) }
        }
    }
    return $out
}
$Find = Get-FindLinks @($Here, $NeuronDir, $NeuragDir)

# Find Python 3.10+ ??? prefer python on PATH (avoids MSIX redirect), then py launcher.
$PyExe = $null; $PyArgs = @()
foreach ($cand in @(@("python"), @("py","-3.14"), @("py","-3.13"), @("py","-3.12"),
                    @("py","-3.11"), @("py","-3.10"))) {
    $exe = $cand[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count-1)] }
    try {
        $v = & $exe @rest -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
    } catch { continue }
    if ($v -and [int]$v -ge 310) { $PyExe = $exe; $PyArgs = $rest; break }
}
# Click-and-go bootstrap. Nota: lo stub Windows Store ("python" che apre lo
# Store) fallisce il version-check sopra, quindi arriva qui = trattato come
# assente. Se c'?? winget proviamo l'install ufficiale; il py launcher che
# installa viene ritrovato al secondo giro. Fallback: apri python.org.
if (-not $PyExe) {
    Write-Host "Python 3.10+ not found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python 3.12 via winget (official python.org build)..."
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        # winget aggiorna il PATH ma non in QUESTO processo: usa il py launcher
        # dal percorso standard, o rilancia lo script.
        $pyLauncher = Join-Path $env:WINDIR "py.exe"
        foreach ($cand in @(@("py","-3.12"), @($pyLauncher,"-3.12"), @("py","-3"))) {
            $exe = $cand[0]
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue) -and -not (Test-Path $exe)) { continue }
            $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count-1)] }
            try { $v = & $exe @rest -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null } catch { continue }
            if ($v -and [int]$v -ge 310) { $PyExe = $exe; $PyArgs = $rest; break }
        }
        if (-not $PyExe) {
            Write-Host "Python installed - please RE-RUN this installer (new PATH needs a fresh shell)."
            exit 0
        }
    } else {
        Write-Host "Opening python.org - install Python 3.12 (check 'Add to PATH'), then re-run."
        Start-Process "https://www.python.org/downloads/"
        exit 1
    }
}
Write-Host "Using: $PyExe $($PyArgs -join ' ')"

# Idempotenza VISIBILE (fix 2026-07-21): se la versione installata ?? gi?? quella
# del sorgente, si SALTA il pip install (niente rebuild muto a ogni re-run).
function Get-SrcVersion([string]$dir) {
    $toml = Join-Path $dir "pyproject.toml"
    if (-not (Test-Path $toml)) { return "" }
    $lines = Get-Content $toml
    foreach ($l in $lines) {
        if ($l -match 'version\s*=\s*"(.+?)"') { return $Matches[1] }
    }
    return ""
}

$Venv = Join-Path $env:LOCALAPPDATA "gray-matter\.venv"
# venv: Plan A stdlib venv, Plan B virtualenv, else EXIT with guidance.
if (-not (Test-Path $Venv)) {
    & $PyExe @PyArgs -m venv $Venv
    if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $PyExe @PyArgs -m virtualenv $Venv 2>$null }
    if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { Write-Host "ERROR: could not create a venv at $Venv ??? check disk space and permissions."; exit 1 }
}
$VPy = Join-Path $Venv "Scripts\python.exe"
# pip self-upgrade is non-critical: never let it abort the install.
& $VPy -m pip install --upgrade pip 2>$null | Out-Null

function Test-AlreadyInstalled([string]$pkg, [string]$dir) {
    $src = Get-SrcVersion $dir
    if (-not $src) { return $null }
    $probe = Join-Path $env:TEMP "gm_probe.py"
    $n = $pkg.ToLower().Replace('_','-')
    @"
import importlib.metadata as m, sys
n = "$n"
sys.stdout.write(next((d.version for d in m.distributions()
    if (d.metadata["Name"] or "").lower().replace("_","-") == n), ""))
"@ | Set-Content $probe -Encoding ASCII
    $inst = & $VPy -I "$probe"
    Remove-Item -Force $probe -ErrorAction SilentlyContinue
    if ($inst -and $inst.Trim() -eq $src) { return $inst.Trim() }
    return $null
}
# Returns: "skip", "reinstall", or "clean". Non-interactive => "skip".
function Prompt-InstallChoice([string]$label, [string]$ver) {
    if ($Force) { return "reinstall" }
    if (-not [Environment]::UserInteractive) { return "skip" }
    Write-Host "`n$label $ver is already installed."
    Write-Host "  [S]kip     - keep current installation"
    Write-Host "  [R]einstall - reinstall (same version, fresh copy)"
    Write-Host "  [C]lean    - remove venv and reinstall from scratch"
    $ans = Read-Host "Choice"
    switch -Regex ($ans) {
        '^(r|reinstall)$' { return "reinstall" }
        '^(c|clean)$'     { return "clean" }
        default            { return "skip" }
    }
}

$gmVer = Test-AlreadyInstalled "gray-matter" $Here
if ($gmVer) {
    $choice = Prompt-InstallChoice "Gray-Matter" $gmVer
    if ($choice -eq "clean") {
        Write-Host "Removing venv and reinstalling from scratch..."
        Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
        & $PyExe @PyArgs -m venv $Venv
        if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $PyExe @PyArgs -m virtualenv $Venv 2>$null }
        $VPy = Join-Path $Venv "Scripts\python.exe"
        & $VPy -m pip install --upgrade pip 2>$null | Out-Null
    }
    if ($choice -ne "skip") {
        Write-Host "Reinstalling Gray-Matter..."
        & $VPy -m pip install --force-reinstall --no-deps $Here
        if ($LASTEXITCODE -ne 0) { & $VPy -m pip install --force-reinstall --no-deps --no-cache-dir $Here }
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gray-matter install failed (the required gateway). Check network/Python and re-run."; exit 1 }
        & $VPy -c "import sys;sys.stderr=sys.stdout;import gray_matter"
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gray-matter module not found after install"; exit 1 }
        Write-Host "  gray-matter OK"
    } else {
        Write-Host "Keeping Gray-Matter $gmVer."
    }
} else {
    Write-Host "Installing Gray-Matter..."
    & $VPy -m pip install @ForceArgs $Here
    if ($LASTEXITCODE -ne 0) { & $VPy -m pip install --no-cache-dir @ForceArgs $Here }
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gray-matter install failed (the required gateway). Check network/Python and re-run."; exit 1 }
    & $VPy -c "import sys;sys.stderr=sys.stdout;import gray_matter"
    if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: gray-matter module not found after install"; exit 1 }
    Write-Host "  gray-matter OK"
}
# GM_PEER_DIR set ??? standalone mode (called from Neuron/install.ps1 or NeuRAG):
# install ONLY GM + the specified peer, skip sibling detection entirely.
function Install-Peer([string]$dir, [string]$label) {
    $pkg = (Split-Path -Leaf $dir).ToLower()
    $peerVer = Test-AlreadyInstalled $pkg $dir
    if ($peerVer) {
        $choice = Prompt-InstallChoice $label $peerVer
        if ($choice -ne "skip") {
            Write-Host "Reinstalling $label..."
            & $VPy -m pip install --force-reinstall --no-deps @Find $dir
            if ($LASTEXITCODE -ne 0) { & $VPy -m pip install --force-reinstall --no-deps $dir }
            if ($LASTEXITCODE -ne 0) { Write-Host "  WARNING: $label reinstall failed - continuing." }
        } else {
            Write-Host "Keeping $label $peerVer."
        }
        return
    }
    Write-Host "Installing $label ($dir)..."
    & $VPy -m pip install @Find @ForceArgs $dir
    if ($LASTEXITCODE -ne 0) { & $VPy -m pip install @ForceArgs $dir }
    if ($LASTEXITCODE -ne 0) { Write-Host "  WARNING: $label install failed - continuing." }
}

if ($env:GM_PEER_DIR -and (Test-Path (Join-Path $env:GM_PEER_DIR "pyproject.toml"))) {
    # Standalone: le wheel del peer si aggiungono a quelle gi?? trovate.
    $Find += Get-FindLinks @($env:GM_PEER_DIR)
    Install-Peer $env:GM_PEER_DIR (Split-Path -Leaf $env:GM_PEER_DIR)
} else {
    # Full suite mode ??? tools bundled INSIDE the GM repo zip, or siblings.
    if (-not $env:GM_NO_NEURON -and $NeuronDir) { Install-Peer $NeuronDir "Neuron" }
    if (-not $env:GM_NO_NEURAG -and $NeuragDir) { Install-Peer $NeuragDir "NeuRAG" }
}

# Probe presenza modulo SENZA stderr: `import x` stampa il traceback su
# stderr e sotto ErrorActionPreference=Stop PowerShell lo tratta come errore
# FATALE anche con 2>$null (stesso tranello del probe versioni, vedi sopra).
# find_spec non importa e non scrive niente: solo exit code.
function Test-PyModule([string]$module) {
    & $VPy -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('$module') else 1)"
    return ($LASTEXITCODE -eq 0)
}

# Best-effort turso tier: wheel vendored (Neuron\vendor o vendor del peer),
# altrimenti PyPI. Se fallisce NON blocca: si degrada al tier sqlite3.
if (-not (Test-PyModule "turso")) {
    Write-Host "Enabling the Turso vector tier (best-effort)..."
    & $VPy -m pip install @Find "pyturso==0.6.1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  pyturso not available here - running on the sqlite3 tier (still fully functional)."
    }
}

# Best-effort GUI nativa: pywebview. Senza, la GUI degrada al browser ??? che
# funziona ma vive appesa a una console (chiusa quella, GUI morta). Con la
# finestra nativa il control center ?? autosufficiente.
if (-not (Test-PyModule "webview")) {
    Write-Host "Enabling the native GUI window (best-effort)..."
    & $VPy -m pip install "pywebview>=5.0"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  pywebview not available - the control center will open in the browser."
    }
}

# Best-effort semantic tier: fastembed (retrieval preciso, meno token).
if (-not (Test-PyModule "fastembed")) {
    Write-Host "Enabling the semantic embedding tier (best-effort)..."
    & $VPy -m pip install "fastembed>=0.5.0,<1.0"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  fastembed not available - lexical ranking only (still functional)."
    }
}

# Gateway model (INSTALLER-UX): register ONLY gray-matter, deploy hooks, manifest.
# Hook assets now live INSIDE the neuron package (src/neuron/clients); the GM
# resolver finds them via importlib after install. For a source checkout we still
# hint the dev path ??? new in-package location first, legacy repo-root as fallback.
if ($NeuronDir) {
    foreach ($rel in @("src\neuron\clients", "clients")) {
        $cand = Join-Path $NeuronDir $rel
        if (Test-Path (Join-Path $cand "claude-code-hook\neuron_sessionstart_hook.py")) {
            $env:GM_NEURON_CLIENTS = $cand
            break
        }
    }
}
Write-Host "Installing the gateway (register + hooks + manifest)..."
try { & $VPy -m gray_matter.cli install } catch { & $VPy -m gray_matter.cli register }

# Registro path sorgente (SoC): ogni componente registra il PROPRIO sorgente nel
# proprio registro; GM li scopre chiedendo ai peer. Si riscrive a ogni install.
try { & $VPy -m gray_matter.cli record-env --gm $Here 2>$null } catch { }
if ($NeuronDir) { try { & $VPy -m neuron record-paths --source $NeuronDir 2>$null } catch { } }
if ($NeuragDir) { try { & $VPy -m neurag.cli record-paths --source $NeuragDir 2>$null } catch { } }

# Desktop shortcut to the control center ??? a REAL Windows .lnk (with icon), not a
# raw .cmd. Targets pythonw.exe so there is no console flash; falls back to the
# python.exe icon if the bundled GM.ico can't be found.
$Desk = [Environment]::GetFolderPath("Desktop")
if ($Desk) {
    # pythonw.exe = windowed interpreter (no console); fall back to python.exe.
    $VPyw = Join-Path (Split-Path $VPy) "pythonw.exe"
    if (-not (Test-Path $VPyw)) { $VPyw = $VPy }

    # App dir (persist the icon there, out of the user's way).
    $AppDir = Join-Path $env:LOCALAPPDATA "graymatter"
    if (-not (Test-Path $AppDir)) { New-Item -ItemType Directory -Force -Path $AppDir | Out-Null }

    # Use the bundled GM.ico (pre-rendered, no conversion needed).
    $IconPath = $VPyw   # sensible default: the interpreter's own icon
    try {
        $icoSrc = & $VPy -c "import gray_matter,os;p=os.path.join(os.path.dirname(gray_matter.__file__),'assets','gray-matter.ico');print(p) if os.path.isfile(p) else exit(1)" 2>$null
        if ($icoSrc -and (Test-Path $icoSrc)) {
            $ico = Join-Path $AppDir "gray-matter.ico"
            Copy-Item $icoSrc $ico -Force
            if (Test-Path $ico) { $IconPath = $ico }
        }
    } catch { }   # any failure ??? keep the python.exe icon, never block install

    $lnkPath = Join-Path $Desk "Gray Matter.lnk"
    try {
        $ws = New-Object -ComObject WScript.Shell
        $sc = $ws.CreateShortcut($lnkPath)
        $sc.TargetPath       = $VPyw
        $sc.Arguments        = "-m gray_matter.cli gui"
        $sc.WorkingDirectory = $AppDir
        $sc.IconLocation     = $IconPath
        $sc.Description       = "Gray Matter control center"
        $sc.Save()
        # Retire a stale .cmd launcher from previous installs.
        $oldCmd = Join-Path $Desk "Gray Matter GUI.cmd"
        if (Test-Path $oldCmd) { Remove-Item $oldCmd -Force -ErrorAction SilentlyContinue }
    } catch {
        # COM unavailable (rare) ??? fall back to the old .cmd so the user still has a launcher.
        Set-Content -Path (Join-Path $Desk "Gray Matter GUI.cmd") `
            -Value "@`"$VPy`" -m gray_matter.cli gui" -Encoding ASCII
    }
}

Write-Host "Done. Restart your AI apps to load the servers."
Write-Host "Control center any time:  $VPy -m gray_matter.cli gui"
& $VPy -m gray_matter.cli gui
