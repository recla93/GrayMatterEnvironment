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

**Report first.** The cut points below were measured once (see the note on
PROMOTE_RULES) and will move again, and the failure mode of guessing them is a knowledge base full of promoted
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
#
# Measured on the real `ai` graph, 2026-09-14 (380 nodes, 140 turns): salience
# and trust never sit on the same node. Salience DECAYS every turn ("hot now"),
# trust is written by `confirm` and never decays ("was confirmed once"): the top
# nodes by salience all had trust 0.00, the top by trust all had salience 0.
# An AND across a fading signal and a lasting one passes only a node confirmed
# in the very turn it is hot — never happened in 140 turns, 0 candidates.
# So salience left the gate (it still ranks). The gate is: old enough, AND at
# least one signal that does not decay — confirmed, or structurally reinforced
# (strong links, Hebbian co-activation). 19 of 380 passed; read by eye, none
# was noise.
PROMOTE_RULES = {
    "min_age_turns": 50,     # survived long enough to be stable, not merely hot
    "min_trust": 0.5,        # actually confirmed useful (B2 feedback) ...
    "min_strong_links": 2,   # ... or anchored by typed strong links ...
    "min_coactivation": 3,   # ... or reinforced together with its neighbours (Hebbian)
}


def first_seen(export: dict) -> dict[str, int]:
    """keyword -> turn of the oldest link touching it.

    Node.turn is the LAST touch, not the birth: the engine rewrites it on every
    reinforcement, and salience decays with idleness. Measured from Node.turn,
    "old" and "salient" exclude each other and nothing is ever promoted
    (verified on a real graph: 347 nodes, 0 candidates, 0 that met both).
    Links keep their birth turn, so the oldest link is the earliest proof the
    concept existed. A node with no links has no age — and a concept never
    connected to anything is not consolidated, so it is not eligible."""
    born: dict[str, int] = {}
    for lk in export.get("links") or []:
        t = lk.get("created_turn")
        if t is None:
            continue
        for kw in (lk.get("source"), lk.get("target")):
            if kw and int(t) < born.get(kw, int(t) + 1):
                born[kw] = int(t)
    return born


def score(node: dict, age: int, strong: int = 0, coact: int = 0) -> float:
    """(trust + strong links + co-activation) x age, salience as a tie-breaker.

    Ranking only — eligibility is the floors. Age is in turns, Neuron's own
    clock; wall-clock would punish a graph that sat unused for a month, and
    sitting unused is not evidence."""
    lasting = float(node.get("trust", 0.0)) + 0.5 * strong + 0.25 * coact
    return lasting * (max(0, age) / 100.0) + 0.01 * float(node.get("salience", 0))


def _structure(export: dict) -> "tuple[dict[str, int], dict[str, int], dict[str, list[str]]]":
    """Per keyword: strong-link count, Hebbian co-activation sum, and the
    rationales of its strong/medium links as one-line chunks. Drift links are
    skipped: their target lives in another context."""
    strong: dict[str, int] = {}
    coact: dict[str, int] = {}
    why: dict[str, list[str]] = {}
    for lk in export.get("links") or []:
        if lk.get("link_type") == "drift":
            continue
        src, tgt, w = lk.get("source"), lk.get("target"), lk.get("weight")
        for kw in (src, tgt):
            if not kw:
                continue
            coact[kw] = coact.get(kw, 0) + int(lk.get("co_activation_count") or 0)
            if w == "strong":
                strong[kw] = strong.get(kw, 0) + 1
            if w in ("strong", "medium") and (lk.get("rationale") or "").strip():
                why.setdefault(kw, []).append(
                    f"{src} -[{lk.get('link_type')}]-> {tgt}: {lk['rationale'].strip()}")
    return strong, coact, why


def chunks_for(kw: str, export: dict, why: dict[str, list[str]]) -> list[dict]:
    """What a promoted concept carries into the vault: link rationales first
    (a *why* in one sentence, by construction), then its episodes (facts, some
    of which are logs — the dry-run report is the filter, not a heuristic).
    `source`/`section` are NeuRAG's own chunk fields: provenance and when."""
    out = [{"text": t, "source": f"neuron:{kw}", "section": "link"} for t in why.get(kw, [])]
    for ep in (export.get("episodes") or {}).get(kw) or []:
        text = (ep.get("text") or "").strip()
        if text:
            out.append({"text": text, "source": f"neuron:{kw}", "section": f"turn {ep.get('turn')}"})
    return out


