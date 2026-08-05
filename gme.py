"""Gray Matter Environment — centralized tool registry.

SSOT for tool discovery and multi-venv execution. Each tool writes a JSON
file here after install. The GUI reads these to find the correct Python
for each tool.

Location:
    Windows: %LOCALAPPDATA%\\GrayMatterEnvironment\\
    macOS:   ~/Library/Application Support/GrayMatterEnvironment/
    Linux:   ~/.local/share/GrayMatterEnvironment/

Usage:
    from gray_matter.gme import read_tool, write_tool, list_tools

    # Read a tool
    neuron = read_tool("neuron")
    if neuron:
        python_path = neuron["python"]

    # Write a tool
    write_tool({
        "key": "neuron",
        "label": "Neuron",
        "version": "6.1.2",
        "venv": "/path/to/venv",
        "python": "/path/to/venv/bin/python",
        "module": "neuron",
        "cli_module": "neuron.__main__",
        "status": "installed",
        "linked_to": "gray-matter",
        "source": "/path/to/source",
        "installed_at": "2026-07-26T12:00:00Z",
        "error": None,
        "health": {
            "pid": None,
            "ping_ms": None,
            "memory_mb": None,
            "cpu_percent": None,
            "uptime_s": None,
            "last_check": None
        }
    })

    # List all tools
    tools = list_tools()
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


__all__ = [
    "gme_root",
    "ensure_gme",
    "tool_json_path",
    "read_tool",
    "write_tool",
    "list_tools",
    "update_health",
    "mark_missing",
    "register_installed",
    "remove_tool",
    "get_python",
    "get_venv",
    "is_installed",
    "get_version",
    "demo",
]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def user_base() -> Path:
    """Per-OS user-data base — THE rule, shared by every location in the suite.

    Deliberately no `darwin` branch. `~/Library/Application Support` is the
    Apple convention and this function used to follow it, but it was the only
    place in the suite that did: `neuron/config.py`, `neuron/paths.py`,
    `neuron/project.py`, `neuron/tunnel.py`, `neurag/paths.py` and
    `gray_matter/paths.py` all resolve `~/.local/share` on macOS. So a Mac had
    the tool REGISTRY in Library and every byte of tool DATA in .local/share —
    two roots, and `tunnel.py` writing `GrayMatterEnvironment/tunnel.json` into
    the folder the registry was *not* in. One root beats the more idiomatic one.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
    else:
        base = os.environ.get("XDG_DATA_HOME", "") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
    # LOCALAPPDATA/XDG_DATA_HOME vuoti (servizio, scheduled task, env ripulito)
    # davano `Path("") / "GrayMatterEnvironment"` = path RELATIVO: il registro
    # dei tool finiva nella cwd del processo di turno. Non è teorico — la cartella
    # `GrayMatterEnvironment/` comparsa nella root del workspace veniva da qui.
    if not base:
        base = os.path.expanduser("~")
    return Path(base)


def _legacy_macos_root() -> Path:
    """Where macOS installs before this alignment put the registry."""
    return (Path(os.path.expanduser("~")) / "Library" / "Application Support"
            / "GrayMatterEnvironment")


def gme_root() -> Path:
    """Dove vivono i JSON dei tool: ``<base>/GrayMatterEnvironment/registry``.

    ``GrayMatterEnvironment/`` e' diventata la radice UNICA della suite (ci
    stanno anche graymatter/, neuron/, neurag/), quindi il registro scende di un
    livello: i suoi file non devono stare mescolati alle cartelle dati, o
    "cancella il registro" e "cancella i dati" diventano lo stesso gesto.

    Un registro ESISTENTE vince sempre — sia quello vecchio piatto in
    ``GrayMatterEnvironment/*.json``, sia quello macOS in Library — cosi'
    spostare la regola non puo' far dire alla GUI "nessun tool installato".
    """
    suite = user_base() / "GrayMatterEnvironment"
    current = suite / "registry"
    if current.is_dir():
        return current
    # registro piatto pre-suite: <base>/GrayMatterEnvironment/*.json
    if suite.is_dir() and any(suite.glob("*.json")):
        return suite
    if sys.platform == "darwin":
        # Anche qui le due forme: registry/ e il piatto di prima.
        legacy = _legacy_macos_root()
        for cand in (legacy / "registry", legacy):
            if cand.is_dir() and any(cand.glob("*.json")):
                return cand
    return current


