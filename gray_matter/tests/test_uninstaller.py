"""Uninstaller brain + legacy scan (INSTALLER-UX §6). Pure, stdlib-only."""
from gray_matter import uninstaller as U

_MANIFEST = {
    "clients": ["cursor", "claude-code", "cursor"],
    "hooks": {"claude-code": ["hooks/sessionstart.py"]},
}
_DATA = {"neuron_graphs": "/x/graphs", "gm_bridges": "/x/bridges.json"}


def _acts(plan):
    return [a["action"] for a in plan]


def test_interactive_data_by_default():
    plan = U.plan(_MANIFEST, data_paths=_DATA)
    data = [a for a in plan if a["action"] in ("ask_data", "remove_data")]
    assert data and all(a["action"] == "ask_data" for a in data)   # never wiped silently


def test_purge_downgrades_to_remove():
    plan = U.plan(_MANIFEST, data_paths=_DATA, purge_data=True)
    assert all(a["action"] == "remove_data"
               for a in plan if a["name"] in _DATA) if False else True
    data = [a for a in plan if a.get("name") in _DATA]
    assert data and all(a["action"] == "remove_data" for a in data)


def test_order_and_dedup():
    plan = U.plan(_MANIFEST, data_paths=_DATA, orphan_pids=[9])
    assert _acts(plan)[:3] == ["reap", "deregister", "remove_hook"]
    dereg = [a for a in plan if a["action"] == "deregister"][0]
    assert dereg["clients"] == ["claude-code", "cursor"]           # sorted+deduped
    assert {"action": "remove_code"} in plan


def test_no_orphans_no_reap():
    plan = U.plan(_MANIFEST, data_paths=_DATA)
    assert "reap" not in _acts(plan)


def test_legacy_scan_covers_old_name_and_slug():
    kinds = {t["kind"] for t in U.legacy_scan_plan()}
    assert {"old_slug", "old_name", "path_scripts", "stale_client", "orphan_procs"} <= kinds


# --- venvs from previous installs -----------------------------------

def test_leftover_venvs_are_offered_too():
    """The manifest knows ONE venv, so uninstall never named the others and
    never removed them: they sat on disk forever, hundreds of MB no command ever
    touched. They now get the same treatment — we ASK, never assume — but with
    no peers, because nothing runs from them any more: that is exactly what
    makes them leftovers."""
    plan = U.plan(_MANIFEST, data_paths=_DATA, venv="/x/graymatter/.venv",
                  venv_peers=["neuron"],
                  legacy_venvs=["/old/graymatter/.venv", "/old/gray-matter/.venv"])
    venvs = [a for a in plan if a["action"] == "ask_venv"]
    assert [a["path"] for a in venvs] == [
        "/x/graymatter/.venv", "/old/graymatter/.venv", "/old/gray-matter/.venv"]
    assert venvs[0]["peers"] == ["neuron"] and not venvs[0].get("legacy")
    assert all(a["legacy"] and a["peers"] == [] for a in venvs[1:])


def test_the_active_venv_is_never_offered_twice():
    """If a "legacy" location is the one in use, asking twice means answering
    twice for the same folder."""
    plan = U.plan(_MANIFEST, data_paths=_DATA, venv="/x/.venv",
                  legacy_venvs=["/x/.venv"])
    assert len([a for a in plan if a["action"] == "ask_venv"]) == 1


def test_leftovers_alone_still_get_asked():
    """A half-uninstalled GM (a manifest with no venv) left the leftovers
    invisible: no row, no question, nothing."""
    plan = U.plan(_MANIFEST, data_paths=_DATA, venv=None,
                  legacy_venvs=["/old/gray-matter/.venv"])
    assert [a["path"] for a in plan if a["action"] == "ask_venv"] == ["/old/gray-matter/.venv"]


def test_paths_finds_the_previous_locations_and_skips_the_active_one(tmp_path, monkeypatch):
    from gray_matter import paths as P

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    active = tmp_path / "GrayMatterEnvironment" / "graymatter" / ".venv"
    for p in (active, tmp_path / "graymatter" / ".venv", tmp_path / "gray-matter" / ".venv"):
        p.mkdir(parents=True)
    monkeypatch.setattr(P, "gm_venv", lambda: active)

    found = [str(p) for p in P.legacy_venvs()]
    assert found == [str(tmp_path / "graymatter" / ".venv"),
                     str(tmp_path / "gray-matter" / ".venv")]
    assert str(active) not in found, "it would offer to delete the venv in use twice"
