"""GME registry (ADR-009) — the SSOT that answers "where is this tool's Python?".

Covers the four phases of InstallAndGuiRefactorNEW that had no tests at all:
Phase 1 (read/write/list/health/mark_missing), Phase 2 (status gates the
python/venv lookups that webgui._python_for_tool depends on), Phase 3
(migration detection), Phase 4 (health merge) — plus the uninstall wiring that
stops discovery from handing out a venv path that no longer exists.

gme_root() is monkeypatched instead of the platform env vars so the same test
file is valid on Windows, macOS and Linux.
"""
import json

import pytest

from gray_matter import gme, uninstaller


@pytest.fixture(autouse=True)
def _gme_in_tmp(tmp_path, monkeypatch):
    root = tmp_path / "GrayMatterEnvironment"
    monkeypatch.setattr(gme, "gme_root", lambda: root)
    # _find_venv_for() reads LOCALAPPDATA/XDG_DATA_HOME directly, so without this
    # the suite passes or fails depending on whether the machine running it
    # happens to have a real install.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    return root


def _tool(key="neuron", **over):
    data = {"key": key, "label": key.title(), "version": "6.1.2",
            "venv": f"/opt/{key}/.venv", "python": f"/opt/{key}/.venv/bin/python",
            "module": key, "cli_module": f"{key}.cli"}
    data.update(over)
    return data


# --- Phase 1: read / write / list -----------------------------------------

def test_write_then_read_roundtrip():
    gme.write_tool(_tool())
    got = gme.read_tool("neuron")
    assert got["version"] == "6.1.2"
    assert got["status"] == "installed"          # defaulted
    assert got["health"]["pid"] is None          # defaulted


def test_read_missing_returns_none():
    assert gme.read_tool("nope") is None


def test_reading_never_creates_the_gme_folder(_gme_in_tmp):
    """A read must not leave %LOCALAPPDATA%\\GrayMatterEnvironment behind on a
    machine where nothing was ever installed — tool_json_path used to call
    ensure_gme()."""
    assert gme.read_tool("neuron") is None
    assert gme.list_tools() == []
    assert gme.get_python("neuron") is None
    assert not _gme_in_tmp.exists()

    gme.write_tool(_tool())                  # writing is what creates it
    assert _gme_in_tmp.exists()


def test_read_rejects_corrupt_and_incomplete_json(_gme_in_tmp):
    _gme_in_tmp.mkdir(parents=True, exist_ok=True)
    (_gme_in_tmp / "broken.json").write_text("{not json", encoding="utf-8")
    (_gme_in_tmp / "partial.json").write_text('{"key": "partial"}', encoding="utf-8")
    assert gme.read_tool("broken") is None
    assert gme.read_tool("partial") is None      # no "python" field


def test_write_requires_key():
    with pytest.raises(ValueError):
        gme.write_tool({"label": "no key"})


def test_write_is_atomic_no_tmp_left(_gme_in_tmp):
    gme.write_tool(_tool())
    assert not list(_gme_in_tmp.glob("*.tmp"))


def test_write_twice_does_not_duplicate(_gme_in_tmp):
    gme.write_tool(_tool(version="1.0"))
    gme.write_tool(_tool(version="2.0"))
    assert len(list(_gme_in_tmp.glob("*.json"))) == 1
    assert gme.read_tool("neuron")["version"] == "2.0"


def test_list_tools_reads_all_and_skips_junk(_gme_in_tmp):
    gme.write_tool(_tool("neuron"))
    gme.write_tool(_tool("neurag"))
    (_gme_in_tmp / "junk.json").write_text("[]", encoding="utf-8")
    assert {t["key"] for t in gme.list_tools()} == {"neuron", "neurag"}


def test_list_tools_empty_when_no_folder():
    assert gme.list_tools() == []


# --- Phase 2: status gates the lookups webgui relies on --------------------

def test_lookups_respect_status():
    gme.write_tool(_tool())
    assert gme.is_installed("neuron")
    assert gme.get_python("neuron").endswith("python")
    assert gme.get_venv("neuron") == "/opt/neuron/.venv"

    gme.mark_missing("neuron")
    assert not gme.is_installed("neuron")
    # the JSON survives, but nothing hands out the dead path any more
    assert gme.get_python("neuron") is None
    assert gme.get_venv("neuron") is None
    assert gme.read_tool("neuron")["status"] == "missing"
    assert gme.get_version("neuron") == "6.1.2"


_GONE = [{"key": "neuron", "label": "Neuron", "module": "no_such_module_xyz",
          "cli": "no_such_module_xyz.cli"}]      # catalogo con un modulo assente


def test_register_demotes_what_this_venv_no_longer_has(_gme_in_tmp, monkeypatch):
    """`register_installed` promuoveva soltanto: un tool sparito dal venv restava
    `installed` per sempre e il SessionStart hook continuava ad annunciarlo."""
    import sys as _sys
    gme.write_tool(_tool("neuron", venv=_sys.prefix, python=_sys.executable))
    monkeypatch.setattr("gray_matter.catalog.ENVIRONMENTS", _GONE)

    gme.register_installed()
    assert gme.read_tool("neuron")["status"] == "missing"


