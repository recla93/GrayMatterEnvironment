"""Turso engine per file locali + ranking vettoriale in SQL (vector_distance_cos).

Sul tier sqlite3 (pyturso assente) verifica il fallback; con pyturso installato
(la macchina locale) verifica che il path SQL ordini per similarità reale.
"""
import pytest

from neurag.db import KnowledgeGraph, TURSO_AVAILABLE


class _FixedEmbedder:
    """Embedding deterministico: proietta su 3 assi-parola note, dim 384."""

    name = "fixed"           # il contratto embedder reale espone .name (status)
    _AXES = ("spring", "kotlin", "python")

    def embed(self, text: str):
        t = text.lower()
        v = [0.0] * 384
        for i, w in enumerate(self._AXES):
            if w in t:
                v[i] = 1.0
        return v if any(v) else [0.001] * 384


@pytest.fixture
def kg(tmp_path):
    kg = KnowledgeGraph(db_path=tmp_path / "k.db")
    kg._embedder = _FixedEmbedder()
    root = kg.add_node(name="Root", node_type="godnode")
    n = kg.add_node(name="JVM", node_type="fundamental", parent_id=root)
    kg.add_chunk(n, "Spring Boot dependency injection", source="s.md")
    kg.add_chunk(n, "Kotlin coroutines guide", source="k.md")
    kg.add_chunk(n, "Python asyncio patterns", source="p.md")
    return kg


def test_engine_uses_turso_for_local_files_when_available(kg):
    assert kg._vector_sql == TURSO_AVAILABLE
    assert kg.status()["engine"] == ("turso" if TURSO_AVAILABLE else "sqlite")


def test_semantic_ranking_best_first(kg):
    r = kg.search("kotlin", top_n=2)
    assert r and "Kotlin" in r[0]["text"]


@pytest.mark.skipif(not TURSO_AVAILABLE, reason="pyturso non installato")
def test_sql_vector_path_matches_python_cosine(kg):
    sql_top = kg.search("spring", top_n=3)
    # forza il fallback Python sulla stessa query e confronta l'ordine
    kg._vector_sql = False
    py_top = kg.search("spring", top_n=3)
    kg._vector_sql = True
    assert [r["text"] for r in sql_top][:1] == [r["text"] for r in py_top][:1]
    assert "Spring" in sql_top[0]["text"]
