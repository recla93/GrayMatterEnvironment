"""P5 — the graph learns, and what it learns survives (DESIGN-EVOLUTION §5.1).

`rebuild_links()` runs at the end of every `auto_ingest` and used to open with a
bare `DELETE FROM node_links`. The graph could not learn anything, and a
hand-curated link had a lifetime of exactly one re-ingest. Two halves fix that:
`origin` separates derived links from learned ones, and reinforcement happens on
CONFIRMATION rather than on co-retrieval — retrieval is cheap and often wrong, so
reinforcing every co-return would teach the graph whatever the ranker already
believed.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph


def _kg():
    return KnowledgeGraph(pathlib.Path(":memory:"))


def _pair(kg, tags_a=("x", "y"), tags_b=("x", "y")):
    a = kg.add_node("A", "fundamental", parent_id=0, tags=list(tags_a))
    b = kg.add_node("B", "fundamental", parent_id=0, tags=list(tags_b))
    kg.add_chunk(a, "alpha material", source="a.md")
    kg.add_chunk(b, "beta material", source="b.md")
    return a, b


def _link(kg, a, b, link_type="tag_overlap"):
    return kg._conn.execute(
        "SELECT * FROM node_links WHERE source_id=? AND target_id=? AND link_type=?",
        (a, b, link_type)).fetchone()


def _tick(kg, n=2):
    """Advance the query clock past the Hebbian cooldown."""
    kg._meta_set("query_count", int(kg._meta_get("query_count", "0") or 0) + n)


# ---------- origin: derived vs learned ----------

def test_a_curated_link_survives_a_rebuild():
    kg = _kg()
    a, b = _pair(kg)
    kg.upsert_link(a, b, "semantic", 0.97, "curato a mano", origin="curated")
    report = kg.rebuild_links()
    assert report["kept"] == 1
    row = _link(kg, a, b, "semantic")
    assert row is not None
    assert (row["weight"], row["evidence"], row["origin"]) == (0.97, "curato a mano", "curated")
    kg.close()


def test_a_derived_rebuild_cannot_clobber_a_learned_link():
    """Deleting only origin='auto' is not enough on its own: the builders
    re-upsert every pair on the way back in, and without the guard in
    upsert_link the survivor would get its weight replaced by the Jaccard
    number it started from."""
    kg = _kg()
    a, b = _pair(kg)
    kg.upsert_link(a, b, "tag_overlap", 0.95, "confermato", origin="confirmed")
    kg.upsert_link(a, b, "tag_overlap", 0.10, "jaccard", origin="auto")
    row = _link(kg, a, b)
    assert (row["weight"], row["origin"]) == (0.95, "confirmed")
    kg.close()


def test_but_a_newer_curation_does_get_through():
    kg = _kg()
    a, b = _pair(kg)
    kg.upsert_link(a, b, "tag_overlap", 0.95, "confermato", origin="confirmed")
    kg.upsert_link(a, b, "tag_overlap", 0.99, "ri-confermato", origin="curated")
    row = _link(kg, a, b)
    assert (row["weight"], row["origin"]) == (0.99, "curated")
    kg.close()


def test_derived_links_are_still_rebuilt_from_scratch():
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    assert _link(kg, a, b)["origin"] == "auto"
    kg._conn.execute("UPDATE node_links SET weight = 0.01")   # stale derived value
    kg._conn.commit()
    kg.rebuild_links()
    assert _link(kg, a, b)["weight"] > 0.01, "a derived link must be recomputed"
    kg.close()


# ---------- Hebbian: confirmation is the signal ----------

def test_the_first_confirm_on_a_fresh_vault_counts():
    """`last_coactivation` defaults to 0, which is indistinguishable from
    "counted at query 0" — so the cooldown swallowed the very first confirm on
    every new vault. The count is the unambiguous "never reinforced"."""
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    kg.confirm([a, b])
    assert _link(kg, a, b)["co_activation_count"] == 1
    kg.close()


def test_confirm_promotes_at_three_and_eight_and_never_demotes():
    kg = _kg()
    a, b = _pair(kg, tags_a=("x", "y"), tags_b=("y", "z"))    # jaccard 1/3
    kg.rebuild_links()
    start = _link(kg, a, b)["weight"]
    assert start == pytest.approx(1 / 3, abs=1e-3)

    seen = {}
    for _ in range(9):
        _tick(kg)
        kg.confirm([a, b])
        row = _link(kg, a, b)
        seen[row["co_activation_count"]] = row["weight"]

    assert seen[1] == pytest.approx(start), "below the medium threshold: unchanged"
    assert seen[2] == pytest.approx(start)
    assert seen[3] == pytest.approx(kg.HEBBIAN_FLOOR["medium"])
    assert seen[7] == pytest.approx(kg.HEBBIAN_FLOOR["medium"])
    assert seen[8] == pytest.approx(kg.HEBBIAN_FLOOR["strong"])
    # monotone: the sequence never goes down
    weights = [seen[c] for c in sorted(seen)]
    assert weights == sorted(weights)
    kg.close()


def test_a_threshold_is_a_floor_not_an_assignment():
    """A tag overlap can already be 1.0. Setting the weight to the threshold
    value would DEMOTE a strong link for being confirmed."""
    kg = _kg()
    a, b = _pair(kg)                       # identical tags -> jaccard 1.0
    kg.rebuild_links()
    assert _link(kg, a, b)["weight"] == 1.0
    for _ in range(4):
        _tick(kg)
        kg.confirm([a, b])
    assert _link(kg, a, b)["weight"] == 1.0
    kg.close()


def test_reinforcement_takes_the_link_out_of_the_derived_set():
    """What the graph learned has to outlive the next ingest."""
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    assert _link(kg, a, b)["origin"] == "auto"
    kg.confirm([a, b])
    assert _link(kg, a, b)["origin"] == "hebbian"
    kg.rebuild_links()
    row = _link(kg, a, b)
    assert row["origin"] == "hebbian" and row["co_activation_count"] == 1
    kg.close()


def test_the_cooldown_stops_a_rapid_repeat_from_inflating_the_count():
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    kg.confirm([a, b])
    kg.confirm([a, b])
    kg.confirm([a, b])
    assert _link(kg, a, b)["co_activation_count"] == 1, "no query passed in between"
    _tick(kg)
    kg.confirm([a, b])
    assert _link(kg, a, b)["co_activation_count"] == 2
    kg.close()


def test_confirming_does_not_invent_links():
    """Creating links stays with the auto-builders, as in Neuron."""
    kg = _kg()
    a, b = _pair(kg, tags_a=("x",), tags_b=("z",))   # nothing in common
    kg.rebuild_links()
    assert kg.link_count() == 0
    assert kg.confirm([a, b]) == []
    assert kg.link_count() == 0
    kg.close()


def test_confirming_one_node_is_not_a_co_activation():
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    assert kg.confirm([a]) == []
    assert _link(kg, a, b)["co_activation_count"] == 0
    kg.close()


def test_confirmation_counts_as_use():
    """It is stronger evidence than a retrieval, so the clocks parking and
    decay read must move too — otherwise a node could be confirmed weekly and
    still be parked for inactivity."""
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    assert kg.get_node(a)["last_used"] is None
    kg.confirm([a, b])
    assert kg.get_node(a)["last_used"] is not None
    sal = kg._conn.execute("SELECT MAX(salience) FROM tags").fetchone()[0]
    assert sal > 0
    kg.close()


def test_a_directional_pair_is_reinforced_in_each_direction_on_its_own():
    """The primary key is (source, target, link_type), so A->B and B->A are two
    rows, and `build_crossref_links` really does create both: "A talks about B"
    is not "B talks about A" and the two carry different evidence.

    A confirmation is symmetric — it says these were useful together — so it
    raises BOTH rows to the floor while leaving the asymmetry the derived
    evidence had. Pinned here because the alternative (averaging them, or
    treating the pair as one row) would throw that evidence away.
    """
    kg = _kg()
    a, b = _pair(kg)
    kg.upsert_link(a, b, "cross_ref", 0.80, "a mentions b 8x")
    kg.upsert_link(b, a, "cross_ref", 0.05, "b mentions a once")
    kg.confirm([a, b])
    ab = _link(kg, a, b, "cross_ref")
    ba = _link(kg, b, a, "cross_ref")
    assert ab["weight"] == 0.80, "the strong direction is not pulled down"
    assert ba["weight"] == kg.HEBBIAN_FLOOR["tangential"], "the weak one is pulled up"
    assert ab["co_activation_count"] == ba["co_activation_count"] == 1
    kg.close()


# ---------- spreading activation ----------

def test_activation_falls_off_with_distance():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    c = kg.add_node("C", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "semantic", 1.0, "", origin="curated")
    kg.upsert_link(b, c, "semantic", 1.0, "", origin="curated")
    out = dict(kg.spreading_activation([a], k=2))
    assert out[b] > out[c] > 0, "a second hop must arrive weaker, not equal"
    kg.close()


def test_k_bounds_how_far_it_reaches():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    c = kg.add_node("C", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "semantic", 1.0, "", origin="curated")
    kg.upsert_link(b, c, "semantic", 1.0, "", origin="curated")
    assert c not in dict(kg.spreading_activation([a], k=1))
    assert c in dict(kg.spreading_activation([a], k=2))
    kg.close()


def test_seeds_are_not_returned_as_their_own_neighbours():
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    assert a not in dict(kg.spreading_activation([a]))
    kg.close()


def test_a_weak_route_dies_under_the_activation_floor():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    b = kg.add_node("B", "fundamental", parent_id=0)
    kg.upsert_link(a, b, "semantic", 0.01, "", origin="curated")
    assert kg.spreading_activation([a], min_activation=0.1) == []
    kg.close()


def test_parked_nodes_stay_out_unless_asked_for():
    """An expansion must not quietly undo P4's parking."""
    kg = _kg()
    a, b = _pair(kg)
    kg.upsert_link(a, b, "semantic", 1.0, "", origin="curated")
    kg._conn.execute("UPDATE nodes SET layer = ? WHERE id = ?", (kg.LAYER_DORMANT, b))
    kg._conn.commit()
    assert b not in dict(kg.spreading_activation([a]))
    assert b in dict(kg.spreading_activation([a], deep=True))
    kg.close()


