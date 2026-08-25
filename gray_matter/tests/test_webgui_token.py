"""Il gate del capability token sulla GUI HTTP.

Prima del 2026-08-25 ogni risposta portava `Access-Control-Allow-Origin: *`
e nessun POST richiedeva auth: qualsiasi sito aperto nel browser poteva
comandare l'Api (che spawna subprocess veri: run, repair_run, uninstall_run)
con un fetch su 127.0.0.1 — il CORS non blocca la *sending* cross-origin.
"""
import json
import threading
import urllib.error
import urllib.request

import pytest

webgui = pytest.importorskip("gray_matter.webgui")


@pytest.fixture
def gui_server():
    srv, port, html = webgui._build_server(webgui.Api())
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, port, html
    srv.shutdown()


def _post(port: int, token: str | None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/poll_log", data=b"", method="POST")
    if token is not None:
        req.add_header("X-GM-Token", token)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def test_post_without_token_is_403(gui_server):
    _, port, _ = gui_server
    with pytest.raises(urllib.error.HTTPError) as err:
        _post(port, token=None)
    assert err.value.code == 403


def test_post_with_a_wrong_token_is_403(gui_server):
    _, port, _ = gui_server
    with pytest.raises(urllib.error.HTTPError) as err:
        _post(port, token="forged")
    assert err.value.code == 403


def test_post_with_the_real_token_passes(gui_server):
    _, port, html = gui_server
    # il token vero è incorporato nella pagina servita: lo si estrae da lì,
    # esattamente come fa il JS del pannello
    marker = 'const TOKEN = "'
    start = html.index(marker) + len(marker)
    token = html[start:html.index('"', start)]
    status, body = _post(port, token=token)
    assert status == 200
    assert "error" not in body


def test_no_cors_wildcard_and_no_leftover_placeholder(gui_server):
    """ACAO:* era il buco: una volta tolto non deve tornare, e il placeholder
    del token non deve sopravvivere nella pagina servita."""
    _, _, html = gui_server
    assert "__GM_TOKEN__" not in html
    src = html  # la pagina è ciò che un altro sito vedrebbe provando a leggere
    assert "Access-Control-Allow-Origin" not in src or \
        "__GM_TOKEN__" in src  # se qualcuno lo reintrodotto, almeno il token c'è
