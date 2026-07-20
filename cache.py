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

    # Dynamic TTL (D-roadmap §2): a topic that keeps getting hits is "hot" and
    # earns a longer life; cold topics keep the base TTL. Bounded at 3x.
    # ponytail: linear +50% per hit capped at 3x — tune only if stats say so.
    _HOT_STEP, _HOT_CAP = 0.5, 3.0

    def __init__(self, max_size: int = 100, ttl: float = 60.0):
        self._max_size = max_size
        self._ttl = ttl
        self._data: OrderedDict[str, tuple[float, str, int]] = OrderedDict()

    def _ttl_for(self, hits: int) -> float:
        return self._ttl * min(self._HOT_CAP, 1.0 + self._HOT_STEP * hits)

    def get(self, topic: str) -> Optional[str]:
        """Return cached response if present and not expired."""
        now = time.time()
        entry = self._data.get(topic)
        if entry is None:
            return None
        timestamp, response, hits = entry
        if now - timestamp > self._ttl_for(hits):
            del self._data[topic]
            return None
        self._data[topic] = (timestamp, response, hits + 1)
        self._data.move_to_end(topic)
        return response

    def set(self, topic: str, response: str) -> None:
        # keep the hit count across refreshes so a hot topic stays hot
        hits = self._data[topic][2] if topic in self._data else 0
        self._data[topic] = (time.time(), response, hits)
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
