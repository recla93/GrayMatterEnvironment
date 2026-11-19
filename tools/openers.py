"""Session openers: did the memory arrive, and did `last:` say where the work stood?

    python tools/openers.py                     # the table and the counts
    python tools/openers.py --judge MODEL       # plus a blind verdict by a cheap model (tools/ask.py)
    python tools/openers.py --selftest

One row per real session (Claude Code transcripts of this project, OpenCode
sessions not archived), its first user message:
- `got`: what the hook injected on that message, read from the transcript
  (Claude Code only): none, empty, memory, last. `none` is a lost opener: the
  memory never reached the model (2026-11-19: the daemon never prewarmed, the
  first recall took 2.59 s against the hook's 2.5 s).
- `last`: the `last:` line the CURRENT code gives that message on the memory as
  it was then: facts created after it left out, a fact superseded later active
  again. Same function as the live recall (`_last_stop`), on a read-only copy.
- `truth`, on the openers that ask for the state ("where were we?"): the
  assistant's answer to that message, written after it checked the repo: the
  state as it really was. (The previous session's closing message was tried
  first, 19/11: it is mostly "I saved two facts", so the judge scored the
  closing, not the line.)
- `--judge`: a cheap model sees the truth and the `last:` line, nothing else,
  and says YES / PARTLY / NO to "does the line give that state". On the other
  openers `last:` is noise: its characters are the cost.

The rows hold the user's messages: they are written to a temp folder printed at
the end, never into the repo. Exit 1 only on a crash.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay import CLEAN, HOME, REPO, SKIP, copy_graphs  # noqa: E402

FORK = "Background (from the session that started this one)"   # a session started by another: not an opener
# Model tests run by hand in OpenCode (12/11, 15/11): prompts, not openers.
TESTS = ("Reply only", "Rispondi solo", "Rispondi a memoria", "Spiegami in almeno")
STATE_Q = re.compile(r"dove eravamo|where were we|riprend|handoff|da dove|stato (attuale|dei lavori)"
                     r"|(check|controlla|verifica)\w* (dello |lo )?stato", re.I)
TRUTH_CHARS = 1500
JUDGE = """A user opens a new work session with an assistant. Below:
(A) the assistant's answer to "where were we?", written after checking the project: where the work really stood;
(B) a memory line given to the assistant before it checked anything.

Does (B) already give the state that (A) found: what was done last, what is open, or what comes next?
Answer with one word first, YES, PARTLY or NO, then one short reason.

(A)
{truth}

