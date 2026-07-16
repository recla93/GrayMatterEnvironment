"""Gray-Matter — Context cache with TTL and LRU eviction."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Optional


class ContextCache:
    """In-memory cache for context responses.

    - LRU eviction when max_size is exceeded
    - TTL-based invalidation per entry
    - Automatic miss if topic changes (track last_topic)
    """

    def __init__(self, max_size: int = 100, ttl: float = 60.0):
        self._max_size = max_size
        self._ttl = ttl
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._last_topic: Optional[str] = None

    def get(self, topic: str) -> Optional[str]:
        """Return cached response if present and not expired."""
        now = time.time()
        entry = self._data.get(topic)
        if entry is None:
            return None
        timestamp, response = entry
        if now - timestamp > self._ttl:
            del self._data[topic]
            return None
        self._data.move_to_end(topic)
        return response

    def set(self, topic: str, response: str) -> None:
        # Topic change → invalidate previous
        if self._last_topic is not None and topic != self._last_topic:
            self.clear()
        self._data[topic] = (time.time(), response)
        self._last_topic = topic
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def invalidate(self, topic: str) -> None:
        self._data.pop(topic, None)

    def clear(self) -> None:
        self._data.clear()

    def size(self) -> int:
        return len(self._data)
