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
    assert p.manifest_path() == p.gm_home() / "manifest.json"
    assert p.gm_state() == p.gm_home() / "state.db"


def test_data_paths_present(tmp_path):
    p = _reload_with_home(tmp_path)
    d = p.data_paths()
    # neurag_config is in here now: the GUI panel listed it as removable while
    # the plan, which reads THIS, never saw it — so it could be ticked and
    # nothing happened.
    assert set(d) == {"neuron_graphs", "gm_bridges", "neurag_db", "neurag_config"}


def test_gm_venv_comes_from_the_manifest(tmp_path):
    """The venv location is recorded, not guessed — an install made at the old
    `<base>/gray-matter/.venv` must still be findable by a current uninstall."""
    p = _reload_with_home(tmp_path)
    old = tmp_path / "gray-matter" / ".venv"
    old.mkdir(parents=True)
    m = p.Manifest()
    m.data["venv"] = str(old)
    m.record_component("neuron", present=True)
    m.record_component("gray_matter", present=True)
    m.save()
    assert p.gm_venv() == old
    assert p.venv_peers() == ["neuron"]      # gray_matter itself is not a peer


def test_manifest_round_trip(tmp_path):
    p = _reload_with_home(tmp_path)
    m = p.Manifest()
    m.record_component("gray_matter", version="1.0", home=str(p.gm_home()))
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
