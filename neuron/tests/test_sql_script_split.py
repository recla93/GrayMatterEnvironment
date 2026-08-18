"""A ';' inside a SQL comment must not truncate the statement around it.

The remote (Turso Cloud) client has no `executescript`, so
`RemoteTursoConnection.executescript` cuts the script on ';' by hand. A
semicolon inside a `--` comment split the statement that contained it, and the
engine got "incomplete input" — a table silently missing from the schema.

Neuron's own schemas (`models.py`, `engine.py`) carry no SQL comments, so this
never fired here. It fired in NeuRAG, whose `db.py` is the keep-in-sync port of
this file, the first time a column got commented. The defect was latent on this
side, which is worse than broken: it waits for whoever documents a column.
"""
from __future__ import annotations

import sys

from tests._mockdeps import install_mock_deps  # noqa: F401

from neuron.db import _split_sql               # noqa: E402


def test_a_semicolon_in_a_comment_does_not_cut_the_statement():
    script = """
    CREATE TABLE IF NOT EXISTS t (
        id   INTEGER PRIMARY KEY,
        sal  REAL DEFAULT 0.0,   -- Hebbian home (P5); unused for now
        name TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_t ON t(name);
    """
    stmts = _split_sql(script)
    assert len(stmts) == 2, stmts
    assert "name TEXT" in stmts[0] and stmts[0].count("(") == stmts[0].count(")")
    assert stmts[1].startswith("CREATE INDEX")


def test_comment_only_lines_do_not_become_statements():
    assert _split_sql("-- just a note\n-- and another;\n") == []


def test_ordinary_scripts_are_unchanged():
    assert _split_sql("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_neurons_own_schemas_survive_the_split():
    """Not a hypothetical: run the real scripts through the real splitter."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "neuron"
    found = 0
    for f in ("models.py", "engine.py"):
        src = (root / f).read_text(encoding="utf-8")
        for m in re.finditer(r'executescript\("""(.*?)"""', src, re.S):
            found += 1
            for stmt in _split_sql(m.group(1)):
                assert stmt.count("(") == stmt.count(")"), f"{f}: {stmt[:80]}"
                assert stmt.upper().startswith(("CREATE", "INSERT", "PRAGMA",
                                                "ALTER", "DROP")), stmt[:80]
    assert found >= 2, "schema scripts moved — this test is no longer looking at them"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
