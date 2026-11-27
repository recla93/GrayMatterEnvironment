"""A respawned worker is alive again: a managed server once marked dead stayed
dead, and _reap_dead_workers killed every new worker mid-call (2026-11-27)."""
from gray_matter import server
from gray_matter.registry import Registry


class _FakeProc:
    def poll(self):
        return None


def test_respawn_clears_dead(monkeypatch):
    reg = Registry()
    reg.register_managed("neuron", ["pre_turn"])
    reg.mark_dead("neuron")
    monkeypatch.setattr(server, "_registry", reg)
    monkeypatch.setattr(server, "_workers", {})
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: _FakeProc())
    server._worker_for("neuron")
    assert reg.get_server("neuron").status == "alive"
