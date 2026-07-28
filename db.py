"""Turso-backed hierarchical knowledge graph with vector embeddings.

Single-database design using Turso (SQLite-compatible) with an extension for
vector cosine-similarity search (384-dim, same as Neuron). Local pyturso for
single-machine, remote Turso (libSQL cloud) for multi-machine.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Optional

try:
    from turso import connect as turso_connect
    TURSO_AVAILABLE = True
except ImportError:
    TURSO_AVAILABLE = False

# --- Cloud Turso (multi-machine) — libsql-client facade ----------------------
# Decoupled port (2026-07-21), keep-in-sync with Neuron/src/neuron/db.py. NeuRAG
# accesses rows by name, so the remote cursor yields name-accessible _CompatRow
# (defined below) instead of Neuron's plain tuples.
#
# IMPORTANT: NeuRAG has its OWN cloud DB. Neuron and NeuRAG must NOT share a Turso
# database — both define a `nodes` table with DIFFERENT schemas, so one URL would
# collide. Hence NeuRAG reads NEURAG_TURSO_DATABASE_URL (its own DB), never
# Neuron's TURSO_DATABASE_URL. The auth token may be shared (org/group token):
# NEURAG_TURSO_AUTH_TOKEN if set, else fall back to TURSO_AUTH_TOKEN.
def _sanitize_credential(value: str) -> str:
    """Toglie ogni whitespace/controllo, non solo agli estremi — keep-in-sync con
    Neuron/_env.py. Il token diventa un header HTTP e lo stack rifiuta un valore
    con CR/LF/NUL dentro: un a-capo nascosto da copia-incolla, o un .env CRLF,
    faceva fallire il cloud senza spiegazione."""
    return re.sub(r"[\s\x00-\x1f\x7f]", "", value or "")


TURSO_DATABASE_URL = _sanitize_credential(os.environ.get("NEURAG_TURSO_DATABASE_URL", ""))
TURSO_AUTH_TOKEN = _sanitize_credential(os.environ.get("NEURAG_TURSO_AUTH_TOKEN")
                                        or os.environ.get("TURSO_AUTH_TOKEN", ""))
REMOTE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

_libsql = None
if REMOTE_TURSO:
    try:
        import libsql_client as _libsql
    except ImportError:
        import sys as _sys
        print("neurag: NEURAG_TURSO_DATABASE_URL is set but the 'cloud' extra "
              "(libsql-client) is not installed — falling back to the local "
              "engine. Enable cloud with: pip install \"neurag[cloud]\"",
              file=_sys.stderr)
        REMOTE_TURSO = False

_REMOTE_NOOP_PRAGMAS = ("journal_mode", "synchronous", "foreign_keys")
_WRITE_PREFIXES = ("insert", "update", "delete", "replace", "create", "alter", "drop")


def _is_write_sql(sql: str) -> bool:
    head = sql.lstrip()
    if not head:
        return False
    return head.split(None, 1)[0].lower() in _WRITE_PREFIXES


def _with_retry(fn, *, attempts: int = 4, base_delay: float = 0.4,
                on_retry=None):
    """Run *fn* with exponential backoff on transient remote failures (P5).

    Only wraps atomic units (client creation, single batch) so a retry can
    never double-apply a partially-written save. *on_retry* (T76) recreates
    a dead client between attempts — without it a dropped WebSocket session
    made every retry fail on the same corpse."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))
            if on_retry is not None:
                try:
                    on_retry()
                except Exception:
                    pass
    raise last  # pragma: no cover


def _url_candidates(url: str) -> list[str]:
    """Connection URLs to try, in order (T76). WebSocket schemes keep a
    long-lived socket that some proxies silently drop; the https:// form
    is stateless per request. Try the user's URL first, then its HTTP twin."""
    out = [url]
    for prefix in ("libsql://", "wss://", "ws://"):
        if url.startswith(prefix):
            out.append("https://" + url[len(prefix):])
            break
    return out


class _RemoteCursor:
    """sqlite3-cursor-like view over a libsql ResultSet; rows name-accessible."""

    def __init__(self, result=None):
        self._result = result

    @property
    def description(self):
        if self._result is None:
            return None
        return [(c,) for c in self._result.columns]

    def fetchall(self):
        if self._result is None:
            return []
        cols = list(self._result.columns)
        return [_CompatRow(cols, tuple(r)) for r in self._result.rows]

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def __iter__(self):
        return iter(self.fetchall())


