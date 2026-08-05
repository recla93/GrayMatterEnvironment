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
#
# Repair mode:  -Force  — bypass the version-skip idempotence and reinstall the
# code even at the same version (pip --force-reinstall --no-deps). This is what
# the GUI "Ripara" button uses: code-only changes (same version) were otherwise
# never reinstalled ("already installed - skipping").
#
# Last resort:  -Clear  — delete the venv and rebuild it from scratch, then
# install as usual (implies -Force). For the states no reinstall can repair: a
# half-written venv, a broken interpreter, a dependency pinned wrong. Removes
# CODE only — graphs, knowledge.db, bridges and the GME registry are untouched.
#   -EmbedModel <name>  -> embedding model for Neuron (skips the prompt)
#   -Client <sel>       -> where to register: all|detected|ask|a,b,c
param([switch]$Force, [switch]$Clear, [string]$EmbedModel = "",
      [string]$Client = "")
if ($Clear) { $Force = $true }
$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $Here
# In repair mode force pip to reinstall the package code even if the version is
# unchanged; --no-deps keeps it fast (heavy deps like fastembed/pyturso stay).
$ForceArgs = @(); if ($Force) { $ForceArgs = @("--force-reinstall", "--no-deps") }
# Il repo GM (zip GitHub) bundle-a i tool come sottocartelle: cerca prima
# DENTRO il repo ($Here), poi come sibling ($Root, checkout multi-repo).
#
# La cartella si IDENTIFICA dal pyproject, non dal nome. Confrontare il nome
# esatto ("neuron"/"Neuron") rendeva INVISIBILE, in silenzio, ogni peer
# scaricato come zip: GitHub estrae in `Neuron-master`, `neurag-main`,
# `gray-matter-main`, e uno zip di release in `neurag-1.3.1`. È esattamente così
# che un'installazione full-suite finiva con Neuron installato e NeuRAG no —
# senza un solo messaggio, perché "peer assente" è uno stato legittimo.
function Get-ProjectName([string]$dir) {
    $toml = Join-Path $dir "pyproject.toml"
    if (-not (Test-Path $toml)) { return "" }
    foreach ($l in (Get-Content $toml -ErrorAction SilentlyContinue)) {
        if ($l -match '^\s*name\s*=\s*"(.+?)"') {
            return $Matches[1].ToLower().Replace('_', '-')
        }
    }
    return ""
}
function Find-PeerIn([string]$pkg, [string]$parent) {
    if (-not $parent -or -not (Test-Path $parent)) { return $null }
    # 1) nome esatto: il layout di sviluppo, e il caso piu' comune
    foreach ($n in @($pkg, $pkg.Substring(0,1).ToUpper() + $pkg.Substring(1))) {
        $d = Join-Path $parent $n
        if ((Test-Path (Join-Path $d "pyproject.toml")) -and (Get-ProjectName $d) -eq $pkg) { return $d }
    }
    # 2) qualunque sottocartella il cui pyproject dichiari QUESTO pacchetto
    foreach ($d in (Get-ChildItem -Directory $parent -ErrorAction SilentlyContinue)) {
        if ((Get-ProjectName $d.FullName) -eq $pkg) { return $d.FullName }
    }
    return $null
}
function Find-Peer([string]$pkg) {
    foreach ($base in @($Here, $Root)) {
        $d = Find-PeerIn $pkg $base
        if ($d) { return $d }
    }
    return $null
}

$NeuronDir = Find-Peer "neuron"
$NeuragDir = Find-Peer "neurag"
# Wheel offline (pyturso non ha wheel win_amd64 su PyPI): si prendono da OGNI
# vendor presente, non da quella di Neuron. I tre tool sono standalone — dare
# per scontata `neuron/vendor` lasciava un install GM+NeuRAG senza wheel, cioè
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

# Find Python 3.10+ — prefer python on PATH (avoids MSIX redirect), then py launcher.
# Returns the version as 3xx, or 0 for "not a usable interpreter". `[int]$v` used
# to run unguarded on whatever the candidate printed, and under EAP=Stop a cast
# failure is FATAL: a candidate that emits anything non-numeric on stdout — the
# Windows Store App Execution Alias, a conda/pyenv shim banner, any wrapper that
# greets before it answers — killed the installer with a raw .NET conversion
# error. On the exact machine this code path exists for (nothing installed yet),
# instead of the intended "Python 3.10+ not found → let me install it".
# Same shape neuron/install.ps1's Test-PythonOk already used; GM, the entry point
# a new user actually runs, was the one still doing it by hand.
function Get-PythonVersion($exe, $rest) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $exe @rest -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])"
        if ($LASTEXITCODE -ne 0) { return 0 }
        $last = "$($out | Select-Object -Last 1)".Trim()   # ignore a banner above it
        if ($last -notmatch '^\d+$') { return 0 }
        return [int]$last
    } catch {
        return 0
    } finally { $ErrorActionPreference = $prevEap }
}

