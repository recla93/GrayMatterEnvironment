# NeuRAG installer (Windows) — click-and-go, default: NeuRAG + Gray Matter
# (gateway). One shared venv, registers the gateway, opens GUI.
#
# Modes:
#   default           → install NeuRAG + GM (recommended, click-and-go)
#   --no-gm           → standalone (NeuRAG only, registers directly in clients)
#   -Force / --force  → repair mode (pip --force-reinstall --no-deps)
#   -Clear / --clear  → last resort: delete the venv and rebuild (implies -Force).
#                       CODE only — graphs/knowledge.db/bridges are never touched.
param([switch]$Force, [switch]$Clear)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 0) Parse flags. Default: install with GM (gateway mode). --no-gm = standalone.
$WantGm = $true; $Mode = "gateway"
foreach ($a in $args) {
    if ($a -eq "--no-gm") { $WantGm = $false; $Mode = "standalone" }
    if ($a -eq "-f" -or $a -eq "--force") { $Force = $true }
    if ($a -eq "-c" -or $a -eq "--clear") { $Clear = $true }
}
# Args da inoltrare al GM installer: quelli ricevuti meno le forme -f/--force,
# più il -Force nativo se in repair mode.
$Fwd = @(); foreach ($a in $args) {
    if ($a -notin @("-f", "--force", "-c", "--clear")) { $Fwd += $a }
}
if ($Clear) { $Force = $true }          # clear is a stronger force
if ($Force) { $Fwd += "-Force" }
if ($Clear) { $Fwd += "-Clear" }        # forwarded: GM owns the shared venv
$ForceArgs = @(); if ($Force) { $ForceArgs = @("--force-reinstall", "--no-deps") }
if ($env:GM_OPTIN -eq "0") { $WantGm = $false; $Mode = "standalone" }

# Mode selector: click-and-go (Enter = full suite) or explicit --no-gm.
# Only shows in interactive sessions; non-interactive defaults to gateway.
if ($WantGm -and [Environment]::UserInteractive -and -not $Force) {
    Write-Host "`n  Installation mode:"
    Write-Host "    [F] Full suite — GM + Neuron + NeuRAG (recommended)"
    Write-Host "    [N] Solo NeuRAG — standalone (registers directly in clients)"
    Write-Host "    [D] Details — what you lose without GM"
    Write-Host ""
    $ans = Read-Host "  Choice [F]"
    switch -Regex ($ans) {
        '^(n|no|standalone)$' { $WantGm = $false; $Mode = "standalone" }
        '^(d|details)$' {
            Write-Host "`n  Without GM you lose:"
            Write-Host "    - Cross-store bridges (NeuRAG <-> Neuron)"
            Write-Host "    - Neighbor auto-surface"
            Write-Host "    - Unified GUI control center"
            Write-Host "    - Auto-registration in MCP clients"
            Write-Host ""
            $ans2 = Read-Host "  Install Full suite? [Y/n]"
            if ($ans2 -match '^(n|no)$') { $WantGm = $false; $Mode = "standalone" }
        }
    }
}

