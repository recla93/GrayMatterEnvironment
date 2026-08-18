"""Tier dello store bridge (cloud -> Turso locale -> sqlite3) e trasferimento.

Il cloud è simulato con un secondo file locale: quello che può sbagliare è la
logica di MERGE, non il transport libSQL (coperto da test_cloud_setup.py).
"""
import importlib
import sqlite3

import pytest


@pytest.fixture
def B(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "local.db"))
    monkeypatch.delenv("GM_TURSO_DATABASE_URL", raising=False)
    from gray_matter import bridges
    importlib.reload(bridges)

    def fake_cloud():
        c = bridges._open_local_turso(str(tmp_path / "cloud.db"))
        if c is not None:
            c.row_factory = bridges._local_row_factory
        else:
            c = sqlite3.connect(str(tmp_path / "cloud.db"))
            c.row_factory = sqlite3.Row
        c.execute(bridges._SCHEMA)
        c.commit()
        return c

    monkeypatch.setattr(bridges, "_open_cloud", fake_cloud)
    bridges._fake_cloud = fake_cloud
    return bridges


def test_local_tier_is_turso_when_available(B):
    # coerenza con Neuron/NeuRAG: stesso motore, non sqlite3 quando c'è pyturso
    assert B.ENGINE_NAME == ("Turso (local)" if B.LOCAL_TURSO_ENGINE else "SQLite")


def test_rows_are_name_accessible_on_every_tier(B):
    B.add_bridge("jvm bytecode", "Java/JVM", "r")
    row = B.all_bridges()[0]
    assert row["neuron"] == "jvm bytecode"      # dict(_Row) / sqlite3.Row
    assert B.bridges_for("about jvm bytecode")  # recall vivo sul tier attivo


def test_transfer_merges_instead_of_duplicating(B):
    B.add_bridge("jvm bytecode", "Java/JVM", "r")
    B.add_bridge("kotlin coroutines", "Kotlin/Async", "r")
    B.add_bridge("jvm bytecode", "Java/JVM", "r")        # weight 2

    assert B.transfer("to-cloud", dry_run=True)["written"] == 0   # dry-run non scrive
    first = B.transfer("to-cloud")
    assert (first["written"], first["merged"]) == (2, 0)

    again = B.transfer("to-cloud")                        # idempotente
    assert (again["written"], again["merged"]) == (0, 2)

    cl = B._fake_cloud()
    rows = {(r["neuron"], r["neurag"]): r["weight"]
            for r in cl.execute("SELECT * FROM bridges").fetchall()}
    cl.close()
    assert len(rows) == 2
    assert rows[("jvm bytecode", "Java/JVM")] == 2.0      # vince il weight più alto

    B.transfer("from-cloud")                              # ritorno non degrada
    assert {(r["neuron"], r["neurag"]): r["weight"] for r in B.all_bridges()} == rows


def test_transfer_rejects_bad_direction(B):
    with pytest.raises(ValueError):
        B.transfer("sideways")
