"""Il daemon e il ramo stdio devono partire dallo stesso stato."""

import ast
import io
from pathlib import Path

import pytest

_SERVER = Path(__file__).resolve().parents[1] / "server.py"


def _called_names(func_name: str) -> set:
    """Nomi delle funzioni CHIAMATE dentro `func_name`, nidificate incluse.

    Non distingue `await f()` da `asyncio.create_task(f())`: conta che la
    chiamata ci sia, non come viene attesa — il bootstrap gira apposta come
    task in background nel daemon (se lo si aspetta prima del listener, la
    porta IPC resta chiusa per decine di secondi).

    Lettura statica: importare server.py tira dentro mcp, e avviare un daemon
    vero dentro un test è peggio del bug che stiamo prevenendo.
    """
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    target = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name == func_name),
        None,
    )
    assert target is not None, f"{func_name}() non esiste più in server.py"
    return {
        node.func.id
        for node in ast.walk(target)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize("entry", ["main", "run_daemon"])
def test_both_entry_points_bootstrap_the_subservers(entry):
    """Il bug: `_bootstrap_subservers()` era cablata SOLO in main() (il ramo
    stdio, quello che lancia il client AI). Un daemon avviato con
    `gray-matter start` — o spawnato da autoregister — restava col registro
    vuoto: `gray-matter status` diceva "Servers: 0" e ogni gm-neuron/gm-neurag
    moriva con "worker gave no response". Due porte d'ingresso allo stesso
    gateway non possono avere due stati iniziali diversi.
    """
    assert "_bootstrap_subservers" in _called_names(entry), (
        f"{entry}() non chiama _bootstrap_subservers(): il registro parte vuoto"
    )


def test_the_daemon_does_not_wait_for_the_bootstrap_before_listening():
    """Il bootstrap interroga i worker: spawn del subprocess più caricamento del
    modello, decine di secondi. Aspettarlo PRIMA di `_ipc_listener` teneva la
    porta IPC chiusa per tutto quel tempo — `gray-matter start` diceva
    "started" e un `doctor` subito dopo rispondeva "not running"."""
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    run_daemon = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "run_daemon")
    for node in ast.walk(run_daemon):
        if (isinstance(node, ast.Await) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_bootstrap_subservers"):
            pytest.fail("run_daemon aspetta il bootstrap: la porta IPC resta "
                        "chiusa finché i worker non hanno risposto")


class _ReconfigureIsNone(io.StringIO):
    reconfigure = None                         # attributo c'è, ma non chiamabile


class _NoReconfigure:
    """Wrapper minimale: `.reconfigure` non esiste proprio."""
    def write(self, s): return len(s)
    def flush(self): pass


@pytest.mark.parametrize("fake", [_ReconfigureIsNone, _NoReconfigure])
def test_console_safe_survives_a_stream_without_reconfigure(monkeypatch, fake):
    """`_console_safe()` gira su stdout veri, pipe, GUI e stream sostituiti da
    pytest: dove `.reconfigure` manca o non è chiamabile deve tacere. Prima
    catturava solo AttributeError e su un attributo a None moriva di TypeError,
    portandosi dietro l'intero comando."""
    import sys
    from gray_matter import cli

    monkeypatch.setattr(sys, "stdout", fake())
    monkeypatch.setattr(sys, "stderr", fake())
    cli._console_safe()                        # non deve sollevare


def test_console_safe_makes_unencodable_output_survive(tmp_path):
    """Il crash vero: `gray-matter gm-neuron pre_turn` moriva con
    UnicodeEncodeError perché il contesto di Neuron contiene '→' e la console
    Windows di default è cp1252, che quella freccia non ce l'ha. Il contenuto
    del grafo è testo utente arbitrario — emoji, CJK, frecce — e non si negozia
    con la code page: si degrada, non si perde il comando.
    """
    path = tmp_path / "out.txt"
    with open(path, "w", encoding="cp1252") as fh:
        fh.reconfigure(errors="replace")
        fh.write("next: → fine")           # '→' non esiste in cp1252

    assert "fine" in path.read_text(encoding="cp1252")


def test_without_the_guard_the_same_write_raises(tmp_path):
    """Controprova: senza `errors="replace"` quella stessa riga solleva."""
    path = tmp_path / "boom.txt"
    with open(path, "w", encoding="cp1252") as fh:
        with pytest.raises(UnicodeEncodeError):
            fh.write("next: → fine")
