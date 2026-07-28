"""La console della GUI deve bastare: niente finestre CMD, risposte incluse."""

import inspect
import io
import re
import sys
import tokenize
from pathlib import Path

import pytest

webgui = pytest.importorskip("gray_matter.webgui")
HTML = Path(__file__).resolve().parents[1] / "webgui.html"


def _code(obj) -> str:
    """Sorgente senza commenti: un flag NOMINATO nel commento che ne spiega
    l'assenza non deve far passare (o fallire) un test sul codice."""
    src = inspect.getsource(obj)
    lines = src.splitlines()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col]
    return "\n".join(lines)


def test_gui_never_opens_a_console_window():
    """Il bug segnalato: la GUI dirottava i comandi interattivi (setup, connect,
    cloud) e repair in una finestra `cmd /k` con CREATE_NEW_CONSOLE. Ora girano
    nella console del pannello, con stdin collegato."""
    src = _code(webgui)
    assert "CREATE_NEW_CONSOLE" not in src
    assert not re.search(r'["\']cmd["\']\s*,\s*cmd_flag', src)
    assert not hasattr(webgui.Api, "_terminal"), (
        "_terminal apriva la finestra: se torna, torna la finestra"
    )


def test_streamed_commands_get_a_writable_stdin():
    """Senza stdin collegato un comando che fa una domanda resta appeso in
    silenzio — ed era la ragione per cui esisteva la finestra esterna."""
    src = _code(webgui.Api._stream)
    assert "stdin=subprocess.PIPE" in src
    assert "stdin=subprocess.DEVNULL" not in src


def test_send_input_without_a_running_command_is_an_error_not_a_crash():
    api = webgui.Api()
    r = api.send_input('{"text": "yes"}')
    assert r["ok"] is False and "no running command" in r["error"]


def test_send_input_reaches_the_process_and_is_echoed():
    """Giro completo: si avvia un comando che LEGGE, gli si risponde, e la
    risposta deve (a) arrivargli e (b) comparire in console — lo stdin non
    passa dallo stdout del figlio, quindi senza eco l'utente vede la domanda
    e mai la propria risposta."""
    api = webgui.Api()
    child = "import sys; print('NAME?', flush=True); " \
            "n = sys.stdin.readline().strip(); print('HELLO ' + n, flush=True)"
    api._stream([sys.executable, "-u", "-c", child], key="t", display="probe")

    import time

    def _wait_for(needle: str) -> bool:
        # La riga "$ <comando>" contiene il sorgente della sonda, quindi
        # contiene ANCHE il testo che stiamo aspettando: senza saltarla il
        # test crede che il figlio abbia gia' risposto prima ancora di partire.
        for _ in range(100):
            if any(needle in e["line"] for e in list(api._log)
                   if not e["line"].startswith("$ ")):
                return True
            time.sleep(0.05)
        return False

    assert _wait_for("NAME?"), f"il figlio non ha mai chiesto: {list(api._log)}"
    assert api.send_input('{"text": "gray matter", "key": "t"}')["ok"] is True
    assert _wait_for("HELLO gray matter"), \
        f"la risposta non e' arrivata al processo: {list(api._log)}"
    assert any(e["line"].strip() == "> gray matter" for e in list(api._log)), \
        "la risposta non e' stata ri-mostrata in console"


def test_html_has_the_answer_row_wired_in_both_languages():
    """La riga di risposta non serve a niente se il pannello non la mostra o se
    esiste solo in una delle due lingue."""
    html = HTML.read_text(encoding="utf-8")
    for ident in ("stdin-bar", "stdin-input", "stdin-label", "btn-send"):
        assert f'id="{ident}"' in html, f"manca l'elemento {ident}"
    assert "send_input" in html, "il pannello non chiama mai send_input"
    for key in ("btn_send", "stdin_label", "stdin_hint"):
        assert html.count(key + ":") >= 2, f"'{key}' non e' tradotto in IT e EN"
