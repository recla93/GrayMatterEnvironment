"""Who speaks at session start, and with which tool names.

Two failures this pins, both of which shipped:

* **Double handshake.** Every installer deployed its own hook, so a full suite
  opened each session with two. The blunt fix was to empty the Cowork plugin's
  hooks.json — which killed the handshake for Cowork entirely. Now all three
  tools deploy the SAME file to the SAME path and the owner is resolved at
  RUNTIME, so deploying twice is a no-op instead of a duplicate.

* **Wrong tool prefix.** The prefix was hardcoded to `mcp__gray-matter__`, so a
  STANDALONE install told the model to call tools that do not exist in that
  session — the mirror of the old `mcp__neuron5__*` bug.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

ASSET_DIRS = {
    "neuron": ROOT / "neuron" / "src" / "neuron" / "clients",
    "neurag": ROOT / "neurag" / "clients",
}
SHARED = [
    "claude-code-hook/neuron_sessionstart_hook.py",
    "opencode-plugin/neuron-handshake.mjs",
    "deploy_hooks.py",
    "cowork-plugin/neuron-guard/hooks/hooks.json",
    "cowork-plugin/neuron-guard/hooks/neuron_sessionstart_hook.py",
]


def _hook():
    path = ASSET_DIRS["neuron"] / "claude-code-hook" / "neuron_sessionstart_hook.py"
    spec = importlib.util.spec_from_file_location("_hs", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the copies must never drift ---------------------------------------------

@pytest.mark.parametrize("asset", SHARED)
def test_every_tool_ships_the_same_asset(asset):
    """Byte-identical, so 'keep in sync' is enforced rather than hoped for."""
    blobs = {}
    for tool, d in ASSET_DIRS.items():
        p = d / asset
        assert p.is_file(), f"{tool} is missing {asset}"
        blobs[tool] = p.read_bytes()
    first = next(iter(blobs.values()))
    for tool, b in blobs.items():
        assert b == first, f"{tool}/{asset} has drifted from the other copies"


# --- ownership: exactly one speaker, decided at runtime ----------------------

OWNER_CASES = [
    ({"gray-matter", "neuron", "neurag"}, "gray-matter"),   # full suite
    ({"gray-matter", "neuron"},           "gray-matter"),   # GM + Neuron
    ({"gray-matter", "neurag"},           "gray-matter"),   # GM + NeuRAG
    ({"neuron"},                          "neuron"),        # standalone
    ({"neurag"},                          "neurag"),        # standalone
    (set(),                               None),            # nothing installed
]


@pytest.mark.parametrize("installed,expected", OWNER_CASES)
def test_exactly_one_owner(installed, expected):
    assert _hook().owner(installed) == expected


@pytest.mark.parametrize("installed,expected", OWNER_CASES)
def test_the_prefix_is_the_owners(installed, expected):
    """A standalone Neuron must say mcp__neuron__, never mcp__gray-matter__."""
    m = _hook()
    if expected is None:
        return
    text = m.handshake(expected, installed)
    if not text:
        return
    assert f"mcp__{expected}__" in text
    for other in {"gray-matter", "neuron", "neurag"} - {expected}:
        assert f"mcp__{other}__" not in text, (
            f"handshake for {expected} names {other}'s tools")


# --- content follows the CAPABILITIES actually installed ---------------------

def test_gateway_without_neuron_does_not_announce_memory():
    """GM + NeuRAG has no memory loop behind it. Announcing pre_turn/store_turn
    there points the model at tools that are not running."""
    text = _hook().handshake("gray-matter", {"gray-matter", "neurag"})
    assert "pre_turn" not in text and "store_turn" not in text
    assert "knowledge_query" in text


def test_gateway_without_neurag_does_not_announce_knowledge():
    text = _hook().handshake("gray-matter", {"gray-matter", "neuron"})
    assert "pre_turn" in text
    assert "knowledge_query" not in text


def test_gateway_alone_says_nothing():
    """No peers = nothing to push. Silence beats a reminder about absent tools."""
    assert _hook().handshake("gray-matter", {"gray-matter"}) == ""


def test_full_suite_announces_both():
    text = _hook().handshake("gray-matter", {"gray-matter", "neuron", "neurag"})
    assert "pre_turn" in text and "knowledge_query" in text


# --- it can never break a session -------------------------------------------

def test_registry_failures_are_silent(monkeypatch, tmp_path):
    """A missing/garbage registry costs a no-op, never an exception at start."""
    m = _hook()
    monkeypatch.setattr(m, "_gme_root", lambda: tmp_path / "nope")
    assert m.installed_slugs() == set()

    real = tmp_path / "reg"
    real.mkdir()
    (real / "broken.json").write_text("{not json", encoding="utf-8")
    (real / "ok.json").write_text('{"key":"neuron","status":"installed"}', encoding="utf-8")
    monkeypatch.setattr(m, "_gme_root", lambda: real)
    assert m.installed_slugs() == {"neuron"}, "a broken file must not hide a good one"


def test_only_one_hook_speaks_per_session(tmp_path):
    """Il bug del 2026-08-03: la sessione si apriva con lo STESSO blocco due
    volte, perché il plugin Cowork registra questo script da CLAUDE_PLUGIN_ROOT
    e l'installer da ~/.claude/hooks — due percorsi, due esecuzioni, e la
    risoluzione del proprietario non può accorgersene perché ogni processo vede
    solo sé stesso. Il primo che rivendica la sessione parla."""
    m = _hook()
    assert m.claim("sess-abc", tmp_path) is True, "il primo deve parlare"
    assert m.claim("sess-abc", tmp_path) is False, "il secondo deve tacere"
    # sessioni diverse non si rubano il turno
    assert m.claim("sess-xyz", tmp_path) is True
    # fail-open: senza session_id si parla, meglio due volte che mai
    assert m.claim("", tmp_path) is True
    assert m.claim("", tmp_path) is True
    # temp non scrivibile: si parla lo stesso, mai un'eccezione all'avvio
    assert m.claim("sess-abc", tmp_path / "non" / "esiste") is True


def test_hook_imports_no_tool_package():
    """stdlib only: importing neuron/gray_matter here would make a broken venv
    able to slow down or fail every session start."""
    body = (ASSET_DIRS["neuron"] / "claude-code-hook"
            / "neuron_sessionstart_hook.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    for forbidden in ("import neuron", "import neurag", "import gray_matter",
                      "from neuron", "from neurag", "from gray_matter"):
        assert forbidden not in code, f"hook must not {forbidden}"


def test_cowork_hook_is_wired_again():
    """It was emptied to stop the double handshake; runtime ownership replaced
    that workaround, so the hook must be live."""
    import json
    body = json.loads((ASSET_DIRS["neuron"] / "cowork-plugin" / "neuron-guard"
                       / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    starts = body.get("hooks", {}).get("SessionStart") or []
    assert starts, "Cowork SessionStart hook is still disabled"
    cmds = [h.get("command", "") for e in starts for h in (e.get("hooks") or [])]
    assert any("neuron_sessionstart_hook.py" in c for c in cmds), cmds
    assert not any("neuron_handshake.py" in c for c in cmds), (
        "still points at the removed script that named mcp__neuron5__ tools")


# --- deploying twice must never produce two handshakes ----------------------

def _deployer():
    path = ASSET_DIRS["neuron"] / "deploy_hooks.py"
    spec = importlib.util.spec_from_file_location("_dh", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_deploy_is_idempotent_across_different_command_spellings(monkeypatch, tmp_path):
    """Gray Matter registers the hook as `"<venv>\python.exe" "<hook>"`; the
    standalone deployer uses `python "<hook>"`. Comparing whole command strings
    treated those as different and appended a SECOND SessionStart entry — the
    double handshake, reintroduced by the code meant to prevent it. Seen live.
    """
    import json
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    hook_path = home / ".claude" / "hooks" / "neuron_sessionstart_hook.py"
    settings = home / ".claude" / "settings.json"
    # pre-existing entry, GM's spelling
    settings.write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [
            {"type": "command", "command": '"C:/venv/python.exe" "%s"' % hook_path}]}]}}),
        encoding="utf-8")

    d = _deployer()
    d.deploy_claude_code(ASSET_DIRS["neuron"], dry_run=False)

    body = json.loads(settings.read_text(encoding="utf-8-sig"))
    cmds = [h.get("command", "") for e in body["hooks"]["SessionStart"]
            for h in (e.get("hooks") or [])]
    ours = [c for c in cmds if "neuron_sessionstart_hook" in c]
    assert len(ours) == 1, f"deploy added a duplicate handshake: {ours}"


def test_deploy_never_rewrites_an_unparseable_settings_file(monkeypatch, tmp_path):
    """A JSONC/broken settings.json is reported, never clobbered."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    settings = home / ".claude" / "settings.json"
    original = '{ // a comment\n "hooks": {} }'
    settings.write_text(original, encoding="utf-8")

    msg = _deployer().deploy_claude_code(ASSET_DIRS["neuron"], dry_run=False)
    assert "SKIPPED" in msg
    assert settings.read_text(encoding="utf-8") == original, "clobbered a config it could not parse"
