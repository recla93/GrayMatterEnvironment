"""The reorganised control center: sections per task and per tool, every
argument explained for someone who does not code, bridges editable by hand."""
import json
import re
from pathlib import Path

import pytest

from gray_matter import catalog

HTML = (Path(__file__).resolve().parents[1] / "webgui.html").read_text(encoding="utf-8")
PANELS = {"config", "repair", "uninstall", "link"}   # rendered as panels, not forms


def _commands(lang="it"):
    for env in catalog.environments(lang):
        if env["installed"]:
            for c in env["commands"]:
                yield env["key"], c


def test_every_command_lands_in_a_known_section():
    keys = {k for k, _it, _en in catalog.SECTIONS}
    bad = [(t, c["name"], c["section"]) for t, c in _commands() if c["section"] not in keys]
    assert not bad, bad


def test_section_overrides_name_real_commands():
    """An override for a command that no longer exists is a silent no-op."""
    installed = {e["key"] for e in catalog.environments() if e["installed"]}
    real = {(t, c["name"]) for t, c in _commands()}
    stale = {k for k in catalog.SECTION_OF if k[0] in installed} - real
    assert not stale, sorted(stale)


def test_operational_maintenance_and_settings_stay_apart():
    sec = {(t, c["name"]): c["section"] for t, c in _commands()}
    assert sec.get(("neurag", "query")) == "ops"
    assert sec.get(("neurag", "archive")) == "graph"
    assert sec.get(("gray-matter", "repair")) == "tools"
    assert sec.get(("gray-matter", "config")) == "settings"
    assert sec.get(("neurag", "config")) == "settings"


@pytest.mark.parametrize("lang", ["it", "en"])
def test_every_form_argument_is_explained_in_both_languages(lang):
    """argparse help is English and terse: the GUI must say what each field
    means in plain words, in the language the user picked."""
    missing = [(t, c["name"], a["dest"]) for t, c in _commands(lang) if c["name"] not in PANELS
               for a in c["args"] if not catalog.arg_doc(t, c["name"], a["dest"], lang)]
    assert not missing, f"[{lang}] arguments without a plain explanation: {missing}"


def test_arg_docs_are_complete_and_translated():
    for key, (it, en) in catalog.ARG_DOCS.items():
        assert it.strip() and en.strip() and it != en, key


def test_machine_only_arguments_are_hidden_from_forms():
    assert not [(t, c["name"]) for t, c in _commands() if any(a["dest"] == "json" for a in c["args"])]


def test_the_page_has_the_sections_the_legend_and_the_command_line():
    for view in ("overview", "graphs", "bridges", "guide"):
        assert f'view_{view}:' in HTML and HTML.count(f"view_{view}_sub:") == 2, view
    assert "const LEGEND" in HTML and "const GLOSSARY" in HTML
    assert "function cmdLine" in HTML, "the exact command line is not shown"
    for method in ("bridges_list", "bridge_add", "bridge_update", "bridge_remove"):
        assert f'call("{method}"' in HTML, method


def test_the_graph_is_interactive_and_edits_only_through_apis():
    """Physics knobs, drawn bridges, KB node actions — and no store access:
    bridges go through the bridge_* endpoints, KB edits through neurag's CLI."""
    for needle in ("gm_graph_phys", "addEdgeMode", "function bridgeEnd", "function newBridgeForm",
                   'runN("archive"', 'runN("rename-node"', "getConnectedNodes"):
        assert needle in HTML, needle


def test_page_strings_exist_in_both_languages():
    it = set(re.findall(r"^    (\w+):", HTML.split("  en: {")[0], re.M))
    en = set(re.findall(r"^    (\w+):", HTML.split("  en: {")[1].split("\n  },")[0], re.M))
    assert it == en, {"only it": sorted(it - en), "only en": sorted(en - it)}


