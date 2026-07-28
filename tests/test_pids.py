"""Registro dei PID: la metà scrivente che per mesi non è mai esistita."""

import json
import os
import subprocess
import sys

import pytest

from gray_matter import paths, pids


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """GM_HOME in tmp: il registro dei PID è uno stato REALE della macchina,
    non lo si sporca in un test."""
    monkeypatch.setenv("GM_HOME", str(tmp_path / "gmhome"))


def test_the_file_nobody_used_to_write_now_gets_written():
    """Il bug di fondo: `pids.json` era letto da executor, cancellato
    dall'uninstall e nominato in paths.py — ma NESSUNO lo scriveva. Quindi
    `orphan_pids` era sempre vuoto, il reap non mieteva mai nulla, e i processi
    si accumulavano a ogni riavvio di un client."""
    assert not paths.pids_path().exists()
    pids.record_self("test")
    assert paths.pids_path().exists(), "record_self non ha scritto il registro"
    entries = json.loads(paths.pids_path().read_text(encoding="utf-8"))
    assert [e["pid"] for e in entries] == [os.getpid()]
    assert entries[0]["role"] == "test"
    assert entries[0]["ppid"] == os.getppid()


def test_recording_twice_does_not_duplicate():
    pids.record_self("a")
    pids.record_self("b")
    assert len(pids.tracked()) == 1


def test_dead_entries_are_pruned_on_read():
    """Un registro che accumula fantasmi è peggio di nessun registro: farebbe
    sparire gli orfani veri in mezzo al rumore."""
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    pids._write([
        {"pid": dead.pid, "ppid": os.getpid(), "role": "ghost", "started": 0},
        {"pid": os.getpid(), "ppid": os.getppid(), "role": "me", "started": 0},
    ])
    live = pids.tracked()
    assert [e["role"] for e in live] == ["me"]
    # e la potatura è stata scritta su disco, non solo restituita
    assert len(json.loads(paths.pids_path().read_text(encoding="utf-8"))) == 1


def test_an_orphan_is_a_live_process_whose_parent_is_gone():
    """La definizione che conta per l'utente: il client AI si è chiuso ma il
    server è rimasto attaccato allo store. Prima si contava come orfano
    QUALSIASI pid vivo — che avrebbe mietuto anche i server in uso.

    Serve un processo VERO e diverso da questo: `orphans()` esclude apposta il
    processo corrente (`reap` non deve mai suicidarsi), quindi usare os.getpid()
    qui verificherebbe l'esclusione, non la rilevazione.
    """
    dead_parent = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_parent.wait()
    survivor = subprocess.Popen([sys.executable, "-c",
                                 "import time; time.sleep(60)"])
    try:
        pids._write([
            # vivo, ma il genitore non c'è più -> orfano
            {"pid": survivor.pid, "ppid": dead_parent.pid,
             "role": "orphan", "started": 0},
        ])
        assert [e["role"] for e in pids.orphans()] == ["orphan"]
    finally:
        survivor.kill()
        survivor.wait()


def test_a_process_serving_a_live_parent_is_not_an_orphan():
    """Il caso che NON va toccato: 18 dei 24 processi trovati sulla macchina
    stavano servendo client vivi. Mieterli sarebbe stato un piede nella porta."""
    pids._write([
        {"pid": os.getpid(), "ppid": os.getppid(), "role": "serving", "started": 0},
    ])
    assert pids.orphans() == []


def test_current_process_is_never_its_own_orphan():
    pids.record_self("me")
    assert os.getpid() not in [e["pid"] for e in pids.orphans()]


def test_forget_removes_only_the_named_process():
    pids._write([
        {"pid": os.getpid(), "ppid": os.getppid(), "role": "keep", "started": 0},
        {"pid": 999999, "ppid": os.getppid(), "role": "drop", "started": 0},
    ])
    pids.forget(999999)
    assert [e["role"] for e in pids._read()] == ["keep"]


def test_a_corrupt_registry_does_not_take_the_suite_down():
    """Il registro è un aiuto diagnostico: se è illeggibile la suite deve
    funzionare lo stesso, non rifiutarsi di partire."""
    paths.pids_path().parent.mkdir(parents=True, exist_ok=True)
    paths.pids_path().write_text("{ questo non e' json", encoding="utf-8")
    assert pids.tracked() == []
    assert pids.orphans() == []
    pids.record_self("recovered")          # e si ripara scrivendoci sopra
    assert [e["role"] for e in pids.tracked()] == ["recovered"]


@pytest.mark.parametrize("legacy", [
    [1, 2, 3],                              # vecchia lista di soli interi
    {"pids": [1, 2, 3]},                    # vecchio dict
])
def test_legacy_formats_are_tolerated(legacy):
    """Formati che la spec aveva ipotizzato: leggerli non deve esplodere."""
    paths.pids_path().parent.mkdir(parents=True, exist_ok=True)
    paths.pids_path().write_text(json.dumps(legacy), encoding="utf-8")
    pids.tracked()                          # non solleva


def test_executor_sees_the_registry():
    """Il consumatore vero: `detect_state()` alimenta il passo di reap
    dell'installer. Se non legge il registro, il reap resta decorativo."""
    executor = pytest.importorskip("gray_matter.executor")
    pids.record_self("visible")
    assert os.getpid() in executor._tracked_pids()
