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
import re
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
# "neuron" is the slug installs use; "neuron5" is the retired v5 identity, kept
# here so a config written by an older install still gets evicted.
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


def _vscode_user_dir() -> str:
    if _env("APPDATA"):
        return os.path.join(_env("APPDATA"), "Code", "User")
    if sys.platform == "darwin":
        return _home("Library", "Application Support", "Code", "User")
    return _home(".config", "Code", "User")


def _vscode_paths() -> list[str]:
    """`mcp.json` FIRST, then `settings.json`.

    VS Code 1.102 moved MCP servers into a dedicated `User/mcp.json`. Targeting
    only settings.json wrote the gateway entry where a current VS Code never
    looks, and deregister could not SEE a server living in mcp.json — so an
    uninstall left it behind. Keep-in-sync with neuron/ and neurag/clients.py.
    """
    d = _vscode_user_dir()
    return [os.path.join(d, "mcp.json"), os.path.join(d, "settings.json")]


def _vscode_keys_for(path: str) -> list[str]:
    """mcp.json IS the MCP file → servers sit at the root."""
    return ["servers"] if os.path.basename(path).lower() == "mcp.json" else ["mcp", "servers"]


def keys_for(spec: dict, path: str) -> list[str]:
    """Nested path to the server map for THIS file (see _vscode_paths)."""
    fn = spec.get("keys_for")
    return fn(path) if fn else spec["keys"]


def _windsurf_paths() -> list[str]:
    """Windsurf (Cognition). Primary is Codeium's own MCP file; the second is
    the VS Code-fork layout (Windsurf is a VS Code fork). Not verifiable here —
    which is why both are probed and nothing is ever created: a wrong guess
    costs a "skipped", never a config written to the wrong place."""
    cands = [_home(".codeium", "windsurf", "mcp_config.json")]
    if _env("APPDATA"):
        cands.append(os.path.join(_env("APPDATA"), "Windsurf", "User", "mcp.json"))
    elif sys.platform == "darwin":
        cands.append(_home("Library", "Application Support", "Windsurf", "User", "mcp.json"))
    else:
        cands.append(_home(".config", "Windsurf", "User", "mcp.json"))
    return cands


def _toml_upsert_section(text: str, section: str, body_lines: list[str]) -> str:
    """Replace the ``[section]`` block if present, else append it; everything
    else stays byte-for-byte. Keep-in-sync with neuron/clients.py."""
    new_block = f"[{section}]\n" + "\n".join(body_lines) + "\n"
    pattern = re.compile(r"(?ms)^\[" + re.escape(section) + r"\]\s*?\n.*?(?=^\[|\Z)")
    if pattern.search(text):
        # lambda: the block holds Windows backslashes re.sub would eat.
        return pattern.sub(lambda _m: new_block, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text.strip() else "") + new_block


