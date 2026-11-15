"""knowledge_query shows the whole chunk, not its first 200 chars (2026-11-15).

On 14 detail questions over the real KB the answer was in view 8 times
instead of 6; returning the whole section on top added none.
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag import server  # noqa: E402
from neurag.db import KnowledgeGraph  # noqa: E402


def test_the_tail_of_a_chunk_reaches_the_model(monkeypatch):
    kg = KnowledgeGraph(pathlib.Path(":memory:"))
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "proxy firewall handshake notes. " + "filler words here. " * 12
                 + "The answer is port 8443.", source="net.md")
    monkeypatch.setattr(server, "_db", kg)
    out = asyncio.run(server.call_tool("knowledge_query", {"query": "proxy firewall handshake"}))[0].text
    kg.close()
    assert "port 8443" in out, out
