"""Purge dei mock cross-repo (audit 2026-07-20, FAILURE 1).

Copia deliberata di gray_matter/tests/conftest.py: i due repo non condividono
un import path nei test, e 15 righe duplicate battono un pacchetto condiviso.
Vedi quel file per il razionale completo (fake di Neuron/_mockdeps.py che
sopravvivono in sys.modules nella run pytest unica sui 3 repo).
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
def _clear_conn_cache():
    """Clear the module-level connection cache between tests.

    _turso_conn_cache is process-global and keyed by path string. Tests using
    ':memory:' share the same key, so without clearing the cache, later tests
    reuse the connection (and data) from earlier tests.
    """
    yield
    from neurag import db as neurag_db
    neurag_db._turso_conn_cache.clear()
