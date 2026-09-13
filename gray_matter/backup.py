"""Daily backup of the suite's memory: one folder per day, one subfolder per tool.

    <suite>/backups/gm-graph-backup_2026-09-13/
        gray-matter/  bridges.db
        neuron/       graph_*.db  _cross_links.json
        neurag/       knowledge.db  config.json

Sources come from `paths.data_paths()` — the inventory the uninstaller reads —
so a store added there is backed up here without a second list. SQLite files
go through the backup API over a `mode=ro` connection, the one sanctioned way
to open a graph another process has locked (WAL folded into the copy, the live
WAL untouched — see neuron/db.py:connect_read_only); everything else is a plain
copy. The newest KEEP days survive; the oldest folder goes when a new one lands.

Two guarantees against a process that dies mid-copy. Nothing is ever written
into a day folder directly: the whole day is built in `<folder>.tmp` and
renamed into place at the end, and each SQLite file is itself written to
`<file>.tmp` and replaced — so a folder that exists is complete, and a kill
leaves only `.tmp` leftovers that the next run sweeps. And `run()` holds
`_LOCK` for the whole copy: the daemon's shutdown calls `wait_idle()` before
`os._exit`, so a graceful `stop` does not cut a copy in half.

Neuron keeps its own `_backups/` next to the graphs (standalone contract, I2).
This is the suite-level copy: one place, same dates, all three tools.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from gray_matter import paths as _paths

KEEP = int(os.environ.get("GM_BACKUP_KEEP", "7") or 0)
PREFIX = "gm-graph-backup_"
_LOCK = threading.Lock()   # held while a copy is in flight (see wait_idle)


def wait_idle(timeout: float = 120.0) -> bool:
    """Block until no copy is in flight. False if one still is after `timeout`."""
    if not _LOCK.acquire(timeout=timeout):
        return False
    _LOCK.release()
    return True


def sources() -> dict[str, list[Path]]:
    """tool -> files to copy. Missing files are skipped at copy time."""
    d = _paths.data_paths()
    graphs = Path(d["neuron_graphs"])
    return {
        "gray-matter": [Path(d["gm_bridges"])],
        "neuron": sorted(p for p in graphs.glob("*") if p.suffix in (".db", ".json"))
                  if graphs.is_dir() else [],
        "neurag": [Path(d["neurag_db"]), Path(d["neurag_config"])],
    }


def _copy(src: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src.suffix != ".db":
        shutil.copy2(src, dst)
        return
    ro = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        out = sqlite3.connect(f"{dst}.tmp")
        try:
            ro.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")   # one self-contained file
        finally:
            out.close()
    finally:
        ro.close()
    os.replace(f"{dst}.tmp", dst)


def run(day: str | None = None, keep: int = KEEP, force: bool = False) -> tuple[Path | None, list[str]]:
    """Write the day's folder, prune to `keep`. (folder, errors); folder None = nothing done.

    Idempotent per day: a second call the same day is a no-op unless `force`,
    which replaces the day's folder with a fresh copy (the CLI's "backup now").
    """
    if keep <= 0:
        return None, []
    with _LOCK:
        return _run_locked(day, keep, force)


def _run_locked(day: str | None, keep: int, force: bool) -> tuple[Path | None, list[str]]:
    root = _paths.backups_dir()
    folder = root / f"{PREFIX}{day or time.strftime('%Y-%m-%d')}"
    if folder.exists() and not force:
        return None, []
    root.mkdir(parents=True, exist_ok=True)
    for stale in root.glob(f"{PREFIX}*.tmp"):        # a previous run died mid-copy
        shutil.rmtree(stale, ignore_errors=True)
    for stale in root.glob(f"{PREFIX}*.old"):        # ... or mid-swap (force)
        shutil.rmtree(stale, ignore_errors=True)
    tmp = Path(f"{folder}.tmp")
    tmp.mkdir()
    errors = []
    for tool, files in sources().items():
        for f in files:
            if not f.is_file():
                continue
            try:
                _copy(f, tmp / tool)
            except Exception as exc:  # noqa: BLE001 — one bad file must not lose the others
                errors.append(f"{tool}/{f.name}: {exc}")
    # Swap, never delete-then-write: a kill in between leaves the old copy as
    # `.old` and the new one as `.tmp` — either is recoverable, nothing is gone.
    old = Path(f"{folder}.old")
    if folder.exists():
        folder.rename(old)
    tmp.rename(folder)
    shutil.rmtree(old, ignore_errors=True)
    days = sorted(p for p in root.glob(f"{PREFIX}????-??-??") if p.is_dir())
    for dead in days[:-keep]:
        shutil.rmtree(dead, ignore_errors=True)
    return folder, errors
