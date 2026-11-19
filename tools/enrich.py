"""Give gists to the facts that have none, with a cheap model; the model of a
session rarely writes one (155 of 317 live facts had none on 2026-11-18).

    python tools/enrich.py propose --model openrouter/... --out gists.json [--limit N]
    python tools/enrich.py apply gists.json            # through the daemon of $GM_PORT
    python tools/enrich.py --selftest

`propose` reads the active facts without a gist (from $NS_GRAPHS_DIR, else the
live suite, read-only), asks the model through tools/ask.py in batches, and
writes the gists that pass the checks to a JSON file to read before applying.
`apply` restates each fact word for word with its gist through store_turn: the
gist fills in place (same id, same place), nothing else changes. Run it under
`tools/isolated.py run --` first, then on the live daemon once read.

A gist is English (the memory's pivot language), so a fact written in Italian
reaches the recall in English through it, without a rewrite. Procedures keep
none: recall shows them whole.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "neuron" / "src"))
from neuron.curation import foreign_language  # noqa: E402

GIST_MAX = 100
BATCH = 15
PROMPT = """Write a gist for each fact below: the fact for a machine, in ENGLISH whatever the
fact's language, terse, at most {max} characters. Keep what makes it useful: names,
numbers, ids (#xxxxxxxx), commands, cause -> effect. Add nothing that is not in the fact.
Forms that work: "fix: daemon log locked on purge -> retry rmtree 30s",
"decision: K=2 facts per recall; noise 1.3 -> 0.5", "user wants plans before code".
Never use the character |.

Reply with ONLY a JSON object mapping each id to its gist: {{"id": "gist", ...}}

FACTS:
{facts}
"""


def graphs_db(context: str) -> Path:
    base = Path(os.environ.get("NS_GRAPHS_DIR") or Path.home() / "GrayMatterEnvironment/neuron/graphs")
    return base / f"graph_{context}.db"


def missing(context: str) -> list[dict]:
    db = sqlite3.connect(graphs_db(context).resolve().as_uri() + "?mode=ro", uri=True)
    rows = db.execute("SELECT id, kind, text FROM facts WHERE context=? AND status='active' "
                      "AND gist='' AND kind != 'procedure' ORDER BY turn", (context,)).fetchall()
    db.close()
    return [{"id": i, "kind": k, "text": t} for i, k, t in rows]


def check(gist: str) -> str:
    """'' when the gist can be stored, else why not."""
    g = " ".join(str(gist or "").split())
    if not g:
        return "empty"
    if len(g) > GIST_MAX + 10:
        return f"{len(g)} chars"
    if "|" in g:
        return "has |"
    if foreign_language(g):
        return "not English"
    return ""


def parse(out: str) -> dict:
    m = re.search(r"\{.*\}", out, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}
    return {str(k).lstrip("#"): str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def propose(a) -> int:
    facts = missing(a.context)[: a.limit or None]
    tmp = Path(tempfile.mkdtemp(prefix="gm-enrich-"))
    for i in range(0, len(facts), BATCH):
        part = facts[i:i + BATCH]
        body = "\n".join(f"#{f['id']} [{f['kind']}] {f['text']}" for f in part)
        (tmp / f"b{i // BATCH:03d}.txt").write_text(PROMPT.format(max=a.max, facts=body), encoding="utf-8")
    subprocess.run([sys.executable, str(REPO / "tools" / "ask.py"), "--model", a.model, *map(str, sorted(tmp.glob("b*.txt")))])
    texts = {f["id"]: f for f in facts}
    good, bad = {}, {}
    for out in sorted(tmp.glob("b*.out")):
        for fid, gist in parse(out.read_text(encoding="utf-8")).items():
            if fid not in texts:
                continue
            why = check(gist)
            (bad if why else good)[fid] = {"gist": " ".join(gist.split()), "text": texts[fid]["text"],
                                          "kind": texts[fid]["kind"], **({"why": why} if why else {})}
    Path(a.out).write_text(json.dumps({"context": a.context, "model": a.model, "gists": good, "rejected": bad},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(facts)} facts without a gist: {len(good)} gists ok, {len(bad)} rejected, "
          f"{len(facts) - len(good) - len(bad)} unanswered -> {a.out}")
    return 0


def apply(a) -> int:
    d = json.loads(Path(a.file).read_text(encoding="utf-8"))
    db = sqlite3.connect(graphs_db(d["context"]).resolve().as_uri() + "?mode=ro", uri=True)
    code = ("import json,sys; from gray_matter.cli import _send_ipc; "
            "print(json.dumps(_send_ipc(json.loads(sys.stdin.read()), 120.0)))")
    py = Path.home() / "GrayMatterEnvironment/graymatter/.venv/Scripts/python.exe"
    facts = []
    for fid, g in d["gists"].items():
        row = db.execute("SELECT kind, text, gist, status FROM facts WHERE context=? AND id=?", (d["context"], fid)).fetchone()
        if not row or row[2] or row[3] != "active" or row[1] != g["text"] or check(g["gist"]):
            continue          # changed since the proposal: leave it
        cs = [k for (k,) in db.execute("SELECT keyword FROM fact_concepts WHERE context=? AND fact_id=?", (d["context"], fid))]
        facts.append({"kind": row[0], "text": row[1], "concepts": cs, "gist": g["gist"]})
    added = 0
    for i in range(0, len(facts), 3):          # store_turn takes 3 facts a call
        msg = {"action": "call", "server": "neuron", "tool": "store_turn",
               "args": {"facts": facts[i:i + 3], "context": d["context"]}}
        r = subprocess.run([str(py), "-I", "-c", code], input=json.dumps(msg), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        added += (r.stdout or "").count("gist added")
    print(f"{added} gists added of {len(facts)} sent ({len(d['gists'])} proposed)")
    return 0 if added == len(facts) else 1


def selftest() -> None:
    assert check("fix: daemon log locked -> retry 30s") == ""
    assert check("") == "empty" and check("a | b") == "has |" and check("x" * 120).endswith("chars")
    assert check("il daemon non parte perché la porta è occupata") == "not English"
    assert parse('noise {"#0a1b2c3d": "g1", "11111111": "g2"} tail') == {"0a1b2c3d": "g1", "11111111": "g2"}
    assert parse("no json") == {}
    print("selftest ok")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("propose")
    p.add_argument("--model", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--context", default="backend")
    p.add_argument("--limit", type=int, default=0)
    # The model overshoots the length it is asked for: 14 of 155 came back over
    # GIST_MAX + 10 on 2026-11-18. Asking for less leaves the check where it is.
    p.add_argument("--max", type=int, default=GIST_MAX, help="length asked of the model")
    q = sub.add_parser("apply")
    q.add_argument("file")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.selftest:
        selftest()
        return 0
    return {"propose": propose, "apply": apply}[a.cmd](a) if a.cmd else ap.print_help() or 1


if __name__ == "__main__":
    sys.exit(main())
