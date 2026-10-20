"""One cached pyturso connection, many threads: must not crash the process.

pyturso 0.8.3 panics (wal.rs:3590) when two threads are inside one connection at
once, and a Rust panic takes the process down — on 2026-10-18 parallel
knowledge_ingest calls killed the NeuRAG worker. The load runs in a subprocess:
a panic there would kill pytest itself.
"""
import subprocess
import sys
import textwrap

import pytest

from neurag.db import TURSO_AVAILABLE

pytestmark = pytest.mark.skipif(not TURSO_AVAILABLE, reason="pyturso not installed")


def test_threads_sharing_the_cached_connection_do_not_crash(tmp_path):
    script = textwrap.dedent(f"""
        import threading
        from neurag import db
        conn = db._turso_open(r"{tmp_path / 'shared.db'}")
        conn.execute("CREATE TABLE t (k TEXT, i INTEGER)")
        conn.commit()

        def work(k):
            for i in range(200):
                conn.execute("INSERT INTO t VALUES (?, ?)", (k, i))
                conn.commit()
                conn.execute("SELECT count(*) FROM t").fetchone()

        ts = [threading.Thread(target=work, args=(str(n),)) for n in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        print("ROWS", conn.execute("SELECT count(*) FROM t").fetchone()[0])
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    ctx = f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr[-400:]!r}"
    assert r.returncode == 0 and "panicked" not in r.stderr, ctx
    assert "ROWS 800" in r.stdout, ctx


def test_parallel_transactions_do_not_mix(tmp_path):
    """One connection has ONE transaction. Two ingests in parallel used to write
    into the same one: one's rollback erased the other's rows, with no error
    (2026-10-20: 217, 35, 82, 118 rows where 50 each were due). Each job here
    replaces its own 50 rows and rolls back now and then, like an ingest that
    fails half-way; every job must end with exactly its 50."""
    script = textwrap.dedent(f"""
        import random, threading
        from neurag import db
        conn = db._turso_open(r"{tmp_path / 'tx.db'}")
        conn.execute("CREATE TABLE t (k TEXT, i INTEGER)")
        conn.commit()

        def job(k):
            rnd = random.Random(k)
            for _ in range(20):
                try:
                    conn.execute("DELETE FROM t WHERE k = ?", (k,))
                    for i in range(50):
                        conn.execute("INSERT INTO t VALUES (?, ?)", (k, i))
                    if rnd.random() < 0.2:
                        raise RuntimeError("half-way failure")
                    conn.commit()
                except RuntimeError:
                    conn.rollback()

        ts = [threading.Thread(target=job, args=(f"j{{n}}",)) for n in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        rows = conn.execute("SELECT k, count(*) FROM t GROUP BY k ORDER BY k").fetchall()
        print("ROWS", [tuple(r) for r in rows])
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    ctx = f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr[-400:]!r}"
    assert r.returncode == 0 and "panicked" not in r.stderr, ctx
    assert "ROWS [('j0', 50), ('j1', 50), ('j2', 50), ('j3', 50)]" in r.stdout, ctx
