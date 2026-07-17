"""Cross-store bridges — the orchestrator's own memory, that *learns from use*.

A bridge is a persisted link between a Neuron concept and a NeuRAG knowledge
node: a connection only Gray-Matter (sitting between the two stores) can see.
Persisted so a connection is *discovered once* and *recalled cheaply* forever.

Auto-learning (B4): a bridge carries a `weight`. It grows every time the bridge
re-emerges or is surfaced in a pulse (Hebbian: co-occurrence = reinforcement),
and `decay()` shrinks bridges that go unused — an unconfirmed hypothesis that
never proves useful fades away. **Only bridges decay**; NeuRAG knowledge is a
permanent vault and is never touched here.

Tiny JSON store. Path overridable via GRAY_MATTER_BRIDGES (for tests). This is
the only place Gray-Matter writes — see ARCHITETTURA.md.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

_WEIGHT_CAP = 1000          # weights are relative; cap keeps them bounded
_MAX_LEN = 200              # ingest guard: longer endpoints are pasted blobs, not concepts
_MIN_LEN = 2                # a 1-char endpoint substring-matches almost every topic -> noise


def _clean(s, cap: int = _MAX_LEN) -> str:
    """Normalize a string entering the store: coerce to str, strip, collapse inner
    whitespace, cap length. The single choke-point for anything ingested (F4)."""
    if not isinstance(s, str):
        s = str(s or "")
    return " ".join(s.split())[:cap]


def _valid_endpoint(s: str) -> bool:
    """A usable bridge endpoint: non-trivial, not an oversized blob."""
    return _MIN_LEN <= len(s) <= _MAX_LEN


def _store() -> Path:
    p = os.environ.get("GRAY_MATTER_BRIDGES")
    return Path(p) if p else Path.home() / ".local" / "share" / "gray_matter" / "bridges.json"


def _load() -> list[dict]:
    try:
        return json.loads(_store().read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(bridges: list[dict]) -> None:
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bridges, ensure_ascii=False, indent=2), encoding="utf-8")


def _bump(b: dict) -> None:
    b["weight"] = min(b.get("weight", 1) + 1, _WEIGHT_CAP)
    b["last_used"] = time.time()


def add_bridge(neuron_concept: str, neurag_node: str, rationale: str = "") -> bool:
    """Record a bridge. Idempotent on (neuron_concept, neurag_node). If it already
    exists, its weight is reinforced (+1) and False is returned; a brand-new bridge
    returns True.

    Ingest validation (F4): endpoints are cleaned and must be non-trivial; junk
    (empty, 1-char, oversized blobs) and self-bridges are rejected -> False, no
    write. This is the only write path, so validating here covers both the manual
    `gray_matter_bridge` tool and the v3b auto-discovery in pulse."""
    neuron_concept, neurag_node = _clean(neuron_concept), _clean(neurag_node)
    rationale = _clean(rationale, cap=500)
    if not (_valid_endpoint(neuron_concept) and _valid_endpoint(neurag_node)):
        return False
    if neuron_concept.lower() == neurag_node.lower():
        return False                                   # self-bridge carries no cross-store info
    bridges = _load()
    key = (neuron_concept.strip().lower(), neurag_node.strip().lower())
    for b in bridges:
        if (b["neuron"].strip().lower(), b["neurag"].strip().lower()) == key:
            _bump(b)                                   # re-emergence = reinforcement
            if rationale and not b.get("rationale"):
                b["rationale"] = rationale
            _save(bridges)
            return False
    now = time.time()
    bridges.append({"neuron": neuron_concept, "neurag": neurag_node,
                    "rationale": rationale, "weight": 1,
                    "created": now, "last_used": now})
    _save(bridges)
    return True


def bridges_for(topic: str) -> list[dict]:
    """Bridges whose Neuron or NeuRAG endpoint overlaps the topic (either
    direction). Surfacing a bridge in a pulse *is* using it → reinforce it.
    Returned strongest-first."""
    t = topic.strip().lower()
    if not t:
        return []
    bridges = _load()
    out, touched = [], False
    for b in bridges:
        n, r = b["neuron"].lower(), b["neurag"].lower()
        if n in t or r in t or t in n or t in r:
            _bump(b)                                   # recalled in a pulse = used
            touched = True
            out.append(b)
    if touched:
        _save(bridges)
    out.sort(key=lambda b: b.get("weight", 1), reverse=True)
    return out


def decay(amount: float = 1.0, max_idle_seconds: float = 7 * 24 * 3600,
          prune_below: float = 1.0) -> int:
    """Maintenance: a bridge not surfaced within `max_idle_seconds` loses `amount`
    weight; one that falls below `prune_below` is dropped. Returns how many were
    pruned. Bridges are *hypotheses* — the unconfirmed ones that never get used
    fade. Call from GM's idle/maintenance pass."""
    bridges = _load()
    now = time.time()
    kept, changed = [], False
    for b in bridges:
        if now - b.get("last_used", now) > max_idle_seconds:
            b["weight"] = b.get("weight", 1) - amount
            changed = True
        if b.get("weight", 1) >= prune_below:
            kept.append(b)
        else:
            changed = True
    if changed:
        _save(kept)
    return len(bridges) - len(kept)


def all_bridges() -> list[dict]:
    return sorted(_load(), key=lambda b: b.get("weight", 1), reverse=True)
