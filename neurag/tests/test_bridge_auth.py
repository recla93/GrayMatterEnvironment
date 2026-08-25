"""Il bridge HTTP non si pubblica aperto senza chiave.

`--host 0.0.0.0` e i tunnel espongono tool distruttivi (knowledge_remove_node,
knowledge_ingest): senza shared secret il bind va rifiutato all'avvio, non
pubblicato pregando che nessuno lo trovi.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from neurag import http_transport  # noqa: E402


def test_loopback_needs_no_token(monkeypatch):
    monkeypatch.delenv("NEURAG_BRIDGE_TOKEN", raising=False)
    assert not http_transport._refuse_open_bind("127.0.0.1")
    assert not http_transport._refuse_open_bind("localhost")


def test_open_bind_without_token_is_refused(monkeypatch):
    monkeypatch.delenv("NEURAG_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("NEURAG_BRIDGE_ALLOW_OPEN", raising=False)
    assert http_transport._refuse_open_bind("0.0.0.0")
    with pytest.raises(SystemExit):
        http_transport.serve(app=None, host="0.0.0.0", port=1)


def test_open_bind_with_token_or_escape_hatch_passes(monkeypatch):
    monkeypatch.setenv("NEURAG_BRIDGE_TOKEN", "s3cret")
    assert not http_transport._refuse_open_bind("0.0.0.0")

    monkeypatch.delenv("NEURAG_BRIDGE_TOKEN", raising=False)
    monkeypatch.setenv("NEURAG_BRIDGE_ALLOW_OPEN", "1")
    assert not http_transport._refuse_open_bind("0.0.0.0")
