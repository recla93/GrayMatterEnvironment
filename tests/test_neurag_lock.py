"""pyturso connection cache tests.

pyturso 0.6.1 on Windows does NOT release the OS file lock on conn.close().
A second process CANNOT open the same file at all. These tests verify:
  1. Module cache prevents multiple pyturso connections to the same file
  2. Cross-process access fails cleanly (confirms exclusive lock behavior)
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from neurag import db as neurag_db
from neurag.db import KnowledgeGraph, TURSO_AVAILABLE


pytestmark = pytest.mark.skipif(
    not TURSO_AVAILABLE,
    reason="pyturso not installed — cache tests irrelevant"
)


def test_cache_prevents_duplicate_connections(tmp_path):
    """Two KnowledgeGraph instances on the same path share one pyturso connection
    via _turso_conn_cache — the second open reuses the cached handle."""
    path = tmp_path / "k.db"
    kg1 = KnowledgeGraph(db_path=path)
    kg2 = KnowledgeGraph(db_path=path)
    assert kg1._engine_name == "Turso (local)"
    assert kg2._engine_name == "Turso (local)"
    conn1 = neurag_db._turso_conn_cache.get(str(path))
    assert conn1 is not None, "cache must have the connection"
    conn1.execute("SELECT 1")


def test_second_process_cannot_open_locked_file(tmp_path):
    """Process A holds pyturso lock, process B gets 'Turso (pending)' for same file.

    Confirms pyturso on Windows uses an exclusive lock — cross-process concurrent
    access is impossible. This is why GM routes writes through _run_via_gm and
    reads go through the GM server's cached connection."""
    path = tmp_path / "lock_test.db"
    script_a = textwrap.dedent(
        "import time\n"
        "from pathlib import Path\n"
        "from neurag.db import KnowledgeGraph\n"
        "kg = KnowledgeGraph(db_path=Path(r'%s'))\n"
        "print('READY', flush=True)\n"
        "time.sleep(3)\n"
        "kg.close()\n"
    ) % str(path)
    script_b = textwrap.dedent(
        "import time\n"
        "from pathlib import Path\n"
        "from neurag.db import KnowledgeGraph\n"
        "time.sleep(1)\n"
        "kg = KnowledgeGraph(db_path=Path(r'%s'))\n"
        "print('ENGINE', kg._engine_name, flush=True)\n"
    ) % str(path)
    a = subprocess.Popen([sys.executable, "-c", script_a], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    b = subprocess.run([sys.executable, "-c", script_b], capture_output=True, text=True,
                       timeout=15)
    a_out = a.stdout.read()
    a.wait(timeout=10)
    assert "READY" in a_out, f"process A failed: {a.stderr.read()!r}"
    # B can't open the file held by A → "Turso (pending)" (connection failed)
    assert "Turso (pending)" in b.stdout, (
        f"expected 'Turso (pending)' when file is locked: stdout={b.stdout!r} stderr={b.stderr!r}"
    )
