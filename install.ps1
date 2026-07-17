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

Write-Host "Registering installed servers in your MCP clients..."
& $VPy -m gray_matter.cli register

Write-Host "Done. Restart your AI apps to load the servers."
Write-Host "Control center any time:  $VPy -m gray_matter.cli gui"
& $VPy -m gray_matter.cli gui
