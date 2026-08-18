"""CLS consolidation: memory that proved itself becomes knowledge.

DESIGN-EVOLUTION §5.3. The McClelland/O'Reilly model, two thirds of which the
suite already was:

    hippocampus  fast, episodic, decays, pattern-separates  -> Neuron
    neocortex    slow, semantic, permanent, completes       -> NeuRAG
    consolidation  stable traces replayed to cortex         -> missing

`sleep_maybe()` consolidates Neuron *within itself* and never writes to NeuRAG,
so a concept reinforced across 200 turns — high salience, high trust, stable —
stays in the decaying store forever and never becomes permanent knowledge. GM's
bridges *observe* that correlation; this acts on it.

**Report first.** The cut points below have never been measured on a real graph,
and the failure mode of guessing them is a knowledge base full of promoted
noise — which, unlike a bad bridge, does not decay. So `promote` is a dry run
unless asked, exactly like `neurag park` (§8.2).

Only GM does this. Standalone Neuron keeps working with no promotion at all —
not a degraded mode, just Neuron as it is today (I2).
"""
from __future__ import annotations

# Constants, not literals, in the shape of Neuron's RANK_WEIGHTS: they need real
# graph data and they WILL move (§8.2).
#
# Three floors rather than one product: the design describes the threshold as
# "salience x trust x age", and that product is what ranks the report — but a
# single number hides WHICH factor carried a candidate. A concept can reach a
# high product on salience alone while never having been confirmed once, and
# that is exactly the thing not to make permanent. Every floor must be met.
PROMOTE_RULES = {
    "min_salience": 5,      # reinforced repeatedly, not a one-off
    "min_trust": 0.5,       # actually confirmed useful (B2 feedback), not just frequent
    "min_age_turns": 50,    # survived long enough to be stable, not merely hot
}


def score(node: dict, turn_count: int) -> float:
    """salience x trust x age, normalized enough to be comparable across graphs.

    Ranking only — eligibility is the floors. Age is in turns since the concept
    first appeared, which is Neuron's own clock; wall-clock would punish a graph
    that sat unused for a month, and sitting unused is not evidence."""
    age = max(0, int(turn_count) - int(node.get("turn", 0)))
    return float(node.get("salience", 0)) * float(node.get("trust", 0.0)) * (age / 100.0)


def candidates(export: dict, rules: dict | None = None) -> list[dict]:
    """Concepts eligible for promotion, best first, with the reason.

    `export` is Neuron's `export` payload — {turn_count, nodes:[...]}. Reading
    it through the tool rather than the DB keeps GM an orchestrator: it never
    opens someone else's vault (I3), and never fights the single writer.
    """
    r = {**PROMOTE_RULES, **(rules or {})}
    turn_count = int(export.get("turn_count") or 0)
    out = []
    for nd in export.get("nodes") or []:
        salience = float(nd.get("salience", 0) or 0)
        trust = float(nd.get("trust", 0.0) or 0.0)
        age = max(0, turn_count - int(nd.get("turn", 0) or 0))
        if salience < r["min_salience"] or trust < r["min_trust"] \
                or age < r["min_age_turns"]:
            continue
        out.append({
            "keyword": nd.get("keyword", ""),
            "topic": nd.get("topic", "") or "",
            "domain": nd.get("domain", "") or "",
            # The tags it ALREADY shares are what the promoted node gets: §4 made
            # the tag the one object both stores agree on, so a promotion joins
            # the two graphs instead of dropping an orphan into NeuRAG.
            "tags": [str(t) for t in (nd.get("tags") or [])],
            "salience": salience,
            "trust": round(trust, 3),
            "age_turns": age,
            "score": round(score(nd, turn_count), 3),
        })
    out.sort(key=lambda c: -c["score"])
    return [c for c in out if c["keyword"]]


def report_lines(cands: list[dict], applied: bool = False) -> list[str]:
    """Human-readable report. Says what WOULD happen unless it happened."""
    if not cands:
        return ["[ok] Nessun concetto sopra la soglia di promozione.",
                f"     soglie: {PROMOTE_RULES}"]
    verb = "Promossi" if applied else "Da promuovere (dry run)"
    lines = [f"{verb}: {len(cands)} concetto/i Neuron -> nodi NeuRAG"]
    for c in cands[:40]:
        tags = (", ".join(c["tags"][:5]) or "nessun tag")
        lines.append(f"  {c['score']:>7.3f}  {c['keyword']}"
                     f"   (salienza {c['salience']:.0f}, trust {c['trust']}, "
                     f"{c['age_turns']} turni)  [{tags}]")
    if not applied:
        lines.append("")
        lines.append("Niente è stato scritto. Con --apply diventano nodi NeuRAG.")
        lines.append("Un nodo promosso NON decade: le soglie non sono ancora "
                     "misurate su un grafo reale, leggi la lista prima.")
    return lines


def demo() -> None:
    """Runnable self-check (stdlib only): the floors are AND, not OR."""
    exp = {"turn_count": 200, "nodes": [
        {"keyword": "quorum", "salience": 9, "trust": 0.8, "turn": 10, "tags": ["raft"]},
        {"keyword": "hot_but_unconfirmed", "salience": 40, "trust": 0.0, "turn": 10},
        {"keyword": "trusted_but_new", "salience": 9, "trust": 0.9, "turn": 199},
        {"keyword": "rare", "salience": 1, "trust": 0.9, "turn": 10},
    ]}
    got = [c["keyword"] for c in candidates(exp)]
    assert got == ["quorum"], got
    assert candidates({"turn_count": 0, "nodes": []}) == []
    print("promote OK: ogni soglia è un AND, e il punteggio ordina")


if __name__ == "__main__":
    demo()