def test_register_leaves_a_peer_that_lives_in_its_own_venv_alone(_gme_in_tmp, monkeypatch):
    """Un peer standalone non e' importabile da QUI e non e' affar nostro:
    declassarlo spegnerebbe l'handshake di un'installazione sana."""
    gme.write_tool(_tool("neuron", venv="/opt/neuron/.venv"))
    monkeypatch.setattr("gray_matter.catalog.ENVIRONMENTS", _GONE)

    gme.register_installed()
    assert gme.read_tool("neuron")["status"] == "installed"


def test_mark_missing_on_unknown_key_is_noop():
    gme.mark_missing("ghost")                    # must not raise
    assert gme.read_tool("ghost") is None


def test_remove_tool():
    gme.write_tool(_tool())
    assert gme.remove_tool("neuron") is True
    assert gme.remove_tool("neuron") is False
    assert gme.read_tool("neuron") is None


# --- Phase 4: health merge -------------------------------------------------

def test_update_health_merges_and_stamps():
    gme.write_tool(_tool())
    gme.update_health("neuron", {"pid": 4321, "memory_mb": 91.5})
    h = gme.read_tool("neuron")["health"]
    assert h["pid"] == 4321 and h["memory_mb"] == 91.5
    assert h["cpu_percent"] is None              # untouched key preserved
    assert h["last_check"]                       # stamped

    gme.update_health("neuron", {"cpu_percent": 3.0})
    h = gme.read_tool("neuron")["health"]
    assert h["pid"] == 4321 and h["cpu_percent"] == 3.0   # merge, not replace


def test_update_health_on_unknown_key_is_noop():
    gme.update_health("ghost", {"pid": 1})       # must not raise
    assert gme.read_tool("ghost") is None


# --- Phase 3: migration detection -----------------------------------------

def test_detect_old_installs_reports_a_usable_python_when_co_installed():
    """The default install puts all three tools in ONE venv, which
    _VENV_CANDIDATES ({localappdata}/{key}/.venv) never finds. Rows used to come
    back with python='' and migrating them wrote a hollow entry that silenced the
    card for good."""
    import sys

    old = gme.detect_old_installs()
    assert old, "nothing detected — the trio should be importable in the test env"
    for d in old:
        # no dedicated venv exists (the fixture points LOCALAPPDATA at an empty
        # tmp dir), so every row must fall back to the interpreter that just
        # imported the module — never to ""
        assert d["python"] == sys.executable
        assert d["venv"] == sys.prefix

    assert gme.migrate_tool(old[0]["key"])["ok"]
    migrated = gme.read_tool(old[0]["key"])
    assert migrated["version"], "migration must not leave a blank version"
    assert gme.get_python(old[0]["key"]) == sys.executable


def test_migrate_unknown_tool_is_rejected():
    r = gme.migrate_tool("nope")
    assert r["ok"] is False and "not detected" in r["error"]


def test_webgui_migrate_survives_a_malformed_payload():
    from gray_matter import webgui
    r = webgui.Api().migrate("{not json")
    assert r["ok"] is False and "error" in r


def test_detect_old_installs_skips_already_registered(monkeypatch):
    monkeypatch.setattr(gme, "_find_venv_for", lambda key: f"/opt/{key}/.venv")
    monkeypatch.setattr(gme, "_find_python_for_venv",
                        lambda venv: f"{venv}/bin/python")
    before = {d["key"] for d in gme.detect_old_installs()}
    assert before, "nothing detected — fixture stubs are not being used"

    for key in before:
        gme.write_tool(_tool(key))
    assert gme.detect_old_installs() == []


def test_detect_old_installs_reoffers_a_tool_marked_missing(monkeypatch):
    """uninstall → mark_missing → tool reappears on disk (pip, peer installer,
    repair). It has to show up in the migration card again, otherwise
    mark_missing is a one-way door out of the whole migration UI."""
    monkeypatch.setattr(gme, "_find_venv_for", lambda key: f"/opt/{key}/.venv")
    monkeypatch.setattr(gme, "_find_python_for_venv",
                        lambda venv: f"{venv}/bin/python")
    gme.write_tool(_tool("gray-matter"))
    assert "gray-matter" not in {d["key"] for d in gme.detect_old_installs()}

    gme.mark_missing("gray-matter")
    assert "gray-matter" in {d["key"] for d in gme.detect_old_installs()}


# --- install wiring: the suite path must register the peers ----------------

def test_register_installed_covers_every_importable_tool():
    """The hole this closes: a full-suite install left only gray-matter in GME,
    because the peers' own GME blocks live in Install-Standalone and the suite
    installs them with a bare pip."""
    import sys

    keys = gme.register_installed(source="/src")
    assert set(keys) == {"gray-matter", "neuron", "neurag"}, keys

    for key in keys:
        t = gme.read_tool(key)
        assert t["status"] == "installed"
        assert t["python"] == sys.executable      # the interpreter that resolved it
        assert t["venv"] == sys.prefix
        assert t["version"], f"{key} registered without a version"
        assert t["source"] == "/src"
        assert gme.get_python(key) == sys.executable


