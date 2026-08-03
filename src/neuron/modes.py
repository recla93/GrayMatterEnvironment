"""Modalità operative del retrieval (Neuron, ippocampo).

Strategie di ranking pure applicate da `_resolve_context`:

- ``semantic`` (default): invariato — il ranking composito esistente.
- ``focus``: boost sui nodi simili al compito attivo. Il focus arriva come
  PARAMETRO (standalone: passato a mano; con GM: iniettato dal proxy dal
  blackboard `cervello/focus`) — Neuron non legge mai il DB di GM.
- ``brainstorm``: penalizza i nodi più simili alla query (il contrario della
  rilevanza) → emergono i nodi lontani, associazioni inaspettate.
- ``pattern``: suggerisce il prossimo passo da sequenze ricorrenti di keyword
  nei turni (coppie consecutive >= min_count, dal mock). Il materiale è lo
  storico dei TURNI (topic + keywords per turno), che il grafo NON preserva:
  store_turn appende una riga a `turns.jsonl` in graphs_dir (append-only,
  best-effort) e la modalità pattern estrae le coppie da lì al bisogno.

Stdlib only. Le funzioni sono pure e testabili (__main__ incluso).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

MODES = ("semantic", "focus", "brainstorm", "pattern")
PATTERN_MIN_COUNT = 2


# --- focus -------------------------------------------------------------

def focus_boost(node_scores: dict[str, float], focus_sim: dict[str, float],
                boost: float = 0.3) -> dict[str, float]:
    """Riordina i punteggi dando ``+boost * sim`` ai nodi simili al focus."""
    out = dict(node_scores)
    for kw, s in focus_sim.items():
        if kw in out:
            out[kw] += boost * s
    return out


# --- brainstorm ---------------------------------------------------------

def brainstorm_spread(node_scores: dict[str, float], sim_map: dict[str, float],
                      factor: float = 0.3) -> dict[str, float]:
    """Penalizza la somiglianza con la query: i nodi lontani salgono."""
    out = dict(node_scores)
    for kw, s in sim_map.items():
        if kw in out:
            out[kw] -= factor * s
    return out


# --- pattern ------------------------------------------------------------

def pattern_extract(turns: list[dict], min_count: int = PATTERN_MIN_COUNT) -> list[dict]:
    """Coppie consecutive di keyword che compaiono >= min_count volte."""
    pairs: Counter = Counter()
    for t in turns:
        kws = t.get("keywords", []) or []
        for i in range(len(kws) - 1):
            pairs[(kws[i], kws[i + 1])] += 1
    return [{"pattern": [a, b], "count": c}
            for (a, b), c in pairs.items() if c >= min_count]


def pattern_suggest(current_kws: list[str], patterns: list[dict]) -> list[dict]:
    """Se lo stato corrente finisce con la prima meta' di uno schema, suggerisci
    il resto. Ritorna i suggerimenti ordinati per count."""
    sugg = []
    for p in patterns:
        seq = p["pattern"]
        if len(current_kws) >= 1 and current_kws[-1] == seq[0] and len(seq) >= 2:
            sugg.append({"next": seq[1], "pattern": seq, "count": p["count"]})
    return sorted(sugg, key=lambda s: s["count"], reverse=True)


def append_turn(log_path: "str | Path", topic: str, keywords: list[str]) -> None:
    """Appende un turno al log (turns.jsonl): topic + keywords ordinate come
    ricevute. Best-effort: il log è lo storico per i pattern, mai bloccante."""
    try:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"topic": topic, "keywords": list(keywords)},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def patterns_from_log(log_path: "str | Path", min_count: int = PATTERN_MIN_COUNT) -> list[dict]:
    """Estrae i pattern dallo storico dei turni (coppie consecutive di keyword
    che compaiono >= min_count volte). Il log è la fonte di verità: nessuna
    cache, l'ultima riga conta sempre."""
    path = Path(log_path)
    turns = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue   # riga corrotta: la salta, il resto conta
    except OSError:
        return []
    return pattern_extract(turns, min_count)


if __name__ == "__main__":
    # focus: il nodo del focus sale
    ns = {"wal": 0.8, "persistenza": 0.6, "checkpoint": 0.7}
    boosted = focus_boost(ns, {"persistenza": 1.0, "wal": 0.1})
    assert boosted["persistenza"] > boosted["wal"], boosted

    # brainstorm: il nodo piu' simile scende sotto il piu' lontano
    spread = brainstorm_spread({"wal": 0.8, "fantasia": 0.4},
                               {"wal": 1.0, "fantasia": 0.0}, factor=0.5)
    assert spread["fantasia"] > spread["wal"], spread

    # pattern: estrazione e match (caso del mock)
    turns = [
        {"keywords": ["build", "check", "tag", "push"]},
        {"keywords": ["build", "check", "tag", "push"]},
        {"keywords": ["build", "check"]},
        {"keywords": ["ripulire", "testare"]},
    ]
    pats = pattern_extract(turns)
    keys = {tuple(p["pattern"]) for p in pats}
    assert ("build", "check") in keys and ("tag", "push") in keys
    assert ("ripulire", "testare") not in keys
    sugg = pattern_suggest(["build", "check", "tag"], pats)
    assert sugg and sugg[0]["next"] == "push", sugg

    # log dei turni: append + estrazione (lo storico che il grafo non preserva)
    p = Path(__import__("tempfile").mkdtemp()) / "turns.jsonl"
    for kws in (["checkpoint", "wal", "seed", "release"],
                ["checkpoint", "wal", "seed", "release"],
                ["checkpoint", "wal", "seed"],
                ["checkpoint", "wal"]):
        append_turn(p, kws[0], kws)
    pats_log = patterns_from_log(p)
    assert ("seed", "release") in {tuple(x["pattern"]) for x in pats_log}, pats_log
    assert ("wal", "seed") in {tuple(x["pattern"]) for x in pats_log}
    # log assente -> []
    assert patterns_from_log(Path("nope/non_esiste.jsonl")) == []
    # riga corrotta saltata, il resto conta
    with p.open("a", encoding="utf-8") as f:
        f.write("{not json}\n")
        f.write(json.dumps({"topic": "seed", "keywords": ["seed", "release"]}) + "\n")
    pats2 = patterns_from_log(p)
    assert ("seed", "release") in {tuple(x["pattern"]) for x in pats2}

    print("PASS: modes")
