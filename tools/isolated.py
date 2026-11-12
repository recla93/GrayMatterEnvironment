"""An isolated instance of the INSTALLED suite: a copy of the real memory, its own
daemon, port and IPC channel. Everything that writes (store_turn, the "saved: yes"
path, a real OpenCode turn, the A/B) runs here, never on the real memory.

    python tools/isolated.py up                 # fresh copy + daemon
    python tools/isolated.py run -- python tools/smoke.py
    python tools/isolated.py status
    python tools/isolated.py check              # store through it: copy yes, real memory no
    python tools/isolated.py down [--purge]     # stop; --purge deletes the copy

Same code (the real venv), other data: GM_HOME, NS_GRAPHS_DIR and NEURAG_HOME
point at the copy (all three: Neuron and NeuRAG started from the real venv would
find the real suite on their own), GM_PORT moves the port, GM_INSTANCE the
Windows pipe. The real suite is only READ, through the SQLite backup API over a
mode=ro connection (as gray_matter/backup.py does).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
SUITE = Path(os.environ.get("GM_SUITE") or HOME / "GrayMatterEnvironment")
PY = SUITE / "graymatter" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
ROOT = Path(os.environ.get("GM_ISOLATED_DIR") or HOME / "GrayMatterEnvironment-isolated")
PORT = int(os.environ.get("GM_ISOLATED_PORT") or 9890)
MARKER = ".gm-isolated"          # a folder without it is never deleted
SIDECARS = ("-wal", "-shm", "-tshm", "-journal")
# Variables that would point the copy back at real data or at the cloud.
DROP = ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "GM_TURSO_DATABASE_URL", "GM_TURSO_AUTH_TOKEN",
        "GRAY_MATTER_BRIDGES", "GM_ENV_FILE", "NEURON_ENV_FILE")


def env() -> dict:
    e = {k: v for k, v in os.environ.items() if k not in DROP}
    e.update(GM_HOME=str(ROOT), NS_GRAPHS_DIR=str(ROOT / "neuron" / "graphs"),
             NEURAG_HOME=str(ROOT / "neurag"), GM_PORT=str(PORT), GM_INSTANCE="isolated",
             GM_GUI_NOBROWSER="1", GM_SUITE=str(SUITE))
    return e


def gm(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), "-I", "-m", "gray_matter.cli", *args], env=env(),
                          capture_output=True, text=True, timeout=timeout)


def running() -> bool:
    return gm("ping").returncode == 0


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix != ".db":
        shutil.copy2(src, dst)
        return
    ro = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        out = sqlite3.connect(dst)
        try:
            ro.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")
        finally:
            out.close()
    finally:
        ro.close()


def snapshot() -> list[str]:
    """Copy the real memory into ROOT. Returns the copied paths, relative."""
    pairs = []
    for sub in ("graymatter", "neurag"):
        for name in ("bridges.db", "config.json", "knowledge.db"):
            if (SUITE / sub / name).is_file():
                pairs.append(Path(sub) / name)
    graphs = SUITE / "neuron" / "graphs"
    pairs += [Path("neuron/graphs") / p.name for p in sorted(graphs.iterdir())
              if p.is_file() and not p.name.endswith(SIDECARS)]
    if (SUITE / "neuron" / ".env").is_file():   # embedding model: the copy must embed alike
        pairs.append(Path("neuron/.env"))
    for rel in pairs:
        _copy(SUITE / rel, ROOT / rel)
    return [str(p) for p in pairs]


def purge() -> None:
    if ROOT.exists():
        if not (ROOT / MARKER).exists():
            sys.exit(f"{ROOT} exists without {MARKER}: not mine, not deleting it")
        # A stopped daemon and its workers let go of daemon.log and the graphs
        # a few seconds after `stop` returns (Windows: open files cannot go).
        for _ in range(30):
            try:
                shutil.rmtree(ROOT)
                return
            except PermissionError:
                time.sleep(1)
        shutil.rmtree(ROOT)


def up() -> int:
    if not PY.exists():
        sys.exit(f"suite python missing: {PY}")
    if running():
        gm("stop")
        time.sleep(1)
    purge()
    ROOT.mkdir(parents=True)
    (ROOT / MARKER).write_text(json.dumps({"source": str(SUITE), "port": PORT,
                                           "created": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    copied = snapshot()
    r = gm("start", timeout=120)
    ok = running()
    print(f"copied {len(copied)} files from {SUITE} to {ROOT}")
    print(f"daemon {'up' if ok else 'NOT up'} on port {PORT}: {(r.stdout + r.stderr).strip()}")
    if not ok:
        log = ROOT / "graymatter" / "logs" / "daemon.log"
        print(log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.exists() else "no daemon.log")
    return 0 if ok else 1


def status() -> int:
    s = gm("status") if running() else None
    print(json.dumps({"root": str(ROOT), "exists": ROOT.exists(), "port": PORT,
                      "running": s is not None,
                      "status": (s.stdout.strip()[:600] if s else "")}, indent=2))
    return 0


def _marker_rows(graphs: Path, mark: str) -> int:
    n = 0
    for db in graphs.glob("graph_*.db"):
        c = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            n += c.execute("SELECT count(*) FROM facts WHERE text LIKE ?", (f"%{mark}%",)).fetchone()[0]
        finally:
            c.close()
    return n


def check() -> int:
    """Proof of isolation: a fact stored through the instance lands in the copy
    and NOT in the real memory (both read with mode=ro)."""
    if not running():
        sys.exit("isolated instance not running: python tools/isolated.py up")
    mark = "isocheck" + os.urandom(5).hex()
    fact = {"kind": "fact", "text": f"Isolation probe {mark}.", "concepts": ["isolation probe"]}
    gm("gm-neuron", "store_turn", json.dumps({"facts": [fact]}), timeout=120)
    copy, real = _marker_rows(ROOT / "neuron" / "graphs", mark), _marker_rows(SUITE / "neuron" / "graphs", mark)
    ok = copy >= 1 and real == 0
    print(f"{'PASS' if ok else 'FAIL'}  probe fact: {copy} in the copy, {real} in the real memory")
    return 0 if ok else 1


def down(purge_data: bool) -> int:
    if running():
        print(gm("stop").stdout.strip())
    if purge_data:
        time.sleep(1)
        purge()
        print(f"removed {ROOT}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up")
    sub.add_parser("status")
    sub.add_parser("check")
    d = sub.add_parser("down")
    d.add_argument("--purge", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    if a.cmd == "up":
        return up()
    if a.cmd == "status":
        return status()
    if a.cmd == "check":
        return check()
    if a.cmd == "down":
        return down(a.purge)
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        ap.error("run needs a command")
    if not running():
        sys.exit("isolated instance not running: python tools/isolated.py up")
    return subprocess.run(cmd, env=env()).returncode


if __name__ == "__main__":
    sys.exit(main())
