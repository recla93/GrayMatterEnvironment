"""Install-path SSOT + install manifest for the trio (INSTALLER-UX §3–4).

One place that resolves every location install/uninstall touch, and a manifest
that records exactly what was written — so uninstall removes exactly that, no
guessing. Stdlib only. The env override GM_HOME roots everything under one dir
(handy for tests and isolated installs).

Layout (per-OS base = %LOCALAPPDATA% on Windows, $XDG_DATA_HOME|~/.local/share else):
    <base>/graymatter/        app/, config.json, logs/, manifest.json, pids.json, bridges.json
    <base>/<slug>/graphs      Neuron graph store (slug default 'neuron')
    <base>/neurag/knowledge.db NeuRAG knowledge base
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Must match neuron/config.py:resolve_slug(), which defaults to "neuron". It
# defaulted to "neuron5" here, so Neuron wrote its graphs to <base>/neuron while
# Gray Matter looked in <base>/neuron5 — that divergence is what split a real
# user's memory across two folders. Only used as the fallback for when Neuron
# is not importable; neuron_graphs() asks the peer first.
SLUG = os.environ.get("NEURON_SLUG", "neuron")
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
# SoC: GM NON definisce i path dei peer, li SCOPRE chiamando i peer (ognuno è la
# SSOT dei propri). Import lazy + fallback storico se il peer non è installato,
# così GM standalone non si rompe. (richiesta 2026-07-22: SSOT/SoC ai massimi)
def neuron_graphs() -> Path:
    try:
        from neuron import paths as _np
        return _np.graphs_dir()
    except Exception:  # noqa: BLE001 — Neuron non installato: fallback storico
        return _user_base() / SLUG / "graphs"


def _neurag_dir_fallback() -> Path:
    """Come NeuRAG risolve la SUA cartella, senza poterlo importare.

    Deve restare allineato a `neurag/paths.py:data_dir()`, inclusa la regola
    "il vault esistente vince": NeuRAG ha scritto per anni in
    `~/.local/share/neurag` su OGNI OS, quindi su Windows indovinare solo
    `%LOCALAPPDATA%\\neurag` puntava a una cartella vuota mentre il vault vero
    stava altrove."""
    if os.environ.get("NEURAG_HOME"):
        return Path(os.environ["NEURAG_HOME"])
    current = _user_base() / "neurag"
    legacy = Path.home() / ".local" / "share" / "neurag"
    if current != legacy and legacy.exists() and not current.exists():
        return legacy
    return current


def neurag_db() -> Path:
    try:
        from neurag import paths as _rp
        return _rp.db_path()
    except Exception:  # noqa: BLE001 — NeuRAG non installato: fallback storico
        return _neurag_dir_fallback() / "knowledge.db"


def neurag_config() -> Path:
    try:
        from neurag import paths as _rp
        return _rp.config_path()
    except Exception:  # noqa: BLE001 — stessa regola del vault (vedi sopra)
        return _neurag_dir_fallback() / "config.json"


def gm_bridges() -> Path:    return gm_home() / "bridges.db"   # was bridges.json (migrated once)


def data_paths() -> dict:
    """The user's memory — treated specially at uninstall (interactive prompt)."""
    return {"neuron_graphs": neuron_graphs(),
            "gm_bridges": gm_bridges(),
            "neurag_db": neurag_db()}


# --- Source discovery: GM registra il PROPRIO sorgente, SCOPRE quelli dei peer
# SoC/SSOT: ogni componente è la fonte di verità del proprio path sorgente
# (`<comp>.paths.source_dir()`). GM tiene solo il PROPRIO record e, per repair/
# reinstall/GUI, COMPONE la vista chiedendo ai peer — non li ridefinisce.
def env_file() -> Path:
    return gm_home() / "paths.json"          # record del sorgente DI GM


def record_self(source: "str | Path | None" = None) -> dict:
    """GM registra la propria cartella sorgente (repo). La chiama l'installer.
    I peer registrano sé stessi con i loro `record-paths`. Idempotente."""
    data = {}
    try:
        data = json.loads(env_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    if source and (Path(source) / "pyproject.toml").exists():
        data["source"] = str(Path(source).resolve())
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        f = env_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return data


def _gm_source() -> Path:
    try:
        rec = json.loads(env_file().read_text(encoding="utf-8")).get("source")
        if rec and Path(rec).exists():
            return Path(rec)
    except Exception:  # noqa: BLE001
        pass
    return Path(__file__).resolve().parent   # .../gray_matter (posizione pacchetto)


def source_dir(component: str) -> "Path | None":
    """Cartella sorgente (repo) di un componente. GM la conosce per sé, i peer la
    ESPONGONO loro (`<comp>.paths.source_dir()`) → GM chiede, non hardcoda."""
    try:
        if component == "gray-matter":
            p = _gm_source()
        elif component == "neuron":
            from neuron import paths as _np
            p = _np.source_dir()
        elif component == "neurag":
            from neurag import paths as _rp
            p = _rp.source_dir()
        else:
            return None
        return p if p and Path(p).exists() else None
    except Exception:  # noqa: BLE001 — peer non installato
        return None


def discover_sources() -> dict:
    """Vista composta {componente: sorgente} chiedendo a ciascuno il proprio."""
    out = {}
    for c in ("gray-matter", "neuron", "neurag"):
        d = source_dir(c)
        if d:
            out[c] = str(d)
    return out


def installer_script() -> "Path | None":
    """L'installer completo (install.ps1/sh) dal sorgente gray-matter."""
    gm = source_dir("gray-matter")
    if not gm:
        return None
    ps1, sh = gm / "install.ps1", gm / "install.sh"
    if os.name == "nt" and ps1.exists():
        return ps1
    if sh.exists():
        return sh
    return ps1 if ps1.exists() else None


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
