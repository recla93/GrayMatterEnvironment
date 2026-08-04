"""Il registro GME e' condiviso: scrivere non deve MAI perdere quello che c'era.

Ci scrivono, in momenti diversi e da versioni diverse: l'installer
(`register_installed`), il monitor di salute (`update_health`), l'uninstall
(`mark_missing`) e i tool della suite. Finche' `write_tool` sovrascriveva il file
con quello che sapeva un solo writer, ogni reinstall azzerava `linked_to`,
buttava `health` e resettava `installed_at` — dati che nessuno aveva deciso di
buttare.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def gme(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from gray_matter import gme as _g
    importlib.reload(_g)
    return _g


def _base(**over):
    d = {"key": "neuron", "label": "Neuron", "version": "6.4.0",
         "venv": "/v", "python": "/v/python", "module": "neuron",
         "cli_module": "neuron.__main__", "status": "installed"}
    d.update(over)
    return d


def test_reinstall_does_not_wipe_linked_to(gme):
    """register_installed() scrive sempre linked_to=None: non sa chi gestisce il
    tool. Prima azzerava il gateway a ogni reinstall."""
    gme.write_tool(_base(linked_to="gray-matter"))
    gme.write_tool(_base(linked_to=None))          # il reinstall
    assert gme.read_tool("neuron")["linked_to"] == "gray-matter"


def test_health_is_merged_not_replaced(gme):
    gme.write_tool(_base())
    gme.update_health("neuron", {"pid": 123, "memory_mb": 400})
    gme.update_health("neuron", {"pid": 456})       # aggiorno solo il pid
    h = gme.read_tool("neuron")["health"]
    assert h["pid"] == 456
    assert h["memory_mb"] == 400, "l'aggiornamento parziale ha buttato il resto"


def test_first_install_time_survives(gme):
    gme.write_tool(_base())
    first = gme.read_tool("neuron")["installed_at"]
    gme.write_tool(_base(version="6.5.0"))
    again = gme.read_tool("neuron")
    assert again["installed_at"] == first
    assert again["version"] == "6.5.0"
    assert again["updated_at"] >= first


def test_unknown_fields_from_another_version_survive(gme):
    """Una versione futura (o un altro tool) aggiunge un campo: non e' spazzatura
    da buttare solo perche' questo writer non lo conosce."""
    gme.write_tool(_base(custom_field={"a": 1}, tags=["x"]))
    gme.write_tool(_base(version="7.0.0"))
    d = gme.read_tool("neuron")
    assert d["custom_field"] == {"a": 1}
    assert d["tags"] == ["x"]


def test_mark_missing_keeps_the_record(gme):
    """L'uninstall marca, non cancella: un reinstall successivo deve ritrovare
    da dove veniva il tool."""
    gme.write_tool(_base(source="/repo/neuron", linked_to="gray-matter"))
    gme.mark_missing("neuron")
    d = gme.read_tool("neuron")
    assert d["status"] == "missing"
    assert d["source"] == "/repo/neuron"
    assert d["linked_to"] == "gray-matter"


def test_a_corrupt_entry_is_set_aside_not_destroyed(gme):
    """JSON troncato da un crash: sovrascriverlo in silenzio distrugge l'unica
    copia di quello che c'era."""
    gme.write_tool(_base())
    p = gme.tool_json_path("neuron")
    p.write_text('{"key": "neuron", "venv": "/v", tronc', encoding="utf-8")
    gme.write_tool(_base())
    assert gme.read_tool("neuron")["key"] == "neuron"       # riscritto
    saved = p.with_suffix(".json.corrupt")
    assert saved.exists() and "tronc" in saved.read_text(encoding="utf-8")


def test_replace_is_still_possible_when_asked(gme):
    gme.write_tool(_base(linked_to="gray-matter"))
    gme.write_tool(_base(), merge=False)
    assert gme.read_tool("neuron").get("linked_to") is None


def test_the_written_file_stays_valid_json(gme):
    gme.write_tool(_base(health={"pid": 1}))
    raw = gme.tool_json_path("neuron").read_text(encoding="utf-8")
    assert json.loads(raw)["key"] == "neuron"