class RemoteTursoConnection:
    """sqlite3-compatible facade over a remote Turso (libSQL cloud) database.

    Retry + URL fallback + transaction support, matching Neuron's
    RemoteTursoConnection pattern (keep-in-sync). Rows come back as
    _CompatRow so NeuRAG's ``row['col']`` access works unchanged.
    """

    def __init__(self, url: str, auth_token: str):
        self.row_factory = None  # accepted for API parity; rows already named
        self._auth_token = auth_token
        self._urls = _url_candidates(url)
        self._url_idx = 0
        self._client = self._create_client()
        self._tx: list | None = None  # buffered Statements while a tx is open

    def _create_client(self):
        """Create the libsql client, falling back across URL transports."""
        last: Exception | None = None
        for i in range(self._url_idx, len(self._urls)):
            try:
                client = _with_retry(
                    lambda u=self._urls[i]: _libsql.create_client_sync(
                        url=u, auth_token=self._auth_token),
                    attempts=2)
                self._url_idx = i
                return client
            except Exception as e:
                last = e
        raise last

    def _reconnect(self) -> None:
        """Drop dead client and build fresh (T76)."""
        try:
            self._client.close()
        except Exception:
            pass
        self._client = self._create_client()

    @staticmethod
    def _is_noop_pragma(sql: str) -> bool:
        s = sql.strip().lower()
        return (s.startswith("pragma")
                and any(p in s for p in _REMOTE_NOOP_PRAGMAS)
                and "table_info" not in s)

    # -- transaction control ------------------------------------------------
    def begin(self) -> None:
        self._tx = []

    def rollback(self) -> None:
        self._tx = None

    def commit(self) -> None:
        if self._tx is None:
            return
        stmts, self._tx = self._tx, None
        if stmts:
            _with_retry(lambda: self._client.batch(stmts),
                        on_retry=self._reconnect)

    # -- statement execution ------------------------------------------------
    def execute(self, sql: str, params=()):
        if self._is_noop_pragma(sql):
            return _RemoteCursor(None)
        if self._tx is not None and _is_write_sql(sql):
            self._tx.append(_libsql.Statement(sql, list(params) if params else None))
            return _RemoteCursor(None)
        return _with_retry(
            lambda: _RemoteCursor(self._client.execute(sql, list(params) if params else None)),
            on_retry=self._reconnect)

    def executemany(self, sql: str, seq_of_params):
        stmts = [_libsql.Statement(sql, list(p)) for p in seq_of_params]
        if self._tx is not None:
            self._tx.extend(stmts)
            return _RemoteCursor(None)
        if stmts:
            _with_retry(lambda: self._client.batch(stmts),
                        on_retry=self._reconnect)
        return _RemoteCursor(None)

    def executescript(self, script: str):
        for s in script.split(";"):
            s = s.strip()
            if s:
                self.execute(s)

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


def _ensure_parent_dir(path: str) -> None:
    """Create the file's parent dir before open (turso.connect raises
    ``open: NotFound`` otherwise). keep-in-sync with Neuron/db.py."""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass


# ponytail: _turso_conn_cache stays permanent — pyturso 0.6.1 on Windows does NOT
# release the OS file lock on conn.close(), so "release and re-acquire" is
# impossible. The cache prevents multiple pyturso connections to the same file
# within one process (which would fail on the second open). Reads from other
# processes work fine (shared lock); only concurrent writes would fail, and
# neurag CLI routes writes through GM when it's active (_run_via_gm in cli.py).
_turso_conn_cache: dict[str, object] = {}


def _open_local_turso(path: str):
    """Open the local pyturso engine with a process-level connection cache.

    Uses a module-level cache so multiple KnowledgeGraph instances sharing the
    same DB path reuse one pyturso connection (pyturso acquires an exclusive
    lock — a second open to the same file fails). On cache miss, retries a few
    times then returns None so the caller logs an error.
    keep-in-sync with Neuron/db.py _open_local_engine.
    """
    # Cache hit: reuse existing connection
    cached = _turso_conn_cache.get(path)
    if cached is not None:
        try:
            cached.execute("SELECT 1")
            return cached
        except Exception:  # noqa: BLE001 — stale connection
            _turso_conn_cache.pop(path, None)

    # Try to open — transient errors (dir not ready) get a few retries
    import time as _t
    try:
        conn = turso_connect(path)
        _turso_conn_cache[path] = conn
        return conn
    except Exception:  # noqa: BLE001
        for attempt in range(2):
            _t.sleep(0.05 * (attempt + 1))
            _ensure_parent_dir(path)
            try:
                conn = turso_connect(path)
                _turso_conn_cache[path] = conn
                return conn
            except Exception:  # noqa: BLE001
                pass
    return None


# SSOT dei path: la posizione del vault vive in neurag/paths.py, non qui.
from neurag import paths as _paths
_DEFAULT_DB_DIR = _paths.data_dir()
_DEFAULT_DB = _paths.db_path()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    node_type   TEXT    NOT NULL CHECK(node_type IN ('godnode','fundamental','specialization')),
    parent_id   INTEGER REFERENCES nodes(id) ON DELETE CASCADE,
    path        TEXT    NOT NULL,   -- materialised path: /BackEndNotes/Java/SpringBoot
    tags        TEXT    DEFAULT '[]',  -- JSON array
    triggers    TEXT    DEFAULT '[]',  -- JSON array
    created_at  TEXT    DEFAULT (datetime('now'))
);

-- Absolute root (id=0, path='/', parent_id=NULL).
INSERT OR IGNORE INTO nodes (id, name, node_type, parent_id, path)
VALUES (0, '/', 'godnode', NULL, '/');

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    text        TEXT    NOT NULL,
    source      TEXT,       -- original file path
    section     TEXT,
    chunk_index INTEGER DEFAULT 0,
    embedding   BLOB,       -- 384-dim float32 vector (or NULL if not embedded)
    created_at  TEXT    DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_path   ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_chunks_node  ON chunks(node_id);

