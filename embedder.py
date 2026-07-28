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
_MODEL = (os.environ.get("NEURAG_EMBED_MODEL")
          or os.environ.get("NS_EMBED_MODEL")
          or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
DIM = 384


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
