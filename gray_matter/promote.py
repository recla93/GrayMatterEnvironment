"""CLS consolidation: memory that proved itself becomes knowledge.

DESIGN-EVOLUTION §5.3, by facts since ADR-016 D8 (2026-11-08):

    hippocampus  fast, episodic, append-only facts        -> Neuron
    neocortex    slow, semantic, permanent                -> NeuRAG
    consolidation  facts that proved useful, replayed     -> this module

What gets promoted is a FACT, never a node: a `decision`, `fix` or `fact` that
is active (never superseded), old enough to be stable, and confirmed at least
once (ADR-015 D8: shown and then reused, cited, superseded or confirmed).
**Never** `user` or `habit`: they are the user's, and the vault is shared.
The node-based rules (trust, strong links, co-activation) promoted names whose
"chunks" were link rationales and logs; a fact is already one sentence with its
why.

Each promoted fact becomes a chunk with its provenance (`neuron:#id`) under a
node named after its first concept, and a bridge `#id <-> node` — the pointer
ADR-015 §6 asks Neuron to keep, and the record that stops a second promotion.

**Report first.** A promoted chunk does not decay, so `promote` is a dry run
unless asked. Only GM does this; standalone Neuron simply never promotes (I2).
"""
from __future__ import annotations

# Where promoted facts live in the vault: one godnode, so the tree keeps the
# ingested documents on one side and the memory that earned permanence on the other.
PROMOTE_PARENT = "memoria promossa"

PROMOTE_RULES = {
    "kinds": ("decision", "fix", "fact"),
    "min_age_turns": 20,     # survived long enough to be stable, not merely recent
    "min_confirmed": 1,      # used at least once (ADR-015 D8)
}


def candidates(export: dict, rules: dict | None = None,
               promoted: "set[str] | None" = None) -> list[dict]:
    """Facts eligible for promotion, grouped by node (first concept), best first.

    `export` is Neuron's `export` payload; `promoted` the fact ids already in the
    vault (their `#id` bridges). Reading the tool rather than the DB keeps GM an
    orchestrator: it never opens someone else's store (I3)."""
    r = {**PROMOTE_RULES, **(rules or {})}
    turn_count = int(export.get("turn_count") or 0)
    done = promoted or set()
    groups: dict[str, dict] = {}
    for f in export.get("facts") or []:
        if (f.get("status") != "active" or f.get("kind") not in r["kinds"]
                or f.get("id") in done):
            continue
        age = max(0, turn_count - int(f.get("turn") or 0))
        used = int(f.get("confirmed") or 0)
        if age < r["min_age_turns"] or used < r["min_confirmed"]:
            continue
        concepts = [str(c) for c in (f.get("concepts") or []) if str(c).strip()]
        node = concepts[0] if concepts else "memory"
        g = groups.setdefault(node, {"keyword": node, "facts": [], "chunks": [], "tags": [],
                                     "confirmed": 0, "age_turns": 0})
        g["facts"].append(f["id"])
        g["chunks"].append({"text": f["text"], "source": f"neuron:#{f['id']}",
                            "section": f["kind"]})
        g["tags"] += [c for c in concepts if c not in g["tags"]]
        g["confirmed"] += used
        g["age_turns"] = max(g["age_turns"], age)
    out = sorted(groups.values(), key=lambda g: (-g["confirmed"], -len(g["facts"])))
    for g in out:
        g["score"] = g["confirmed"]
    return out


def report_lines(cands: list[dict], applied: bool = False) -> list[str]:
    """Human-readable report. Says what WOULD happen unless it happened."""
    if not cands:
        return ["[ok] No fact above the promotion threshold.",
                f"     rules: {PROMOTE_RULES}"]
    n = sum(len(c["facts"]) for c in cands)
    verb = "Promoted" if applied else "To promote (dry run)"
    lines = [f"{verb}: {n} fact(s) into {len(cands)} NeuRAG node(s)"]
    for c in cands[:40]:
        lines.append(f"  {c['keyword']}  (confirmed {c['confirmed']}, "
                     f"{c['age_turns']} turns)  [{', '.join(c['tags'][:5])}]")
        for ch in c["chunks"]:
            lines.append(f"      {ch['source']} {ch['section']}: {ch['text'][:110]}")
    if not applied:
        lines += ["", f"Nothing was written. With --apply each fact becomes a chunk under "
                      f"'{PROMOTE_PARENT}' and a bridge #id <-> node. A promoted chunk does "
                      "not decay: read the lines first."]
    return lines


def demo() -> None:
    """Runnable self-check (stdlib only)."""
    exp = {"turn_count": 100, "facts": [
        {"id": "a1", "kind": "decision", "text": "Turso in local too", "turn": 10,
         "status": "active", "confirmed": 2, "concepts": ["turso"]},
        {"id": "a2", "kind": "habit", "text": "user tests first", "turn": 10,
         "status": "active", "confirmed": 5, "concepts": ["turso"]},
        {"id": "a3", "kind": "fix", "text": "too new", "turn": 95,
         "status": "active", "confirmed": 3, "concepts": ["wal"]},
        {"id": "a4", "kind": "fix", "text": "never used", "turn": 10,
         "status": "active", "confirmed": 0, "concepts": ["wal"]},
        {"id": "a5", "kind": "fix", "text": "replaced", "turn": 10,
         "status": "superseded", "confirmed": 4, "concepts": ["wal"]},
    ]}
    got = candidates(exp)
    assert [(c["keyword"], c["facts"]) for c in got] == [("turso", ["a1"])], got
    assert got[0]["chunks"] == [{"text": "Turso in local too", "source": "neuron:#a1",
                                 "section": "decision"}]
    assert candidates(exp, promoted={"a1"}) == []
    print("promote OK: active, old enough, used; never user/habit")


if __name__ == "__main__":
    demo()