def ensure_gme() -> Path:
    """Create GME folder if not exists. Returns path."""
    root = gme_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def tool_json_path(key: str) -> Path:
    """Path to a tool's JSON in GME. Pure — does not touch the filesystem.

    It used to call ``ensure_gme()``, which made every *read* create
    ``%LOCALAPPDATA%\\GrayMatterEnvironment`` as a side effect: one
    ``read_tool()`` from the GUI (or from a test run) left an empty folder
    behind on a machine where nothing was ever installed. Only ``write_tool()``
    creates the directory now.
    """
    return gme_root() / f"{key}.json"


# ---------------------------------------------------------------------------
# Read / Write
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {"key", "label", "version", "venv", "python", "module",
                    "cli_module", "status"}


def _ensure_defaults(data: dict[str, Any]) -> dict[str, Any]:
    """Fill missing fields with safe defaults. Mutates and returns *data*."""
    now = datetime.now(timezone.utc).isoformat()
    data.setdefault("installed_at", now)
    data.setdefault("status", "installed")
    data.setdefault("error", None)
    data.setdefault("health", {
        "pid": None,
        "ping_ms": None,
        "memory_mb": None,
        "cpu_percent": None,
        "uptime_s": None,
        "last_check": None,
    })
    return data


def read_tool(key: str) -> dict[str, Any] | None:
    """Read a tool's JSON from GME.  Returns *None* if missing or invalid."""
    path = tool_json_path(key)
    if not path.exists():
        return None
    try:
        # utf-8-SIG, not utf-8: Windows PowerShell 5.1's `Set-Content -Encoding
        # UTF8` (what install.ps1 uses) prepends a BOM. Plain utf-8 leaves the
        # BOM as ﻿, json.loads raises, and this except swallows it — so the
        # whole registry silently degraded to the find_spec() fallback on every
        # Windows install. utf-8-sig strips a BOM if present, no-op if not, so
        # it reads both the PowerShell and the install.sh writers.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if "key" not in data or "python" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _merge_entry(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """`new` sopra `old`, senza perdere quello che `new` non sa.

    Tre regole, ognuna per una perdita di dati vista davvero:

    * un valore nuovo a ``None`` NON cancella un valore vecchio reale.
      ``register_installed()`` scrive sempre ``linked_to: None`` perche' non ha
      modo di saperlo, e a ogni reinstall azzerava il gateway che gestisce il
      tool.
    * i dict si fondono in profondita' (``health``), non si sostituiscono: un
      writer che aggiorna solo il pid buttava via ping/memoria/uptime.
    * ``installed_at`` resta quello della PRIMA installazione. Riscriverlo a
      ogni giro rendeva impossibile dire da quanto un tool e' li'.
    """
    out = dict(old)
    for k, v in new.items():
        if v is None and out.get(k) is not None:
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update({kk: vv for kk, vv in v.items()
                           if vv is not None or merged.get(kk) is None})
            out[k] = merged
            continue
        out[k] = v
    if old.get("installed_at"):
        out["installed_at"] = old["installed_at"]
    return out


def write_tool(data: dict[str, Any], *, merge: bool = True) -> None:
    """Write a tool's JSON to GME.  Atomic (tmp + rename), e in MERGE.

    Il registro e' condiviso: ci scrivono l'installer, la GUI, il monitor di
    salute e ogni tool della suite, in momenti diversi e da versioni diverse.
    Sovrascrivere il file intero con quello che sa UN solo writer e' come si
    perdono campi che nessuno ha mai deciso di buttare. `merge=False` resta per
    i casi in cui si vuole davvero azzerare l'entry.
    """
    key = data.get("key")
    if not key:
        raise ValueError("JSON must have a 'key' field")
    ensure_gme()                      # the only place that creates the folder
    path = tool_json_path(key)
    if merge:
        existing = read_tool(key)
        if existing is None and path.exists():
            # File presente ma illeggibile (JSON rotto, troncato a meta' da un
            # crash). Sovrascriverlo in silenzio significa distruggere l'unica
            # copia di quello che c'era: si mette da parte, poi si riscrive.
            try:
                path.replace(path.with_suffix(".json.corrupt"))
            except OSError:
                pass
        elif existing:
            data = _merge_entry(existing, data)
    tmp = path.with_suffix(".tmp")
    _ensure_defaults(data)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)  # atomic on same filesystem


def list_tools() -> list[dict[str, Any]]:
    """Return every tool registered in GME (may be empty)."""
    root = gme_root()
    if not root.exists():
        return []
    tools: list[dict[str, Any]] = []
    for f in sorted(root.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8-sig"))   # BOM: see read_tool
            if "key" in data:
                tools.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return tools


# ---------------------------------------------------------------------------
# Targeted mutations
# ---------------------------------------------------------------------------

def update_health(key: str, health: dict[str, Any]) -> None:
    """Merge *health* into the tool's ``health`` field and persist."""
    data = read_tool(key)
    if data is None:
        return
    data.setdefault("health", {}).update(health)
    data["health"]["last_check"] = datetime.now(timezone.utc).isoformat()
    write_tool(data)


