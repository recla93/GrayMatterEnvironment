"""Who depends on what: recomputed from the repo on every run, never stored.

    python tools/deps.py pre_turn                 # every reference to a name, by area
    python tools/deps.py GM_HOME brainstorm_hint  # several names
    python tools/deps.py --check                  # the gate: exit 1 on a broken dependency

Run the lookup BEFORE changing a tool, an option or a shipped file. --check fails when:
  twins     a file in neurag/clients differs from its twin in neuron/src/neuron/clients
            (one hook shipped by both packages: a change to one copy must reach the other);
  guidance  text the model reads (session hooks, OpenCode plugin, Neuron signpost, GM
            instructions) calls a tool outside the I/O contract: the model cannot see it;
  gone      a name removed on purpose (work/design/PARCHEGGIO.md) is still referenced in
            living code, tests or docs (history and decision records may keep it).
Stdlib only. Not a call graph: the tests catch Python callers; this covers what they
cannot see (names inside strings, docs, copies, guidance).
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "build", "dist", "__pycache__", ".venv", "node_modules", "vendor",
             ".pytest_cache", "graphify-out"}
TEXT = {".py", ".mjs", ".js", ".ts", ".ps1", ".cmd", ".sh", ".json", ".toml", ".md", ".html", ".txt"}
# History and decision records may name what was removed: that is their job.
HISTORY = re.compile(r"(^|/)(work/|docs/design/|EVOLUTION|CHANGELOG|HANDOFF|DESIGN-EVOLUTION)", re.I)
TWINS = ("neurag/clients", "neuron/src/neuron/clients")
# The I/O contract (work/design/CONTRATTO-IO-2026-11-14.md); the announced sets are
# asserted by neuron/tests/test_tool_diet.py and gray_matter/tests/test_tool_diet_routing.py.
CONTRACT = {"pre_turn", "store_turn", "switch_context", "knowledge_query"}
TOOL_SOURCES = ("neuron/src/neuron/server.py", "neurag/server.py", "gray_matter/server.py")
# (file, first line of the guidance block or None for the whole file, end marker)
GUIDANCE = (
    ("neuron/src/neuron/clients/claude-code-hook/neuron_sessionstart_hook.py", None, None),
    ("neuron/src/neuron/clients/cowork-plugin/neuron-guard/hooks/neuron_sessionstart_hook.py", None, None),
    ("neuron/src/neuron/clients/opencode-plugin/neuron-handshake.mjs", None, None),
    ("gray_matter/memhook.py", "REMIND = (", ")\n\n"),
    ("neuron/src/neuron/funnel.py", "SIGNPOST_BASE = (", "\n)\n"),
    ("gray_matter/server.py", "GM_INSTRUCTIONS = (", "\n)\n"),
)
# Removed on purpose (PARCHEGGIO.md). Identifiers only: a common word would flag prose.
GONE = {"gray_matter_brainstorm", "brainstorm_hint", "_brainstorm_hint", "_tool_brainstorm",
        "gray_matter_state_set", "gray_matter_state_get", "gray_matter_state_delta",
        "_inject_neuron_mode", "_stimulus_block", "take_staged_stimulus", "stimulus_candidates",
        "spark_fact", "focus_boost", "append_turn", "STAGE_FRESH_SECONDS",
        "NEURON_STIMULUS_MIN_ACTIVATION", "NEURON_CONFIRM_HINT", "_confirm_hint_enabled",
        "_tool_around"}


def files(root: Path):
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and p.suffix in TEXT and not SKIP_DIRS.intersection(rel.parts):
            yield p, rel.as_posix()


def area(rel: str) -> str:
    if HISTORY.search(rel):
        return "history"
    if "/tests/" in rel or rel.startswith("tests/"):
        return "tests"
    if "/clients/" in rel or rel.endswith("memhook.py"):
        return "hooks"
    if rel.endswith(".md"):
        return "docs"
    if rel.startswith(("tools/", "neuron/bench/", "gray_matter/bench/", "neurag/bench/")):
        return "scripts"
    return "code"


def lookup(root: Path, names: list[str]) -> dict:
    """{name: {area: [(rel, line_no, line)]}} for whole-word matches."""
    pats = {n: re.compile(rf"(?<![\w]){re.escape(n)}(?![\w])") for n in names}
    out = {n: {} for n in names}
    for p, rel in files(root):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for n, pat in pats.items():
                if pat.search(line):
                    out[n].setdefault(area(rel), []).append((rel, i, line.strip()[:110]))
    return out


def tool_names(root: Path) -> set:
    names = set()
    for src in TOOL_SOURCES:
        p = root / src
        if p.exists():
            names |= set(re.findall(r'name="([a-z_]+)"', p.read_text(encoding="utf-8")))
    return names


def check(root: Path) -> list[str]:
    problems = []
    # twins
    a, b = root / TWINS[0], root / TWINS[1]
    if a.exists():
        for p in a.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                twin = b / p.relative_to(a)
                if not twin.exists() or twin.read_bytes() != p.read_bytes():
                    problems.append(f"twins: {p.relative_to(root).as_posix()} != "
                                    f"{twin.relative_to(root).as_posix()}"
                                    + ("" if twin.exists() else " (missing)"))
    # guidance
    hidden = tool_names(root) - CONTRACT
    for rel, start, end in GUIDANCE:
        p = root / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if start:
            i = text.find(start)
            j = text.find(end, i) if i >= 0 else -1
            if j < 0:      # a moved marker must not switch the rule off in silence
                problems.append(f"guidance: {rel}: block '{start}' not found, update GUIDANCE")
                continue
            text = text[i:j + len(end)]
        for name in sorted(hidden):
            if re.search(rf"(?<![\w.]){re.escape(name)}\(", text):
                problems.append(f"guidance: {rel} sends the model to '{name}', not in the I/O contract")
    # gone
    for name, by_area in lookup(root, sorted(GONE)).items():
        for ar, hits in by_area.items():
            if ar == "history":
                continue
            for rel, ln, _ in hits:
                if rel != "tools/deps.py":
                    problems.append(f"gone: '{name}' still in {rel}:{ln}")
    return problems


def _selftest() -> None:
    """Each rule fires on a planted fault and stays quiet on a clean tree."""
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        for twin in TWINS:
            (r / twin).mkdir(parents=True)
            (r / twin / "hook.py").write_text("same", encoding="utf-8")
        (r / "neuron/src/neuron/server.py").write_text('name="pre_turn" name="status"', encoding="utf-8")
        (r / "neuron/src/neuron/funnel.py").write_text('SIGNPOST_BASE = (\n "call pre_turn(x)"\n)\n', encoding="utf-8")
        (r / "work").mkdir()
        (r / "work/PARCHEGGIO.md").write_text("gray_matter_brainstorm was removed", encoding="utf-8")
        assert check(r) == [], check(r)
        (r / TWINS[0] / "hook.py").write_text("drifted", encoding="utf-8")
        (r / "neuron/src/neuron/funnel.py").write_text('SIGNPOST_BASE = (\n "call status(x)"\n)\n', encoding="utf-8")
        (r / "README.md").write_text("use `gray_matter_brainstorm` here", encoding="utf-8")
        got = check(r)
        assert [p.split(":")[0] for p in got] == ["twins", "guidance", "gone"], got
        assert set(lookup(r, ["pre_turn"])["pre_turn"]) == {"code"}   # server.py only, now
        assert "docs" in lookup(r, ["gray_matter_brainstorm"])["gray_matter_brainstorm"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="tool names, options, env vars, functions")
    ap.add_argument("--check", action="store_true", help="fail on a broken dependency (gate)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.check:
        _selftest()
        problems = check(REPO)
        for p in problems:
            print(p)
        print(f"deps: {len(problems)} problem(s)" if problems else "deps: ok")
        return 1 if problems else 0
    if not a.names:
        ap.error("give one or more names, or --check")
    for name, by_area in lookup(REPO, a.names).items():
        total = sum(len(h) for h in by_area.values())
        print(f"\n{name}: {total} reference(s)")
        for ar in ("code", "hooks", "tests", "scripts", "docs", "history"):
            for rel, ln, line in by_area.get(ar, []):
                print(f"  [{ar:7}] {rel}:{ln}  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
