"""Path SSOT + install manifest (INSTALLER-UX §3–4). Stdlib-only, no server import."""
import importlib
import os

from gray_matter import paths as P


def _reload_with_home(tmp_path):
    os.environ["GM_HOME"] = str(tmp_path)
    return importlib.reload(P)


def test_gm_home_honors_override(tmp_path):
    p = _reload_with_home(tmp_path)
    assert str(p.gm_home()).startswith(str(tmp_path))
    assert p.app_dir() == p.gm_home() / "app"
    assert p.manifest_path() == p.gm_home() / "manifest.json"


def test_data_paths_present(tmp_path):
    p = _reload_with_home(tmp_path)
    d = p.data_paths()
    assert set(d) == {"neuron_graphs", "gm_bridges", "neurag_db"}


def test_manifest_round_trip(tmp_path):
    p = _reload_with_home(tmp_path)
    m = p.Manifest()
    m.record_component("gray_matter", version="1.0", app_dir=str(p.app_dir()))
    m.set_clients(["cursor", "claude-code", "cursor"])   # dedups
    m.record_hook("claude-code", "hooks/neuron_sessionstart_hook.py")
    m.save()
    again = p.Manifest.load()
    assert again.components()["gray_matter"]["version"] == "1.0"
    assert again.data["clients"] == ["claude-code", "cursor"]
    assert again.data["hooks"]["claude-code"] == ["hooks/neuron_sessionstart_hook.py"]


def test_manifest_remove_component(tmp_path):
    p = _reload_with_home(tmp_path)
    m = p.Manifest()
    m.record_component("neurag", db=str(p.neurag_db()))
    m.remove_component("neurag")
    assert "neurag" not in m.components()


def test_manifest_load_missing_is_empty(tmp_path):
    p = _reload_with_home(tmp_path)
    assert p.Manifest.load(tmp_path / "nope.json").components() == {}
