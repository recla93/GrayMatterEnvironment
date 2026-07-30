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
        for s in _split_sql(script):
            self.execute(s)

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


def _without_vector(row: dict) -> dict:
    """Drop the stored vector from a row on its way out of the graph.

    It is ranking machinery, not content: MMR and the sqlite3 cosine fallback
    read it INSIDE db.py and nothing outside ever has. On the way out it is a
    384-float blob that `neurag query --json` serialised with `default=str`,
    so every result dragged a page of escaped bytes through the output a user
    actually reads. Stripped at the boundary rather than at each printer, so a
    future caller cannot leak it again."""
    row.pop("embedding", None)
    return row


def _scored(row: dict, score: float, stage: str) -> dict:
    """Stamp a result with the score of the stage that ranked it.

    Every row `search()` returns carries both keys. It used to carry `sim` only
    when it happened to come out of the vector leg — the BM25-only rows had no
    score at all and the fused RRF value was thrown away — so nothing could
    display or threshold a ranking it was handed.

    `score_from` is not decoration: the scales are not comparable (cosine in
    [0,1], RRF around 1/60, BM25 unbounded, a cross-encoder logit signed), so a
    bare float would be unreadable. Compare within one ranking, never across.
    """
    row["score"] = float(score)
    row["score_from"] = stage
    return row


def _split_sql(script: str) -> list[str]:
    """Split a SQL script into executable statements.

    Comments are stripped BEFORE the split. Neither pyturso nor the remote
    client has `executescript`, so we cut on ';' by hand — and a ';' inside a
    `--` comment truncated the statement that contained it, leaving the engine
    with "incomplete input" and the schema silently short a table. It cost the
    tag substrate one debugging round. Comments exist for whoever reads db.py,
    not for the engine, so dropping them costs nothing.

    ponytail: no string-literal awareness. Nothing in SCHEMA_SQL quotes a '--';
    if something ever does, this needs a real tokenizer, not a bigger regex.
    """
    return [s.strip() for s in re.sub(r"--[^\n]*", "", script).split(";") if s.strip()]


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


def _settings_get(key: str):
    """Read a persisted knob. Never fatal: a missing/unreadable config must not
    stop the vault from opening (same rule as embedder._setting)."""
    try:
        from neurag import settings
        return settings.get(key)
    except Exception:  # noqa: BLE001
        return None
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

-- Which embedding model produced the vectors in `chunks`. Stored NEXT TO the
-- vectors, not in config.json, because that is the only place that stays true:
-- a settings file can be edited, copied, or reset independently of the vault,
-- and then nothing knows the stored vectors are from a different space.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- The tag substrate (DESIGN-EVOLUTION §4). One atom had five representations
-- and no join key: chunk.tags, node.triggers, node.tags, Neuron keywords, GM
-- endpoint strings. Here a tag is a row, and `uses` (how many nodes carry it)
-- makes IDF suppression a lookup instead of a hand-maintained stop list.
-- `nodes.tags` / `nodes.triggers` stay as the legacy read path until the
-- migration has been verified on real vaults.
CREATE TABLE IF NOT EXISTS tags (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,   -- normalized: lowercase, trimmed
    uses      INTEGER DEFAULT 0,         -- document frequency, drives IDF suppression
    salience  REAL    DEFAULT 0.0,       -- Hebbian home (P5); unused in P1
    last_used TEXT
);
-- No FK on purpose: pyturso 0.6.1 stack-overflows on cascade triggers (see
-- delete_node), so every delete site cleans these rows explicitly instead.
CREATE TABLE IF NOT EXISTS node_tags  (node_id  INTEGER NOT NULL, tag_id INTEGER NOT NULL,
                                       PRIMARY KEY (node_id, tag_id));
CREATE TABLE IF NOT EXISTS chunk_tags (chunk_id INTEGER NOT NULL, tag_id INTEGER NOT NULL,
                                       PRIMARY KEY (chunk_id, tag_id));
