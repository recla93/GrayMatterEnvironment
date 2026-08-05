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
import subprocess
import sys
import tempfile
from pathlib import Path

from gray_matter import installer, paths, uninstaller

# Windows: nascondi la finestra console dei child (tasklist/taskkill). La GUI gira
# via pythonw (senza console), quindi ogni subprocess console LAMPEGGIA un CMD —
# era il "cmd che appare a ogni clic sul tool" (pannello Processi in render()).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

__all__ = ["detect_state", "execute_install", "execute_uninstall",
           "repair_targets", "execute_repair"]

# Marker used to recognise our own entries when scrubbing client configs.
_HOOK_MARKERS = ("neuron_sessionstart_hook", "neuron-handshake", "neuron-guard")


# --------------------------------------------------------------------------
# State detection (read-only)
# --------------------------------------------------------------------------

def _alive(pid: int) -> bool:
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                               capture_output=True, text=True, timeout=10,
                               creationflags=_NO_WINDOW)
            return str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


def _tracked_pids() -> list[int]:
    """I PID registrati e ancora vivi (gray_matter.pids è la SSOT del registro).

    Leggeva il JSON a mano, e per mesi ha letto un file che NESSUNO scriveva:
    tornava sempre [], quindi `orphan_pids` era sempre vuoto e il reap in
    `execute_install()` non mieteva mai nulla. Ora la scrittura c'è
    (`pids.record_self`) e la lettura passa da lì, potatura inclusa.
    """
    try:
        from gray_matter import pids as _pids
        return [e["pid"] for e in _pids.tracked()]
    except Exception:  # noqa: BLE001 — registro illeggibile: nessun orfano noto
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
    # Orfano = vivo, ma il processo che l'ha lanciato non c'è più (il client AI
    # è stato chiuso o riavviato). Prima si contava come orfano QUALSIASI PID
    # tracciato e vivo: con il registro finalmente popolato, quella definizione
    # avrebbe mietuto anche i server che stanno servendo un client attivo.
    try:
        from gray_matter import pids as _pids
        orphans = [e["pid"] for e in _pids.orphans()]
    except Exception:  # noqa: BLE001
        orphans = []
    return {"installed": installed,
            # The manifest, not a directory that existed only as a side effect of
            # _install_gm creating it (see the note there).
            "gm_present": paths.manifest_path().exists(),
            "clients": detected,
            "orphan_pids": orphans}


# --------------------------------------------------------------------------
# Shared effectful primitives
# --------------------------------------------------------------------------