def test_register_installed_skips_what_it_cannot_import(monkeypatch):
    """A peer in its own venv is not importable here — it must be left to its
    own installer, not claimed with the wrong Python."""
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda m: None if m == "neuron" else object())
    keys = gme.register_installed()
    assert "neuron" not in keys
    assert gme.read_tool("neuron") is None


def test_register_installed_is_idempotent(_gme_in_tmp):
    gme.register_installed()
    gme.register_installed()
    assert len(list(_gme_in_tmp.glob("*.json"))) == 3


def test_install_plan_registers_gme_after_the_manifest():
    from gray_matter import installer
    acts = installer.plan({"installed": ["neuron"], "gm_present": True,
                           "clients": ["cursor"]})
    names = [a["action"] for a in acts]
    assert "register_gme" in names
    assert names.index("register_gme") > names.index("write_manifest")


def test_executor_register_gme(_gme_in_tmp):
    from gray_matter import executor

    dry = executor._register_gme(dry_run=True)
    assert dry["ok"] and not _gme_in_tmp.exists()      # dry-run writes nothing

    res = executor._register_gme(dry_run=False)
    assert res["ok"] and set(res["keys"]) == {"gray-matter", "neuron", "neurag"}


# --- uninstall wiring ------------------------------------------------------

def test_uninstall_plan_unregisters_gme():
    acts = uninstaller.plan({}, data_paths={})
    entry = [a for a in acts if a["action"] == "unregister_gme"]
    assert entry == [{"action": "unregister_gme", "key": "gray-matter"}]
    # registry entry goes only after the code it points at
    assert acts.index(entry[0]) > acts.index({"action": "remove_code"})


def test_uninstall_marks_gme_missing_not_deleted(_gme_in_tmp):
    from gray_matter import executor
    gme.write_tool(_tool("gray-matter"))

    dry = executor._unregister_gme("gray-matter", dry_run=True)
    assert dry["ok"] and gme.is_installed("gray-matter")   # dry-run touches nothing

    res = executor._unregister_gme("gray-matter", dry_run=False)
    assert res["ok"] and res["detail"] == "marked missing"
    assert not gme.is_installed("gray-matter")
    assert (_gme_in_tmp / "gray-matter.json").exists()     # history kept

    again = executor._unregister_gme("never-installed", dry_run=False)
    assert again["ok"] and again["detail"] == "not registered"


def test_written_json_is_utf8_and_reloadable(_gme_in_tmp):
    gme.write_tool(_tool("neurag", label="NeuRAG — cartellá"))
    raw = json.loads((_gme_in_tmp / "neurag.json").read_text(encoding="utf-8"))
    assert raw["label"] == "NeuRAG — cartellá"


# --- cross-writer: PowerShell emits a BOM, install.sh does not -------------

def test_reads_json_written_with_utf8_bom(_gme_in_tmp):
    """Windows PowerShell 5.1 `Set-Content -Encoding UTF8` — what all three
    install.ps1 use — prepends EF BB BF. Read as plain utf-8 the BOM makes
    json.loads raise, read_tool swallows it and returns None, and the entire
    registry silently degrades to the find_spec() fallback on every Windows
    install. Verified against real installer output before this was fixed."""
    _gme_in_tmp.mkdir(parents=True, exist_ok=True)
    # written raw, so spell out `status` the way install.ps1 does — write_tool's
    # defaulting never runs on a file PowerShell produced
    payload = json.dumps(_tool("neuron", status="installed"), indent=2)
    (_gme_in_tmp / "neuron.json").write_text(payload, encoding="utf-8-sig")

    assert (_gme_in_tmp / "neuron.json").read_bytes()[:3] == b"\xef\xbb\xbf"
    assert gme.read_tool("neuron")["version"] == "6.1.2"
    assert [t["key"] for t in gme.list_tools()] == ["neuron"]
    assert gme.is_installed("neuron")


def test_python_for_tool_ignores_a_tool_marked_missing(_gme_in_tmp, tmp_path):
    """webgui routes each tool to its own venv; after uninstall marks the entry
    *missing* it must fall back, not exec a python that is gone."""
    from gray_matter import webgui

    fake_py = tmp_path / "venv" / "python.exe"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("", encoding="utf-8")     # must EXIST, contents irrelevant
    gme.write_tool(_tool("neuron", python=str(fake_py)))

    assert webgui._python_for_tool("neuron") == str(fake_py)

    gme.mark_missing("neuron")
    assert webgui._python_for_tool("neuron") == webgui._python()


def test_python_for_tool_falls_back_when_venv_vanished():
    gme.write_tool(_tool("neuron", python="/gone/bin/python"))
    from gray_matter import webgui
    assert webgui._python_for_tool("neuron") == webgui._python()
