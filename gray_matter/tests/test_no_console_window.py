"""Nessun processo di background deve far comparire una finestra CMD."""

import os
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="flag solo Windows")

# Il figlio si guarda allo specchio: ha una console? è VISIBILE? Quella
# finestra è esattamente la "CMD vuota" che l'utente vede comparire.
_PROBE = textwrap.dedent("""
    import ctypes, sys
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    visible = bool(ctypes.windll.user32.IsWindowVisible(hwnd)) if hwnd else False
    sys.stdout.write("VISIBLE" if visible else "HIDDEN")
""")


def _code_of(obj) -> str:
    """Sorgente SENZA commenti: il nome di un flag citato nel commento che ne
    spiega l'assenza non deve far fallire (o passare) un test sul codice."""
    import inspect
    import io
    import tokenize

    src = inspect.getsource(obj)
    lines = src.splitlines()
    # taglia OGNI riga alla colonna dove inizia il suo commento: il resto del
    # layout (e quindi `subprocess.CREATE_NO_WINDOW` attaccato) resta intatto.
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col]
    return "\n".join(lines)


def _spawn_and_ask(flags: int, tmp_path) -> str:
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    out = tmp_path / "out.txt"
    with open(out, "w", encoding="utf-8") as fh:
        subprocess.Popen(
            [sys.executable, "-u", str(probe)],
            creationflags=flags, stdin=subprocess.DEVNULL,
            stdout=fh, stderr=subprocess.STDOUT,
        ).wait(timeout=60)
    return out.read_text(encoding="utf-8").strip()


def test_daemon_spawn_flags_do_not_create_a_visible_console(tmp_path):
    """Il bug: `_spawn_gray_matter` usava CREATE_NO_WINDOW | DETACHED_PROCESS.
    Windows IGNORA CREATE_NO_WINDOW quando c'è DETACHED_PROCESS, e il figlio
    staccato si alloca una console propria → finestra CMD vuota a ogni
    `gray-matter start`. Qui si misurano i flag VERI usati dal codice."""
    server = pytest.importorskip("gray_matter.server")
    assert "DETACHED_PROCESS" not in _code_of(server._spawn_gray_matter), (
        "DETACHED_PROCESS fa ignorare CREATE_NO_WINDOW: torna la finestra vuota"
    )

    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    assert _spawn_and_ask(flags, tmp_path) == "HIDDEN"


def _runner_has_a_visible_console() -> bool:
    """La controprova misura una finestra EREDITATA: se chi lancia i test non
    ha console propria (CI, servizio, agente, `pythonw`), il figlio staccato
    non ne fa comparire nessuna e l'asserzione fallisce per il posto in cui
    gira, non per il codice."""
    if os.name != "nt":
        return False
    import ctypes
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    return bool(hwnd) and bool(ctypes.windll.user32.IsWindowVisible(hwnd))


@pytest.mark.skipif(not _runner_has_a_visible_console(),
                    reason="controprova valida solo da una console visibile")
def test_detached_process_is_what_made_the_window_appear(tmp_path):
    """Controprova: la combinazione vecchia produce davvero la finestra. Senza
    questa, il test sopra potrebbe passare per il motivo sbagliato."""
    old = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    assert _spawn_and_ask(old, tmp_path) == "VISIBLE"


def test_worker_spawn_has_no_window():
    """Anche i worker sono processi di background: stessa regola."""
    server = pytest.importorskip("gray_matter.server")
    import re

    src = _code_of(server)
    # ogni creationflags nel modulo deve essere "senza finestra". Si prende
    # tutta la riga: una forma come getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # e' corretta, ma un pattern che si ferma al primo identificatore vede solo
    # "getattr" e la boccia.
    for m in re.finditer(r"creationflags\s*=\s*([^\n]+)", src):
        expr = m.group(1).strip().rstrip(",")
        if expr in ("0", "creationflags"):
            continue
        assert "CREATE_NO_WINDOW" in expr, f"spawn senza CREATE_NO_WINDOW: {expr}"
        assert "DETACHED_PROCESS" not in expr, f"DETACHED_PROCESS rimasto: {expr}"
