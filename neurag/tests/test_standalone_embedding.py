"""NeuRAG alone must be able to embed. It could not.

`fastembed` was declared only as the optional `semantic` extra, and no installer
ever requested that extra — so a standalone NeuRAG resolved to NullEmbedder and
searched lexically. It embedded only when Neuron (which has fastembed as a HARD
dependency) happened to be installed in the same venv, silently borrowing it.

That made "NeuRAG alone" a degraded mode rather than the baseline, and it failed
without a word: pick `multilingual-e5-large` at install time and you got worse
results than the default, with nothing anywhere saying why.

The dependency assertion is the load-bearing test here — everything else can be
fixed after the fact, but if the declaration regresses the whole class of bug
comes back invisibly.
"""
import pathlib
import sys
import tomllib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from neurag import embedder


def _pyproject(name: str) -> dict:
    return tomllib.loads((ROOT.parent / name / "pyproject.toml").read_text(encoding="utf-8"))


def test_fastembed_is_a_hard_dependency_not_an_extra():
    deps = " ".join(_pyproject("neurag")["project"]["dependencies"])
    assert "fastembed" in deps, (
        "fastembed is back to being optional — a standalone NeuRAG will fall "
        "back to lexical search and never say so")


_NEURON_PYPROJECT = ROOT.parent / "neuron" / "pyproject.toml"


@pytest.mark.skipif(
    not _NEURON_PYPROJECT.exists(),
    reason="parita' con Neuron: serve il sibling, che in standalone non c'e'")
def test_neurag_declares_the_same_embedder_as_neuron():
    """One vector space across the suite starts with one dependency pin.

    Reads the SIBLING repo, so it can only run where both are checked out --
    `ci.yml`, which is also the only place where the two pins can actually
    diverge. The standalone job installs NeuRAG alone on purpose: there a
    missing `neuron/pyproject.toml` is the arrangement, not a regression, and
    letting it raise FileNotFoundError turned the one job that proves NeuRAG
    stands alone into a job that says it cannot.
    """
    def pin(pkg, dep):
        for d in _pyproject(pkg)["project"]["dependencies"]:
            if d.startswith(dep):
                return d.replace(" ", "")
        return None
    assert pin("neurag", "fastembed") == pin("neuron", "fastembed")


def test_pyturso_stays_mandatory():
    """Vector SQL is the default tier; sqlite3 is the fallback, not the target."""
    deps = " ".join(_pyproject("neurag")["project"]["dependencies"])
    assert "pyturso" in deps


# --- requested lexical vs accidental lexical --------------------------------

def test_none_is_recognised_as_a_deliberate_choice(monkeypatch):
    monkeypatch.setattr(embedder, "_resolve_model", lambda: "none")
    assert embedder.lexical_only_requested() is True
    assert embedder.get_embedder().name == "null"


def test_a_real_model_is_not_a_lexical_request(monkeypatch):
    monkeypatch.setattr(embedder, "_resolve_model",
                        lambda: "intfloat/multilingual-e5-large")
    assert embedder.lexical_only_requested() is False


def test_env_null_is_a_deliberate_choice(monkeypatch):
    monkeypatch.setenv("NEURAG_EMBEDDER", "null")
    assert embedder.lexical_only_requested() is True


def test_status_distinguishes_requested_from_degraded(tmp_path, monkeypatch):
    """Both end at NullEmbedder; reporting them identically is how a broken
    semantic install stayed invisible."""
    from neurag.db import KnowledgeGraph

    monkeypatch.setenv("NEURAG_EMBEDDER", "null")
    kg = KnowledgeGraph(tmp_path / "requested.db")
    assert kg.status()["search_mode"] == "lexical (requested)"
    assert "warning" not in kg.status()
    kg.close()

    # Now the accident: a model IS configured, but the embedder failed to load.
    monkeypatch.delenv("NEURAG_EMBEDDER", raising=False)
    kg2 = KnowledgeGraph(tmp_path / "degraded.db")
    kg2._embedder = embedder.NullEmbedder()
    monkeypatch.setattr(embedder, "_resolve_model",
                        lambda: "sentence-transformers/all-MiniLM-L6-v2")
    st = kg2.status()
    assert st["search_mode"] == "lexical (DEGRADED)"
    assert "fastembed" in st["warning"]
    kg2.close()


def test_status_reports_the_real_embedding_dim(tmp_path):
    """Was hardcoded 384 — wrong as soon as anyone picked mpnet (768) or
    e5-large (1024), and this is the number the GUI shows."""
    from neurag.db import KnowledgeGraph

    kg = KnowledgeGraph(tmp_path / "dim.db")
    kg._embedder = embedder.NullEmbedder()
    kg._embedder.dim = 1024
    assert kg.status()["embedding_dim"] == 1024
    kg.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
