# Gray-Matter TOTAL installer for Windows — one entry point for the whole
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
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$Vendor = Join-Path $Root "Neuron\vendor"
$Find = @()
if (Test-Path $Vendor) { $Find = @("--find-links", $Vendor) }

# Find Python 3.10+ — prefer the py launcher, fall back to python on PATH.
$PyExe = $null; $PyArgs = @()
foreach ($cand in @(@("py","-3.12"), @("py","-3.11"), @("py","-3.13"),
                    @("py","-3.10"), @("py","-3.14"), @("python"))) {
    $exe = $cand[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count-1)] }
    try {
        $v = & $exe @rest -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
    } catch { continue }
    if ($v -and [int]$v -ge 310) { $PyExe = $exe; $PyArgs = $rest; break }
}
if (-not $PyExe) { Write-Host "ERROR: need Python 3.10+ (install from https://python.org)."; exit 1 }
Write-Host "Using: $PyExe $($PyArgs -join ' ')"

$Venv = Join-Path $env:LOCALAPPDATA "gray-matter\.venv"
if (-not (Test-Path $Venv)) { & $PyExe @PyArgs -m venv $Venv }
$VPy = Join-Path $Venv "Scripts\python.exe"
& $VPy -m pip install --upgrade pip | Out-Null

Write-Host "Installing Gray-Matter..."
& $VPy -m pip install @Find $Here
if (-not $env:GM_NO_NEURON -and (Test-Path (Join-Path $Root "Neuron"))) {
    Write-Host "Installing Neuron..."
    & $VPy -m pip install @Find (Join-Path $Root "Neuron")
}
if (-not $env:GM_NO_NEURAG -and (Test-Path (Join-Path $Root "neurag"))) {
    Write-Host "Installing NeuRAG..."
    & $VPy -m pip install @Find (Join-Path $Root "neurag")
}
# Launched from a standalone tool repo (Neuron-only / NeuRAG-only download):
# the thin per-repo installer points GM_PEER_DIR at itself — install it too.
if ($env:GM_PEER_DIR -and (Test-Path (Join-Path $env:GM_PEER_DIR "pyproject.toml"))) {
    Write-Host "Installing $(Split-Path -Leaf $env:GM_PEER_DIR)..."
    foreach ($v in @("Neuron\vendor", "vendor")) {
        $vd = Join-Path $env:GM_PEER_DIR $v
        if (Test-Path $vd) { $Find = @("--find-links", $vd) }
    }
    & $VPy -m pip install @Find $env:GM_PEER_DIR
}

# Best-effort turso tier: wheel vendored (Neuron\vendor o vendor del peer),
# altrimenti PyPI. Se fallisce NON blocca: si degrada al tier sqlite3.
& $VPy -c "import turso" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Enabling the Turso vector tier (best-effort)..."
    & $VPy -m pip install @Find "pyturso==0.6.1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  pyturso not available here - running on the sqlite3 tier (still fully functional)."
    }
}

# Gateway model (INSTALLER-UX): register ONLY gray-matter, deploy hooks, manifest.
Write-Host "Installing the gateway (register + hooks + manifest)..."
try { & $VPy -m gray_matter.cli install } catch { & $VPy -m gray_matter.cli register }

# Desktop shortcut to the control center.
$Desk = [Environment]::GetFolderPath("Desktop")
if ($Desk) {
    Set-Content -Path (Join-Path $Desk "Gray Matter GUI.cmd") `
        -Value "@`"$VPy`" -m gray_matter.cli gui" -Encoding ASCII
}

Write-Host "Done. Restart your AI apps to load the servers."
Write-Host "Control center any time:  $VPy -m gray_matter.cli gui"
& $VPy -m gray_matter.cli gui
