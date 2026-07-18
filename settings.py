"""Tunable knobs for Gray-Matter — the 'sensibilità' surface (INSTALLER-UX §8).

One JSON config (`paths.config_file()`) so flash rate, cache TTL, etc. can be tuned
via `gray-matter config get|set` (and the GUI) without editing code. Only known keys
are accepted; values are coerced to the default's type; the file stores only the
overrides (so DEFAULTS can evolve). Stdlib only.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "flash_min_gap": 3,           # pulses between flashes (anti-spam)
    "cache_ttl_seconds": 60,      # context cache TTL
    "cache_max_size": 100,        # context cache LRU cap
    "prewarm": True,              # pre-warm workers at start (D2)
    "heartbeat_interval": 5.0,    # server liveness ping (s)
    "idle_sleep_timeout": 600.0,  # idle before sleep (s)
}


def _coerce(default, value):
    if isinstance(default, bool):
        return value.strip().lower() in ("1", "true", "yes", "on") if isinstance(value, str) else bool(value)
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return str(value)


def _config_path(path=None):
    if path is not None:
        return Path(path)
    from gray_matter import paths as _paths   # lazy: keeps the knob logic import-free
    return _paths.config_file()


def load(path=None) -> dict:
    """DEFAULTS overlaid with the user's config.json (known keys only, type-coerced)."""
    out = dict(DEFAULTS)
    try:
        raw = json.loads(Path(_config_path(path)).read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    for k, v in (raw or {}).items():
        if k in DEFAULTS:
            try:
                out[k] = _coerce(DEFAULTS[k], v)
            except Exception:
                pass
    return out


def get(key, path=None):
    return load(path).get(key)


def set(key, value, path=None) -> dict:
    """Set one known knob (type-coerced), persist only the overrides, return merged."""
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting '{key}' (known: {', '.join(sorted(DEFAULTS))})")
    cfg = load(path)
    cfg[key] = _coerce(DEFAULTS[key], value)
    p = Path(_config_path(path))
    p.parent.mkdir(parents=True, exist_ok=True)
    overrides = {k: v for k, v in cfg.items() if v != DEFAULTS[k]}
    p.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg
