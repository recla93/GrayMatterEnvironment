"""Where MCP servers get written, and who decides.

Two real defects are pinned here:

* **VS Code**: 1.102 moved MCP servers into `User/mcp.json`. All three tools
  targeted `User/settings.json` only, so entries went where a current VS Code
  never looks — and `deregister` could not SEE a server that lived in mcp.json.
  Observed 2026-07-29: a legacy `neuron5` in mcp.json survived
  `deregister_all('neuron5')`, which cheerfully reported "not registered".

* **Choice**: registration was all-or-one. The user must be able to say WHICH
  clients get touched, and a prompt nobody can answer must fall back to a safe
  default rather than registering nothing.
"""

import importlib

import pytest

TOOLS = ["neuron.clients", "neurag.clients", "gray_matter.clients"]


def _mod(name):
    return pytest.importorskip(name)


# --- VS Code: both files, right nesting for each -----------------------------

@pytest.mark.parametrize("name", TOOLS)
def test_vscode_looks_at_mcp_json_first(name):
    m = _mod(name)
    paths = m._vscode_paths() if hasattr(m, "_vscode_paths") else m.vscode_candidates()
    bases = [p.replace("\\", "/").rsplit("/", 1)[-1].lower() for p in paths]
    assert bases[0] == "mcp.json", f"{name}: mcp.json must be probed first, got {bases}"
    assert "settings.json" in bases, f"{name}: settings.json must remain a candidate"


@pytest.mark.parametrize("name", TOOLS)
def test_server_map_nesting_depends_on_the_file(name):
    """mcp.json holds servers at the root; settings.json nests them under 'mcp'.
    Using one nesting for both writes a structurally invalid config."""
    m = _mod(name)
    fn = getattr(m, "_vscode_keys_for", None) or getattr(m, "vscode_keys_for")
    assert fn("/x/User/mcp.json") == ["servers"]
    assert fn("/x/User/settings.json") == ["mcp", "servers"]


# --- Client choice -----------------------------------------------------------

SELECTORS = ["neuron.clients", "neurag.clients"]


@pytest.mark.parametrize("name", SELECTORS)
def test_selector_forms(name):
    m = _mod(name)
    assert m.resolve_clients("all") == list(m.CLIENTS)
    assert m.resolve_clients("detected") == m.detected_clients()
    picked = m.resolve_clients(next(iter(m.CLIENTS)))
    assert picked == [next(iter(m.CLIENTS))]


@pytest.mark.parametrize("name", SELECTORS)
def test_a_typo_is_loud_not_silent(name):
    """A mistyped client must fail, never quietly register into nothing."""
    m = _mod(name)
    with pytest.raises(ValueError):
        m.resolve_clients("cursr")


@pytest.mark.parametrize("name", SELECTORS)
def test_ask_without_a_console_falls_back_to_detected(name, monkeypatch):
    """An installer must not no-op because a prompt could not be read."""
    m = _mod(name)
    monkeypatch.setattr(m.sys, "stdin", None)
    assert m.resolve_clients("ask") == m.detected_clients()


@pytest.mark.parametrize("name", SELECTORS)
def test_detected_is_a_subset_of_known_clients(name):
    m = _mod(name)
    assert set(m.detected_clients()) <= set(m.CLIENTS)


# --- The matrices stay as their owners decided -------------------------------

CANONICAL = {"claude-desktop", "claude-code", "cursor", "vscode",
             "opencode", "windsurf", "codex", "zed"}


def test_all_three_tools_offer_the_same_clients():
    """One matrix, everywhere. Picking NeuRAG must not silently give you fewer
    targets than picking Neuron — NeuRAG shipped 5 and Gray Matter, the GATEWAY,
    could not reach Codex at all (in gateway mode GM is the only server
    registered, so that client got nothing). Superseded 2026-07-29.

    `vscode` covers GitHub Copilot: Copilot reads VS Code's own User/mcp.json."""
    sets = {name: set(_mod(name).CLIENTS) for name in TOOLS}
    for name, got in sets.items():
        assert got == CANONICAL, (
            f"{name} offers {sorted(got)} — expected {sorted(CANONICAL)}; "
            f"missing: {sorted(CANONICAL - got)}  extra: {sorted(got - CANONICAL)}")


@pytest.mark.parametrize("name", TOOLS)
def test_codex_is_written_as_toml_not_json(name):
    """Codex's config.toml is not JSON. A tool that lists codex but writes JSON
    into it corrupts the file — worse than not supporting it."""
    m = _mod(name)
    spec = m.CLIENTS["codex"]
    assert spec.get("format") == "toml", f"{name}: codex must be written as TOML"


# --- The safety guard must sit on the function that WRITES -------------------

@pytest.mark.parametrize("name", SELECTORS)
def test_no_write_guard_covers_the_picker_path(name, monkeypatch, tmp_path):
    """GM_NO_CLIENT_REGISTER must hold on the path the installer actually takes.

    It was first put on register_all(); then the client picker replaced that
    call with a per-client register() loop and drove straight past it, so a
    "dry" test install rewrote six live configs anyway — twice. The guard
    belongs on register(), the single function that writes.
    """
    m = _mod(name)
    monkeypatch.setenv("GM_NO_CLIENT_REGISTER", "1")
    for client in m.resolve_clients("all"):
        r = m.register(client, "guard-probe", str(tmp_path / "python.exe"))
        assert "dry-run" in r.action or r.action == "skipped", (
            f"{name}.register({client!r}) wrote despite GM_NO_CLIENT_REGISTER: {r.action}")


@pytest.mark.parametrize("name", SELECTORS)
def test_the_guard_is_declared_on_register_itself(name):
    """Structural: a guard only on a wrapper is one refactor from useless."""
    import inspect
    m = _mod(name)
    assert "GM_NO_CLIENT_REGISTER" in inspect.getsource(m.register), (
        f"{name}: the guard must live on register(), not only on a caller")
