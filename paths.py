"""SSOT dei path di NeuRAG — NeuRAG sa dove stanno i SUOI file, punto.

Separation of Concerns: qui vivono TUTTE le location di NeuRAG (dati, config,
sorgente). `db.py` e `settings.py` non le ridefiniscono, le importano da qui; e
Gray Matter non le hardcoda, le SCOPRE chiamando queste funzioni (`source_dir`,
`db_path`, ...). Un componente = una fonte di verità dei propri path.

Override: NEURAG_HOME per la cartella dati.
Stdlib only.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


def data_dir() -> Path:
    """Cartella dati di NeuRAG (dove vivono knowledge.db e config.json).

    Convenzione storica di NeuRAG: ~/.local/share/neurag (coerente su ogni OS —
    è dove NeuRAG ha sempre scritto, audit compreso). Override: NEURAG_HOME."""
    env = os.environ.get("NEURAG_HOME")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "neurag"


def db_path() -> Path:
    return data_dir() / "knowledge.db"


def config_path() -> Path:
    return data_dir() / "config.json"


# --- self-knowledge del sorgente (per repair/reinstall) ---------------------
def _self_registry() -> Path:
    """Il registro DI NEURAG (nella sua cartella dati): NeuRAG registra sé stesso
    qui, e chi vuole scoprirlo (GM) chiama source_dir()."""
    return data_dir() / "paths.json"


def record_self(source: "str | Path | None" = None) -> dict:
    """Registra la cartella sorgente (repo) di NeuRAG. La chiama l'installer di
    NeuRAG (o quello di GM per conto suo). Idempotente."""
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
    """Cartella sorgente (repo) di NeuRAG: quella registrata se c'è, altrimenti
    la posizione del pacchetto installato (Path(__file__).parent)."""
    try:
        rec = json.loads(_self_registry().read_text(encoding="utf-8")).get("source")
        if rec and Path(rec).exists():
            return Path(rec)
    except Exception:  # noqa: BLE001
        pass
    return Path(__file__).resolve().parent


def data_paths() -> dict:
    """Le location dati di NeuRAG (per repair/uninstall scoped su NeuRAG)."""
    return {"neurag_db": db_path(), "neurag_config": config_path()}
