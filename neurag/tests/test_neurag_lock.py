"""pyturso connection cache tests.

pyturso 0.6.1 on Windows does NOT release the OS file lock on conn.close().
A second process CANNOT open the same file at all. These tests verify:
  1. Module cache prevents multiple pyturso connections to the same file
  2. Cross-process access fails cleanly (confirms exclusive lock behavior)
"""
import os
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


def test_second_process_degrades_to_sqlite_instead_of_having_no_connection(tmp_path):
    """Process A holds the pyturso lock; process B must still be able to READ.

    The lock is real — pyturso on Windows takes an exclusive one, which is why
    GM routes writes through `_run_via_gm`. What was wrong was the consequence:
    this test used to assert `Turso (pending)`, i.e. process B ending up with
    `_conn = None`, and called that the expected outcome. It was the symptom of
    a fallback that did not exist. `_connect` never called `sqlite3.connect`
    anywhere, so B went on to fail `_init_schema` with "'NoneType' object has
    no attribute 'execute'" and report the vault CORRUPT — a healthy file, held
    by a healthy server, diagnosed as damaged.

    sqlite3 opens the very same file pyturso refused (measured against the live
    vault while the MCP server held it), so the assertion is now the stronger
    one: B degrades a tier and keeps working."""
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
        "print('CORRUPT', kg._corrupt, flush=True)\n"
        "print('NODES', kg.status()['nodes'], flush=True)\n"
        "try:\n"
        "    kg.add_node('B', 'godnode')\n"
        "    print('WROTE yes', flush=True)\n"
        "except Exception as e:\n"
        "    print('WROTE no', type(e).__name__, flush=True)\n"
    ) % str(path)
    a = subprocess.Popen([sys.executable, "-c", script_a], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    b = subprocess.run([sys.executable, "-c", script_b], capture_output=True, text=True,
                       timeout=15)
    a_out = a.stdout.read()
    a.wait(timeout=10)
    assert "READY" in a_out, f"process A failed: {a.stderr.read()!r}"
    ctx = f"stdout={b.stdout!r} stderr={b.stderr!r}"
    # The lock still holds: B does not get the Turso tier...
    assert "Turso (local)" not in b.stdout, f"expected the lock to hold: {ctx}"
    # ...it degrades to a tier that works, rather than to no connection...
    assert "read-only" in b.stdout, ctx
    assert "CORRUPT False" in b.stdout, f"a locked vault is not a damaged one: {ctx}"
    assert "NODES" in b.stdout, f"the borrowed tier must actually read: {ctx}"
    # ...and it does NOT write. The exclusive lock was enforcing single-writer
    # by accident; the fallback removed that, letting two engines with two WAL
    # implementations write one file. Reads were the point, writes were the bug.
    assert "WROTE no" in b.stdout, (
        f"a borrowed vault must refuse writes -- they belong to its owner: {ctx}")


def test_borrowed_vault_answers_a_search_instead_of_returning_the_lock_error(tmp_path):
    """A search on a borrowed vault must return its results, not the lock notice.

    `search(touch=True)` -- the default, and what `knowledge_query` uses -- ends
    by reinforcing the nodes it hit. On the borrowed tier that write raised
    `VaultUnavailable`, `server.call_tool` caught it and returned the message as
    the answer, so a search that had already ranked its rows came back as an
    error with the rows discarded: every `knowledge_query` against a vault held
    by another instance answered nothing. Measured on the live vault while three
    MCP clients each ran their own gateway: `touch=False` returned 3 hits in
    548ms, `touch=True` raised.

    Reinforcement is a side effect of answering, not part of it, so it is the
    write that gives way -- not the read.
    """
    path = tmp_path / "search_borrowed.db"
    env = {**os.environ, "NEURAG_EMBEDDER": "null"}   # lexical only: no model load
    seed = textwrap.dedent(
        "import time\n"
        "from pathlib import Path\n"
        "from neurag.db import KnowledgeGraph\n"
        "kg = KnowledgeGraph(db_path=Path(r'%s'))\n"
        "nid = kg.add_node('Docs', 'godnode')\n"
        "kg.add_chunk(nid, 'the quorum threshold guards the parking rule',\n"
        "             source='docs/parking.md')\n"
        "print('READY', flush=True)\n"
        "time.sleep(4)\n"
    ) % str(path)
    borrower = textwrap.dedent(
        "import time\n"
        "from pathlib import Path\n"
        "from neurag.db import KnowledgeGraph\n"
        "time.sleep(1)\n"
        "kg = KnowledgeGraph(db_path=Path(r'%s'))\n"
        "print('ENGINE', kg._engine_name, flush=True)\n"
        "try:\n"
        "    hits = kg.search('quorum threshold', top_n=3)\n"   # touch defaults True
        "    print('HITS', len(hits), flush=True)\n"
        "except Exception as e:\n"
        "    print('RAISED', type(e).__name__, flush=True)\n"
    ) % str(path)
    a = subprocess.Popen([sys.executable, "-c", seed], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env)
    b = subprocess.run([sys.executable, "-c", borrower], capture_output=True,
                       text=True, timeout=20, env=env)
    a_out = a.stdout.read()
    a.wait(timeout=10)
    assert "READY" in a_out, f"seeding process failed: {a.stderr.read()!r}"
    ctx = f"stdout={b.stdout!r} stderr={b.stderr!r}"
    assert "read-only" in b.stdout, f"expected the borrowed tier: {ctx}"
    assert "RAISED" not in b.stdout, (
        f"the reinforcement write must not fail the search: {ctx}")
    assert "HITS 1" in b.stdout, f"the borrowed tier must answer: {ctx}"
