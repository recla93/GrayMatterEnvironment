"""Blackboard condiviso (GM, talamo): key-value con TTL e versioni.

state_set pubblica un valore con TTL opzionale; state_get lo legge (None se
assente o scaduto — lo stato decade da solo); state_delta ritorna i cambi da
una versione (scadute incluse: il consumatore deve vedere che una entry è
scaduta, non sparita). Chiavi: 'org/componente/nome'. DB sqlite locale
(paths.gm_state()), override GRAY_MATTER_STATE per i test. Stdlib only,
connessione aperta per chiamata (single-writer, niente stato globale).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import gray_matter.paths as _paths

_SCHEMA = """CREATE TABLE IF NOT EXISTS state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    version     INTEGER NOT NULL,
    updated_at  REAL NOT NULL,
    expires_at  REAL
)"""


def _db_path() -> Path:
    ov = os.environ.get("GRAY_MATTER_STATE", "").strip()
    return Path(ov) if ov else _paths.gm_state()


def _open() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _entry(row: sqlite3.Row) -> dict:
    return {"key": row["key"], "value": json.loads(row["value"]),
            "version": row["version"], "updated_at": row["updated_at"],
            "expires_at": row["expires_at"]}


def state_set(key: str, value, ttl: float | None = None) -> dict:
    """Scrive key=value con scadenza opzionale (ttl secondi). Ritorna l'entry."""
    conn = _open()
    try:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM state").fetchone()[0]
        now = time.time()
        expires_at = now + ttl if ttl else None
        conn.execute(
            "INSERT OR REPLACE INTO state (key, value, version, updated_at, expires_at) "
            "VALUES (?,?,?,?,?)",
            (key, json.dumps(value), version, now, expires_at))
        conn.commit()
        return {"key": key, "value": value, "version": version,
                "updated_at": now, "expires_at": expires_at}
    finally:
        conn.close()


def state_get(key: str) -> dict | None:
    """Legge key. None se assente o scaduta (lo stato e' passato)."""
    conn = _open()
    try:
        row = conn.execute("SELECT * FROM state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        entry = _entry(row)
        if entry["expires_at"] is not None and time.time() > entry["expires_at"]:
            return None
        return entry
    finally:
        conn.close()


def state_delta(prefix: str = "", since_version: int = 0) -> list[dict]:
    """Cambi dalla versione since in poi, filtro per prefisso di chiave.
    Le entry scadute compaiono (il consumatore deve vederle); il prefisso è
    confrontato letteralmente (substr, niente jolly di LIKE/GLOB)."""
    conn = _open()
    try:
        rows = conn.execute(
            "SELECT * FROM state WHERE version > ? AND substr(key, 1, length(?)) = ? "
            "ORDER BY version", (since_version, prefix, prefix)).fetchall()
        return [_entry(r) for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["GRAY_MATTER_STATE"] = str(Path(tmp) / "state.db")
        state_set("gm/worker/neuron", {"pid": 42}, ttl=10)
        assert state_get("gm/worker/neuron")["value"]["pid"] == 42
        # TTL scaduto: 0.01s di vita, aspetta e rileggi
        state_set("x/fugace", 1, ttl=0.01)
        time.sleep(0.02)
        assert state_get("x/fugace") is None
        # versioni e delta: il delta riporta i CAMBI da since, scadute incluse
        v0 = state_get("gm/worker/neuron")["version"]  # entry viva
        state_set("neurag/topic/count", 27)            # dopo x/fugace (scaduta)
        delta = state_delta("", since_version=v0)
        assert len(delta) == 2, delta
        assert {e["key"] for e in delta} == {"x/fugace", "neurag/topic/count"}
        # prefisso letterale: un underscore nel prefisso non diventa un jolly
        assert len(state_delta("neurag/")) == 1
        assert len(state_delta("gm/w_orker")) == 0  # '_' non e' jolly
        # roundtrip dei tipi: il valore torna col tipo originale
        assert state_get("neurag/topic/count")["value"] == 27
        print("PASS: state")
