"""A corrupt vault has to SAY so, on every surface, not only the diagnostics.

`_init_schema` swallows schema errors into `self._corrupt` so `status`/`health`/
`doctor` can run and report instead of the CLI dying on a malformed file. That
was right, and it was only half done: everything else went on using a
connection with no tables and surfaced a raw pyturso "no such table", which
names the symptom and hides the cause. The handoff records two schema errors
hidden that way in one session, the second found only by driving the CLI by
hand.

These tests corrupt an actual file rather than setting `_corrupt = True`, so
they exercise the detection as well as the reporting.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import (KnowledgeGraph, VaultUnavailable,  # noqa: E402
                        open_failure_message)


@pytest.fixture
def broken(tmp_path):
    """A file that is definitely not a database."""
    p = tmp_path / "knowledge.db"
    p.write_bytes(b"this is not a database, it is a text file" * 40)
    kg = KnowledgeGraph(p)
    yield kg
    kg.close()


def test_the_vault_notices(broken):
    assert broken._corrupt, "a text file was accepted as a vault"
    assert broken._corrupt_err


def test_status_and_health_still_answer(broken):
    """The whole reason corruption is a flag and not an exception: the
    diagnostics must survive it to be able to report it."""
    assert broken.status()["corrupt"] is True
    assert broken.status()["hint"]
    assert broken.health()["ok"] is False


@pytest.mark.parametrize("call", [
    lambda kg: kg.search("anything"),
    lambda kg: kg.recall("anything"),
    lambda kg: kg.get_node_by_name("x"),
    lambda kg: kg.add_node("x", "godnode"),
    lambda kg: kg.rebuild_links(),
    lambda kg: kg.related_nodes(1),
    lambda kg: kg.park(apply=False),
    lambda kg: kg.decay(),
])
def test_every_working_command_names_the_cause_and_the_cure(broken, call):
    """Not a parametrised list of guards -- ONE substituted connection covers
    all of these, which is why a method added later is covered too."""
    with pytest.raises(VaultUnavailable) as exc:
        call(broken)
    msg = str(exc.value)
    assert "file is not a database" in msg, "the cause has to survive to the user"
    assert "neurag doctor" in msg, "an error the user cannot act on is half an error"


# --- locked is not damaged, and the difference is destructive ---------------

def test_a_locked_vault_is_not_reported_as_damaged():
    """The two failures are opposites: a lock clears when the other process
    lets go, damage only clears by replacing the file. They were conflated,
    and the cure for the second is `--wipe-knowledge` -- so a healthy vault
    that happened to be open in the MCP server was one message away from being
    wiped on advice."""
    msg = open_failure_message(
        "Locking error: Failed locking file ... (os error 33)")
    assert "wipe" not in msg.lower(), "told a busy vault to destroy itself"
    assert "another process" in msg.lower()
    assert "neurag stop" in msg, "say which process, or the advice is unusable"


def test_real_damage_still_gets_the_destructive_cure():
    """The narrow classifier must not swallow the case it exists for."""
    msg = open_failure_message("file is not a database")
    assert "--wipe-knowledge" in msg


def test_a_locked_vault_still_opens_and_reads(tmp_path):
    """The reason the lock case matters at all: sqlite3 opens the very file
    pyturso refused, so the fallback is a real tier and not a consolation.
    Measured against the live vault while the MCP server held it."""
    kg = KnowledgeGraph(tmp_path / "v.db")
    n = kg.add_node("N", "godnode")
    kg.add_chunk(n, "content that must survive a degraded open", source="a.md")
    kg.close()
    import neurag.db as dbmod
    dbmod._turso_conn_cache.clear()          # TODO-6: close() keeps it cached
    real, dbmod.TURSO_AVAILABLE = dbmod.TURSO_AVAILABLE, False   # force the tier
    try:
        kg2 = KnowledgeGraph(tmp_path / "v.db")
        assert not kg2._corrupt, kg2._corrupt_err
        assert kg2._engine_name == "SQLite (degraded)"
        assert kg2.search("content that must survive")
        kg2.close()
    finally:
        dbmod.TURSO_AVAILABLE = real


def test_closing_a_vault_that_never_opened_is_not_an_error(broken):
    broken.close()          # the fixture closes it again; both must be fine


def test_a_healthy_vault_is_untouched(tmp_path):
    """The guard must not cost anything on the path everyone actually takes."""
    kg = KnowledgeGraph(tmp_path / "ok.db")
    assert not kg._corrupt
    n = kg.add_node("N", "godnode")
    kg.add_chunk(n, "hello world", source="a.md")
    assert kg.search("hello")
    kg.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
