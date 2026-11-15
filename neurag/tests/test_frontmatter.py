"""YAML frontmatter is metadata, not text (2026-11-15).

It was embedded raw into the first chunk of every Obsidian note: `---\\ntags: [...]`
sat in the vector of the intro, and the tags a human wrote never reached the node.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.chunker import chunk_markdown, split_frontmatter


def test_inline_and_block_lists():
    meta, body = split_frontmatter(
        "---\ntitle: \"Piano: tre tempi\"\ntags: [piano, neurag]\naliases:\n  - Digestione\n"
        "  - 'Ingest'\ncreated: 2026-11-15\n---\n# Body\n")
    assert meta == {"title": "Piano: tre tempi", "tags": ["piano", "neurag"],
                    "aliases": ["Digestione", "Ingest"], "created": "2026-11-15"}
    assert body == "# Body\n"


def test_no_frontmatter_is_untouched():
    for text in ("# Title\n---\nnot: meta\n---\n", "text\n", "---\nnever closed\n"):
        assert split_frontmatter(text) == ({}, text)


def test_chunks_drop_the_block_and_carry_its_tags(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("---\ntitle: Ingest pipeline\ntags: [RAG, '#obsidian']\ntype: guida\n---\n"
                 "Intro paragraph long enough to become a chunk of its own.\n\n"
                 "## Watcher\nDebounce two seconds before re-indexing a saved note.\n",
                 encoding="utf-8")
    card, *rest = chunk_markdown(p)
    # the card keeps what made the raw block findable (title, tags), minus the YAML
    assert (card.section, card.text) == ("", "Ingest pipeline\ntags: rag, obsidian")
    assert [c.section for c in rest] == ["Ingest pipeline", "Watcher"]
    assert [c.chunk_index for c in (card, *rest)] == [0, 1, 2]
    assert not any("---" in c.text or "type:" in c.text for c in (card, *rest))
    assert all(c.tags[:2] == ["rag", "obsidian"] for c in (card, *rest))


def test_tiny_frontmatter_makes_no_card(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("---\ntags: [ab]\n---\n", encoding="utf-8")
    assert chunk_markdown(p) == []
