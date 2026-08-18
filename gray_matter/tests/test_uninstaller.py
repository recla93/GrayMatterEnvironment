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
