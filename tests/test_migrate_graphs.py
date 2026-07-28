"""Slug migration: neuron5 -> neuron, per file.

The version this replaces moved the whole directory with one shutil.move and
refused with "New path already has data" as soon as the destination held
anything — which it does the moment Neuron runs once under the new slug. On a
real machine that left five graphs stranded in neuron5 with a migration that
would never run again. These lock in that it moves what it can and never
overwrites what it cannot.
"""
from __future__ import annotations

import os
import sys

from tests._mockdeps import install_mock_deps, unpoison_turso
install_mock_deps()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from neuron import paths as _paths          # noqa: E402
unpoison_turso()


def _layout(tmp_path, monkeypatch, old_names=(), new_names=()):
    """Point both slugs inside tmp and seed each side with named graph files."""
    monkeypatch.delenv("NEURON_SLUG", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    old = tmp_path / "neuron5" / "graphs"
    new = tmp_path / "neuron" / "graphs"
    monkeypatch.setattr(_paths, "graphs_dir", lambda: str(new))
    for d, names in ((old, old_names), (new, new_names)):
        if names:
            d.mkdir(parents=True, exist_ok=True)
        for n in names:
            (d / n).write_text(n, encoding="utf-8")
    return old, new


def test_migrates_when_destination_already_has_data(tmp_path, monkeypatch):
    """The exact case the old code refused: destination non-empty."""
    old, new = _layout(tmp_path, monkeypatch,
                       old_names=["graph_default.db", "graph_backend.db"],
                       new_names=["graph_software.db"])

    r = _paths.migrate_graphs()
    assert r["error"] == ""
    assert sorted(r["migrated"]) == ["graph_backend.db", "graph_default.db"]
    assert r["collisions"] == []
    assert sorted(p.name for p in new.iterdir()) == [
        "graph_backend.db", "graph_default.db", "graph_software.db"]
    assert not old.exists()                       # emptied and dropped


def test_collision_is_never_overwritten(tmp_path, monkeypatch):
    old, new = _layout(tmp_path, monkeypatch,
                       old_names=["graph_gm.db", "graph_backend.db"],
                       new_names=["graph_gm.db"])
    (new / "graph_gm.db").write_text("NEWER", encoding="utf-8")

    r = _paths.migrate_graphs()
    assert r["migrated"] == ["graph_backend.db"]
    assert r["collisions"] == ["graph_gm.db"]
    assert (new / "graph_gm.db").read_text(encoding="utf-8") == "NEWER"
    assert (old / "graph_gm.db").exists()         # the other copy still reachable
    assert old.exists()                           # kept: the user's data is in it


def test_dry_run_moves_nothing(tmp_path, monkeypatch):
    old, new = _layout(tmp_path, monkeypatch,
                       old_names=["graph_default.db"], new_names=["graph_x.db"])
    r = _paths.migrate_graphs(dry_run=True)
    assert r["migrated"] == ["graph_default.db"]
    assert (old / "graph_default.db").exists()
    assert not (new / "graph_default.db").exists()


def test_idempotent(tmp_path, monkeypatch):
    _layout(tmp_path, monkeypatch, old_names=["graph_default.db"], new_names=[])
    first = _paths.migrate_graphs()
    second = _paths.migrate_graphs()
    assert first["migrated"] == ["graph_default.db"]
    assert second["migrated"] == [] and second["error"] == ""


def test_pinned_old_slug_is_left_alone(tmp_path, monkeypatch):
    old, new = _layout(tmp_path, monkeypatch, old_names=["graph_default.db"])
    monkeypatch.setenv("NEURON_SLUG", "neuron5")
    r = _paths.migrate_graphs()
    assert r["migrated"] == [] and (old / "graph_default.db").exists()


def test_nothing_to_do_without_old_dir(tmp_path, monkeypatch):
    _layout(tmp_path, monkeypatch, new_names=["graph_default.db"])
    r = _paths.migrate_graphs()
    assert r["migrated"] == [] and r["collisions"] == [] and r["error"] == ""


def test_stale_paths_json_is_dropped_only_when_the_new_slug_has_one(tmp_path, monkeypatch):
    """paths.json records which source dir Neuron was installed from — not user
    data. Left behind it keeps the retired neuron5 folder alive and the legacy
    scan reporting it. Removed only once the current slug has its own."""
    old, new = _layout(tmp_path, monkeypatch, old_names=["graph_default.db"])
    (old.parent / "paths.json").write_text("{}", encoding="utf-8")

    # nessun paths.json nel nuovo slug -> non si tocca niente
    r = _paths.migrate_graphs()
    assert (old.parent / "paths.json").exists()

    # ora il nuovo slug ce l'ha: il fossile va via e la vecchia cartella sparisce
    (new.parent / "paths.json").write_text("{}", encoding="utf-8")
    (old / "graph_x.db").parent.mkdir(parents=True, exist_ok=True)
    (old / "graph_x.db").write_text("x", encoding="utf-8")
    r = _paths.migrate_graphs()
    assert "graph_x.db" in r["migrated"]
    assert not (old.parent / "paths.json").exists()
    assert not old.parent.exists()