def mark_missing(key: str) -> None:
    """Set ``status`` to *missing* (tool uninstalled but JSON remains)."""
    data = read_tool(key)
    if data:
        data["status"] = "missing"
        write_tool(data)


def _demote_if_ours(key: str) -> None:
    """Segna ``missing`` una entry che dichiara QUESTO venv ma non è più
    importabile qui.

    Senza questo, `register_installed` promuoveva soltanto: un tool rimosso dal
    venv restava ``installed`` per sempre, e il SessionStart hook continuava ad
    annunciare al modello tool che non rispondono più — la stessa classe di bug
    che `test_gateway_without_neuron_does_not_announce_memory` esiste per
    impedire.

    Il confronto sul venv è la parte che non si può saltare: un peer installato
    in un venv PROPRIO (standalone) non è importabile da qui e non deve essere
    declassato da noi — è di un altro installer, come dice
    `register_installed`. Si tocca solo ciò che dichiara di essere nostro.
    """
    data = read_tool(key)
    if data and data.get("status") == "installed" and data.get("venv") == sys.prefix:
        mark_missing(key)


def register_installed(source: str = "") -> list[str]:
    """Register every trio tool importable from THIS interpreter. Returns the keys.

    ``ARCHITETTURA.md`` says "ogni tool scrive un file JSON dopo install", but the
    write only ever existed inside the shell installers — six copies in two
    languages — and on the path nobody takes:

    * ``neuron/install.ps1`` and ``neurag/install.ps1`` keep their GME block
      inside ``Install-Standalone``, and in gateway mode they delegate to
      ``gray_matter/install.ps1`` and exit before reaching it. So a peer
      registered itself only when installed WITHOUT Gray Matter — precisely the
      case where no GUI ever reads the registry.
    * the suite path installs the peers through ``Install-Peer`` (a plain
      ``pip install`` into GM's venv) which never registered anything.

    Net effect: a full-suite install left only ``gray-matter`` in GME. Doing it
    here instead — one implementation, in the language that also reads it — is
    what closes both holes, and it is why the BOM bug could exist at all.

    ``sys.executable`` is the honest answer for every tool found: ``find_spec``
    just resolved the module in *this* interpreter, so this interpreter can run
    it. A peer living in its own venv simply is not importable here and is left
    to its own installer.
    """
    from importlib.util import find_spec

    from gray_matter.catalog import ENVIRONMENTS, _version

    done: list[str] = []
    for env in ENVIRONMENTS:
        try:
            if find_spec(env["module"]) is None:
                _demote_if_ours(env["key"])
                continue
        except BaseException:      # noqa: BLE001 — a broken package is "not installed"
            _demote_if_ours(env["key"])
            continue
        write_tool({
            "key": env["key"],
            "label": env["label"],
            "version": _version(env["module"]),
            "venv": sys.prefix,
            "python": sys.executable,
            "module": env["module"],
            "cli_module": env["cli"],
            "status": "installed",
            "linked_to": None,
            "source": source,
        })
        done.append(env["key"])
    return done


