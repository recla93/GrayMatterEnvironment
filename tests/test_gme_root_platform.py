"""One user-data root per OS — including the one we cannot run on.

macOS was the odd platform out: `gme_root()` resolved
`~/Library/Application Support/GrayMatterEnvironment` while every data location
in the suite (neuron/config.py, neuron/paths.py, neuron/project.py,
neuron/tunnel.py, neurag/paths.py, gray_matter/paths.py) resolved
`~/.local/share`. Two roots on one machine, and tunnel.json written into the
folder the registry was not in.

These tests fake `sys.platform`, so they actually exercise the macOS branch from
Windows or Linux — otherwise the fix is unverified until a Mac shows up.
"""

import importlib
from pathlib import Path

import pytest

from gray_matter import gme


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda p: p.replace("~", str(tmp_path), 1))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    return tmp_path


def test_macos_uses_the_same_root_as_every_data_location(home, monkeypatch):
    monkeypatch.setattr(gme.sys, "platform", "darwin")
    assert gme.gme_root() == home / ".local" / "share" / "GrayMatterEnvironment" / "registry"


def test_macos_keeps_reading_an_existing_library_registry(home, monkeypatch):
    """Aligning the rule must not make the GUI report 'no tools installed'."""
    monkeypatch.setattr(gme.sys, "platform", "darwin")
    legacy = home / "Library" / "Application Support" / "GrayMatterEnvironment" / "registry"
    legacy.mkdir(parents=True)
    (legacy / "neuron.json").write_text("{}", encoding="utf-8")

    assert gme.gme_root() == legacy


def test_macos_prefers_the_aligned_root_once_it_exists(home, monkeypatch):
    monkeypatch.setattr(gme.sys, "platform", "darwin")
    (home / "Library" / "Application Support" / "GrayMatterEnvironment" / "registry").mkdir(parents=True)
    aligned = home / ".local" / "share" / "GrayMatterEnvironment" / "registry"
    aligned.mkdir(parents=True)

    assert gme.gme_root() == aligned


def test_linux_is_untouched(home, monkeypatch):
    monkeypatch.setattr(gme.sys, "platform", "linux")
    assert gme.gme_root() == home / ".local" / "share" / "GrayMatterEnvironment" / "registry"


def test_windows_is_untouched(home, monkeypatch):
    monkeypatch.setattr(gme.sys, "platform", "win32")
    assert gme.gme_root() == home / "AppData" / "Local" / "GrayMatterEnvironment" / "registry"


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_root_is_absolute_even_with_a_scrubbed_env(home, monkeypatch, platform):
    """A set-but-EMPTY var made Path("") -> a relative root, and the registry
    landed in whatever cwd the process happened to have. Really happened."""
    monkeypatch.setattr(gme.sys, "platform", platform)
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setenv("XDG_DATA_HOME", "")

    assert gme.gme_root().is_absolute()


def test_find_venv_shares_the_one_resolver(home, monkeypatch):
    """`_find_venv_for` carried a second hand-rolled copy of the per-OS rule and
    drifted from gme_root() whenever either moved."""
    import inspect
    body = inspect.getsource(gme._find_venv_for)
    assert "Application Support" not in body, "the duplicated per-OS branch is back"
    assert "user_base()" in body
