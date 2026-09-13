"""Backup giornaliero della suite: una cartella al giorno, tre sottocartelle.

La copia passa dalla backup API su una connessione `mode=ro`: è l'unico modo
sancito di aprire un grafo che un altro processo tiene bloccato. Un
`sqlite3.connect` normale, alla chiusura, cancella il WAL vivo e il worker
continua a scrivere su un file che non c'è più (2026-09-12: tre turni persi).
"""
import json
import sqlite3

import pytest

from gray_matter import backup, paths


@pytest.fixture
def suite(tmp_path, monkeypatch):
    graphs = tmp_path / "neuron" / "graphs"
    graphs.mkdir(parents=True)
    (tmp_path / "gm").mkdir()
    (tmp_path / "neurag").mkdir()
    monkeypatch.setattr(paths, "data_paths", lambda: {
        "neuron_graphs": graphs,
        "gm_bridges": tmp_path / "gm" / "bridges.db",
        "neurag_db": tmp_path / "neurag" / "knowledge.db",
        "neurag_config": tmp_path / "neurag" / "config.json",
    })
    monkeypatch.setattr(paths, "backups_dir", lambda: tmp_path / "backups")
    return tmp_path


def _db(path, rows):
    c = sqlite3.connect(path)
    c.execute("create table t(x)")
    c.executemany("insert into t values (?)", [(r,) for r in rows])
    c.commit()
    c.close()


def _count(path):
    c = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return c.execute("select count(*) from t").fetchone()[0]
    finally:
        c.close()


def test_one_folder_per_day_three_subfolders(suite):
    _db(suite / "neuron/graphs/graph_ai.db", range(5))
    _db(suite / "gm/bridges.db", range(2))
    (suite / "neurag/config.json").write_text('{"tier": "local"}', encoding="utf-8")
    # knowledge.db assente: si salta, non si fallisce

    folder, errors = backup.run(day="2026-09-13")

    assert errors == []
    assert folder == suite / "backups" / "gm-graph-backup_2026-09-13"
    assert _count(folder / "neuron" / "graph_ai.db") == 5
    assert _count(folder / "gray-matter" / "bridges.db") == 2
    assert json.loads((folder / "neurag" / "config.json").read_text(encoding="utf-8")) == {"tier": "local"}
    assert not (folder / "neurag" / "knowledge.db").exists()
    assert not folder.with_suffix(".tmp").exists(), "la cartella di lavoro viene rinominata"


def test_same_day_is_a_noop_unless_forced(suite):
    _db(suite / "gm/bridges.db", range(2))
    first, _ = backup.run(day="2026-09-13")
    assert backup.run(day="2026-09-13") == (None, [])
    _db(suite / "neuron/graphs/graph_new.db", range(3))
    again, _ = backup.run(day="2026-09-13", force=True)
    assert again == first
    assert _count(again / "neuron" / "graph_new.db") == 3, "--force rifà la copia di oggi"


def test_the_live_wal_survives_the_copy(suite):
    """Il caso del 2026-09-12: il worker tiene il grafo in WAL con scritture non
    ancora checkpointate. La copia deve contenerle E lasciare il WAL dov'è."""
    db = suite / "neuron/graphs/graph_ai.db"
    _db(db, range(5))
    writer = sqlite3.connect(db)
    writer.execute("pragma journal_mode=wal")
    writer.execute("insert into t values (99)")
    writer.commit()                      # nel WAL, non nel file principale
    wal = db.with_name(db.name + "-wal")
    assert wal.exists()

    folder, errors = backup.run(day="2026-09-13")

    assert errors == []
    assert wal.exists(), "un lettore passivo non cancella il WAL del worker"
    assert _count(folder / "neuron" / "graph_ai.db") == 6, "la copia ripiega il WAL"
    writer.execute("insert into t values (100)")
    writer.commit()                      # il worker continua a scrivere
    writer.close()
    assert _count(db) == 7


def test_keeps_the_newest_seven_days(suite):
    _db(suite / "gm/bridges.db", range(1))
    for d in range(1, 10):
        backup.run(day=f"2026-09-{d:02d}")
    days = sorted(p.name for p in (suite / "backups").iterdir())
    assert len(days) == backup.KEEP == 7
    assert days[0] == "gm-graph-backup_2026-09-03" and days[-1] == "gm-graph-backup_2026-09-09"


