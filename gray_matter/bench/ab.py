"""A/B counterfactual (PIANO fase 0, MISURA livello 2): the same OpenCode agent on
the same tasks, WITH the suite (hook + MCP, on an isolated copy of the real
memory) and WITHOUT it (the same config minus the memory plugin and MCP).

    python gray_matter/bench/ab.py                      # all tasks, both arms
    python gray_matter/bench/ab.py --only t01,c01 -v    # a pilot
    python gray_matter/bench/ab.py --report results/ab-2026-11-12.json

Per run: tokens (input, output, reasoning, cache read), tool calls split into
memory and exploration, wall time, correctness = share of the task's expected
words in the answer. Output: paired deltas (ON - OFF) with a 95% bootstrap
interval, memory tasks and control tasks apart.

Read-only on the repo: agent `plan`. The ON arm writes only into the isolated
copy (tools/isolated.py), which is removed at the end. Known limits of the
pilot: one run per task and arm; `opencode run` ends before the plugin's
end-of-turn reminder, so a save turn is not counted; facts the ON arm saves
during the run stay in the copy for the later tasks.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import isolated as ISO  # noqa: E402

HERE = Path(__file__).resolve().parent
TASKS = HERE / "ab_tasks.json"
OUT = HERE / "results"
MODEL = "opencode/big-pickle"
CLEAN = {k: v for k, v in os.environ.items()
         if k not in ("GM_HOME", "NS_GRAPHS_DIR", "NEURAG_HOME", "GM_PORT", "GM_INSTANCE", "XDG_CONFIG_HOME")}
# Memory tools reach the agent as MCP tools (`gray-matter_*`) or, in OpenCode's code
# mode, inside an `execute` call. A shell grep for "gray_matter" in the repo is exploration.
MEMORY = re.compile(r"pre_turn|store_turn|knowledge_query|knowledge_|get_context|switch_context|gray_matter_pulse", re.I)


# A provider out of quota: OpenCode's own free models ("provider.free-limit") and
# OpenRouter's daily cap ("provider.rate-limit ... free-models-per-day"), both 429.
QUOTA = re.compile(r"free-limit|rate-limit|Free usage limit|Rate limit exceeded", re.I)


def is_memory(name: str, args: dict) -> bool:
    return name.lower().startswith("gray") or (name == "execute" and bool(MEMORY.search(json.dumps(args))))


def opencode() -> str:
    oc = shutil.which("opencode")
    if not oc:
        sys.exit("opencode not on PATH")
    exe = Path(oc).parent / "node_modules/@opencode/cli/bin/opencode.exe"   # the npm shim survives a kill
    return str(exe) if exe.exists() else oc


def off_config() -> Path:
    """The real OpenCode config dir minus the memory: no neuron-handshake plugin, no MCP."""
    real = Path.home() / ".config" / "opencode"
    tmp = Path(tempfile.mkdtemp(prefix="ab-off-")) / "opencode"
    shutil.copytree(real, tmp, ignore=shutil.ignore_patterns("neuron-handshake*"))
    cfg = json.loads((tmp / "opencode.json").read_text(encoding="utf-8-sig"))
    cfg["plugin"] = [p for p in cfg.get("plugin", []) if "neuron-handshake" not in str(p)]
    cfg.pop("mcp", None)
    (tmp / "opencode.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return tmp.parent


def score(text: str, expect: list) -> float:
    t = text.lower()
    return sum(any(a.lower() in t for a in e.split("|")) for e in expect) / len(expect)


def run_one(oc: str, env: dict, prompt: str, timeout: int, cwd: Path = REPO) -> dict:
    import threading
    t0 = time.monotonic()
    p = subprocess.Popen([oc, "run", "--standalone", "--archived", "--agent", "plan", "--format", "json",
                          "--print-logs", "-m", MODEL, prompt], env=env, cwd=cwd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    chunks, failed = [], threading.Event()

    def drain_logs():
        # Plan agent + a provider error + the memory plugin's context hook (it awaits
        # the recall): OpenCode's own plan-mode reminder lands in the inbox after the
        # step failed, "Failed to drain Session", and `run` never exits (2026-11-12).
        for ln in p.stderr:
            if "Failed to drain Session" in ln or QUOTA.search(ln):
                failed.set()

    threads = [threading.Thread(target=lambda: chunks.extend(p.stdout), daemon=True),
               threading.Thread(target=drain_logs, daemon=True)]
    for th in threads:
        th.start()
    rc = None
    while rc is None:
        try:
            rc = p.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if failed.is_set() or time.monotonic() - t0 > timeout:
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"] if os.name == "nt"
                               else ["kill", "-9", str(p.pid)], capture_output=True)
                p.wait()
                rc = "provider-error" if failed.is_set() else "timeout"
    threads[0].join(5)
    out = "".join(chunks)
    if QUOTA.search(out):
        rc = "quota"
    r = {"secs": round(time.monotonic() - t0, 1), "rc": rc, "input": 0, "output": 0, "reasoning": 0,
         "cache_read": 0, "steps": 0, "tools_memory": 0, "tools_explore": 0, "tool_names": [], "text": ""}
    texts = []
    for ln in out.splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        part = e.get("part") or {}
        if part.get("type") == "step-finish":
            tok = part.get("tokens") or {}
            r["steps"] += 1
            for k in ("input", "output", "reasoning"):
                r[k] += int(tok.get(k) or 0)
            r["cache_read"] += int((tok.get("cache") or {}).get("read") or 0)
        elif part.get("type") == "tool":
            name = str(part.get("tool"))
            args = (part.get("state") or {}).get("input") or {}
            r["tools_memory" if is_memory(name, args) else "tools_explore"] += 1
            r["tool_names"].append(name)
        elif part.get("type") == "text":
            texts.append(part.get("text") or "")
        elif e.get("type") == "error":
            texts.append(f"[error] {e.get('error')}")
    r["text"] = "\n".join(texts)
    return r


def bootstrap(deltas: list, n: int = 2000, seed: int = 0) -> "tuple[float, float, float]":
    if not deltas:
        return (0.0, 0.0, 0.0)
    rnd = random.Random(seed)
    means = sorted(statistics.fmean(rnd.choices(deltas, k=len(deltas))) for _ in range(n))
    return (round(statistics.fmean(deltas), 3), round(means[int(n * 0.025)], 3), round(means[int(n * 0.975)], 3))


# tokens = what the model processed fresh; context = everything it read, cache included.
METRICS = ("correct", "tokens", "context", "input", "output", "tools_explore", "tools_memory", "steps", "secs")


def summarize(rows: list) -> dict:
    """Repetitions are averaged per task first: the bootstrap resamples TASKS,
    so three runs of one task do not count as three independent tasks."""
    out = {}
    for group, keep in (("memory", lambda r: not r.get("control")), ("control", lambda r: r.get("control"))):
        by_task: dict = {}
        for r in rows:
            if keep(r) and "on" in r and "off" in r:
                by_task.setdefault(r["id"], []).append(r)
        per = {tid: {arm: {m: statistics.fmean(x[arm][m] for x in rs) for m in METRICS} for arm in ("on", "off")}
               for tid, rs in by_task.items()}
        g = {"tasks": len(per), "runs": sum(len(rs) for rs in by_task.values())}
        for m in METRICS:
            g[m] = {"on": round(statistics.fmean(p["on"][m] for p in per.values()), 2) if per else 0,
                    "off": round(statistics.fmean(p["off"][m] for p in per.values()), 2) if per else 0,
                    "delta_ci95": bootstrap([p["on"][m] - p["off"][m] for p in per.values()])}
        out[group] = g
    return out


def print_report(res: dict) -> None:
    print(f"\nA/B {res['date']}  model {res['model']}  scenario {res.get('scenario', 'repo')}  "
          f"reps {res.get('reps', 1)}  runs {len(res['rows'])}")
    for group, g in res["summary"].items():
        print(f"\n== {group} (tasks {g.get('tasks', g.get('n'))}, runs {g.get('runs', g.get('n'))})"
              f"          ON      OFF     delta [95% CI]")
        for m in METRICS:
            d = g[m]["delta_ci95"]
            print(f"  {m:14} {g[m]['on']:>9} {g[m]['off']:>8}   {d[0]:+} [{d[1]:+}, {d[2]:+}]")
    print("\n  id  rep  correct on/off  tokens on/off      explore on/off  memory  secs on/off")
    for r in res["rows"]:
        on, off = r.get("on", {}), r.get("off", {})
        print(f"  {r['id']:4} {r.get('rep', 0):>2} {on.get('correct', '-'):>5}/{off.get('correct', '-'):<5}  "
              f"{on.get('tokens', '-'):>7}/{off.get('tokens', '-'):<8}  {on.get('tools_explore', '-'):>4}/{off.get('tools_explore', '-'):<4}"
              f"  {on.get('tools_memory', '-'):>5}   {on.get('secs', '-'):>5}/{off.get('secs', '-')}")


class StopRun(Exception):
    """The provider refuses both arms (quota): stop, keep what was measured."""


def main(argv=None) -> int:
    global MODEL
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="", help="comma-separated task ids")
    ap.add_argument("--model", default=MODEL, help="OpenCode provider/model, e.g. openrouter/<id>:free")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", default="")
    ap.add_argument("--report", default="", help="print a saved result and exit")
    ap.add_argument("--reps", type=int, default=1, help="runs per task and arm, a fresh memory copy each")
    ap.add_argument("--outside", action="store_true",
                    help="work in an empty folder: the agent cannot read the answer from the repo")
    ap.add_argument("--memory-only", action="store_true", help="leave the control tasks out")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    MODEL = a.model           # run_one and the saved result read it
    sys.stdout.reconfigure(encoding="utf-8")
    if a.report:
        print_report(json.loads(Path(a.report).read_text(encoding="utf-8")))
        return 0
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    only = {t for t in a.only.split(",") if t}
    tasks = [t for t in data["tasks"] if (not only or t["id"] in only)
             and not (a.memory_only and t.get("control"))]
    oc = opencode()
    OUT.mkdir(exist_ok=True)
    path = Path(a.out) if a.out else OUT / f"ab-{time.strftime('%Y-%m-%d-%H%M')}.json"

    def save(rows: list) -> dict:
        # Only pairs where both arms answered count: a provider failure is not a result.
        ok = [r for r in rows if r.get("on", {}).get("rc") == 0 and r.get("off", {}).get("rc") == 0]
        res = {"date": time.strftime("%Y-%m-%d %H:%M"), "model": MODEL, "tasks_version": data["version"],
               "scenario": "outside" if a.outside else "repo", "reps": a.reps,
               "valid_runs": len(ok), "summary": summarize(ok), "rows": rows}
        path.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        return res

    off_home = off_config()
    cwd = Path(tempfile.mkdtemp(prefix="ab-empty-")) if a.outside else REPO
    arms = {"on": ISO.env(),
            "off": dict(CLEAN, XDG_CONFIG_HOME=str(off_home))}
    rows = []
    try:
        for rep in range(a.reps):
            # A fresh copy per repetition: facts the ON arm saved in one must not help the next.
            up = subprocess.run([sys.executable, str(REPO / "tools/isolated.py"), "up"], env=CLEAN,
                                capture_output=True, text=True, timeout=300)
            if up.returncode != 0:
                sys.exit("isolated up failed: " + (up.stdout + up.stderr)[-300:])
            for i, t in enumerate(tasks):
                row = {"id": t["id"], "rep": rep, "control": bool(t.get("control")), "fact": t.get("fact")}
                # Alternate which arm goes first: drift in the free model's load hits both alike.
                for arm in (("on", "off") if (i + rep) % 2 == 0 else ("off", "on")):
                    r = run_one(oc, arms[arm], t["prompt"], a.timeout, cwd)
                    r["correct"] = round(score(r["text"], t["expect"]), 2)
                    r["tokens"] = r["input"] + r["output"] + r["reasoning"]
                    r["context"] = r["input"] + r["cache_read"]
                    row[arm] = r
                    print(f"r{rep} {t['id']} {arm:3} correct {r['correct']:.2f} tokens {r['tokens']:>6} "
                          f"explore {r['tools_explore']:>2} memory {r['tools_memory']} {r['secs']:>5}s rc {r['rc']}",
                          flush=True)
                    if a.verbose:
                        print("    " + r["text"][:400].replace("\n", "\n    "))
                rows.append(row)
                save(rows)                   # after every task: a stopped run keeps what it measured
                if all(row[arm]["rc"] in ("quota", "provider-error") for arm in ("on", "off")):
                    print("both arms failed on the provider (quota?): stopping, results so far are saved")
                    raise StopRun
    except StopRun:
        pass
    finally:
        subprocess.run([sys.executable, str(REPO / "tools/isolated.py"), "down", "--purge"], env=CLEAN,
                       capture_output=True, timeout=120)
        shutil.rmtree(off_home, ignore_errors=True)
        if a.outside:
            shutil.rmtree(cwd, ignore_errors=True)
    res = save(rows)
    print_report(res)
    print(f"\nsaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