$PyExe = $null; $PyArgs = @()
foreach ($cand in @(@("python"), @("py","-3.14"), @("py","-3.13"), @("py","-3.12"),
                    @("py","-3.11"), @("py","-3.10"))) {
    $exe = $cand[0]
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count-1)] }
    if ((Get-PythonVersion $exe $rest) -ge 310) { $PyExe = $exe; $PyArgs = $rest; break }
}
# Click-and-go bootstrap. Nota: lo stub Windows Store ("python" che apre lo
# Store) fallisce il version-check sopra, quindi arriva qui = trattato come
# assente. Se c'è winget proviamo l'install ufficiale; il py launcher che
# installa viene ritrovato al secondo giro. Fallback: apri python.org.
if (-not $PyExe) {
    Write-Host "Python 3.10+ not found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Python 3.12 via winget (official python.org build)..."
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        $wingetRc = $LASTEXITCODE
        # winget aggiorna il PATH ma non in QUESTO processo: usa il py launcher
        # dal percorso standard, o rilancia lo script.
        $pyLauncher = Join-Path $env:WINDIR "py.exe"
        # ...and the per-user install location: winget's PrependPath does not
        # affect THIS process, and if the py launcher was not part of the package
        # there is nothing on PATH to find. neuron/install.ps1 already looked here;
        # without it a successful winget install still ended in "please RE-RUN".
        $userPy = @()
        foreach ($n in @("Python314", "Python313", "Python312", "Python311", "Python310")) {
            $userPy += ,@((Join-Path $env:LOCALAPPDATA "Programs\Python\$n\python.exe"))
        }
        foreach ($cand in (@(@("py","-3.12"), @($pyLauncher,"-3.12"), @("py","-3")) + $userPy)) {
            $exe = $cand[0]
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue) -and -not (Test-Path $exe)) { continue }
            $rest = @(); if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count-1)] }
            if ((Get-PythonVersion $exe $rest) -ge 310) { $PyExe = $exe; $PyArgs = $rest; break }
        }
        if (-not $PyExe) {
            # winget's exit code was ignored, so a FAILED install (no network,
            # package unavailable, winget too old) still printed "Python
            # installed - please RE-RUN" — and re-running loops on that same
            # message forever without ever saying what went wrong. Only claim
            # success when winget actually reported it.
            if ($wingetRc -ne 0) {
                Write-Host "winget could not install Python (exit $wingetRc)."
                Write-Host "Opening python.org - install Python 3.12 (check 'Add to PATH'), then re-run."
                Start-Process "https://www.python.org/downloads/"
                exit 1
            }
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

# Idempotenza VISIBILE (fix 2026-07-21): se la versione installata è già quella
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

# INSTALLER-UX §5.3 — "Termina eventuali processi orfani PRIMA di scrivere
# (evita lock Windows)". That step was specified but never implemented in the
# shell installers: the reap lives inside `gray_matter.cli install`, which runs
# after every pip. On Windows a loaded .pyd cannot be replaced, so an install
# over a running gateway died with
#   ERROR: Could not install packages due to an OSError: [WinError 5]
#   Accesso negato: '...\.venv\Lib\site-packages\rpds\rpds.cp314-win_amd64.pyd'
# Deliberately native PowerShell, not `$VPy -m gray_matter...`: this has to work
# when the venv is exactly what is broken (the -Clear case), and -Clear's own
# Remove-Item hits the same lock, so it must come first.
function Get-VenvPids([string]$VenvPath) {
    # Win32_Process, not Get-Process: `.Path` is null for any process this token
    # cannot open, and on a live machine that hid half of them (9 of 18 here) —
    # the survivors keep the .pyd mapped and pip fails anyway. ExecutablePath and
    # CommandLine come straight from the CIM record and are always readable.
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and (
            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($VenvPath, [StringComparison]::OrdinalIgnoreCase)) -or
            ($_.CommandLine    -and $_.CommandLine.IndexOf($VenvPath, [StringComparison]::OrdinalIgnoreCase) -ge 0)
        )
    } | Select-Object -ExpandProperty ProcessId)
}

function Stop-VenvProcesses([string]$VenvPath) {
    if (-not (Test-Path $VenvPath)) { return }
    $pids = Get-VenvPids $VenvPath
    if ($pids.Count -eq 0) { return }
    Write-Host "Stopping $($pids.Count) running process(es) from this venv (they hold the files pip must replace)..."
    foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 800        # let Windows release the file handles
    $left = Get-VenvPids $VenvPath
    if ($left.Count -gt 0) {
        Write-Host "  WARNING: $($left.Count) still alive (PID $($left -join ', ')) — close your AI apps and re-run if pip reports 'Accesso negato'."
    }
}

# The venv lives under gm_home() (paths.py: <base>\graymatter) like every other
# thing GM owns. It used to be the ONE item in `<base>\gray-matter\`: two nearly
# identical folder names for the same product, which is the first thing every
# tester asks about. $env:GM_HOME is the BASE here, exactly as in paths.py —
# install.sh used to read it as the gray-matter dir itself, so the same variable
# put the venv and the config in unrelated places.
# An EXISTING install is not migrated: a venv is not movable (pyvenv.cfg and the
# Scripts shims carry absolute paths) and the registered MCP clients point at the
# old interpreter. It stays valid where it is and converges on the next -Clear.
# Il fallback su USERPROFILE non è teorico: con LOCALAPPDATA vuoto (servizio,
# scheduled task, env ripulito) `Join-Path ""` NON restituisce un path relativo,
# solleva — e sotto EAP=Stop l'installer muore lì, prima di dire qualsiasi cosa.
# È lo stesso buco che gme.user_base() documenta di aver già tappato in Python.
$OsBase = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA }
          elseif ($env:USERPROFILE) { Join-Path $env:USERPROFILE "AppData\Local" }
          else { throw "Né LOCALAPPDATA né USERPROFILE sono impostati: non so dove installare." }
