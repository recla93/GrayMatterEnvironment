"""Smoke test of the INSTALLED suite: one run checks what was checked by hand on
2026-11-10, before every push. Exit 0 = every check passed (SKIP allowed).

    python tools/smoke.py            # all checks, table
    python tools/smoke.py --json     # machine-readable
    python tools/smoke.py --only kimi,codex

It never writes a fact: the recall it triggers only touches the daemon's
per-session record (fresh `smoke-*` sessions). The "saved: yes" path needs a
store_turn and is NOT here; it belongs to the isolated instance (TODO).

Groups: daemon (ping, workers), recall (shape, chrome trimmed, off-topic),
save (saved/turn IPC), claude, kimi, codex, opencode (deployed hooks, run with
each host's input), cohesion (byte-identical copies and deployed files equal
to the repo: catches a stale deploy).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOME = Path.home()
SUITE = Path(os.environ.get("GM_SUITE") or HOME / "GrayMatterEnvironment")
PY = SUITE / "graymatter" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
RUN = uuid.uuid4().hex[:8]
results: list = []


def check(group: str, name: str):
    def deco(fn):
        def run(only):
            if only and group not in only:
                return
            t0 = time.monotonic()
            try:
                status, detail = fn()
            except Exception as e:  # noqa: BLE001 — a crashing check is a FAIL, not a crash
                status, detail = "FAIL", f"{type(e).__name__}: {e}"
            results.append({"group": group, "check": name, "status": status,
                            "detail": str(detail)[:200], "ms": round((time.monotonic() - t0) * 1000)})
        CHECKS.append(run)
        return fn
    return deco


CHECKS: list = []


def ipc(msg: dict, timeout: float = 15) -> dict:
    """One daemon request through the suite's own client (same path as the hooks)."""
    code = ("import json,sys; from gray_matter.cli import _send_ipc; "
            "print(json.dumps(_send_ipc(json.loads(sys.argv[1]), float(sys.argv[2]))))")
    out = subprocess.run([str(PY), "-I", "-c", code, json.dumps(msg), str(timeout)],
                         capture_output=True, timeout=timeout + 10)
    return json.loads(out.stdout.decode("utf-8") or "null") or {}


def sh(cmd, payload: dict, shell: str = "cmd"):
    """Run a hook command the way its host does. "native": the whole string to the
    platform shell (Kimi: spawn with shell:true); a list for cmd /c re-quotes it."""
    argv = (cmd if shell == "native" else
            ["cmd.exe", "/c", cmd] if shell == "cmd" and os.name == "nt" else
            ["powershell.exe", "-NoProfile", "-Command", cmd] if shell == "powershell" else cmd)
    p = subprocess.run(argv, input=json.dumps(payload).encode(), capture_output=True,
                       timeout=60, shell=isinstance(argv, str))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "missing"


# --- daemon -------------------------------------------------------------------

@check("daemon", "suite python exists")
def _():
    return ("PASS", PY) if PY.exists() else ("FAIL", f"missing {PY}")


@check("daemon", "ping and workers")
def _():
    s = ipc({"action": "stats"})
    alive = s.get("workers_alive") or (s.get("result") or {}).get("workers_alive")
    if not isinstance(s, dict) or "error" in s or alive is None:
        return "FAIL", s
    return ("PASS" if {"neuron", "neurag"} <= set(alive) else "FAIL"), f"workers {alive}"


# --- recall -------------------------------------------------------------------

ON_TOPIC = "dove vive la memoria di Gray Matter sul mio PC?"
OFF_TOPIC = "ricetta della carbonara con guanciale"


@check("recall", "on-topic: facts, trimmed chrome")
def _():
    t = (ipc({"action": "recall", "prompt": ON_TOPIC, "session": f"smoke-{RUN}-a",
              "profile": False, "exclude": []}).get("result") or "")
    bad = [m for m in ("\n→ ", "turn=", "links:", "nodes:") if m in t]
    if "facts:" not in t or not t.startswith("[neuron] ctx=") or bad:
        return "FAIL", f"len {len(t)} chrome {bad} head {t[:80]!r}"
    return "PASS", f"{len(t)} chars"