def check_wiring() -> list[dict]:
    """Read-only: i PUNTATORI scritti sul disco puntano ancora dove serve?

    `detect_state()` guarda cosa e' installato; questo guarda se cio' che e'
    installato e' ancora *collegato*. Sono i quattro controlli che, fatti a mano
    dopo la migrazione alla radice GME, hanno trovato quattro guasti veri: il
    registro cercato un livello sopra, un interprete sparito lasciato nella
    entry SessionStart, un hook deployato piu' vecchio del sorgente, e le stesse
    entry stantie nei config MCP. Nessuno di questi rompe un import, quindi
    nessuna suite li vede: si vedono solo guardando il disco.

    Ogni voce: ``{check, ok, detail, fix}``. Non tocca niente e non solleva mai.
    """
    out: list[dict] = []

    def rec(check, ok, detail, fix=""):
        out.append({"check": check, "ok": bool(ok), "detail": detail, "fix": fix})

    # 1. Il registro: GM e l'hook devono guardare la STESSA cartella. E' un
    #    mirror scritto a mano (l'hook non puo' importare gray_matter), quindi
    #    e' la copia che va alla deriva quando la regola si sposta.
    try:
        from gray_matter import gme
        root = gme.gme_root()
        tools = sorted(t.get("key") for t in gme.list_tools() if t.get("key"))
        hook_root = None
        try:
            hook_root = _shipped_hook()._gme_root()
        except Exception:  # noqa: BLE001
            pass
        if hook_root is not None and Path(hook_root) != Path(root):
            rec("registry", False,
                f"GM scrive in {root}, l'hook legge {hook_root}",
                "reinstalla l'hook: gray-matter repair")
        elif not tools:
            rec("registry", False, f"nessun tool registrato in {root}",
                "gray-matter repair (riscrive il registro)")
        else:
            rec("registry", True, f"{root} -> {', '.join(tools)}")
    except Exception as exc:  # noqa: BLE001
        rec("registry", False, f"non leggibile: {exc}")

    # 2. La entry SessionStart deve poter GIRARE: dopo la migrazione il venv ha
    #    cambiato posto e il comando registrato puntava a un interprete sparito.
    settings = _claude_dir() / "settings.json"
    try:
        cfg = json.loads(settings.read_text(encoding="utf-8-sig")) if settings.exists() else {}
        cmds = [h.get("command", "")
                for g in (cfg.get("hooks", {}).get("SessionStart") or [])
                if isinstance(g, dict)
                for h in (g.get("hooks") or []) if isinstance(h, dict)]
        ours = [c for c in cmds if "neuron_sessionstart_hook" in c]
        broken = [c for c in ours if _entry_is_dead(c)]
        if broken:
            rec("hook_entry", False,
                f"interprete inesistente: {_hook_interpreter(broken[0])}",
                "gray-matter repair (riscrive la entry)")
        elif not ours:
            rec("hook_entry", False, "nessuna entry SessionStart registrata",
                "gray-matter repair")
        else:
            rec("hook_entry", True, f"{len(ours)} entry, interprete presente")
    except (json.JSONDecodeError, OSError) as exc:
        rec("hook_entry", False, f"{settings} non leggibile: {exc}")

    # 3. L'hook deployato deve essere il sorgente: un deploy vecchio resta li'
    #    per sempre, e un hook stantio parla di tool che non esistono piu'.
    try:
        src = _find_clients_root() / "claude-code-hook" / "neuron_sessionstart_hook.py"
        dst = _claude_dir() / "hooks" / "neuron_sessionstart_hook.py"
        if not dst.exists():
            rec("hook_file", False, f"non deployato: {dst}", "gray-matter repair")
        elif src.exists() and src.read_bytes() != dst.read_bytes():
            rec("hook_file", False, f"{dst} e' diverso dal sorgente",
                "gray-matter repair (ri-deploya l'hook)")
        else:
            rec("hook_file", True, str(dst))
    except OSError as exc:
        rec("hook_file", False, f"non confrontabile: {exc}")

    # 4. Stessa domanda per i config MCP: un client che invoca un interprete
    #    sparito e' un server che non parte, in silenzio.
    try:
        from gray_matter import clients as _c
        bad = []
        for _key, spec in _c.CLIENTS.items():
            path = _c._pick(spec["paths"]())
            if not path or spec.get("format") == "toml":
                continue
            try:
                node = json.loads(Path(path).read_text(encoding="utf-8-sig") or "{}")
            except (json.JSONDecodeError, OSError):
                continue
            for k in _c.keys_for(spec, path):
                node = node.get(k) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                continue
            for slug in _c.SERVERS:
                entry = node.get(slug)
                if not isinstance(entry, dict):
                    continue
                cmd = entry.get("command")
                exe = cmd[0] if isinstance(cmd, list) and cmd else cmd
                if isinstance(exe, str) and os.path.isabs(exe) and not os.path.exists(exe):
                    bad.append(f"{spec['label']}/{slug} -> {exe}")
        if bad:
            rec("mcp_entries", False, "; ".join(bad[:3]),
                "gray-matter register (riscrive le entry)")
        else:
            rec("mcp_entries", True, "ogni interprete registrato esiste")
    except Exception as exc:  # noqa: BLE001
        rec("mcp_entries", False, f"non verificabile: {exc}")

    # 5. L'etichetta deve corrispondere al CORPO. Un'installazione andata a
    #    meta' (file lock di un server vivo durante l'install, e il
    #    "WARNING: install failed - continuing" che se la mangia) lascia il
    #    dist-info nuovo sopra i file vecchi. Da li' in poi tutto cio' che si
    #    fida della versione — pip ("already satisfied"), `Install-Peer`
    #    ("Keeping X"), `catalog._version` — vede aggiornato cio' che non lo e',
    #    e i fix non arrivano piu' a nessuno. Verificato: neuron 6.4.0 sotto un
    #    dist-info 6.4.1, con due dist-info per lo stesso pacchetto.
    try:
        import importlib
        import importlib.metadata as _md
        from gray_matter.catalog import ENVIRONMENTS

        problems = []
        for env in ENVIRONMENTS:
            dist = env["module"].replace("_", "-")
            # `d.name`, non `d.metadata["Name"]`: su 3.14 il getitem implicito
            # di Message emette una DeprecationWarning a ogni run.
            found = [d for d in _md.distributions()
                     if (getattr(d, "name", "") or "").lower() == dist]
            if not found:
                continue
            if len(found) > 1:
                vs = sorted({d.version for d in found})
                problems.append(f"{dist}: {len(found)} dist-info ({', '.join(vs)})")
                continue
            declared = found[0].version
            try:
                body = getattr(importlib.import_module(env["module"]), "__version__", "")
            except Exception:  # noqa: BLE001 — pacchetto rotto: lo dice il check 4
                continue
            if body and declared and body != declared:
                problems.append(f"{dist}: dist-info {declared}, codice {body}")
        if problems:
            rec("versions", False, "; ".join(problems),
                "pip install --force-reinstall --no-deps <sorgente>  (a client AI chiusi)")
        else:
            rec("versions", True, "etichetta e codice coincidono")
    except Exception as exc:  # noqa: BLE001
        rec("versions", False, f"non verificabile: {exc}")

    return out


