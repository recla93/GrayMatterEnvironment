"""A tool list already fetched is served without the worker: a gateway's
handshake queued behind the daemon's model pre-warm (2026-11-28)."""
import asyncio

from gray_matter import server


def test_cached_schemas_skip_the_worker(monkeypatch):
    cached = {"pre_turn": {"description": "", "inputSchema": {"type": "object"}}}
    monkeypatch.setattr(server, "_schemas_cache", {"neuron": cached})

    def _no_worker(name):
        raise AssertionError("the worker was asked")

    monkeypatch.setattr(server, "_worker_for", _no_worker)
    assert asyncio.run(server._fetch_tool_schemas("neuron")) == cached