@check("recall", "off-topic: no facts")
def _():
    t = (ipc({"action": "recall", "prompt": OFF_TOPIC, "session": f"smoke-{RUN}-b",
              "profile": False, "exclude": []}).get("result") or "")
    return ("FAIL", t[:160]) if "facts:" in t else ("PASS", f"{len(t)} chars, no facts")


# --- save check -----------------------------------------------------------------

@check("save", "saved: unknown, then no after a recall, unknown after an ack")
def _():
    s = f"smoke-{RUN}-c"
    first = ipc({"action": "saved", "session": s}).get("result")
    ipc({"action": "recall", "prompt": ON_TOPIC, "session": s, "profile": False, "exclude": []})
    second = ipc({"action": "saved", "session": s}).get("result")
    ipc({"action": "turn", "session": s, "worth": False})
    third = ipc({"action": "saved", "session": s}).get("result")
    ok = (first, second, third) == ("unknown", "no", "unknown")
    return ("PASS" if ok else "FAIL"), f"{first} / {second} / {third}"


# --- clients ------------------------------------------------------------------

@check("claude", "settings.json: SessionStart, UserPromptSubmit, Stop with a live interpreter")
def _():
    p = HOME / ".claude" / "settings.json"
    if not p.exists():
        return "SKIP", "Claude Code not configured"
    hooks = json.loads(p.read_text(encoding="utf-8-sig")).get("hooks", {})
    found = {}
    for ev in ("SessionStart", "UserPromptSubmit", "Stop"):
        cmds = [h.get("command", "") for g in hooks.get(ev, []) for h in g.get("hooks", [])]
        ours = [c for c in cmds if "gm_memhook" in c or "neuron_sessionstart_hook" in c]
        exe = ours[0].split('"')[1] if ours and ours[0].startswith('"') else (ours[0].split()[0] if ours else "")
        found[ev] = bool(ours) and Path(exe).exists()
    return ("PASS" if all(found.values()) else "FAIL"), found


def _toml_hooks() -> dict:
    import tomllib
    p = HOME / ".kimi-code" / "config.toml"
    cfg = tomllib.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
    return {h["event"]: h["command"] for h in cfg.get("hooks", [])
            if "gm_memhook" in h["command"] or "neuron_sessionstart_hook" in h["command"]}


@check("kimi", "hooks run with Kimi's input: recall text, Stop exit 2, ack ignored")
def _():
    h = _toml_hooks()
    if not h:
        return "SKIP", "Kimi Code not configured"
    if set(h) != {"SessionStart", "UserPromptSubmit", "Stop"}:
        return "FAIL", f"events {sorted(h)}"
    s = f"smoke-{RUN}-kimi"
    rc1, out1, _ = sh(h["UserPromptSubmit"], {"hook_event_name": "UserPromptSubmit", "session_id": s, "prompt": ON_TOPIC}, "native")
    rc2, _, err2 = sh(h["Stop"], {"hook_event_name": "Stop", "session_id": s, "stop_hook_active": False}, "native")
    rc3, out3, _ = sh(h["UserPromptSubmit"], {"hook_event_name": "UserPromptSubmit", "session_id": s, "prompt": "ok"}, "native")
    ok = rc1 == 0 and out1.startswith("[neuron]") and rc2 == 2 and err2.startswith("[memory]") and rc3 == 0 and not out3
    return ("PASS" if ok else "FAIL"), f"recall rc{rc1} {len(out1)}ch | stop rc{rc2} | ack rc{rc3}"