# Radice UNICA della suite. GM_HOME resta l'override e vale gia' la radice
# suite, come in paths.py: sotto ci vanno graymatter/, registry/, neuron/,
# neurag/ — una cartella sola da guardare, copiare o cancellare.
$GmBase = if ($env:GM_HOME) { $env:GM_HOME } else { Join-Path $OsBase "GrayMatterEnvironment" }
$Venv = Join-Path $GmBase "graymatter\.venv"
# Le due posizioni precedenti, nell'ordine in cui sono esistite. Un venv non e'
# spostabile (pyvenv.cfg e gli script hanno path assoluti, e i client MCP
# puntano al suo interprete): se ce n'e' gia' uno lo si continua a usare, e
# converge alla posizione nuova al primo -Clear.
# Si eredita solo un venv SANO. Bastava che la cartella esistesse, e un residuo
# rotto — .venv presente ma senza pyvenv.cfg, cioe' una cancellazione a meta' —
# veniva preferito alla creazione di uno nuovo. Da li' in poi OGNI chiamata
# all'interprete moriva con "failed to locate pyvenv.cfg" e l'installer tirava
# dritto fino a dichiarare INSTALL COMPLETE. Visto su una macchina vera.
function Test-VenvUsable([string]$p) {
    if (-not (Test-Path (Join-Path $p "pyvenv.cfg"))) { return $false }
    return (Test-Path (Join-Path $p "Scripts\python.exe"))
}
foreach ($old in @((Join-Path $OsBase "graymatter\.venv"), (Join-Path $OsBase "gray-matter\.venv"))) {
    if ((Test-VenvUsable $old) -and -not (Test-VenvUsable $Venv)) { $Venv = $old; break }
}
Stop-VenvProcesses $Venv
# -Clear: throw the venv away and rebuild. A "clean" option existed before, but
# only as a letter in an interactive prompt — and -Force skipped that prompt, so
# exactly when you needed a clean rebuild you could not ask for one. As a flag it
# also reaches the GUI's Ripara button and any script.
# CODE ONLY: graphs, knowledge.db, bridges and the GME registry are user data and
# live outside the venv. Wiping those is `gray-matter repair` / `uninstall`.
# A venv is "there" only if its interpreter actually RUNS. Test-Path on the
# folder is not that test: a Remove-Item that deleted pyvenv.cfg and then hit a
# locked .pyd leaves Lib\ and Scripts\ behind, the folder still exists, creation
# is skipped, and the first pip dies with
#   python.exe : failed to locate pyvenv.cfg
# as a raw NativeCommandError. Seen on a real machine after an interrupted wipe.
function Test-VenvHealthy([string]$VenvPath) {
    if (-not (Test-Path (Join-Path $VenvPath "pyvenv.cfg"))) { return $false }
    $py = Join-Path $VenvPath "Scripts\python.exe"
    if (-not (Test-Path $py)) { return $false }
    & $py -c "import sys" | Out-Null      # no: see the note by $ErrorActionPreference
    return ($LASTEXITCODE -eq 0)
}

