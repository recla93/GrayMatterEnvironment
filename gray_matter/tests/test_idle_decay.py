"""Idle work runs once per machine, in the daemon (ADR-010 F0).

`_sleep_monitor` runs in the daemon AND in every stdio gateway, each with its
own idle clock. The backup was daemon-only; `decay()` was not, so the bridges
decayed once per open client. And the daemon's clock never moved — only stdio
`call_tool` touched it — so a daemon-only decay would have run once per life.
"""
import asyncio
import time

import pytest


def _one_tick(monkeypatch, server, is_daemon: bool) -> int:
    """Run `_sleep_monitor` for exactly one tick, idle long past the timeout.
    Returns how many times bridges.decay() was called."""
    from gray_matter import backup, bridges

    calls = {"decay": 0}
    monkeypatch.setattr(bridges, "decay", lambda *a, **k: calls.__setitem__("decay", calls["decay"] + 1))
    monkeypatch.setattr(backup, "run", lambda *a, **k: (None, []))
    monkeypatch.setattr(server, "_IS_DAEMON", is_daemon)
    monkeypatch.setattr(server, "_is_sleeping", False)
    monkeypatch.setattr(server, "IDLE_SLEEP_TIMEOUT", 1.0)
    monkeypatch.setattr(server, "_last_call_time", time.time() - 100)

    ticks = {"n": 0}

    async def fake_sleep(_s):
        ticks["n"] += 1
        if ticks["n"] > 1:              # second tick: stop the endless loop
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(server._sleep_monitor())
    return calls["decay"]


def test_decay_runs_in_the_daemon_and_not_in_a_gateway(monkeypatch):
    pytest.importorskip("mcp")
    from gray_matter import server

    in_daemon = _one_tick(monkeypatch, server, is_daemon=True)
    in_gateway = _one_tick(monkeypatch, server, is_daemon=False)
    assert (in_daemon, in_gateway) == (1, 0), (
        f"daemon={in_daemon} gateway={in_gateway}: decay must run once per machine")


def test_a_gateway_call_moves_the_daemon_idle_clock():
    """The daemon has no stdio: gateway calls reach it as IPC `call`. If that
    branch does not touch `_last_call_time`, the daemon sleeps 600 s after start
    and never wakes."""
    pytest.importorskip("mcp")
    import inspect
    from gray_matter import server

    src = inspect.getsource(server._ipc_listener)
    i_call = src.find('action in ("call", "knowledge_cmd")')
    i_next = src.find('elif action == "schemas"', i_call)
    assert i_call != -1 and i_next != -1, "IPC call branch not found"
    assert "_last_call_time = time.time()" in src[i_call:i_next], (
        "the IPC call branch must move the daemon's idle clock")
    assert "global _last_call_time" in src, "without `global` the assignment is a local"