def install_drift(module: str, source_dir) -> dict:
    """Il codice INSTALLATO e' lo stesso del sorgente? Confronta i file, non le
    versioni.

    La versione e' un'etichetta, e un'etichetta puo' mentire: un install andato
    a meta' lascia il dist-info nuovo sui file vecchi, e da li' in poi pip dice
    "already satisfied" e l'installer dice "Keeping X" su codice che non e'
    quello. L'unica risposta onesta alla domanda "devo reinstallare?" e' il
    confronto dei byte.

    Ritorna ``{state, files, detail}`` con state in absent|same|differ.
    Una implementazione sola, chiamata da install.ps1 E install.sh: la stessa
    regola scritta in due linguaggi e' esattamente cio' che va alla deriva.
    """
    import importlib
    src = Path(source_dir)
    try:
        mod = importlib.import_module(module)
        installed = Path(mod.__file__).parent
    except Exception as exc:  # noqa: BLE001
        return {"state": "absent", "files": 0, "detail": f"non importabile ({exc})"}
    # Sorgente: layout src/ (neuron) o piatto (neurag, gray_matter).
    for cand in (src / "src" / module, src / module, src):
        if (cand / "__init__.py").exists():
            src_pkg = cand
            break
    else:
        return {"state": "absent", "files": 0, "detail": f"sorgente non trovato in {src}"}
    if src_pkg.resolve() == installed.resolve():
        return {"state": "same", "files": 0, "detail": "installazione editable (stesso albero)"}
    differ = 0
    for f in src_pkg.rglob("*"):
        if not f.is_file() or "__pycache__" in f.parts or f.suffix == ".pyc":
            continue
        other = installed / f.relative_to(src_pkg)
        try:
            if not other.exists() or other.read_bytes() != f.read_bytes():
                differ += 1
        except OSError:
            differ += 1
    if differ:
        return {"state": "differ", "files": differ,
                "detail": f"{differ} file diversi dal sorgente"}
    return {"state": "same", "files": 0, "detail": "identico al sorgente"}


def setup_summary() -> str:
    """Quale installazione c'e' adesso, in una riga — perche' un menu che chiede
    "reinstallo?" senza ricordare COSA e' installato costringe a indovinare."""
    try:
        from gray_matter import gme
        have = {t.get("key") for t in gme.list_tools()
                if t.get("status") == "installed"}
    except Exception:  # noqa: BLE001
        return "installazione non determinabile"
    if not have:
        return "nessun tool registrato"
    names = {"gray-matter": "GM", "neuron": "Neuron", "neurag": "NeuRAG"}
    label = " + ".join(names[k] for k in ("gray-matter", "neuron", "neurag") if k in have)
    if have == set(names):
        return f"full suite ({label})"
    if "gray-matter" in have:
        return f"gateway ({label})"
    return f"standalone ({label})"


def _shipped_hook():
    """Il modulo hook COME SPEDITO, caricato da file: e' l'unico modo di
    chiedergli dove crede di trovare il registro senza duplicarne la regola."""
    import importlib.util
    p = _find_clients_root() / "claude-code-hook" / "neuron_sessionstart_hook.py"
    spec = importlib.util.spec_from_file_location("_gm_shipped_hook", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reap(pids: list[int], dry_run: bool) -> dict:
    killed, failed = [], []
    for pid in pids:
        if dry_run:
            killed.append(pid)
            continue
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=10,
                               creationflags=_NO_WINDOW)
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
    # app_dir() is gone: it was an empty `<gm_home>/app` that only ever existed
    # because this line created it, and the uninstall panel then presented that
    # empty folder to the user as "the code".
    made = [paths.logs_dir(), paths.gm_bridges().parent]
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


def _hook_interpreter(cmd: str) -> str:
    """L'interprete di una command line: il primo token, quotato o no."""
    cmd = (cmd or "").strip()
    if cmd.startswith('"'):
        return cmd[1:].split('"', 1)[0]
    return cmd.split(" ", 1)[0]


def _entry_is_dead(cmd: str) -> bool:
    """La entry non puo' girare: il suo interprete ASSOLUTO non esiste piu'.

    Un `python` nudo non si giudica (dipende dal PATH); un path assoluto si'.
    """
    exe = _hook_interpreter(cmd)
    return bool(exe) and os.path.isabs(exe) and not os.path.exists(exe)


