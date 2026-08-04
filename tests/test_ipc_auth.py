"""IPC autenticato + un solo set di worker per macchina.

La porta accetta `call`, cioè l'esecuzione di un tool arbitrario sui worker:
chi la raggiunge legge e SCRIVE la memoria. Il bind è su loopback, che però su
una macchina multi-utente non è una barriera. Qui si fissano le due regole che
lo rendono sicuro e il fallback che lo rende non-bloccante.
"""
import importlib
import json
import os
import socket
import struct
import threading

import pytest

from gray_matter import cli


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GM_HOME", str(tmp_path))
    from gray_matter import paths
    importlib.reload(paths)
    yield tmp_path
    monkeypatch.delenv("GM_HOME", raising=False)
    importlib.reload(paths)


def test_token_is_created_once_and_reused(home):
    first = cli.ensure_ipc_token()
    assert len(first) == 32
    # Idempotente: un secondo gateway che parte non può coniarne un altro, o
    # parlerebbe con un segreto che il daemon rifiuta.
    assert cli.ensure_ipc_token() == first
    assert cli.read_ipc_token() == first


def test_every_request_carries_the_token(home):
    """`_send_ipc` è l'unico mittente: se lo allega qui, lo allegano CLI e GUI."""
    cli.ensure_ipc_token()
    seen = {}

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _run():
        conn, _ = srv.accept()
        with conn:
            hdr = conn.recv(4)
            (n,) = struct.unpack("!I", hdr)
            seen.update(json.loads(conn.recv(n).decode("utf-8")))
            body = json.dumps({"status": "ok"}).encode("utf-8")
            conn.sendall(struct.pack("!I", len(body)) + body)
        srv.close()

    threading.Thread(target=_run, daemon=True).start()
    original = cli.resolve_port
    cli.resolve_port = lambda: port
    try:
        cli._send_ipc({"action": "status"})
    finally:
        cli.resolve_port = original
    assert seen.get("token") == cli.read_ipc_token()


def test_ping_stays_unauthenticated():
    """Il probe del singleton deve funzionare PRIMA che qualcuno abbia il
    token — se lo richiedesse, due daemon si accamperebbero sulla stessa porta
    senza mai riconoscersi. Rivela solo 'qui c'è un GM'."""
    server = pytest.importorskip("gray_matter.server")
    src = __import__("inspect").getsource(server._ipc_listener)
    ping = src.index('action == "ping"')
    guard = src.index("compare_digest")
    assert ping < guard, "il ramo ping deve precedere il controllo del token"


def test_shared_workers_can_be_switched_off(monkeypatch):
    """GM_SHARED_WORKERS=0 riporta al comportamento vecchio (worker locali).

    È la via d'uscita se la serializzazione fra client dà fastidio, ed è ciò
    che tiene VIVO il ramo di fallback: senza, il percorso locale marcisce."""
    server = pytest.importorskip("gray_matter.server")
    monkeypatch.setenv("GM_SHARED_WORKERS", "0")
    assert server._daemon_reachable() is False


def test_daemon_never_delegates_to_itself(monkeypatch):
    """Il daemon POSSIEDE i worker: se delegasse, chiamerebbe se stesso."""
    server = pytest.importorskip("gray_matter.server")
    monkeypatch.setattr(server, "_IS_DAEMON", True)
    monkeypatch.delenv("GM_SHARED_WORKERS", raising=False)
    assert server._daemon_reachable() is False
