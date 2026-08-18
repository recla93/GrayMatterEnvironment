"""B4 — promozione bridge → confirm Neuron al crossing di _PROMOTE_AT usi.

Store = tabella `bridges` (sqlite locale in sandbox); si verifica via API
(`all_bridges()`), mai leggendo il file grezzo. `promoted` è un INTEGER (truthy).
"""
import json


def _use(monkeypatch, tmp_path, times):
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    from gray_matter import bridges
    bridges.add_bridge("kafka", "streaming", "test")
    out = []
    for _ in range(times):
        out = bridges.bridges_for("kafka")
    return out


def test_promotion_fires_once_at_threshold(monkeypatch, tmp_path):
    from gray_matter import bridges
    # peso parte da 1 (add), ogni bridges_for fa +1 → soglia al giro _PROMOTE_AT-1
    out = _use(monkeypatch, tmp_path, bridges._PROMOTE_AT - 1)
    assert out[0].get("_just_promoted") is True
    # il flag NON è persistito; `promoted` sì → mai ri-promosso
    saved = bridges.all_bridges()
    assert saved[0]["promoted"]
    assert "_just_promoted" not in saved[0]
    again = bridges.bridges_for("kafka")
    assert "_just_promoted" not in again[0]


def test_below_threshold_no_promotion(monkeypatch, tmp_path):
    out = _use(monkeypatch, tmp_path, 1)
    assert "_just_promoted" not in out[0]


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
