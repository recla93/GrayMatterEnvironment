"""Purge dei mock cross-repo (audit 2026-07-20, FAILURE 1).

Neuron/tests/_mockdeps.py inietta moduli fake (mcp*, fastembed, turso=None) in
sys.modules a module-level. In una run pytest unica sui 3 repo i fake
sopravvivono ai test Neuron e rompono gli import REALI qui. Questa fixture è
session-scoped e autouse ma — essendo definita in QUESTO conftest — si attiva
solo quando parte il primo test di questo package, cioè DOPO i test Neuron:
rimuove i fake (riconoscibili: niente __file__ né __spec__) così l'import
successivo risolve i pacchetti veri.
"""
import sys

import pytest


def _purge_fake_modules() -> None:
    for name in list(sys.modules):
        if name == "turso" and sys.modules[name] is None:
            del sys.modules[name]
            continue
        if name == "fastembed" or name == "mcp" or name.startswith("mcp."):
            m = sys.modules[name]
            if m is not None and getattr(m, "__file__", None) is None \
                    and getattr(m, "__spec__", None) is None:
                del sys.modules[name]


@pytest.fixture(scope="session", autouse=True)
def _clean_mockdeps_pollution():
    _purge_fake_modules()
    yield


@pytest.fixture(autouse=True)
def _no_real_home(tmp_path_factory, monkeypatch):
    """No test sees the user's real folders. On 2026-11-23 the suite default
    moved to %USERPROFILE%, and tests that isolated only LOCALAPPDATA wrote fake
    values into the real neuron/.env and registry/neuron.json. Same fixture in
    the three suites' conftest.py; a test that needs a folder sets its own."""
    d = tmp_path_factory.mktemp("home")
    for k, v in {"USERPROFILE": d, "HOME": d, "LOCALAPPDATA": d / "AppData" / "Local",
                 "APPDATA": d / "AppData" / "Roaming", "XDG_DATA_HOME": d / ".local" / "share"}.items():
        monkeypatch.setenv(k, str(v))
    for k in ("GM_HOME", "NEURAG_HOME"):
        monkeypatch.delenv(k, raising=False)
    # The Desktop comes from the registry, not from an env var: every
    # execute_uninstall in test_executor.py deleted the REAL
    # "D:\Desktop\Gray Matter.lnk" (seen 2026-11-23: present before the suite,
    # gone after it; a user found the shortcut missing after an install).
    from gray_matter import shortcut
    monkeypatch.setattr(shortcut, "_windows_desktop", lambda: str(d / "Desktop"))