def _deploy_claude_code(src: Path, dry_run: bool) -> tuple[list[str], str]:
    """Copy the SessionStart hook + register it in ~/.claude/settings.json."""
    dest = _claude_dir() / "hooks" / src.name
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        settings = _claude_dir() / "settings.json"
        try:
            cfg = json.loads(settings.read_text(encoding="utf-8-sig")) if settings.exists() else {}
        except (json.JSONDecodeError, OSError):
            return [str(dest)], "settings.json unreadable — register hook manually"
        groups = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])
        # "matcher" singolare, come il resto del mondo: hooks.json del plugin, il
        # deployer standalone, gli hook dell'utente. "matchers" (plurale, lista)
        # esisteva solo qui.
        fresh = {"matcher": "startup|resume|clear|compact",
                 "hooks": [{"type": "command",
                            "command": f'"{sys.executable}" "{dest}"'}]}
        ours = [g for g in groups
                if any("neuron_sessionstart_hook" in (h.get("command") or "")
                       for h in (g.get("hooks") or []) if isinstance(h, dict))]
        # Una entry NOSTRA che non puo' girare va RISCRITTA, non lasciata stare.
        # "gia' presente = non toccare" e' come `claude mcp add` trattava le entry
        # esistenti: dopo che l'install e' passato alla radice GME, il comando
        # registrato puntava a un interprete che non esiste piu' e l'handshake
        # non partiva piu' — per sempre, perche' nessun reinstall lo aggiornava.
        # Verificato su installazione reale.
        dead = [g for g in ours
                if any(_entry_is_dead(h.get("command") or "")
                       for h in (g.get("hooks") or []) if isinstance(h, dict))]
        if dead:
            for g in dead:
                groups.remove(g)
            groups.append(fresh)
            note = "hook copied + stale SessionStart entry rewritten"
        elif not ours:
            groups.append(fresh)
            note = "hook copied + SessionStart registered"
        else:
            return [str(dest)], "hook refreshed (SessionStart already registered)"
        settings.parent.mkdir(parents=True, exist_ok=True)
        _save_user_json(settings, cfg)
        return [str(dest)], note
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


