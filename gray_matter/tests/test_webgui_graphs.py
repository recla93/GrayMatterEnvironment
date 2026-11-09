"""Api.graphs: the Graphs panel reads through the tools (daemon IPC), never the
stores (ADR-016), and one source failing never blanks the other two."""
import json
import threading
import urllib.request

import pytest

webgui = pytest.importorskip("gray_matter.webgui")
from gray_matter import bridges, cli  # noqa: E402

NEURON = {"nodes": [{"keyword": "release"}], "links": [],
          "facts": [{"id": "ab12", "kind": "fact", "text": "t", "concepts": ["release"],
                     "status": "active"}]}
NEURAG = {"nodes": [{"id": 0, "name": "Root", "layer": 2}], "links": []}


@pytest.fixture
def ipc(monkeypatch):
    calls = []

    def fake(msg, timeout=0, connect_timeout=None):
        calls.append(msg)
        return {"result": json.dumps(NEURON if msg["action"] == "gm-neuron" else NEURAG)}
    monkeypatch.setattr(cli, "_send_ipc", fake)
    monkeypatch.setattr(bridges, "all_bridges", lambda: [
        {"neuron": "#ab12", "neurag": "Root", "rationale": "why", "weight": 2.0,
         "promoted": 0, "neuron_key": "#ab12", "created": 1.0}])
    return calls


def test_graphs_asks_the_tools_and_returns_the_three_graphs(ipc):
    out = webgui.Api().graphs()
    assert out["neuron"] == NEURON and out["neurag"] == NEURAG
    assert out["bridges"] == [{"neuron": "#ab12", "neurag": "Root", "rationale": "why",
                               "weight": 2.0, "promoted": 0}]
    assert [(c["action"], c["tool"]) for c in ipc] == [
        ("gm-neuron", "export"), ("gm-neurag", "knowledge_link_graph")]
    assert ipc[1]["args"] == {"format": "json"}


def test_a_failing_source_is_an_error_in_its_slot_not_a_blank_panel(monkeypatch):
    def fake(msg, timeout=0, connect_timeout=None):
        if msg["action"] == "gm-neuron":
            raise ConnectionRefusedError("daemon down")
        return {"result": "No links. Run knowledge_rebuild_links first."}   # an old NeuRAG
    monkeypatch.setattr(cli, "_send_ipc", fake)
    monkeypatch.setattr(bridges, "all_bridges", lambda: (_ for _ in ()).throw(OSError("locked")))
    out = webgui.Api().graphs()
    assert "daemon down" in out["neuron"]["error"]
    assert "No links" in out["neurag"]["error"]
    assert out["bridges"] == {"error": "locked"}


def test_the_graph_library_is_served_from_the_package():
    srv, port, html = webgui._build_server(webgui.Api())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/vis-network.min.js", timeout=5) as r:
            assert r.status == 200 and b"vis-network" in r.read(400)
    finally:
        srv.shutdown()
    assert "/vis-network.min.js" in html          # the page loads it from us, not a CDN
    assert "unpkg" not in html and "cdn." not in html
