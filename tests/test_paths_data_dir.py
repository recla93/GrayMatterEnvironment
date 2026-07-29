"""Where the vault lives.

NeuRAG wrote to `~/.local/share/neurag` on every OS, including Windows — a
POSIX path outside %LOCALAPPDATA%, where Neuron and Gray Matter keep their data
and where GM's own fallback already looked. Aligning the rule must never strand
an existing knowledge.db, so "the vault that exists wins" is the load-bearing
part of this, not the new default.
"""

import os
from pathlib import Path

import pytest

from neurag import paths


@pytest.fixture
def clean(monkeypatch, tmp_path):
    monkeypatch.delenv("NEURAG_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    return tmp_path


def test_env_override_always_wins(clean, monkeypatch, tmp_path):
    monkeypatch.setenv("NEURAG_HOME", str(tmp_path / "custom"))
    assert paths.data_dir() == tmp_path / "custom"


def test_clean_machine_uses_the_per_os_base(clean, tmp_path):
    """Nothing on disk yet → the new, per-OS location."""
    expected = (tmp_path / "AppData" / "Local" if os.name == "nt" else tmp_path / "xdg") / "neurag"
    assert paths.data_dir() == expected


def test_an_existing_legacy_vault_is_never_abandoned(clean, tmp_path):
    """The regression that would have cost a user their knowledge base."""
    legacy = tmp_path / "home" / ".local" / "share" / "neurag"
    legacy.mkdir(parents=True)
    (legacy / "knowledge.db").write_text("vault", encoding="utf-8")

    assert paths.data_dir() == legacy
    assert paths.db_path().read_text(encoding="utf-8") == "vault"


def test_the_new_location_wins_once_it_exists(clean, tmp_path):
    """Both present → the per-OS one, so a migrated install stops looking back."""
    legacy = tmp_path / "home" / ".local" / "share" / "neurag"
    legacy.mkdir(parents=True)
    current = (tmp_path / "AppData" / "Local" if os.name == "nt" else tmp_path / "xdg") / "neurag"
    current.mkdir(parents=True)

    assert paths.data_dir() == current


def test_posix_default_is_unchanged_by_the_realignment(clean, monkeypatch, tmp_path):
    """On Linux/macOS without XDG the new rule resolves to the historic path —
    the realignment is a Windows-only behaviour change."""
    if os.name == "nt":
        pytest.skip("POSIX default; on Windows the base is LOCALAPPDATA by design")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert paths.data_dir() == paths.legacy_data_dir()


def test_gray_matter_fallback_agrees_when_neurag_is_not_importable(clean, tmp_path):
    """GM guesses the vault only when it cannot import NeuRAG. The guess used to
    be the bare per-OS path, so on Windows it missed a legacy vault entirely."""
    gp = pytest.importorskip("gray_matter.paths")
    legacy = tmp_path / "home" / ".local" / "share" / "neurag"
    legacy.mkdir(parents=True)

    assert gp._neurag_dir_fallback() == paths.data_dir()