# STANDALONE: only NeuRAG, its own venv. Reversible: re-run without --no-gm
# and GM takes over (gateway + bridges). Also the safety net when GM cannot
# be obtained (§6: degrade, don't exit).
function Install-Standalone {
    Write-Host "Installing NeuRAG STANDALONE (no Gray Matter - add it any time by re-running)."
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
    if (-not $py) { Write-Host "ERROR: need Python 3.10+ - https://www.python.org/downloads/"; exit 1 }
    $Home_ = if ($env:NEURAG_HOME) { $env:NEURAG_HOME } else { Join-Path $env:LOCALAPPDATA "neurag" }
    $Venv = Join-Path $Home_ ".venv"
    # INSTALLER-UX §5.3 — kill what runs from this venv BEFORE pip writes to it.
    # A loaded .pyd cannot be replaced on Windows: pip dies with
    #   [WinError 5] Accesso negato: <venv>/Lib/site-packages/rpds/rpds.cp314-win_amd64.pyd
    # The reap inside `gray_matter.cli install` runs long after every pip.
    # Win32_Process, not Get-Process: `.Path` is null for processes this token
    # cannot open, which hid half of them on a live machine.
    $VenvPids = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and (
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($Venv, [StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine    -and $_.CommandLine.IndexOf($Venv, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        )
    } | Select-Object -ExpandProperty ProcessId)
    if ($VenvPids.Count -gt 0) {
        Write-Host "Stopping $($VenvPids.Count) running process(es) from this venv (they hold the files pip must replace)..."
        foreach ($p in $VenvPids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 800
    }
    # Un venv "c'è" solo se il suo interprete PARTE. Test-Path sulla cartella non
    # è quel test: una Remove-Item che cancella pyvenv.cfg e poi inciampa in un
    # .pyd bloccato lascia Lib\ e Scripts\, la cartella esiste ancora, la
    # creazione viene saltata e il primo pip muore con
    #   python.exe : failed to locate pyvenv.cfg
    # come NativeCommandError grezzo. Visto su una macchina vera.
    function Test-VenvHealthy([string]$VenvPath) {
        if (-not (Test-Path (Join-Path $VenvPath "pyvenv.cfg"))) { return $false }
        $p = Join-Path $VenvPath "Scripts\python.exe"
        if (-not (Test-Path $p)) { return $false }
        & $p -c "import sys" | Out-Null
        return ($LASTEXITCODE -eq 0)
    }
    function Remove-Venv([string]$VenvPath, [string]$why) {
        Write-Host "$why ($VenvPath)"
        Write-Host "  (user memory is NOT touched - it lives outside the venv)"
        Remove-Item -Recurse -Force $VenvPath -ErrorAction SilentlyContinue
        if (Test-Path $VenvPath) {
            Write-Host "ERROR: could not fully remove $VenvPath."
            Write-Host "  Close your AI apps (they respawn the servers) and re-run with -Clear."
            exit 1
        }
    }
    if ($Clear -and (Test-Path $Venv)) {
        Remove-Venv $Venv "Clear: removing the venv and rebuilding from scratch"
    }
    # Un mezzo-venv si ripara, non si eredita: e' tutto il punto.
    if ((Test-Path $Venv) -and -not (Test-VenvHealthy $Venv)) {
        Remove-Venv $Venv "Damaged venv detected (pyvenv.cfg missing or interpreter dead) - rebuilding"
    }
    if (-not (Test-Path $Venv)) {
        & $py.Source -m venv $Venv
        if (-not (Test-VenvHealthy $Venv)) {
            Write-Host "ERROR: could not create a working venv at $Venv - check disk space and permissions"
            exit 1
        }
    }
    $Vpy = Join-Path $Venv "Scripts\python.exe"
    & $Vpy -m pip install --upgrade pip | Out-Null
    if ($Force) { Write-Host "Repair: reinstalling NeuRAG (forced)..." }
    $Vendor = Join-Path $Here "vendor"
    if (Test-Path $Vendor) { & $Vpy -m pip install --find-links $Vendor @ForceArgs $Here }
    else { & $Vpy -m pip install @ForceArgs $Here }
    if ($LASTEXITCODE -ne 0) {
        & $Vpy -m pip install @ForceArgs $Here
        if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: NeuRAG install failed — check network, or try: pip install --upgrade pip"; exit 1 }
    }
    & (Join-Path $Venv "Scripts\neurag.exe") register --client all
    & (Join-Path $Venv "Scripts\neurag.exe") doctor
    
    # --- GME Registry ---
    # One line instead of ~30 of hand-written JSON: gray_matter/gme.py is the
    # single writer (and the reader). Six shell copies in two languages is what
    # let the PowerShell BOM and the macOS path divergence ship unnoticed.
    # Best-effort — standalone means Gray Matter may be absent, and then there
    # is no registry to write and nothing that would read it.
    try { & $Vpy -m gray_matter.gme register "$Here" } catch { }
    
    # Desktop icon "NeuRAG" → doppio click apre il control center (bootstrappa GM
    # al primo click). Best-effort: non blocca l'install se fallisce.
    try { & $Vpy -m neurag.cli gui --shortcut-only } catch {}
    $NeuRAGVer = & (Join-Path $Venv "Scripts\neurag.exe") --version
    Write-Host "`n  NeuRAG $NeuRAGVer — standalone"
    Write-Host "  Restart your AI apps to load the server."
    Write-Host "  Desktop icon 'NeuRAG' opens the control center (installs Gray Matter on first click)."
    exit 0
}
if (-not $WantGm) { Install-Standalone }

# 1) Local GM (bundled or sibling) — zero-network, always the safest path.
foreach ($gm in @((Join-Path $Here "gray_matter"), (Join-Path (Split-Path -Parent $Here) "gray_matter"))) {
    $inst = Join-Path $gm "install.ps1"
    if (Test-Path $inst) {
        $env:GM_PEER_DIR = $Here
        & powershell -ExecutionPolicy Bypass -File $inst @Fwd
        exit $LASTEXITCODE
    }
}

# GM is the required gateway: if missing, fetch it. Safest source first. These
# remote paths activate once Gray Matter is published (GitHub release / PyPI).
$GmVersion = if ($env:GM_VERSION) { $env:GM_VERSION } else { "1.1.2" }
$GmRepo    = if ($env:GM_REPO)    { $env:GM_REPO }    else { "recla93/gray-matter" }
$GmSha256  = $env:GM_SHA256          # optional: pin the release zip checksum
$Cache     = if ($env:GM_CACHE)   { $env:GM_CACHE }  else { Join-Path $Here ".gm-bootstrap" }
Write-Host "Gray Matter not found locally - bootstrapping it (GM is the required gateway)."
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

# 2) Primary remote: pinned GitHub release zip of the GM repo (immutable tag,
#    TLS, optional SHA256). Reuses the exact same tested install.ps1 pipeline.
$Url = "https://github.com/$GmRepo/archive/refs/tags/v$GmVersion.zip"
$Zip = Join-Path $Cache "gm-$GmVersion.zip"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
} catch { Remove-Item $Zip -Force -ErrorAction SilentlyContinue }
if (Test-Path $Zip) {
    if ($GmSha256) {
        $h = (Get-FileHash -Algorithm SHA256 $Zip).Hash
        if ($h -ne $GmSha256) { Write-Host "ERROR: GM checksum mismatch — re-download or set `$env:GM_SHA256 to skip"; exit 1 }
    }
    Expand-Archive -Path $Zip -DestinationPath $Cache -Force
    $gm = Get-ChildItem -Directory $Cache -Filter "gray-matter*" | Select-Object -First 1
    if ($gm) {
        $inst = Join-Path $gm.FullName "install.ps1"
        if (Test-Path $inst) {
            $env:GM_PEER_DIR = $Here
            & powershell -ExecutionPolicy Bypass -File $inst @Fwd
            exit $LASTEXITCODE
        }
    }
}

# 3) Fallback: PyPI. Install GM into the venv, then drive the gateway install.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if ($py) {
    & $py.Source -m pip install "gray-matter==$GmVersion"
    if ($LASTEXITCODE -eq 0) {
        & $py.Source -m pip install --find-links (Join-Path $Here "vendor") $Here
        $gmcli = Get-Command gray-matter -ErrorAction SilentlyContinue
        if ($gmcli) { & gray-matter install @args; if ($LASTEXITCODE -eq 0) { exit 0 } }
    }
}

# GM unobtainable → degrade to standalone (§6), don't strand the user.
Write-Host "WARNING: could not obtain Gray Matter (offline, or not yet published)."
Write-Host "Falling back to a STANDALONE NeuRAG install - re-run this script later to add GM."
Install-Standalone
