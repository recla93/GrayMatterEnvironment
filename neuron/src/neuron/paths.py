"""SSOT dei path di Neuron — Neuron sa dove stanno i SUOI file.

Separation of Concerns: le location di Neuron (memoria/grafi, sorgente) vivono
qui. `graphs_dir` delega a `config` (che era già la fonte di verità del grafo);
la novità è la *self-knowledge* del sorgente per repair/reinstall, così Gray
Matter la SCOPRE chiamando `source_dir()` invece di hardcodarla.

Stdlib only, zero import pesanti (come config.py).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from neuron import config as _config


def graphs_dir() -> Path:
    """Store dei grafi di Neuron (delega a config, la SSOT storica)."""
    return Path(_config.graphs_dir())


def data_dir() -> Path:
    """Cartella dati di Neuron (il livello slug, genitore di graphs/)."""
    return graphs_dir().parent


def _self_registry() -> Path:
    return data_dir() / "paths.json"


def record_self(source: "str | Path | None" = None) -> dict:
    """Registra la cartella sorgente (repo) di Neuron. La chiama l'installer di
    Neuron (o quello di GM per conto suo). Idempotente."""
    data = {}
    try:
        data = json.loads(_self_registry().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    if source and (Path(source) / "pyproject.toml").exists():
        data["source"] = str(Path(source).resolve())
    data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        f = _self_registry()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return data


def source_dir() -> Path:
    """Cartella sorgente (repo) di Neuron: quella registrata se c'è, altrimenti
    la posizione del pacchetto installato. Neuron usa il src-layout, quindi il
    repo è due livelli sopra il package (`.../neuron/src/neuron`)."""
    try:
        rec = json.loads(_self_registry().read_text(encoding="utf-8")).get("source")
        if rec and Path(rec).exists():
            return Path(rec)
    except Exception:  # noqa: BLE001
        pass
    pkg = Path(__file__).resolve().parent          # .../src/neuron
    for cand in (pkg.parent.parent, pkg):           # repo (src-layout), else pkg
        if (cand / "pyproject.toml").exists():
            return cand
    return pkg.parent.parent


def data_paths() -> dict:
    """Le location dati di Neuron (per repair/uninstall scoped su Neuron)."""
    return {"neuron_graphs": graphs_dir()}


_OLD_SLUG = "neuron5"


def migrate_graphs(dry_run: bool = False) -> dict:
    """Move graph files from the old ``neuron5`` slug to the current ``neuron`` one.

    Per FILE, not per directory. The original moved the whole folder with a single
    ``shutil.move`` and bailed out with "New path already has data" the moment the
    new location held anything at all — which it does as soon as Neuron has run
    once under the new slug. On a real machine that meant five graphs (default,
    architecture, backend, general, gray-matter) stranded in ``neuron5`` with a
    migration that would refuse forever, and no way out short of moving files by
    hand. Moving file by file migrates everything that does not collide.

    A name present on BOTH sides is left untouched and reported in ``collisions``:
    two graph DBs for the same context are two different memories, and merging
    them is a decision only the user can make. Nothing is ever overwritten.

    Returns ``migrated`` (list of moved names), ``collisions``, ``old_path``,
    ``new_path``, ``error``. Idempotent.
    """
    import os
    import shutil
    from pathlib import Path

    result: dict = {"migrated": [], "collisions": [], "old_path": "",
                    "new_path": "", "error": ""}

    # The user explicitly pinned the old slug: leave their data where they put it.
    if os.environ.get("NEURON_SLUG") == _OLD_SLUG:
        return result

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share")

    old_path = Path(base) / _OLD_SLUG / "graphs"
    new_path = Path(graphs_dir())
    result["old_path"], result["new_path"] = str(old_path), str(new_path)

    if not old_path.exists() or old_path.resolve() == new_path.resolve():
        return result

    try:
        entries = sorted(p for p in old_path.iterdir() if p.is_file())
    except OSError as exc:
        result["error"] = str(exc)
        return result

    for src_file in entries:
        dest = new_path / src_file.name
        if dest.exists():
            result["collisions"].append(src_file.name)
            continue
        if dry_run:
            result["migrated"].append(src_file.name)
            continue
        try:
            new_path.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_file), str(dest))
            result["migrated"].append(src_file.name)
        except OSError as exc:
            result["error"] = f"{src_file.name}: {exc}"
            return result          # stop at the first failure, report what moved

    # Drop the old tree only when nothing of the user's is left behind.
    # `paths.json` is the slug's self-registration (which source dir Neuron was
    # installed from), not user data: once the graphs have moved and the CURRENT
    # slug has its own, the old copy is a fossil that keeps the retired
    # `neuron5` folder alive — and the legacy scan keeps reporting it forever.
    if not dry_run and not result["collisions"]:
        stale = old_path.parent / "paths.json"
        if stale.is_file() and (Path(graphs_dir()).parent / "paths.json").is_file():
            try:
                stale.unlink()
                result["migrated"].append("paths.json (fossile dello slug)")
            except OSError:
                pass
        for d in (old_path, old_path.parent):
            try:
                if d.exists() and not any(d.iterdir()):
                    d.rmdir()
            except OSError:
                pass

    return result
