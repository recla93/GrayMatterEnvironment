"""The AI indexes only the folders the user chose, and never keys (ADR-012 F3).

knowledge_ingest and knowledge_index took ANY path, and index returns the text:
an AI steered by a hostile document, or anyone on an open bridge, could read a
config full of secrets off the disk.
"""
import asyncio
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.chunker import is_secret, scan_directory  # noqa: E402
from neurag.ingest import ai_ingest_refusal  # noqa: E402


@pytest.fixture
def tree(tmp_path, monkeypatch):
    allowed, outside = tmp_path / "notes", tmp_path / "private"
    (allowed / ".git").mkdir(parents=True)
    outside.mkdir()
    (allowed / "a.md").write_text("# nota\nruns on nginx", encoding="utf-8")
    (allowed / "prod.env").write_text("TOKEN=s3cret", encoding="utf-8")
    (allowed / ".git" / "config.md").write_text("[remote] token", encoding="utf-8")
    (outside / "b.md").write_text("riservato", encoding="utf-8")
    monkeypatch.setenv("NEURAG_INGEST_ROOTS", str(allowed))
    return allowed, outside


@pytest.mark.parametrize("name", ["id_rsa", ".env", ".env.local", "server.pem",
                                  "cert.pfx", "credentials", ".git-credentials",
                                  ".ssh/config.md", ".aws/notes.md"])
def test_keys_and_credentials_are_recognised(name):
    assert is_secret(name)


@pytest.mark.parametrize("name", ["notes.md", "token-budget.md", "keyboard.md", "env.md"])
def test_ordinary_names_are_not(name):
    assert not is_secret(name)


def test_no_roots_declared_means_the_ai_reads_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("NEURAG_INGEST_ROOTS", raising=False)
    monkeypatch.setattr("neurag.settings.get", lambda k, path=None: "")
    why = ai_ingest_refusal(tmp_path)
    assert why and "ingest_roots" in why, "il rifiuto deve dire come sbloccarlo"


def test_inside_a_root_passes_outside_and_escapes_do_not(tree):
    allowed, outside = tree
    assert ai_ingest_refusal(allowed / "a.md") is None
    assert ai_ingest_refusal(outside / "b.md")
    assert ai_ingest_refusal(allowed / ".." / "private" / "b.md"), "'..' esce dalla radice"
    assert ai_ingest_refusal(allowed / "prod.env"), "un segreto dentro la radice resta fuori"


def test_every_walk_skips_secrets_and_hidden_folders(tree):
    allowed, _ = tree
    assert [p.name for p in scan_directory(allowed)] == ["a.md"]


def test_a_symlink_out_of_the_root_is_not_followed(tree):
    allowed, outside = tree
    try:
        os.symlink(outside / "b.md", allowed / "link.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlink non consentiti su questa macchina")
    assert "link.md" not in [p.name for p in scan_directory(allowed)]


def test_the_tool_refuses_before_reading(tree):
    from neurag import server
    _, outside = tree
    out = asyncio.run(server.call_tool("knowledge_index", {"path": str(outside / "b.md")}))
    assert "refused" in out[0].text and "riservato" not in out[0].text
