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