function Remove-Venv([string]$VenvPath, [string]$why) {
    Write-Host "$why ($VenvPath)"
    Write-Host "  (user memory is NOT touched — graphs, knowledge.db and bridges live elsewhere)"
    Stop-VenvProcesses $VenvPath          # a live process is what makes a wipe partial
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
# A leftover half-venv is repaired, not inherited: that is the whole point.
if ((Test-Path $Venv) -and -not (Test-VenvHealthy $Venv)) {
    Remove-Venv $Venv "Damaged venv detected (pyvenv.cfg missing or interpreter dead) — rebuilding"
}
# venv: Plan A stdlib venv, Plan B virtualenv, else EXIT with guidance.
if (-not (Test-Path $Venv)) {
    & $PyExe @PyArgs -m venv $Venv
    if (-not (Test-VenvHealthy $Venv)) { & $PyExe @PyArgs -m virtualenv $Venv }
    if (-not (Test-VenvHealthy $Venv)) {
        Write-Host "ERROR: could not create a working venv at $Venv."
        Write-Host "  Check disk space and permissions, then re-run."
        exit 1
    }
}
$VPy = Join-Path $Venv "Scripts\python.exe"
# -Yes / GM_YES = "don't ask me anything": ONE gate for every prompt below.
# Needed by any caller without a usable stdin (CI, scheduled task, a GUI that
# redirects streams). UserInteractive cannot carry this — it describes the
# session, not the console, so it stays TRUE exactly when Read-Host would hang.
$Ask = ([Environment]::UserInteractive -and -not $Force -and
        -not $env:GM_YES -and ($args -notcontains "-Yes"))
# pip self-upgrade is non-critical: never let it abort the install.
& $VPy -m pip install --upgrade pip --quiet | Out-Null

function Test-AlreadyInstalled([string]$pkg, [string]$dir) {
    $src = Get-SrcVersion $dir
    if (-not $src) { return $null }
    $probe = Join-Path $env:TEMP "gm_probe.py"
    $n = $pkg.ToLower().Replace('_','-')
    # importlib.metadata.version() — the same call install.sh has always used.
    # The previous version walked every distribution reading d.metadata["Name"],
    # and on Python 3.14 that emits
    #   DeprecationWarning: Implicit None on return values is deprecated and
    #   will raise KeyErrors
    # because email.message.Message.__getitem__ returns None for a missing
    # header. The `or ""` never helped: the warning fires on the lookup itself.
    # version() also normalises gray_matter/gray-matter for us.
    #
    # Still a temp file, not `-c`: a raising one-liner would print a traceback on
    # stderr, and under ErrorActionPreference=Stop PowerShell treats that as a
    # FATAL error even with 2>$null (the trap documented above). Swallowing the
    # exception in Python keeps stderr empty.
    @"
import importlib.metadata as m, sys
try:
    sys.stdout.write(m.version("$n"))
except Exception:
    pass
"@ | Set-Content $probe -Encoding ASCII
    $inst = & $VPy -I "$probe"
    Remove-Item -Force $probe -ErrorAction SilentlyContinue
    if ($inst -and $inst.Trim() -eq $src) { return $inst.Trim() }
    return $null
}
# Returns: "skip", "reinstall", or "clean". Non-interactive => "skip".
function Prompt-InstallChoice([string]$label, [string]$ver) {
    if ($Force) { return "reinstall" }
    Write-Host "`n$label $ver is already installed."
    Write-Host "  [R]einstall - reinstall (same version, fresh copy)"
    Write-Host "  [C]lean    - remove venv and reinstall from scratch"
    Write-Host "  [S]kip     - keep current installation"
    # No console (GUI installer: CreateNoWindow, stdin not redirected) => Read-Host
    # throws, and ErrorActionPreference=Stop would abort the whole install. The
    # UserInteractive gate is deliberately NOT back (it was wrong: it is true in
    # that very case); catching the failure delivers the documented "skip".
    try { $ans = Read-Host "Choice" }
    catch { Write-Host "  (no console for the prompt - keeping the current install)"; return "skip" }
    switch -Regex ($ans) {
        '^(r|reinstall)$' { return "reinstall" }
        '^(c|clean)$'     { return "clean" }
        default            { return "skip" }
    }
}

$gmVer = Test-AlreadyInstalled "gray-matter" $Here
if ($gmVer) {
    $choice = Prompt-InstallChoice "Gray-Matter" $gmVer
    # Stop AGAIN, after the prompt. The call at the top of the script is not
    # enough in the interactive flow (double-clicked install.cmd): while the user
    # reads the menu, the MCP client notices its stdio server died and respawns
    # it — so by the time pip runs the .pyd is mapped again and we are back to
    # "[WinError 5] Accesso negato". Non-interactive runs never showed this
    # because there is no pause between the kill and the write.
    Stop-VenvProcesses $Venv
    if ($choice -eq "clean") {
        Write-Host "Removing venv and reinstalling from scratch..."
        Remove-Item -Recurse -Force $Venv -ErrorAction SilentlyContinue
        if (Test-Path $Venv) { Write-Host "ERROR: could not remove $Venv — close your AI apps (they respawn the servers) and re-run."; exit 1 }
        & $PyExe @PyArgs -m venv $Venv
        if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $PyExe @PyArgs -m virtualenv $Venv }
        $VPy = Join-Path $Venv "Scripts\python.exe"
        & $VPy -m pip install --upgrade pip | Out-Null
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
# GM_PEER_DIR set → coupled mode (called from Neuron/install.ps1 or NeuRAG):
# install GM + the calling peer, then detect and ask about other siblings.
function Install-Peer([string]$dir, [string]$label) {
    $pkg = (Split-Path -Leaf $dir).ToLower()
    # Peers land in the SAME venv as GM and are installed after it, so a peer
    # with looser pins can pull a shared dep past GM's cap (an old Neuron with
    # an uncapped `mcp>=1.28` dragged in mcp 2.x and broke GM's server import).
    # pip only warns about that and exits 0 — feed the peer's own caps when it
    # ships them, and see the pip check before the final banner.
    $Cons = @()
    $cf = Join-Path $dir "constraints.txt"
    if (Test-Path $cf) { $Cons = @("-c", $cf) }
    $peerVer = Test-AlreadyInstalled $pkg $dir
    if ($peerVer) {
        $choice = Prompt-InstallChoice $label $peerVer
        Stop-VenvProcesses $Venv        # same respawn window as above
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
    & $VPy -m pip install @Find @Cons @ForceArgs $dir
    if ($LASTEXITCODE -ne 0) { & $VPy -m pip install @Cons @ForceArgs $dir }
    if ($LASTEXITCODE -ne 0) { Write-Host "  WARNING: $label install failed - continuing." }
}

if ($env:GM_PEER_DIR -and (Test-Path (Join-Path $env:GM_PEER_DIR "pyproject.toml"))) {
    # Coupled mode: called from Neuron or NeuRAG installer.
    # Always install GM + the calling peer, then detect other siblings and ask.
    $Find += Get-FindLinks @($env:GM_PEER_DIR)
    $PeerLabel = Split-Path -Leaf $env:GM_PEER_DIR
    Install-Peer $env:GM_PEER_DIR $PeerLabel
    # Detect other peers as siblings of the calling peer's parent
    $PeerParent = Split-Path -Parent $env:GM_PEER_DIR
    $OtherPeers = @()
    # GM_NO_NEURON / GM_NO_NEURAG were honoured only in the full-suite branch
    # below, so a caller that set them here got asked anyway — and the caller
    # that matters is a GUI installer with no stdin, where Read-Host hangs.
    # Same env contract in both branches now.
    if ($PeerLabel -ne "neuron" -and $PeerLabel -ne "Neuron" -and -not $env:GM_NO_NEURON) {
        $nd = Find-PeerIn "neuron" $PeerParent
        if ($nd) { $OtherPeers += @{dir=$nd; label="Neuron"} }
    }
    if ($PeerLabel -ne "neurag" -and $PeerLabel -ne "Neurag" -and -not $env:GM_NO_NEURAG) {
        $nd = Find-PeerIn "neurag" $PeerParent
        if ($nd) { $OtherPeers += @{dir=$nd; label="NeuRAG"} }
    }
    # -Yes / GM_YES = "don't ask": include what was found (the recommended
    # answer) instead of blocking on a prompt nobody can see. Opting a peer
    # OUT is what GM_NO_<PEER> is for.
    $GmAsk = $Ask   # one gate for every prompt (defined near the top)
    foreach ($op in $OtherPeers) {
        $opVer = Test-AlreadyInstalled $op.label.ToLower() $op.dir
        if ($opVer) {
            Write-Host "`n  $($op.label) $opVer detected alongside $PeerLabel."
        } else {
            Write-Host "`n  $($op.label) source found alongside $PeerLabel."
        }
        if (-not $GmAsk) {
            Write-Host "  Including $($op.label) (non-interactive; set GM_NO_$($op.label.ToUpper())=1 to skip)."
            Install-Peer $op.dir $op.label
            continue
        }
        Write-Host "  [Y]es — add $($op.label) to the suite"
        Write-Host "  [N]o  — keep $PeerLabel standalone"
        $ans = Read-Host "  Include $($op.label)? [Y]"
        if ($ans -notmatch '^(n|no)$') {
            Install-Peer $op.dir $op.label
        } else {
            Write-Host "  Skipping $($op.label)."
        }
    }
} else {
    # Full suite mode — tools bundled INSIDE the GM repo zip, or siblings.
    #
    # GM è l'ORCHESTRATORE: se un peer manca se lo scarica, non si limita a dire
    # all'utente di clonarselo. Prima era il contrario, e non aveva senso:
    # neuron/install.ps1 (Get-GrayMatter) tira dentro GM con tre fallback, mentre
    # GM — l'unico che dichiara di installare la full suite — stampava un
    # messaggio e proseguiva a metà. Nessun tag fisso qui: il branch di default è
    # quello che la CI dei peer testa, e una costante di versione da tenere
    # allineata a mano è esattamente la deriva che il guard su GM_VERSION ha
    # appena chiuso. Ogni passo degrada: git → zip → il vecchio messaggio.
    $PeerRepos = @{ "neuron" = "recla93/Neuron"; "neurag" = "recla93/neurag" }

    function Report-MissingPeer([string]$Label, [string]$Dir, [string]$Url) {
        Write-Host ""
        Write-Host "  [i] $Label not found next to Gray Matter - it will NOT be installed."
        Write-Host "      Gray Matter works on its own, with that half of the memory missing."
        Write-Host "      To add it: clone $Url into a '$Dir'"
        Write-Host "      folder next to this one, then run this installer again."
    }

    function Get-PeerFromGitHub([string]$pkg, [string]$label) {
        $repo = $PeerRepos[$pkg]
        $target = Join-Path $Root $pkg
        Write-Host ""
        Write-Host "  $label non è accanto a Gray Matter: lo scarico ($repo)."
        # 1) git — aggiornabile, ed è quello che vuole uno sviluppatore.
        if (Get-Command git -ErrorAction SilentlyContinue) {
            # NIENTE 2>&1: git scrive "Cloning into..." su stderr e PS 5.1 lo
            # trasformerebbe in un NativeCommandError su un clone riuscito.
            & git clone --depth 1 "https://github.com/$repo.git" $target
            $d = Find-PeerIn $pkg $Root
            if ($d) { Write-Host "      [OK] $label in $d"; return $d }
            Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue
            Write-Host "      git clone non ha prodotto un checkout usabile - provo lo zip."
        }
        # 2) zip del branch di default. `main` e `master` entrambi, invece di
        #    incollare qui il branch di ogni repo: si sposta senza avvisare.
        #    Lo zip estrae in `<repo>-<branch>` e Find-Peer ora lo riconosce dal
        #    pyproject, quindi il rename è un di più, non un requisito.
        $tmp = Join-Path $env:TEMP "gm-peer-$pkg-$PID"
        foreach ($branch in @("main", "master")) {
            Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Force -Path $tmp | Out-Null
            $zip = Join-Path $tmp "$pkg.zip"
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -UseBasicParsing -OutFile $zip `
                    -Uri "https://github.com/$repo/archive/refs/heads/$branch.zip"
            } catch { continue }
            if (-not (Test-Path $zip)) { continue }
            try { Expand-Archive -Path $zip -DestinationPath $tmp -Force } catch { continue }
            $ex = Get-ChildItem -Directory $tmp -ErrorAction SilentlyContinue |
                  Where-Object { Test-Path (Join-Path $_.FullName "pyproject.toml") } |
                  Select-Object -First 1
            if (-not $ex) { continue }
            # Il rename è best-effort: se fallisce (lock, permessi) si lascia la
            # cartella dov'è e la si usa comunque, invece di buttare il download.
            $dest = $target
            try { Move-Item -Path $ex.FullName -Destination $dest -Force -ErrorAction Stop }
            catch { $dest = $ex.FullName }
            Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
            if ((Get-ProjectName $dest) -eq $pkg) { Write-Host "      [OK] $label in $dest"; return $dest }
        }
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
        return $null
    }

    function Resolve-Peer([string]$pkg, [string]$label, [string]$dir) {
        if ($dir) { return $dir }
        $fetched = Get-PeerFromGitHub $pkg $label
        if ($fetched) { return $fetched }
        Write-Host "      download non riuscito (rete/git assenti?)."
        Report-MissingPeer $label $pkg "https://github.com/$($PeerRepos[$pkg])"
        return $null
    }

    if (-not $env:GM_NO_NEURON) {
        $NeuronDir = Resolve-Peer "neuron" "Neuron (semantic memory)" $NeuronDir
        if ($NeuronDir) { $Find += Get-FindLinks @($NeuronDir); Install-Peer $NeuronDir "Neuron" }
    }
    if (-not $env:GM_NO_NEURAG) {
        $NeuragDir = Resolve-Peer "neurag" "NeuRAG (knowledge base)" $NeuragDir
        if ($NeuragDir) { $Find += Get-FindLinks @($NeuragDir); Install-Peer $NeuragDir "NeuRAG" }
    }
}

# Last stop before the dependency phase (pyturso / pywebview / fastembed all
# write into site-packages). The "Include <peer>?" prompt above is another
# window in which the MCP client can respawn a server.
Stop-VenvProcesses $Venv

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

# Best-effort GUI nativa: pywebview. Senza, la GUI degrada al browser — che
# funziona ma vive appesa a una console (chiusa quella, GUI morta). Con la
# finestra nativa il control center è autosufficiente.
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
# hint the dev path — new in-package location first, legacy repo-root as fallback.
if ($NeuronDir) {
    foreach ($rel in @("src\neuron\clients", "clients")) {
        $cand = Join-Path $NeuronDir $rel
        if (Test-Path (Join-Path $cand "claude-code-hook\neuron_sessionstart_hook.py")) {
            $env:GM_NEURON_CLIENTS = $cand
            break
        }
    }
}
# Embedding model — asked HERE because the full-suite path installs Neuron
# without ever running Neuron's own installer, so these users were never given
# the choice. Same list and same persistence (neuron.config.set_user_env) as
# neuron/install.ps1 — keep the two in sync.
$EmbedModels = @(
    @{ name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"; dim = 384;  size = "220 MB"; note = "multilingual (EN+IT) - default, best size/quality" },
    @{ name = "sentence-transformers/all-MiniLM-L6-v2";                      dim = 384;  size = "90 MB";  note = "English only - smallest and fastest" },
    @{ name = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"; dim = 768;  size = "1.0 GB"; note = "multilingual, stronger - 2x storage per vector" },
    @{ name = "intfloat/multilingual-e5-large";                              dim = 1024; size = "2.2 GB"; note = "multilingual, best quality - heavy (RAM + disk)" }
)
function Select-GmEmbedModel {
    if ($EmbedModel) {
        foreach ($m in $EmbedModels) { if ($m.name -eq $EmbedModel) { return $m } }
        return @{ name = $EmbedModel; dim = 0; size = "?"; note = "custom" }
    }
    if (-not $Ask) { return $EmbedModels[0] }
    Write-Host "`n  Embedding model (downloaded once, defines the memory's vector space):"
    for ($i = 0; $i -lt $EmbedModels.Count; $i++) {
        $m = $EmbedModels[$i]
        Write-Host ("    [{0}] {1}" -f ($i + 1), $m.note)
        Write-Host ("        {0}  ({1}-dim, {2})" -f $m.name, $m.dim, $m.size)
    }
    Write-Host ""
    Write-Host "  Changing this later requires re-embedding the whole store."
    try { $a = Read-Host "  Choice [1]" } catch { $a = "" }
    if ($a -match '^[1-9][0-9]*$' -and [int]$a -le $EmbedModels.Count) { return $EmbedModels[[int]$a - 1] }
    return $EmbedModels[0]
}
function Save-GmEmbedModel([string]$Vpy, $Model) {
    # Never fatal: a wrong/absent model choice must not take the install down.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # Through the environment, not string-interpolated into the source: an
        # -EmbedModel with an apostrophe in it used to close the Python literal
        # and the choice was silently lost behind the generic "not saved" line.
        $env:GM_EMBED_NAME = $Model.name
        $env:GM_EMBED_DIM  = "$($Model.dim)"
        & $Vpy -c "import os
from neuron.config import set_user_env
print(set_user_env(NS_EMBED_MODEL=os.environ['GM_EMBED_NAME'], NS_EMBED_DIM=os.environ['GM_EMBED_DIM']))"
        if ($LASTEXITCODE -ne 0) { Write-Host "  (embedding model choice not saved - default stays active)"; return }
        Write-Host "`n  Downloading the embedding model ($($Model.size), one-time)."
        Write-Host "  Large models take several minutes - this is NOT frozen."
        $prevBars = $env:HF_HUB_DISABLE_PROGRESS_BARS
        $env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
        & $Vpy -W "ignore" -c "from neuron.server import _get_embedder
_get_embedder()
print('EMBED_MODEL_READY')"
        $env:HF_HUB_DISABLE_PROGRESS_BARS = $prevBars
        if ($LASTEXITCODE -eq 0) { Write-Host "  [OK] $($Model.name) cached." }
        else { Write-Host "  [!] download failed - Neuron retries on first use (install continues)." }
    } catch {
        Write-Host "  [!] embedding step skipped: $($_.Exception.Message)"
    } finally { $ErrorActionPreference = $prevEap }
}

# Tells `cli install` that this script owns the final word, so its own
# "Done. Restart your AI apps." does not land in the middle of our output.
$env:GM_INSTALLER = "1"

# `try { & native } catch { }` does NOT swallow a subprocess's stderr: the
# best-effort steps below stayed silent about failing while printing a full
# Python traceback into the log, right before the OK banner. Run them quietly and
# say, in one line, what was skipped and why.
function Invoke-BestEffort([string]$label, [scriptblock]$cmd) {
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        # Capture (not stream) so a failure can be reported as ONE line instead
        # of a traceback; on success the output is passed through unchanged,
        # since those lines are the confirmation the user is reading for.
        $out = & $cmd 2>&1
        if ($LASTEXITCODE -eq 0) { $out | ForEach-Object { Write-Host "$_" } }
        else {
            # Interpolare un ErrorRecord da' "System.Management.Automation.
            # RemoteException", cioe' il NOME DEL TIPO al posto del messaggio: e'
            # quello che il log del collega mostrava quattro volte di fila,
            # nascondendo l'errore vero (un venv senza pyvenv.cfg). Si estrae il
            # testo reale e si prende l'ultima riga NON vuota.
            $msg = @($out | ForEach-Object {
                if ($_ -is [System.Management.Automation.ErrorRecord]) {
                    if ($_.Exception -and $_.Exception.Message) { $_.Exception.Message }
                    else { $_.ToString() }
                } else { "$_" }
            } | Where-Object { "$_".Trim() } | Select-Object -Last 1)
            if (-not $msg) { $msg = "exit $LASTEXITCODE, nessun messaggio" }
            Write-Host "  [!] $label skipped: $msg"
        }
    } catch {
        Write-Host "  [!] $label skipped: $($_.Exception.Message)"
    } finally { $ErrorActionPreference = $prevEap }
}

# Trasloco sotto la radice unica, PRIMA di registrare qualsiasi cosa: se i dati
# si spostano dopo, il manifest e il registro puntano gia' ai path vecchi.
# Copia + verifica + rimozione, mai un move cieco (vedi migrate_to_suite_root).
Invoke-BestEffort "migrazione sotto GrayMatterEnvironment" {
    & $VPy -c "from gray_matter.paths import migrate_to_suite_root
for r in migrate_to_suite_root():
    print(('  [OK] ' if r['ok'] else '  [!] ') + r['from'] + ' -> ' + r['to'] + '  ' + r['detail'])"
}

# Cosa c'era gia' e se era allineato. Va DOPO l'install dei pacchetti (serve un
# venv da cui importare) ma PRIMA di registrare i client, cosi' un interprete
# morto o una suite incompleta si leggono qui e non come `spawn ... ENOENT`
# tre giorni dopo. Non aggiusta niente da solo: dice cosa e come.
Invoke-BestEffort "controllo dell'esistente" { & $VPy -m gray_matter.preflight }

Write-Host "Installing the gateway (register + hooks + manifest)..."
# Where to register: explicit -Client wins, else ask when there is a console,
# else "detected" (never touches a client the user does not have).
$ClientSel = if ($Client) { $Client } elseif ($Ask) { "ask" } else { "detected" }
try { & $VPy -m gray_matter.cli install --client $ClientSel }
catch { & $VPy -m gray_matter.cli register --gateway --client $ClientSel }

# Embedding model for Neuron (full-suite users never see neuron/install.ps1).
if ($NeuronDir) {
    $GmChosen = Select-GmEmbedModel
    Save-GmEmbedModel $VPy $GmChosen
}

# Registro path sorgente (SoC): ogni componente registra il PROPRIO sorgente nel
# proprio registro; GM li scopre chiedendo ai peer. Si riscrive a ogni install.
Invoke-BestEffort "source path record (gray-matter)" { & $VPy -m gray_matter.cli record-env --gm $Here }
if ($NeuronDir) { Invoke-BestEffort "source path record (Neuron)" { & $VPy -m neuron record-paths --source $NeuronDir } }
if ($NeuragDir) { Invoke-BestEffort "source path record (NeuRAG)" { & $VPy -m neurag.cli record-paths --source $NeuragDir } }

# --- GME Registry ---
# `cli install` above already registers every tool (installer.plan emits
# register_gme). Repeated here as the safety net for its `catch { cli register }`
# path, which writes no manifest and no registry: one line, same single writer,
# so the two can never drift the way six shell copies did.
Invoke-BestEffort "GME registry" { & $VPy -m gray_matter.gme register $Here }

# Desktop shortcut to the control center — a REAL Windows .lnk (with icon), not a
# raw .cmd. Targets pythonw.exe so there is no console flash; falls back to the
# python.exe icon if the bundled GM.ico can't be found.
$Desk = [Environment]::GetFolderPath("Desktop")
if ($Desk) {
    # pythonw.exe = windowed interpreter (no console); fall back to python.exe.
    $VPyw = Join-Path (Split-Path $VPy) "pythonw.exe"
    if (-not (Test-Path $VPyw)) { $VPyw = $VPy }

    # App dir (persist the icon there, out of the user's way).
    $AppDir = Join-Path $GmBase "graymatter"   # = paths.gm_home(), GM_HOME included
    if (-not (Test-Path $AppDir)) { New-Item -ItemType Directory -Force -Path $AppDir | Out-Null }

    # Use the bundled GM.ico (pre-rendered, no conversion needed).
    $IconPath = $VPyw   # sensible default: the interpreter's own icon
    try {
        $icoSrc = & $VPy -c "import gray_matter,os;p=os.path.join(os.path.dirname(gray_matter.__file__),'assets','gray-matter.ico');print(p) if os.path.isfile(p) else exit(1)"
        if ($icoSrc -and (Test-Path $icoSrc)) {
            $ico = Join-Path $AppDir "gray-matter.ico"
            Copy-Item $icoSrc $ico -Force
            if (Test-Path $ico) { $IconPath = $ico }
        }
    } catch { }   # any failure — keep the python.exe icon, never block install

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
        # COM unavailable (rare) — fall back to the old .cmd so the user still has a launcher.
        Set-Content -Path (Join-Path $Desk "Gray Matter GUI.cmd") `
            -Value "@`"$VPy`" -m gray_matter.cli gui" -Encoding ASCII
    }
}

# A peer install can leave the shared venv internally inconsistent (pip prints
# "dependency resolver ... conflicts" and still exits 0), and the banner below
# then declares success over a venv whose servers crash on import. Say it here,
# where the user is still reading, instead of at the next MCP startup.
$prevEap3 = $ErrorActionPreference; $ErrorActionPreference = "Continue"
$pipCheck = & $VPy -m pip check     # no 2>&1: PS 5.1 wraps native stderr in ErrorRecords
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    if (-not ($pipCheck | Where-Object { "$_".Trim() })) {
        # `pip check` fallito SENZA dire niente = non e' un conflitto, e'
        # l'interprete che non parte. Stampare "conflicting dependencies" con
        # l'elenco vuoto mandava a cercare il problema sbagliato.
        Write-Host "  [!] Il venv non e' utilizzabile: $VPy non risponde."
        Write-Host "      Rilancia con -Clear per ricostruirlo da zero."
    } else {
        Write-Host "  [!] The venv has conflicting dependencies - servers may fail to start:"
        $pipCheck | ForEach-Object { Write-Host "      $_" }
        Write-Host "      Fix: update the offending source to a version with matching pins and re-run."
    }
}
$ErrorActionPreference = $prevEap3

# An explicit, affirmative terminator: callers (and the user) could not tell
# "finished successfully" from "still working" or "died quietly".
$GmVer = "?"
try {
    $prevEap2 = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $GmVer = (& $VPy -m gray_matter.cli --version | Select-Object -Last 1)
    $ErrorActionPreference = $prevEap2
} catch { }
if (-not "$GmVer".Trim()) { $GmVer = "?" }
# Se la versione non si legge, l'interprete non parte: NIENTE e' installato, per
# quanto ne sappiamo. Il banner diceva comunque "[OK] INSTALL COMPLETE - Gray
# Matter ?", e un log del campo mostrava esattamente quello sopra quattro
# "failed to locate pyvenv.cfg". Un terminatore affermativo che non sa
# distinguere riuscito da morto e' peggio di nessun terminatore.
Write-Host ""
Write-Host "  ============================================================"
if ($GmVer -eq "?") {
    Write-Host "  [X] INSTALL FALLITA - Gray Matter non e' avviabile"
    Write-Host "  ============================================================"
    Write-Host "      $VPy non risponde (venv incompleto o corrotto)."
    Write-Host "      Rilancia con -Clear per ricostruire il venv da zero:"
    Write-Host "        powershell -ExecutionPolicy Bypass -File install.ps1 -Clear"
    exit 1
}
Write-Host "  [OK] INSTALL COMPLETE - Gray Matter $GmVer"
Write-Host "  ============================================================"
if ($NeuronDir) { Write-Host "  Neuron:  installed" }
if ($NeuragDir) { Write-Host "  NeuRAG:  installed" }
Write-Host "Done. Restart your AI apps to load the servers."
Write-Host "Control center: double-click 'Gray Matter' on your Desktop"
Write-Host "                (or run: $VPy -m gray_matter.cli gui)"
# L'installer NON apre piu' il control center da solo. Lanciarlo qui lo apriva
# nel momento peggiore — subito dopo aver scritto venv, registrazioni e
# shortcut, con il daemon non ancora a regime — ed era anche l'ultima cosa che
# l'utente vedeva fallire di un'installazione in realta' riuscita. In piu'
# girava con $VPy (python.exe, con console) invece che con pythonw.exe: un'altra
# finestra nera. L'icona sul Desktop c'e': la si apre quando si vuole.
