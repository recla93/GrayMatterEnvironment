"""Quanto contesto GM inietta è un budget, non un effetto collaterale.

Il senso del progetto è far RISPARMIARE token. Il blocco proattivo della pulse —
bridge, vicini, flash: roba che nessuno ha chiesto — non aveva alcun tetto:
40 bridge che condividevano un tag valevano ~5000 token in una sola pulse, e
`bridges_for` rinforzava ogni match, quindi un match di massa era anche una
promozione di massa verso la soglia che dice a Neuron "questo concetto vale".

Il match per identità di tag ha reso quel caso PIÙ facile, non meno: un tag
condiviso basta, dove prima serviva che il topic contenesse la stringa.
"""
import pytest


@pytest.fixture
def B(tmp_path, monkeypatch):
    import importlib

    from gray_matter import bridges
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    importlib.reload(bridges)
    return bridges


# ---------- il tetto sui bridge ----------

def test_limit_caps_what_comes_back(B):
    for i in range(40):
        B.add_bridge(f"concetto_{i}", f"Nodo_{i}")
    tags = {f"nodo_{i}" for i in range(40)}
    assert len(B.bridges_for("topic muto", tags=tags)) == 40      # senza limite
    assert len(B.bridges_for("topic muto", tags=tags, limit=5)) == 5


def test_the_strongest_survive_the_cut(B):
    for i in range(6):
        B.add_bridge(f"c_{i}", f"Nodo_{i}")
    # porta c_3 in cima usandolo da solo
    for _ in range(4):
        B.bridges_for("c_3")
    top = B.bridges_for("topic muto", tags={f"nodo_{i}" for i in range(6)}, limit=2)
    assert top[0]["neuron"] == "c_3"
    assert top[0]["weight"] > top[1]["weight"]


def test_what_is_not_shown_is_not_reinforced(B):
    """La regola era già scritta nel docstring — "far emergere un bridge è
    usarlo" — ma match e rinforzo stavano nello stesso loop, quindi si
    rinforzava anche ciò che il chiamante non mostrava mai."""
    for i in range(10):
        B.add_bridge(f"c_{i}", f"Nodo_{i}")
    tags = {f"nodo_{i}" for i in range(10)}
    shown = {b["neuron"] for b in B.bridges_for("topic muto", tags=tags, limit=3)}
    assert len(shown) == 3
    for b in B.all_bridges():
        expected = 2 if b["neuron"] in shown else 1
        assert b["weight"] == expected, f"{b['neuron']}: peso {b['weight']}"


def test_mass_matching_no_longer_mass_promotes(B):
    """Con 40 match per pulse e la soglia a 5, un giro di pulse promuoveva
    l'intero store — e ogni promozione manda un `confirm` a Neuron."""
    for i in range(40):
        B.add_bridge(f"c_{i}", f"Nodo_{i}")
    tags = {f"nodo_{i}" for i in range(40)}
    for _ in range(6):
        B.bridges_for("topic muto", tags=tags, limit=5)
    promoted = [b for b in B.all_bridges() if b["promoted"]]
    assert len(promoted) <= 5, f"{len(promoted)} bridge promossi in 6 pulse"


def test_limit_zero_means_none(B):
    B.add_bridge("quorum", "Spec")
    assert B.bridges_for("quorum", limit=0) == []
    assert B.all_bridges()[0]["weight"] == 1, "nemmeno rinforzati"


# ---------- il budget proattivo ----------

def _fit():
    from gray_matter.server import _fit
    return _fit


def test_blocks_are_dropped_whole_never_cut_mid_sentence():
    fit = _fit()
    text, dropped = fit(20, ["dodici char.", "un altro blocco lungo"])
    assert text == "dodici char."
    assert dropped == 1


def test_a_block_too_big_is_skipped_not_a_stop_signal():
    """Sono spunti indipendenti: farne entrare di più nello stesso budget vale
    più di un prefisso stretto dell'ordine di priorità."""
    fit = _fit()
    text, dropped = fit(10, ["primo", "secondo", "terzo"])
    assert text == "primo\n\nterzo"      # "secondo" non entra (5+7 > 10), "terzo" sì
    assert dropped == 1


def test_order_is_otherwise_preserved():
    fit = _fit()
    text, _ = fit(100, ["primo", "secondo", "terzo"])
    assert text.index("primo") < text.index("secondo") < text.index("terzo")


def test_a_zero_budget_keeps_nothing():
    fit = _fit()
    text, dropped = fit(0, ["qualcosa"])
    assert text == "" and dropped == 1


def test_empty_blocks_are_not_counted_as_dropped():
    fit = _fit()
    text, dropped = fit(100, ["", None, "vero"])
    assert text == "vero" and dropped == 0


def test_everything_fits_when_the_budget_is_generous():
    fit = _fit()
    text, dropped = fit(10_000, ["a", "b", "c"])
    assert text == "a\n\nb\n\nc" and dropped == 0


# ---------- le manopole esistono e sono raggiungibili dalla GUI ----------

def test_the_memory_budget_is_passed_and_not_left_to_the_tool_default():
    """`get_context` has always had a char budget from `max_tokens`, but GM
    never passed it — so the oldest item in a pulse was the one thing the user
    could not turn down. The default matches the tool's own, so exposing the
    knob changed nothing by itself."""
    import inspect

    from gray_matter import server, settings

    src = inspect.getsource(server.call_tool)
    assert '"max_tokens": MEMORY_MAX_TOKENS' in src, (
        "get_context is back on the tool's own default")
    assert server.MEMORY_MAX_TOKENS == settings.DEFAULTS["memory_max_tokens"] == 400


def test_the_injection_knobs_exist_with_help():
    """La GUI costruisce la sua card da `<tool> config list --json`, e
    `_knob_dict` legge HELP con un fallback a {} — quindi per un bel po' OGNI
    knob di GM è stato reso senza una riga di spiegazione."""
    from gray_matter import settings
    for key in ("knowledge_top_n", "proactive_budget_chars"):
        assert key in settings.DEFAULTS
        assert settings.HELP.get(key, "").strip(), f"{key} senza help: la GUI lo mostra nudo"


def test_every_gm_knob_is_documented():
    from gray_matter import settings
    missing = [k for k in settings.DEFAULTS if not settings.HELP.get(k, "").strip()]
    assert not missing, f"knob senza help (la GUI li mostra nudi): {missing}"


def test_config_list_json_carries_the_knobs_to_the_gui():
    import json

    from gray_matter.cli import _knob_dict
    from gray_matter import settings

    cfg = settings.load()
    knobs = [_knob_dict(k, cfg, settings) for k in sorted(settings.DEFAULTS)]
    payload = json.loads(json.dumps({"knobs": knobs}))     # deve serializzare
    keys = {k["key"] for k in payload["knobs"]}
    assert {"knowledge_top_n", "proactive_budget_chars"} <= keys
    for k in payload["knobs"]:
        assert set(k) == {"key", "value", "default", "type", "help", "suggest"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
