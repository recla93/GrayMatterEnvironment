"""Pluggable text embedder for NeuRAG.

Auto-detect: if `fastembed` is importable (i.e. NeuRAG runs next to Neuron, which
already ships it) the semantic embedder turns on by itself, sharing Neuron's
384-dim space. Otherwise NeuRAG stays lexical-only (NullEmbedder) — zero deps,
zero model download, fully standalone.

Override with env NEURAG_EMBEDDER = auto (default) | fastembed | null.
Model override with env NEURAG_EMBED_MODEL (default = Neuron's MiniLM).
"""

from __future__ import annotations

import os

# Same model Neuron defaults to → same 384-dim vector space when paired.
# Aligned 2026-07-20 (era all-MiniLM-L6-v2, English-only: spazio DIVERSO da
# Neuron e cieco sull'italiano). Ordine: override NeuRAG → override Neuron
# (una sola env governa la suite) → default multilingue IT/EN di Neuron.
_DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _setting(key: str):
    """The persisted install-time choice (neurag/settings.py). Never fatal: the
    embedder must still resolve if the config is missing or unreadable."""
    try:
        from neurag import settings
        return settings.get(key)
    except Exception:  # noqa: BLE001
        return None


def _resolve_model() -> str:
    # env (NeuRAG → Neuron) beats the persisted choice, which beats the default.
    return (os.environ.get("NEURAG_EMBED_MODEL")
            or os.environ.get("NS_EMBED_MODEL")
            or (_setting("embed_model") or "")
            or _DEFAULT_MODEL)


def _resolve_dim() -> int:
    """384 only because the DEFAULT model is 384-dim. The installer now lets the
    user pick an mpnet (768) or e5-large (1024), and a hardcoded 384 next to an
    overridable model silently mis-sizes every vector NeuRAG stores — the shared
    space with Neuron is the whole point of the model alignment above."""
    raw = os.environ.get("NEURAG_EMBED_DIM") or os.environ.get("NS_EMBED_DIM") or ""
    try:
        if str(raw).strip():
            return int(str(raw).strip())
    except (ValueError, TypeError):
        pass
    try:
        cfg = int(_setting("embed_dim") or 0)
        if cfg > 0:
            return cfg
    except (ValueError, TypeError):
        pass
    return 384


_MODEL = _resolve_model()
DIM = _resolve_dim()


class NullEmbedder:
    """No embeddings. `embed` returns None → callers use the lexical path."""

    dim = DIM
    available = False
    name = "null"

    def embed(self, text: str):
        return None


class FastEmbedEmbedder:
    """Semantic embeddings via fastembed. Lazy: model loads on construction
    (first run downloads it — the known cost of turning semantic mode on)."""

    dim = DIM
    available = True
    name = "fastembed"

    def __init__(self, model: str = _MODEL):
        from fastembed import TextEmbedding  # lazy: only imported in this branch
        # ponytail: onnxruntime defaults to a growing CPU memory arena + one
        # thread per core, tuned for high-throughput serving. This embeds one
        # short text at a time, never concurrently within a process — the
        # arena's "reuse across overlapping calls" benefit never applies here,
        # it just holds ~30MB extra resident for nothing. threads=2 is plenty
        # for a single sequential inference. Measured: ~4% lower resident
        # memory per worker, no latency change for this workload.
        self._m = TextEmbedding(model_name=model, threads=2, enable_cpu_mem_arena=False)

    def embed(self, text: str) -> list[float]:
        v = next(iter(self._m.embed([text])))
        return [float(x) for x in v]


def get_embedder():
    """Return the embedder per NEURAG_EMBEDDER. auto = fastembed if present else null."""
    choice = os.environ.get("NEURAG_EMBEDDER", "auto").lower()
    if choice == "null":
        return NullEmbedder()
    if choice in ("auto", "fastembed"):
        try:
            return FastEmbedEmbedder()
        except Exception:
            if choice == "fastembed":
                raise  # explicit request must not silently downgrade
            return NullEmbedder()  # auto: graceful fallback
    return NullEmbedder()


def demo() -> None:
    """Runnable self-check (stdlib only): factory routing + Null behaviour."""
    os.environ["NEURAG_EMBEDDER"] = "null"
    e = get_embedder()
    assert e.name == "null" and e.embed("anything") is None
    assert NullEmbedder().dim == DIM
    print("embedder OK: null routing + None embed")


if __name__ == "__main__":
    demo()
