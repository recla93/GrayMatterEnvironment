"""Ask a model a prompt file, isolated: no memory, no user instructions, no tools.

    python tools/ask.py --model openrouter/baidu/ernie-5.5-flash-preview:free p/*.txt
    python tools/ask.py --model opencode/gpt-5.4-nano --out answers/ case.txt

For A/B tests on what a model does with a recall (2026-11-18). Through OpenCode,
with the user's providers (OpenRouter, OpenCode Zen): a Haiku subagent of Claude
Code cost ~61k tokens a case, this costs the prompt.

Isolation, each part needed (checked by asking the model):
- `--standalone`: a private server. Without it `opencode run` attaches to the
  running OpenCode service, which carries the real config, the Neuron plugin and
  the user's AGENTS.md (the model quoted the user's language rules).
- XDG_CONFIG_HOME on an empty config that denies every permission: no plugin,
  no MCP, no AGENTS.md, and a tool call is refused instead of run.
- an empty working folder: no project opencode.json or AGENTS.md.
- `--archived`, and every prompt opens with MARKER, so tools/replay.py leaves
  these sessions out of the real messages.

Writes <prompt>.out next to each prompt (or into --out). Exit 1 if any call failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "[gm-ask]"
CONFIG = {"$schema": "https://opencode.ai/config.json", "plugin": [], "mcp": {},
          "permission": {"*": "deny", "bash": "deny", "edit": "deny", "read": "deny",
                         "webfetch": "deny", "websearch": "deny"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, help="provider/model, as `opencode models` lists it")
    ap.add_argument("--out", help="folder for the answers (default: next to each prompt)")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("prompts", nargs="+")
    a = ap.parse_args(argv)
    exe = shutil.which("opencode")
    if not exe:
        print("opencode not found on PATH")
        return 1
    home = Path(tempfile.mkdtemp(prefix="gm-ask-"))
    (home / "xdg" / "opencode").mkdir(parents=True)
    (home / "xdg" / "opencode" / "opencode.json").write_text(json.dumps(CONFIG), encoding="utf-8")
    (home / "cwd").mkdir()
    # OpenCode 2.3.2 also reads ~/.claude/CLAUDE.md, its skills and the project
    # config unless told not to: an isolated run quoted the user's rules (2026-11-23).
    env = {**os.environ, "XDG_CONFIG_HOME": str(home / "xdg"),
           "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1",
           "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1", "OPENCODE_DISABLE_PROJECT_CONFIG": "1"}
    failed = 0
    try:
        for p in map(Path, a.prompts):
            text = f"{MARKER} " + p.read_text(encoding="utf-8")
            # On stdin: through the npm shim (opencode.cmd) an argument is cut at its first newline.
            r = subprocess.run([exe, "run", "--standalone", "--archived", "--model", a.model],
                               input=text, cwd=home / "cwd", env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=a.timeout)
            out = (Path(a.out) / f"{p.stem}.out") if a.out else p.with_suffix(".out")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(r.stdout, encoding="utf-8")
            ok = r.returncode == 0 and r.stdout.strip()
            failed += not ok
            print(f"{'ok ' if ok else 'ERR'} {p.name} -> {out}" + ("" if ok else f" | {r.stderr[-200:]}"))
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
