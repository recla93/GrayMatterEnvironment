"""gray_matter_brainstorm: il vicinato di un problema, con la sua storia.

La versione precedente prendeva la CODA di una ricerca normale e chiamava il
rank "distanza": l'ottavo chunk piu' vicino su seimila usciva come "distance
1.0" (visto sul vivo 2026-09-14). Ora compone Neuron `around` (banda media con
fatti e ragioni) e i chunk NeuRAG piu' vicini, e non inventa nessuna misura.
"""
import asyncio

import pytest

from gray_matter import server as S


@pytest.fixture
def srv(monkeypatch):
    calls = []

    async def fake_call(server, tool, args):
        calls.append((server, tool, dict(args)))
        if (server, tool) == ("neuron", "around"):
            return ("Around 'lock' (mid-band 0.3-0.75, 2 nodes, now=100):\n"
                    "  mode-ro  sim=0.61  salience=4  dormant 12t\n"
                    "    fact: sqlite3 nudo cancella il WAL alla close\n"
                    "  bare  sim=0.44  salience=1  active")
        if (server, tool) == ("neurag", "knowledge_query"):
            return "Query: lock\nTop 1 results:\n  [1] docs/DATA.md :: Neuron > Backup\n       mode=ro..."
        raise AssertionError(f"unexpected call {server}.{tool}")
    monkeypatch.setattr(S, "_call_server_async", fake_call)
    S._calls = calls
    return S


def _run(S, **args):
    return asyncio.run(S._tool_brainstorm(args))[0].text


def test_memory_and_knowledge_travel_as_they_are_no_invented_distance(srv):
    out = _run(srv, seed="lock")
    assert "fact: sqlite3 nudo cancella il WAL" in out
    assert "docs/DATA.md :: Neuron > Backup" in out
    assert "distance" not in out and "0.875" not in out


def test_it_asks_neuron_around_not_the_tail_of_a_search(srv):
    _run(srv, seed="lock", n=7)
    assert ("neuron", "around", {"topic": "lock", "n": 7}) in srv._calls
    assert not [c for c in srv._calls if c[1] == "vector_search"]
    kq = [c for c in srv._calls if c[1] == "knowledge_query"][0]
    assert kq[2]["top_n"] == 3, "i chunk restano pochi: sono contesto, non la lista"


def test_a_dormant_hint_tells_how_to_bring_it_back(srv):
    out = _run(srv, seed="lock")
    assert "dormant 12t" in out and "confirm(" in out and "recall(" in out


def test_one_missing_worker_does_not_empty_the_answer(srv, monkeypatch):
    async def half(server, tool, args):
        if server == "neuron":
            raise RuntimeError("worker down")
        return "Query: lock\n  [1] docs/DATA.md :: Neuron > Backup"
    monkeypatch.setattr(S, "_call_server_async", half)
    out = _run(srv, seed="lock")
    assert "memoria: non disponibile" in out and "docs/DATA.md" in out


def test_an_empty_seed_says_what_to_pass(srv):
    assert "seed" in _run(srv, seed="  ") and srv._calls == []