CREATE TABLE IF NOT EXISTS node_links (
    source_id   INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id   INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    link_type   TEXT    NOT NULL CHECK(link_type IN ('tag_overlap','cross_ref','semantic')),
    weight      REAL    DEFAULT 1.0,
    evidence    TEXT    DEFAULT '',
    created_at  TEXT    DEFAULT (datetime('now')),
    updated_at  TEXT    DEFAULT (datetime('now')),
    PRIMARY KEY (source_id, target_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_links_source ON node_links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON node_links(target_id);
"""


class _CompatRow:
    """Turso tuple wrapper: supports both r[0] and r['col'] like sqlite3.Row."""

    __slots__ = ('_cols', '_vals')

    def __init__(self, cols: list[str], vals: tuple):
        object.__setattr__(self, '_cols', cols)
        object.__setattr__(self, '_vals', vals)

    def __getitem__(self, key):
        if isinstance(key, str):
            idx = self._cols.index(key)
            return self._vals[idx]
        return self._vals[key]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def keys(self):
        return self._cols


class KnowledgeGraph:
    """Hierarchical knowledge graph with vector search.

    Uses Turso (libsql) via pyturso for local or remote (cloud) operation.
    """

    def __init__(self, db_path: Optional[Path] = None):
        # Lazy imports: fastembed (380MB) loads only on first KG instantiation,
        # not on `import neurag.db` — keeps MCP server startup fast. (audit 2026-07-22)
        from neurag.chunker import chunk_file, scan_directory
        from neurag.embedder import get_embedder
        from neurag.reranker import get_reranker
        self._chunk_file = chunk_file
        self._scan_directory = scan_directory
        self._db_path = db_path or _DEFAULT_DB
        # :memory: has no filesystem parent — skip mkdir (audit 2026-07-22)
        if str(self._db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        # Corruption is DATA, not a crash: a malformed knowledge.db must not blow
        # up __init__ (that killed EVERY command, not just health). Flag it here
        # and let status()/health() REPORT it with a recovery hint. (audit 2026-07-22)
        self._corrupt = False
        self._corrupt_err = ""
        self._connect()
        self._ensure_turso(db_path)
        self._init_schema()
        self._embedder = get_embedder()  # auto: fastembed if present, else null (lexical)
        self._reranker = get_reranker()  # OFF by default → NullReranker (zero cost)

    # -- connection ---------------------------------------------------------

    def _connect(self) -> None:
        db_str = str(self._db_path)
        # Tier order: cloud Turso (shared, multi-machine) -> local pyturso
        # (native vector_distance_cos). Reads from other processes work fine
        # via shared lock; writes route through GM (_run_via_gm in cli.py).
        if REMOTE_TURSO:
            self._conn = RemoteTursoConnection(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
            self._vector_sql = True
            self._engine_name = "Turso (cloud)"
            return  # remote: pragmas are no-ops, rows already name-accessible
        _ensure_parent_dir(db_str)
        conn = _open_local_turso(db_str) if TURSO_AVAILABLE else None
        if conn is not None:
            self._conn = conn
            self._vector_sql = True
            self._engine_name = "Turso (local)"
            def _row_factory(cursor, row):
                if cursor.description is None:
                    return row
                cols = [c[0] for c in cursor.description]
                return _CompatRow(cols, row)
            self._conn.row_factory = _row_factory
        else:
            # turso not importable (missing wheel) — log and let _ensure_turso fix it
            self._conn = None
            self._vector_sql = False
            self._engine_name = "Turso (pending)"
        # WAL + busy_timeout: letture concorrenti non bloccano lo scrittore e gli
        # scrittori si accodano invece di corrompersi (audit 2026-07-22). Su un
        # file già malformato anche la PRAGMA può sollevare → flag, non crash.
        if self._conn is not None:
            try:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA foreign_keys=ON")
            except Exception as e:  # noqa: BLE001 — DB corrotto/illeggibile
                self._corrupt = True
                self._corrupt_err = str(e)

    @staticmethod
    def _find_vendor_dir():
        """La cartella `vendor/` con le wheel pyturso, se localizzabile."""
        import importlib.util
        cands = []
        env = os.environ.get("NEURAG_VENDOR")
        if env:
            cands.append(Path(env))
        try:
            spec = importlib.util.find_spec("neurag")
            for loc in (spec.submodule_search_locations or []) if spec else []:
                cands.append(Path(loc) / "vendor")
                cands.append(Path(loc).parent / "vendor")
        except Exception:  # noqa: BLE001
            pass
        cands.append(Path(__file__).resolve().parent / "vendor")
        for c in cands:
            try:
                if c and c.is_dir():
                    return c
            except OSError:
                pass
        return None

    def _ensure_turso(self, db_path) -> None:
        """Turso PREFERITO sul vault reale, con fallback documentato.

        Richiesta 2026-07-22: "deve usare Turso senza se e senza ma" MA "senza
        dimenticare i fallback — prendere Turso dalle wheel, solo dopo X tentativi
        va in fallback documentando l'errore". Quindi: se sul vault di default
        (db_path None) NON siamo su Turso, si prova ad acquisirlo — import, e se
        manca `pip install` dalle wheel vendored — fino a NEURAG_TURSO_ATTEMPTS
        volte; solo allora si degrada a sqlite3 registrando gli errori (che
        `status`/`doctor` mostrano). Nessun crash. Non tocca i DB di test
        (db_path esplicito) né se sbloccato con NEURAG_REQUIRE_TURSO=0."""
        self._turso_degraded = False
        self._turso_errors: list[str] = []
        if db_path is not None:
            return
        require = os.environ.get("NEURAG_REQUIRE_TURSO", "1").strip().lower() \
            not in ("0", "false", "no", "off")
        if not require or getattr(self, "_vector_sql", False):
            return  # escape hatch, o già su Turso (cloud/pyturso locale)

        import importlib
        import subprocess
        import sys as _sys
        global TURSO_AVAILABLE, turso_connect
        attempts = max(1, int(os.environ.get("NEURAG_TURSO_ATTEMPTS", "3") or 3))
        autoinstall = os.environ.get("NEURAG_TURSO_AUTOINSTALL", "1").strip().lower() \
            not in ("0", "false", "no", "off")
        vendor = self._find_vendor_dir()

        for i in range(1, attempts + 1):
            got = False
            try:
                mod = importlib.import_module("turso")
                turso_connect = mod.connect
                TURSO_AVAILABLE = True
                got = True
            except Exception as e:  # noqa: BLE001 — non ancora installato
                self._turso_errors.append(f"tentativo {i}: import turso KO ({e!r})")
                if autoinstall:
                    cmd = [_sys.executable, "-m", "pip", "install", "pyturso==0.6.1"]
                    if vendor:
                        cmd[4:4] = ["--find-links", str(vendor)]
                    try:
                        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                           creationflags=(subprocess.CREATE_NO_WINDOW
                                                          if os.name == "nt" else 0))
                        if r.returncode != 0:
                            self._turso_errors.append(
                                f"tentativo {i}: pip install KO rc={r.returncode}: "
                                f"{(r.stderr or '').strip()[-200:]}")
                        else:
                            importlib.invalidate_caches()
                            try:
                                mod = importlib.import_module("turso")
                                turso_connect = mod.connect
                                TURSO_AVAILABLE = True
                                got = True
                            except Exception as e2:  # noqa: BLE001
                                self._turso_errors.append(
                                    f"tentativo {i}: import post-install KO ({e2!r})")
                    except Exception as pe:  # noqa: BLE001 — timeout/rete
                        self._turso_errors.append(f"tentativo {i}: pip errore ({pe!r})")
                else:
                    self._turso_errors.append(f"tentativo {i}: autoinstall disattivato")
            if got:
                # turso disponibile: riconnetti al tier locale (TURSO_AVAILABLE ora True)
                try:
                    if self._conn is not None:
                        self._conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self._conn = None
                self._connect()
                if getattr(self, "_vector_sql", False):
                    return  # riuscito → siamo su Turso
                self._turso_errors.append(
                    f"tentativo {i}: turso importato ma open locale fallito")

        # Esauriti i tentativi → fallback documentato su sqlite3.
        self._turso_degraded = True
        if self._conn is None:            # riapri una connessione sqlite valida
            self._connect()
        print("neurag: TURSO non ottenuto dopo %d tentativi — degrado a sqlite3. "
              "Dettagli: %s" % (attempts, " | ".join(self._turso_errors) or "n/d"),
              file=_sys.stderr)

    def _init_schema(self) -> None:
        try:
            for stmt in SCHEMA_SQL.split(";"):
                s = stmt.strip()
                if s:
                    self._conn.execute(s)
            self._conn.commit()
        except Exception as e:  # noqa: BLE001 — "file is not a database" & simili
            # DB malformato: non alziamo qui, così i comandi diagnostici
            # (status/health/doctor) possono girare e DIRLO invece di crashare.
            self._corrupt = True
            self._corrupt_err = str(e)

    def close(self) -> None:
        if self._conn:
            # Don't close cached pyturso connections — other KG instances may be using them
            if self._engine_name == "Turso (local)":
                self._conn = None  # release reference, keep connection alive in cache
            else:
                self._conn.close()
                self._conn = None

    # -- node CRUD ----------------------------------------------------------

    def add_node(self, name: str, node_type: str,
                 parent_id: Optional[int] = None,
                 tags: Optional[list[str]] = None,
                 triggers: Optional[list[str]] = None) -> int:
        # Default parent: root (id=0) for godnodes, require explicit parent otherwise
        if parent_id is None:
            if node_type == "godnode":
                parent_id = 0
            else:
                raise ValueError(f"{node_type} nodes require an explicit parent_id (godnode root)")
        parent_path = "/"
        row = self._conn.execute(
            "SELECT path FROM nodes WHERE id = ?", (parent_id,)
        ).fetchone()
        if row:
            parent_path = row["path"] if row["path"].endswith("/") else row["path"] + "/"
        path = f"{parent_path}{name}"

        cur = self._conn.execute(
            """INSERT INTO nodes (name, node_type, parent_id, path, tags, triggers)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, node_type, parent_id, path,
             json.dumps(tags or []), json.dumps(triggers or [])),
        )
        self._conn.commit()
        return cur.lastrowid

    def add_triggers(self, node_id: int, triggers: list[str]) -> None:
        """Merge extra triggers into a node (dedup, capped at 40).

        Auto-enriches a node from the symbol tags of the code chunked into it,
        so the Neuron→NeuRAG bridge can reach the node by concept without anyone
        hand-tagging it."""
        clean = [t for t in (triggers or []) if t]
        if not clean:
            return
        row = self._conn.execute(
            "SELECT triggers FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return
        try:
            current = json.loads(row["triggers"] or "[]")
        except (TypeError, ValueError):
            current = []
        merged = list(dict.fromkeys([*current, *clean]))[:40]
        self._conn.execute("UPDATE nodes SET triggers = ? WHERE id = ?",
                           (json.dumps(merged), node_id))
        self._conn.commit()

    def get_node(self, node_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_node_by_name(self, name: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_children(self, node_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY name",
            (node_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_node(self, node_id: int) -> int:
        """Delete a node and its whole subtree — EXPLICIT bottom-up deletes.

        pyturso 0.6.1 stack-overflows on FK cascade triggers even when
        children are already gone (audit 2026-07-20). We disable FK
        enforcement around the manual delete loop to avoid the C-level
        recursion. Funziona identico sul tier sqlite3.
        Ritorna quanti nodi sono stati rimossi (0 = id inesistente)."""
        start = self.get_node(node_id)
        if not start:
            return 0
        doomed = [d["id"] for d in reversed(self.get_descendants(node_id))]
        doomed.append(node_id)                     # la radice per ultima
        # ponytail: FK off for the loop, pyturso 0.6.1 C cascade bug.
        # try/finally so FK enforcement is ALWAYS restored, even if a DELETE
        # raises — otherwise the connection would silently keep FK disabled.
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            for nid in doomed:
                self._conn.execute("DELETE FROM chunks WHERE node_id = ?", (nid,))
                self._conn.execute(
                    "DELETE FROM node_links WHERE source_id = ? OR target_id = ?",
                    (nid, nid))
                self._conn.execute("DELETE FROM nodes WHERE id = ?", (nid,))
            self._conn.commit()
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")
        return len(doomed)

    def rename_node(self, node_id: int, new_name: str) -> None:
        """Rinomina un nodo aggiornando il suo path E i path dei discendenti.

        Il path è derivato dai nomi (add_node lo costruisce da parent.path +
        name): rinominare solo `name` lascerebbe l'albero incoerente. Qui il
        prefisso vecchio viene riscritto in un colpo su tutto il sottoalbero.
        """
        node = self.get_node(node_id)
        if not node:
            raise ValueError(f"nodo inesistente: {node_id}")
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("il nuovo nome è vuoto")
        old_path = node["path"]
        parent_prefix = old_path.rsplit("/", 1)[0]
        new_path = f"{parent_prefix}/{new_name}"
        self._conn.execute("UPDATE nodes SET name = ?, path = ? WHERE id = ?",
                           (new_name, new_path, node_id))
        # substr è 1-based: si tiene tutto ciò che segue il vecchio prefisso.
        self._conn.execute(
            "UPDATE nodes SET path = ? || substr(path, ?) WHERE path LIKE ?",
            (new_path, len(old_path) + 1, old_path + "/%"))
        self._conn.commit()

    def get_descendants(self, node_id: int) -> list[dict]:
        """Breadth-first descendants via path prefix."""
        row = self._conn.execute(
            "SELECT path FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return []
        base = row["path"]
        base = base + "/" if not base.endswith("/") else base
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE path LIKE ? ORDER BY path",
            (f"{base}%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def find_node_by_trigger(self, keyword: str) -> Optional[dict]:
        """Find a node whose triggers list contains the given keyword."""
        # SQLite JSON array search
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE triggers LIKE ?",
            (f'%"{"%s" % keyword}"%',)
        ).fetchall()
        if rows:
            return dict(rows[0])
        return None

    def node_tree(self, root_id: Optional[int] = None) -> str:
        """Pretty-print the hierarchy. Defaults to root (id=0)."""
        target_id = root_id if root_id is not None else 0
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (target_id,)
        ).fetchone()
        if not row:
            return "(empty)"
        lines = []
        self._print_node(dict(row), 0, lines)
        return "\n".join(lines)

    def _print_node(self, node: dict, depth: int, lines: list) -> None:
        prefix = "  " * depth
        tags_str = ", ".join(json.loads(node["tags"])) if node["tags"] != "[]" else ""
        lines.append(
            f"{prefix}{node['node_type']}: {node['name']}"
            f"{'  [' + tags_str + ']' if tags_str else ''}"
        )
        children = self.get_children(node["id"])
        for child in children:
            self._print_node(child, depth + 1, lines)

    # -- chunks -------------------------------------------------------------

    def add_chunk(self, node_id: int, text: str,
                  source: Optional[str] = None,
                  section: Optional[str] = None,
                  chunk_index: int = 0) -> int:
        vec = self._get_embedding(text)
        blob = self._pack_vec(vec) if vec else None
        cur = self._conn.execute(
            "INSERT INTO chunks (node_id, text, source, section, chunk_index, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (node_id, text, source, section, chunk_index, blob),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_chunks(self, node_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE node_id = ? ORDER BY chunk_index",
            (node_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def index_into_node(self, filepath: Path, node_id: int) -> int:
        """Chunk a file, add the chunks to a node, and enrich the node's triggers
        with the symbols found (the tags each code chunk carries)."""
        chunks = self._chunk_file(filepath)
        count = 0
        tag_pool: list[str] = []
        for c in chunks:
            self.add_chunk(
                node_id=node_id,
                text=c.text,
                source=c.source,
                section=c.section,
                chunk_index=c.chunk_index,
            )
            tag_pool += getattr(c, "tags", None) or []
            count += 1
        self.add_triggers(node_id, list(dict.fromkeys(tag_pool)))
        return count

    def index_directory_into_node(self, root: Path, node_id: int) -> int:
        total = 0
        for fp in self._scan_directory(root):
            total += self.index_into_node(fp, node_id)
        return total

    # -- node links ----------------------------------------------------------

    def upsert_link(self, source_id: int, target_id: int,
                    link_type: str, weight: float = 1.0,
                    evidence: str = "") -> None:
        """Insert or update a link between two nodes. Self-links are silently ignored."""
        if source_id == target_id:
            return
        self._conn.execute("""
            INSERT INTO node_links (source_id, target_id, link_type, weight, evidence, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source_id, target_id, link_type) DO UPDATE SET
                weight = excluded.weight,
                evidence = excluded.evidence,
                updated_at = datetime('now')
        """, (source_id, target_id, link_type, weight, evidence))
        self._conn.commit()

    def get_links(self, node_id: int, link_type: Optional[str] = None) -> list[dict]:
        """All links for a node (outgoing + incoming), with connected node info."""
        # Outgoing: node_id is source → "other" node is target
        sql = """
            SELECT nl.link_type, nl.weight, nl.evidence, nl.created_at, nl.updated_at,
                   nl.source_id, nl.target_id,
                   nl.target_id AS other_id,
                   t.name AS other_name, t.node_type AS other_type,
                   'out' AS direction
            FROM node_links nl
            JOIN nodes t ON t.id = nl.target_id
            WHERE nl.source_id = ?
        """
        params: list = [node_id]
        if link_type:
            sql += " AND nl.link_type = ?"
            params.append(link_type)

        # Incoming: node_id is target → "other" node is source
        sql += """
            UNION
            SELECT nl.link_type, nl.weight, nl.evidence, nl.created_at, nl.updated_at,
                   nl.source_id, nl.target_id,
                   nl.source_id AS other_id,
                   s.name AS other_name, s.node_type AS other_type,
                   'in' AS direction
            FROM node_links nl
            JOIN nodes s ON s.id = nl.source_id
            WHERE nl.target_id = ?
        """
        params.append(node_id)
        if link_type:
            sql += " AND nl.link_type = ?"
            params.append(link_type)

        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_neighbors(self, node_id: int, depth: int = 1, limit: int = 10) -> list[dict]:
        """D3 — structured neighborhood: BFS over parent, children and links up
        to ``depth`` hops. Returns [{name, path, node_type, relation, distance}]
        sorted by distance (closest first), self excluded, deduped. SQL-only:
        no embedding involved, so it is cheap enough for every pulse."""
        start = self.get_node(node_id)
        if not start:
            return []
        seen = {node_id}
        out: list[dict] = []
        frontier = [(start, 0)]
        for dist in range(1, max(1, min(depth, 3)) + 1):
            nxt: list[tuple[dict, int]] = []
            for node, _ in frontier:
                hops: list[tuple[dict, str]] = []
                if node.get("parent_id"):
                    parent = self.get_node(node["parent_id"])
                    if parent:
                        hops.append((parent, "parent"))
                hops += [(c, "child") for c in self.get_children(node["id"])]
                for lk in self.get_links(node["id"]):
                    other = self.get_node(lk["other_id"])
                    if other:
                        hops.append((other, f"link:{lk['link_type']}"))
                for other, relation in hops:
                    if other["id"] in seen:
                        continue
                    seen.add(other["id"])
                    out.append({"name": other["name"], "path": other.get("path"),
                                "node_type": other.get("node_type"),
                                "relation": relation, "distance": dist})
                    nxt.append((other, dist))
                    if len(out) >= limit:
                        return out
            frontier = nxt
            if not frontier:
                break
        return out

    def get_link_graph(self) -> list[dict]:
        """All links with source/target node info (for graph visualization)."""
        rows = self._conn.execute("""
            SELECT nl.*,
                   s.name AS source_name, s.node_type AS source_type,
                   t.name AS target_name, t.node_type AS target_type
            FROM node_links nl
            JOIN nodes s ON s.id = nl.source_id
            JOIN nodes t ON t.id = nl.target_id
            ORDER BY nl.weight DESC
        """).fetchall()
        return [dict(r) for r in rows]

    def link_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM node_links").fetchone()[0]

    def build_tag_links(self) -> int:
        """Create tag_overlap links between nodes sharing tags. Returns link count added."""
        # Single pass: build inverted index + tag cache
        index: dict[str, set[int]] = {}
        node_tags: dict[int, set[str]] = {}
        for row in self._conn.execute(
            "SELECT id, tags FROM nodes WHERE tags IS NOT NULL AND tags != '[]'"
        ).fetchall():
            tags = set(json.loads(row["tags"]))
            node_tags[row["id"]] = tags
            for tag in tags:
                index.setdefault(tag, set()).add(row["id"])

        added = 0
        seen: set[tuple[int,int]] = set()
        for tag, node_ids in index.items():
            ids = sorted(node_ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pair = (ids[i], ids[j])
                    if pair in seen:
                        continue
                    seen.add(pair)
                    tags_a = node_tags[ids[i]]
                    tags_b = node_tags[ids[j]]
                    shared = tags_a & tags_b
                    union = tags_a | tags_b
                    weight = len(shared) / len(union) if union else 0.0
                    evidence = ",".join(sorted(shared))
                    self.upsert_link(ids[i], ids[j], "tag_overlap", weight, evidence)
                    added += 1
        self._conn.commit()
        return added

    def build_crossref_links(self) -> int:
        """Create cross_ref links between nodes sharing the same source file. Returns count."""
        # Pre-fetch all chunk data in 2 queries
        source_nodes: dict[str, set[int]] = {}
        node_source_chunks: dict[tuple[int,str], int] = {}
        for row in self._conn.execute(
            "SELECT node_id, source, COUNT(*) AS cnt FROM chunks "
            "WHERE source IS NOT NULL AND source != '' GROUP BY node_id, source"
        ).fetchall():
            source_nodes.setdefault(row["source"], set()).add(row["node_id"])
            node_source_chunks[(row["node_id"], row["source"])] = row["cnt"]

        node_total_chunks: dict[int, int] = {}
        for row in self._conn.execute(
            "SELECT node_id, COUNT(*) AS cnt FROM chunks GROUP BY node_id"
        ).fetchall():
            node_total_chunks[row["node_id"]] = row["cnt"]

        added = 0
        seen: set[tuple[int,int]] = set()
        for source, node_ids in source_nodes.items():
            ids = sorted(node_ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pair = (ids[i], ids[j])
                    if pair in seen:
                        continue
                    seen.add(pair)
                    chunks_a = node_source_chunks.get((ids[i], source), 0)
                    chunks_b = node_source_chunks.get((ids[j], source), 0)
                    total_a = node_total_chunks.get(ids[i], 1)
                    total_b = node_total_chunks.get(ids[j], 1)
                    min_chunks = min(chunks_a, chunks_b)
                    max_total = max(total_a, total_b) or 1
                    weight = min_chunks / max_total
                    self.upsert_link(ids[i], ids[j], "cross_ref", weight, source)
                    added += 1
        self._conn.commit()
        return added

    def rebuild_links(self) -> dict:
        """Clear all links and rebuild from tags + cross-refs."""
        self._conn.execute("DELETE FROM node_links")
        self._conn.commit()
        tag_count = self.build_tag_links()
        xref_count = self.build_crossref_links()
        return {"tag_overlap": tag_count, "cross_ref": xref_count, "total": tag_count + xref_count}

    def search_with_links(self, query: str, top_k: int = 5) -> list[dict]:
        """Search, then enrich each result with links to other result nodes."""
        results = self.search(query, top_n=top_k)
        if len(results) < 2:
            return results

        result_node_ids = {r["node_id"] for r in results}
        # Collect all links between result nodes
        inter_links: list[dict] = []
        for r in results:
            for link in self.get_links(r["node_id"]):
                if link["other_id"] in result_node_ids and link["other_id"] != r["node_id"]:
                    inter_links.append({
                        "source_id": r["node_id"],
                        "target_id": link["other_id"],
                        "target_name": link["other_name"],
                        "link_type": link["link_type"],
                        "weight": link["weight"],
                        "evidence": link["evidence"],
                    })

        for r in results:
            r["links"] = [
                l for l in inter_links
                if l["source_id"] == r["node_id"] or l["target_id"] == r["node_id"]
            ]
        return results

    # -- search: semantic (embedder) or lexical (TF-IDF) --------------------

    def _get_embedding(self, text: str):
        """Embed via the active embedder. None when lexical-only (NullEmbedder)."""
        return self._embedder.embed(text)

    @staticmethod
    def _pack_vec(v: list[float]) -> bytes:
        return struct.pack(f"{len(v)}f", *v)

    @staticmethod
    def _unpack_vec(b: bytes) -> list[float]:
        return list(struct.unpack(f"{len(b) // 4}f", b))

    def _cosine_sim(self, a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        if not na or not nb:
            return 0.0
        return dot / (na * nb)

    def search(self, query: str, top_n: int = 5) -> list[dict]:
        """Rank chunks for a free-text query. Semantic when the embedder is on and
        embeddings exist, else lexical TF-IDF. Returns chunk rows, best first.

        Two stages: :meth:`_retrieve` fetches candidates cheaply (vector SQL /
        Python cosine / lexical), then — only if the reranker is enabled — a
        cross-encoder reorders a wider pool and keeps the true top-n. With the
        reranker OFF (default) the pool equals top_n and this is a no-op wrapper
        around the old behaviour."""
        rr = getattr(self, "_reranker", None)
        rerank_on = bool(rr is not None and getattr(rr, "available", False))
        pool = top_n
        if rerank_on:
            from neurag import settings as _st
            pool = max(top_n, int(_st.get("rerank_pool") or 50))
        results = self._retrieve(query, pool)
        if rerank_on and results:
            results = rr.rerank(query, results, top_n)
        return results[:top_n]

    def _retrieve(self, query: str, top_n: int = 5) -> list[dict]:
        """First-stage retrieval (no rerank).

        Fast path (Turso engine): ranking interamente in SQL con
        ``vector_distance_cos`` — niente full-scan dei blob in Python, scala
        con l'indice invece che con O(N) per query. Fallback trasparente al
        coseno Python (sqlite3 stdlib) o al lessicale (senza embedder)."""
        qv = self._get_embedding(query)
        if qv and getattr(self, "_vector_sql", False):
            try:
                rows = self._conn.execute(
                    "SELECT id, node_id, text, source, section, chunk_index, "
                    "1.0 - vector_distance_cos(f32blob(embedding), f32blob(?)) AS sim "
                    "FROM chunks WHERE embedding IS NOT NULL "
                    "ORDER BY sim DESC LIMIT ?",
                    (self._pack_vec(qv), top_n)).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except Exception:  # noqa: BLE001 — engine senza f32blob → path Python
                pass
        rows = [dict(r) for r in self._conn.execute("SELECT * FROM chunks").fetchall()]
        if not rows:
            return []
        embedded = [r for r in rows if r.get("embedding")]
        if qv and embedded:
            scored = [(self._cosine_sim(qv, self._unpack_vec(r["embedding"])), r) for r in embedded]
            scored.sort(key=lambda x: x[0], reverse=True)
            return [r for _, r in scored[:top_n]]
        return self._rank_lexical(query, rows, top_n)

    @staticmethod
    def _rank_lexical(query: str, rows: list[dict], top_n: int) -> list[dict]:
        # ponytail: TF-IDF lite — a real ranking, not substring; swap for BM25 if it bites.
        def toks(s: str) -> list[str]:
            return [t for t in re.findall(r"\w+", s.lower()) if len(t) > 1]
        q = set(toks(query))
        if not q:
            return rows[:top_n]
        doc_toks = [toks(r["text"]) for r in rows]
        n = len(rows)
        idf = {t: math.log(1 + n / (1 + sum(1 for dt in doc_toks if t in dt))) for t in q}
        scored = []
        for r, dt in zip(rows, doc_toks):
            score = sum(dt.count(t) * idf[t] for t in q)
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_n]] or rows[:top_n]

    # -- status -------------------------------------------------------------

    def status(self) -> dict:
        if getattr(self, "_corrupt", False):
            return {
                "engine": getattr(self, "_engine_name", "SQLite"),
                "embedder": getattr(getattr(self, "_embedder", None), "name", "?"),
                "reranker": getattr(getattr(self, "_reranker", None), "name", "null"),
                "db_path": str(self._db_path),
                "corrupt": True,
                "error": self._corrupt_err,
                "nodes": 0, "chunks": 0, "embedded": 0, "links": 0,
                "embedding_dim": 384,
                "hint": "knowledge.db corrotto — ripristina un backup o rifai "
                        "l'ingest (le fonti su disco sono intatte).",
            }
        node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        chunk_count = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        db_str = str(self._db_path)
        engine = getattr(self, "_engine_name", "Turso (local)")
        return {
            "engine": engine,
            "turso_errors": getattr(self, "_turso_errors", []),
            "embedder": self._embedder.name,
            "reranker": getattr(getattr(self, "_reranker", None), "name", "null"),
            "db_path": str(self._db_path),
            "nodes": node_count,
            "chunks": chunk_count,
            "embedded": embedded,
            "links": self.link_count(),
            "embedding_dim": 384,
        }

    # -- health: structural integrity (L1, deterministic) -------------------

    def health(self) -> dict:
        """Structural audit of the vault (no LLM, no embeddings). Flags problems;
        it never deletes — NeuRAG is a curated source of truth. `ok` is False only
        for the serious issues (broken hierarchy, tiny chunks, duplicate names)."""
        if getattr(self, "_corrupt", False):
            return {
                "ok": False,
                "corrupt": True,
                "serious_count": 1,
                "error": self._corrupt_err,
                "issues": {}, "warnings": {},
                "hint": "knowledge.db corrotto — ripristina un backup o rifai "
                        "l'ingest (le fonti su disco sono intatte).",
            }
        c = self._conn
        rows = lambda sql: [dict(r) for r in c.execute(sql).fetchall()]
        count = lambda sql: c.execute(sql).fetchone()[0]

        # Serious issues
        broken_hierarchy = rows(
            "SELECT n.id, n.name, n.parent_id FROM nodes n "
            "WHERE n.parent_id IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM nodes p WHERE p.id = n.parent_id)")
        tiny_chunks = rows(
            "SELECT id, node_id, source FROM chunks WHERE length(trim(text)) < 20")
        duplicate_node_names = rows(
            "SELECT name, COUNT(*) AS n FROM nodes WHERE id != 0 "
            "GROUP BY name HAVING n > 1")

        # Warnings (smells, not necessarily errors)
        orphan_nodes = rows(
            "SELECT n.id, n.name, n.path FROM nodes n WHERE n.id != 0 "
            "  AND NOT EXISTS (SELECT 1 FROM chunks ch WHERE ch.node_id = n.id) "
            "  AND NOT EXISTS (SELECT 1 FROM nodes k WHERE k.parent_id = n.id)")
        chunks_without_source = count(
            "SELECT COUNT(*) FROM chunks WHERE source IS NULL OR source = ''")
        nodes_without_triggers = count(
            "SELECT COUNT(*) FROM nodes WHERE id != 0 AND (triggers IS NULL OR triggers = '[]')")

        serious = len(broken_hierarchy) + len(tiny_chunks) + len(duplicate_node_names)
        return {
            "ok": serious == 0,
            "serious_count": serious,
            "issues": {
                "broken_hierarchy": broken_hierarchy,
                "tiny_or_empty_chunks": tiny_chunks,
                "duplicate_node_names": duplicate_node_names,
            },
            "warnings": {
                "orphan_nodes": orphan_nodes,
                "chunks_without_source": chunks_without_source,
                "nodes_without_triggers": nodes_without_triggers,
            },
        }
