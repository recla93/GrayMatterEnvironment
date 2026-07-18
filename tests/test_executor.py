"""Executor tests — tmp-dir only (GM_HOME + HOME patched), no live processes.

Static/sandbox coverage of the effectful wrappers; the real-machine pass
(processes, 6 client configs) stays a local step per ENVIRONMENT.md.
"""
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
ASSETS = REPO / "Neuron" / "clients"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GM_HOME", str(tmp_path / "gmhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path


def _run_install(state, **kw):
    from gray_matter import executor
    return executor.execute_install(state, assets_root=ASSETS, **kw)


def test_install_creates_dirs_and_manifest(env):
    from gray_matter import paths
    res = _run_install({"installed": ["neuron", "neurag"], "gm_present": False,
                        "clients": []})
    assert all(r["ok"] for r in res)
    assert paths.neuron_graphs().exists()
    assert paths.neurag_db().parent.exists()
    assert paths.app_dir().exists()
    assert paths.config_file().exists()
    m = json.loads(paths.manifest_path().read_text(encoding="utf-8"))
    assert m["components"]["gray_matter"]["registered"] is True
    assert m["components"]["neuron"]["registered"] is False


def test_install_dry_run_touches_nothing(env):
    from gray_matter import paths
    res = _run_install({"installed": ["neuron"], "gm_present": False,
                        "clients": []}, dry_run=True)
    assert all(r["ok"] for r in res)
    assert not paths.gm_home().exists()
    assert not paths.neuron_graphs().exists()


def test_deploy_hook_claude_code(env):
    home = env / "home"
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    res = _run_install({"installed": [], "gm_present": True,
                        "clients": ["claude-code"]})
    hook = [r for r in res if r["action"] == "deploy_hook"][0]
    assert hook["ok"], hook
    dest = home / ".claude" / "hooks" / "neuron_sessionstart_hook.py"
    assert dest.exists()
    cfg = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [h["command"] for g in cfg["hooks"]["SessionStart"] for h in g["hooks"]]
    assert any("neuron_sessionstart_hook" in c for c in cmds)
    # idempotent: second run doesn't duplicate the entry
    _run_install({"installed": [], "gm_present": True, "clients": ["claude-code"]})
    cfg2 = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert len(cfg2["hooks"]["SessionStart"]) == len(cfg["hooks"]["SessionStart"])
    # manifest tracks the deployed path
    from gray_matter import paths
    m = json.loads(paths.manifest_path().read_text(encoding="utf-8"))
    assert str(dest) in m["hooks"]["claude-code"]


def test_deploy_hook_cowork_and_opencode(env):
    home = env / "home"
    res = _run_install({"installed": [], "gm_present": True,
                        "clients": ["cowork", "opencode"]})
    hooks = {r["client"]: r for r in res if r["action"] == "deploy_hook"}
    assert hooks["cowork"]["ok"] and hooks["opencode"]["ok"]
    assert (home / ".claude" / "plugins" / "neuron-guard" / "hooks" / "hooks.json").exists()
    mjs = home / ".config" / "opencode" / "plugins" / "neuron-handshake.mjs"
    assert mjs.exists()
    cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
    assert any("neuron-handshake" in p for p in cfg["plugin"])


def test_uninstall_removes_hooks_code_and_asks_data(env):
    from gray_matter import executor, paths
    home = env / "home"
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    _run_install({"installed": ["neuron"], "gm_present": False,
                  "clients": ["claude-code", "opencode"]})
    paths.neuron_graphs().mkdir(parents=True, exist_ok=True)
    (paths.neuron_graphs() / "g.json").write_text("{}", encoding="utf-8")
    asked = []
    res = executor.execute_uninstall(ask=lambda q: (asked.append(q), False)[1])
    by_action = {}
    for r in res:
        by_action.setdefault(r["action"], []).append(r)
    assert all(r["ok"] for rs in by_action.values() for r in rs)
    # hooks gone, entry scrubbed
    assert not (home / ".claude" / "hooks" / "neuron_sessionstart_hook.py").exists()
    cfg = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert not cfg.get("hooks", {}).get("SessionStart")
    oc = json.loads((home / ".config" / "opencode" / "opencode.json").read_text(encoding="utf-8"))
    assert not any("neuron-handshake" in p for p in oc.get("plugin", []))
    # code removed, memory KEPT (answered no)
    assert not paths.app_dir().exists() and not paths.manifest_path().exists()
    assert (paths.neuron_graphs() / "g.json").exists()
    assert asked, "must ask before touching the memory"


def test_uninstall_purge_wipes_data_without_asking(env):
    from gray_matter import executor, paths
    _run_install({"installed": ["neuron"], "gm_present": False, "clients": []})
    (paths.neuron_graphs() / "g.json").write_text("{}", encoding="utf-8")
    res = executor.execute_uninstall(
        purge_data=True, ask=lambda q: pytest.fail("must not ask with purge_data"))
    assert all(r["ok"] for r in res)
    assert not paths.neuron_graphs().exists()


def test_uninstall_dry_run_never_asks_nor_touches(env):
    from gray_matter import executor, paths
    _run_install({"installed": ["neuron"], "gm_present": False, "clients": []})
    res = executor.execute_uninstall(
        dry_run=True, ask=lambda q: pytest.fail("dry-run must not prompt"))
    assert all(r["ok"] for r in res)
    assert paths.app_dir().exists() and paths.manifest_path().exists()


def test_deregister_scrubs_json_client(env):
    from gray_matter import clients
    home = env / "home"
    cfgp = home / ".cursor" / "mcp.json"
    cfgp.parent.mkdir(parents=True)
    cfgp.write_text(json.dumps({"mcpServers": {
        "gray-matter": {"command": "py"}, "neuron5": {"command": "py"},
        "other": {"command": "keep"}}}), encoding="utf-8")
    res = [r for r in clients.deregister() if r.get("detail") == str(cfgp)]
    assert res and res[0]["ok"]
    data = json.loads(cfgp.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"other"}
    assert (home / ".cursor" / "mcp.json.bak").exists()
