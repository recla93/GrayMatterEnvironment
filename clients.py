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

# Windows: nascondi la console dei child (claude CLI) — la GUI gira via pythonw,
# quindi register/deregister facevano lampeggiare un CMD. Guardia Windows-only
# (CREATE_NO_WINDOW non esiste altrove).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

__all__ = ["SERVERS", "CLIENTS", "register", "deregister", "doctor",
           "unmanaged_tools", "set_unmanaged", "release_tool",
           "standalone_register_tool"]


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

# Gateway flip (§1 proxy model): clients talk ONLY to GM; these slugs get
# evicted from client configs (GM spawns them itself as managed workers).
# "neuron5" is the slug real installs use, "neuron" the generic one.
GATEWAY_EVICT = ("neuron", "neuron5", "neurag")


def _claude_desktop_paths() -> list[str]:
    if sys.platform == "darwin":
        return [_home("Library", "Application Support", "Claude", "claude_desktop_config.json")]
    if _env("APPDATA"):
        out = [os.path.join(_env("APPDATA"), "Claude", "claude_desktop_config.json")]
        # MSIX install reads its LocalCache redirect, NOT %APPDATA% — cover both.
        if _env("LOCALAPPDATA"):
            import glob
            out += glob.glob(os.path.join(_env("LOCALAPPDATA"), "Packages", "Claude_*",
                                          "LocalCache", "Roaming", "Claude",
                                          "claude_desktop_config.json"))
        return out
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


def _register_json(spec: dict, path: str, servers: list[str], py: str,
                   evict: tuple = ()) -> dict:
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
    for s in evict:
        node.pop(s, None)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            Path(path + ".bak").write_text(raw, encoding="utf-8")   # backup first
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"client": spec["label"], "ok": False, "action": "error", "detail": str(exc)}
    return {"client": spec["label"], "ok": True, "action": "registered", "detail": path}


def _claude_argv(*args) -> "list[str] | None":
    """Argv per la CLI `claude`, funzionante ANCHE su Windows.

    Root-cause del "register Claude Code fallisce sempre" (2026-07-21): su
    Windows `claude` è uno shim `.cmd` (npm) — CreateProcess non esegue i .cmd,
    quindi Popen(["claude", …]) alza FileNotFoundError anche se `which` lo
    trova. Fix: path risolto da shutil.which + wrapper `cmd /c` per .cmd/.bat."""
    exe = shutil.which("claude")
    if not exe:
        return None
    argv = [exe, *args]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", *argv]
    return argv