def _save_user_json(p: Path, data) -> None:
    """Backup + atomic replace + ensure_ascii=False, per ogni config UTENTE che
    riscriviamo. Stessa garanzia di `_save_json` in clients/deploy_hooks.py e
    dell'hardening S2 su `_register_json`: qui mancava, e questo path riscrive
    lo stesso genere di file (accenti escapati, nessun backup, scrittura non
    atomica)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        shutil.copyfile(p, p.with_suffix(p.suffix + ".bak"))
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _deploy_opencode(src: Path, dry_run: bool) -> tuple[list[str], str]:
    """Copy the .mjs plugin next to opencode.json + add it to `plugin` array."""
    dest = _opencode_dir() / "plugins" / src.name
    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        cfgp = _opencode_dir() / "opencode.json"
        try:
            cfg = json.loads(cfgp.read_text(encoding="utf-8-sig")) if cfgp.exists() else {}
        except (json.JSONDecodeError, OSError):
            return [str(dest)], "opencode.json unreadable — add plugin manually"
        plugins = cfg.setdefault("plugin", [])
        # "./plugins/x": la stessa forma che scrive il deployer standalone
        # (clients/deploy_hooks.py). Due forme per lo stesso file facevano
        # appendere una seconda entry a chi installava GM e poi un peer.
        rel = f"./plugins/{src.name}"
        if not any(src.name in p for p in plugins if isinstance(p, str)):
            plugins.append(rel)
            _save_user_json(cfgp, cfg)
    return [str(dest)], "plugin copied + registered in opencode.json"


def _deploy_codex(src: Path, dry_run: bool) -> tuple[list[str], str]:
    """Mirror the neuron-guard cowork plugin into the Codex plugin cache and
    enable it in ~/.codex/config.toml.

    The plugin keeps its Claude-Cowork format (the same asset Cowork consumes) —
    Codex loads cowork-format plugins from its cache but only when listed as
    `[plugins."<name>@claude-cowork"] enabled = true`. The mirror prunes stale
    files (removed in the source, removed in the cache) and the config.toml
    edit is a section-targeted upsert: the rest of the user's config stays
    byte-for-byte. config.toml is NOT returned as a removable path — uninstall
    scrubs the block, it never deletes the file."""
    codex_home = Path(os.path.expanduser("~")) / ".codex"
    # Versione dal plugin, non hardcoded: al primo bump di plugin.json un
    # "0.1.0" fisso avrebbe deployato in una cartella che nessuno legge
    # (stesso helper in clients/deploy_hooks.py::_plugin_version).
    try:
        _meta = json.loads((src / ".claude-plugin" / "plugin.json")
                           .read_text(encoding="utf-8-sig"))
        _ver = str(_meta.get("version") or "") or "0.1.0"
    except (OSError, json.JSONDecodeError, AttributeError):
        _ver = "0.1.0"
    cache = codex_home / "plugins" / "cache" / "claude-cowork" / src.name / _ver
    cfg = codex_home / "config.toml"
    if not dry_run:
        cache.parent.mkdir(parents=True, exist_ok=True)
        keep = set()
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src)
                keep.add(rel)
                out = cache / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
        if cache.is_dir():
            for f in list(cache.rglob("*")):
                if f.is_file() and f.relative_to(cache) not in keep:
                    try:
                        f.unlink()
                    except OSError:
                        pass
        from gray_matter import clients
        section = f'plugins."{src.name}@claude-cowork"'
        text = cfg.read_text(encoding="utf-8-sig") if cfg.exists() else ""
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(clients._toml_upsert_section(text, section, ["enabled = true"]),
                       encoding="utf-8")
    return [str(cache)], "plugin mirrored + enabled in config.toml"


_DEPLOYERS = {"claude-code": _deploy_claude_code,
              "cowork": _deploy_cowork,
              "opencode": _deploy_opencode,
              "codex": _deploy_codex}


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
    # The deployers guard their writes with `if not dry_run` but return the same
    # past-tense detail either way, so a --dry-run reported "hook copied +
    # SessionStart registered" for a hook it had not touched. Prefixed here, once,
    # rather than in each deployer — same marker cmd_uninstall/cmd_repair print.
    if dry_run:
        detail = f"[dry-run] {detail}"
    return {"action": "deploy_hook", "ok": True, "client": client,
            "deployed": deployed, "detail": detail}


# A sentinel asset every valid clients-root must contain. Guards against
# returning a dir that merely *exists* but is empty (the old "asset missing"
# trap: a stale env var or an assets-less repo-root shell).
_CLIENTS_SENTINEL = "claude-code-hook/neuron_sessionstart_hook.py"


def _has_assets(p: Path) -> bool:
    return (p / _CLIENTS_SENTINEL).exists()


def _find_clients_root() -> Path:
    """Locate the handshake-assets ``clients/`` directory.

    Since the assets now travel *inside* the installed ``neuron`` package
    (`src/neuron/clients/`, shipped via package-data), the robust primary path
    is to ask importlib where ``neuron`` lives — this works identically for a
    wheel install and an editable (`pip install -e`) checkout. The dev-layout
    and env-var paths remain as fallbacks. Every candidate is validated with
    :func:`_has_assets` so a stale/empty dir never wins.
    """
    import os
    # 1. Explicit env var (power users / dev) — only if it actually has assets.
    env_dir = os.environ.get("GM_NEURON_CLIENTS")
    if env_dir and _has_assets(Path(env_dir)):
        return Path(env_dir)
    # 2. Installed peer package (wheel OR editable): <peer>/clients.
    #    NeuRAG is probed too, not just Neuron: a GM + NeuRAG install has no
    #    `neuron` package at all, so looking only there left that combination
    #    with no handshake assets — and therefore no handshake.
    try:
        import importlib.util
        for peer in ("neuron", "neurag"):
            spec = importlib.util.find_spec(peer)
            for loc in (spec.submodule_search_locations or []) if spec else []:
                cand = Path(loc) / "clients"
                if _has_assets(cand):
                    return cand
    except Exception:  # noqa: BLE001 — import machinery must never break install
        pass
    # 3. Dev/source layouts (no neuron installed): new in-package location, then
    #    the legacy repo-root location, bundled-in-GM, and a short walk-up.
    pkg = Path(__file__).resolve().parent
    for cand in (
        pkg / "neuron" / "src" / "neuron" / "clients",          # bundled in GM zip
        pkg.parent / "neuron" / "src" / "neuron" / "clients",   # sibling checkout
        pkg / "neuron" / "clients",                             # legacy bundled
        pkg.parent / "neuron" / "clients",                      # legacy sibling
    ):
        if _has_assets(cand):
            return cand
    for parent in (pkg.parent, pkg.parent.parent, pkg.parent.parent.parent):
        for cand in (parent / "neuron" / "src" / "neuron" / "clients",
                     parent / "neuron" / "clients"):
            if _has_assets(cand):
                return cand
    # 4. Nothing found — return the canonical in-package path so the deploy step
    #    emits a clear "asset missing: <path>" pointing at the right place.
    return pkg.parent / "neuron" / "src" / "neuron" / "clients"


# --------------------------------------------------------------------------
# Install executor
# --------------------------------------------------------------------------

def execute_install(state: dict | None = None, *, assets_root=None,
                    dry_run: bool = False, only: "list[str] | None" = None) -> list[dict]:
    """Run `installer.plan(state)` for real. Returns one result dict per action.

    ``assets_root`` = directory containing `Neuron/clients` assets (defaults to
    the repo's Neuron/clients next to this package, if present).

    ``only`` = the clients the USER picked. It overrides the plan's detected
    list rather than intersecting with it: someone who explicitly names a
    client means it, even if its config does not exist yet. ``None`` keeps the
    historic behaviour (every detected client).
    """
    from gray_matter import clients as _clients
    state = state if state is not None else detect_state()
    root = Path(assets_root) if assets_root else _find_clients_root()
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
                picked = (list(only) if only is not None
                          else [c for c in act["clients"] if c in _clients.CLIENTS] or None)
                regs = _clients.register(gateway=True, only=picked)
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
        elif a == "register_gme":
            results.append(_register_gme(dry_run))
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
        cfg = json.loads(cfgp.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return
    plugins = cfg.get("plugin")
    if not isinstance(plugins, list):
        return
    kept = [p for p in plugins if not (isinstance(p, str) and "neuron-handshake" in p)]
    if kept != plugins and not dry_run:
        cfg["plugin"] = kept
        _save_user_json(cfgp, cfg)


def _scrub_codex_plugins(dry_run: bool) -> None:
    """Drop our `[plugins."neuron-guard@claude-cowork"]` block from
    ~/.codex/config.toml and the mirrored plugin cache — never the file,
    never the user's other plugins."""
    cfg = Path(os.path.expanduser("~")) / ".codex" / "config.toml"
    try:
        text = cfg.read_text(encoding="utf-8-sig")
    except OSError:
        text = None
    import re
    if text is not None:
        pattern = re.compile(r"(?ms)^\[plugins\.\"neuron-guard@claude-cowork\"\]\s*?\n.*?(?=^\[|\Z)")
        new_text = pattern.sub("", text)
        if new_text != text and not dry_run:
            cfg.write_text(new_text, encoding="utf-8")
    # The Cowork plugin cache is OUR mirror (deploy_hooks.deploy_cowork):
    # scrubbing the config block but leaving the cache would keep the model
    # reaching for tools that no longer exist.
    cache = Path(os.path.expanduser("~")) / ".codex" / "plugins" / "cache" / "claude-cowork" / "neuron-guard"
    if cache.exists() and not dry_run:
        shutil.rmtree(cache, ignore_errors=True)


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
    elif client == "codex":
        _scrub_codex_plugins(dry_run)
    return {"action": "remove_hook", "ok": ok, "client": client, "path": path}


def _remove_code(dry_run: bool) -> dict:
    # state.db and paths.json are GM's own control files in gm_home() and were in
    # NO list — not code, not data — so every uninstall left them behind and the
    # rmdir below could never succeed. app_dir() is gone (see _install_gm).
    # The cloud `.env` (Turso token) lives in gm_home() too and was never a
    # target either: uninstall left the credentials on disk.
    from gray_matter import cloud
    targets = [paths.logs_dir(), paths.config_file(), paths.manifest_path(),
               paths.pids_path(), paths.gm_state(), paths.env_file(),
               cloud.default_env_file()]
    if not dry_run:
        for t in targets:
            try:
                if t.is_dir():
                    shutil.rmtree(t, ignore_errors=True)
                else:
                    t.unlink(missing_ok=True)
            except OSError:
                pass
        _sweep_gm_home()
    # `removed` on a dry-run would claim a deletion that never happened — the GUI
    # renders this list verbatim.
    return {"action": "remove_code", "ok": True,
            "removed": [] if dry_run else [str(t) for t in targets],
            "detail": ("[dry-run] would remove " + ", ".join(str(t) for t in targets)
                       if dry_run else "")}


def _sweep_gm_home() -> None:
    """Remove gm_home() once nothing the user chose to keep is left in it.

    `rmdir` and not `rmtree` on purpose: whatever survives here survived because
    the user answered "keep" (bridges.db is the realistic case), and the sweep
    must not out-vote that. Called again after the venv goes, since that is the
    last thing standing between a kept-nothing uninstall and an empty folder."""
    try:
        paths.gm_home().rmdir()
    except OSError:
        pass


def _schedule_venv_delete(path: str) -> bool:
    """Hand the leftovers to a detached shell that outlives us and retries.

    The uninstall is normally run BY something inside the venv — the control
    center, or `gray-matter uninstall` itself — and on Windows a loaded .pyd
    cannot be unlinked, so the process asked to delete the venv is exactly the
    one holding it open. No amount of retrying from in here fixes that: the
    handles go away when we exit. So the deleter has to be a process that is not
    us and does not live in that venv. Polls for ~5 minutes, then gives up.
    """
    home = str(paths.gm_home())
    try:
        if os.name == "nt":
            # A .bat, not `cmd /c "<one long string>"`: passing the loop inline
            # tripped cmd's quoting rules and died with "syntax of the file name
            # is incorrect" (rc 123) while still exiting 0 from Python's view.
            # A file has no quoting problem, loops properly, and deletes itself.
            # `ping` is the sleep — `timeout` needs a console a detached process
            # does not have.
            bat = Path(tempfile.gettempdir()) / f"gm_rmvenv_{os.getpid()}.bat"
            bat.write_text(
                "@echo off\r\n"
                f'set "T={path}"\r\n'
                "for /l %%i in (1,1,60) do (\r\n"
                '  if not exist "%T%" goto done\r\n'
                '  rmdir /s /q "%T%" 2>nul\r\n'
                "  ping -n 6 127.0.0.1 >nul\r\n"
                ")\r\n"
                ":done\r\n"
                f'rmdir "{home}" 2>nul\r\n'      # empty parent, if nothing was kept
                'del "%~f0"\r\n', encoding="ascii")
            subprocess.Popen(["cmd", "/c", str(bat)],
                             creationflags=0x00000008 | 0x00000200,  # DETACHED | NEW_GROUP
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            script = (f'for i in $(seq 60); do [ -e "{path}" ] || break; '
                      f'rm -rf "{path}" 2>/dev/null; sleep 5; done; '
                      f'rmdir "{home}" 2>/dev/null || true')
            subprocess.Popen(["sh", "-c", script], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _remove_venv(path: str, dry_run: bool) -> dict:
    if dry_run:
        return {"action": "remove_venv", "ok": True, "path": path,
                "detail": f"[dry-run] would remove {path}"}
    p = Path(path)
    shutil.rmtree(p, ignore_errors=True)
    if p.exists():
        # Windows: a live server (or this very process) still maps its .pyd. The
        # reap at the top of execute_uninstall covers the tracked PIDs; an AI
        # client that respawned its stdio server is not tracked, and we cannot
        # kill ourselves. Defer to a process that outlives us.
        if _schedule_venv_delete(path):
            return {"action": "remove_venv", "ok": True, "path": path,
                    "detail": "in use — scheduled: removed once the app and your "
                              "AI clients close (within ~5 min)"}
        return {"action": "remove_venv", "ok": False, "path": path,
                "detail": "could not fully remove — close your AI apps and re-run"}
    _sweep_gm_home()
    return {"action": "remove_venv", "ok": True, "path": path,
            "detail": f"removed {path}"}


def _register_gme(dry_run: bool) -> dict:
    """Write the GME entry for every trio tool this interpreter can import.
    Best-effort: an install that worked must not be reported as failed because
    the discovery registry could not be written."""
    if dry_run:
        return {"action": "register_gme", "ok": True,
                "detail": f"would register into {gme_root_str()}"}
    try:
        from gray_matter import gme
        keys = gme.register_installed(source=str(paths.gm_home()))
        return {"action": "register_gme", "ok": True, "keys": keys,
                "detail": f"{len(keys)} tool(s) -> {gme.gme_root()}"}
    except (ImportError, OSError) as e:
        return {"action": "register_gme", "ok": False, "detail": str(e)}


def gme_root_str() -> str:
    try:
        from gray_matter import gme
        return str(gme.gme_root())
    except ImportError:
        return "GME"


def _unregister_gme(key: str, dry_run: bool) -> dict:
    """Flip the GME registry entry to ``missing`` so discovery stops handing out
    a dead venv path. Best-effort: a stale entry is cosmetic, a failed uninstall
    is not — never let this raise."""
    if dry_run:
        return {"action": "unregister_gme", "ok": True, "key": key,
                "detail": "would mark missing"}
    try:
        from gray_matter import gme
        existed = gme.read_tool(key) is not None
        gme.mark_missing(key)
        return {"action": "unregister_gme", "ok": True, "key": key,
                "detail": "marked missing" if existed else "not registered"}
    except (ImportError, OSError) as e:
        return {"action": "unregister_gme", "ok": False, "key": key,
                "detail": str(e)}


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


# --------------------------------------------------------------------------
# Repair — granular clean: the user picks WHAT to wipe; code reinstall (forced)
# is done separately by the installer (`install.ps1 -Force`). This function is
# only the "cosa togliere" half: it removes exactly the chosen data surfaces and
# never touches anything not requested. Every item is optional and independent.
# --------------------------------------------------------------------------

def _neurag_config_path() -> Path:
    """NeuRAG's own knob file — chiesto a NeuRAG (SSOT), non hardcodato."""
    return paths.neurag_config()


# Cosa "possiede" ciascun ambiente: da Neuron si pulisce solo Neuron, da NeuRAG
# solo NeuRAG, da Gray Matter tutta la suite. Le registrazioni client (gateway)
# sono un fatto GM, quindi solo nello scope gray-matter.
_SCOPE_KEYS = {
    "gray-matter": ["neuron_graphs", "neurag_db", "gm_bridges",
                    "gm_config", "neurag_config", "registrations"],
    "neuron":      ["neuron_graphs"],
    "neurag":      ["neurag_db", "neurag_config"],
}


def repair_targets(scope: str = "gray-matter") -> list[dict]:
    """Wipeable surfaces for a given SCOPE (which tool launched the repair), each
    with its live state — so the GUI shows only what's present and pertinent, and
    the user picks keep/remove per item. `key` is the id passed to execute_repair."""
    allp = {
        "neuron_graphs": ("Memoria Neuron (grafi)", paths.neuron_graphs()),
        "neurag_db":     ("Knowledge NeuRAG (knowledge.db)", paths.neurag_db()),
        "gm_bridges":    ("Bridges Gray Matter", paths.gm_bridges()),
        "gm_config":     ("Config Gray Matter (config.json)", paths.config_file()),
        "neurag_config": ("Config NeuRAG (embedding, chunk)", _neurag_config_path()),
    }
    out = []
    for key in _SCOPE_KEYS.get(scope, _SCOPE_KEYS["gray-matter"]):
        if key == "registrations":
            out.append({"key": "registrations", "label": "Registrazioni MCP nei client",
                        "path": "(client configs)", "exists": True})
            continue
        label, p = allp[key]
        out.append({"key": key, "label": label, "path": str(p), "exists": p.exists()})
    return out


def execute_repair(wipe: list[str], *, dry_run: bool = False) -> list[dict]:
    """Remove ONLY the chosen surfaces (`wipe` = list of keys from
    :func:`repair_targets`). Anything not listed is kept untouched. Never raises;
    one result dict per requested action."""
    from gray_matter import clients as _clients
    file_targets = {
        "neuron_graphs": paths.neuron_graphs(),
        "neurag_db": paths.neurag_db(),
        "gm_bridges": paths.gm_bridges(),
        "gm_config": paths.config_file(),
        "neurag_config": _neurag_config_path(),
    }
    results: list[dict] = []
    for key in wipe:
        if key == "registrations":
            if dry_run:
                results.append({"action": "deregister", "ok": True,
                                "detail": "would deregister from all clients"})
            else:
                regs = _clients.deregister()
                results.append({"action": "deregister", "ok": True, "clients": regs})
            continue
        target = file_targets.get(key)
        if target is None:
            results.append({"action": "remove_data", "ok": False, "name": key,
                            "detail": "chiave sconosciuta"})
            continue
        results.append(_remove_data(key, str(target), dry_run))
    return results


def execute_uninstall(*, purge_data: bool = False, assume_yes: bool = False,
                      dry_run: bool = False, ask=None,
                      remove_venv: "bool | None" = None) -> list[dict]:
    """Run `uninstaller.plan()` for real.

    Data policy stays interactive: `ask_data` prompts (via ``ask`` callable or
    stdin); ``assume_yes`` answers yes to every prompt; ``purge_data`` skips
    the question entirely (plan already emits remove_data).

    ``remove_venv`` overrides the venv question: True removes it, False keeps it,
    None asks (and keeps it in any non-interactive run). It is separate from
    ``assume_yes`` because the venv is shared with the peers — see the ask_venv
    branch below.
    """
    from gray_matter import clients as _clients
    manifest = paths.Manifest.load().data
    ask = ask or (lambda q: assume_yes or
                  input(f"{q} [y/N] ").strip().lower() in ("y", "yes", "s", "si", "sì"))
    results: list[dict] = []
    # Kill orphans first — pre-condition, not part of the plan loop.
    # If kill fails the error is isolated and doesn't block deregister/remove.
    orphans = [p for p in _tracked_pids() if _alive(p) and p != os.getpid()]
    if orphans:
        results.append(_reap(orphans, dry_run))
    venv = paths.gm_venv()
    for act in uninstaller.plan(manifest, purge_data=purge_data,
                                orphan_pids=[], data_paths=paths.data_paths(),
                                venv=venv, venv_peers=paths.venv_peers()):
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
        elif a == "unregister_gme":
            results.append(_unregister_gme(act["key"], dry_run))
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
        elif a == "ask_venv":
            size = paths.human_size(paths.dir_size(act["path"]))
            who = (" (also runs " + ", ".join(act["peers"]) + ")") if act["peers"] else ""
            # Unticked by default, deliberately: `assume_yes` is a batch flag for
            # "don't block on prompts", and letting it tear down a shared venv
            # would uninstall Neuron and NeuRAG as a side effect of `gray-matter
            # uninstall --yes`. Removing it takes a real yes: an answered prompt
            # or an explicit --venv.
            if dry_run:
                wanted = None
            elif remove_venv is not None:
                wanted = remove_venv
            else:
                wanted = (not assume_yes) and ask(
                    f"Rimuovere anche il venv{who} — {size}? [{act['path']}]")
            if wanted:
                results.append(_remove_venv(act["path"], dry_run))
            else:
                detail = ("would ask" if dry_run else "kept") + f" — {size}{who}"
                results.append({"action": "ask_venv", "ok": True,
                                "path": act["path"], "detail": detail})
        else:
            results.append({"action": a, "ok": False, "detail": "unknown action"})
    return results
