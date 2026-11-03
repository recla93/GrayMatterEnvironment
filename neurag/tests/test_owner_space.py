"""Every node says which space it belongs to (ADR-013, phase 4a).

Chunks inherit their node's space, so the column lives on nodes only. A local
vault is one user's by construction; a shared one is not, and its older nodes
must not get an invented owner.
"""
import pathlib
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import neurag.db as neurag_db
from neurag.db import KnowledgeGraph


@pytest.fixture
def ada(monkeypatch):
    for var in ("NEURAG_USER", "NEURAG_SPACE", "NEURON_SPACE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NEURON_USER", "ada")     # one name for the whole suite
    monkeypatch.setattr(neurag_db, "REMOTE_TURSO", False)


def _spaces(path):
    """name -> space, without the root '/' every vault seeds for itself."""
    with sqlite3.connect(path) as c:
        return dict(c.execute("SELECT name, space FROM nodes WHERE name != '/'").fetchall())


def _legacy(path):
    """A vault from before 4a: same nodes, no space column. The connection
    cache is cleared first — an upgrade always runs in a fresh process."""
    neurag_db._turso_conn_cache.clear()
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE nodes DROP COLUMN space")
    raw.commit()
    raw.close()


def test_a_new_node_carries_the_space(tmp_path, ada):
    db = tmp_path / "v.db"
    kg = KnowledgeGraph(db)
    kg.add_node("Proxy", "fundamental", parent_id=0)
    kg.close()
    assert _spaces(db) == {"Proxy": "personale:ada"}


def test_neurag_user_wins_over_neuron_user(monkeypatch, ada):
    monkeypatch.setenv("NEURAG_USER", "bruno")
    assert neurag_db.vault_space() == "personale:bruno"


def test_a_local_legacy_vault_becomes_its_users(tmp_path, ada):
    db = tmp_path / "v.db"
    kg = KnowledgeGraph(db)
    kg.add_node("Proxy", "fundamental", parent_id=0)
    kg.close()
    _legacy(db)
    kg = KnowledgeGraph(db)                       # the migration runs on open
    assert not kg._corrupt, kg._corrupt_err
    kg.close()
    assert _spaces(db) == {"Proxy": "personale:ada"}


def test_a_shared_vault_keeps_old_nodes_unattributed(tmp_path, ada, monkeypatch):
    db = tmp_path / "v.db"
    kg = KnowledgeGraph(db)
    kg.add_node("Proxy", "fundamental", parent_id=0)
    kg.close()
    _legacy(db)
    monkeypatch.setattr(neurag_db, "REMOTE_TURSO", True)   # the team's shared DB
    with sqlite3.connect(db) as raw:
        KnowledgeGraph._ensure_columns(SimpleNamespace(_conn=raw))
    assert _spaces(db) == {"Proxy": ""}


def test_the_space_follows_the_vault(monkeypatch, ada):
    assert neurag_db.vault_space() == "personale:ada"
    monkeypatch.setattr(neurag_db, "REMOTE_TURSO", True)
    assert neurag_db.vault_space() == "team:shared"
    monkeypatch.setenv("NEURAG_SPACE", "team:backend")
    assert neurag_db.vault_space() == "team:backend"
