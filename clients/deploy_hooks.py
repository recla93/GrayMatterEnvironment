#!/usr/bin/env python3
"""Deploy the handshake assets for a STANDALONE install.

Gray Matter's installer deploys these through `gray_matter.executor`. A
standalone Neuron or NeuRAG has no Gray Matter, so without this the model got
no handshake at all on the one install shape where the MCP `instructions`
field is the only other channel -- and that field is host-optional.

Deliberately stdlib-only and idempotent: all three tools deploy the SAME files
to the SAME paths, so running it twice (or from two tools) is a no-op rather
than a double handshake. Ownership is resolved at runtime by the hook itself,
never here.

Usage:  python deploy_hooks.py [--dry-run]
Run from the directory that contains claude-code-hook/ (i.e. this file's dir).

KEEP IN SYNC: byte-identical copies live in neuron/src/neuron/clients/ and
neurag/clients/. `test_handshake.py` fails if they drift.
"""

import json
import os
import shutil
import sys
from pathlib import Path

HOOK = "claude-code-hook/neuron_sessionstart_hook.py"
OPENCODE = "opencode-plugin/neuron-handshake.mjs"
COWORK = "cowork-plugin/neuron-guard"

_MATCHER = "startup|resume|clear|compact"


def _load_json(p: Path):
    try:
        raw = p.read_text(encoding="utf-8-sig")
        return json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError):
        return None            # missing OR unparseable: caller decides


def _save_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        shutil.copyfile(p, p.with_suffix(p.suffix + ".bak"))
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def deploy_claude_code(root: Path, dry_run: bool) -> str:
    """Copy the hook and register it under hooks.SessionStart."""
    src = root / HOOK
    dst_dir = Path.home() / ".claude" / "hooks"
    dst = dst_dir / src.name
    settings = Path.home() / ".claude" / "settings.json"
    data = _load_json(settings)
    if data is None and settings.exists():
        # Never rewrite a config we cannot parse -- say so instead.
        return f"SKIPPED: {settings} is not parseable JSON, left untouched"
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return f"SKIPPED: {settings} root is not a JSON object"

    cmd = f'python "{dst}"'
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return f"SKIPPED: {settings} 'hooks' is not an object"
    starts = hooks.setdefault("SessionStart", [])
    if not isinstance(starts, list):
        return f"SKIPPED: {settings} 'SessionStart' is not a list"

    # Match on the SCRIPT, not on the exact command string. Gray Matter
    # registers it as `"<venv>\python.exe" "<hook>"` and this deployer as
    # `python "<hook>"`; comparing whole strings saw those as different and
    # appended a second entry -- the double handshake, back again, from the
    # very code meant to prevent it. Observed on a live machine.
    already = any(
        isinstance(e, dict)
        and any(isinstance(h, dict) and src.name in (h.get("command") or "")
                for h in (e.get("hooks") or []))
        for e in starts
    )
    if dry_run:
        return f"[dry-run] would deploy {dst}" + ("" if already else " + SessionStart entry")
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    if not already:
        starts.append({"matcher": _MATCHER,
                       "hooks": [{"type": "command", "command": cmd, "timeout": 10}]})
        _save_json(settings, data)
        return f"hook copied + SessionStart registered ({dst})"
    return f"hook refreshed ({dst})"


def deploy_opencode(root: Path, dry_run: bool) -> str:
    """Copy the plugin next to opencode.json and list it in `plugin`."""
    cfg = Path.home() / ".config" / "opencode" / "opencode.json"
    if not cfg.exists():
        return "SKIPPED: OpenCode not configured on this machine"
    data = _load_json(cfg)
    if data is None:
        return f"SKIPPED: {cfg} is not parseable JSON, left untouched"
    dst = cfg.parent / "plugins" / (root / OPENCODE).name
    rel = f"./plugins/{dst.name}"
    plugins = data.setdefault("plugin", [])
    if not isinstance(plugins, list):
        return f"SKIPPED: {cfg} 'plugin' is not a list"
    if dry_run:
        return f"[dry-run] would deploy {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / OPENCODE, dst)
    if rel not in plugins:
        plugins.append(rel)
        _save_json(cfg, data)
        return f"plugin copied + registered ({dst})"
    return f"plugin refreshed ({dst})"


def deploy_cowork(root: Path, dry_run: bool) -> str:
    """Mirror the plugin directory into the Cowork/Codex plugin cache.

    A MIRROR, not a copy: files removed from the source are removed from the
    deployed copy too. A stale `neuron_handshake.py` survived here for months
    telling the model to call `mcp__neuron5__*` tools that no longer existed,
    precisely because deploy only ever added.
    """
    src = root / COWORK
    if not src.is_dir():
        return "SKIPPED: cowork plugin assets missing"
    base = Path.home() / ".codex" / "plugins" / "cache" / "claude-cowork"
    if not base.is_dir():
        return "SKIPPED: Cowork/Codex plugin cache not present"
    dst = base / "neuron-guard" / "0.1.0"
    if dry_run:
        return f"[dry-run] would mirror {dst}"
    keep = set()
    for f in src.rglob("*"):
        if f.is_file():
            rel = f.relative_to(src)
            keep.add(rel)
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, out)
    removed = 0
    if dst.is_dir():
        for f in list(dst.rglob("*")):
            if f.is_file() and f.relative_to(dst) not in keep:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
    return f"plugin mirrored ({dst})" + (f", {removed} stale file(s) removed" if removed else "")


def main(argv) -> int:
    dry = "--dry-run" in argv
    root = Path(__file__).resolve().parent
    if not (root / HOOK).exists():
        print(f"deploy_hooks: assets not found under {root}", file=sys.stderr)
        return 1
    for name, fn in (("claude-code", deploy_claude_code),
                     ("opencode", deploy_opencode),
                     ("cowork", deploy_cowork)):
        try:
            print(f"  [{name}] {fn(root, dry)}")
        except Exception as exc:            # noqa: BLE001 — never fail an install
            print(f"  [{name}] SKIPPED: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