def test_hebbian_promotion_widens_the_route_it_travels():
    """The two halves of §5.1 meet here: confirmation raises the weight, and
    the weight is what spreading activation walks on."""
    kg = _kg()
    a, b = _pair(kg, tags_a=("x", "y"), tags_b=("y", "z"))
    kg.rebuild_links()
    before = dict(kg.spreading_activation([a]))[b]
    for _ in range(3):
        _tick(kg)
        kg.confirm([a, b])
    after = dict(kg.spreading_activation([a]))[b]
    assert after > before
    kg.close()


def test_related_nodes_attaches_the_node_info():
    kg = _kg()
    a, b = _pair(kg)
    kg.rebuild_links()
    rel = kg.related_nodes(a)
    assert [r["name"] for r in rel] == ["B"]
    assert rel[0]["activation"] > 0 and rel[0]["layer"] == kg.LAYER_ACTIVE
    kg.close()


# ---------- the gate that was missing entirely ----------

def test_every_served_tool_is_announced_to_the_gateway():
    """`main()` used to hand Gray Matter a hand-written `tool_names` list while
    `list_tools()` built the real one, and it had drifted TWICE:
    `knowledge_neighbors` and `skill` were served and dispatched for releases
    while the gateway was never told they existed — so GM could not proxy tools
    that worked, and nothing anywhere said so.

    Both lists now come from `_tools()`, the way Neuron derives its own from
    `_HANDLERS.keys()`. This asserts they still do: a literal list
    reintroduced next to `autoregister` fails here."""
    import asyncio
    import inspect

    from neurag import server

    served = {t.name for t in asyncio.run(server.list_tools())}
    announced = set(server.announced_tool_names())
    assert served == announced, (
        f"served but not announced: {sorted(served - announced)}; "
        f"announced but not served: {sorted(announced - served)}")
    assert "tool_names = [" not in inspect.getsource(server.main), (
        "the announced list is hand-written again — derive it from _tools()")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
