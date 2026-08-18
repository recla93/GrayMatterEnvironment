"""The clients panel is the error register — so it must not cry wolf.

It reported "points at a DIFFERENT install" for every correctly registered
client, on every machine, always. Not a real mismatch: the control center is
launched by the desktop shortcut and therefore runs under `pythonw.exe`, while
registration writes `sys.executable` from a console run, `python.exe`. Same
venv, same install, different launcher.

An alarm that is always on is worse than no alarm: it teaches you to ignore the
one time it means something.
"""
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from gray_matter.webgui import _same_interpreter  # noqa: E402

VENV = r"C:\Users\x\AppData\Local\gray-matter\.venv\Scripts"


def test_pythonw_is_the_same_install_as_python():
    assert _same_interpreter(VENV + r"\python.exe", VENV + r"\pythonw.exe")
    assert _same_interpreter(VENV + r"\pythonw.exe", VENV + r"\python.exe")


def test_a_genuinely_different_venv_is_still_reported():
    """The check has to keep working: this is the case it exists for — a config
    left pointing at an install that was moved or replaced."""
    other = r"C:\Users\x\AppData\Local\neuron\.venv\Scripts\python.exe"
    assert not _same_interpreter(VENV + r"\python.exe", other)


def test_case_and_separators_do_not_matter_on_windows():
    assert _same_interpreter(VENV + r"\python.exe", VENV.upper() + r"\PYTHON.EXE")
    assert _same_interpreter(VENV + r"\python.exe", VENV + "/python.exe")


def test_a_missing_path_does_not_match_everything():
    assert not _same_interpreter("", VENV + r"\python.exe")


@pytest.mark.skipif(os.name != "nt", reason="pythonw is Windows-only")
def test_the_real_pair_this_was_reported_for():
    """Regression on the exact shapes seen on the user's machine."""
    reg = r"C:\Users\recla\AppData\Local\gray-matter\.venv\Scripts\python.exe"
    gui = r"C:\Users\recla\AppData\Local\gray-matter\.venv\Scripts\pythonw.exe"
    assert _same_interpreter(reg, gui)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------------------
# The assets have to be IN the package, not just in the repo
# ---------------------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[2]

# What reads them, and from where. Both resolve inside the INSTALLED package.
ASSETS = {
    "assets/GM.png": "webgui.py serves it at /logo.png (the header logo)",
    "assets/gray-matter.ico": "shortcut._resolve_icon() gives the desktop shortcut its icon",
}


@pytest.mark.parametrize("rel", ASSETS)
def test_the_asset_exists_in_the_repo(rel):
    assert (ROOT / "gray_matter" / rel).is_file(), ASSETS[rel]


@pytest.mark.parametrize("rel", ASSETS)
def test_the_asset_is_declared_as_package_data(rel):
    """It was not, and that one omission caused both reported symptoms: the
    control center never showed its logo and the desktop shortcut never had its
    icon, because on an installed copy `<package>/assets/` did not exist.

    `include-package-data = true` does not catch these on a flat layout without
    a MANIFEST.in, so the glob has to be explicit."""
    toml = (ROOT / "gray_matter" / "pyproject.toml").read_text(encoding="utf-8")
    block = toml.split("[tool.setuptools.package-data]", 1)[1].split("[", 1)[0]
    assert "assets/*" in block or rel in block, (
        f"{rel} would not ship — {ASSETS[rel]}")


def test_the_reader_and_the_shipped_path_agree():
    """Both consumers build the path the same way; if one moves, this fails."""
    web = (ROOT / "gray_matter" / "webgui.py").read_text(encoding="utf-8")
    sc = (ROOT / "gray_matter" / "shortcut.py").read_text(encoding="utf-8")
    assert '"assets") / "GM.png"' in web or "'assets') / 'GM.png'" in web
    assert '"assets" / "gray-matter.ico"' in sc


# ---------------------------------------------------------------------------
# A shortcut already on disk has to pick up the icon it never got
# ---------------------------------------------------------------------------

def test_the_shortcut_marker_records_the_recipe_not_just_a_flag(monkeypatch, tmp_path):
    """`ensure_shortcut` short-circuited on "marker exists AND file exists", so
    a shortcut built while the .ico was missing from the package kept the bare
    interpreter icon forever. Shipping the asset fixes new installs; this is
    what fixes the ones already out there."""
    from gray_matter import shortcut as sc

    calls = {"built": 0}
    monkeypatch.setattr(sc, "_resolve_icon", lambda: r"C:\x\gray-matter.ico")
    monkeypatch.setattr(sc, "_shortcut_file_exists", lambda label: True)
    monkeypatch.setattr(sc.os, "name", "nt")
    monkeypatch.setattr(sc, "_windows_lnk",
                        lambda *a, **k: calls.__setitem__("built", calls["built"] + 1) or True)
    fake_exe = tmp_path / "python.exe"
    fake_exe.write_text("")
    monkeypatch.setattr(sc.sys, "executable", str(fake_exe))
    marker = tmp_path / ".gray-matter-gui-shortcut"

    marker.write_text("1", encoding="utf-8")        # il vecchio formato
    sc.ensure_desktop_shortcut("gray-matter", "Gray Matter", ["-m", "gray_matter.cli", "gui"])
    assert calls["built"] == 1, "un collegamento senza icona non è stato ricostruito"
    assert marker.read_text(encoding="utf-8").strip() == "icon=True"

    sc.ensure_desktop_shortcut("gray-matter", "Gray Matter", ["-m", "gray_matter.cli", "gui"])
    assert calls["built"] == 1, "ricostruito di nuovo: non è più idempotente"


# --- il registro degli errori non deve morire sull'errore che deve mostrare ---
# Segnalato dal campo come "i client danno errori di path in GUI": UN config con
# `command` in una forma inattesa (dict, lista vuota, numero) faceva alzare a
# os.path.exists()
#   TypeError: path should be string, bytes, os.PathLike or integer, not dict
# che usciva da clients_state e portava via il PANNELLO INTERO — quindi anche i
# client sani diventavano invisibili. I sei config non li scriviamo solo noi:
# l'utente li edita a mano e i client cambiano schema, quindi la forma di
# `command` e' input non fidato, non un invariante.
from gray_matter.webgui import _as_command_path  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    (r"C:\py\python.exe", r"C:\py\python.exe"),              # stringa: la forma normale
    ([r"C:\py\python.exe", "-m", "x"], r"C:\py\python.exe"),  # argv: primo elemento
    ([], None),                                             # lista vuota: niente IndexError
    ([None, "python"], "python"),                           # primo utile, non il primo
    ({"exe": "python"}, None),                              # dict: illeggibile, non esplode
    (42, None),                                             # numero: idem
    (None, None),                                           # assente
    ("", None),                                             # stringa vuota != path valido
])
def test_command_shapes_never_reach_os_path(raw, expected):
    assert _as_command_path(raw) == expected


def test_every_shape_is_safe_for_os_path_exists():
    """La garanzia che conta: qualunque cosa esca di qui si puo' dare a
    os.path.exists() senza TypeError."""
    for raw in ("x", ["x"], [], {}, 42, None, "", [None], ({"a": 1},)):
        got = _as_command_path(raw)
        assert got is None or isinstance(got, str)
        os.path.exists(got or "")      # non deve alzare
