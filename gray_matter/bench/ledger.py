"""Memory ledger: what the suite costs and how much of it gets used, on REAL sessions.

Level 0 of the savings measurement (work/design/MISURA-RISPARMIO-2026-11-10.md).
It reads Claude Code transcripts and, per session and in total, reports:

  cost     tokens the memory adds: the hook injections (SessionStart handshake,
           UserPromptSubmit recall) and the memory tool calls (their input and
           their result), weighted by what they really cost: an injected text
           is written to the prompt cache once and READ again on every later
           request of the session.
  use      fact ids the memory showed (#xxxxxxxx in an injection or a tool
           result) that the model then used: confirmed, superseded or cited.
  work     tool calls that explore (Read, Grep, Glob, Bash, Web*, Agent): the
           baseline the counterfactual A/B (level 2) will compare against.

It never calls a model and never touches the memory: it only reads files.

    python gray_matter/bench/ledger.py                       # every project
    python gray_matter/bench/ledger.py --project GrayMatter  # name filter
    python gray_matter/bench/ledger.py --json > ledger.json
    python gray_matter/bench/ledger.py --md report.md

Token weights are "input-equivalent tokens" (IET), the price ratios of the
Claude API: input 1, cache write 1.25 (5 min) or 2 (1 h), cache read 0.1,
output 5. shortcut: chars/4 for injected text (Italian runs closer to 3.5),
upgrade to the real tokenizer if the overhead share ever decides something.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

W_IN, W_CW5, W_CW1H, W_CR, W_OUT = 1.0, 1.25, 2.0, 0.1, 5.0
CHARS_PER_TOKEN = 4
FACT_ID = re.compile(r"#([0-9a-f]{8})\b")
MEMORY_MARKERS = ("[neuron]", "[NEURON]", "[NEURAG]", "<recalled-memory", "Gray-Matter", "📚 KB")
# One line of memory shown to the model: "[kind] text (concepts) #id".
FACT_LINE = re.compile(r"\[(?:idea|decision|fix|fact|progress|user|habit|procedure|detail)\]\s+(.+?)\s+#([0-9a-f]{8})\b")
SILENT_WINDOW = 1          # turns after the one that showed the fact
EXPLORE = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "Agent", "Task", "LS", "Bash", "PowerShell"}


def is_memory_tool(name: str) -> bool:
    n = name.lower()
    return "gray-matter" in n or "gray_matter" in n or "neuron" in n or "neurag" in n


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(c.get("text", c.get("content", ""))) if isinstance(c, dict) else str(c)
                         for c in content)
    return str(content or "")


# The use rule lives in the hook that applies it live; loaded by path, as this
# file is (a script, not a package module).
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("gm_memhook", Path(__file__).resolve().parents[1] / "memhook.py")
_memhook = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_memhook)
distinctive, silently_used = _memhook.distinctive, _memhook.silently_used


def _is_user_turn(e: dict) -> bool:
    if e.get("type") != "user" or e.get("isSidechain") or e.get("isMeta"):
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return False
    return bool(_text(c).strip())


def _iet(u: dict) -> float:
    cc = u.get("cache_creation") or {}
    cw1h = cc.get("ephemeral_1h_input_tokens") or 0
    cw5 = cc.get("ephemeral_5m_input_tokens")
    if cw5 is None:
        cw5 = (u.get("cache_creation_input_tokens") or 0) - cw1h
    return (W_IN * (u.get("input_tokens") or 0) + W_CW5 * cw5 + W_CW1H * cw1h
            + W_CR * (u.get("cache_read_input_tokens") or 0) + W_OUT * (u.get("output_tokens") or 0))


def analyze(path: Path, common: frozenset = frozenset()) -> dict:
    """One transcript -> its ledger. Events keep file order (chronological).
    `common`: words too frequent in the corpus to prove a silent use."""
    events = []          # ("req", None) per API request, ("inj", tokens) per injection
    turns = 0
    requests: set = set()
    iet_total = 0.0
    mem_calls = explore_calls = other_calls = 0
    shown: set = set()
    used: set = set()
    written: set = set()
    silent: set = set()
    prompt = ""
    watch: dict = {}                  # fact id -> (distinctive words, last turn to watch)
    pending_mem: dict = {}            # tool_use_id -> True for memory tools
    for ln in path.open(encoding="utf-8", errors="replace"):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        if t == "attachment":
            a = e.get("attachment") or {}
            body = _text(a.get("content"))
            if a.get("hookEvent") in ("SessionStart", "UserPromptSubmit") and any(m in body for m in MEMORY_MARKERS):
                events.append(("inj", len(body) / CHARS_PER_TOKEN))
                shown.update(FACT_ID.findall(body))
                _watch(watch, body, turns + 1, common)      # the recall arrives before its turn starts
            continue
        if _is_user_turn(e):
            turns += 1
            prompt = _text((e.get("message") or {}).get("content")).lower()
            continue
        msg = e.get("message") if isinstance(e.get("message"), dict) else {}
        if t == "user":                                   # tool results
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_result" and pending_mem.pop(b.get("tool_use_id"), None):
                    body = _text(b.get("content"))
                    events.append(("inj", len(body) / CHARS_PER_TOKEN))
                    # "facts: 2 saved — #a #b": the model's own writes, not memory shown to it.
                    saved = "\n".join(ln for ln in body.splitlines() if ln.startswith("facts:"))
                    written.update(FACT_ID.findall(saved))
                    shown.update(FACT_ID.findall(body.replace(saved, "")))
                    _watch(watch, body.replace(saved, ""), turns, common)
            continue
        if t != "assistant":
            continue
        mid = msg.get("id")
        if mid and mid not in requests:                   # one entry per content block, same usage
            requests.add(mid)
            iet_total += _iet(msg.get("usage") or {})
            events.append(("req", None))
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            said = (b.get("text") if b.get("type") == "text" else
                    json.dumps(b.get("input"), ensure_ascii=False) if b.get("type") == "tool_use" else "") or ""
            if said and watch and not is_memory_tool(str(b.get("name") or "")):
                low = said.lower()
                for fid, (words, until) in list(watch.items()):
                    if turns > until:
                        del watch[fid]
                    elif silently_used(words, low, prompt):
                        silent.add(fid)
                        del watch[fid]
            if b.get("type") == "text":
                used.update(i for i in FACT_ID.findall(b.get("text") or "") if i in shown)
            if b.get("type") != "tool_use":
                continue
            name, inp = str(b.get("name") or ""), b.get("input") if isinstance(b.get("input"), dict) else {}
            if is_memory_tool(name):
                mem_calls += 1
                pending_mem[b.get("id")] = True
                events.append(("inj", len(json.dumps(inp, ensure_ascii=False)) / CHARS_PER_TOKEN))
                if name.endswith("confirm"):
                    used.update(str(x).lstrip("#") for x in inp.get("facts") or [])
                for f in inp.get("facts") or []:
                    if isinstance(f, dict) and f.get("supersedes"):
                        used.add(str(f["supersedes"]).lstrip("#"))
            elif name in EXPLORE:
                explore_calls += 1
            else:
                other_calls += 1
    # An injection is written to the cache once, then read by every later request.
    later, overhead = 0, 0.0
    for kind, tok in reversed(events):
        if kind == "req":
            later += 1
        else:
            overhead += tok * (W_CW1H + W_CR * later)
    shown -= written
    used &= shown
    silent = (silent & shown) - used
    return {"session": path.stem[:8], "project": path.parent.name, "turns": turns,
            "requests": len(requests), "iet_total": round(iet_total),
            "mem_overhead_iet": round(overhead),
            "mem_share": round(overhead / iet_total, 4) if iet_total else 0.0,
            "mem_calls": mem_calls, "explore_calls": explore_calls, "other_calls": other_calls,
            "facts_shown": len(shown), "facts_used": len(used), "facts_silent": len(silent),
            "use_rate": round(len(used) / len(shown), 3) if shown else None,
            "any_use_rate": round((len(used) + len(silent)) / len(shown), 3) if shown else None}


def _watch(watch: dict, body: str, turn: int, common: frozenset = frozenset()) -> None:
    for text, fid in FACT_LINE.findall(body):
        watch.setdefault(fid, (distinctive(text) - common, turn + SILENT_WINDOW))


def totals(rows: list) -> dict:
    s = lambda k: sum(r[k] for r in rows)
    shown, used, iet = s("facts_shown"), s("facts_used"), s("iet_total")
    silent = s("facts_silent")
    turns = s("turns") or 1
    return {"sessions": len(rows), "turns": s("turns"), "requests": s("requests"),
            "iet_total": iet, "mem_overhead_iet": s("mem_overhead_iet"),
            "mem_share": round(s("mem_overhead_iet") / iet, 4) if iet else 0.0,
            "mem_calls_per_turn": round(s("mem_calls") / turns, 2),
            "explore_calls_per_turn": round(s("explore_calls") / turns, 2),
            "facts_shown": shown, "facts_used": used, "facts_silent": silent,
            "use_rate": round(used / shown, 3) if shown else None,
            "any_use_rate": round((used + silent) / shown, 3) if shown else None}


COMMON_SHARE = 0.2        # a word in the answers of more than 1 session in 5 proves nothing


def common_words(paths: list) -> frozenset:
    """Distinctive words that appear in the model's answers of more than
    COMMON_SHARE of the sessions: project vocabulary, not memory."""
    df: dict = {}
    for p in paths:
        seen = set()
        for ln in p.open(encoding="utf-8", errors="replace"):
            if '"assistant"' not in ln:
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            for b in ((e.get("message") or {}).get("content") or []) if isinstance(e, dict) else []:
                if isinstance(b, dict) and b.get("type") == "text":
                    seen |= distinctive(b.get("text") or "")
        for w in seen:
            df[w] = df.get(w, 0) + 1
    cut = max(2, COMMON_SHARE * len(paths))
    return frozenset(w for w, n in df.items() if n > cut)


def collect(root: Path, project: str = "") -> list:
    rows = []
    paths = sorted(root.glob("*/*.jsonl"))
    common = common_words(paths)
    for p in paths:
        if project.lower() not in p.parent.name.lower():
            continue
        r = analyze(p, common)
        if r["turns"]:
            rows.append(r)
    return rows


def markdown(rows: list, tot: dict) -> str:
    head = ("| session | project | turns | requests | IET | memory IET | share | mem calls | "
            "explore calls | shown | used | silent | any use |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    body = "\n".join(
        f"| {r['session']} | {r['project'][-28:]} | {r['turns']} | {r['requests']} | {r['iet_total']:,} | "
        f"{r['mem_overhead_iet']:,} | {r['mem_share']:.1%} | {r['mem_calls']} | {r['explore_calls']} | "
        f"{r['facts_shown']} | {r['facts_used']} | {r['facts_silent']} | "
        f"{'' if r['any_use_rate'] is None else f'{r['any_use_rate']:.0%}'} |"
        for r in sorted(rows, key=lambda r: -r["iet_total"]))
    t = tot
    summary = (f"**Total**: {t['sessions']} sessions, {t['turns']} turns, {t['requests']} requests, "
               f"{t['iet_total']:,} IET. Memory overhead {t['mem_overhead_iet']:,} IET = "
               f"**{t['mem_share']:.1%}**. Memory calls per turn {t['mem_calls_per_turn']}, explore calls "
               f"per turn {t['explore_calls_per_turn']}. Facts shown {t['facts_shown']}, used "
               f"{t['facts_used']} explicitly + {t['facts_silent']} silently (explicit **"
               f"{'' if t['use_rate'] is None else f'{t['use_rate']:.0%}'}**, any **"
               f"{'' if t['any_use_rate'] is None else f'{t['any_use_rate']:.0%}'}**).")
    return summary + "\n\n" + head + "\n" + body + "\n"


def experiment(path: Path) -> dict:
    """ADR-021 use bonus, per arm, from the daemon's own log (one line per turn:
    arm, facts shown, facts used). Arms are drawn per turn since 2026-11-24.
    z: two-proportion test on used/shown; |z| >= 1.96 is a difference at 95%."""
    arms = {False: [0, 0, 0], True: [0, 0, 0]}          # turns, shown, used
    if path.is_file():
        for ln in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            a = arms[bool(r.get("arm"))]
            a[0] += 1; a[1] += len(r.get("shown") or []); a[2] += len(r.get("used") or [])
    out = {("bonus" if k else "control"): {"turns": t, "shown": n, "used": u,
                                           "rate": round(u / n, 3) if n else None}
           for k, (t, n, u) in arms.items()}
    (_, n0, u0), (_, n1, u1) = arms[False], arms[True]
    if n0 and n1:
        p = (u0 + u1) / (n0 + n1)
        se = (p * (1 - p) * (1 / n0 + 1 / n1)) ** 0.5
        out["z"] = round((u1 / n1 - u0 / n0) / se, 2) if se else 0.0
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--project", default="", help="substring of the project folder name")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", help="write a markdown report to this file")
    ap.add_argument("--experiment", nargs="?", const="", metavar="LOG",
                    help="ADR-021 use bonus per arm, from logs/use_experiment.jsonl")
    a = ap.parse_args(argv)
    if a.experiment is not None:
        from gray_matter.paths import logs_dir
        print(json.dumps(experiment(Path(a.experiment or logs_dir() / "use_experiment.jsonl")), indent=2))
        return 0
    rows = collect(Path(a.root), a.project)
    tot = totals(rows)
    if a.json:
        print(json.dumps({"totals": tot, "sessions": rows}, indent=2))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(markdown(rows, tot))
    if a.md:
        Path(a.md).write_text(markdown(rows, tot), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