def _register_claude_cli(spec: dict, servers: list[str], py: str,
                         evict: tuple = ()) -> dict:
    ok, errors = True, []
    for s in servers:
        argv = _claude_argv("mcp", "add", "--scope", "user", s, py, "--", *SERVERS[s])
        if argv is None:
            return {"client": spec["label"], "ok": False, "action": "skipped",
                    "detail": "claude CLI not on PATH"}
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                               creationflags=_NO_WINDOW)
            if r.returncode != 0:
                # l'errore VERO nel report, non un muto "cli failed"
                tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["?"])[-1]
                # "already exists in user config" = già registrato: è il caso
                # IDEMPOTENTE (re-run dell'installer), non un errore. Segnalarlo
                # rosso faceva sembrare fallito ogni reinstall.
                if "already exists" in tail.lower():
                    continue
                ok = False
                errors.append(f"{s}: {tail[:120]}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            errors.append(f"{s}: {exc}")
    for s in evict:
        argv = _claude_argv("mcp", "remove", "--scope", "user", s)
        if argv is None:
            break
        try:  # absent server -> nonzero exit; that's fine, we only want it gone
            subprocess.run(argv, capture_output=True, text=True, timeout=60,
                           creationflags=_NO_WINDOW)
        except Exception:  # noqa: BLE001
            pass
    out = {"client": spec["label"], "ok": ok,
           "action": "claude mcp add" if ok else "cli failed"}
    if errors:
        out["detail"] = "; ".join(errors)
    return out


def register(servers: "list[str] | None" = None, *, py: "str | None" = None,
             only: "list[str] | None" = None, gateway: bool = False) -> list[dict]:
    """Register ``servers`` (default: all installed) into detected clients.

    ``gateway=True`` flips clients to the proxy model: register ONLY
    gray-matter and evict neuron/neurag entries (GM spawns them itself).

    Returns one result dict per client. Never raises — a failing client is
    reported, the others still get done.
    """
    evict: tuple = GATEWAY_EVICT if gateway else ()
    servers = ["gray-matter"] if gateway else (servers or installed_servers())
    servers = [s for s in servers if s in SERVERS]
    py = py or sys.executable or "python"
    results: list[dict] = []
    if not servers:
        return [{"client": "-", "ok": False, "action": "skipped",
                 "detail": "no installed servers to register"}]
    for ckey, spec in CLIENTS.items():
        if only and ckey not in only:
            continue
        paths = [p for p in spec["paths"]() if os.path.exists(p)]
        if not paths and not spec.get("create"):
            results.append({"client": spec["label"], "ok": False,
                            "action": "skipped", "detail": "client not found"})
            continue
        if spec.get("cli") and shutil.which("claude"):
            results.append(_register_claude_cli(spec, servers, py, evict))
            continue
        if not paths:
            paths = [spec["paths"]()[0]]
        # Every existing config for this client (Claude Desktop MSIX keeps a
        # second one in LocalCache) — updating only the newest leaves the other
        # stale and the old servers still spawning.
        for path in paths:
            results.append(_register_json(spec, path, servers, py, evict))
    return results


def deregister(servers: "list[str] | None" = None) -> list[dict]:
    """Remove ``servers`` (default: whole trio incl. legacy slugs) from every
    existing client config. Backup `.bak` before each write; JSONC/unreadable
    configs are reported, never clobbered. Claude Code goes via its CLI."""
    targets = tuple(servers) if servers else ("gray-matter", *GATEWAY_EVICT)
    results: list[dict] = []
    for ckey, spec in CLIENTS.items():
        paths_ = [p for p in spec["paths"]() if os.path.exists(p)]
        if not paths_:
            continue
        if spec.get("cli") and shutil.which("claude"):
            for s in targets:
                try:
                    subprocess.run(["claude", "mcp", "remove", "--scope", "user", s],
                                   capture_output=True, text=True, timeout=60,
                                   creationflags=_NO_WINDOW)
                except Exception:  # noqa: BLE001
                    pass
            results.append({"client": spec["label"], "ok": True, "action": "claude mcp remove"})
            continue
        for path in paths_:
            try:
                raw = Path(path).read_text(encoding="utf-8")
                data = json.loads(raw) if raw.strip() else {}
            except (json.JSONDecodeError, OSError):
                results.append({"client": spec["label"], "ok": False,
                                "action": "manual", "detail": path})
                continue
            node = data
            for k in spec["keys"]:
                node = node.get(k) if isinstance(node, dict) else None
                if node is None:
                    break
            removed = []
            if isinstance(node, dict):
                for s in targets:
                    if s in node:
                        node.pop(s)
                        removed.append(s)
            if removed:
                try:
                    Path(path + ".bak").write_text(raw, encoding="utf-8")
                    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
                except OSError as exc:
                    results.append({"client": spec["label"], "ok": False,
                                    "action": "error", "detail": str(exc)})
                    continue
            results.append({"client": spec["label"], "ok": True,
                            "action": "deregistered", "removed": removed, "detail": path})
    return results


# ---------------------------------------------------------------------------
# Deregister per-tool (go-standalone) — 2026-07-22
# ---------------------------------------------------------------------------
# Semantica: un tool "unmanaged" esce dal gateway (GM non lo spawna più come
# worker e non ne ripubblica i tool) e vive come MCP diretto nei client, con la
# SUA registrazione (`<tool>.clients`). Persistito in settings ("unmanaged"),
# reversibile con `gray-matter register --gateway` (che azzera la lista).
# Caso misto sicuro: l'entry `gray-matter` resta nei client finché ALMENO un
# peer è ancora gestito da GM; sparisce solo quando nessuno lo è (decisione
# utente 2026-07-22, §6 handoff).

_STANDALONE_TOOLS = ("neuron", "neurag")


def unmanaged_tools() -> set:
    """I tool usciti dal gateway (da settings, csv)."""
    from gray_matter import settings
    raw = str(settings.get("unmanaged") or "")
    return {t.strip() for t in raw.split(",") if t.strip() in _STANDALONE_TOOLS}


def set_unmanaged(name: str, flag: bool) -> set:
    """Aggiunge/toglie un tool dalla lista unmanaged (persistita)."""
    from gray_matter import settings
    cur = unmanaged_tools()
    (cur.add if flag else cur.discard)(name)
    settings.set("unmanaged", ",".join(sorted(cur)))
    return cur


def clear_unmanaged() -> None:
    from gray_matter import settings
    settings.set("unmanaged", "")


def standalone_register_tool(name: str, dry_run: bool = False) -> list[str]:
    """Fa registrare il tool DA SOLO nei client, con il SUO engine
    (`neuron.clients` / `neurag.clients`) — GM non ridefinisce nulla, delega."""
    lines: list[str] = []
    try:
        if name == "neuron":
            from neuron import clients as _nc
            slug = os.environ.get("NEURON_SLUG", "neuron5")
            py = _nc.default_server_python(slug)
            results = _nc.register_all(slug, py, dry_run=dry_run)
        elif name == "neurag":
            from neurag import clients as _rc
            results = _rc.register_all(dry_run=dry_run)
        else:
            return [f"[!!] tool sconosciuto: {name}"]
    except ImportError:
        return [f"[!!] {name} non installato: impossibile registrarlo standalone"]
    return [r.line().strip() for r in results]


def release_tool(name: str) -> list[str]:
    """GM smette di gestire `name`: persist (settings), IPC al daemon vivo
    (best-effort) e — SOLO se nessun peer resta gestito — rimozione dell'entry
    `gray-matter` dai client. Ritorna righe di report."""
    if name not in _STANDALONE_TOOLS:
        return [f"[!!] tool sconosciuto: {name}"]
    lines = []
    un = set_unmanaged(name, True)
    lines.append(f"[OK] GM non gestisce più '{name}' (persistito)")
    try:  # daemon vivo: molla il worker subito, senza aspettare un restart
        from gray_matter.cli import _send_ipc
        r = _send_ipc({"action": "unregister", "name": name})
        lines.append("[OK] daemon avvisato (worker rilasciato)" if "error" not in r
                     else f"[--] daemon non in esecuzione ({r['error']}) — vale dal prossimo avvio")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"[--] IPC non riuscito ({exc}) — vale dal prossimo avvio")
    still_managed = [t for t in installed_servers()
                     if t in _STANDALONE_TOOLS and t not in un]
    if still_managed:
        lines.append(f"[OK] entry 'gray-matter' TENUTA nei client: gestisce ancora "
                     + ", ".join(still_managed))
    else:
        lines.append("[OK] nessun peer resta dietro GM: tolgo 'gray-matter' dai client")
        for r in deregister(["gray-matter"]):
            mark = "OK" if r.get("ok") else "!!"
            lines.append(f"  [{mark}] {r['client']}: {r['action']}")
    return lines


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
