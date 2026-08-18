"""Prima di installare, guarda cosa c'e'.

L'installer sovrascriveva e sperava: nessun controllo su altre installazioni,
su versioni disallineate fra i tre pacchetti, o su client che puntano a un
interprete morto. Quest'ultimo e' quello che ha prodotto
`spawn ...python.exe ENOENT` su una macchina vera — e sarebbe stato visibile
prima dell'utente.

`scan()` e' puro: qui si verifica che VEDA, non che aggiusti.
"""
from __future__ import annotations

import importlib
import json
import os

import pytest


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # APPDATA serve quanto gli altri: senza, i path di Claude Desktop e VS Code
    # restano quelli VERI e il test legge la macchina su cui gira.
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("GM_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    from gray_matter import clients, paths, preflight
    importlib.reload(paths)
    importlib.reload(clients)
    importlib.reload(preflight)
    return tmp_path, preflight


def _fake_venv(root, versions: dict):
    """Un venv finto il cui python stampa le versioni che gli diciamo."""
    scripts = root / ("Scripts" if os.name == "nt" else "bin")
    scripts.mkdir(parents=True, exist_ok=True)
    py = scripts / ("python.exe" if os.name == "nt" else "python")
    py.write_text("", encoding="utf-8")     # basta che esista: _versions e' mockata
    return py


def test_a_clean_machine_has_nothing_to_say(machine):
    _, preflight = machine
    st = preflight.scan()
    assert st["ok"] is True
    assert st["venvs"] == []
    assert preflight.report(st) == ""


def test_two_live_venvs_are_reported(machine, monkeypatch):
    tmp, preflight = machine
    _fake_venv(tmp / "GrayMatterEnvironment" / "graymatter" / ".venv", {})
    _fake_venv(tmp / "gray-matter" / ".venv", {})
    monkeypatch.setattr(preflight, "_versions",
                        lambda p: {"gray-matter": "1.4.0", "neuron": "6.4.0", "neurag": "1.3.1"})
    monkeypatch.setattr(preflight, "source_versions",
                        lambda: {"gray-matter": "1.4.0", "neuron": "6.4.0", "neurag": "1.3.1"})
    st = preflight.scan()
    kinds = {p["kind"] for p in st["problems"]}
    assert "multiple_venvs" in kinds, "due venv vivi e nessuno lo dice"


def test_version_skew_between_venv_and_source(machine, monkeypatch):
    tmp, preflight = machine
    _fake_venv(tmp / "GrayMatterEnvironment" / "graymatter" / ".venv", {})
    monkeypatch.setattr(preflight, "_versions", lambda p: {"gray-matter": "1.1.2"})
    monkeypatch.setattr(preflight, "source_versions", lambda: {"gray-matter": "1.4.0"})
    st = preflight.scan()
    skew = [p for p in st["problems"] if p["kind"] == "version_skew"]
    assert skew and "1.1.2" in skew[0]["detail"] and "1.4.0" in skew[0]["detail"]


def test_an_incomplete_suite_is_named(machine, monkeypatch):
    """GM installato e NeuRAG no: il caso segnalato dal campo."""
    tmp, preflight = machine
    _fake_venv(tmp / "GrayMatterEnvironment" / "graymatter" / ".venv", {})
    monkeypatch.setattr(preflight, "_versions",
                        lambda p: {"gray-matter": "1.4.0", "neuron": "6.4.0"})
    monkeypatch.setattr(preflight, "source_versions",
                        lambda: {"gray-matter": "1.4.0", "neuron": "6.4.0", "neurag": "1.3.1"})
    st = preflight.scan()
    inc = [p for p in st["problems"] if p["kind"] == "incomplete_suite"]
    assert inc and "neurag" in inc[0]["detail"]


def test_a_dead_client_interpreter_is_caught(machine, monkeypatch):
    """IL controllo che avrebbe preso l'ENOENT prima dell'utente."""
    tmp, preflight = machine
    cfg = tmp / "home" / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    dead = str(tmp / "sparito" / "python.exe")
    cfg.write_text(json.dumps(
        {"mcpServers": {"gray-matter": {"command": dead, "args": ["-m", "gray_matter.server"]}}}),
        encoding="utf-8")
    monkeypatch.setattr(preflight, "source_versions", lambda: {})
    st = preflight.scan()
    dead_p = [p for p in st["problems"] if p["kind"] == "dead_client_interpreter"]
    assert dead_p, "un client punta al vuoto e nessuno lo dice"
    assert "python.exe" in dead_p[0]["detail"]


def test_report_stays_quiet_when_all_is_well(machine, monkeypatch):
    tmp, preflight = machine
    _fake_venv(tmp / "GrayMatterEnvironment" / "graymatter" / ".venv", {})
    monkeypatch.setattr(preflight, "_versions", lambda p: {"gray-matter": "1.4.0"})
    monkeypatch.setattr(preflight, "source_versions", lambda: {"gray-matter": "1.4.0"})
    st = preflight.scan()
    assert st["ok"], st["problems"]
    assert "OK" in preflight.report(st)


def test_scan_writes_nothing(machine):
    """E' un controllo, non un'installazione: non deve materializzare cartelle."""
    tmp, preflight = machine
    before = sorted(p.name for p in tmp.iterdir())
    preflight.scan()
    assert sorted(p.name for p in tmp.iterdir()) == before