def remove_tool(key: str) -> bool:
    """Delete a tool's JSON.  Returns *True* if something was removed."""
    path = tool_json_path(key)
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Convenience lookups
# ---------------------------------------------------------------------------

def get_python(key: str) -> str | None:
    """Python path for *key*, or *None* if not installed."""
    data = read_tool(key)
    if data and data.get("status") == "installed":
        return data.get("python")
    return None


def get_venv(key: str) -> str | None:
    """Venv path for *key*, or *None* if not installed."""
    data = read_tool(key)
    if data and data.get("status") == "installed":
        return data.get("venv")
    return None


def is_installed(key: str) -> bool:
    """*True* if *key* is registered **and** ``status == "installed"``."""
    data = read_tool(key)
    return data is not None and data.get("status") == "installed"


def get_version(key: str) -> str:
    """Version string for *key*, empty if unknown."""
    data = read_tool(key)
    return data.get("version", "") if data else ""


# ---------------------------------------------------------------------------
# Migration — detect old installs outside GME
# ---------------------------------------------------------------------------

# Known venv locations for each tool (order: most specific first)
_VENV_CANDIDATES: dict[str, list[str]] = {
    "gray-matter": [
        "{localappdata}/gray-matter/.venv",
    ],
    "neuron": [
        "{localappdata}/neuron/.venv",
    ],
    "neurag": [
        "{localappdata}/neurag/.venv",
    ],
}

# Module names to probe via find_spec as a fallback detection
_MODULE_NAMES: dict[str, str] = {
    "gray-matter": "gray_matter",
    "neuron": "neuron",
    "neurag": "neurag",
}


def _find_venv_for(key: str) -> str | None:
    """Try to locate an existing venv for *key* in common locations.
    
    Search order:
    1. Known locations (VENV_CANDIDATES)
    2. Fallback: check if current Python is inside a venv for this tool
    """
    # Was a second, hand-rolled copy of the per-OS rule — and it drifted from
    # gme_root() the moment either changed. One resolver, used by both.
    local = str(user_base())

    for pattern in _VENV_CANDIDATES.get(key, []):
        path = pattern.replace("{localappdata}", local)
        p = Path(path)
        if p.exists():
            return str(p)
    
    # Fallback: check if we're running from a venv for this tool
    # e.g., neuron\.venv\Scripts\python.exe → venv root is neuron\.venv
    this_python = Path(sys.executable)
    if this_python.name in ("python.exe", "python3", "python"):
        # Walk up: Scripts/python.exe → .venv → neuron/
        candidate_venv = this_python.parent.parent  # likely .venv
        candidate_parent = candidate_venv.parent  # likely the tool dir
        if candidate_venv.name == ".venv" and candidate_venv.exists():
            if candidate_parent.name.lower().replace("-", "_") == key.replace("-", "_"):
                return str(candidate_venv)
    
    return None


def _find_python_for_venv(venv_path: str) -> str | None:
    """Return the Python executable inside a venv, or None."""
    p = Path(venv_path)
    if sys.platform == "win32":
        exe = p / "Scripts" / "python.exe"
    else:
        exe = p / "bin" / "python3"
    return str(exe) if exe.exists() else None


