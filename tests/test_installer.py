"""Installer idempotency brain (INSTALLER-UX §5). plan() is pure; record_install
writes the manifest. Stdlib-only."""
import os

from gray_matter import installer as I
from gray_matter import paths as P


def _actions(plan):
    return [a["action"] for a in plan]


def test_fresh_install_registers_only_gateway():
    plan = I.plan({"installed": ["neuron"], "gm_present": False,
                   "clients": ["cursor", "claude-code"]})
    assert _actions(plan) == ["ensure_data", "install", "register",
                              "deploy_hook", "write_manifest"]   # hook: claude-code only
    reg = [a for a in plan if a["action"] == "register"][0]
    assert reg["target"] == "gray_matter"                # ONLY the gateway
    assert reg["clients"] == ["claude-code", "cursor"]   # sorted+deduped


def test_idempotent_when_gm_present():
    plan = I.plan({"installed": ["gray_matter"], "gm_present": True, "clients": []})
    assert "install" not in _actions(plan)               # not reinstalled
    assert _actions(plan) == ["write_manifest"]          # nothing to register (no clients)


def test_orphans_reaped_first():
    plan = I.plan({"orphan_pids": [111, 222], "gm_present": True})
    assert plan[0] == {"action": "reap", "pids": [111, 222]}


def test_subservers_never_registered():
    plan = I.plan({"installed": ["neuron", "neurag"], "gm_present": True,
                   "clients": ["vscode"]})
    reg = [a for a in plan if a["action"] == "register"][0]
    assert reg["target"] == "gray_matter"                # neuron/neurag are workers, not connectors


def test_hooks_deployed_per_client_and_tracked(tmp_path):
    plan = I.plan({"gm_present": True, "clients": ["claude-code", "cursor", "cowork"]})
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
