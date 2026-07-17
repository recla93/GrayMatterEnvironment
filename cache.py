"""Gray-Matter — Context cache with TTL and LRU eviction."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Optional


class ContextCache:
    """In-memory cache for context responses.

    - LRU eviction when max_size is exceeded
    - TTL-based invalidation per entry
    - Targeted invalidation on write (see invalidate_related)

    Note: an earlier version cleared the WHOLE cache on every topic change, so
    alternating topics evicted each other and the cache never accumulated (the
    "too aggressive" note in the backlog). Removed — LRU bounds memory and TTL
    bounds staleness; writes invalidate only the affected entries.
    """

    def __init__(self, max_size: int = 100, ttl: float = 60.0):
        self._max_size = max_size
        self._ttl = ttl
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()

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
        self._data[topic] = (time.time(), response)
        self._data.move_to_end(topic)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

    def invalidate(self, topic: str) -> None:
        self._data.pop(topic, None)

    def invalidate_related(self, term: str) -> int:
        """Drop entries whose topic overlaps `term` (either substring). Called after
        a write (store_turn) so a just-updated topic isn't served stale from cache.
        Returns how many entries were dropped."""
        t = (term or "").strip().lower()
        if not t:
            return 0
        doomed = [k for k in self._data if t in k.lower() or k.lower() in t]
        for k in doomed:
            del self._data[k]
        return len(doomed)

    def clear(self) -> None:
        self._data.clear()

    def size(self) -> int:
        return len(self._data)
