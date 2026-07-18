"""Effectful executor for the install/uninstall plans (INSTALLER-UX §5–6).

`installer.plan()` / `uninstaller.plan()` are the pure brains; this module is
the thin hands. One small function per action, a dispatch loop, and `dry_run`
everywhere (print what would happen, touch nothing). Result dicts, never
raises — a failing step is reported, the rest still runs.

MUST be exercised **locally**: it touches live processes, the client configs
and the disk. In the sandbox only static checks and tmp-dir tests are valid
(ENVIRONMENT.md rule).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sys
from pathlib import Path

from gray_matter import installer, paths, uninstaller

__all__ = ["detect_state", "execute_install", "execute_uninstall"]

# Marker used to recognise our own entries when scrubbing client configs.
_HOOK_MARKERS = ("neuron_sessionstart_hook", "neuron-handshake", "neuron-guard")


# --------------------------------------------------------------------------
# State detection (read-only)
# --------------------------------------------------------------------------

def _alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            import subprocess
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                               capture_output=True, text=True, timeout=10)
            return str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


def _tracked_pids() -> list[int]:
    try:
        data = json.loads(paths.pids_path().read_text(encoding="utf-8"))
        return [int(p) for p in (data if isinstance(data, list) else data.get("pids", []))]
    except Exception:  # noqa: BLE001
        return []


def detect_state() -> dict:
    """Build the `state` dict installer.plan() expects, from the live machine."""
    from gray_matter import clients as _clients
    slugs = _clients.installed_servers()          # neuron / neurag / gray-matter
    installed = [s.replace("-", "_") for s in slugs if s != "gray-matter"]
    detected = []
    for ckey, spec in _clients.CLIENTS.items():
        if any(os.path.exists(p) for p in spec["paths"]()):
            detected.append(ckey)
    # Cowork has no config path in CLIENTS: it rides Claude Desktop's install.
    if "claude-desktop" in detected:
        detected.append("cowork")
    orphans = [p for p in _tracked_pids() if _alive(p) and p != os.getpid()]
    return {"installed": installed,
            "gm_present": paths.app_dir().exists() or paths.manifest_path().exists(),
            "clients": detected,
            "orphan_pids": orphans}


# --------------------------------------------------------------------------
# Shared effectful primitives
# --------------------------------------------------------------------------

def _reap(pids: list[int], dry_run: bool) -> dict:
    killed, failed = [], []
    for pid in pids:
        if dry_run:
            killed.append(pid)
            continue
        try:
            if os.name == "nt":
                import subprocess
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except Exception:  # noqa: BLE001
            failed.append(pid)
    if not dry_run:
        try:
            paths.pids_path().unlink(missing_ok=True)
        except OSError:
            pass
    return {"action": "reap", "ok": not failed, "killed": killed, "failed": failed}


def _ensure_data(component: str, dry_run: bool) -> dict:
    dirs = {"neuron": paths.neuron_graphs(),
            "neurag": paths.neurag_db().parent}
    target = dirs.get(component)
    if target is None:
        return {"action": "ensure_data", "ok": True, "component": component,
                "detail": "no data dir for component"}
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    return {"action": "ensure_data", "ok": True, "component": component,
            "detail": str(target)}


def _install_gm(dry_run: bool) -> dict:
    made = [paths.app_dir(), paths.logs_dir(), paths.gm_bridges().parent]
    if not dry_run:
        for d in made:
            d.mkdir(parents=True, exist_ok=True)
        if not paths.config_file().exists():
            paths.config_file().write_text("{}\n", encoding="utf-8")
    return {"action": "install", "ok": True, "component": installer.GATEWAY,
            "detail": str(paths.gm_home())}


# --------------------------------------------------------------------------
# Hook deploy (§8b) — per-client destinations
# --------------------------------------------------------------------------

def _claude_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude"


def _opencode_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".config" / "opencode"


def _deploy_claude_code(src: Path, dry_run: bool) -> tuple[list[str], str]:
    """Copy the SessionStart hook + register it in ~/.claude/settings.json."""
    dest = _claude_dir() / "hooks" / src.name
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        settings = _claude_dir() / "settings.json"
        try:
            cfg = json.loads(settings.read_text(encoding="utf-8")) if settings.exists() else {}
        except (json.JSONDecodeError, OSError):
            return [str(dest)], "settings.json unreadable — register hook manually"
        groups = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])
        already = any("neuron_sessionstart_hook" in h.get("command", "")
                      for g in groups for h in g.get("hooks", []))
        if not already:
            groups.append({"matchers": ["startup", "resume", "clear", "compact"],
                           "hooks": [{"type": "command",
                                      "command": f'"{sys.executable}" "{dest}"'}]})
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return [str(dest)], "hook copied + SessionStart registered"


def _deploy_cowork(src: Path, dry_run: bool) -> tuple[list[str], str]:
    """Copy the neuron-guard plugin dir; enabling stays a Cowork-side step."""
    dest = _claude_dir() / "plugins" / src.name
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    return [str(dest)], "plugin copied (enable it from Cowork if not active)"


def _deploy_opencode(src: Path, dry_run: bool) -> tuple[list[str], str]:
    """Copy the .mjs plugin next to opencode.json + add it to `plugin` array."""
    dest = _opencode_dir() / "plugins" / src.name
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        cfgp = _opencode_dir() / "opencode.json"
        try:
            cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
        except (json.JSONDecodeError, OSError):
            return [str(dest)], "opencode.json unreadable — add plugin manually"
        plugins = cfg.setdefault("plugin", [])
        rel = f"plugins/{src.name}"
        if not any(src.name in p for p in plugins):
            plugins.append(rel)
            cfgp.parent.mkdir(parents=True, exist_ok=True)
            cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return [str(dest)], "plugin copied + registered in opencode.json"


_DEPLOYERS = {"claude-code": _deploy_claude_code,
              "cowork": _deploy_cowork,
              "opencode": _deploy_opencode}


def _deploy_hook(client: str, asset: str, assets_root: Path, dry_run: bool) -> dict:
    src = assets_root / asset
    if not src.exists():
        return {"action": "deploy_hook", "ok": False, "client": client,
                "detail": f"asset missing: {src}"}
    fn = _DEPLOYERS.get(client)
    if fn is None:
        return {"action": "deploy_hook", "ok": False, "client": client,
                "detail": "no deployer for client"}
    try:
        deployed, detail = fn(src, dry_run)
    except Exception as exc:  # noqa: BLE001
        return {"action": "deploy_hook", "ok": False, "client": client, "detail": str(exc)}
    return {"action": "deploy_hook", "ok": True, "client": client,
            "deployed": deployed, "detail": detail}


# --------------------------------------------------------------------------
# Install executor
# --------------------------------------------------------------------------

def execute_install(state: dict | None = None, *, assets_root=None,
                    dry_run: bool = False) -> list[dict]:
    """Run `installer.plan(state)` for real. Returns one result dict per action.

    ``assets_root`` = directory containing `Neuron/clients` assets (defaults to
    the repo's Neuron/clients next to this package, if present).
    """
    from gray_matter import clients as _clients
    state = state if state is not None else detect_state()
    root = Path(assets_root) if assets_root else (
        Path(__file__).resolve().parent.parent / "Neuron" / "clients")
    hooks: dict[str, list[str]] = {}
    results: list[dict] = []
    for act in installer.plan(state):
        a = act["action"]
        if a == "reap":
            results.append(_reap(act["pids"], dry_run))
        elif a == "ensure_data":
            results.append(_ensure_data(act["component"], dry_run))
        elif a == "install":
            results.append(_install_gm(dry_run))
        elif a == "register":
            if dry_run:
                results.append({"action": "register", "ok": True,
                                "detail": f"would register {act['target']} in {act['clients']}"})
            else:
                only = [c for c in act["clients"] if c in _clients.CLIENTS] or None
                regs = _clients.register(gateway=True, only=only)
                # "skipped: client not found" is not a failure of the install
                ok = all(r.get("ok") or r.get("action") == "skipped" for r in regs)
                results.append({"action": "register", "ok": ok, "clients": regs})
        elif a == "deploy_hook":
            r = _deploy_hook(act["client"], act["asset"], root, dry_run)
            if r.get("ok") and r.get("deployed"):
                hooks.setdefault(act["client"], []).extend(r["deployed"])
            results.append(r)
        elif a == "write_manifest":
            if dry_run:
                results.append({"action": "write_manifest", "ok": True,
                                "detail": str(paths.manifest_path())})
            else:
                installer.record_install({**state, "hooks": hooks})
                results.append({"action": "write_manifest", "ok": True,
                                "detail": str(paths.manifest_path())})
        else:
            results.append({"action": a, "ok": False, "detail": "unknown action"})
    return results


# --------------------------------------------------------------------------
# Uninstall executor
# --------------------------------------------------------------------------

def _scrub_claude_settings(dry_run: bool) -> None:
    """Drop our SessionStart entry from ~/.claude/settings.json (only ours)."""
    settings = _claude_dir() / "settings.json"
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    groups = (cfg.get("hooks") or {}).get("SessionStart")
    if not groups:
        return
    new_groups = []
    for g in groups:
        kept = [h for h in g.get("hooks", [])
                if "neuron_sessionstart_hook" not in h.get("command", "")]
        if kept:
            g["hooks"] = kept
            new_groups.append(g)
    if new_groups != groups and not dry_run:
        cfg["hooks"]["SessionStart"] = new_groups
        settings.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _scrub_opencode_config(dry_run: bool) -> None:
    cfgp = _opencode_dir() / "opencode.json"
    try:
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    plugins = cfg.get("plugin")
    if not isinstance(plugins, list):
        return
    kept = [p for p in plugins if "neuron-handshake" not in p]
    if kept != plugins and not dry_run:
        cfg["plugin"] = kept
        cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _remove_hook(client: str, path: str, dry_run: bool) -> dict:
    p = Path(path)
    ok = True
    try:
        if not dry_run:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    except OSError:
        ok = False
    if client == "claude-code":
        _scrub_claude_settings(dry_run)
    elif client == "opencode":
        _scrub_opencode_config(dry_run)
    return {"action": "remove_hook", "ok": ok, "client": client, "path": path}


def _remove_code(dry_run: bool) -> dict:
    targets = [paths.app_dir(), paths.logs_dir(), paths.config_file(),
               paths.manifest_path(), paths.pids_path()]
    if not dry_run:
        for t in targets:
            try:
                if t.is_dir():
                    shutil.rmtree(t, ignore_errors=True)
                else:
                    t.unlink(missing_ok=True)
            except OSError:
                pass
        try:  # gm_home itself, if now empty (bridges may survive as data)
            paths.gm_home().rmdir()
        except OSError:
            pass
    return {"action": "remove_code", "ok": True,
            "removed": [str(t) for t in targets]}


def _remove_data(name: str, path: str, dry_run: bool) -> dict:
    p = Path(path)
    try:
        if not dry_run:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        return {"action": "remove_data", "ok": True, "name": name, "path": path}
    except OSError as exc:
        return {"action": "remove_data", "ok": False, "name": name, "detail": str(exc)}


def execute_uninstall(*, purge_data: bool = False, assume_yes: bool = False,
                      dry_run: bool = False, ask=None) -> list[dict]:
    """Run `uninstaller.plan()` for real.

    Data policy stays interactive: `ask_data` prompts (via ``ask`` callable or
    stdin); ``assume_yes`` answers yes to every prompt; ``purge_data`` skips
    the question entirely (plan already emits remove_data).
    """
    from gray_matter import clients as _clients
    manifest = paths.Manifest.load().data
    orphans = [p for p in _tracked_pids() if _alive(p) and p != os.getpid()]
    ask = ask or (lambda q: assume_yes or
                  input(f"{q} [y/N] ").strip().lower() in ("y", "yes", "s", "si", "sì"))
    results: list[dict] = []
    for act in uninstaller.plan(manifest, purge_data=purge_data,
                                orphan_pids=orphans, data_paths=paths.data_paths()):
        a = act["action"]
        if a == "reap":
            results.append(_reap(act["pids"], dry_run))
        elif a == "deregister":
            if dry_run:
                results.append({"action": "deregister", "ok": True,
                                "detail": f"would deregister from {act['clients']}"})
            else:
                regs = _clients.deregister()
                results.append({"action": "deregister", "ok": True, "clients": regs})
        elif a == "remove_hook":
            results.append(_remove_hook(act["client"], act["path"], dry_run))
        elif a == "remove_code":
            results.append(_remove_code(dry_run))
        elif a == "ask_data":
            if dry_run:
                results.append({"action": "ask_data", "ok": True,
                                "name": act["name"], "detail": "would ask"})
            elif ask(f"Rimuovere la memoria '{act['name']}' ({act['path']})?"):
                results.append(_remove_data(act["name"], act["path"], dry_run))
            else:
                results.append({"action": "ask_data", "ok": True,
                                "name": act["name"], "detail": "kept"})
        elif a == "remove_data":
            results.append(_remove_data(act["name"], act["path"], dry_run))
        else:
            results.append({"action": a, "ok": False, "detail": "unknown action"})
    return results
