"""An optional argument that was not given is an ABSENT key, not a null one.

`neurag ingest <path>` without `--godnode` sent `{"godnode": None}` to the
gateway. The MCP schema declares it `{"type": "string"}` and does not require
it — so an omitted key is valid and an explicit null is not. Every ingest from
the CLI died with "Input validation error: None is not of type 'string'"
whenever Gray Matter was running, which is the normal case.

Found by using the tool the way a user would, not by a unit test: the failure
needs a live gateway on the other end.
"""
import pathlib
import sys

import pytest

# The peers must run WITHOUT Gray Matter. This file exercises the
# collaboration WITH it, so a GM-less venv must skip it, not invent failures.
pytest.importorskip("gray_matter")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


@pytest.fixture
def sent(monkeypatch):
    """Capture what would go over IPC, with a gateway that says yes."""
    import neurag.cli as cli
    box = {}
    import gray_matter.cli as gmc
    from neurag import clients as rc

    def fake_ipc(payload):
        if payload.get("action") == "ping":
            return {"gm": True}
        box["args"] = payload["args"]
        return {"result": "ok"}

    monkeypatch.setattr(gmc, "_send_ipc", fake_ipc)
    monkeypatch.setattr(rc, "gm_still_manages", lambda tool: True)
    return box


def test_a_none_valued_optional_is_dropped_before_it_reaches_the_gateway(sent):
    from neurag.cli import _run_via_gm
    assert _run_via_gm("knowledge_ingest", {"path": "/x/doc.md", "godnode": None})
    assert sent["args"] == {"path": "/x/doc.md"}, "il null è arrivato allo schema"


def test_a_given_optional_still_travels(sent):
    from neurag.cli import _run_via_gm
    _run_via_gm("knowledge_ingest", {"path": "/x", "godnode": "Ricette"})
    assert sent["args"]["godnode"] == "Ricette"


def test_add_node_has_the_same_shape_and_the_same_fix(sent):
    """`--parent` defaults to None too — same trap, same funnel."""
    from neurag.cli import _run_via_gm
    _run_via_gm("knowledge_add_node",
                {"name": "N", "node_type": "godnode", "parent_name": None,
                 "triggers": []})
    assert "parent_name" not in sent["args"]
    assert sent["args"]["triggers"] == [], "una lista vuota non è un valore assente"


def test_falsey_values_that_are_not_none_survive(sent):
    """`0`, `""` and `False` are answers; only None means "not given"."""
    from neurag.cli import _run_via_gm
    _run_via_gm("knowledge_query", {"query": "", "top_n": 0, "deep": False})
    assert sent["args"] == {"query": "", "top_n": 0, "deep": False}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
