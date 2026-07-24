"""GM-level .env loader — env model daemon→worker (DESIGN-CLOUD-MEMORY §Action 2).

Problem: Neuron finds its `.env` by walking up from the *cwd*; when the GM
daemon spawns the persistent workers (`_worker.py`) the cwd is arbitrary, so
worker processes never see the saved cloud credentials. NeuRAG has no loader
at all.

Fix (one flow): the daemon loads `<gm_home>/.env` into ``os.environ`` at
package import — before `bridges.py` resolves its tier and before any worker
is spawned. Workers inherit the daemon's environment (Popen without ``env=``),
so one GM-level file feeds all three stores:

    GM_TURSO_DATABASE_URL / GM_TURSO_AUTH_TOKEN         (bridges)
    TURSO_DATABASE_URL / TURSO_AUTH_TOKEN               (Neuron)
    NEURAG_TURSO_DATABASE_URL / NEURAG_TURSO_AUTH_TOKEN (NeuRAG)

Keep-in-sync with Neuron's `_env.py` (dual-implementation principle), same
guarantees: real environment always wins (setdefault); disabled under pytest
and via ``GM_NO_DOTENV=1``; runs at most once; never raises.
Explicit file override: ``GM_ENV_FILE``.
"""
from __future__ import annotations

import os
import sys

_loaded = False


def _default_env_file() -> str:
    from gray_matter.paths import gm_home
    return str(gm_home() / ".env")


def _is_test_run() -> bool:
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def load_dotenv_once(path: str | None = None) -> bool:
    """Populate os.environ from the GM .env (real env wins). Returns True if a
    file was read. No-op under pytest / GM_NO_DOTENV, and after the first call."""
    global _loaded
    if _loaded:
        return False
    _loaded = True
    if os.environ.get("GM_NO_DOTENV", "").strip():
        return False
    if _is_test_run():
        return False
    try:
        path = path or os.environ.get("GM_ENV_FILE", "").strip() or _default_env_file()
        if not os.path.isfile(path):
            return False
        # utf-8-sig: PS 5.1 `Set-Content -Encoding utf8` scrive il BOM (audit
        # 2026-07-21); il lstrip sotto resta come cintura per BOM mid-file.
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip().lstrip("\ufeff")
                if key:
                    os.environ.setdefault(key, _unquote(val))
    except OSError:
        return False
    return True
