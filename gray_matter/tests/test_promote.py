"""CLS by facts (ADR-016 D8): a fact that proved useful becomes knowledge.

Report-only unless --apply: a promoted chunk does not decay, so promoting noise
costs more than promoting nothing.
"""
import asyncio
import json

from gray_matter.promote import PROMOTE_PARENT, PROMOTE_RULES, candidates, report_lines


def _f(fid, kind="decision", turn=10, confirmed=1, status="active", concepts=("turso",), text=None):
    return {"id": fid, "kind": kind, "text": text or f"fact {fid}", "turn": turn,
            "status": status, "confirmed": confirmed, "concepts": list(concepts)}


def _exp(*facts, turn_count=100):
    return {"turn_count": turn_count, "facts": list(facts)}


def test_an_old_used_active_fact_is_promoted_with_its_provenance():
    c = candidates(_exp(_f("a1", text="Turso in local too")))
    assert [(x["keyword"], x["facts"]) for x in c] == [("turso", ["a1"])]
    assert c[0]["chunks"] == [{"text": "Turso in local too", "source": "neuron:#a1",
                               "section": "decision"}]


def test_never_user_or_habit_and_never_a_progress():
    """The vault is shared; user/habit are the user's (ADR-016 D8)."""
    assert candidates(_exp(_f("u", kind="user"), _f("h", kind="habit"),
                           _f("p", kind="progress"), _f("i", kind="idea"))) == []


def test_too_young_unused_or_superseded_stay_out():
    assert candidates(_exp(_f("y", turn=95), _f("n", confirmed=0),
                           _f("s", status="superseded", confirmed=9))) == []


def test_exactly_at_the_floors_is_in():
    age, used = PROMOTE_RULES["min_age_turns"], PROMOTE_RULES["min_confirmed"]
    assert candidates(_exp(_f("x", turn=100 - age, confirmed=used)))


def test_an_already_promoted_fact_is_skipped():
    assert candidates(_exp(_f("a1")), promoted={"a1"}) == []


def test_facts_group_by_their_first_concept_and_rank_by_use():
    c = candidates(_exp(_f("a", concepts=("wal", "pyturso"), confirmed=1),
                        _f("b", concepts=("turso",), confirmed=3),
                        _f("c", concepts=("wal",), kind="fix", confirmed=1)))
    assert [(x["keyword"], x["facts"]) for x in c] == [("turso", ["b"]), ("wal", ["a", "c"])]
    assert c[1]["tags"] == ["wal", "pyturso"]


def test_an_empty_or_broken_export_is_not_a_crash():
    assert candidates({}) == [] and candidates({"facts": None}) == []


def test_the_reports_say_what_happened():
    c = candidates(_exp(_f("a1")))
    assert "Nothing was written" in "\n".join(report_lines(c, applied=False))
    assert "Nothing was written" not in "\n".join(report_lines(c, applied=True))
    assert "rules" in "\n".join(report_lines([]))


def test_the_self_check_runs():
    from gray_matter import promote
    promote.demo()


# ---------- --apply: parent, chunks, the #id bridge ----------

def _apply(monkeypatch, export, answers=None, bridges=()):
    import gray_matter.server as srv
    import gray_matter.bridges as br
    calls = []

    async def fake_call(server, tool, args):
        calls.append((server, tool, args))
        if tool == "export":
            return json.dumps(export)
        if tool == "knowledge_add_node":
            return (answers or {}).get(args["name"], f"Created node '{args['name']}'")
        return "ok"
    monkeypatch.setattr(srv, "_call_server_async", fake_call)
    monkeypatch.setattr(br, "all_bridges", lambda: [{"neuron": b, "neurag": "x"} for b in bridges])
    monkeypatch.setattr(br, "add_bridge", lambda a, b, r="": calls.append(("bridge", a, b)) or True)
    return asyncio.run(srv._do_promote(apply=True)), calls


def test_apply_writes_parent_node_chunks_and_the_provenance_bridge(monkeypatch):
    r, calls = _apply(monkeypatch, _exp(_f("a1")))
    adds = [c[2] for c in calls if c[1] == "knowledge_add_node"]
    assert adds[0]["name"] == PROMOTE_PARENT and adds[1]["parent_name"] == PROMOTE_PARENT
    assert [c[2]["chunks"][0]["source"] for c in calls if c[1] == "knowledge_add_chunks"] == ["neuron:#a1"]
    assert [c[1:] for c in calls if c[0] == "bridge"] == [("#a1", "turso")]
    assert r["written"] == ["turso"] and r["chunks"] == 1


def test_a_new_fact_joins_an_existing_node_and_a_bridged_one_is_not_readded(monkeypatch):
    r, calls = _apply(monkeypatch, _exp(_f("a1"), _f("a2")),
                      {"turso": "Node 'turso' already exists (type=fundamental)."}, bridges=("#a1",))
    assert r["already"] == ["turso"] and r["chunks"] == 1
    assert [c[1:] for c in calls if c[0] == "bridge"] == [("#a2", "turso")]
