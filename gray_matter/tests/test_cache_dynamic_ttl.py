"""TTL dinamico (roadmap §2): topic caldi vivono più a lungo, bounded 3x."""
import time

from gray_matter.cache import ContextCache


def test_hot_topic_outlives_base_ttl():
    c = ContextCache(ttl=0.2)
    c.set("hot", "x")
    for _ in range(4):
        assert c.get("hot") == "x"
    time.sleep(0.35)                      # > TTL base, < TTL hot (cap 3x)
    assert c.get("hot") == "x"


def test_cold_topic_expires_at_base_ttl():
    c = ContextCache(ttl=0.2)
    c.set("cold", "y")
    time.sleep(0.25)
    assert c.get("cold") is None


def test_refresh_keeps_heat():
    c = ContextCache(ttl=10)
    c.set("t", "v1")
    c.get("t"); c.get("t")
    c.set("t", "v2")                      # refresh non azzera i hit
    assert c._data["t"][2] == 2
