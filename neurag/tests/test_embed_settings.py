"""Embedding model/dim resolution: env > persisted settings > default.

DIM used to be a hardcoded 384 next to an overridable model — fine while the
only model was 384-dim, wrong the moment the installer let anyone pick an
mpnet (768) or e5-large (1024).
"""

import importlib

import pytest

from neurag import embedder, settings


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Isolate the config (settings writes next to the vault via paths.py)."""
    monkeypatch.setenv("NEURAG_HOME", str(tmp_path))
    for var in ("NEURAG_EMBED_MODEL", "NEURAG_EMBED_DIM", "NS_EMBED_MODEL", "NS_EMBED_DIM"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _reload():
    importlib.reload(embedder)
    return embedder


def test_defaults_when_nothing_is_set(vault):
    e = _reload()
    assert e.DIM == 384
    assert e._MODEL.endswith("paraphrase-multilingual-MiniLM-L12-v2")


def test_persisted_settings_are_honoured(vault):
    settings.set("embed_model", "intfloat/multilingual-e5-large")
    settings.set("embed_dim", 1024)
    e = _reload()
    assert e._MODEL == "intfloat/multilingual-e5-large"
    assert e.DIM == 1024, "a 1024-dim model must not keep storing 384-wide vectors"


def test_env_beats_persisted_settings(vault, monkeypatch):
    settings.set("embed_model", "intfloat/multilingual-e5-large")
    settings.set("embed_dim", 1024)
    monkeypatch.setenv("NEURAG_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setenv("NEURAG_EMBED_DIM", "384")
    e = _reload()
    assert e._MODEL == "sentence-transformers/all-MiniLM-L6-v2"
    assert e.DIM == 384


def test_neurons_model_is_not_followed(vault, monkeypatch):
    """2026-11-27: Neuron's default became mpnet, worse on NeuRAG's bench
    (recall@5 0.933 -> 0.900, Italian 1.00 -> 0.857): NeuRAG keeps its own."""
    monkeypatch.setenv("NS_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
    monkeypatch.setenv("NS_EMBED_DIM", "768")
    e = _reload()
    assert e._MODEL.endswith("paraphrase-multilingual-MiniLM-L12-v2")
    assert e.DIM == 384


def test_empty_model_setting_falls_back_to_the_default(vault):
    """"" is the installer's "follow Neuron" answer — not a model named ""."""
    settings.set("embed_model", "")
    e = _reload()
    assert e._MODEL.endswith("paraphrase-multilingual-MiniLM-L12-v2")


def test_garbage_dim_does_not_crash_the_embedder(vault, monkeypatch):
    monkeypatch.setenv("NEURAG_EMBED_DIM", "not-a-number")
    e = _reload()
    assert e.DIM == 384


def teardown_module():
    """Leave the module in its real-environment state for the other tests."""
    importlib.reload(embedder)


def test_the_model_is_loaded_once_per_process(vault, monkeypatch):
    """Every KnowledgeGraph built its own embedder: 1.7 s of tokenizer and ONNX
    session each time (the suite took 7 minutes for it; an ingest job loaded a
    second model beside the server's). One per process, and a replaced class is
    never served the old instance."""
    e = _reload()
    built = []

    class Fake:
        name = "fastembed"

        def __init__(self):
            built.append(self)
    monkeypatch.setenv("NEURAG_EMBEDDER", "fastembed")
    monkeypatch.setattr(e, "FastEmbedEmbedder", Fake)
    assert e.get_embedder() is e.get_embedder() and len(built) == 1

    class Other(Fake):
        pass
    monkeypatch.setattr(e, "FastEmbedEmbedder", Other)
    assert isinstance(e.get_embedder(), Other) and len(built) == 2
