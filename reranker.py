"""Optional cross-encoder reranker for NeuRAG — OFF by default.

Second-stage precision: the first stage (vector / lexical / hybrid) retrieves a
generous candidate pool cheaply, then — if enabled — a cross-encoder rescoring
reorders the pool and keeps the true top-n. This is the standard RAG pattern
(retrieve wide, rerank narrow); it trades latency for precision, so it is an
explicit opt-in (`neurag config set rerank on`, or env NEURAG_RERANK=on).

Same design as embedder.py: lazy import, graceful fallback. If fastembed (or the
rerank model) is unavailable, or the toggle is off, `get_reranker()` returns a
NullReranker whose `rerank()` is the identity — zero cost, zero model download.
"""
from __future__ import annotations

import os

from neurag import settings


class NullReranker:
    """No reranking. `rerank` returns the candidates unchanged (identity)."""

    available = False
    name = "null"

    def rerank(self, query: str, candidates: list[dict], top_n: int) -> list[dict]:
        return candidates[:top_n]


class FastEmbedReranker:
    """Cross-encoder rescoring via fastembed.TextCrossEncoder.

    Lazy: the model loads on construction (first run downloads it — the known
    cost of turning rerank on). `rerank` scores each candidate's text against the
    query and returns the best `top_n`, highest score first.
    """

    available = True
    name = "fastembed-cross-encoder"

    def __init__(self, model: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder  # lazy
        self._m = TextCrossEncoder(model_name=model)

    def rerank(self, query: str, candidates: list[dict], top_n: int) -> list[dict]:
        if not candidates:
            return []
        docs = [(c.get("text") or "") for c in candidates]
        try:
            scores = list(self._m.rerank(query, docs))
        except Exception:  # noqa: BLE001 — any scoring failure → keep first-stage order
            return candidates[:top_n]
        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:top_n]]


def get_reranker(path=None):
    """Return the active reranker. OFF (NullReranker) unless the toggle is on
    AND fastembed is importable. Explicit env request that can't load must not
    silently downgrade; the config-driven path degrades gracefully."""
    if not settings.rerank_enabled(path):
        return NullReranker()
    # Lazy: read model name only when rerank is actually enabled (audit 2026-07-22)
    model = (os.environ.get("NEURAG_RERANK_MODEL")
             or settings.get("rerank_model")
             or "Xenova/ms-marco-MiniLM-L-6-v2")
    explicit_env = os.environ.get("NEURAG_RERANK") is not None
    try:
        return FastEmbedReranker(model)
    except Exception:
        if explicit_env:
            raise  # a one-off `NEURAG_RERANK=on` must surface why it failed
        return NullReranker()  # config toggle on but model absent: don't break search


def demo() -> None:
    """Runnable self-check (stdlib only): null routing is the identity."""
    r = NullReranker()
    cand = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    assert r.rerank("q", cand, 2) == cand[:2]
    print("reranker OK: null routing = identity")


if __name__ == "__main__":
    demo()
