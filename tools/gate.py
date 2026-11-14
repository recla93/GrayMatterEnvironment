"""The gate before a push: one command, exit 0 = push allowed.

    python tools/gate.py && git push
    python tools/gate.py --oc-turn        # plus a real OpenCode turn (~30 s, a model)
    python tools/gate.py --skip smoke     # a step left out is reported, never passed

Steps, each in its own process:
  deps          tools/deps.py --check: identical client twins, guidance only names the
                I/O contract, removed names do not come back (seconds; runs first)
  suite:<tool>  pytest of neuron, gray_matter, neurag, one process each (never together)
  bench         neuron/bench --mode message, against the newest saved result of the
                same set: recall and full not lower, noise and off-topic not higher
  smoke         a FRESH isolated instance (copy of the real memory), the whole smoke
                (writes included) and the isolation check; the instance is removed after

A new baseline is a decision, not a side effect: save it by hand into
neuron/bench/results/ when a change is meant to move the numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "neuron" / "bench" / "results"
# The suites' conftest drops these too; the gate must not even pass them on.
CLEAN = {k: v for k, v in os.environ.items()
         if k not in ("GM_HOME", "NS_GRAPHS_DIR", "NEURAG_HOME", "GM_PORT", "GM_INSTANCE")}
EPS = 1e-3
rows: list = []


def step(name: str, fn) -> None:
    t0 = time.monotonic()
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 — a crashing step is a failed step
        ok, detail = False, f"{type(e).__name__}: {e}"
    rows.append((name, ok, round(time.monotonic() - t0), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:20} {rows[-1][2]:>4}s  {detail}", flush=True)


def run(cmd: list, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO, env=CLEAN, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def deps():
    p = run([sys.executable, "tools/deps.py", "--check"], timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    return p.returncode == 0, ("; ".join(lines[:-1])[:400] or lines[-1]) if lines else p.stderr[-200:]


def suite(tool: str):
    def fn():
        p = run([sys.executable, "-m", "pytest", f"{tool}/tests", "-q", "-p", "no:cacheprovider"])
        tail = [ln for ln in p.stdout.splitlines() if ln.strip()][-1:] or [p.stderr[-200:]]
        return p.returncode == 0, tail[0]
    return fn


def baseline(version: int) -> "tuple[str, dict] | None":
    for f in sorted(RESULTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        d = json.loads(f.read_text(encoding="utf-8"))
        m = next((r for r in d.get("results", []) if r["mode"] == "message"), None)
        if d.get("set_version") == version and m:
            return f.name, m
    return None


def bench():
    p = run([sys.executable, "neuron/bench/run.py", "--mode", "message", "--json"])
    if p.returncode != 0:
        return False, p.stderr[-200:]
    now = json.loads(p.stdout)
    cur = now["results"][0]
    base = baseline(now["set_version"])
    if not base:
        return False, f"no saved result for set v{now['set_version']} in {RESULTS}"
    name, b = base
    worse = [k for k in ("recall", "full") if cur[k] < b[k] - EPS]
    worse += [k for k in ("noise", "off_topic") if cur[k] > b[k] + EPS]
    nums = " ".join(f"{k} {cur[k]}/{b[k]}" for k in ("recall", "full", "noise", "off_topic"))
    return not worse, (f"WORSE: {worse} | " if worse else "") + f"{nums} (now/{name})"


def smoke(oc_turn: bool):
    def fn():
        iso = [sys.executable, "tools/isolated.py"]
        up = run(iso + ["up"], timeout=300)
        if up.returncode != 0:
            return False, "isolated up: " + (up.stdout + up.stderr)[-200:]
        try:
            out = []
            for cmd in (["run", "--", sys.executable, "tools/smoke.py", "--json"], ["check"]):
                p = run(iso + cmd, timeout=600)
                out.append(p)
            if oc_turn:
                out.append(run(iso + ["run", "--", sys.executable, "tools/smoke.py", "--json", "--only", "oc-turn"],
                               timeout=600))
        finally:
            run(iso + ["down", "--purge"], timeout=120)
        smokes = [json.loads(p.stdout[p.stdout.find("{"):]) for p in out if "--json" in p.args]
        failed = [f"{r['group']}: {r['check']}: {r['detail']}" for s in smokes for r in s["results"]
                  if r["status"] == "FAIL"]
        total = sum(len(s["results"]) for s in smokes)
        check = out[1]
        if check.returncode != 0:
            failed.append(check.stdout.strip()[-160:])
        return not failed, (f"{total} checks + isolation ok" if not failed else "; ".join(failed)[:400])
    return fn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--oc-turn", action="store_true", help="add a real OpenCode turn to the smoke")
    ap.add_argument("--skip", default="", help="comma-separated: deps, suite, bench, smoke")
    a = ap.parse_args(argv)
    skip = {s for s in a.skip.split(",") if s}
    sys.stdout.reconfigure(encoding="utf-8")
    if "deps" not in skip:
        step("deps", deps)
    if "suite" not in skip:
        for tool in ("neuron", "gray_matter", "neurag"):
            step(f"suite:{tool}", suite(tool))
    if "bench" not in skip:
        step("bench", bench)
    if "smoke" not in skip:
        step("smoke (isolated)", smoke(a.oc_turn))
    failed = [r for r in rows if not r[1]]
    print(f"\ngate: {len(rows) - len(failed)}/{len(rows)} ok"
          + (f", skipped {sorted(skip)}" if skip else "")
          + (" — NO PUSH" if failed or skip else " — push allowed"))
    return 1 if failed or skip else 0


if __name__ == "__main__":
    sys.exit(main())
