"""Ingesting one document, not just a tree.

A vault you can only fill by pointing at a folder makes you invent a folder for
every PDF someone sends you. The dispatch lives in `auto_ingest` — the funnel
the CLI, the MCP job and the control center all pass through — so the single
file reaches every surface without any of them being touched.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph  # noqa: E402
from neurag.ingest import auto_ingest, ingest_file  # noqa: E402


@pytest.fixture
def kg(tmp_path):
    g = KnowledgeGraph(tmp_path / "k.db")
    yield g
    g.close()


def _doc(tmp_path, name="nota.md", body="# Titolo\n\n" + "contenuto utile. " * 20):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_a_single_file_is_ingested_and_searchable(kg, tmp_path):
    rep = auto_ingest(kg, _doc(tmp_path))
    assert rep["files"] == 1 and rep["chunks"] > 0
    assert kg.search("contenuto utile"), "il documento non è recuperabile"


def test_the_default_godnode_is_the_containing_folder(kg, tmp_path):
    """Chi salva tre file nella stessa cartella si aspetta di ritrovarli
    insieme — il nome del file darebbe un godnode per documento."""
    folder = tmp_path / "appunti"
    folder.mkdir()
    rep = auto_ingest(kg, _doc(folder))
    assert rep["godnode"] == "appunti"


def test_an_explicit_godnode_wins(kg, tmp_path):
    rep = auto_ingest(kg, _doc(tmp_path), godnode="Ricerca")
    assert rep["godnode"] == "Ricerca"
    assert kg.get_node_by_name("Ricerca") is not None


def test_re_ingesting_the_same_file_replaces_it_instead_of_duplicating(kg, tmp_path):
    """Aggiornare un documento è l'operazione normale, non un caso da gestire."""
    doc = _doc(tmp_path)
    first = auto_ingest(kg, doc, godnode="R")["chunks"]
    again = auto_ingest(kg, doc, godnode="R")["chunks"]
    assert first == again
    total = kg._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert total == first, "il vault è raddoppiato al secondo ingest"


def test_two_files_in_one_godnode_both_survive(kg, tmp_path):
    """Il replace è PER SORGENTE: aggiungerne uno non cancella l'altro."""
    auto_ingest(kg, _doc(tmp_path, "a.md", "# A\n\n" + "alfa unico. " * 20), godnode="R")
    auto_ingest(kg, _doc(tmp_path, "b.md", "# B\n\n" + "beta unico. " * 20), godnode="R")
    assert kg.search("alfa unico") and kg.search("beta unico")


def test_an_unindexable_type_says_what_is_supported(kg, tmp_path):
    """Questo messaggio finisce in faccia all'utente nella GUI."""
    bad = tmp_path / "foto.jpeg"
    bad.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(ValueError) as exc:
        auto_ingest(kg, bad)
    assert ".md" in str(exc.value), "l'errore non elenca i tipi accettati"


def test_a_missing_path_is_not_reported_as_a_folder_problem(kg, tmp_path):
    with pytest.raises(FileNotFoundError):
        auto_ingest(kg, tmp_path / "non-esiste.md")


def test_the_folder_path_still_works(kg, tmp_path):
    """Il dispatch non deve aver rotto il caso che c'era prima."""
    folder = tmp_path / "albero"
    folder.mkdir()
    _doc(folder, "uno.md")
    _doc(folder, "due.md")
    rep = auto_ingest(kg, folder)
    assert rep["files"] == 2 and rep["godnode"] == "albero"


def test_ingest_file_is_callable_directly(kg, tmp_path):
    assert ingest_file(kg, _doc(tmp_path), godnode="X")["files"] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
