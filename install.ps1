# NeuRAG installer for Windows. Installs NeuRAG plus the Gray-Matter
# orchestrator (bundled by default) into ONE shared venv and registers them in
# your MCP clients via `gray-matter register`. pyturso installs from the
# prebuilt wheels in ..\Neuron\vendor when present (--find-links) so no
# Rust/MSVC toolchain is needed. Symmetric to Neuron's installer.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Opt out of the orchestrator:  $env:NEURAG_NO_GM=1
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
$Vendor = Join-Path $Root "Neuron\vendor"
$Find = @()
if (Test-Path $Vendor) { $Find = @("--find-links", $Vendor) }

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
if (-not $PyExe) { Write-Host "ERROR: need Python 3.10+ (https://python.org)."; exit 1 }
Write-Host "Using: $PyExe $($PyArgs -join ' ')"

$Venv = Join-Path $env:LOCALAPPDATA "neurag\.venv"
if (-not (Test-Path $Venv)) { & $PyExe @PyArgs -m venv $Venv }
$VPy = Join-Path $Venv "Scripts\python.exe"
& $VPy -m pip install --upgrade pip | Out-Null

Write-Host "Installing NeuRAG..."
& $VPy -m pip install @Find $Here

$GmBundled = $false
if (-not $env:NEURAG_NO_GM -and (Test-Path (Join-Path $Root "gray_matter"))) {
    Write-Host "Bundling Gray-Matter orchestrator..."
    & $VPy -m pip install @Find (Join-Path $Root "gray_matter")
    $GmBundled = $true
}

if ($GmBundled) {
    Write-Host "Registering installed servers in your MCP clients..."
    & $VPy -m gray_matter.cli register
} else {
    Write-Host "Add NeuRAG to your MCP client by hand — command: $VPy  args: -m neurag.server"
}

$NeuragCli = Join-Path $Venv "Scripts\neurag.exe"
Write-Host "Done. Restart your AI apps to load NeuRAG."
Write-Host "  index docs:  $NeuragCli index <folder>"
Write-Host "  query:       $NeuragCli query 'java streams'"