def _register_toml(spec: dict, path: str, servers: list[str], py: str,
                   evict: tuple = ()) -> dict:
    """Codex CLI. Section-targeted upsert + removal of evicted slugs, so the
    rest of config.toml (other MCP servers, user settings) is never touched."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig") if os.path.exists(path) else ""
    except OSError:
        return {"client": spec["label"], "ok": False, "action": "manual", "detail": path}
    root = spec["keys"][0]
    for s_ in servers:
        text = _toml_upsert_section(
            text, f"{root}.{s_}",
            ["command = " + json.dumps(py), "args = " + json.dumps(SERVERS[s_])])
    for s_ in evict:
        text = re.sub(r"(?ms)^\[" + re.escape(f"{root}.{s_}") + r"\]\s*?\r?\n.*?(?=^\[|\Z)",
                      "", text)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            Path(path + ".bak").write_text(
                Path(path).read_text(encoding="utf-8-sig"), encoding="utf-8")
        Path(path).write_text(text, encoding="utf-8")
    except OSError as e:
        return {"client": spec["label"], "ok": False, "action": "error", "detail": str(e)}
    after = Path(path).read_text(encoding="utf-8-sig")
    if any(f"[{root}.{s_}]" not in after for s_ in servers):
        return {"client": spec["label"], "ok": False, "action": "error",
                "detail": "write verification failed"}
    return {"client": spec["label"], "ok": True, "action": "registered", "detail": path}


def _zed_paths() -> list[str]:
    if _env("APPDATA"):
        return [os.path.join(_env("APPDATA"), "Zed", "settings.json")]
    return [_home(".config", "zed", "settings.json")]


# client -> spec. style decides the entry shape; keys is the nested path to the
# server map; create=True means we may create the file if absent.
CLIENTS: dict[str, dict] = {
    "claude-desktop": {"label": "Claude Desktop", "paths": _claude_desktop_paths,
                       "keys": ["mcpServers"], "style": "args", "create_if_missing": False},
    "claude-code": {"label": "Claude Code", "paths": lambda: [_home(".claude.json")],
                    "keys": ["mcpServers"], "style": "args", "create_if_missing": False, "cli": True},
    "cursor": {"label": "Cursor", "paths": lambda: [_home(".cursor", "mcp.json")],
               "keys": ["mcpServers"], "style": "args", "create_if_missing": False},
    "vscode": {"label": "VS Code", "paths": _vscode_paths,
               "keys": ["mcp", "servers"], "keys_for": _vscode_keys_for,
               "style": "stdio", "create_if_missing": False},
    "zed": {"label": "Zed", "paths": _zed_paths,
            "keys": ["context_servers"], "style": "args", "create_if_missing": False},
    "opencode": {"label": "OpenCode", "paths": lambda: [_home(".config", "opencode", "opencode.json")],
                 "keys": ["mcp"], "style": "local", "create_if_missing": False},
    "windsurf": {"label": "Windsurf", "paths": _windsurf_paths,
                 "keys": ["mcpServers"], "style": "args", "create_if_missing": False},
    "codex": {"label": "Codex CLI", "paths": lambda: [_home(".codex", "config.toml")],
              "keys": ["mcp_servers"], "style": "args", "format": "toml",
              "create_if_missing": False},
    # ChatGPT non gira su questa macchina: non ha un file da scrivere, ci arriva
    # via HTTP pubblico. "Registrarlo" significa accendere il bridge ed esporlo
    # con un tunnel — `remote: True` e' quello che dice a register() di non
    # cercargli un config e di non contarlo come "client non trovato".
    "chatgpt": {"label": "ChatGPT", "paths": lambda: [], "keys": [],
                "style": "remote", "remote": True, "create_if_missing": False},
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
        raw = Path(path).read_text(encoding="utf-8-sig") if os.path.exists(path) else ""
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        # Likely JSONC or unreadable — hand the user a snippet, don't clobber.
        snippet = {s: _entry(spec["style"], py, SERVERS[s]) for s in servers}
        return {"client": spec["label"], "ok": False, "action": "manual",
                "detail": path, "snippet": json.dumps(snippet, indent=2)}
    if not isinstance(data, dict):
        # JSON valido ma root non-oggetto (stringa/lista/numero): setdefault()
        # esploderebbe su 'str'/'list' invece di segnalare. Il loop sotto gestisce
        # i livelli annidati non-dict; il root serve questo check qui.
        return {"client": spec["label"], "ok": False, "action": "error",
                "detail": f"config root is not a JSON object: {path}"}
    node = data
    for k in keys_for(spec, path):
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
        existed = os.path.exists(path)
        if existed:
            Path(path + ".bak").write_text(raw, encoding="utf-8")   # backup first
        # ensure_ascii=False: paths with accented characters must stay readable,
        # not escape into \uXXXX sequences a client may refuse to resolve.
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        return {"client": spec["label"], "ok": False, "action": "error", "detail": str(exc)}
    # Verify-after-write + rollback: a truncated write must not leave the
    # client's config unreadable (same pattern as neuron/neurag clients).
    try:
        reread = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        reread = None
    node = reread if isinstance(reread, dict) else None
    for k in keys_for(spec, path):
        node = node.get(k) if isinstance(node, dict) else None
    # The eviction is half of the gateway flip: a config that kept the old peer
    # entries alongside gray-matter is as wrong as one missing gray-matter.
    if not (isinstance(node, dict) and all(s in node for s in servers)
            and not any(s in node for s in evict)):
        if existed and os.path.exists(path + ".bak"):
            shutil.copyfile(path + ".bak", path)
        elif not existed:
            # No .bak to restore from - the file is ours, and a half-written
            # config is worse than the absent one the client already handles.
            try:
                os.remove(path)
            except OSError:
                pass
        return {"client": spec["label"], "ok": False, "action": "error",
                "detail": "write verification failed - rolled back: " + path}
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
                # "already exists in user config": `claude mcp add` non aggiorna,
                # rifiuta. Trattarlo come successo idempotente lasciava in piedi
                # la entry VECCHIA — ed e' cosi' che, spostando il venv, Claude
                # Code e' rimasto l'unico client puntato a un interprete che non
                # esiste piu' (`spawn ... python.exe ENOENT`) mentre gli altri
                # cinque erano stati riscritti. Non si puo' sapere se la entry
                # esistente e' identica o stantia: si rimuove e si riscrive, cosi'
                # dopo la registrazione il valore e' quello corrente, punto.
                if "already exists" in tail.lower():
                    rm = _claude_argv("mcp", "remove", "--scope", "user", s)
                    if rm is not None:
                        subprocess.run(rm, capture_output=True, text=True,
                                       timeout=60, creationflags=_NO_WINDOW)
                        r = subprocess.run(argv, capture_output=True, text=True,
                                           timeout=60, creationflags=_NO_WINDOW)
                    if r.returncode == 0:
                        continue
                    tail = ((r.stderr or r.stdout or "").strip().splitlines() or ["?"])[-1]
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


def detected_clients() -> list[str]:
    """Clients whose config actually exists on this machine."""
    return [k for k, spec in CLIENTS.items()
            if any(os.path.exists(p) for p in spec["paths"]())]


def resolve_clients(selector: str, *, interactive: bool = True) -> "list[str] | None":
    """'all' | 'detected' | 'ask' | 'a,b,c'. None = the user aborted.

    Keep-in-sync with neuron/clients.py and neurag/clients.py. Feeds
    ``register(only=...)``, which already existed but had no CLI surface."""
    selector = (selector or "all").strip()
    if selector == "all":
        return list(CLIENTS)
    if selector == "detected":
        return detected_clients()
    if selector == "ask":
        if not interactive or not sys.stdin or not sys.stdin.isatty():
            return detected_clients()
        return _pick_clients_interactively()
    names = [n.strip() for n in selector.split(",") if n.strip()]
    unknown = [n for n in names if n not in CLIENTS]
    if unknown:
        raise ValueError(f"unknown client(s): {', '.join(unknown)} — "
                         f"known: {', '.join(sorted(CLIENTS))}")
    return names


def _pick_clients_interactively() -> "list[str] | None":
    found = set(detected_clients())
    names = list(CLIENTS)
    print("\n  Register the MCP gateway in which clients?")
    for i, name in enumerate(names, 1):
        mark = "x" if name in found else " "
        note = "" if name in found else "   (not detected)"
        print(f"    [{mark}] {i}) {CLIENTS[name]['label']}{note}")
    print("\n  Enter = the detected ones, 'all', 'none', or numbers like 1,3,4")
    try:
        raw = input("  Choice [detected]: ").strip().lower()
    except EOFError:
        # Nobody there to answer: safe default beats registering NOTHING.
        print("detected (no input available)")
        return sorted(found, key=names.index)
    except KeyboardInterrupt:
        print()
        return None
    if not raw or raw == "detected":
        return sorted(found, key=names.index)
    if raw == "all":
        return names
    if raw in ("none", "skip", "-"):
        return []
    picked = []
    for tok in raw.replace(" ", ",").split(","):
        if not tok:
            continue
        if tok.isdigit() and 1 <= int(tok) <= len(names):
            picked.append(names[int(tok) - 1])
        elif tok in CLIENTS:
            picked.append(tok)
        else:
            print(f"  (ignoring '{tok}' — not a client)")
    return list(dict.fromkeys(picked))


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
        if spec.get("remote"):
            # Client che non gira qui (ChatGPT): non ha un config da scrivere,
            # si raggiunge via bridge+tunnel. Solo se richiesto ESPLICITAMENTE —
            # accendere un tunnel pubblico non e' una cosa da fare per default
            # dentro un "registra nei client rilevati".
            if not only:
                continue
            from gray_matter import chatgpt
            results.append(chatgpt.register())
            continue
        paths = [p for p in spec["paths"]() if os.path.exists(p)]
        # One key across the three repos (I6): the peers read and write
        # `create_if_missing`, and now so do these specs. They used to say
        # `create`, which this reader never looked at — so `cursor` and
        # `opencode`, both set to True, were dead letters.
        #
        # Renaming them is NOT permission to switch them on. Every flag here is
        # False on purpose: `test_no_client_config_is_created_for_an_app_that_is
        # _not_installed` forbids inventing a config for an app that is absent,
        # because `executor.detect_state()` then counts that client as present
        # forever and keeps deploying hooks into it. GM happened to comply while
        # the key was dead; now it complies because it says so.
        if not paths and not spec.get("create_if_missing"):
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
        writer = _register_toml if spec.get("format") == "toml" else _register_json
        for path in paths:
            results.append(writer(spec, path, servers, py, evict))
    return results


def servers_for(gateway: bool) -> list[str]:
    """Which servers a registration writes. One definition, so the message the
    user reads and the entries actually written can never disagree."""
    return ["gray-matter"] if gateway else installed_servers()


def register_flow(*, gateway: bool, only: "list[str] | None",
                  py: "str | None" = None) -> list[dict]:
    """THE registration path — CLI, installer and control center all enter here.

    They used to each assemble the call themselves, and had already drifted: the
    CLI reset the unmanaged list on a gateway flip (a tool released to
    standalone comes back under GM) and the GUI did not, so the same button in
    two places left the registry in two different states. Nothing detected it,
    because both produced a plausible list of successes.

    The installer reaches this through `gray-matter register`, so aligning the
    CLI aligns all six installers with it for free.
    """
    servers = servers_for(gateway)
    if not servers:
        return [{"client": "-", "ok": False, "action": "skipped",
                 "detail": "no installed servers to register"}]
    if gateway:
        # Round-trip of go-standalone: returning to the gateway takes every tool
        # back under management and evicts the direct entries.
        clear_unmanaged()
    results = register(servers, gateway=gateway, only=only, py=py)
    _sync_manifest_clients(results)
    return results


def _sync_manifest_clients(results: list[dict]) -> None:
    """Record where gray-matter is actually registered so uninstall can undo it.

    The installer writes the manifest, but `cli register`/GUI live on
    ``register_flow`` and used to leave ``clients`` stale — an uninstall would
    then deregister only the last-installed client and orphan the rest. Union
    with what is already there: ``only`` may address a subset, dropping the
    previous entries would re-orphan them.
    """
    label_to_key = {spec["label"]: key for key, spec in CLIENTS.items()}
    ok_keys = {label_to_key[r["client"]] for r in results
               if r.get("ok") and r["client"] in label_to_key}
    if not ok_keys:
        return
    from gray_matter import paths
    m = paths.Manifest.load()
    m.set_clients(sorted(set(m.data.get("clients") or []) | set(ok_keys)))
    m.save()


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
                argv = _claude_argv("mcp", "remove", "--scope", "user", s)
                if argv is None:
                    continue
                try:
                    subprocess.run(argv, capture_output=True, text=True, timeout=60,
                                   creationflags=_NO_WINDOW)
                except Exception:  # noqa: BLE001
                    pass
            results.append({"client": spec["label"], "ok": True, "action": "claude mcp remove"})
            continue
        for path in paths_:
            try:
                raw = Path(path).read_text(encoding="utf-8-sig")
                data = json.loads(raw) if raw.strip() else {}
            except (json.JSONDecodeError, OSError):
                results.append({"client": spec["label"], "ok": False,
                                "action": "manual", "detail": path})
                continue
            node = data
            for k in keys_for(spec, path):
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
            slug = os.environ.get("NEURON_SLUG", "neuron")
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
            data = json.loads(Path(path).read_text(encoding="utf-8-sig") or "{}")
            node = data
            for k in keys_for(spec, path):
                node = node.get(k, {}) if isinstance(node, dict) else {}
            present = [s for s in SERVERS if isinstance(node, dict) and s in node]
        except (json.JSONDecodeError, OSError):
            present = []
        out.append({"client": spec["label"], "path": path, "servers": present})
    return out
