"""Cross-platform MCP client registration for the trio — owned by Gray-Matter.

GM is the ecosystem hub, so it can register any *installed* server (Neuron,
NeuRAG, Gray-Matter) into the user's MCP clients. This is deliberately
standalone: it does NOT import ``neuron.clients`` (Neuron may not be installed
in the GM-hub model), but it mirrors that engine's client paths and JSON shapes.

Scope (lazy but functional): JSON clients + Claude Code via its official CLI.
A config that can't be parsed as plain JSON (VS Code settings are often JSONC)
is reported with a manual snippet rather than being clobbered — never overwrite
a whole config we don't understand.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

__all__ = ["SERVERS", "CLIENTS", "register", "doctor"]


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


def _env(key: str) -> str:
    return os.environ.get(key, "")


# Server slug -> the args that follow the python executable to launch its MCP
# stdio server. Verified against each project's __main__/console script.
SERVERS: dict[str, list[str]] = {
    "neuron": ["-m", "neuron"],
    "neurag": ["-m", "neurag.server"],
    "gray-matter": ["-m", "gray_matter.server"],
}

# Module used to detect whether a server is installed (importable).
_DETECT = {"neuron": "neuron", "neurag": "neurag", "gray-matter": "gray_matter"}


def _claude_desktop_paths() -> list[str]:
    if sys.platform == "darwin":
        return [_home("Library", "Application Support", "Claude", "claude_desktop_config.json")]
    if _env("APPDATA"):
        return [os.path.join(_env("APPDATA"), "Claude", "claude_desktop_config.json")]
    return [_home(".config", "Claude", "claude_desktop_config.json")]


def _vscode_paths() -> list[str]:
    if _env("APPDATA"):
        return [os.path.join(_env("APPDATA"), "Code", "User", "settings.json")]
    if sys.platform == "darwin":
        return [_home("Library", "Application Support", "Code", "User", "settings.json")]
    return [_home(".config", "Code", "User", "settings.json")]


def _zed_paths() -> list[str]:
    if _env("APPDATA"):
        return [os.path.join(_env("APPDATA"), "Zed", "settings.json")]
    return [_home(".config", "zed", "settings.json")]


# client -> spec. style decides the entry shape; keys is the nested path to the
# server map; create=True means we may create the file if absent.
CLIENTS: dict[str, dict] = {
    "claude-desktop": {"label": "Claude Desktop", "paths": _claude_desktop_paths,
                       "keys": ["mcpServers"], "style": "args", "create": False},
    "claude-code": {"label": "Claude Code", "paths": lambda: [_home(".claude.json")],
                    "keys": ["mcpServers"], "style": "args", "create": False, "cli": True},
    "cursor": {"label": "Cursor", "paths": lambda: [_home(".cursor", "mcp.json")],
               "keys": ["mcpServers"], "style": "args", "create": True},
    "vscode": {"label": "VS Code", "paths": _vscode_paths,
               "keys": ["mcp", "servers"], "style": "stdio", "create": False},
    "zed": {"label": "Zed", "paths": _zed_paths,
            "keys": ["context_servers"], "style": "args", "create": False},
    "opencode": {"label": "OpenCode", "paths": lambda: [_home(".config", "opencode", "opencode.json")],
                 "keys": ["mcp"], "style": "local", "create": True},
}


def installed_servers() -> list[str]:
    """Server slugs whose package is importable right now."""
    import importlib.util
    out = []
    for slug, module in _DETECT.items():
        try:
            if importlib.util.find_spec(module) is not None:
                out.append(slug)
        except Exception:  # noqa: BLE001 — a broken/partial install
            pass
    return out


def _entry(style: str, py: str, args: list[str]) -> dict:
    if style == "stdio":
        return {"type": "stdio", "command": py, "args": args}
    if style == "local":
        return {"command": [py, *args], "type": "local"}
    return {"command": py, "args": args}


def _pick(paths: list[str]) -> "str | None":
    existing = [p for p in paths if os.path.exists(p)]
    return max(existing, key=os.path.getmtime) if existing else None


def _register_json(spec: dict, path: str, servers: list[str], py: str) -> dict:
    try:
        raw = Path(path).read_text(encoding="utf-8") if os.path.exists(path) else ""
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        # Likely JSONC or unreadable — hand the user a snippet, don't clobber.
        snippet = {s: _entry(spec["style"], py, SERVERS[s]) for s in servers}
        return {"client": spec["label"], "ok": False, "action": "manual",
                "detail": path, "snippet": json.dumps(snippet, indent=2)}
    node = data
    for k in spec["keys"]:
        node = node.setdefault(k, {})
        if not isinstance(node, dict):
            return {"client": spec["label"], "ok": False, "action": "error",
                    "detail": f"unexpected shape at '{k}'"}
    for s in servers:
        node[s] = _entry(spec["style"], py, SERVERS[s])
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            Path(path + ".bak").write_text(raw, encoding="utf-8")   # backup first
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"client": spec["label"], "ok": False, "action": "error", "detail": str(exc)}
    return {"client": spec["label"], "ok": True, "action": "registered", "detail": path}


def _register_claude_cli(spec: dict, servers: list[str], py: str) -> dict:
    ok = True
    for s in servers:
        try:
            r = subprocess.run(
                ["claude", "mcp", "add", "--scope", "user", s, py, "--", *SERVERS[s]],
                capture_output=True, text=True, timeout=60)
            ok = ok and r.returncode == 0
        except Exception:  # noqa: BLE001
            ok = False
    return {"client": spec["label"], "ok": ok,
            "action": "claude mcp add" if ok else "cli failed"}


def register(servers: "list[str] | None" = None, *, py: "str | None" = None,
             only: "list[str] | None" = None) -> list[dict]:
    """Register ``servers`` (default: all installed) into detected clients.

    Returns one result dict per client. Never raises — a failing client is
    reported, the others still get done.
    """
    servers = servers or installed_servers()
    servers = [s for s in servers if s in SERVERS]
    py = py or sys.executable or "python"
    results: list[dict] = []
    if not servers:
        return [{"client": "-", "ok": False, "action": "skipped",
                 "detail": "no installed servers to register"}]
    for ckey, spec in CLIENTS.items():
        if only and ckey not in only:
            continue
        path = _pick(spec["paths"]())
        if path is None and not spec.get("create"):
            results.append({"client": spec["label"], "ok": False,
                            "action": "skipped", "detail": "client not found"})
            continue
        if spec.get("cli") and shutil.which("claude"):
            results.append(_register_claude_cli(spec, servers, py))
            continue
        if path is None:
            path = spec["paths"]()[0]
        results.append(_register_json(spec, path, servers, py))
    return results


def doctor(py: "str | None" = None) -> list[dict]:
    """Read-only: which servers each detected client currently lists."""
    out = []
    for ckey, spec in CLIENTS.items():
        path = _pick(spec["paths"]())
        if path is None:
            continue
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8") or "{}")
            node = data
            for k in spec["keys"]:
                node = node.get(k, {}) if isinstance(node, dict) else {}
            present = [s for s in SERVERS if isinstance(node, dict) and s in node]
        except (json.JSONDecodeError, OSError):
            present = []
        out.append({"client": spec["label"], "path": path, "servers": present})
    return out
