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

import re
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
def test_cmd_has_no_bom_and_is_pure_ascii(project):
    r"""cmd.exe does not understand a UTF-8 BOM: it becomes part of the first
    token, so `@echo off` turns into an unknown command and every later `rem`
    echoes to the screen. It also reads the file in the OEM codepage, so a
    UTF-8 em dash renders as mojibake (`ÔÇö`). Really happened — a line-ending
    normalisation wrote these with utf-8-sig and broke all three launchers.

    .ps1 is the OPPOSITE (see the next test): PowerShell 5.1 needs the BOM."""
    raw = _bytes(project, ".cmd")
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        "install.cmd must NOT start with a UTF-8 BOM — cmd.exe chokes on it")
    try:
        raw.decode("ascii")
    except UnicodeDecodeError as e:
        raise AssertionError(
            f"install.cmd must be pure ASCII (cmd.exe reads it in the OEM "
            f"codepage, so anything else is mojibake): {e}") from None


@pytest.mark.parametrize("project", PROJECTS)
def test_ps1_keeps_its_bom(project):
    """The mirror rule. Windows PowerShell 5.1 decodes a BOM-less script as
    ANSI, so the accented comments and box-drawing output come out wrong."""
    assert _bytes(project, ".ps1").startswith(b"\xef\xbb\xbf"), (
        "install.ps1 must keep its UTF-8 BOM for PowerShell 5.1")


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("suffix", POSIX)
def test_posix_launchers_have_no_bom(project, suffix):
    """`sh` would try to execute the BOM as part of the shebang line."""
    assert not _bytes(project, suffix).startswith(b"\xef\xbb\xbf"), (
        f"install{suffix} must not have a BOM")


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


# --- feature parity: no installer may fall behind the others ----------------
#
# Gray Matter's installer is the one most users run (it bundles the suite), and
# it was the one missing every hardening the peers grew: the prompt gate, the
# embedding-model question, the client picker, the completion banner. Drift in
# the direction of "the main entry point is the stale one" is exactly what this
# file exists to catch, so the features are asserted, not just the shapes.

PS1_FEATURES = {
    "a prompt gate so no Read-Host can hang a console-less caller": "$Ask",
    "the embedding-model question": "EmbedModel",
    "a client picker (WHERE to register)": "--client",
    "an affirmative completion banner": "INSTALL COMPLETE",
}
SH_FEATURES = {
    "a tty check so no prompt blocks a piped run": "-t 0",
    "the embedding-model question": "EMBED_MODEL",
    "a client picker (WHERE to register)": "--client",
    "an affirmative completion banner": "INSTALL COMPLETE",
}


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("why,token", sorted(PS1_FEATURES.items()))
def test_every_ps1_has_every_feature(project, why, token):
    assert token in _read(project, ".ps1"), f"{project}/install.ps1 is missing {why}"


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("why,token", sorted(SH_FEATURES.items()))
def test_every_sh_has_every_feature(project, why, token):
    assert token in _read(project, ".sh"), f"{project}/install.sh is missing {why}"


def _offered_models(project: str, suffix: str) -> list[str]:
    """The model names a picker offers. `""` is a real entry — NeuRAG's "follow
    Neuron" — so absence and empty string are different answers here."""
    body = _read(project, suffix)
    if suffix == ".ps1":
        block = re.search(r"\$EmbedModels\s*=\s*@\((.*?)\n\)", body, re.S)
        return re.findall(r'name\s*=\s*"([^"]*)"', block.group(1)) if block else []
    return [ln.split("=", 1)[1].strip('"').split("|")[0]
            for ln in body.splitlines() if re.match(r'^(GM_)?EM_\d+="', ln)]


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("suffix", (".ps1", ".sh"))
def test_no_installer_offers_to_skip_the_embedder(project, suffix):
    """Embedding is mandatory in all three: fastembed and pyturso are hard
    dependencies, so an install either has them or fails.

    NeuRAG's picker kept a `"none" — lexical only, no model download` entry from
    the days when fastembed was an optional extra. It contradicted the
    dependency — NeuRAG's own numbers are recall@5 67% vector-only vs 94% hybrid
    — and it lied twice over: the branch wrote `embed_model = ''`, which means
    "follow Neuron / the multilingual default", so it announced that no model
    would be downloaded and then configured one. Nothing ever wrote the literal
    "none" that `lexical_only_requested()` looks for.

    Lexical-only is still reachable through `neurag config set embed_model none`.
    The rule is about the INSTALLER: it must not offer the degraded half of the
    tool as a menu entry.
    """
    offered = _offered_models(project, suffix)
    assert offered, f"{project}/install{suffix}: no embedding picker found at all"
    bad = [m for m in offered if m.strip().lower() in ("none", "null")]
    assert not bad, f"{project}/install{suffix} offers to skip embedding: {bad}"
    assert "Lexical only" not in _read(project, suffix), (
        f"{project}/install{suffix} still advertises a lexical-only install")


