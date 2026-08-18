"""Changing the embedding model must not silently strand the vault's vectors.

`neurag config set embed_model X` used to succeed instantly, and every stored
vector became garbage the moment it did — vectors from two models are not
comparable, so the cosine between them is noise, not a weak match. The only
warning was prose in the knob's help text, which nothing enforced and nobody
had to read.

Two halves: the provenance is recorded NEXT TO the vectors (config.json can be
edited, copied or reset independently of the vault, so it cannot be the source
of truth), and `reindex` is the way out.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag import embedder
from neurag.db import KnowledgeGraph


def _vault(tmp_path, name="v.db"):
    return KnowledgeGraph(tmp_path / name)


# --- provenance --------------------------------------------------------------

def test_a_fresh_vault_claims_the_active_model(tmp_path):
    kg = _vault(tmp_path)
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "some text long enough to matter", source="a.md")
    stored = kg.stored_embed_signature()
    assert stored is not None
    assert stored == kg.active_embed_signature()
    kg.close()


def test_an_empty_vault_claims_nothing(tmp_path):
    kg = _vault(tmp_path)
    assert kg.stored_embed_signature() is None
    assert kg.embed_mismatch() is None
    kg.close()


def test_mismatch_is_detected_and_never_fatal(tmp_path):
    kg = _vault(tmp_path)
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "text that gets a vector", source="a.md")
    # Someone swapped the model behind the vault's back.
    kg.meta_set("embed_model", "intfloat/multilingual-e5-large")
    kg.meta_set("embed_dim", 1024)

    m = kg.embed_mismatch()
    if not getattr(kg._embedder, "available", False):
        pytest.skip("lexical-only environment: no vectors to mismatch")
    assert m is not None
    assert m["stored_model"] == "intfloat/multilingual-e5-large"
    assert m["embedded_chunks"] >= 1
    assert "reindex" in m["hint"]
    # ...and the vault still works (I5: never fatal).
    assert kg.status()["warning"]
    assert kg.search("text", top_n=3) is not None
    kg.close()


def test_the_first_new_chunk_does_not_overwrite_an_existing_claim(tmp_path):
    """Otherwise a mismatch erases itself as soon as anything is added."""
    kg = _vault(tmp_path)
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "first", source="a.md")
    kg.meta_set("embed_model", "some/other-model")
    kg.add_chunk(n, "second", source="a.md")
    assert kg.stored_embed_signature()[0] == "some/other-model"
    kg.close()


# --- reindex -----------------------------------------------------------------

def test_reindex_rebuilds_vectors_and_reclaims_the_vault(tmp_path):
    kg = _vault(tmp_path)
    if not getattr(kg._embedder, "available", False):
        pytest.skip("lexical-only environment")
    n = kg.add_node("N", "fundamental", parent_id=0)
    for i in range(3):
        kg.add_chunk(n, f"chunk number {i} with enough words to embed", source="a.md")
    kg.meta_set("embed_model", "stale/model")

    report = kg.reindex()
    assert report["ok"] and report["embedded"] == 3
    assert kg.stored_embed_signature() == kg.active_embed_signature()
    assert kg.embed_mismatch() is None
    kg.close()


def test_reindex_touches_only_vectors(tmp_path):
    """Chunk text, sections and links are knowledge — reindex must not alter
    them, and it must not need the source files."""
    kg = _vault(tmp_path)
    if not getattr(kg._embedder, "available", False):
        pytest.skip("lexical-only environment")
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "il testo originale resta intatto", section="Sez", source="gone.md")
    before = kg._conn.execute("SELECT text, section, source FROM chunks").fetchall()
    kg.reindex()
    after = kg._conn.execute("SELECT text, section, source FROM chunks").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]
    kg.close()


def test_progress_output_is_ascii_only(tmp_path):
    """A Windows console on the legacy cp1252 codepage raises UnicodeEncodeError
    on a bare arrow and takes the whole run down. Hit live: reindex died on
    "->" before it re-embedded anything."""
    kg = _vault(tmp_path)
    if not getattr(kg._embedder, "available", False):
        pytest.skip("lexical-only environment")
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "abbastanza testo per un vettore vero", source="a.md")
    lines: list[str] = []
    kg.reindex(say=lines.append)
    for line in lines:
        line.encode("cp1252")            # raises if a non-ASCII arrow crept back
    kg.close()


def test_reindex_in_lexical_mode_reports_instead_of_pretending(tmp_path, monkeypatch):
    kg = _vault(tmp_path)
    kg._embedder = embedder.NullEmbedder()
    report = kg.reindex()
    assert report["ok"] is False and "lexical" in report["reason"]
    kg.close()


# --- the guard ---------------------------------------------------------------

def test_guard_blocks_a_model_change_on_a_populated_vault(tmp_path, monkeypatch):
    from neurag import cli, settings

    kg = _vault(tmp_path, "guarded.db")
    if not getattr(kg._embedder, "available", False):
        pytest.skip("lexical-only environment")
    n = kg.add_node("N", "fundamental", parent_id=0)
    kg.add_chunk(n, "something embedded lives here", source="a.md")
    kg.close()

    monkeypatch.setattr(cli, "_embed_change_blocked",
                        cli._embed_change_blocked)          # keep the real one
    import neurag.db as dbmod
    monkeypatch.setattr(dbmod, "_DEFAULT_DB", tmp_path / "guarded.db")

    msg = cli._embed_change_blocked("embed_model", "intfloat/multilingual-e5-large")
    assert msg and "--force" in msg and "reindex" in msg
    msg.encode("cp1252")   # printed to a console that may be on the legacy codepage


def test_guard_allows_an_empty_vault(tmp_path, monkeypatch):
    from neurag import cli
    import neurag.db as dbmod
    monkeypatch.setattr(dbmod, "_DEFAULT_DB", tmp_path / "empty.db")
    assert cli._embed_change_blocked("embed_model", "whatever") == ""


def test_guard_allows_setting_the_same_value(tmp_path, monkeypatch):
    from neurag import cli, settings
    import neurag.db as dbmod
    monkeypatch.setattr(dbmod, "_DEFAULT_DB", tmp_path / "same.db")
    current = settings.get("embed_model")
    assert cli._embed_change_blocked("embed_model", current) == ""


def test_reindex_is_reachable_from_cli_and_mcp():
    """A fix nobody can invoke is not a fix."""
    from neurag.cli import COMMAND_GROUPS, build_parser
    actions = build_parser()._subparsers._group_actions[0].choices
    assert "reindex" in actions
    assert COMMAND_GROUPS.get("reindex"), "GUI would not render it (I7)"

    server_src = (pathlib.Path(__file__).resolve().parent.parent / "server.py").read_text(
        encoding="utf-8")
    assert '"knowledge_reindex"' in server_src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
