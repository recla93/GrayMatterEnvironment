"""Replay the real user messages through the recall, before and after a change.

    python tools/replay.py                 # working tree vs HEAD
    python tools/replay.py --ref fa378d0   # working tree vs any git ref
    python tools/replay.py --show 5        # also print 5 changed recalls to read
    python tools/replay.py --data-after DIR   # same code, live graphs vs the graphs in DIR
    python tools/replay.py --selftest

What a client would get from the hook for each distinct user message of the
transcripts (Claude Code projects named *GrayMatter*, OpenCode sessions): pre_turn
with the message as topic, trimmed as GM's hook trims it. Each side runs on its
own fresh copy of the live graphs (read with the SQLite backup API, mode=ro: a
recall counts showings, the real memory is never touched) with its own code.

The messages and recalls are the user's: they are written next to the copies, in
a temp folder printed at the end, never into the repo. The report is numbers:
messages changed, characters per message, fact ids gained / lost, notes, and
procedures shown.

Exit 1 when a crash happens or when the change empties recalls: more than 5% of
the messages that had a fact before have none after. Everything else is for a
human to read (--show), not a verdict: a bench says right or wrong, a replay
says what moved (ADR-022, 2026-11-17: the bench said better, the replay found
17 worse messages).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOME = Path.home()
SUITE = Path(os.environ.get("GM_SUITE") or HOME / "GrayMatterEnvironment")
CLEAN = {k: v for k, v in os.environ.items()
         if k not in ("GM_HOME", "NS_GRAPHS_DIR", "NEURAG_HOME", "GM_PORT", "GM_INSTANCE")}
EMPTIED_MAX = 0.05
FACT_ID = re.compile(r"\) #([0-9a-f]{8})")          # "(concept) #id": a recalled fact, not a cited one
# Hook reminders, harness notes, and prompts of tools/ask.py (A/B tests, not the user's).
SKIP = ("<", "[memory]", "Stop hook", "[Request", "Caveat:", "[gm-ask]",
        "You are a coding agent, on Windows", "Isolation check")


def messages(limit: int = 0) -> list[str]:
    """Distinct user messages, oldest first: Claude Code transcripts of this
    project, then OpenCode's (V2 table session_message)."""
    out: dict = {}
    for f in sorted(glob.glob(str(HOME / ".claude/projects/*GrayMatter*/*.jsonl")), key=os.path.getmtime):
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") != "user" or o.get("isMeta"):
                continue
            c = (o.get("message") or {}).get("content")
            t = c if isinstance(c, str) else " ".join(
                b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text") if isinstance(c, list) else ""
            out.setdefault(" ".join(t.split()), None)
    oc = HOME / ".local/share/opencode/opencode.db"
    if oc.is_file():
        try:
            db = sqlite3.connect(oc.resolve().as_uri() + "?mode=ro", uri=True)
            for (d,) in db.execute("SELECT data FROM session_message WHERE type='user' ORDER BY time_created"):
                out.setdefault(" ".join(str(json.loads(d).get("text") or "").split()), None)
            db.close()
        except (sqlite3.Error, ValueError):
            pass
    msgs = [m for m in out if len(m) >= 8 and not m.startswith(SKIP) and "tool_result" not in m]
    return msgs[-limit:] if limit else msgs


def copy_graphs(dst: Path, src: "Path | None" = None) -> None:
    dst.mkdir(parents=True)
    src = src or SUITE / "neuron" / "graphs"
    for p in src.glob("graph_*.db"):
        ro = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
        out = sqlite3.connect(dst / p.name)
        try:
            ro.backup(out)
            out.execute("PRAGMA journal_mode=DELETE")
        finally:
            out.close()
            ro.close()
    # Not the live pointer: another session can switch it between the two copies
    # of one replay, and the sides then compare different graphs (2026-11-26).
    for name in ("graymatter", "backend"):
        if (dst / f"graph_{name}.db").is_file():
            (dst / "_active_context.txt").write_text(name, encoding="utf-8")
            break
    else:
        ctx = src / "_active_context.txt"
        if ctx.is_file():
            shutil.copy2(ctx, dst / ctx.name)


def worker(code: str, graphs: str, msgs_file: str, out_file: str) -> None:
    """In its own process: the code of one checkout, one copy of the graphs."""
    os.environ.update(NS_GRAPHS_DIR=graphs, NEURON_NO_DOTENV="1", GM_HOME=str(Path(graphs).parent / "gm"))
    sys.path[:0] = [str(Path(code) / "neuron" / "src"), code]
    import asyncio
    import time
    from neuron import server as S
    from neuron import search as _search
    from neuron.registry import GraphRegistry
    from gray_matter.server import _trim_for_hook
    assert Path(S.__file__).resolve().is_relative_to(Path(code).resolve()), S.__file__
    S._g = GraphRegistry(graphs_dir=graphs)
    S.TURSO_ENGINE = False
    g = S._g.get()
    _search._search_recall("warm", 1, g)
    while _search._recall_warming:     # past 64 texts the vectors warm in a thread
        time.sleep(0.1)
    msgs = json.loads(Path(msgs_file).read_text(encoding="utf-8"))

    async def go():
        return {m: _trim_for_hook((await S.call_tool("pre_turn", {"topic": m[:300]}))[0].text) for m in msgs}
    Path(out_file).write_text(json.dumps(asyncio.run(go()), ensure_ascii=False), encoding="utf-8")


def compare(before: dict, after: dict) -> dict:
    keys = [m for m in before if m in after]
    ids = lambda t: set(FACT_ID.findall(t))
    had = [m for m in keys if ids(before[m])]
    return {
        "messages": len(keys),
        "changed": sum(before[m] != after[m] for m in keys),
        "chars_per_msg": round(sum(len(after[m]) - len(before[m]) for m in keys) / max(len(keys), 1), 1),
        "lost_ids": sum(bool(ids(before[m]) - ids(after[m])) for m in keys),
        "gained_ids": sum(bool(ids(after[m]) - ids(before[m])) for m in keys),
        "emptied": sum(not ids(after[m]) for m in had),
        "had_facts": len(had),
        "notes": [sum("↳#" in d[m] for m in keys) for d in (before, after)],
        "procedures": [sum("[procedure]" in d[m] for m in keys) for d in (before, after)],
    }


def selftest() -> None:
    b = {"a": "facts: [fix] x (k) #0a1b2c3d", "b": "facts: [fix] y (k) #11111111", "c": "no facts"}
    a = {"a": "facts: [fix] x (k) #0a1b2c3d ↳#22222222: z", "b": "nothing", "c": "no facts"}
    r = compare(b, a)
    assert (r["changed"], r["lost_ids"], r["gained_ids"], r["emptied"], r["had_facts"], r["notes"]) == \
        (2, 1, 0, 1, 2, [0, 1]), r
    print("selftest ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ref", default="HEAD", help="git ref to compare the working tree with")
    ap.add_argument("--limit", type=int, default=0, help="only the newest N messages")
    ap.add_argument("--show", type=int, default=0, help="print N changed recalls, before and after")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--data-after", help="graphs folder for the after side (a data change, e.g. "
                                         "an isolated instance after tools/enrich.py); code = working tree on both")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--worker", nargs=4, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.worker:
        worker(*a.worker)
        return 0
    if a.selftest:
        selftest()
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gm-replay-"))
    msgs = messages(a.limit)
    (tmp / "messages.json").write_text(json.dumps(msgs, ensure_ascii=False), encoding="utf-8")
    ref_tree = tmp / "ref"
    if not a.data_after:
        subprocess.run(["git", "worktree", "add", "--detach", "-q", str(ref_tree), a.ref], cwd=REPO, check=True)
    try:
        sides = {}
        for side, code in (("before", REPO if a.data_after else ref_tree), ("after", REPO)):
            copy_graphs(tmp / side / "graphs", Path(a.data_after) if a.data_after and side == "after" else None)
            out = tmp / f"{side}.json"
            p = subprocess.run([sys.executable, "-X", "utf8", __file__, "--worker", str(code),
                                str(tmp / side / "graphs"), str(tmp / "messages.json"), str(out)],
                               cwd=tmp, env=CLEAN, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if p.returncode != 0:
                print(f"{side}: worker failed\n{p.stderr[-1500:]}")
                return 1
            sides[side] = json.loads(out.read_text(encoding="utf-8"))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(ref_tree)], cwd=REPO, capture_output=True)
    r = compare(sides["before"], sides["after"])
    r.update(ref=a.data_after or a.ref, folder=str(tmp))
    emptied = r["emptied"] > EMPTIED_MAX * max(r["had_facts"], 1)
    if a.json:
        print(json.dumps(r))
    else:
        print(f"replay vs {r['ref']}: {r['changed']}/{r['messages']} recalls changed, "
              f"{r['chars_per_msg']:+} chars/msg, ids lost on {r['lost_ids']} gained on {r['gained_ids']}, "
              f"emptied {r['emptied']}/{r['had_facts']}, notes {r['notes'][0]}->{r['notes'][1]}, "
              f"procedures {r['procedures'][0]}->{r['procedures'][1]}\nrecalls in {tmp}")
        changed = [m for m in sides["before"] if sides["before"][m] != sides["after"].get(m)]
        for m in changed[:a.show]:
            print(f"\n=== {m[:160]}\n--- before\n{sides['before'][m]}\n--- after\n{sides['after'][m]}")
    return 1 if emptied else 0


if __name__ == "__main__":
    sys.exit(main())
