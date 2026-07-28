"""Il registro dei tool non deve mai finire nella cwd del processo di turno."""

import os
import sys

import pytest

from gray_matter import gme


@pytest.mark.parametrize("var", ["LOCALAPPDATA", "XDG_DATA_HOME", "HOME"])
def test_gme_root_is_absolute_even_with_a_stripped_environment(monkeypatch, var):
    """Il bug: con LOCALAPPDATA/XDG_DATA_HOME vuoti, `Path("") / "GrayMatter‑
    Environment"` è un path RELATIVO — il registro veniva scritto dove capitava
    di trovarsi. Non è teorico: la cartella `GrayMatterEnvironment/` comparsa
    nella root del workspace è stata scritta così, da una suite di test che
    fa `monkeypatch.delenv("LOCALAPPDATA")`.

    Env ripulito capita davvero: servizi Windows, scheduled task, `sudo -i`.
    """
    monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("USERPROFILE", os.path.expanduser("~"))  # fallback Win

    root = gme.gme_root()
    assert root.is_absolute(), f"gme_root() relativo senza {var}: {root}"
    assert root.name == "GrayMatterEnvironment"


def test_gme_root_prefers_the_platform_location(monkeypatch, tmp_path):
    """Il fallback non deve rubare la precedenza alla posizione di piattaforma."""
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    elif sys.platform != "darwin":
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    else:
        pytest.skip("macOS ancora la posizione a ~/Library, niente env var")

    assert gme.gme_root() == tmp_path / "GrayMatterEnvironment"


def test_reading_the_registry_creates_nothing(monkeypatch, tmp_path):
    """Una lettura non deve materializzare la cartella: era il modo in cui i
    `GrayMatterEnvironment/` fantasma si moltiplicavano."""
    monkeypatch.setattr(gme, "gme_root", lambda: tmp_path / "gme")
    gme.read_tool("neuron")
    assert not (tmp_path / "gme").exists()