@pytest.mark.parametrize("project", PROJECTS)
def test_the_two_pickers_of_a_project_offer_the_same_models(project):
    """The `.ps1` list and the `.sh` list are hand-maintained copies of each
    other — the comment says "keep in sync" and nothing checked it. Renumbering
    one of them (removing an entry shifts every `EM_n` and every `case` arm) is
    exactly how the two drift apart."""
    assert _offered_models(project, ".ps1") == _offered_models(project, ".sh"), (
        f"{project}: install.ps1 and install.sh offer different models")


@pytest.mark.parametrize("project", PROJECTS)
def test_every_installer_agrees_on_one_vector_space(project):
    """Vectors from different models are not comparable, so the three tools must
    land in ONE space. Two legitimate ways to say that:

    * name the 384-dim multilingual default (Neuron, and Gray Matter which
      installs Neuron in the full-suite path);
    * defer to Neuron explicitly (NeuRAG — its picker's first option is
      "follow Neuron", and its embedder reads NS_EMBED_MODEL).

    What must never appear is a THIRD answer: a different default of its own.
    """
    default = "paraphrase-multilingual-MiniLM-L12-v2"
    for suffix in (".ps1", ".sh"):
        body = _read(project, suffix)
        names_default = default in body
        defers = "Follow Neuron" in body or "following Neuron" in body
        assert names_default or defers, (
            f"{project}/install{suffix}: neither names the shared default "
            f"({default}) nor defers to Neuron — that is a third vector space")


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


@pytest.mark.parametrize("project", PROJECTS)
def test_interpreter_output_is_never_cast_unguarded(project):
    """Il probe di versione non deve poter UCCIDERE l'installer.

    `[int]$v` sull'output di un candidato Python era senza rete: sotto
    ErrorActionPreference=Stop un cast fallito è FATALE, e su una macchina
    pulita — l'unica per cui quel ramo esiste — basta che il candidato stampi
    qualcosa di non numerico (l'App Execution Alias dello Store, un banner
    conda/pyenv, un wrapper che saluta prima di rispondere) per far morire
    l'installer con un errore .NET grezzo invece di "Python non trovato, lo
    installo io". neuron/neurag validavano già con una regex; gray_matter, cioè
    il punto d'ingresso che un utente nuovo lancia davvero, no.
    """
    lines = _read(project, ".ps1").splitlines()
    offenders = []
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        # Un cast a [int]/[Version] di una VARIABILE va protetto da un controllo
        # di forma: sulla riga stessa o nelle 3 sopra (il guard tipico è
        # `if ($x -notmatch '^\d+$') { return 0 }`). `Sort-Object { [Version]$_ }`
        # su una lista già filtrata da una regex passa per la stessa regola.
        if not re.search(r"\[(int|Version)\]\s*[(\"']?\$", line):
            continue
        window = "\n".join(lines[max(0, n - 4):n])
        if "-match" in window or "-notmatch" in window:
            continue
        offenders.append(f"riga {n}: {line.strip()[:70]}")
    assert not offenders, (
        "cast non protetto sull'output dell'interprete:\n" + "\n".join(offenders))
