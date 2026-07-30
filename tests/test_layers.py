"""P4 — the activation gradient (DESIGN-EVOLUTION §3).

The one rule the whole phase hangs on: **no layer is a grave**. Parking takes
away a node's right to be scanned by default and nothing else — the chunks,
the links and the tags stay exactly where they were, and `recall` reaches every
layer. The gate at the bottom is I5 stated as an assertion: park it, re-ingest
over it, decay it, then get it back byte-identical.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph


def _kg(path=":memory:"):
    return KnowledgeGraph(pathlib.Path(path))


def _aged(kg, node_id, days):
    """Backdate a node's activity. Parking measures inactivity, and a test
    cannot wait half a year for it."""
    kg._conn.execute(
        "UPDATE nodes SET last_used = datetime('now', ?) WHERE id = ?",
        (f"-{days} days", node_id))
    kg._conn.commit()


def _vault():
    kg = _kg()
    old = kg.add_node("Old", "fundamental", parent_id=0)
    new = kg.add_node("New", "fundamental", parent_id=0)
    kg.add_chunk(old, "the forgotten spec about quorum handling", source="old.md")
    kg.add_chunk(new, "the current spec about quorum handling", source="new.md")
    return kg, old, new


# ---------- schema ----------

def test_layer_and_last_used_exist_and_default_to_active():
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0)
    row = kg.get_node(n)
    assert row["layer"] == kg.LAYER_ACTIVE
    assert row["last_used"] is None       # nothing has consulted it yet
    kg.close()


def test_added_columns_reach_a_vault_that_predates_them(tmp_path):
    """CREATE TABLE IF NOT EXISTS is a no-op on an existing table, so a new
    column reaches an old vault only through _ensure_columns."""
    db = tmp_path / "old.db"
    kg = _kg(db)
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.close()

    # rewind: a vault from before P4. The connection cache MUST be cleared —
    # `close()` on the Turso tier keeps the connection alive on purpose, and a
    # reopen would hand back a handle still holding the old schema, so the test
    # would assert against a stale view and pass no matter what the code does.
    # An upgrade always happens in a fresh process; this makes it one.
    import sqlite3

    import neurag.db as neurag_db
    neurag_db._turso_conn_cache.clear()
    raw = sqlite3.connect(db)
    raw.execute("DROP INDEX IF EXISTS idx_nodes_layer")   # indexes the column
    raw.execute("ALTER TABLE nodes DROP COLUMN layer")
    raw.execute("ALTER TABLE nodes DROP COLUMN last_used")
    raw.commit()
    raw.close()

    kg = _kg(db)
    assert not kg._corrupt, kg._corrupt_err
    assert kg.get_node(n)["layer"] == kg.LAYER_ACTIVE     # DEFAULT means "as before"
    assert kg.layer_counts() == {"L2": 1}                 # the index over it works too
    kg.close()
    neurag_db._turso_conn_cache.clear()
    kg = _kg(db)                                          # idempotent
    assert not kg._corrupt, kg._corrupt_err
    assert kg.get_node(n)["layer"] == kg.LAYER_ACTIVE
    kg.close()


# ---------- activity is what parking measures ----------

def test_answering_marks_the_node_and_reinforces_its_tags():
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0, tags=["quorum"])
    kg.add_chunk(n, "quorum handling in the coordinator", source="a.md")
    assert kg.get_node(n)["last_used"] is None
    kg.search("quorum", top_n=3)
    assert kg.get_node(n)["last_used"] is not None
    sal = kg._conn.execute("SELECT salience FROM tags WHERE name='quorum'").fetchone()[0]
    assert sal == pytest.approx(kg.SALIENCE_BUMP)
    kg.close()


def test_a_diagnostic_must_not_keep_a_node_warm_by_looking_at_it():
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0, tags=["quorum"])
    kg.add_chunk(n, "quorum handling", source="a.md")
    kg.search("quorum", top_n=3, touch=False)
    assert kg.get_node(n)["last_used"] is None
    assert kg.session_cache() == {}
    kg.close()


# ---------- L1 ----------

def test_session_cache_expires_by_queries_and_evicts_at_the_cap():
    kg = _kg()
    ids = [kg.add_node(f"N{i}", "fundamental", parent_id=0)
           for i in range(kg.SESSION_CACHE_MAX + 3)]
    for i in ids:
        kg.cache_add([i])
    cache = kg.session_cache()
    assert len(cache) == kg.SESSION_CACHE_MAX          # FIFO evicted the oldest
    assert ids[-1] in cache and ids[0] not in cache

    for _ in range(kg.SESSION_CACHE_QUERIES + 1):
        kg.cache_add([])                               # queries pass, nothing refreshed
    assert kg.session_cache() == {}                    # expired, not deleted from the vault
    assert len(kg.get_children(0)) == len(ids)
    kg.close()


def test_a_persisted_working_set_also_expires_on_the_clock():
    """The query TTL alone would make "session" a lie: a vault consulted twice
    six months apart would still call the first hit warm, and a single query
    would have protected that node from ever being parked."""
    kg, old, _ = _vault()
    kg.cache_add([old])
    assert old in kg.session_cache()
    stale = json.loads(kg._meta_get("session_cache"))
    stale[str(old)]["t"] = _iso_hours_ago(kg.SESSION_CACHE_HOURS + 1)
    kg._meta_set("session_cache", json.dumps(stale))
    assert kg.session_cache() == {}
    kg.close()


def test_a_stale_working_set_no_longer_shields_a_node_from_parking():
    kg, old, _ = _vault()
    kg.search("forgotten quorum")                      # warms it, the honest way
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    assert kg.park_candidates() == []                  # still warm: protected
    stale = json.loads(kg._meta_get("session_cache"))
    for e in stale.values():
        e["t"] = _iso_hours_ago(kg.SESSION_CACHE_HOURS + 1)
    kg._meta_set("session_cache", json.dumps(stale))
    assert [c["id"] for c in kg.park_candidates()] == [old]
    kg.close()


def _iso_hours_ago(hours: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def test_session_cache_survives_the_process(tmp_path):
    """A CLI invocation is a whole process life — an in-memory dict would be a
    session cache that never lasts a session."""
    db = tmp_path / "v.db"
    kg = _kg(db)
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.cache_add([n])
    kg.close()
    kg = _kg(db)
    assert n in kg.session_cache()
    kg.close()


# ---------- parking ----------

def test_an_idle_weakly_linked_node_is_a_candidate_and_a_fresh_one_is_not():
    kg, old, new = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    ids = {c["id"]: c for c in kg.park_candidates()}
    assert old in ids and new not in ids
    assert ids[old]["to_layer"] == kg.LAYER_DORMANT
    kg.close()


def test_very_long_inactivity_goes_straight_to_deep():
    kg, old, _ = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_deep"] + 10)
    assert kg.park_candidates()[0]["to_layer"] == kg.LAYER_DEEP
    kg.close()


def test_a_well_connected_node_is_never_parked():
    """Reachability beats idleness: something everything else points at is
    still part of how the vault is navigated."""
    kg, old, new = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_deep"] + 10)
    kg.upsert_link(old, new, "tag_overlap",
                   kg.PARK_RULES["max_link_weight"] + 0.1, "shared")
    assert kg.park_candidates() == []
    kg.close()


def test_the_session_working_set_is_never_parked():
    kg, old, _ = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_deep"] + 10)
    kg.cache_add([old])
    assert kg.park_candidates() == []
    kg.close()


def test_park_is_a_dry_run_unless_asked():
    kg, old, _ = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    report = kg.park()
    assert report["count"] == 1 and report["applied"] is False
    assert kg.get_node(old)["layer"] == kg.LAYER_ACTIVE      # nothing moved

    report = kg.park(apply=True)
    assert report["applied"] is True
    assert kg.get_node(old)["layer"] == kg.LAYER_DORMANT
    kg.close()


def test_parking_never_touches_content():
    kg, old, _ = _vault()
    before = kg.get_chunks(old)
    links_before = kg.link_count()
    tags_before = kg._conn.execute("SELECT COUNT(*) FROM node_tags").fetchone()[0]
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    kg.park(apply=True)
    assert kg.get_chunks(old) == before
    assert kg.link_count() == links_before
    assert kg._conn.execute(
        "SELECT COUNT(*) FROM node_tags").fetchone()[0] == tags_before
    kg.close()


def test_unpark_brings_it_back():
    kg, old, _ = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    kg.park(apply=True)
    assert kg.unpark(old) is True
    assert kg.get_node(old)["layer"] == kg.LAYER_ACTIVE
    assert kg.unpark(999999) is False
    kg.close()


# ---------- what parking actually changes: the default scan ----------

def test_a_parked_node_leaves_the_default_scan():
    kg, old, new = _vault()
    # touch=False: consulting it here would put it in the working set, and the
    # working set is never parked — the pre-check must not change the outcome.
    assert old in {r["node_id"]
                   for r in kg.search("forgotten quorum", top_n=10, touch=False)}
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    kg.park(apply=True)
    assert old not in {r["node_id"] for r in kg.search("forgotten quorum", top_n=10)}
    kg.close()


def test_but_deep_node_scope_and_recall_all_still_reach_it():
    kg, old, new = _vault()
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    kg.park(apply=True)
    q = "forgotten quorum"
    assert old in {r["node_id"] for r in kg.search(q, top_n=10, deep=True)}
    assert old in {r["node_id"] for r in kg.search(q, top_n=10, node_id=old)}
    assert old in {r["node_id"] for r in kg.recall(q, top_n=10)}
    kg.close()


def test_layer_counts_report_the_gradient():
    kg, old, _ = _vault()
    assert kg.layer_counts() == {"L2": 2}
    _aged(kg, old, kg.PARK_RULES["idle_days_dormant"] + 10)
    kg.park(apply=True)
    assert kg.layer_counts() == {"L2": 1, "L3": 1}
    assert kg.status()["layers"] == {"L2": 1, "L3": 1}
    kg.close()


# ---------- decay: the route, not the trace ----------

def test_first_decay_starts_the_clock_and_changes_nothing():
    kg, a, b = _vault()
    kg.upsert_link(a, b, "tag_overlap", 0.8, "x")
    report = kg.decay()
    assert report == {"days": 0.0, "links": 0, "tags": 0}
    assert kg.get_links(a)[0]["weight"] == 0.8
    kg.close()


def test_decay_weakens_a_route_by_the_elapsed_half_life():
    kg, a, b = _vault()
    kg.upsert_link(a, b, "tag_overlap", 0.8, "x")
    kg.decay()                                     # start the clock
    days = kg.DECAY["link_half_life_days"]
    kg._meta_set("decayed_at", _iso_days_ago(days))
    kg.decay()
    assert kg.get_links(a)[0]["weight"] == pytest.approx(0.4, abs=1e-3)
    kg.close()


def test_decay_stops_at_the_floor_so_a_route_gets_faint_never_gone():
    kg, a, b = _vault()
    kg.upsert_link(a, b, "tag_overlap", 0.06, "x")
    kg.decay()
    kg._meta_set("decayed_at", _iso_days_ago(kg.DECAY["link_half_life_days"] * 20))
    kg.decay()
    assert kg.get_links(a)[0]["weight"] == kg.DECAY["floor"]
    kg.close()


def test_running_decay_twice_in_a_row_is_not_decaying_twice():
    """Elapsed time comes from meta.decayed_at, not from each row — so any
    maintenance path can call this without compounding it by accident."""
    kg, a, b = _vault()
    kg.upsert_link(a, b, "tag_overlap", 0.8, "x")
    kg.decay()
    kg._meta_set("decayed_at", _iso_days_ago(kg.DECAY["link_half_life_days"]))
    kg.decay()
    once = kg.get_links(a)[0]["weight"]
    kg.decay()
    # approx, not equal: the second call still measures the microseconds that
    # really elapsed. The point is that it is not another half-life.
    assert kg.get_links(a)[0]["weight"] == pytest.approx(once, abs=1e-6)
    kg.close()


def test_use_reinforces_what_decay_weakens():
    kg = _kg()
    n = kg.add_node("N", "fundamental", parent_id=0, tags=["quorum"])
    kg.add_chunk(n, "quorum handling", source="a.md")
    kg.search("quorum")
    kg.decay()
    kg._meta_set("decayed_at", _iso_days_ago(kg.DECAY["tag_half_life_days"]))
    kg.decay()
    faded = kg._conn.execute("SELECT salience FROM tags WHERE name='quorum'").fetchone()[0]
    assert faded == pytest.approx(kg.SALIENCE_BUMP / 2, abs=1e-3)
    kg.search("quorum")
    assert kg._conn.execute(
        "SELECT salience FROM tags WHERE name='quorum'").fetchone()[0] > faded
    kg.close()


def _iso_days_ago(days: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ---------- the phase gate: I5, nothing is ever lost ----------

def test_everything_parked_comes_back_byte_identical(tmp_path):
    """DESIGN-EVOLUTION §7: park a node, run the operations that rewrite a
    vault, then recall it and assert the content returns unchanged. This is
    the assertion the whole 'no layer is a grave' claim rests on."""
    src = tmp_path / "spec.md"
    original = ("# Quorum\n\nIl coordinatore richiede un quorum di 3 nodi.\n\n"
                "## Dettaglio\n\nUn valore con accenti: perché, così, però.\n")
    src.write_text(original, encoding="utf-8")

    db = tmp_path / "v.db"
    kg = _kg(db)
    node = kg.add_node("Spec", "fundamental", parent_id=0)
    kg.add_node("Other", "fundamental", parent_id=0)
    kg.index_into_node(src, node)
    parked_text = [c["text"] for c in kg.get_chunks(node)]
    assert parked_text

    _aged(kg, node, kg.PARK_RULES["idle_days_deep"] + 10)
    kg.park(apply=True)
    assert kg.get_node(node)["layer"] == kg.LAYER_DEEP

    # the operations that rewrite a vault
    kg.index_into_node(src, node)          # idempotent re-ingest over a parked node
    kg.rebuild_links()
    kg.decay()
    kg._meta_set("decayed_at", _iso_days_ago(kg.DECAY["link_half_life_days"] * 5))
    kg.decay()
    kg.close()

    kg = _kg(db)                            # and a restart
    assert [c["text"] for c in kg.get_chunks(node)] == parked_text
    hits = kg.recall("quorum coordinatore", top_n=10)
    assert node in {h["node_id"] for h in hits}
    recalled = [h["text"] for h in hits if h["node_id"] == node]
    assert all(t in parked_text for t in recalled)
    assert "perché, così, però" in "\n".join(parked_text)
    kg.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
