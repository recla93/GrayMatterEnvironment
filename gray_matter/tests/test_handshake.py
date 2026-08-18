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
import sys
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


def test_the_hook_finds_the_registry_gray_matter_actually_writes(monkeypatch, tmp_path):
    """L'anello che mancava: ogni altro test passa `installed` a mano, quindi
    `installed_slugs()` non veniva mai confrontato con un registro VERO.

    Il hook rispecchia `gme.gme_root()` senza importarlo, e il mirror era rimasto
    al layout piatto `<base>/GrayMatterEnvironment/*.json` quando il registro e'
    sceso in `.../registry/`. Su una macchina reale con i tre tool installati
    `installed_slugs()` tornava vuoto, `owner()` None, e l'handshake non e' mai
    partito. Questo test lega le due implementazioni: chi sposta la regola in
    gme.py rompe qui, non in produzione."""
    from gray_matter import gme

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    gme.write_tool({"key": "neuron", "label": "Neuron", "module": "neuron",
                    "status": "installed"})

    assert gme.gme_root().is_dir(), "GM non ha scritto dove crede"
    assert _hook().installed_slugs() == {"neuron"}, (
        f"il hook guarda in {_hook()._gme_root()}, GM scrive in {gme.gme_root()}")


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


@pytest.mark.parametrize("installed", [
    {"gray-matter", "neuron", "neurag"},        # memory block
    {"gray-matter", "neurag"},                  # knowledge block
])
def test_a_deferred_tool_is_not_an_absent_one(installed):
    """The escape clause used to fire on the wrong condition.

    Some clients defer MCP tool schemas: the tool is there, but calling it before
    the schema is loaded fails. The old closing line -- "if no mcp__*__ tools
    exist here, memory is not connected, ignore this silently" -- made that first
    failure and the permission to abandon the loop arrive on the same turn.

    So the block must (a) say to load and retry once, and (b) condition the
    give-up on the tool LIST being empty, never on a call having failed.
    """
    text = _hook().handshake("gray-matter", installed)
    assert "load its schema" in text, "no recovery offered for a deferred tool"
    assert "retry" in text
    assert "If no mcp__gray-matter__* tools exist here" not in text, (
        "the old unconditional escape clause is back")
    assert "no mcp__gray-matter__* entry" in text, (
        "giving up must be conditioned on the tool list, not on a failed call")


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
    r"""Gray Matter registers the hook as `"<venv>\python.exe" "<hook>"`; the
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


def _fake_home(monkeypatch, tmp_path):
    """I due deployer risolvono la home in modi diversi (`Path.home()` lo
    standalone, `os.path.expanduser` GM): vanno mockati entrambi i canali."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def test_opencode_entry_is_not_duplicated_by_the_other_installer(monkeypatch, tmp_path):
    """Stesso bug del doppio handshake, sull'altro client.

    GM scriveva `plugins/x.mjs` e lo standalone `./plugins/x.mjs`, e lo
    standalone confrontava la stringa INTERA: installato GM e poi un peer,
    `opencode.json` si ritrovava due entry per lo stesso file."""
    import json
    from gray_matter import executor

    home = _fake_home(monkeypatch, tmp_path)
    asset = ASSET_DIRS["neuron"] / "opencode-plugin" / "neuron-handshake.mjs"

    executor._deploy_opencode(asset, dry_run=False)          # prima GM
    _deployer().deploy_opencode(ASSET_DIRS["neuron"], dry_run=False)   # poi lo standalone

    cfgp = home / ".config" / "opencode" / "opencode.json"
    plugins = json.loads(cfgp.read_text(encoding="utf-8-sig"))["plugin"]
    ours = [p for p in plugins if "neuron-handshake" in p]
    assert len(ours) == 1, f"i due installer hanno duplicato l'entry: {plugins}"


