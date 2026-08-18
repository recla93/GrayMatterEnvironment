"""Regressioni IPC — i bug che 626 test verdi non vedevano.

Tutti e tre passavano inosservati perché i test mockano l'IPC invece di aprire
un socket vero: il difetto stava nel trasporto, non nella logica sopra.
"""

import json
import socket
import struct
import threading

import pytest

from gray_matter import cli


def _serve_once(payload: bytes, chunk: int | None = None) -> int:
    """Server TCP usa-e-getta: risponde con `payload` incorniciato, a fette di
    `chunk` byte se richiesto (simula la frammentazione TCP). Ritorna la porta."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _run() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(65536)                      # richiesta: la ignoriamo
            framed = struct.pack("!I", len(payload)) + payload
            if chunk is None:
                conn.sendall(framed)
            else:
                for i in range(0, len(framed), chunk):
                    conn.sendall(framed[i:i + chunk])
        srv.close()

    threading.Thread(target=_run, daemon=True).start()
    return port


@pytest.fixture
def _point_cli_at(monkeypatch):
    """Fa parlare `cli._send_ipc` col server finto invece che col daemon."""
    def _apply(port: int) -> None:
        monkeypatch.setattr(cli, "resolve_port", lambda: port)
    return _apply


def test_send_ipc_reassembles_a_response_split_across_segments(_point_cli_at):
    """Il bug: `s.recv(n)` restituisce quello che è ARRIVATO, non quello che è
    stato chiesto. Ogni risposta più grossa di un segmento TCP (`status` con le
    liste di tool, `bridges`, `logs`, qualunque risultato di gm-neuron) tornava
    troncata e json.loads esplodeva con un traceback grezzo in faccia all'utente.
    """
    big = {"servers": {f"srv{i}": {"tools": ["t"] * 40} for i in range(60)}}
    payload = json.dumps(big).encode("utf-8")
    assert len(payload) > 1500, "il payload deve superare un segmento TCP"

    port = _serve_once(payload, chunk=256)        # arriva a fette, come nella vita
    _point_cli_at(port)

    assert cli._send_ipc({"action": "status"}) == big


def test_send_ipc_reports_a_malformed_response_instead_of_raising(_point_cli_at):
    """Un frame che promette N byte di JSON e ne consegna spazzatura deve
    diventare un `{"error": ...}` gestibile, non un traceback."""
    port = _serve_once(b"non sono json")
    _point_cli_at(port)

    result = cli._send_ipc({"action": "status"})
    assert "error" in result and "malformed" in result["error"]


def test_server_send_ipc_is_the_one_from_cli():
    """Il bug peggiore: `server.py` aveva una COPIA sincrona di `_recv_exact`
    resa irraggiungibile dall'omonima `async _recv_exact` definita più sotto —
    Python risolve i globali alla chiamata, quindi `_send_ipc` invocava la
    coroutine con 2 argomenti su 3 e sollevava TypeError. Effetto a valle:
    `_send_heartbeat`/`_send_registration` fallivano SEMPRE, NeuRAG standalone
    moriva all'avvio e Neuron non si registrava mai al gateway, in silenzio.

    Una sola copia, in cli.py. Se qualcuno ne ridefinisce una qui, il test cade.
    """
    server = pytest.importorskip("gray_matter.server")
    assert server._send_ipc is cli._send_ipc
    assert "_recv_exact" not in server.__dict__, (
        "server.py non deve ridefinire _recv_exact: la sync vive in cli.py e "
        "l'async si chiama _recv_exact_async proprio per non coprirla"
    )


def test_heartbeat_and_registration_are_callable():
    """Il sintomo diretto dello shadowing: queste due sollevavano TypeError
    prima ancora di toccare la rete. Senza daemon devono tornare un dict di
    errore pulito — mai un'eccezione."""
    server = pytest.importorskip("gray_matter.server")
    port = _serve_once(json.dumps({"status": "ok"}).encode("utf-8"))

    import gray_matter.cli as _cli
    original = _cli.resolve_port
    _cli.resolve_port = lambda: port
    try:
        assert server._send_heartbeat("neuron") == {"status": "ok"}
    finally:
        _cli.resolve_port = original


def test_tool_calls_get_a_longer_timeout_than_status_probes():
    """Il primo `gm-neuron pre_turn` falliva sempre con "timed out": il modello
    di embedding freddo ci mette 3-5s e il timeout era fisso a 3s."""
    assert cli.IPC_TOOL_TIMEOUT > cli.IPC_TIMEOUT
    assert cli.IPC_TOOL_TIMEOUT >= 30.0
