"""Tunable knobs (INSTALLER-UX §8). Type-safe get/set, overrides-only persistence."""
from gray_matter import settings as S


def test_defaults_when_no_file(tmp_path):
    cfg = S.load(tmp_path / "config.json")
    assert cfg["flash_min_gap"] == 3 and cfg["prewarm"] is True


def test_set_coerces_type(tmp_path):
    p = tmp_path / "config.json"
    cfg = S.set("flash_min_gap", "5", p)          # str -> int
    assert cfg["flash_min_gap"] == 5 and isinstance(cfg["flash_min_gap"], int)
    cfg = S.set("prewarm", "false", p)            # str -> bool
    assert cfg["prewarm"] is False


def test_set_unknown_key_raises(tmp_path):
    try:
        S.set("nope", "1", tmp_path / "config.json")
        assert False, "should raise"
    except KeyError:
        pass


def test_persists_only_overrides(tmp_path):
    import json
    p = tmp_path / "config.json"
    S.set("cache_ttl_seconds", "120", p)
    on_disk = json.loads(p.read_text())
    assert on_disk == {"cache_ttl_seconds": 120}   # defaults not written


def test_get_and_reload(tmp_path):
    p = tmp_path / "config.json"
    S.set("cache_max_size", "50", p)
    assert S.get("cache_max_size", p) == 50
