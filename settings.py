"""Tunable knobs for Gray-Matter — the 'sensibilità' surface (INSTALLER-UX §8).

One JSON config (`paths.config_file()`) so flash rate, cache TTL, etc. can be tuned
via `gray-matter config get|set` (and the GUI) without editing code. Only known keys
are accepted; values are coerced to the default's type; the file stores only the
overrides (so DEFAULTS can evolve). Stdlib only.

HELP is not decoration: the control center builds its settings card from
`<tool> config list --json`, so a knob without help text renders as a bare
value. GM owns exactly the knobs that decide how much gets injected into a
model's context, and for a long time it was the ONE tool of the three with no
`config` command at all — the panel simply never appeared, and every knob here
was reachable only by editing the JSON by hand.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "flash_min_gap": 3,           # pulses between flashes (anti-spam)
    "stimulus_safety_net": True,  # GM re-launches the stimulus if Neuron's piggyback goes silent
    "stimulus_safety_gap": 5,     # tool turns without 🧠/⚡ before the safety net fires
    "cache_ttl_seconds": 60,      # context cache TTL
    "cache_max_size": 100,        # context cache LRU cap
    "prewarm": True,              # pre-warm workers at start (D2)
    "heartbeat_interval": 5.0,    # server liveness ping (s)
    "idle_sleep_timeout": 600.0,  # idle before sleep (s)
    # -- quanto contesto GM inietta -------------------------------------------
    # Il punto di tutto il progetto è FAR RISPARMIARE token, quindi la quantità
    # iniettata è un budget, non un effetto collaterale.
    "knowledge_top_n": 5,          # chunk di vault per pulse (1-10)
    # Memoria (Neuron): `get_context` applica già un budget in caratteri da
    # `max_tokens`, ma GM non glielo passava, quindi la voce più antica della
    # pulse era l'unica che l'utente non poteva toccare. Il default è lo stesso
    # del tool: cambiare knob è una scelta, non un effetto dell'averlo esposto.
    "memory_max_tokens": 400,
    # Tetto ai contenuti PROATTIVI (bridge, vicini, flash): quelli che l'utente
    # non ha chiesto. Erano senza cap: 40 bridge che condividevano un tag
    # facevano ~5000 token in una sola pulse, e ogni bridge mostrato viene anche
    # rinforzato, quindi un match di massa era una promozione di massa.
    "proactive_budget_chars": 800,
    # Tool usciti dal gateway (go-standalone): csv fra "neuron","neurag". GM non
    # li spawna né li ripubblica finché stanno qui; `register --gateway` azzera.
    "unmanaged": "",
}

# Per-knob help surfaced by the control center (GUI reads these via
# `gray-matter config list --json` — keep-in-sync with the knobs above, same
# rule as neurag/settings.py).
HELP = {
    "flash_min_gap": "Quante pulse passano fra due flash (richiami "
                     "serendipitosi). Più alto = meno interruzioni.",
    "stimulus_safety_net": "Se Neuron smette di agganciare lo stimolo alle "
                           "risposte, GM lo rilancia da sé.",
    "stimulus_safety_gap": "Quanti turni di silenzio prima che la rete di "
                           "sicurezza dello stimolo scatti.",
    "cache_ttl_seconds": "Per quanto una risposta di contesto resta valida in "
                         "cache. Più alto = meno lavoro ripetuto, dati più vecchi.",
    "cache_max_size": "Quante risposte di contesto tenere in cache (LRU).",
    "prewarm": "Scalda i worker all'avvio: prima pulse più veloce, un po' di "
               "RAM in più subito.",
    "heartbeat_interval": "Ogni quanti secondi GM verifica che i suoi server "
                          "siano vivi.",
    "idle_sleep_timeout": "Secondi di inattività prima che GM vada in sleep.",
    "knowledge_top_n": "Quanti chunk di conoscenza iniettare per pulse. È la "
                       "voce più costosa in token: 5 sono circa 300 token, 10 "
                       "circa 700. Abbassalo se il contesto è stretto.",
    "memory_max_tokens": "Tetto in token per il contesto di memoria (Neuron) in "
                         "una pulse. Sono i concetti e i legami già noti: costa "
                         "meno della conoscenza ma è la voce più costante.",
    "proactive_budget_chars": "Tetto in caratteri per ciò che GM aggiunge SENZA "
                              "che tu l'abbia chiesto (bridge, vicini, flash). "
                              "0 = niente contenuti proattivi, solo le risposte "
                              "vere. ~4 caratteri = 1 token.",
    "unmanaged": "Tool sganciati dal gateway (csv fra neuron, neurag): GM non "
                 "li avvia né li ripubblica finché stanno qui.",
}

SUGGEST = {
    "knowledge_top_n": ["3", "5", "10"],
    "memory_max_tokens": ["150", "400", "800"],
    "proactive_budget_chars": ["0", "400", "800", "2000"],
    "unmanaged": ["", "neuron", "neurag", "neuron,neurag"],
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
