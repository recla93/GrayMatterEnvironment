"""ADR-016 D5: a bridge grows when re-affirmed, not when shown.

Store = the `bridges` table (local sqlite in a sandbox), checked through the API
(`all_bridges()`), never by reading the raw file.
"""
import json


def test_showing_a_bridge_keeps_it_alive_but_never_strengthens_it(monkeypatch, tmp_path):
    """It used to gain weight per display and, at 5, confirm its concept in
    Neuron: a bridge matching many topics promoted itself."""
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    from gray_matter import bridges
    bridges.add_bridge("kafka", "streaming", "test")
    before = bridges.all_bridges()[0]["last_used"]
    for _ in range(6):
        bridges.bridges_for("kafka")
    b = bridges.all_bridges()[0]
    assert (b["weight"], b["promoted"]) == (1, 0) and b["last_used"] >= before, b
    bridges.add_bridge("kafka", "streaming")            # re-affirmed: that is use
    assert bridges.all_bridges()[0]["weight"] == 2


def test_migrates_legacy_json_once(monkeypatch, tmp_path):
    """Un bridges.json legacy viene importato una volta sola e rinominato."""
    legacy = tmp_path / "bridges.json"
    legacy.write_text(json.dumps([
        {"neuron": "kafka", "neurag": "streaming", "rationale": "r",
         "weight": 3, "promoted": True},
        {"neuron": "x", "neurag": "y"},        # endpoint troppo corti → scartati
    ]), encoding="utf-8")
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(legacy))  # .json → store in .db sibling
    from gray_matter import bridges
    rows = bridges.all_bridges()
    assert len(rows) == 1
    b = rows[0]
    assert (b["neuron"], b["neurag"]) == ("kafka", "streaming")
    assert b["weight"] == 3 and b["promoted"]
    # one-shot: il json è stato rinominato e non viene re-importato
    assert not legacy.exists()
    assert legacy.with_suffix(".json.migrated").exists()
    bridges.add_bridge("kafka", "streaming")   # tocca lo store di nuovo
    assert len(bridges.all_bridges()) == 1
