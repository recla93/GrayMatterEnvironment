"""Installer idempotency brain (INSTALLER-UX §5). plan() is pure; record_install
writes the manifest. Stdlib-only."""
import os

import pytest

from gray_matter import installer as I
from gray_matter import paths as P


def _actions(plan):
    return [a["action"] for a in plan]


def test_fresh_install_registers_only_gateway():
    plan = I.plan({"installed": ["neuron"], "gm_present": False,
                   "clients": ["cursor", "claude-code"]})
    assert _actions(plan) == ["ensure_data", "install", "register",
                              "deploy_hook", "write_manifest",
                              "register_gme"]                    # hook: claude-code only
    reg = [a for a in plan if a["action"] == "register"][0]
    assert reg["target"] == "gray_matter"                # ONLY the gateway
    assert reg["clients"] == ["claude-code", "cursor"]   # sorted+deduped


def test_idempotent_when_gm_present():
    plan = I.plan({"installed": ["gray_matter"], "gm_present": True, "clients": []})
    assert "install" not in _actions(plan)               # not reinstalled
    # nothing to register in clients (no clients) — but GME still gets refreshed,
    # so a re-run repairs a registry that an older installer never wrote
    assert _actions(plan) == ["write_manifest", "register_gme"]


def test_dry_run_never_reports_work_it_did_not_do():
    """--dry-run has one job: say what *would* happen. The hook deployers guard
    their writes but returned the same past-tense detail either way, so a dry-run
    claimed the hook was copied and registered."""
    from gray_matter import executor as E

    rm = E._remove_code(dry_run=True)
    assert rm["removed"] == [] and rm["detail"].startswith("[dry-run]")

    hooks = [r for r in E.execute_install({"installed": ["neuron"], "gm_present": True,
                                           "clients": ["claude-code"]}, dry_run=True)
             if r["action"] == "deploy_hook"]
    assert hooks, "no hook deployed in the plan — test is vacuous"
    for r in hooks:
        assert str(r["detail"]).startswith("[dry-run]"), r["detail"]


def test_orphans_reaped_first():
    plan = I.plan({"orphan_pids": [111, 222], "gm_present": True})
    assert plan[0] == {"action": "reap", "pids": [111, 222]}


def test_subservers_never_registered():
    plan = I.plan({"installed": ["neuron", "neurag"], "gm_present": True,
                   "clients": ["vscode"]})
    reg = [a for a in plan if a["action"] == "register"][0]
    assert reg["target"] == "gray_matter"                # neuron/neurag are workers, not connectors


def test_no_hooks_without_neuron():
    # NeuRAG+GM (no Neuron): the handshake assets ship inside the neuron package,
    # so there is nothing to deploy — planning one produced a bogus "asset missing".
    plan = I.plan({"installed": ["neurag"], "gm_present": True,
                   "clients": ["claude-code", "opencode"]})
    assert "deploy_hook" not in _actions(plan)


def test_hooks_deployed_per_client_and_tracked(tmp_path):
    plan = I.plan({"installed": ["neuron"], "gm_present": True,
                   "clients": ["claude-code", "cursor", "cowork"]})
    hooks = [a for a in plan if a["action"] == "deploy_hook"]
    assert [h["client"] for h in hooks] == ["claude-code", "cowork"]  # cursor: instructions only
    assert all(h["asset"] for h in hooks)

    os.environ["GM_HOME"] = str(tmp_path)
    import importlib; importlib.reload(P)
    I.record_install({"installed": [], "hooks": {"claude-code": "~/.claude/hooks/x.py"}})
    m = P.Manifest.load()
    assert m.data["hooks"]["claude-code"] == ["~/.claude/hooks/x.py"]


def test_stdio_init_options_build():
    # capabilities is a required field — this crashes if main()'s handshake breaks
    pytest.importorskip("mcp")  # builds real InitializationOptions; needs MCP (local/CI)
    from gray_matter import server
    opts = server._init_options()
    assert opts.capabilities is not None
    assert "pre_turn" in opts.instructions


def test_record_install_writes_manifest(tmp_path):
    os.environ["GM_HOME"] = str(tmp_path)
    import importlib; importlib.reload(P)
    I.record_install({"installed": ["neuron", "gray_matter"], "clients": ["cursor"]})
    m = P.Manifest.load()
    assert m.components()["gray_matter"]["registered"] is True
    assert m.components()["neuron"]["registered"] is False
    assert m.data["clients"] == ["cursor"]


# --- -Clear: the part that did nothing -----------------------------------

import re                                          # noqa: E402
import shutil                                      # noqa: E402
import subprocess                                  # noqa: E402
from pathlib import Path                           # noqa: E402