@check("codex", "hooks.json run in cmd and PowerShell: JSON recall, Stop block")
def _():
    p = HOME / ".codex" / "hooks.json"
    if not p.exists():
        return "SKIP", "Codex hooks.json missing"
    cfg = json.loads(p.read_text(encoding="utf-8-sig"))["hooks"]
    cmd = {e: next((h["command"] for g in cfg.get(e, []) for h in g["hooks"] if "gm_memhook" in h["command"]), "")
           for e in ("UserPromptSubmit", "Stop")}
    if not all(cmd.values()):
        return "FAIL", f"missing {cmd}"
    seen = []
    for shell in ("cmd", "powershell"):
        s = f"smoke-{RUN}-codex-{shell}"
        rc, out, _ = sh(cmd["UserPromptSubmit"], {"hook_event_name": "UserPromptSubmit", "session_id": s,
                                                  "transcript_path": None, "prompt": ON_TOPIC}, shell)
        ev = json.loads(out)["hookSpecificOutput"]["hookEventName"] if rc == 0 and out.strip() else "-"
        rc2, out2, _ = sh(cmd["Stop"], {"hook_event_name": "Stop", "session_id": s, "stop_hook_active": False,
                                        "last_assistant_message": "x" * 700}, shell)
        dec = json.loads(out2).get("decision") if rc2 == 0 and out2.strip() else "-"
        seen.append(f"{shell}: {ev}/{dec}")
        if ev != "UserPromptSubmit" or dec != "block":
            return "FAIL", "; ".join(seen)
    return "PASS", "; ".join(seen)


@check("opencode", "plugin dir registered, loads, registers the context hook")
def _():
    cfgp = HOME / ".config" / "opencode" / "opencode.json"
    if not cfgp.exists():
        return "SKIP", "OpenCode not configured"
    plugins = json.loads(cfgp.read_text(encoding="utf-8-sig")).get("plugin", [])
    ours = [p for p in plugins if "neuron-handshake" in str(p)]
    pdir = cfgp.parent / "plugins" / "neuron-handshake"
    if ours != ["./plugins/neuron-handshake"] or not (pdir / "index.mjs").exists():
        return "FAIL", f"entries {ours}, index.mjs {(pdir / 'index.mjs').exists()}"
    if not shutil.which("node"):
        return "SKIP", "node not on PATH"
    js = ("const m=(await import(process.argv[1])).default;const h=[];"
          "await m.setup({session:{hook:async(n)=>h.push(n),prompt:async()=>{}},"
          "event:{subscribe:()=>(async function*(){})()}});console.log(JSON.stringify(h))")
    url = (pdir / "index.mjs").resolve().as_uri()
    p = subprocess.run(["node", "--input-type=module", "-e", js, url], capture_output=True, timeout=30)
    hooks = p.stdout.decode().strip()
    return ("PASS" if p.returncode == 0 and "context" in hooks else "FAIL"), hooks or p.stderr.decode()[:160]


# --- cohesion -----------------------------------------------------------------

@check("cohesion", "plugin and deployer copies are identical, deploys match the repo")
def _():
    groups = {
        "plugin": [REPO / "neuron/src/neuron/clients/opencode-plugin/neuron-handshake.mjs",
                   REPO / "neurag/clients/opencode-plugin/neuron-handshake.mjs",
                   HOME / ".config/opencode/plugins/neuron-handshake/index.mjs"],
        "deploy_hooks": [REPO / "neuron/src/neuron/clients/deploy_hooks.py",
                         REPO / "neurag/clients/deploy_hooks.py"],
        "memhook": [REPO / "gray_matter/memhook.py", HOME / ".claude/hooks/gm_memhook.py",
                    HOME / ".kimi-code/hooks/gm_memhook.py", HOME / ".codex/hooks/gm_memhook.py"],
    }
    drift = {}
    for name, files in groups.items():
        sums = {str(f.relative_to(HOME) if HOME in f.parents else f.relative_to(REPO)): md5(f)
                for f in files if f.exists() or HOME not in f.parents}
        if len(set(sums.values())) > 1:
            drift[name] = {k: v[:6] for k, v in sums.items()}
    return ("FAIL", drift) if drift else ("PASS", "all copies identical")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated groups")
    a = ap.parse_args(argv)
    only = {g for g in a.only.split(",") if g}
    for run in CHECKS:
        run(only)
    failed = [r for r in results if r["status"] == "FAIL"]
    if a.json:
        print(json.dumps({"run": RUN, "failed": len(failed), "results": results}, indent=2))
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        for r in results:
            print(f"{r['status']:4}  {r['group']:9} {r['check'][:62]:62} {r['ms']:>6}ms  {r['detail']}")
        print(f"\n{len(results) - len(failed)}/{len(results)} ok" + (f", {len(failed)} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