CREATE INDEX IF NOT EXISTS idx_node_tags_tag  ON node_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_chunk_tags_tag ON chunk_tags(tag_id);
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
        # Chunk ceiling comes from the LIVE model's tokenizer, not a constant:
        # every model we ship truncates at 128 tokens, and a chunk past that is
        # silently unsearchable. `chunk_max_chars` overrides for a bigger model.
        from neurag.embedder import max_chars_for
        try:
            configured = int(_settings_get("chunk_max_chars") or 0)
        except (TypeError, ValueError):
            configured = 0
        self._max_chunk_chars = configured if configured > 0 else max_chars_for(self._embedder)

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
            for stmt in _split_sql(SCHEMA_SQL):
                self._conn.execute(stmt)
            self._conn.commit()
            self._migrate_tags()
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
        node_id = cur.lastrowid
        if tags:
            self._sync_node_tags(node_id, tags)
        return node_id

    def _merge_json_list(self, node_id: int, column: str,
                         values: list[str], cap: int) -> None:
        """Merge values into a node's JSON-array column (dedup, order-preserving).

        `column` is never user input — only the two literals below — so the
        f-string can't carry injection."""
        clean = [v for v in (values or []) if v]
        if not clean:
            return
        row = self._conn.execute(
            f"SELECT {column} FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return
        try:
            current = json.loads(row[column] or "[]")
        except (TypeError, ValueError):
            current = []
        merged = list(dict.fromkeys([*current, *clean]))[:cap]
        self._conn.execute(f"UPDATE nodes SET {column} = ? WHERE id = ?",
                           (json.dumps(merged), node_id))
        self._conn.commit()
        return merged

    # -- tag substrate (DESIGN-EVOLUTION §4) ---------------------------------

    @staticmethod
    def _norm_tag(name: str) -> str:
        """Normalization IS the join key: `Cache`, `cache ` and `CACHE` are one
        tag or the substrate buys nothing."""
        return (name or "").strip().lower()

    def _tag_id(self, name: str) -> "int | None":
        norm = self._norm_tag(name)
        if not norm:
            return None
        self._conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (norm,))
        row = self._conn.execute(
            "SELECT id FROM tags WHERE name = ?", (norm,)).fetchone()
        return row["id"] if row else None

    def _refresh_tag_uses(self, tag_ids) -> None:
        """`uses` is recomputed from node_tags, never incremented. IDF
        suppression reads this column, and a counter that drifts silently
        un-suppresses (or hides) tags with no way to notice."""
        for tid in set(tag_ids):
            self._conn.execute(
                "UPDATE tags SET uses = (SELECT COUNT(*) FROM node_tags WHERE tag_id = ?) "
                "WHERE id = ?", (tid, tid))

    def _sync_node_tags(self, node_id: int, names: list[str],
                        commit: bool = True) -> None:
        """Make node_tags mirror `names` exactly — removals included, so the
        relational side never drifts from the legacy column's 40-tag cap."""
        want = {t for t in (self._tag_id(n) for n in names or []) if t}
        have = {r["tag_id"] for r in self._conn.execute(
            "SELECT tag_id FROM node_tags WHERE node_id = ?", (node_id,)).fetchall()}
        for tid in want - have:
            self._conn.execute(
                "INSERT INTO node_tags (node_id, tag_id) VALUES (?, ?)", (node_id, tid))
        for tid in have - want:
            self._conn.execute(
                "DELETE FROM node_tags WHERE node_id = ? AND tag_id = ?", (node_id, tid))
        self._refresh_tag_uses(want ^ have)
        if commit:
            self._conn.commit()

    def _sync_chunk_tags(self, chunk_id: int, names: list[str],
                         commit: bool = True) -> None:
        """Chunks are replaced, never edited, so this side is insert-only."""
        for tid in {t for t in (self._tag_id(n) for n in names or []) if t}:
            self._conn.execute(
                "INSERT OR IGNORE INTO chunk_tags (chunk_id, tag_id) VALUES (?, ?)",
                (chunk_id, tid))
        if commit:
            self._conn.commit()

    def _migrate_tags(self) -> None:
        """Backfill node_tags from the legacy `nodes.tags` JSON column.

        Idempotent twice over: the meta flag skips the scan after the first
        run, and `_sync_node_tags` is a mirror operation anyway — running it
        again on unchanged data writes nothing. chunk_tags has no legacy source
        to backfill from; it fills on the next ingest."""
        if self._conn.execute(
                "SELECT 1 FROM meta WHERE key = 'tags_migrated'").fetchone():
            return
        for row in self._conn.execute(
                "SELECT id, tags FROM nodes WHERE tags IS NOT NULL AND tags != '[]'"
        ).fetchall():
            try:
                names = json.loads(row["tags"] or "[]")
            except (TypeError, ValueError):
                continue
            self._sync_node_tags(row["id"], names, commit=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('tags_migrated', '1')")
        self._conn.commit()

    def add_triggers(self, node_id: int, triggers: list[str]) -> None:
        """Merge extra triggers into a node (dedup, capped at 40).

        Auto-enriches a node from the symbol tags of the code chunked into it,
        so the Neuron→NeuRAG bridge can reach the node by concept without anyone
        hand-tagging it."""
        self._merge_json_list(node_id, "triggers", triggers, 40)

    def add_tags(self, node_id: int, tags: list[str]) -> None:
        """Merge tags into a node (dedup, capped at 40).

        Tags are what `build_tag_links` reads. Until this existed, `auto_ingest`
        wrote the chunker's symbols to `triggers` ONLY, so every auto-ingested
        node had `tags='[]'`, the linker's `WHERE tags != '[]'` matched nothing,
        and the whole graph came out with zero links — a silent no-op that the
        unit tests missed because they hand-set `tags=` on `add_node`.

        Writes both sides: the legacy JSON column (still the read path for
        `_print_node` and the GM bridge) and the `node_tags` rows the linker
        now uses. Syncing from the POST-cap merged list keeps the two in step."""
        merged = self._merge_json_list(node_id, "tags", tags, 40)
        if merged is not None:
            self._sync_node_tags(node_id, merged)

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
            freed: set[int] = set()
            for nid in doomed:
                freed |= {r["tag_id"] for r in self._conn.execute(
                    "SELECT tag_id FROM node_tags WHERE node_id = ?", (nid,)).fetchall()}
                self._conn.execute(
                    "DELETE FROM chunk_tags WHERE chunk_id IN "
                    "(SELECT id FROM chunks WHERE node_id = ?)", (nid,))
                self._conn.execute("DELETE FROM node_tags WHERE node_id = ?", (nid,))
                self._conn.execute("DELETE FROM chunks WHERE node_id = ?", (nid,))
                self._conn.execute(
                    "DELETE FROM node_links WHERE source_id = ? OR target_id = ?",
                    (nid, nid))
                self._conn.execute("DELETE FROM nodes WHERE id = ?", (nid,))
            self._refresh_tag_uses(freed)   # I5: the tag row survives, its count doesn't
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
                  chunk_index: int = 0,
                  tags: Optional[list[str]] = None) -> int:
        # Embed the breadcrumb WITH the body (encoding specificity): a paragraph
        # under "Install > Windows > venv" that only says "run the script" is
        # unreachable by "windows install" unless its location is in the vector.
        # Stored text stays pure — only the embedding input is enriched.
        vec = self._get_embedding(self._embed_input(text, section))
        blob = self._pack_vec(vec) if vec else None
        if blob is not None:
            self._record_embed_signature()   # claims an unclaimed vault only
        cur = self._conn.execute(
            "INSERT INTO chunks (node_id, text, source, section, chunk_index, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (node_id, text, source, section, chunk_index, blob),
        )
        self._conn.commit()
        if tags:
            self._sync_chunk_tags(cur.lastrowid, tags)
        return cur.lastrowid

    def get_chunks(self, node_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE node_id = ? ORDER BY chunk_index",
            (node_id,)
        ).fetchall()
        return [_without_vector(dict(r)) for r in rows]

    def index_into_node(self, filepath: Path, node_id: int) -> int:
        """Chunk a file, add the chunks to a node, and enrich the node's triggers
        with the symbols found (the tags each code chunk carries).

        Idempotent per source file: this file's previous chunks are replaced, not
        appended to. Without that, running `neurag ingest` twice DOUBLED every
        chunk (three times tripled them) — duplicates that are embedded, ranked,
        and counted into the tag/link graph. It also makes re-indexing free: a
        re-run picks up the current chunk ceiling and embedding model, which is
        the only way an existing vault gets the benefit of a settings change.

        Not a violation of "nothing is ever deleted": the same source's content
        is being REPLACED by its current version, not forgotten. Chunks whose
        file is gone from disk are never touched here."""
        source = str(filepath)
        # chunk_tags has no FK cascade (pyturso 0.6.1, see delete_node), so the
        # join rows go first or a re-ingest leaves them pointing at dead ids.
        self._conn.execute(
            "DELETE FROM chunk_tags WHERE chunk_id IN "
            "(SELECT id FROM chunks WHERE node_id = ? AND source = ?)",
            (node_id, source))
        self._conn.execute("DELETE FROM chunks WHERE node_id = ? AND source = ?",
                           (node_id, source))
        chunks = self._chunk_file(filepath, self._max_chunk_chars)
        count = 0
        tag_pool: list[str] = []
        for c in chunks:
            self.add_chunk(
                node_id=node_id,
                text=c.text,
                source=c.source,
                section=c.section,
                chunk_index=c.chunk_index,
                tags=getattr(c, "tags", None) or [],
            )
            tag_pool += getattr(c, "tags", None) or []
            count += 1
        symbols = list(dict.fromkeys(tag_pool))
        self.add_triggers(node_id, symbols)
        self.add_tags(node_id, symbols)   # tags drive build_tag_links; triggers drive lookup
        return count

    def index_directory_into_node(self, root: Path, node_id: int) -> int:
        total = 0
        for fp in self._scan_directory(root):
            total += self.index_into_node(fp, node_id)
        return total

    # -- node links ----------------------------------------------------------

    def upsert_link(self, source_id: int, target_id: int,
                    link_type: str, weight: float = 1.0,
                    evidence: str = "", commit: bool = True) -> None:
        """Insert or update a link between two nodes. Self-links are silently ignored.

        `commit=False` lets a bulk builder write thousands of links in one
        transaction instead of one fsync per row."""
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
        if commit:
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

    # Jaccard floor for a tag_overlap link. From DESIGN-CROSSLINKS.md §2, which
    # specified it and shipped without it: one shared tag out of forty is not a
    # relationship, and linking every such pair is how a few hundred nodes turn
    # into six figures of meaningless edges.
    MIN_TAG_JACCARD = 0.15

    # IDF suppression, the tag-side twin of MAX_CUE_DOC_RATIO below. A tag on
    # half the vault pairs almost every node with almost every other while
    # identifying none of them — a cue that predicts everything predicts
    # nothing. Skipping its posting list is also what takes the O(n²) sting out
    # of the pair loop; the tag still counts in the Jaccard denominators, so
    # this changes which pairs are CONSIDERED, never how similar they are.
    MAX_TAG_NODE_RATIO = 0.5
    # Same caveat as MIN_CUE_DOC_FLOOR: a ratio is meaningless on a small vault.
    MIN_TAG_NODE_FLOOR = 50

    def build_tag_links(self, min_jaccard: "float | None" = None) -> int:
        """Create tag_overlap links between nodes sharing tags. Returns link count added.

        Reads the `node_tags` substrate, not the legacy JSON column: an index
        lookup instead of parsing every node's tag array on every rebuild."""
        floor = self.MIN_TAG_JACCARD if min_jaccard is None else min_jaccard
        # Single pass: inverted index + per-node tag sets, on tag ids
        index: dict[int, set[int]] = {}
        node_tags: dict[int, set[int]] = {}
        tag_names: dict[int, str] = {}
        for row in self._conn.execute(
            "SELECT nt.node_id AS node_id, nt.tag_id AS tag_id, t.name AS name "
            "FROM node_tags nt JOIN tags t ON t.id = nt.tag_id"
        ).fetchall():
            index.setdefault(row["tag_id"], set()).add(row["node_id"])
            node_tags.setdefault(row["node_id"], set()).add(row["tag_id"])
            tag_names[row["tag_id"]] = row["name"]

        cap = max(self.MIN_TAG_NODE_FLOOR,
                  int(len(node_tags) * self.MAX_TAG_NODE_RATIO))

        added = 0
        seen: set[tuple[int,int]] = set()
        for tag, node_ids in index.items():
            if len(node_ids) > cap:
                continue                    # too common to identify anything
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
                    if weight < floor:
                        continue
                    evidence = ",".join(sorted(tag_names[t] for t in shared))
                    self.upsert_link(ids[i], ids[j], "tag_overlap", weight,
                                     evidence, commit=False)
                    added += 1
        self._conn.commit()
        return added

    MIN_CROSSREF_MENTIONS = 2   # one passing mention is a coincidence, not a reference

    # A cue occurring in more than this share of the corpus carries no
    # information about WHICH node is meant. Measured on a real tree: nodes are
    # named after folders, so `cache`, `ast`, `docs`, `tests`, `hooks` became
    # cues and matched every chunk containing that ordinary English word —
    # `cache` linked to six nodes at weight 1.0, `graphify-out -> ast` claimed
    # "mentioned in 3996 chunks". A cue that predicts everything predicts
    # nothing; this is IDF suppression with the threshold made explicit.
    MAX_CUE_DOC_RATIO = 0.10
    # ...but a ratio is meaningless on a small vault: at 3 chunks, 10% rounds to
    # 0 and suppresses every real cue. Below this many documents, suppress
    # nothing — a corpus this size has no "too common" term.
    MIN_CUE_DOC_FLOOR = 50

    def build_crossref_links(self, min_mentions: "int | None" = None) -> int:
        """Create cross_ref links where one node's chunks MENTION another node.

        This is the algorithm `DESIGN-CROSSLINKS.md` §3 specified. What shipped
        instead linked nodes that share a source *file* — and since
        `index_into_node` files every chunk of a file into exactly ONE node, each
        source mapped to one node, the pair loop never executed, and the function
        returned 0 for every auto-ingested vault. A real cross-reference is "A
        talks about B", which is what this measures.
        """
        floor = self.MIN_CROSSREF_MENTIONS if min_mentions is None else min_mentions

        # Trigger index. Single tokens are matched against a tokenised chunk (so
        # "int" can't match inside "print"); names with separators need substring.
        word_index: dict[str, set[int]] = {}
        phrases: list[tuple[str, int]] = []
        for row in self._conn.execute(
                "SELECT id, name, triggers FROM nodes WHERE id != 0").fetchall():
            try:
                cues = json.loads(row["triggers"] or "[]")
            except (TypeError, ValueError):
                cues = []
            for cue in [*cues, row["name"]]:
                cue = (cue or "").strip().lower()
                if len(cue) < 3:
                    continue
                if re.fullmatch(r"\w+", cue):
                    word_index.setdefault(cue, set()).add(row["id"])
                else:
                    phrases.append((cue, row["id"]))

        if not word_index and not phrases:
            return 0

        node_total_chunks: dict[int, int] = {}
        for row in self._conn.execute(
                "SELECT node_id, COUNT(*) AS cnt FROM chunks GROUP BY node_id").fetchall():
            node_total_chunks[row["node_id"]] = row["cnt"]

        # Pass 1 — keep only the cues each chunk actually contains, and count in
        # how many chunks every cue occurs (document frequency).
        per_chunk: list[tuple[int, set[str]]] = []
        doc_freq: dict[str, int] = {}
        for row in self._conn.execute("SELECT node_id, text FROM chunks").fetchall():
            text = (row["text"] or "").lower()
            found = {t for t in re.findall(r"\w+", text) if t in word_index}
            found |= {p for p, _ in phrases if p in text}
            per_chunk.append((row["node_id"], found))
            for cue in found:
                doc_freq[cue] = doc_freq.get(cue, 0) + 1

        # Pass 2 — drop the uninformative cues, then count real mentions.
        total_chunks = len(per_chunk) or 1
        cap = max(self.MIN_CUE_DOC_FLOOR, int(total_chunks * self.MAX_CUE_DOC_RATIO))
        cue_targets: dict[str, set[int]] = dict(word_index)
        for phrase, tgt in phrases:
            cue_targets.setdefault(phrase, set()).add(tgt)

        mentions: dict[tuple[int, int], int] = {}
        for src, found in per_chunk:
            hit: set[int] = set()
            for cue in found:
                if doc_freq.get(cue, 0) > cap:
                    continue                    # too common to identify anything
                hit |= cue_targets.get(cue, set())
            for tgt in hit:
                if tgt != src:
                    mentions[(src, tgt)] = mentions.get((src, tgt), 0) + 1

        added = 0
        for (src, tgt), count in mentions.items():
            if count < floor:
                continue
            weight = min(1.0, count / max(node_total_chunks.get(src, 1), 1))
            self.upsert_link(src, tgt, "cross_ref", weight,
                             f"mentioned in {count} chunk(s)", commit=False)
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

    # -- embedding provenance: which model built the vectors in this vault ----

    @staticmethod
    def _embed_input(text: str, section: "str | None") -> str:
        """What actually gets embedded. One definition so `add_chunk` and
        `reindex` cannot drift into embedding different strings for the same
        chunk — which would silently split the vault across two vector spaces."""
        return f"{section}\n\n{text}" if section else text

    def meta_get(self, key: str) -> "str | None":
        try:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?",
                                     (key,)).fetchone()
        except Exception:  # noqa: BLE001 — pre-meta vault, or corrupt
            return None
        return row[0] if row else None

    def meta_set(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
        self._conn.commit()

    def active_embed_signature(self) -> "tuple[str, int]":
        e = self._embedder
        return (getattr(e, "model_name", "") or e.name, int(getattr(e, "dim", 0) or 0))

    def stored_embed_signature(self) -> "tuple[str, int] | None":
        model = self.meta_get("embed_model")
        if model is None:
            return None
        try:
            return (model, int(self.meta_get("embed_dim") or 0))
        except (TypeError, ValueError):
            return (model, 0)

    def _record_embed_signature(self, force: bool = False) -> None:
        """Claim the vault for the active model — only if unclaimed, so an
        existing mismatch stays visible instead of being overwritten by the
        first new chunk."""
        if force or self.stored_embed_signature() is None:
            model, dim = self.active_embed_signature()
            self.meta_set("embed_model", model)
            self.meta_set("embed_dim", dim)

    def embed_mismatch(self) -> "dict | None":
        """Non-None when the vault's vectors came from a different model.

        Vectors from two models are not comparable — cosine between them is
        noise, not a weak match — so this has to be detected at OPEN, loudly,
        rather than quietly producing bad rankings forever. It is never fatal:
        the vault still opens and still answers (I5)."""
        stored = self.stored_embed_signature()
        if stored is None:
            return None
        if not getattr(self._embedder, "available", False):
            return None                      # lexical mode ignores vectors anyway
        active = self.active_embed_signature()
        if stored == active:
            return None
        try:
            embedded = self._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        except Exception:  # noqa: BLE001
            embedded = 0
        if not embedded:
            return None                      # nothing to be wrong about
        return {"stored_model": stored[0], "stored_dim": stored[1],
                "active_model": active[0], "active_dim": active[1],
                "embedded_chunks": embedded,
                "hint": "Vectors in this vault were built with a different model, "
                        "so semantic search is unreliable. Run `neurag reindex`."}

    def reindex(self, say=None) -> dict:
        """Re-embed every chunk with the ACTIVE model, in place.

        Only the vectors are rebuilt — chunk text, sections, nodes and links are
        untouched, and the source files are not needed. That is the right scope
        for a MODEL change. A change to the chunk ceiling is a different
        operation: re-run `neurag ingest`, which is idempotent per source file
        and re-chunks from disk.
        """
        say = say or (lambda s: None)
        model, dim = self.active_embed_signature()
        if not getattr(self._embedder, "available", False):
            return {"ok": False, "reason": "lexical mode — no embedder to reindex with",
                    "model": model, "chunks": 0, "embedded": 0}

        rows = self._conn.execute(
            "SELECT id, text, section FROM chunks ORDER BY id").fetchall()
        # ASCII only: a Windows console on the legacy cp1252 codepage raises
        # UnicodeEncodeError on a bare "->" arrow and takes the whole reindex
        # down with it. Same rule the .cmd launchers already follow.
        say(f"[reindex] {len(rows)} chunk(s) -> {model} (dim {dim})")
        done = failed = 0
        for i, r in enumerate(rows, 1):
            try:
                vec = self._get_embedding(self._embed_input(r["text"], r["section"]))
                self._conn.execute("UPDATE chunks SET embedding = ? WHERE id = ?",
                                   (self._pack_vec(vec) if vec else None, r["id"]))
                done += 1
            except Exception as exc:  # noqa: BLE001 — one bad chunk must not abort
                failed += 1
                say(f"  [!] chunk {r['id']}: {exc}")
            if i % 200 == 0:
                self._conn.commit()
                say(f"  {i}/{len(rows)}")
        self._conn.commit()
        self._record_embed_signature(force=True)
        say(f"[ok] re-embedded {done}, failed {failed}")
        return {"ok": failed == 0, "model": model, "dim": dim,
                "chunks": len(rows), "embedded": done, "failed": failed}

    def _get_embedding(self, text: str):
        """Embed a DOCUMENT. None when lexical-only (NullEmbedder)."""
        return self._embedder.embed(text)

    def _get_query_embedding(self, text: str):
        """Embed a QUERY — e5 needs `query: ` where documents need `passage: `."""
        fn = getattr(self._embedder, "embed_query", None)
        return fn(text) if fn else self._embedder.embed(text)

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

    # Reciprocal Rank Fusion constant. 60 is the value from the original RRF
    # paper and is not sensitive — it only damps the head of each ranking.
    RRF_K = 60
    MMR_LAMBDA = 0.7        # 1.0 = pure relevance, 0.0 = pure diversity

    def search(self, query: str, top_n: int = 5, node_id: "int | None" = None,
               diversify: bool = True) -> list[dict]:
        """Rank chunks for a free-text query, best first.

        Hybrid by default. It used to be either/or — vector if embeddings
        existed, lexical ONLY as a fallback when they did not — which meant the
        lexical ranker was dead code on every real install. That is backwards
        for a corpus of code and technical docs: dense vectors are weakest
        exactly where precision matters most (identifiers, flags, error
        strings — `vector_distance_cos`, `WinError 5`, `--client`), and lexical
        is blind to paraphrase and to cross-language matches, which an IT+EN
        vault needs constantly. Both retrievers already existed here; they had
        simply never run together.

        `node_id` scopes the search to a subtree — the hierarchy finally
        contributing to retrieval rather than only to browsing.

        Every result carries `score` and `score_from` (`cosine` | `bm25` |
        `rrf` | `cross-encoder`) — the number and the scale of the stage that
        ranked it. Diversification reorders without rescoring, so with
        `diversify=True` the order is deliberately not the score order.
        """
        rr = getattr(self, "_reranker", None)
        rerank_on = bool(rr is not None and getattr(rr, "available", False))
        from neurag import settings as _st
        pool = max(top_n * 4, int(_st.get("rerank_pool") or 50)) if rerank_on \
            else max(top_n * 4, 20)

        results = self._retrieve(query, pool, node_id=node_id)
        if rerank_on and results:
            results = rr.rerank(query, results, max(top_n * 2, top_n))
        if diversify and len(results) > top_n:
            results = self._mmr(query, results, top_n)
        return [_without_vector(r) for r in results[:top_n]]

    def _scope_ids(self, node_id: "int | None") -> "list[int] | None":
        """The node and its whole subtree, or None for "the entire vault"."""
        if node_id is None:
            return None
        ids = [node_id] + [d["id"] for d in self.get_descendants(node_id)]
        return ids or [node_id]

    def _mmr(self, query: str, rows: list[dict], top_n: int) -> list[dict]:
        """Maximal Marginal Relevance — trade a little relevance for coverage.

        Without it the top-n is routinely five near-identical chunks from one
        file, which wastes the model's context on one restated point. Same
        lambda as Neuron's ADR-008 §5.6, so the two behave alike.

        Reorders only — it never rescores, so `score` keeps meaning "how the
        ranking stage rated this row", not "why it sits here". Overwriting it
        with the MMR objective would be worse: that number is relative to the
        rows already chosen and says nothing on its own."""
        vecs, pool = [], []
        for r in rows:
            blob = r.get("embedding")
            if blob:
                vecs.append(self._unpack_vec(blob))
                pool.append(r)
        if len(pool) <= top_n or not vecs:
            return rows
        chosen: list[int] = [0]                      # rows are already ranked
        while len(chosen) < top_n and len(chosen) < len(pool):
            best, best_score = None, None
            for i in range(len(pool)):
                if i in chosen:
                    continue
                relevance = 1.0 - (i / len(pool))    # rank-based, cheap
                redundancy = max(self._cosine_sim(vecs[i], vecs[j]) for j in chosen)
                score = self.MMR_LAMBDA * relevance - (1 - self.MMR_LAMBDA) * redundancy
                if best_score is None or score > best_score:
                    best, best_score = i, score
            if best is None:
                break
            chosen.append(best)
        picked = [pool[i] for i in chosen]
        # Anything without a vector keeps its original order behind the picks.
        return picked + [r for r in rows if r not in picked]

    def _vector_candidates(self, qv, top_n: int,
                           scope: "list[int] | None") -> list[dict]:
        """Vector ranking. Turso does it in SQL (`vector_distance_cos`), which is
        why pyturso is the default tier; sqlite3 falls back to Python cosine."""
        if not qv:
            return []
        where = "embedding IS NOT NULL"
        params: list = [self._pack_vec(qv)]
        if scope:
            where += f" AND node_id IN ({','.join('?' * len(scope))})"
        if getattr(self, "_vector_sql", False):
            try:
                sql = ("SELECT id, node_id, text, source, section, chunk_index, embedding, "
                       "1.0 - vector_distance_cos(f32blob(embedding), f32blob(?)) AS score "
                       f"FROM chunks WHERE {where} ORDER BY score DESC LIMIT ?")
                rows = self._conn.execute(
                    sql, (*params, *(scope or []), top_n)).fetchall()
                if rows:
                    return [_scored(d, d["score"], "cosine")
                            for d in (dict(r) for r in rows)]
            except Exception:  # noqa: BLE001 — engine senza f32blob → path Python
                pass
        # ponytail: O(N) blob scan + Python cosine. Only the sqlite3 tier lands
        # here; on Turso the SQL path above is used. Fine to ~10k chunks.
        sql = f"SELECT * FROM chunks WHERE {where.replace(' AND node_id', ' AND node_id')}"
        rows = [dict(r) for r in self._conn.execute(sql, tuple(scope or [])).fetchall()]
        scored = [(self._cosine_sim(qv, self._unpack_vec(r["embedding"])), r) for r in rows]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [_scored(r, sim, "cosine") for sim, r in scored[:top_n]]

    def _lexical_candidates(self, query: str, top_n: int,
                            scope: "list[int] | None") -> list[dict]:
        sql = "SELECT * FROM chunks"
        params: tuple = ()
        if scope:
            sql += f" WHERE node_id IN ({','.join('?' * len(scope))})"
            params = tuple(scope)
        rows = [dict(r) for r in self._conn.execute(sql, params).fetchall()]
        return self._rank_lexical(query, rows, top_n) if rows else []

    def _retrieve(self, query: str, top_n: int = 5,
                  node_id: "int | None" = None) -> list[dict]:
        """First-stage retrieval: vector AND lexical, fused with RRF.

        Reciprocal Rank Fusion needs no score calibration — it combines the two
        RANKINGS, so a cosine in [0,1] and an unbounded BM25 score can be merged
        without normalising either. That is what makes running both cheap enough
        to always do."""
        scope = self._scope_ids(node_id)
        qv = self._get_query_embedding(query)
        vector = self._vector_candidates(qv, top_n, scope)
        lexical = self._lexical_candidates(query, top_n, scope)

        if not vector:
            return lexical[:top_n]
        if not lexical:
            return vector[:top_n]

        fused: dict[int, float] = {}
        rows_by_id: dict[int, dict] = {}
        for ranking in (vector, lexical):
            for rank, row in enumerate(ranking):
                cid = row["id"]
                rows_by_id.setdefault(cid, row)
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (self.RRF_K + rank + 1)
        order = sorted(fused, key=lambda c: fused[c], reverse=True)
        # The fused score REPLACES the leg's own: a row that surfaced from the
        # vector leg used to keep its cosine while a BM25-only neighbour had no
        # score at all, so the caller saw a ranking it could not read.
        return [_scored(rows_by_id[c], fused[c], "rrf") for c in order[:top_n]]

    # BM25 constants. k1 damps term-frequency saturation, b controls how much
    # document length is penalised. 1.5/0.75 are the standard defaults.
    BM25_K1 = 1.5
    BM25_B = 0.75

    @classmethod
    def _rank_lexical(cls, query: str, rows: list[dict], top_n: int) -> list[dict]:
        """BM25. Was TF-IDF WITHOUT length normalisation (`count * idf`, summed),
        so a long chunk beat a precise short one on raw term count alone — and
        chunk lengths were wildly unequal until the size ceiling landed. BM25 is
        the same shape plus the two constants that fix exactly that."""
        def toks(s: str) -> list[str]:
            return [t for t in re.findall(r"\w+", s.lower()) if len(t) > 1]

        q = set(toks(query))
        if not q:
            return [_scored(r, 0.0, "bm25") for r in rows[:top_n]]
        doc_toks = [toks(r["text"]) for r in rows]
        n = len(rows)
        avgdl = (sum(len(dt) for dt in doc_toks) / n) if n else 0.0
        df = {t: sum(1 for dt in doc_toks if t in dt) for t in q}
        # BM25 probabilistic idf, floored at 0 so a term in >half the corpus
        # cannot subtract score.
        idf = {t: max(0.0, math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))) for t in q}

        scored = []
        for r, dt in zip(rows, doc_toks):
            dl = len(dt) or 1
            score = 0.0
            for t in q:
                f = dt.count(t)
                if not f:
                    continue
                denom = f + cls.BM25_K1 * (1 - cls.BM25_B + cls.BM25_B * dl / (avgdl or dl))
                score += idf[t] * (f * (cls.BM25_K1 + 1)) / denom
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return ([_scored(r, s, "bm25") for s, r in scored[:top_n]]
                or [_scored(r, 0.0, "bm25") for r in rows[:top_n]])

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
        out = {
            "engine": engine,
            "turso_errors": getattr(self, "_turso_errors", []),
            "embedder": self._embedder.name,
            "reranker": getattr(getattr(self, "_reranker", None), "name", "null"),
            "db_path": str(self._db_path),
            "nodes": node_count,
            "chunks": chunk_count,
            "embedded": embedded,
            "links": self.link_count(),
            # Was hardcoded 384 — wrong the moment the installer let anyone pick
            # mpnet (768) or e5-large (1024), and this is the number the GUI and
            # `neurag status` show.
            "embedding_dim": getattr(self._embedder, "dim", 384),
            "max_chunk_chars": getattr(self, "_max_chunk_chars", 0),
        }
        # Lexical-only is a legitimate ANSWER but a terrible accident. Say which
        # one this is: a standalone NeuRAG used to land here silently, because
        # fastembed was an optional extra no installer ever requested.
        if not getattr(self._embedder, "available", False):
            from neurag.embedder import lexical_only_requested
            if lexical_only_requested():
                out["search_mode"] = "lexical (requested)"
            else:
                out["search_mode"] = "lexical (DEGRADED)"
                out["warning"] = (
                    "An embedding model is configured but the embedder did not "
                    "load, so search is lexical only — cross-language and "
                    "paraphrase matches will fail. Fix: pip install "
                    "'fastembed>=0.5,<1', then `neurag reindex`.")
        else:
            out["search_mode"] = "semantic"
        mismatch = self.embed_mismatch()
        if mismatch:
            out["embed_mismatch"] = mismatch
            out["warning"] = mismatch["hint"]
        return out

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
