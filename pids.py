"""Registro dei processi vivi della suite — chi c'è, e chi è rimasto indietro.

Perché esiste (INSTALLER-UX §7). `pids.json` era già previsto dalla spec, già
letto da ``executor._tracked_pids()``, già cancellato dall'uninstall e già
nominato in ``paths.py``. Mancava solo la metà che lo SCRIVE: nessuno lo
creava, quindi ``detect_state()["orphan_pids"]`` era sempre vuoto, il passo di
reap in ``execute_install()`` non mieteva mai niente e i processi si
accumulavano a ogni riavvio di un client (i "4 Neuron" del 2026-07-18).

Auto-registrazione, non registrazione dallo spawner: su Windows il
``python.exe`` di un venv è il *redirector* di CPython, che lancia
l'interprete vero come figlio e aspetta. Il PID che torna da ``Popen`` è
quello dello stub da 4 MB, non quello del processo che tiene il DB aperto.
Ogni processo scrive il PROPRIO ``os.getpid()``: è l'unico che conosce.

Formato (lista, non dict: si legge anche a occhio):
    [{"pid": 123, "ppid": 99, "role": "daemon", "started": 1785…}, …]
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import time

from gray_matter import paths

__all__ = ["record_self", "forget", "tracked", "orphans", "alive"]

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def alive(pid: int) -> bool:
    """Il processo `pid` esiste ancora?"""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                               capture_output=True, text=True, timeout=10,
                               creationflags=_NO_WINDOW)
            # `tasklist` senza match stampa comunque un banner: cercare il PID
            # come parola è l'unico modo per non leggere "INFO:" come un sì.
            return str(pid) in (r.stdout or "")
        os.kill(pid, 0)          # segnale 0 = solo test di esistenza
        return True
    except Exception:            # noqa: BLE001 — tasklist assente, permessi, …
        return False


def _read() -> "list[dict]":
    try:
        data = json.loads(paths.pids_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):           # tollera il vecchio {"pids": [...]}
        data = data.get("pids", [])
    out = []
    for e in data if isinstance(data, list) else []:
        if isinstance(e, int):           # tollera la lista di soli interi
            e = {"pid": e, "ppid": 0, "role": "?", "started": 0}
        if isinstance(e, dict) and isinstance(e.get("pid"), int):
            out.append(e)
    return out


def _write(entries: "list[dict]") -> None:
    p = paths.pids_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
        os.replace(tmp, p)               # atomico: mai un pids.json mezzo scritto
    except OSError:
        pass                             # il registro è un aiuto, non un vincolo


def record_self(role: str) -> None:
    """Registra QUESTO processo e programma la cancellazione all'uscita.

    Idempotente: richiamarla non duplica la riga. `atexit` copre l'uscita
    pulita; per quella sporca (kill -9, crash) ci pensa la potatura in
    :func:`tracked`, che scarta le voci di processi morti.
    """
    me = os.getpid()
    entries = [e for e in _read() if e["pid"] != me and alive(e["pid"])]
    entries.append({"pid": me, "ppid": os.getppid(), "role": role,
                    "started": int(time.time())})
    _write(entries)
    atexit.register(forget, me)


def forget(pid: "int | None" = None) -> None:
    """Toglie un processo dal registro (default: questo)."""
    target = os.getpid() if pid is None else pid
    entries = _read()
    kept = [e for e in entries if e["pid"] != target]
    if len(kept) != len(entries):
        _write(kept)


def tracked() -> "list[dict]":
    """Le voci ancora vive. Pota le morte dal file mentre passa: un registro
    che accumula fantasmi è peggio di nessun registro."""
    entries = _read()
    live = [e for e in entries if alive(e["pid"])]
    if len(live) != len(entries):
        _write(live)
    return live


def orphans() -> "list[dict]":
    """Processi vivi il cui genitore non c'è più.

    È la definizione che conta per l'utente: il client AI si è chiuso o è stato
    riavviato, ma il server che aveva lanciato è rimasto attaccato allo stesso
    store — più writer sullo stesso DB è esattamente il rischio di clobber che
    L1/L2 descrivono. Il processo CORRENTE non è mai un orfano di se stesso.
    """
    me = os.getpid()
    return [e for e in tracked()
            if e["pid"] != me and e.get("ppid", 0) > 0 and not alive(e["ppid"])]
