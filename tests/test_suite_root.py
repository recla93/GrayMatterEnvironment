"""Una sola radice: `<base>/GrayMatterEnvironment`.

Prima erano quattro radici scollegate — `graymatter/` (GM), `GrayMatterEnvironment/`
(solo il registro), `neuron/graphs`, `neurag/` — e niente diceva all'utente che
appartenessero allo stesso prodotto: non si poteva guardarci dentro, copiarle su
un'altra macchina o cancellarle in un gesto solo.

La transizione ha una regola sola e vale per tutti e tre i tool: **i dati che
esistono gia' vincono**. Cambiare dove si guarda non deve MAI poter far sparire
una memoria; il trasloco e' esplicito, non un effetto collaterale.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("GM_HOME", raising=False)
    monkeypatch.delenv("NEURAG_HOME", raising=False)
    monkeypatch.delenv("NS_GRAPHS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    return tmp_path


def _reload():
    from gray_matter import gme, paths
    importlib.reload(paths)
    importlib.reload(gme)
    return paths, gme


def test_everything_lands_under_one_root(base):
    paths, gme = _reload()
    suite = base / "GrayMatterEnvironment"
    assert paths._user_base() == suite
    assert paths.gm_home() == suite / "graymatter"
    assert gme.gme_root() == suite / "registry"
    for p in (paths.gm_state(), paths.manifest_path(), paths.gm_bridges()):
        assert str(p).startswith(str(suite)), f"{p} fuori dalla radice suite"


def test_existing_data_in_the_old_place_still_wins(base):
    """L'aggiornamento non deve far sparire una memoria: finche' il trasloco non
    e' avvenuto, si continua a leggere da dov'e'."""
    old = base / "neuron" / "graphs"
    old.mkdir(parents=True)
    (old / "graph_default.db").write_bytes(b"x")
    paths, _ = _reload()
    assert paths.neuron_graphs() == old, "ha smesso di vedere i grafi esistenti"


def test_the_new_place_wins_once_it_exists(base):
    old = base / "neuron" / "graphs"
    old.mkdir(parents=True)
    new = base / "GrayMatterEnvironment" / "neuron" / "graphs"
    new.mkdir(parents=True)
    paths, _ = _reload()
    assert paths.neuron_graphs() == new


def test_a_flat_registry_is_still_read(base):
    """Registro pre-suite: i .json stavano nella radice, non in registry/."""
    flat = base / "GrayMatterEnvironment"
    flat.mkdir(parents=True)
    (flat / "neuron.json").write_text('{"key":"neuron","python":"x"}', encoding="utf-8")
    _, gme = _reload()
    assert gme.gme_root() == flat
    assert gme.read_tool("neuron") is not None


def test_migration_moves_everything_and_verifies_before_deleting(base):
    old_graphs = base / "neuron" / "graphs"
    old_graphs.mkdir(parents=True)
    (old_graphs / "graph_default.db").write_bytes(b"memoria")
    old_gm = base / "graymatter"
    old_gm.mkdir(parents=True)
    (old_gm / "config.json").write_text("{}", encoding="utf-8")

    paths, _ = _reload()
    res = paths.migrate_to_suite_root()
    assert all(r["ok"] for r in res), res

    suite = base / "GrayMatterEnvironment"
    assert (suite / "neuron" / "graphs" / "graph_default.db").read_bytes() == b"memoria"
    assert (suite / "graymatter" / "config.json").exists()
    assert not old_graphs.exists(), "l'originale non e' stato rimosso dopo la verifica"
    importlib.reload(paths)
    assert paths.neuron_graphs() == suite / "neuron" / "graphs"


def test_migration_is_idempotent(base):
    old = base / "neuron" / "graphs"
    old.mkdir(parents=True)
    (old / "g.db").write_bytes(b"x")
    paths, _ = _reload()
    paths.migrate_to_suite_root()
    second = paths.migrate_to_suite_root()
    assert second == [] or all(r["ok"] for r in second)
    assert (base / "GrayMatterEnvironment" / "neuron" / "graphs" / "g.db").exists()


def test_migration_never_overwrites_an_existing_destination(base):
    """Se entrambe esistono e' il caso ambiguo: non si sceglie per l'utente."""
    old = base / "neuron" / "graphs"
    old.mkdir(parents=True)
    (old / "g.db").write_bytes(b"vecchio")
    new = base / "GrayMatterEnvironment" / "neuron" / "graphs"
    new.mkdir(parents=True)
    (new / "g.db").write_bytes(b"nuovo")

    paths, _ = _reload()
    paths.migrate_to_suite_root()
    assert (new / "g.db").read_bytes() == b"nuovo"
    assert old.exists(), "ha cancellato l'originale senza averlo copiato"


def test_dry_run_touches_nothing(base):
    old = base / "neuron" / "graphs"
    old.mkdir(parents=True)
    (old / "g.db").write_bytes(b"x")
    paths, _ = _reload()
    res = paths.migrate_to_suite_root(dry_run=True)
    assert res and all(r["ok"] for r in res)
    assert old.exists()
    assert not (base / "GrayMatterEnvironment" / "neuron").exists()