def test_standalone_enables_the_plugin_in_codex_config(monkeypatch, tmp_path):
    """Il mirror da solo e' inerte: Codex carica un plugin cowork solo se
    elencato come abilitato. Lo standalone copiava e basta, quindi deployava un
    plugin che non sarebbe mai stato caricato."""
    home = _fake_home(monkeypatch, tmp_path)
    (home / ".codex").mkdir(parents=True)          # Codex presente, cache no

    msg = _deployer().deploy_cowork(ASSET_DIRS["neuron"], dry_run=False)

    assert "SKIPPED" not in msg, msg          # la cache mancante non e' un motivo per saltare
    cfg = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert '[plugins."neuron-guard@claude-cowork"]' in cfg, cfg
    assert "enabled = true" in cfg, cfg
    # idempotente: la seconda passata non duplica la sezione
    _deployer().deploy_cowork(ASSET_DIRS["neuron"], dry_run=False)
    cfg2 = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert cfg2.count('[plugins."neuron-guard@claude-cowork"]') == 1, cfg2


@pytest.mark.parametrize("who", ["gm", "standalone"])
def test_a_hook_entry_pointing_at_a_dead_interpreter_gets_rewritten(monkeypatch, tmp_path, who):
    """Il terzo caso di "gia' presente = non toccare" (dopo `claude mcp add` e il
    mirror del registro).

    Quando l'install e' passato alla radice GME il venv ha cambiato posto, ma il
    comando registrato in settings.json continuava a puntare al vecchio
    interprete. Entrambi i deployer vedevano "c'e' gia'" e non aggiornavano
    nulla: l'handshake era morto e nessun reinstall lo resuscitava. Verificato
    su installazione reale."""
    import json
    from gray_matter import executor

    home = _fake_home(monkeypatch, tmp_path)
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    settings = home / ".claude" / "settings.json"
    dead_py = str(tmp_path / "vecchio" / "venv" / "python.exe")   # non esiste
    hook = home / ".claude" / "hooks" / "neuron_sessionstart_hook.py"
    settings.write_text(json.dumps({"hooks": {"SessionStart": [
        {"matchers": ["startup"], "hooks": [
            {"type": "command", "command": f'"{dead_py}" "{hook}"'}]}]}}),
        encoding="utf-8")

    if who == "gm":
        executor._deploy_claude_code(
            ASSET_DIRS["neuron"] / "claude-code-hook" / "neuron_sessionstart_hook.py",
            dry_run=False)
    else:
        _deployer().deploy_claude_code(ASSET_DIRS["neuron"], dry_run=False)

    body = json.loads(settings.read_text(encoding="utf-8-sig"))
    cmds = [h.get("command", "") for e in body["hooks"]["SessionStart"]
            for h in (e.get("hooks") or [])]
    ours = [c for c in cmds if "neuron_sessionstart_hook" in c]
    assert len(ours) == 1, f"riscrittura duplicata: {ours}"
    assert dead_py not in ours[0], f"l'interprete morto e' rimasto: {ours[0]}"


def test_a_working_entry_is_left_alone(monkeypatch, tmp_path):
    """L'altro verso: una entry che gira non si tocca, o due deployer si
    riscriverebbero a vicenda a ogni installazione."""
    import json
    from gray_matter import executor

    home = _fake_home(monkeypatch, tmp_path)
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    settings = home / ".claude" / "settings.json"
    hook = home / ".claude" / "hooks" / "neuron_sessionstart_hook.py"
    good = f'"{sys.executable}" "{hook}"'          # interprete che esiste davvero
    settings.write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": good}]}]}}),
        encoding="utf-8")

    executor._deploy_claude_code(
        ASSET_DIRS["neuron"] / "claude-code-hook" / "neuron_sessionstart_hook.py",
        dry_run=False)
    _deployer().deploy_claude_code(ASSET_DIRS["neuron"], dry_run=False)

    body = json.loads(settings.read_text(encoding="utf-8-sig"))
    cmds = [h.get("command", "") for e in body["hooks"]["SessionStart"]
            for h in (e.get("hooks") or [])]
    assert [c for c in cmds if "neuron_sessionstart_hook" in c] == [good]


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
