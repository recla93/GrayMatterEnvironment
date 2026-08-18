"""Turso engine per file locali + ranking vettoriale in SQL (vector_distance_cos).

Con pyturso installato verifica che il path SQL ordini per similarità reale.
"""
import sqlite3

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
    # engine label mirrors Neuron's ENGINE_NAME: "Turso (cloud/local)" | "SQLite"
    assert kg.status()["engine"] == ("Turso (local)" if TURSO_AVAILABLE else "SQLite")


def test_semantic_ranking_best_first(kg):
    r = kg.search("kotlin", top_n=2)
    assert r and "Kotlin" in r[0]["text"]


@pytest.mark.skipif(not TURSO_AVAILABLE, reason="pyturso non installato")
def test_sql_vector_path_matches_python_cosine(kg):
    sql_top = kg.search("spring", top_n=3)
    # Il confronto da solo non dimostra niente: finché la query SQL sollevava
    # "no such function: f32blob" l'except la mandava sul cosine Python, e
    # questo test confrontava Python con Python — passando. Il latch è la prova
    # che il ramo SQL è arrivato in fondo.
    assert kg._vector_sql_ok, "il ranking SQL è degradato: la query non gira sull'engine"
    # forza il fallback Python sulla stessa query e confronta l'ordine
    kg._vector_sql = False
    py_top = kg.search("spring", top_n=3)
    kg._vector_sql = True
    assert [r["text"] for r in sql_top][:1] == [r["text"] for r in py_top][:1]
    assert "Spring" in sql_top[0]["text"]


@pytest.mark.skipif(not TURSO_AVAILABLE, reason="pyturso non installato")
def test_vector_sql_query_runs_on_the_engine(kg):
    """Regressione diretta: la SQL di `_vector_candidates` deve eseguire.

    `f32blob` non esiste in nessun build libSQL/pyturso — `vector_distance_cos`
    accetta già il blob. Il wrapper rendeva la query un parse error permanente.
    """
    qv = kg._embedder.embed("spring")
    rows = kg._vector_candidates(qv, top_n=3, scope=None)

    assert kg._vector_sql_ok, "la query SQL ha sollevato 'no such function'"
    assert rows and "Spring" in rows[0]["text"]


def test_missing_function_latches_the_sql_tier_off(kg, capsys):
    """"no such function" spegne il ramo SQL e avvisa UNA volta, poi tace."""
    class NoVectorConn:
        def __init__(self, real): self._real = real
        def execute(self, sql, *a, **kw):
            if "vector_distance_cos" in sql:
                raise sqlite3.OperationalError("no such function: vector_distance_cos")
            return self._real.execute(sql, *a, **kw)

    kg._vector_sql = True
    kg._vector_sql_ok = True
    kg._conn = NoVectorConn(kg._conn)
    qv = kg._embedder.embed("spring")

    first = kg._vector_candidates(qv, top_n=3, scope=None)
    assert kg._vector_sql_ok is False, "un errore permanente deve spegnere il ramo SQL"
    assert first, "il fallback Python deve comunque restituire risultati"
    assert "vector_distance_cos" in capsys.readouterr().err

    kg._vector_candidates(qv, top_n=3, scope=None)
    assert capsys.readouterr().err == "", "l'avviso va stampato una volta sola"


def test_transient_error_does_not_latch(kg):
    """Un lock è transitorio: il ramo SQL resta acceso per il prossimo tentativo."""
    class LockedConn:
        def __init__(self, real): self._real = real
        def execute(self, sql, *a, **kw):
            if "vector_distance_cos" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._real.execute(sql, *a, **kw)

    kg._vector_sql = True
    kg._vector_sql_ok = True
    kg._conn = LockedConn(kg._conn)

    kg._vector_candidates(kg._embedder.embed("spring"), top_n=3, scope=None)

    assert kg._vector_sql_ok is True, "un lock non deve spegnere il ramo SQL"
