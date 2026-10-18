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