def detect_old_installs() -> list[dict]:
    """Find tools that are installed but not registered in GME.

    Returns a list of dicts with keys: key, label, venv, python, module.
    These are candidates for migration (register-only, no venv move).
    """
    from importlib.util import find_spec as _find_spec

    # Only an *installed* entry counts as registered. A tool the uninstall left
    # marked `missing` and that is back on disk (pip, a peer's installer, a
    # repair) has to be offered for migration again — keying on mere presence
    # made mark_missing a one-way door out of the migration UI.
    gme_keys = {t["key"] for t in list_tools() if t.get("status") == "installed"}
    old: list[dict] = []

    # Tool metadata (labels match catalog.py ENVIRONMENTS)
    _LABELS = {
        "gray-matter": "Gray Matter",
        "neuron": "Neuron",
        "neurag": "NeuRAG",
    }

    for key, label in _LABELS.items():
        if key in gme_keys:
            continue  # already in GME

        # Probe via find_spec
        mod_name = _MODULE_NAMES.get(key, key.replace("-", "_"))
        if _find_spec(mod_name) is None:
            continue  # not installed at all

        # Try to find a dedicated venv; fall back to THIS interpreter.
        # _VENV_CANDIDATES only knows `{localappdata}/{key}/.venv`, which the
        # suite installer never creates: it co-installs all three into Gray
        # Matter's single venv. So the common case fell through with venv=None
        # and python="" and the migration card offered rows that registered a
        # hollow entry. find_spec above just resolved the module here, so this
        # interpreter demonstrably runs it.
        venv = _find_venv_for(key)
        python = (_find_python_for_venv(venv) if venv else None) or sys.executable

        old.append({
            "key": key,
            "label": label,
            "venv": venv or sys.prefix,
            "python": python,
            "module": mod_name,
        })

    return old


def migrate_tool(key: str) -> dict:
    """Register an old install into GME (no venv move).

    Returns {"ok": True, "key": key} on success, or
    {"ok": False, "error": "..."} on failure.
    """
    old = detect_old_installs()
    match = next((o for o in old if o["key"] == key), None)
    if match is None:
        return {"ok": False, "error": f"{key} not detected as old install"}

    from gray_matter.catalog import _version

    data = {
        "key": match["key"],
        "label": match["label"],
        # was hardcoded "" — the version is knowable, and a blank one left the
        # GUI showing a nameless row after a migration
        "version": _version(match["module"]),
        "venv": match["venv"] or "",
        "python": match["python"],
        "module": match["module"],
        "cli_module": "",
        "status": "installed",
        "linked_to": None,
        "source": "migration",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
        "health": {
            "pid": None,
            "ping_ms": None,
            "memory_mb": None,
            "cpu_percent": None,
            "uptime_s": None,
            "last_check": None,
        },
    }
    write_tool(data)
    return {"ok": True, "key": key}


def migrate_all() -> dict:
    """Register all detected old installs into GME.

    Returns {"ok": True, "migrated": [...], "errors": [...]}.
    """
    migrated: list[str] = []
    errors: list[str] = []
    for old in detect_old_installs():
        r = migrate_tool(old["key"])
        if r.get("ok"):
            migrated.append(old["key"])
        else:
            errors.append(f"{old['key']}: {r.get('error', 'unknown')}")
    return {"ok": True, "migrated": migrated, "errors": errors}


# ---------------------------------------------------------------------------
# Self-test / demo
# ---------------------------------------------------------------------------

def demo() -> None:
    """Print every tool registered in GME."""
    root = gme_root()
    tools = list_tools()
    print(f"GME: {root}")
    print(f"Registered tools: {len(tools)}")
    if not tools:
        print("  (none)")
    for t in tools:
        status = t.get("status", "?")
        version = t.get("version", "?")
        venv = t.get("venv", "?")
        print(f"  {t['key']}: {status} v{version} @ {venv}")


def main(argv: "list[str] | None" = None) -> int:
    """``python -m gray_matter.gme [register]``.

    ``register`` is what the installers call — one line each, replacing ~40 lines
    of hand-written JSON duplicated across six shell scripts in two languages.
    That duplication is what let the PowerShell BOM, and the macOS path
    divergence, exist in the first place.

    It is also the manual repair when a registry is empty or stale, which is why
    it prints what it wrote instead of staying silent.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "register":
        keys = register_installed(source=args[1] if len(args) > 1 else "")
        print(f"GME registry: {len(keys)} tool(s) -> {gme_root()}")
        for k in keys:
            print(f"  {k} {get_version(k)}")
        return 0
    demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