def test_a_broken_file_does_not_lose_the_others(suite):
    (suite / "gm/bridges.db").write_bytes(b"not a database at all, but long enough")
    _db(suite / "neuron/graphs/graph_ai.db", range(5))

    folder, errors = backup.run(day="2026-09-13")

    assert folder is not None and len(errors) == 1 and errors[0].startswith("gray-matter/bridges.db")
    assert _count(folder / "neuron" / "graph_ai.db") == 5


def test_keep_zero_disables_it(suite):
    assert backup.run(day="2026-09-13", keep=0) == (None, [])
    assert not (suite / "backups").exists()


# ---------- failsafe: una copia a metà non è mai una copia ----------

def test_a_run_killed_mid_copy_leaves_no_day_folder_and_the_next_run_recovers(suite):
    """Simula os._exit fra un file e l'altro: la cartella del giorno non esiste,
    resta solo `.tmp`; la corsa successiva la spazza e completa."""
    _db(suite / "gm/bridges.db", range(2))
    _db(suite / "neuron/graphs/graph_ai.db", range(5))
    real_copy, hits = backup._copy, []

    def dies_on_second(src, dst_dir):
        hits.append(src.name)
        if len(hits) == 2:
            raise SystemExit("killed")       # BaseException: scavalca il try per-file
        real_copy(src, dst_dir)

    backup._copy = dies_on_second
    try:
        with pytest.raises(SystemExit):
            backup.run(day="2026-09-13")
    finally:
        backup._copy = real_copy
    root = suite / "backups"
    assert not (root / "gm-graph-backup_2026-09-13").exists()
    assert (root / "gm-graph-backup_2026-09-13.tmp").exists()

    folder, errors = backup.run(day="2026-09-13")
    assert errors == []
    assert _count(folder / "neuron" / "graph_ai.db") == 5
    assert _count(folder / "gray-matter" / "bridges.db") == 2
    assert sorted(p.name for p in root.iterdir()) == ["gm-graph-backup_2026-09-13"]


def test_force_swaps_instead_of_deleting_first(suite):
    """--force non cancella la copia di oggi prima di avere quella nuova: la
    rinomina in `.old` e la butta solo a scambio avvenuto."""
    _db(suite / "gm/bridges.db", range(2))
    backup.run(day="2026-09-13")
    real_rename, seen = backup.Path.rename, []

    def spy(self, target):
        seen.append((self.name, backup.Path(target).name))
        return real_rename(self, target)

    backup.Path.rename = spy
    try:
        backup.run(day="2026-09-13", force=True)
    finally:
        backup.Path.rename = real_rename
    assert seen == [("gm-graph-backup_2026-09-13", "gm-graph-backup_2026-09-13.old"),
                    ("gm-graph-backup_2026-09-13.tmp", "gm-graph-backup_2026-09-13")]
    assert sorted(p.name for p in (suite / "backups").iterdir()) == ["gm-graph-backup_2026-09-13"]


def test_stale_leftovers_are_swept_and_never_counted_as_days(suite):
    _db(suite / "gm/bridges.db", range(1))
    root = suite / "backups"
    for junk in ("gm-graph-backup_2026-09-01.tmp", "gm-graph-backup_2026-09-02.old"):
        (root / junk).mkdir(parents=True)
    backup.run(day="2026-09-13")
    assert sorted(p.name for p in root.iterdir()) == ["gm-graph-backup_2026-09-13"]


def test_shutdown_waits_for_a_copy_in_flight(suite):
    """Il lock è tenuto per tutta la copia: wait_idle dice False finché dura,
    True appena finisce. È ciò che lo shutdown del daemon interroga."""
    import threading, time as _t
    _db(suite / "gm/bridges.db", range(1))
    real_copy, started = backup._copy, threading.Event()

    def slow(src, dst_dir):
        started.set()
        _t.sleep(0.3)
        real_copy(src, dst_dir)

    backup._copy = slow
    t = threading.Thread(target=backup.run, kwargs={"day": "2026-09-13"})
    try:
        t.start()
        assert started.wait(2)
        assert backup.wait_idle(timeout=0.05) is False, "copia in corso: non è idle"
        assert backup.wait_idle(timeout=5) is True, "finita: idle"
    finally:
        backup._copy = real_copy
        t.join()
    assert (suite / "backups" / "gm-graph-backup_2026-09-13" / "gray-matter" / "bridges.db").exists()
