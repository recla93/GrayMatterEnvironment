"""Install-path SSOT + install manifest for the trio (INSTALLER-UX §3–4).

One place that resolves every location install/uninstall touch, and a manifest
that records exactly what was written — so uninstall removes exactly that, no
guessing. Stdlib only. The env override GM_HOME roots everything under one dir
(handy for tests and isolated installs).

Layout (per-OS base = %LOCALAPPDATA% on Windows, $XDG_DATA_HOME|~/.local/share else):
    <base>/graymatter/        app/, config.json, logs/, manifest.json, pids.json, bridges.json
    <base>/<slug>/graphs      Neuron graph store (slug default 'neuron5')
    <base>/neurag/knowledge.db NeuRAG knowledge base
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

SLUG = os.environ.get("NEURON_SLUG", "neuron5")
MANIFEST_SCHEMA = 1


def _user_base() -> Path:
    if os.environ.get("GM_HOME"):
        return Path(os.environ["GM_HOME"])
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
    return Path(base)


# --- Code / control (removed on uninstall) ---------------------------------
def gm_home() -> Path:      return _user_base() / "graymatter"
def app_dir() -> Path:      return gm_home() / "app"
def gm_exe() -> Path:       return app_dir() / ("gray-matter.exe" if os.name == "nt" else "gray-matter")
def config_file() -> Path:  return gm_home() / "config.json"
def logs_dir() -> Path:     return gm_home() / "logs"
def manifest_path() -> Path: return gm_home() / "manifest.json"
def pids_path() -> Path:    return gm_home() / "pids.json"


# --- User MEMORY (never wiped without explicit consent — INSTALLER-UX §6) ---
def neuron_graphs() -> Path: return _user_base() / SLUG / "graphs"
def gm_bridges() -> Path:    return gm_home() / "bridges.json"
def neurag_db() -> Path:     return _user_base() / "neurag" / "knowledge.db"


def data_paths() -> dict:
    """The user's memory — treated specially at uninstall (interactive prompt)."""
    return {"neuron_graphs": neuron_graphs(),
            "gm_bridges": gm_bridges(),
            "neurag_db": neurag_db()}


class Manifest:
    """Records what the installer wrote so uninstall can undo it precisely."""

    def __init__(self, data: dict | None = None):
        self.data = data or {"schema": MANIFEST_SCHEMA, "components": {},
                             "clients": [], "hooks": {}, "pids": []}

    @classmethod
    def load(cls, path=None) -> "Manifest":
        try:
            return cls(json.loads(Path(path or manifest_path()).read_text(encoding="utf-8")))
        except Exception:
            return cls()

    def save(self, path=None) -> None:
        p = Path(path or manifest_path())
        p.parent.mkdir(parents=True, exist_ok=True)
        self.data["schema"] = MANIFEST_SCHEMA
        self.data["updated"] = time.time()
        p.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_component(self, name: str, **info) -> None:
        self.data.setdefault("components", {})[name] = info

    def remove_component(self, name: str) -> None:
        self.data.get("components", {}).pop(name, None)

    def set_clients(self, clients) -> None:
        self.data["clients"] = sorted(set(clients))

    def record_hook(self, client: str, path: str) -> None:
        hooks = self.data.setdefault("hooks", {}).setdefault(client, [])
        if path not in hooks:
            hooks.append(path)

    def components(self) -> dict:
        return self.data.get("components", {})
