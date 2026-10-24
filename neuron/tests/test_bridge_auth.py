"""The HTTP bridge never serves without a key unless told to, on any host.

keep-in-sync with neurag/tests/test_bridge_auth.py: same attack, same defense,
env prefixed NEURON_.

Loopback used to be exempt. But `--tunnel` binds 127.0.0.1 and cloudflared
reaches the bridge FROM loopback: a public URL served every tool to anyone
(ADR-012 F1).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neuron import http_transport  # noqa: E402

P = "NEURON"


def _clean(monkeypatch):
    monkeypatch.delenv(f"{P}_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv(f"{P}_BRIDGE_ALLOW_OPEN", raising=False)


def test_loopback_without_a_configured_token_still_gets_one(monkeypatch, capsys):
    _clean(monkeypatch)
    token = http_transport.resolve_token(P)
    assert token and len(token) >= 32, "senza token configurato il bridge resta aperto"
    assert token in capsys.readouterr().err, "il token generato va mostrato, o nessuno lo usa"


def test_every_run_mints_a_different_token(monkeypatch):
    _clean(monkeypatch)
    assert http_transport.resolve_token(P) != http_transport.resolve_token(P)


def test_a_configured_token_wins(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv(f"{P}_BRIDGE_TOKEN", "s3cret")
    assert http_transport.resolve_token(P) == "s3cret"


def test_open_only_when_asked_and_said_out_loud(monkeypatch, capsys):
    _clean(monkeypatch)
    monkeypatch.setenv(f"{P}_BRIDGE_ALLOW_OPEN", "1")
    assert http_transport.resolve_token(P) is None
    assert "OPEN" in capsys.readouterr().err


def test_the_prefix_keeps_the_bridges_apart(monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("GM_BRIDGE_TOKEN", "gm-only")
    assert http_transport.resolve_token("GM") == "gm-only"
    assert http_transport.resolve_token(P) != "gm-only"
