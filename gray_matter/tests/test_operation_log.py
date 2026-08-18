"""An operation that kills the window watching it must still leave a record.

`install.ps1` calls `Stop-VenvProcesses`, which terminates every process
started from Gray Matter's venv so pip can replace the files they hold. The
control center is one of those processes — it runs from
`…\.venv\Scripts\pythonw.exe`. So pressing "Ripara" closes the very window that
was showing the progress, and the user is left not knowing whether the install
started, finished, or died.

The child survives (killing a parent does not kill children on Windows), so the
installer keeps running and keeps writing. What was missing was somewhere for
it to write that outlives the reader.
"""
import json
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from gray_matter.webgui import Api  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    import gray_matter.gme as gme
    monkeypatch.setattr(gme, "gme_root", lambda: tmp_path)
    return Api()


def _wait(api, key, timeout=30):
    for _ in range(int(timeout * 20)):
        if key not in api._running:
            return
        time.sleep(0.05)
    raise AssertionError("comando mai terminato")


def test_a_streamed_operation_leaves_its_output_on_disk(api):
    argv = [sys.executable, "-c", "print('riga uno'); print('riga due')"]
    api._stream(argv, key="gray-matter:repair", display="repair", to_log=True)
    _wait(api, "gray-matter:repair")

    res = api.operation_log(json.dumps({"key": "gray-matter:repair"}))
    assert res["found"] and res["running"] is False
    assert res["exit"] == 0
    assert any("riga uno" in l for l in res["tail"])


def test_a_failure_is_recorded_with_its_exit_code(api):
    argv = [sys.executable, "-c", "import sys; print('rotto'); sys.exit(3)"]
    api._stream(argv, key="k", display="x", to_log=True)
    _wait(api, "k")
    res = api.operation_log(json.dumps({"key": "k"}))
    assert res["exit"] == 3 and res["running"] is False


def test_a_log_without_a_terminator_reads_as_still_running(api):
    """Il caso vero: il control center è stato ucciso a metà. Il log c'è, il
    terminatore no — ed è esattamente ciò che si deve poter distinguere."""
    p = Api._op_log("gray-matter:repair")
    p.write_text("$ install.ps1 -Force\nStopping 4 processes...\n", encoding="utf-8")
    res = api.operation_log(json.dumps({"key": "gray-matter:repair"}))
    assert res["found"] and res["running"] is True and res["exit"] is None
    assert any("Stopping" in l for l in res["tail"])


def test_nothing_to_report_is_not_an_error(api):
    res = api.operation_log(json.dumps({"key": "mai-lanciato"}))
    assert res["ok"] is True and res["found"] is False


def test_the_key_cannot_escape_the_log_directory(api, tmp_path):
    """`key` arriva dalla richiesta: senza sanificazione uno scope inventato
    scriverebbe fuori dalla cartella dei log."""
    logs = (tmp_path / "logs").resolve()
    for key in ("../../evil:name", "..", "a/b\\c", "C:/Windows/System32/x"):
        p = Api._op_log(key).resolve()
        # L'invariante è "non esce", non l'estetica del nome: `..` DENTRO un
        # nome di file è inerte, `..` come componente di percorso no.
        assert p.parent == logs, f"{key!r} è uscito in {p}"


def test_a_log_that_cannot_be_opened_does_not_stop_the_command(api, monkeypatch):
    """Il log è una rete di sicurezza: se non si apre, l'operazione va avanti."""
    monkeypatch.setattr(Api, "_op_log", staticmethod(lambda key: pathlib.Path("/")))
    api._stream([sys.executable, "-c", "print('ok')"], key="z", display="z", to_log=True)
    _wait(api, "z")
    assert any("ok" in e["line"] for e in api.poll_log()["lines"])


def test_streaming_without_to_log_writes_no_file(api):
    api._stream([sys.executable, "-c", "print('x')"], key="q", display="q")
    _wait(api, "q")
    assert api.operation_log(json.dumps({"key": "q"}))["found"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
