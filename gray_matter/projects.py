"""Which Neuron context a session works in, from the folder it works in.

One pointer file used to decide the context for every session on the machine:
on 2026-11-26 one session switched it and another session's facts went to the
wrong graph. Now the session's folder decides, by the project's IDENTITY, not
its path: the same project lived under four paths in the OpenCode history
(renamed folders, a nested clone, an isolated copy), so a path list alone would
have split it in four.

Resolution, most certain first, stopping at the NEAREST root above the folder:
  1. a `.neuron-project` file: its first line is the context (explicit choice);
  2. a git root: the origin remote, normalised, looked up in projects.json;
  3. a known path in projects.json.
Nothing found -> "" and the caller keeps today's behaviour. Never a guess: 83% of
the OpenCode messages came from C:\\Windows\\System32, where no project is."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

MARKER = ".neuron-project"
_REMOTE = re.compile(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', re.S)


def _key(url: str) -> str:
    """`https://github.com/A/B.git`, `git@github.com:A/B` -> `github.com/a/b`."""
    u = url.strip().lower()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)            # user@ (ssh or https credentials)
    u = u.replace(":", "/", 1) if "/" not in u.split(":", 1)[0] and ":" in u else u
    return re.sub(r"\.git/?$", "", u).strip("/")


def _git_config(root: Path) -> "Path | None":
    dot = root / ".git"
    if dot.is_dir():
        return dot / "config"
    if dot.is_file():                           # a worktree: `gitdir: <main>/.git/worktrees/x`
        m = re.match(r"gitdir:\s*(.+)", dot.read_text(encoding="utf-8", errors="replace").strip())
        if m:
            gd = Path(m.group(1).strip())
            gd = gd if gd.is_absolute() else (root / gd)
            common = gd / "commondir"
            base = (gd / common.read_text(encoding="utf-8").strip()) if common.is_file() else gd
            return base / "config"
    return None


def norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(p)) if p else ""


def _load(file: Path) -> dict:
    try:
        d = json.loads(file.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve(cwd: str, file: "Path | None" = None) -> str:
    """The context for a session working in `cwd`, or "" when nothing says."""
    if not cwd or not os.path.isdir(cwd):
        return ""
    if file is None:
        from gray_matter.paths import gm_home
        file = gm_home() / "projects.json"
    conf = _load(file)
    remotes = {_key(k): v for k, v in (conf.get("remotes") or {}).items()}
    paths = {norm_path(k): v for k, v in (conf.get("paths") or {}).items()}
    here = Path(os.path.abspath(cwd))
    for d in (here, *here.parents):
        marker = d / MARKER
        if marker.is_file():
            first = marker.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            if first and first[0].strip():
                return first[0].strip().lower().strip("/")
        if norm_path(str(d)) in paths:
            return str(paths[norm_path(str(d))])
        cfg = _git_config(d) if (d / ".git").exists() else None
        if cfg is not None:
            try:
                m = _REMOTE.search(cfg.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                m = None
            return str(remotes.get(_key(m.group(1)), "")) if m else ""
    return ""
