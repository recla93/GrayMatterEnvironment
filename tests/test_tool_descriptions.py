"""What the model reads before deciding to call a tool.

A tool is chosen from the tool list, which is the one text always in front of
the model — a skill file is read only if it decides to read one. So the fact
that decides the call belongs in the description, and the decisive fact is not
HOW to search but whether there is anything to find: "Search the knowledge
base" gives no reason to spend a round-trip, "2555 chunks of the user's own
material" does.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import neurag.server as S  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh():
    S._VAULT_STATS = None
    yield
    S._VAULT_STATS = None


def _note(monkeypatch, status):
    monkeypatch.setattr(S, "_get_db", lambda: type("K", (), {"status": lambda self: status})())
    return S._vault_note()


def test_a_populated_vault_says_how_much_it_holds(monkeypatch):
    note = _note(monkeypatch, {"chunks": 2555, "nodes": 17})
    assert "2555" in note and "17" in note


def test_an_empty_vault_tells_the_model_not_to_bother(monkeypatch):
    """The opposite failure of the one this fixes: searching nothing, forever."""
    note = _note(monkeypatch, {"chunks": 0, "nodes": 1})
    assert "EMPTY" in note and "do not search" in note


def test_an_unreadable_vault_points_at_the_diagnostic(monkeypatch):
    note = _note(monkeypatch, {"corrupt": True, "chunks": 0, "nodes": 0})
    assert "knowledge_status" in note


def test_a_broken_stat_costs_the_sentence_not_the_handshake(monkeypatch):
    """list_tools() runs during the MCP handshake. A vault that will not open
    must cost the extra sentence and nothing else."""
    def boom():
        raise RuntimeError("vault on fire")
    monkeypatch.setattr(S, "_get_db", boom)
    assert S._vault_note() == ""
    assert S._tools(), "the handshake lost its tools over a failed stat"


def test_knowledge_query_states_when_to_use_it_and_what_is_lost(monkeypatch):
    """Trigger AND trade-off: a description that only names the tool leaves the
    model to guess whether this turn is one of the turns it is for."""
    monkeypatch.setattr(S, "_get_db", lambda: type("K", (), {"status": lambda self: {"chunks": 9, "nodes": 2}})())
    d = {t.name: t.description for t in S._tools()}["knowledge_query"]
    assert "USER'S OWN" in d, "nothing distinguishes it from general knowledge"
    assert "skip it" in d.lower(), "no negative trigger: the model over-calls instead"
    assert "cite" in d.lower()


def test_the_stat_is_computed_once_per_process(monkeypatch):
    calls = {"n": 0}
    def counting():
        calls["n"] += 1
        return type("K", (), {"status": lambda self: {"chunks": 1, "nodes": 1}})()
    monkeypatch.setattr(S, "_get_db", counting)
    S._vault_note(); S._vault_note(); S._tools()
    assert calls["n"] == 1, "reopening the vault on every list_tools()"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
