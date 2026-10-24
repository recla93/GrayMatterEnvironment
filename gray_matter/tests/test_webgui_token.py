"""The capability-token gate on the HTTP GUI.

Before 2026-08-25 every response carried `Access-Control-Allow-Origin: *`
and no POST required auth: any website open in the browser could command the
Api (which spawns real subprocesses: run, repair_run, uninstall_run) with a
fetch to 127.0.0.1 — CORS does not block cross-origin *sending*.
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
    # the real token is embedded in the served page: extract it from there,
    # exactly like the panel's JS does
    marker = 'const TOKEN = "'
    start = html.index(marker) + len(marker)
    token = html[start:html.index('"', start)]
    status, body = _post(port, token=token)
    assert status == 200
    assert "error" not in body


def _get(port: int, host: str):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/")
    req.add_header("Host", host)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def test_a_foreign_host_gets_neither_the_page_nor_the_token(gui_server):
    """DNS rebinding (ADR-012 F2): attacker.example resolved to 127.0.0.1 is
    same-origin for the browser. Verified 2026-10-24: the page came back with
    the token in it."""
    _, port, _ = gui_server
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(port, f"attacker.example:{port}")
    assert err.value.code == 403
    assert b"TOKEN" not in err.value.read()


def test_a_foreign_host_cannot_post_even_with_the_token(gui_server):
    _, port, html = gui_server
    marker = 'const TOKEN = "'
    start = html.index(marker) + len(marker)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/poll_log",
                                 data=b"", method="POST")
    req.add_header("Host", f"attacker.example:{port}")
    req.add_header("X-GM-Token", html[start:html.index('"', start)])
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)
    assert err.value.code == 403


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_the_browsers_own_names_for_us_still_work(gui_server, name):
    _, port, _ = gui_server
    status, page = _get(port, f"{name}:{port}")
    assert status == 200 and 'const TOKEN = "' in page


def test_no_cors_wildcard_and_no_leftover_placeholder(gui_server):
    """ACAO:* was the hole: once removed it must not come back, and the token
    placeholder must not survive into the served page."""
    _, _, html = gui_server
    assert "__GM_TOKEN__" not in html
    src = html  # the page is what another site would see when trying to read it
    assert "Access-Control-Allow-Origin" not in src or \
        "__GM_TOKEN__" in src  # if someone reintroduces ACAO, at least keep the token gate