(B)
{last}
"""


def _text(content) -> str:
    if isinstance(content, str):
        return " ".join(content.split())
    return " ".join(" ".join(b.get("text", "").split()) for b in content or []
                    if isinstance(b, dict) and b.get("type") == "text").strip()


def claude_sessions() -> list[dict]:
    out = []
    for f in glob.glob(str(HOME / ".claude/projects/*GrayMatter*/*.jsonl")):
        s = None
        for line in open(f, encoding="utf-8", errors="replace"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            a = o.get("attachment") or {}
            # The hook's injection follows the message it answers, before the next one.
            if s and s["got"] == "none" and a.get("type") == "hook_additional_context" and not s["closed"]:
                c = " ".join(map(str, a.get("content") or []))
                s["got"] = "last" if "last: " in c else "memory" if "recalled-memory" in c else "empty"
            if s and not s["closed"] and o.get("type") == "assistant":
                # The longest text of the turn: the last one is often the reply to the
                # save reminder ("I saved two facts"), not the answer.
                s["answer"] = max(s["answer"], _text((o.get("message") or {}).get("content")), key=len)
            if o.get("type") != "user" or o.get("isMeta"):
                continue
            t = _text((o.get("message") or {}).get("content"))
            if not t or t.startswith(SKIP):
                continue
            if s is None and len(t) >= 8:
                utc = dt.datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00"))
                s = {"client": "cc", "at": utc.astimezone().strftime("%Y-%m-%dT%H:%M:%S"),
                     "opener": t, "got": "none", "closed": False, "answer": ""}
            elif s:
                s["closed"] = True
        if s:
            out.append(s)
    return out


def opencode_sessions() -> list[dict]:
    oc = HOME / ".local/share/opencode/opencode.db"
    if not oc.is_file():
        return []
    db = sqlite3.connect(oc.resolve().as_uri() + "?mode=ro", uri=True)
    out = []
    try:
        for sid, tc in db.execute("SELECT id, time_created FROM session_v2 WHERE parent_id IS NULL "
                                  "AND time_archived IS NULL AND directory LIKE '%GrayMatter%'"):
            msgs = [(t, json.loads(d)) for t, d in db.execute(
                "SELECT type, data FROM session_message WHERE session_id=? ORDER BY time_created", (sid,))]
            first = next((_text(d.get("text")) for t, d in msgs if t == "user"), "")
            if len(first) < 8 or first.startswith(SKIP):
                continue
            users = [i for i, (t, _d) in enumerate(msgs) if t == "user"]
            turn1 = msgs[users[0]:users[1] if len(users) > 1 else None]
            texts = [_text(d.get("content")) for t, d in turn1 if t == "assistant"]
            out.append({"client": "oc", "at": dt.datetime.fromtimestamp(tc / 1000).strftime("%Y-%m-%dT%H:%M:%S"),
                        "opener": first, "got": "?", "answer": max(texts, key=len, default="")})
    finally:
        db.close()
    return out


def as_of(facts: dict, t: str) -> SimpleNamespace:
    """The facts as they stood at `t`: the later ones out, and a fact superseded
    by a later one active again (a retired handoff has no pointer back: it comes
    back too, and the newest handoff before `t` still wins in _last_stop)."""
    keep = {i: dict(f) for i, f in facts.items() if f["created_at"] <= t}
    replaced = {f.get("supersedes") for f in keep.values()}
    for f in keep.values():
        if f["status"] == "superseded" and f["id"] not in replaced:
            f["status"] = "active"
    return SimpleNamespace(facts=keep)


def selftest() -> None:
    f = lambda i, t, st="active", sup=None: {"id": i, "created_at": t, "status": st, "supersedes": sup}
    facts = {"a": f("a", "2026-11-10", "superseded"), "b": f("b", "2026-11-12", sup="a"),
             "c": f("c", "2026-11-09", "superseded"), "d": f("d", "2026-11-09T10", sup="c")}
    v = as_of(facts, "2026-11-11")
    assert set(v.facts) == {"a", "c", "d"}, v.facts
    assert v.facts["a"]["status"] == "active" and v.facts["c"]["status"] == "superseded", v.facts
    print("selftest ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--judge", metavar="MODEL", help="ask this model (tools/ask.py) for a blind verdict")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        selftest()
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gm-openers-"))
    copy_graphs(tmp / "graphs")
    os.environ.clear()
    os.environ.update(CLEAN, NS_GRAPHS_DIR=str(tmp / "graphs"), NEURON_NO_DOTENV="1", GM_HOME=str(tmp / "gm"))
    sys.path[:0] = [str(REPO / "neuron" / "src"), str(REPO)]
    from neuron import server as S
    from neuron.registry import GraphRegistry
    S._g = GraphRegistry(graphs_dir=str(tmp / "graphs"))
    S.TURSO_ENGINE = False
    facts = S._g.get().facts
    first_fact = min(f["created_at"] for f in facts.values())

    seen, rows = set(), []
    for s in sorted(claude_sessions() + opencode_sessions(), key=lambda s: s["at"]):
        key = (s["at"][:16], s["opener"][:200])            # a forked transcript repeats its parent's opener
        if key in seen:
            continue
        seen.add(key)
        rows.append(s)
        if s["opener"].startswith((FORK, *TESTS)) or s["at"] < first_fact:
            s["skip"] = True
            continue
        last = S._last_stop(as_of(facts, s["at"]), s["opener"])
        s["last"] = " | ".join(f"[{f['kind']}] {S.fact_shown(f)} #{f['id']} ({f['created_at'][:10]})" for f in last)
        s["state_q"] = bool(STATE_Q.search(s["opener"]))
        s["truth"] = s["answer"][:TRUTH_CHARS] if s["state_q"] else ""

    todo = [s for s in rows if not s.get("skip")]
    if a.judge:
        (tmp / "judge").mkdir()
        files = []
        for i, s in enumerate(todo):
            if s["truth"] and s["last"]:
                p = tmp / "judge" / f"{i:03d}.txt"
                p.write_text(JUDGE.format(truth=s["truth"], last=s["last"]), encoding="utf-8")
                files.append(p)
        subprocess.run([sys.executable, str(REPO / "tools" / "ask.py"), "--model", a.judge, *map(str, files)])
        for i, s in enumerate(todo):
            out = tmp / "judge" / f"{i:03d}.out"
            m = re.search(r"\b(YES|PARTLY|NO)\b", out.read_text(encoding="utf-8")) if out.is_file() else None
            s["verdict"] = m.group(1) if m else ("-" if s["state_q"] else "")

    (tmp / "openers.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{'when':16} cl  got     state  last  verdict  opener")
    for s in rows:
        if s.get("skip"):
            continue
        print(f"{s['at'][:16]} {s['client']}  {s['got']:7} {'yes' if s['state_q'] else 'no ':5} "
              f"{len(s['last']):5} {s.get('verdict', ''):8} {s['opener'][:60]}")
    cc = [s for s in todo if s["client"] == "cc"]
    print(f"\nopeners {len(todo)} (skipped {len(rows) - len(todo)}: forks, model tests, before the facts) | "
          f"Claude Code memory lost on {sum(s['got'] == 'none' for s in cc)}/{len(cc)} | "
          f"last: on {sum(bool(s['last']) for s in todo)}/{len(todo)}, "
          f"{sum(len(s['last']) for s in todo) // max(len(todo), 1)} chars avg")
    if a.judge:
        v = [s.get("verdict", "-") for s in todo if s["state_q"]]
        print("verdict on the state openers: " + ", ".join(f"{k} {v.count(k)}" for k in ("YES", "PARTLY", "NO", "-")))
    print(f"rows in {tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