def test_command_line_mirrors_argv_for():
    """The line shown to the user must be the argv the backend builds."""
    from gray_matter import webgui
    spec = {"path": {"dest": "path", "flag": "", "is_flag": False},
            "godnode": {"dest": "godnode", "flag": "--godnode", "is_flag": False},
            "code": {"dest": "code", "flag": "--code", "is_flag": True}}
    argv = webgui._argv_for("neurag", "ingest", {"_spec": spec, "_order": ["path", "godnode", "code"],
                                                 "path": "docs", "godnode": "Root", "code": True})
    assert argv[-5:] == ["ingest", "docs", "--godnode", "Root", "--code"]


def test_health_asks_the_daemon_what_really_runs(monkeypatch):
    """The GME pid is empty for gateway-hosted tools: they read "stopped"
    while they answered. The daemon's status is the truth when it is up."""
    from gray_matter import cli, webgui
    monkeypatch.setattr(cli, "_send_ipc", lambda msg, timeout=0, connect_timeout=None:
                        {"neuron": {"status": "alive"}, "neurag": {"status": "dead"}})
    got = {t["key"]: (t["status"], t["via"]) for t in webgui.Api().health_state()["tools"]}
    assert got.get("gray-matter") == ("running", "daemon")
    assert got.get("neuron") == ("running", "gateway")
    assert got.get("neurag", ("", ""))[1] == ""


def test_health_without_daemon_keeps_the_old_answer(monkeypatch):
    from gray_matter import cli, webgui
    monkeypatch.setattr(cli, "_send_ipc", lambda *a, **k: {"error": "down"})
    assert all(t["via"] == "" for t in webgui.Api().health_state()["tools"])


# ── bridges: hand edits on GM's own store ───────────────────────────
@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    from gray_matter import bridges
    bridges.add_bridge("kafka", "Streaming", "test")
    return bridges


def test_update_changes_rationale_and_weight(store):
    assert store.update_bridge("Kafka", "streaming", rationale="new why", weight=4)
    b = store.all_bridges()[0]
    assert (b["rationale"], b["weight"]) == ("new why", 4)


def test_update_refuses_a_missing_bridge_or_a_bad_weight(store):
    assert not store.update_bridge("nope", "streaming", rationale="x")
    assert not store.update_bridge("kafka", "streaming", weight=0)
    assert not store.update_bridge("kafka", "streaming")
    assert store.all_bridges()[0]["weight"] == 1


def test_remove_deletes_one_bridge(store):
    store.add_bridge("redis", "Streaming")
    assert store.remove_bridge("KAFKA", "Streaming")
    assert not store.remove_bridge("kafka", "streaming")
    assert [b["neuron"] for b in store.all_bridges()] == ["redis"]


def test_api_add_checks_the_neurag_node_through_the_tool(store, monkeypatch):
    """ADR-016: the NeuRAG end is validated by asking NeuRAG, never its store."""
    from gray_matter import cli, webgui
    calls = []

    def fake(msg, timeout=0, connect_timeout=None):
        calls.append(msg)
        return {"result": json.dumps({"node": {"name": "Streaming Data"}})}
    monkeypatch.setattr(cli, "_send_ipc", fake)
    api = webgui.Api()
    miss = api.bridge_add(json.dumps({"neuron": "kafka", "neurag": "streaming"}))
    assert not miss["ok"] and miss["suggest"] == "Streaming Data"
    ok = api.bridge_add(json.dumps({"neuron": "kafka", "neurag": "streaming data", "rationale": "r"}))
    assert ok == {"ok": True, "created": True}
    assert calls[0]["action"] == "gm-neurag" and calls[0]["tool"] == "knowledge_neighbors"
    names = {(b["neuron"], b["neurag"]) for b in api.bridges_list()["bridges"]}
    assert ("kafka", "Streaming Data") in names


def test_api_update_and_remove_round_trip(store):
    from gray_matter import webgui
    api = webgui.Api()
    assert api.bridge_update(json.dumps({"neuron": "kafka", "neurag": "Streaming", "weight": "x"}))["ok"] is False
    assert api.bridge_update(json.dumps({"neuron": "kafka", "neurag": "Streaming", "weight": "2.5"}))["ok"]
    assert api.bridges_list()["bridges"][0]["weight"] == 2.5
    assert api.bridge_remove(json.dumps({"neuron": "kafka", "neurag": "Streaming"}))["ok"]
    assert api.bridges_list()["bridges"] == []
