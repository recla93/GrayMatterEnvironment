"""The chunk size ceiling, and the breadcrumb that makes a chunk findable.

Both exist because of the same silent failure. Every embedding model NeuRAG
ships truncates at **128 tokens** (~490 chars, measured: 488 chars encoded to
exactly 128). A markdown section or a Python class is one meaningful unit but
routinely runs to thousands of characters, and nothing in the chunker capped it.
The oversized chunk was stored, displayed fine in the GUI, and everything past
the window was dropped from its vector — so the chunk was unfindable, with no
error anywhere. Bigger files simply retrieved worse.

There is no unit test that can catch that by inspecting one function: the guard
has to hold for EVERY file type, so it is asserted at `chunk_file`, the single
exit every producer funnels through.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.chunker import (DEFAULT_MAX_CHARS, OVERLAP_RATIO, _split_text,
                            chunk_file, chunk_markdown, enforce_budget)
from neurag.models import Chunk

BUDGET = 400

LONG_PARAGRAPH = ("Questo paragrafo parla di salienza, di retrieval semantico e "
                  "di come i chunk vengono indicizzati nel vault. ") * 30


# --- the ceiling holds for every file type ----------------------------------

@pytest.mark.parametrize("name,body", [
    ("doc.md", "# Titolo\n\n" + LONG_PARAGRAPH + "\n\n## Sezione\n\n" + LONG_PARAGRAPH),
    ("mod.py", "class Big:\n" + "".join(
        f"    def m{i}(self):\n        return {i}  # {'x' * 60}\n" for i in range(40))),
    ("app.ts", "export function big() {\n" + "".join(
        f"  const v{i} = {i}; // {'y' * 60}\n" for i in range(40)) + "}\n"),
    ("notes.txt", LONG_PARAGRAPH),
    ("conf.yaml", "\n".join(f"key{i}: {'z' * 70}" for i in range(60))),
])
def test_no_chunk_exceeds_the_budget(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    chunks = chunk_file(p, BUDGET)
    assert chunks, f"{name} produced nothing"
    worst = max(len(c.text) for c in chunks)
    assert worst <= BUDGET, (
        f"{name}: a {worst}-char chunk escaped the {BUDGET}-char ceiling — "
        "everything past the model window is dropped from the vector silently")


def test_the_default_budget_fits_the_shipped_models():
    """128 tokens is the real window; the default must sit under it."""
    assert 0 < DEFAULT_MAX_CHARS <= 128 * 4


def test_budget_zero_disables_the_ceiling(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text(LONG_PARAGRAPH, encoding="utf-8")
    assert max(len(c.text) for c in chunk_file(p, 0)) > BUDGET


# --- splitting behaviour -----------------------------------------------------

def test_split_prefers_the_coarsest_boundary_that_works():
    text = "\n\n".join(["alpha " * 20, "bravo " * 20, "charlie " * 20])
    parts = _split_text(text, 200, 0)
    assert len(parts) > 1
    # each piece stays within one paragraph rather than cutting mid-sentence
    for p in parts:
        assert p.count("alpha") == 0 or p.count("bravo") == 0


def test_split_handles_text_with_no_separator_at_all():
    parts = _split_text("x" * 1000, 100, 0)
    assert parts and max(len(p) for p in parts) <= 100
    assert "".join(parts) == "x" * 1000


def test_overlap_is_taken_out_of_the_budget_not_added_on_top():
    """An overlapped chunk that exceeds the window defeats the whole point."""
    parts = _split_text(LONG_PARAGRAPH, BUDGET, int(BUDGET * OVERLAP_RATIO))
    assert len(parts) > 1
    assert max(len(p) for p in parts) <= BUDGET


def test_enforce_budget_renumbers_and_marks_parts():
    big = Chunk(text=LONG_PARAGRAPH, source="s.md", section="Intro", chunk_index=0)
    out = enforce_budget([big], BUDGET)
    assert len(out) > 1
    assert [c.chunk_index for c in out] == list(range(len(out)))
    assert out[0].section.startswith("Intro (1/")
    assert all(c.tags == [] for c in out)          # tags carried, not invented


def test_enforce_budget_preserves_tags_across_parts():
    big = Chunk(text=LONG_PARAGRAPH, source="s.py", section="def f",
                chunk_index=0, tags=["alpha", "beta"])
    out = enforce_budget([big], BUDGET)
    assert len(out) > 1
    assert all(c.tags == ["alpha", "beta"] for c in out)


# --- the breadcrumb ----------------------------------------------------------

def test_markdown_section_is_the_full_heading_path(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("# Install\n\nintro text here padded out\n\n"
                 "## Windows\n\nwindows text here padded out\n\n"
                 "### venv\n\nrun the script, nothing else identifying\n",
                 encoding="utf-8")
    sections = [c.section for c in chunk_markdown(p)]
    assert "Install > Windows > venv" in sections, sections


def test_markdown_splits_on_h1_and_h6(tmp_path):
    """`#{2,4}` ignored H1 — a doc using `#` for sections came out as ONE chunk."""
    p = tmp_path / "doc.md"
    p.write_text("# Uno\n\nprimo blocco di testo abbastanza lungo\n\n"
                 "# Due\n\nsecondo blocco di testo abbastanza lungo\n\n"
                 "###### Sei\n\nsesto livello con testo abbastanza lungo\n",
                 encoding="utf-8")
    sections = [c.section for c in chunk_markdown(p)]
    assert "Uno" in sections and "Due" in sections and "Uno > Due" not in sections
    assert any(s.endswith("Sei") for s in sections), sections


def test_sibling_headings_do_not_nest(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("## A\n\ntesto di riempimento sufficiente\n\n"
                 "## B\n\naltro testo di riempimento sufficiente\n", encoding="utf-8")
    sections = [c.section for c in chunk_markdown(p)]
    assert "B" in sections and "A > B" not in sections


# --- generated artefacts are not knowledge -----------------------------------

def test_ingest_skips_generated_artefact_dirs(tmp_path):
    """Tool caches are machine-generated path indexes, not knowledge.

    Measured on a real tree: ingesting `neurag/` pulled in `graphify-out/cache`
    and produced 8352 chunks instead of 1571 — 81% of the vault was JSON blobs
    listing every file path in the project. Every project name then appeared as
    a token in every chunk, so each node looked "mentioned" everywhere and the
    `cache` node came out linked to six nodes at weight 1.0. Embedding and
    searching that text costs real time and returns nothing anyone wants.
    """
    from neurag.db import KnowledgeGraph
    from neurag.ingest import auto_ingest

    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "graphify-out" / "cache").mkdir(parents=True)
    (root / "build").mkdir()
    (root / "src" / "real.md").write_text(
        "## Vero\ncontenuto reale sufficientemente lungo da diventare un chunk\n",
        encoding="utf-8")
    (root / "graphify-out" / "cache" / "index.json").write_text(
        '{"' + '":1,"'.join(f"C:/x/y/file{i}.py" for i in range(50)) + '":1}',
        encoding="utf-8")
    (root / "build" / "out.json").write_text('{"generated": true}', encoding="utf-8")

    kg = KnowledgeGraph(tmp_path / "vault.db")
    report = auto_ingest(kg, root)
    sources = {r[0] for r in kg._conn.execute("SELECT DISTINCT source FROM chunks").fetchall()}
    assert report["files"] == 1, f"ingested generated files: {sources}"
    assert not any("graphify-out" in s or "build" in s for s in sources), sources
    names = {r[0] for r in kg._conn.execute("SELECT name FROM nodes").fetchall()}
    assert "cache" not in names and "graphify-out" not in names, names
    kg.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