_HERE = Path(__file__).resolve().parents[1]
_PS1 = (_HERE / "install.ps1").read_text(encoding="utf-8")
_SH = (_HERE / "install.sh").read_text(encoding="utf-8")


def test_removing_a_venv_counts_content_not_the_folder():
    """An EMPTY folder survives its own deletion for as long as a process
    holds it as its working directory: `Test-Path` stays $true, and -Clear
    called a perfectly successful removal a failure, exited 1, and reinstalled
    nothing — hence "-Clear does nothing". Seen live: 283 MB gone, empty folder
    pinned, exit 1.

    The guard must count the CONTENT before declaring failure."""
    ps_fail = _PS1[_PS1.index("function Remove-Venv"):]
    ps_fail = ps_fail[:ps_fail.index("could not fully remove")]
    assert "Get-ChildItem" in ps_fail, "install.ps1 is trusting Test-Path again"

    sh_fail = _SH[_SH.index("remove_venv() {"):]
    sh_fail = sh_fail[:sh_fail.index("could not fully remove")]
    assert "ls -A" in sh_fail, "install.sh is trusting [ -d ] again"


def test_the_wipe_retries_when_something_respawns_into_it():
    """Killing harder is not the answer: deleting 280 MB takes seconds, and a
    client respawning DURING the delete re-locks files the sweep already passed.
    Seen live: one pass left 8422 items behind, while the very same Remove-Item
    run by hand a minute later cleaned everything with no error. So kill+remove
    must LOOP, not fire once."""
    ps = _PS1[_PS1.index("function Remove-Venv"):]
    ps = ps[:ps.index("could not fully remove")]
    assert ps.count("Stop-VenvProcesses") >= 1 and "for (" in ps, (
        "install.ps1: kill+remove do not loop")
    sh = _SH[_SH.index("remove_venv() {"):]
    sh = sh[:sh.index("could not fully remove")]
    assert "while [" in sh and "stop_venv_procs" in sh, "install.sh: kill+remove do not loop"


def test_clear_deletes_the_venvs_of_the_previous_install_locations():
    """The two historical paths were only LOOKED AT (to inherit one) and never
    removed: they sat on disk forever, named by no command at all. -Clear is the
    one moment an install converges on the new location."""
    for name, text, legacy in (("install.ps1", _PS1, "$LegacyVenvs"),
                               ("install.sh", _SH, "gray-matter/.venv")):
        clear = text[text.index("Clear: removing the venv"):]
        clear = clear[:clear.index("Damaged venv detected")]
        assert "previous install location" in clear, f"{name}: -Clear does not remove the old venvs"
        assert legacy in clear, f"{name}: the removal does not run over the legacy paths"
    # And the two historical paths must stay NAMED somewhere, or the loop
    # above spins over nothing.
    assert r"graymatter\.venv" in _PS1 and r"gray-matter\.venv" in _PS1
    assert "graymatter/.venv" in _SH and "gray-matter/.venv" in _SH


def test_clear_does_not_inherit_the_location_it_is_meant_to_leave():
    """Adopting the old venv in the very command meant to start clean is how an
    install never converges on the GME root."""
    assert re.search(r"if \(-not \$Clear\) \{\s*\n\s*foreach \(\$old in \$LegacyVenvs\)", _PS1)
    assert re.search(r'if \[ "\$CLEAR" != "1" \]; then\s*\n\s*for _old in', _SH)


def test_stopping_the_servers_survives_a_client_respawning_them():
    """The MCP client restarts its stdio server within a few hundred ms: a
    single kill leaves the children holding files exactly while pip writes, and
    that is the window where an upgrade half-fails. Seen live: 8 processes
    killed, 26 alive a minute later."""
    ps = _PS1[_PS1.index("function Stop-VenvProcesses"):]
    ps = ps[:ps.index("\n}\n")]
    assert "for (" in ps, "install.ps1: a single kill pass"
    sh = _SH[_SH.index("stop_venv_procs() {"):]
    sh = sh[:sh.index("\n}\n")]
    assert "while [" in sh, "install.sh: a single kill pass"


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell not available")
def test_the_windows_installer_still_parses():
    """1100 lines of PowerShell: nobody sees a syntax error until a user
    double-clicks."""
    ps = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
          f"'{_HERE / 'install.ps1'}', [ref]$null, [ref]$e); "
          "if ($e) { $e | ForEach-Object { $_.Message }; exit 1 }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh not available")
def test_the_posix_installer_still_parses():
    r = subprocess.run(["sh", "-n", str(_HERE / "install.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
