"""A corrupt graph store must name its cause and its cure.

NeuRAG closed this in 1.1.1: a malformed knowledge.db crashed every command
with a raw traceback instead of being reported. Neuron is the keep-in-sync twin
of that db.py and never got the same treatment, so a corrupt graph.db still
arrived as a bare `DatabaseError: file is not a database` — a symptom, with no
file named and nothing to do about it.

Neuron's shape is different enough that the fix is too: NeuRAG substitutes the
connection because it owns one for its lifetime, while a Neuron `Graph` is
loaded and saved through many call sites. `server.call_tool` already funnels
every failure into text, so the classification happens there, once.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from neuron.db import corrupt_store_hint  # noqa: E402


@pytest.mark.parametrize("message", [
    "file is not a database",
    "database disk image is malformed",
    "invalid page size in database header: 29793",
    "malformed database schema",
])
def test_every_spelling_of_corruption_is_recognised(message):
    """Which one you get depends on the tier that opened the file (pyturso vs
    sqlite3) and how far the header parsed, so one string is not enough."""
    hint = corrupt_store_hint(RuntimeError(message))
    assert hint, message
    assert "corrupt" in hint
    assert "neuron doctor" in hint, "an error the reader cannot act on is half an error"


def test_an_unrelated_error_is_not_dressed_up_as_corruption():
    """The classifier must stay narrow: telling someone their store is corrupt
    when a directory is missing sends them to delete the wrong thing."""
    assert corrupt_store_hint(RuntimeError("open: NotFound")) == ""
    assert corrupt_store_hint(ValueError("no such column: salience")) == ""


def test_the_path_is_named_when_it_is_known():
    hint = corrupt_store_hint(RuntimeError("file is not a database"), path="/x/graph.db")
    assert "/x/graph.db" in hint


def test_a_real_corrupt_file_is_classified_end_to_end(tmp_path):
    """The message strings above are only worth something if a genuinely
    broken file actually produces one of them."""
    from neuron.models import Graph
    bad = tmp_path / "graph.db"
    bad.write_bytes(b"this is not a database" * 50)
    with pytest.raises(Exception) as exc:      # noqa: PT011 — tier decides the class
        Graph().load_sqlite(str(bad))
    assert corrupt_store_hint(exc.value, str(bad)), f"unclassified: {exc.value!r}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
