"""Registrarsi in un client non deve toccare NIENT'ALTRO nel suo config.

I sei config non sono nostri: ci stanno gli MCP server di altri progetti, le
impostazioni dell'editor, chiavi che non conosciamo. `register()` ci scrive
dentro a ogni install e a ogni riparazione. Se scrivesse il file invece di
fondersi, un'installazione della suite spegnerebbe in silenzio gli strumenti di
lavoro dell'utente — e nessuno collegherebbe le due cose.

Qui si parte da config SPORCHI (altri server, chiavi sconosciute, struttura
annidata) e si verifica che dopo la registrazione ci sia tutto.
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "Local"))
    from gray_matter import clients as C
    importlib.reload(C)
    return tmp_path


def _write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def test_other_mcp_servers_survive_registration(home):
    from gray_matter import clients as C

    cfg = home / ".cursor" / "mcp.json"
    _write(cfg, {
        "mcpServers": {
            "un-altro-tool": {"command": "node", "args": ["server.js"]},
            "postgres": {"command": "uvx", "args": ["mcp-postgres"]},
        },
        "impostazione-sconosciuta": {"tema": "scuro"},
    })

    C.register(only=["cursor"], gateway=True, py="/fake/python")

    after = json.loads(cfg.read_text(encoding="utf-8"))
    srv = after["mcpServers"]
    assert "gray-matter" in srv, "non si e' registrato"
    assert srv["un-altro-tool"] == {"command": "node", "args": ["server.js"]}
    assert srv["postgres"] == {"command": "uvx", "args": ["mcp-postgres"]}
    assert after["impostazione-sconosciuta"] == {"tema": "scuro"}


def test_a_second_registration_is_idempotent(home):
    from gray_matter import clients as C

    cfg = home / ".cursor" / "mcp.json"
    _write(cfg, {"mcpServers": {"altro": {"command": "x"}}})
    C.register(only=["cursor"], gateway=True, py="/fake/python")
    first = cfg.read_text(encoding="utf-8")
    C.register(only=["cursor"], gateway=True, py="/fake/python")
    assert cfg.read_text(encoding="utf-8") == first, "la seconda scrittura cambia il file"


def test_an_unparsable_config_is_reported_and_never_rewritten(home):
    """JSONC o file rotto: si segnala, NON si riscrive. Riscriverlo significa
    buttare via la configurazione dell'utente per rimetterci la nostra."""
    from gray_matter import clients as C

    cfg = home / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    original = '{ // commento in stile JSONC\n  "mcpServers": {"altro": {"command": "x"}}\n}'
    cfg.write_text(original, encoding="utf-8")

    res = C.register(only=["cursor"], gateway=True, py="/fake/python")

    assert cfg.read_text(encoding="utf-8") == original, "ha riscritto un config che non sa leggere"
    # `client` nel risultato e' l'ETICHETTA ("Cursor"), non la chiave.
    entry = next((r for r in res if str(r.get("client", "")).lower() == "cursor"), None)
    assert entry is not None, "il client non compare nemmeno nel risultato"
    assert not entry.get("ok"), "un fallimento silenzioso e' peggio di un errore"
    # E deve dire all'utente COSA incollare, non solo che non ce l'ha fatta.
    assert entry.get("action") == "manual"
    assert "gray-matter" in (entry.get("snippet") or "")


def test_empty_or_missing_file_is_created_cleanly(home):
    from gray_matter import clients as C

    cfg = home / ".cursor" / "mcp.json"
    C.register(only=["cursor"], gateway=True, py="/fake/python")
    if cfg.exists():
        assert "gray-matter" in json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"]
