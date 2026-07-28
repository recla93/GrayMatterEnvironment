"""The three projects ship the same four launchers each. This asserts they stay
the same shape, so a fix applied to one and forgotten on the others fails here
instead of on a user's machine.

Every rule below exists because that exact drift already happened in this repo:

* the GME registry was hand-written in six shell copies, and the PowerShell BOM
  plus the macOS path divergence lived only in some of them;
* `install.command` never forwarded "$@", so every flag was silently dropped on
  macOS while the Windows `.cmd` forwarded `%*` fine;
* `pause` / `read` swallowed the installer's exit code, so a failed install
  reported success to whatever called the launcher — fixed in `.cmd` first and
  in `.command` only after a test caught the asymmetry;
* writing the POSIX scripts from Windows turned them CRLF, which on Linux is
  `bad interpreter: /usr/bin/env sh^M`.

Rules that are deliberately NOT symmetric are asserted as such, with the reason,
so "it differs" is always either a failure or a documented decision.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ("gray_matter", "neuron", "neurag")

WINDOWS = (".cmd", ".ps1")          # CRLF, native Windows tooling
POSIX = (".sh", ".command")         # LF, or `sh` chokes on the CR


def _read(project: str, suffix: str) -> str:
    return (ROOT / project / f"install{suffix}").read_text(encoding="utf-8")


def _bytes(project: str, suffix: str) -> bytes:
    return (ROOT / project / f"install{suffix}").read_bytes()


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("suffix", WINDOWS + POSIX)
def test_every_project_ships_every_launcher(project, suffix):
    assert (ROOT / project / f"install{suffix}").is_file()


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("suffix", WINDOWS + POSIX)
def test_line_endings(project, suffix):
    raw = _bytes(project, suffix)
    crlf = raw.count(b"\r\n")
    lf_only = raw.count(b"\n") - crlf
    if suffix in WINDOWS:
        assert crlf and not lf_only, f"install{suffix} must be CRLF"
    else:
        assert lf_only and not crlf, (
            f"install{suffix} must be LF — CRLF gives 'bad interpreter: ^M' on Linux")


@pytest.mark.parametrize("project", PROJECTS)
def test_cmd_forwards_args_and_exit_code(project):
    body = _read(project, ".cmd")
    assert "%*" in body, "must forward its arguments to install.ps1"
    assert "%ERRORLEVEL%" in body and "exit /b" in body, (
        "pause alone returns 0 — a failed install must not report success")


@pytest.mark.parametrize("project", PROJECTS)
def test_command_forwards_args_and_exit_code(project):
    body = _read(project, ".command")
    assert '"$@"' in body, "must forward its arguments to install.sh"
    assert "exit $RC" in body, "read alone returns its own status, not the installer's"


@pytest.mark.parametrize("project", PROJECTS)
def test_both_launchers_document_the_same_flags(project):
    cmd, command = _read(project, ".cmd"), _read(project, ".command")
    assert "-Force" in cmd and "-Clear" in cmd
    assert "--force" in command and "--clear" in command


@pytest.mark.parametrize("project", PROJECTS)
def test_ps1_accepts_clear_and_clear_implies_force(project):
    body = _read(project, ".ps1")
    assert "[switch]$Clear" in body
    assert "$Force = $true" in body, "-Clear must imply -Force"


@pytest.mark.parametrize("project", PROJECTS)
def test_sh_accepts_clear_and_clear_implies_force(project):
    body = _read(project, ".sh")
    assert "-c|--clear)" in body
    assert "CLEAR=1; FORCE=1" in body, "--clear must imply --force"


@pytest.mark.parametrize("project", PROJECTS)
def test_clear_never_touches_user_data(project):
    """-Clear removes the venv. It must not reach a graph store or a DB."""
    for suffix in (".ps1", ".sh"):
        body = _read(project, suffix)
        for forbidden in ("graphs", "knowledge.db", "bridges.json", "GrayMatterEnvironment"):
            wipes = [ln for ln in body.splitlines()
                     if forbidden in ln and ("rm -rf" in ln or "Remove-Item" in ln)]
            assert not wipes, f"install{suffix} deletes user data: {wipes}"


@pytest.mark.parametrize("project", PROJECTS)
def test_processes_are_stopped_before_pip_writes(project):
    """INSTALLER-UX §5.3. On Windows a loaded .pyd cannot be replaced, so pip
    fails with WinError 5 when a server is still running from the venv."""
    ps1 = _read(project, ".ps1")
    assert "Win32_Process" in ps1, (
        "Get-Process leaves .Path null for processes it cannot open — it found "
        "9 of 18 on a real machine, and the survivors still hold the lock")
    assert "Stop-Process" in ps1
    sh = _read(project, ".sh")
    assert "pkill" in sh


def test_gm_stops_processes_again_after_every_prompt():
    """GM is the only installer that prompts BETWEEN the stop and the writes:
    while the user reads the menu, the MCP client respawns the server it just
    lost. The peers stop after their own prompt, so one call is enough there —
    a documented asymmetry, not an oversight."""
    for suffix, token in ((".ps1", "Stop-VenvProcesses"), (".sh", "stop_venv_procs")):
        body = _read("gray_matter", suffix)
        calls = [ln for ln in body.splitlines()
                 if token in ln and not ln.lstrip().startswith(("#", "function"))
                 and "()" not in ln]
        assert len(calls) >= 3, f"gray_matter/install{suffix}: only {len(calls)} stop call(s)"

    for project in ("neuron", "neurag"):
        ps1 = _read(project, ".ps1").splitlines()
        stop = next(i for i, l in enumerate(ps1) if "VenvPids" in l)
        prompt = max(i for i, l in enumerate(ps1) if "Read-Host" in l)
        first_pip = next(i for i, l in enumerate(ps1[stop:], stop) if "pip install" in l)
        assert prompt < stop < first_pip, (
            f"{project}: a prompt slipped between the stop and the first pip")


@pytest.mark.parametrize("project", PROJECTS)
def test_no_installer_defaults_to_the_retired_neuron5_slug(project):
    for suffix in (".ps1", ".sh", ".cmd", ".command"):
        body = _read(project, suffix)
        assert "neuron5" not in body, (
            f"install{suffix}: the slug is 'neuron'; 'neuron5' only survives in "
            "the code paths that recognise it as legacy")


@pytest.mark.parametrize("project", PROJECTS)
def test_gme_registry_is_written_by_the_single_python_writer(project):
    """The 40-line hand-written JSON is gone from all six shell scripts; the BOM
    and the macOS path bug were only possible because it existed six times."""
    for suffix in (".ps1", ".sh"):
        body = _read(project, suffix)
        assert "gray_matter.gme register" in body
        assert '"installed_at"' not in body and "installed_at =" not in body, (
            "a hand-written GME JSON is back in the shell")


# --- cross-project: clients / bridges / tunnels ----------------------------

CLIENT_MODULES = {
    "gray_matter": ROOT / "gray_matter" / "clients.py",
    "neuron": ROOT / "neuron" / "src" / "neuron" / "clients.py",
    "neurag": ROOT / "neurag" / "clients.py",
}


@pytest.mark.parametrize("project", PROJECTS)
def test_no_client_config_is_created_for_an_app_that_is_not_installed(project):
    """Registration must never invent a config file. Neuron created one for
    Cursor, Codex and OpenCode, NeuRAG for Cursor and OpenCode — on a machine
    where Cursor and OpenCode were not installed, the installer wrote
    ~/.cursor/mcp.json and ~/.config/opencode/opencode.json anyway. Worse, once
    the file exists executor.detect_state() counts that client as present
    forever and keeps deploying hooks into it."""
    body = CLIENT_MODULES[project].read_text(encoding="utf-8")
    assert '"create_if_missing": True' not in body


def test_the_three_projects_agree_on_the_creation_flag():
    """gray_matter checked `create`, the peers `create_if_missing`. Nothing
    defines `create`, so the opt-in was dead on one side and live on the other —
    the exact shape of drift this file exists to catch."""
    for project, path in CLIENT_MODULES.items():
        body = path.read_text(encoding="utf-8")
        assert "create_if_missing" in body, f"{project} uses a different key"
        assert 'spec.get("create")' not in body, f"{project} still reads the dead key"


# --- cross-project: nessuna API deprecata a sorgente -----------------------

SOURCE_DIRS = {
    "gray_matter": ROOT / "gray_matter",
    "neuron": ROOT / "neuron" / "src" / "neuron",
    "neurag": ROOT / "neurag",
}

# (pattern, perché) — tutte deprecate o rimosse entro Python 3.14
DEPRECATED_APIS = [
    ("asyncio.get_event_loop()", "deprecato con un loop attivo; usa get_running_loop()"),
    ("datetime.utcnow(", "deprecato in 3.12; usa datetime.now(timezone.utc)"),
    ("datetime.utcfromtimestamp(", "deprecato in 3.12"),
    ("pkg_resources", "rimosso da setuptools recenti; usa importlib.metadata"),
    ("locale.getdefaultlocale(", "deprecato in 3.11"),
    ('.metadata["Name"]', "Message.__getitem__ implicit None deprecato in 3.14"),
]


def _code_only(body: str) -> str:
    """Drop comment lines. A rule about an API has to name that API in the
    comment that explains why it is banned — without this, every fix documented
    in place would trip its own guard."""
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.lstrip().startswith("#"))


@pytest.mark.parametrize("project", PROJECTS)
def test_no_deprecated_stdlib_api_in_source(project):
    """Trovato per davvero: install.ps1 leggeva d.metadata["Name"] e su 3.14
    l'installer stampava un DeprecationWarning a ogni run."""
    root = SOURCE_DIRS[project]
    bad = []
    for f in root.rglob("*.py"):
        if "build" in f.parts or ".venv" in f.parts or "tests" in f.parts:
            continue
        body = _code_only(f.read_text(encoding="utf-8", errors="ignore"))
        for pat, why in DEPRECATED_APIS:
            if pat in body:
                bad.append(f"{f.relative_to(ROOT)}: {pat} — {why}")
    assert not bad, "API deprecate a sorgente:\n" + "\n".join(bad)


