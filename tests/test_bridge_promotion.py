"""B4 — promozione bridge → confirm Neuron al crossing di _PROMOTE_AT usi."""
import json


def _use(monkeypatch, tmp_path, times):
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.json"))
    from gray_matter import bridges
    bridges.add_bridge("kafka", "streaming", "test")
    out = []
    for _ in range(times):
        out = bridges.bridges_for("kafka")
    return out


def test_promotion_fires_once_at_threshold(monkeypatch, tmp_path):
    from gray_matter.bridges import _PROMOTE_AT
    # peso parte da 1 (add), ogni bridges_for fa +1 → soglia al giro _PROMOTE_AT-1
    out = _use(monkeypatch, tmp_path, _PROMOTE_AT - 1)
    assert out[0].get("_just_promoted") is True
    # il flag NON è persistito; `promoted` sì → mai ri-promosso
    saved = json.loads((tmp_path / "bridges.json").read_text(encoding="utf-8"))
    assert saved[0]["promoted"] is True
    assert "_just_promoted" not in saved[0]
    from gray_matter import bridges
    again = bridges.bridges_for("kafka")
    assert "_just_promoted" not in again[0]


def test_below_threshold_no_promotion(monkeypatch, tmp_path):
    out = _use(monkeypatch, tmp_path, 1)
    assert "_just_promoted" not in out[0]
