"""CLS: la memoria che si è dimostrata valida diventa conoscenza (§5.3).

`sleep_maybe()` consolida Neuron dentro sé stesso e non scrive mai in NeuRAG,
quindi un concetto rinforzato per 200 turni resta nello store che decade e non
diventa mai permanente. Questo lo promuove — ma **report-only** finché non passi
`--apply`, perché le soglie non sono misurate su un grafo reale e un nodo
promosso, al contrario di un bridge, **non decade**: promuovere rumore costa più
che non promuovere niente.
"""
import pytest

from gray_matter.promote import PROMOTE_RULES, candidates, report_lines, score


def _exp(nodes, turn_count=200):
    return {"turn_count": turn_count, "nodes": nodes}


def _n(keyword, salience=9, trust=0.8, turn=10, tags=None):
    return {"keyword": keyword, "salience": salience, "trust": trust,
            "turn": turn, "tags": tags or [], "topic": "t", "domain": "d"}


# ---------- ogni soglia è un AND ----------

def test_a_concept_meeting_every_floor_is_promoted():
    assert [c["keyword"] for c in candidates(_exp([_n("quorum")]))] == ["quorum"]


def test_frequent_but_never_confirmed_is_not_promoted():
    """Il caso che una soglia sola sul prodotto lascerebbe passare: salienza
    altissima, trust zero. È esattamente ciò che non va reso permanente."""
    assert candidates(_exp([_n("hot", salience=400, trust=0.0)])) == []


def test_trusted_but_too_young_is_not_promoted():
    assert candidates(_exp([_n("nuovo", turn=199)])) == []


def test_rarely_reinforced_is_not_promoted():
    assert candidates(_exp([_n("raro", salience=1)])) == []


@pytest.mark.parametrize("field,value", [
    ("salience", PROMOTE_RULES["min_salience"] - 1),
    ("trust", PROMOTE_RULES["min_trust"] - 0.01),
])
def test_just_below_any_floor_is_out(field, value):
    assert candidates(_exp([_n("borderline", **{field: value})])) == []


@pytest.mark.parametrize("field,value", [
    ("salience", PROMOTE_RULES["min_salience"]),
    ("trust", PROMOTE_RULES["min_trust"]),
])
def test_exactly_at_a_floor_is_in(field, value):
    assert candidates(_exp([_n("borderline", **{field: value})]))


def test_age_is_counted_in_turns_from_the_graphs_own_clock():
    """Non wall-clock: un grafo rimasto inutilizzato un mese non ha per questo
    concetti più stabili, e l'inattività non è evidenza."""
    young = _exp([_n("x", turn=160)], turn_count=200)      # 40 turni
    old = _exp([_n("x", turn=10)], turn_count=200)         # 190 turni
    assert candidates(young) == []
    assert candidates(old)


# ---------- il punteggio ordina, non decide ----------

def test_the_report_is_ranked_by_score():
    cands = candidates(_exp([
        _n("debole", salience=5, trust=0.5),
        _n("forte", salience=50, trust=1.0),
        _n("medio", salience=20, trust=0.7),
    ]))
    assert [c["keyword"] for c in cands] == ["forte", "medio", "debole"]
    assert cands[0]["score"] > cands[1]["score"] > cands[2]["score"]


def test_score_is_zero_without_trust():
    assert score({"salience": 100, "trust": 0.0, "turn": 0}, 500) == 0.0


# ---------- i tag viaggiano: è un join, non un orfano ----------

def test_the_tags_it_already_shares_travel_with_it():
    """§4 ha fatto del tag l'unico oggetto su cui i due store concordano: una
    promozione senza tag lascerebbe cadere un nodo isolato in NeuRAG."""
    c = candidates(_exp([_n("quorum", tags=["raft", "consensus"])]))[0]
    assert c["tags"] == ["raft", "consensus"]


# ---------- robustezza sull'input, che arriva da un altro processo ----------

def test_an_empty_or_broken_export_is_not_a_crash():
    assert candidates({}) == []
    assert candidates({"turn_count": 0, "nodes": []}) == []
    assert candidates({"nodes": [{"keyword": "x"}]}) == []          # campi assenti
    assert candidates(_exp([{"keyword": "", "salience": 99, "trust": 1.0,
                             "turn": 0}])) == [], "un keyword vuoto non è un nodo"


def test_none_values_are_treated_as_zero():
    assert candidates(_exp([_n("x", salience=None, trust=None)])) == []


# ---------- il report dice che non ha fatto niente ----------

def test_the_dry_run_report_says_nothing_was_written():
    lines = "\n".join(report_lines(candidates(_exp([_n("quorum")])), applied=False))
    assert "dry run" in lines.lower()
    assert "Niente è stato scritto" in lines
    assert "--apply" in lines


def test_the_applied_report_does_not_claim_a_dry_run():
    lines = "\n".join(report_lines(candidates(_exp([_n("quorum")])), applied=True))
    assert "dry run" not in lines.lower()
    assert "Niente è stato scritto" not in lines


def test_an_empty_report_shows_the_thresholds():
    lines = "\n".join(report_lines([], applied=False))
    assert "soglie" in lines and "min_trust" in lines


def test_the_cut_points_are_constants_not_literals():
    """§8.2: hanno bisogno di dati veri e si muoveranno, quindi stanno in un
    dict da regolare, non sparsi in una query."""
    assert set(PROMOTE_RULES) == {"min_salience", "min_trust", "min_age_turns"}
    loose = candidates(_exp([_n("x", salience=1, trust=0.1, turn=199)]),
                       rules={"min_salience": 0, "min_trust": 0.0, "min_age_turns": 0})
    assert [c["keyword"] for c in loose] == ["x"]


def test_the_self_check_runs():
    from gray_matter.promote import demo
    demo()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
