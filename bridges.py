"""Cross-store bridges — the orchestrator's own memory.

A bridge is a persisted link between a Neuron concept and a NeuRAG knowledge
node: a connection only Gray-Matter (sitting between the two stores) can see.
Persisted so a connection is *discovered once* and *recalled cheaply* forever.

Tiny JSON store (a bridge set is small). Path overridable via GRAY_MATTER_BRIDGES
(for tests). This is the only place Gray-Matter writes — see ARCHITETTURA.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


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


def add_bridge(neuron_concept: str, neurag_node: str, rationale: str = "") -> bool:
    """Record a bridge. Idempotent on (neuron_concept, neurag_node); returns False
    if it already exists."""
    bridges = _load()
    key = (neuron_concept.strip().lower(), neurag_node.strip().lower())
    for b in bridges:
        if (b["neuron"].strip().lower(), b["neurag"].strip().lower()) == key:
            return False
    bridges.append({"neuron": neuron_concept, "neurag": neurag_node, "rationale": rationale})
    _save(bridges)
    return True


def bridges_for(topic: str) -> list[dict]:
    """Bridges whose Neuron or NeuRAG endpoint overlaps the topic (either direction)."""
    t = topic.strip().lower()
    if not t:
        return []
    out = []
    for b in _load():
        n, r = b["neuron"].lower(), b["neurag"].lower()
        if n in t or r in t or t in n or t in r:
            out.append(b)
    return out


def all_bridges() -> list[dict]:
    return _load()
