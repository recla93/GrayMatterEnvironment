"""IPC autenticato + un solo set di worker per macchina.

La porta accetta `call`, cioè l'esecuzione di un tool arbitrario sui worker:
chi la raggiunge legge e SCRIVE la memoria. Ogni messaggio tranne `ping` porta
un JWT rilasciato sul canale di questo utente (ADR-012 fase 2, test del modulo
in test_ipcauth.py). Qui si fissano le regole lato client e il fallback.
"""
import json
import socket
import struct
import threading

import pytest

from gray_matter import cli, ipcauth


def _fake_daemon(replies: list) -> "tuple[int, list]":
    """A TCP listener that records each message and answers from `replies`."""
    seen: list = []
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(len(replies))

    def _run():
        for reply in replies:
            conn, _ = srv.accept()
            with conn:
                (n,) = struct.unpack("!I", cli._recv_exact(conn, 4))
                seen.append(json.loads(cli._recv_exact(conn, n).decode("utf-8")))
                body = json.dumps(reply).encode("utf-8")
                conn.sendall(struct.pack("!I", len(body)) + body)
        srv.close()

    threading.Thread(target=_run, daemon=True).start()
    return srv.getsockname()[1], seen


@pytest.fixture
def tokens(monkeypatch):
    calls: list = []

    def fake(*, refresh=False):
        calls.append(refresh)
        return "jwt-fresh" if refresh else "jwt-cached"
    monkeypatch.setattr(ipcauth, "client_token", fake)
    return calls


def test_every_request_carries_the_channel_token(tokens, monkeypatch):
    """`_send_ipc` è l'unico mittente: se lo allega qui, lo allegano CLI, GUI,
    gateway e registrazioni."""
    port, seen = _fake_daemon([{"status": "ok"}])
    monkeypatch.setattr(cli, "resolve_port", lambda: port)
    cli._send_ipc({"action": "status"})
    assert seen[0]["token"] == "jwt-cached"


def test_a_rejected_token_is_renewed_once(tokens, monkeypatch):
    """Un daemon riavviato ha una chiave nuova: il token in cache è morto."""
    port, seen = _fake_daemon([{"error": "unauthorized"}, {"status": "ok"}])
    monkeypatch.setattr(cli, "resolve_port", lambda: port)
    assert cli._send_ipc({"action": "status"}) == {"status": "ok"}
    assert [m["token"] for m in seen] == ["jwt-cached", "jwt-fresh"]
    assert tokens == [False, True], "un solo rinnovo, poi basta"


def test_ping_carries_no_token(tokens, monkeypatch):
    port, seen = _fake_daemon([{"gm": True}])
    monkeypatch.setattr(cli, "resolve_port", lambda: port)
    cli._send_ipc({"action": "ping"})
    assert "token" not in seen[0] and tokens == []


def test_ping_stays_unauthenticated_and_everything_else_is_checked():
    """Il probe del singleton deve funzionare PRIMA che qualcuno abbia il
    token — se lo richiedesse, due daemon si accamperebbero sulla stessa porta
    senza mai riconoscersi. Rivela solo 'qui c'è un GM'."""
    server = pytest.importorskip("gray_matter.server")
    src = __import__("inspect").getsource(server._ipc_listener)
    assert src.index('action == "ping"') < src.index("_ipcauth.verify_request")
    assert "compare_digest" not in src, "il vecchio segreto su file è tornato"


def test_the_key_and_channel_exist_before_the_port_is_published():
    server = pytest.importorskip("gray_matter.server")
    src = __import__("inspect").getsource(server._ipc_listener)
    assert src.index("_ipcauth.serve(") < src.index("write_port_file(")


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
