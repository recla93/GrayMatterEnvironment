"""D4 — conversation buffer: ultimi 3 topic, refresh su re-ask."""
import pytest


def test_remember_topic_lru_behavior():
    pytest.importorskip("mcp")
    import gray_matter.server as srv
    srv._topic_buffer.clear()
    for t in ("a", "b", "c", "d"):
        srv._remember_topic(t)
    assert list(srv._topic_buffer) == ["b", "c", "d"]   # maxlen 3
    srv._remember_topic("c")                            # re-ask → in cima
    assert list(srv._topic_buffer) == ["b", "d", "c"]
    srv._topic_buffer.clear()