@pytest.mark.parametrize("project", PROJECTS)
def test_no_deprecated_api_in_the_installers(project):
    for suffix in (".ps1", ".sh"):
        body = _code_only(_read(project, suffix))
        assert '.metadata["Name"]' not in body, (
            f"install{suffix}: emette un DeprecationWarning su Python 3.14")


# --- cross-project: robustezza degli installer --------------------------------

@pytest.mark.parametrize("project", PROJECTS)
def test_venv_is_validated_not_just_present(project):
    r"""`Test-Path $Venv` / `[ -d $VENV ]` non è un test di salute. Una rimozione
    interrotta (processo che tiene un .pyd) lascia Lib\ e Scripts\ senza
    pyvenv.cfg: la cartella esiste, la creazione viene saltata, e il primo pip
    muore con `python.exe : failed to locate pyvenv.cfg`. Successo reale."""
    ps1 = _code_only(_read(project, ".ps1"))
    assert "Test-VenvHealthy" in ps1, "manca il controllo di salute del venv"
    assert "pyvenv.cfg" in ps1
    sh = _code_only(_read(project, ".sh"))
    assert "venv_healthy" in sh and "pyvenv.cfg" in sh


@pytest.mark.parametrize("project", PROJECTS)
def test_a_damaged_venv_is_rebuilt_not_inherited(project):
    for suffix, token in ((".ps1", "Test-VenvHealthy $Venv"), (".sh", "venv_healthy")):
        body = _code_only(_read(project, suffix))
        assert "Damaged venv detected" in body, (
            f"install{suffix}: un mezzo-venv viene ereditato invece che ricostruito")


@pytest.mark.parametrize("project", PROJECTS)
def test_no_native_stderr_redirect_in_powershell(project):
    """In PowerShell 5.1 redirigere lo stderr di un ESEGUIBILE avvolge ogni riga
    in un ErrorRecord (NativeCommandError): sotto ErrorActionPreference=Stop
    diventa fatale anche con exit code 0. È così che un warning di pip ha ucciso
    l'installer con un traceback PowerShell. La redirezione È il problema."""
    import re
    offenders = []
    for n, line in enumerate(_read(project, ".ps1").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if re.search(r"&\s+[\$\(]", line) and "2>$null" in line:
            offenders.append(f"riga {n}: {line.strip()[:70]}")
    assert not offenders, "redirezioni native fatali:\n" + "\n".join(offenders)