def candidates(export: dict, rules: dict | None = None) -> list[dict]:
    """Concepts eligible for promotion, best first, with the reason.

    `export` is Neuron's `export` payload — {turn_count, nodes:[...]}. Reading
    it through the tool rather than the DB keeps GM an orchestrator: it never
    opens someone else's vault (I3), and never fights the single writer.
    """
    r = {**PROMOTE_RULES, **(rules or {})}
    turn_count = int(export.get("turn_count") or 0)
    born = first_seen(export)
    strong, coact, why = _structure(export)
    out = []
    for nd in export.get("nodes") or []:
        kw = nd.get("keyword", "")
        salience = float(nd.get("salience", 0) or 0)
        trust = float(nd.get("trust", 0.0) or 0.0)
        if kw not in born:
            continue
        age = max(0, turn_count - born[kw])
        if age < r["min_age_turns"]:
            continue
        signals = [name for name, ok in (
            ("trust", trust >= r["min_trust"]),
            ("strong-links", strong.get(kw, 0) >= r["min_strong_links"]),
            ("co-activation", coact.get(kw, 0) >= r["min_coactivation"]),
        ) if ok]
        if not signals:
            continue
        out.append({
            "keyword": kw,
            "why": signals,
            "chunks": chunks_for(kw, export, why),
            "topic": nd.get("topic", "") or "",
            "domain": nd.get("domain", "") or "",
            # The tags it ALREADY shares are what the promoted node gets: §4 made
            # the tag the one object both stores agree on, so a promotion joins
            # the two graphs instead of dropping an orphan into NeuRAG.
            "tags": [str(t) for t in (nd.get("tags") or [])],
            "salience": salience,
            "trust": round(trust, 3),
            "age_turns": age,
            "strong_links": strong.get(kw, 0),
            "coactivation": coact.get(kw, 0),
            "score": round(score(nd, age, strong.get(kw, 0), coact.get(kw, 0)), 3),
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
                     f"   ({', '.join(c.get('why') or [])}; trust {c['trust']}, "
                     f"{c.get('strong_links', 0)} link forti, "
                     f"{c['age_turns']} turni)  [{tags}]")
        for ch in c.get("chunks") or []:
            lines.append(f"           {ch['section']:>8}: {ch['text'][:110]}")
    if not applied:
        lines.append("")
        lines.append("Niente è stato scritto. Con --apply diventano nodi NeuRAG, "
                     "con le righe sopra come chunk e un bridge Neuron<->NeuRAG.")
        lines.append("Un nodo promosso NON decade e un chunk nemmeno: leggi le "
                     "righe, gli episodi possono essere log e non conoscenza.")
    return lines


def demo() -> None:
    """Runnable self-check (stdlib only): age is a floor, then ANY lasting
    signal opens the gate — trust, strong links, or co-activation — while a
    hot-but-unanchored node stays out. Every node here was touched at turn 199."""
    exp = {"turn_count": 200, "nodes": [
        {"keyword": "quorum", "salience": 9, "trust": 0.8, "turn": 199, "tags": ["raft"]},
        {"keyword": "hot_but_unanchored", "salience": 40, "trust": 0.0, "turn": 199},
        {"keyword": "trusted_but_new", "salience": 9, "trust": 0.9, "turn": 199},
        {"keyword": "anchored", "salience": 0, "trust": 0.0, "turn": 199},
        {"keyword": "unlinked", "salience": 9, "trust": 0.9, "turn": 199},
    ], "links": [
        {"source": "quorum", "target": "anchored", "created_turn": 10, "weight": "strong",
         "link_type": "deepening", "rationale": "why one", "co_activation_count": 0},
        {"source": "anchored", "target": "hot_but_unanchored", "created_turn": 10,
         "weight": "strong", "link_type": "contrast", "rationale": "why two"},
        {"source": "trusted_but_new", "target": "quorum", "created_turn": 199, "weight": "medium"},
    ], "episodes": {"quorum": [{"turn": 12, "text": "chose raft because ..."}]}}
    got = {c["keyword"]: c for c in candidates(exp)}
    assert set(got) == {"quorum", "anchored"}, set(got)
    assert got["quorum"]["why"] == ["trust"]
    assert got["anchored"]["why"] == ["strong-links"]
    assert [c["section"] for c in got["quorum"]["chunks"]] == ["link", "turn 12"]
    assert candidates({"turn_count": 0, "nodes": []}) == []
    print("promote OK: eta' come soglia, poi un segnale che non decade apre")


if __name__ == "__main__":
    demo()
