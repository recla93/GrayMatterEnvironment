"""Cross-store bridges — the orchestrator's own memory, that *learns from use*.

A bridge is a persisted link between a Neuron concept and a NeuRAG knowledge
node: a connection only Gray-Matter (sitting between the two stores) can see.
Persisted so a connection is *discovered once* and *recalled cheaply* forever.

Auto-learning (B4): a bridge carries a `weight`. It grows every time the bridge
re-emerges or is surfaced in a pulse (Hebbian: co-occurrence = reinforcement),
and `decay()` shrinks bridges that go unused. **Only bridges decay**; NeuRAG
knowledge is a permanent vault and is never touched here.

STORAGE: a small 3-tier table (was a JSON file), so bridges — GM's own learned
memory — sync across machines like the two stores do. Tier, identical to
Neuron/NeuRAG so the suite is coherent end to end:

1. **Turso cloud** — `GM_TURSO_DATABASE_URL` (+ token): GM's OWN DB
   (`gm_bridges`), NEVER Neuron's/NeuRAG's.
2. **Turso local** (pyturso) — same engine the peers use, so a store can move
   between local and cloud without changing SQL dialect.
3. **sqlite3** — base tier, and the L2 degrade when the local engine won't open.

Public API unchanged. A legacy `bridges.json` is migrated once. Path override:
GRAY_MATTER_BRIDGES. Moving data between tiers: :func:`transfer`.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

_WEIGHT_CAP = 1000          # weights are relative; cap keeps them bounded
_PROMOTE_AT = 5             # B4: a 5+ volte il concetto Neuron merita un confirm
_MAX_LEN = 200              # ingest guard: longer endpoints are pasted blobs, not concepts
_MIN_LEN = 2                # a 1-char endpoint substring-matches almost every topic -> noise

# --- Cloud tier (GM's OWN DB) — keep-in-sync with Neuron/NeuRAG RemoteTurso ----
# GM's bridges live in their own Turso DB (`gm_bridges`), never Neuron's/NeuRAG's.
# Token can be the shared group token: GM_TURSO_AUTH_TOKEN, else TURSO_AUTH_TOKEN.
def _sanitize_credential(value: str) -> str:
    """Toglie ogni whitespace/controllo, non solo agli estremi — keep-in-sync con
    Neuron/_env.py. Il token diventa un header HTTP e lo stack rifiuta un valore
    con CR/LF/NUL dentro (guardia anti header-injection): un a-capo nascosto da
    copia-incolla, o un .env CRLF, faceva fallire il cloud senza spiegazione."""
    return re.sub(r"[\s\x00-\x1f\x7f]", "", value or "")


TURSO_DATABASE_URL = _sanitize_credential(os.environ.get("GM_TURSO_DATABASE_URL", ""))
TURSO_AUTH_TOKEN = _sanitize_credential(os.environ.get("GM_TURSO_AUTH_TOKEN")
                                        or os.environ.get("TURSO_AUTH_TOKEN", ""))
REMOTE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

_libsql = None
if REMOTE_TURSO:
    try:
        import libsql_client as _libsql
    except ImportError:
        import sys as _sys
        print("gray-matter: GM_TURSO_DATABASE_URL is set but the 'cloud' extra "
              "(libsql-client) is not installed — bridges stay on the local "
              "engine. Enable cloud with: pip install \"gray-matter[cloud]\"",
              file=_sys.stderr)
        REMOTE_TURSO = False

_REMOTE_NOOP_PRAGMAS = ("journal_mode", "synchronous", "foreign_keys")

# --- Local tier: same pyturso engine as Neuron/NeuRAG (coherence) ------------
try:
    import turso as _local_turso
    LOCAL_TURSO_ENGINE = True
except ImportError:                      # nessuna wheel per questo ABI
    _local_turso = None
    LOCAL_TURSO_ENGINE = False

ENGINE_NAME = ("Turso (cloud)" if REMOTE_TURSO
               else "Turso (local)" if LOCAL_TURSO_ENGINE else "SQLite")


class _Row:
    """tuple wrapper: supports r[0] and r['col'] like sqlite3.Row (for remote)."""
    __slots__ = ("_c", "_v")

    def __init__(self, cols, vals):
        self._c, self._v = cols, vals

    def __getitem__(self, k):
        return self._v[self._c.index(k)] if isinstance(k, str) else self._v[k]

    def keys(self):
        return self._c


class _RemoteCursor:
    def __init__(self, result=None, buffered: bool = False):
        self._r = result
        self._buffered = buffered

    @property
    def description(self):
        if self._r is None:
            return None
        return [(c,) for c in self._r.columns]

    def fetchall(self):
        if self._r is None:
            return []
        cols = list(self._r.columns)
        return [_Row(cols, tuple(row)) for row in self._r.rows]

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


_WRITE_PREFIXES = ("insert", "update", "delete", "replace", "create", "alter", "drop")


def _is_write_sql(sql: str) -> bool:
    head = sql.lstrip()
    if not head:
        return False
    return head.split(None, 1)[0].lower() in _WRITE_PREFIXES


def _with_retry(fn, *, attempts: int = 4, base_delay: float = 0.4,
                on_retry=None):
    """Run *fn* with exponential backoff on transient remote failures.

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


class _RemoteConn:
    """sqlite3-compatible facade over a remote Turso (libSQL cloud) DB.

    Retry + URL fallback + transaction support, matching Neuron's
    RemoteTursoConnection pattern (keep-in-sync).
    """

    def __init__(self, url: str, token: str):
        self._auth_token = token
        self._urls = _url_candidates(url)
        self._url_idx = 0
        self._client = self._create_client()
        self._tx: list | None = None  # buffered Statements while a tx is open

    def _create_client(self):
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

    def _is_noop_pragma(self, sql: str) -> bool:
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
            return _RemoteCursor(None, buffered=True)
        return _with_retry(
            lambda: _RemoteCursor(self._client.execute(sql, list(params) if params else None)),
            on_retry=self._reconnect)

    def executemany(self, sql: str, seq_of_params):
        stmts = [_libsql.Statement(sql, list(p)) for p in seq_of_params]
        if self._tx is not None:
            self._tx.extend(stmts)
            return _RemoteCursor(None, buffered=True)
        if stmts:
            _with_retry(lambda: self._client.batch(stmts),
                        on_retry=self._reconnect)
        return _RemoteCursor(None)

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass


def _clean(s, cap: int = _MAX_LEN) -> str:
    """Normalize a string entering the store: coerce, strip, collapse ws, cap (F4)."""
    if not isinstance(s, str):
        s = str(s or "")
    return " ".join(s.split())[:cap]


def _valid_endpoint(s: str) -> bool:
    return _MIN_LEN <= len(s) <= _MAX_LEN


def _tokens(s: str) -> list[str]:
    return re.findall(r"\w+", (s or "").lower())


def _token_run(needle: list[str], haystack: list[str]) -> bool:
    """True when `needle` appears in `haystack` as a CONTIGUOUS run of whole
    tokens — `["ast"]` matches "the ast walker" and not "fastembed"."""
    n = len(needle)
    if not n or n > len(haystack):
        return False
    return any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def _db_path() -> Path:
    """Local store path. GRAY_MATTER_BRIDGES override: a `.json` value is treated
    as legacy → we store in its `.db` sibling and migrate the json once."""
    p = os.environ.get("GRAY_MATTER_BRIDGES")
    if p:
        pp = Path(p)
        return pp if pp.suffix == ".db" else pp.with_suffix(".db")
    # SSOT: `paths.gm_bridges()` — the same path repair/uninstall target. The old
    # hardcoded ~/.local/share/gray_matter/bridges.db drifted from it, so the real
    # store was never offered for wipe nor removed at uninstall.
    from gray_matter import paths
    return paths.gm_bridges()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bridges (
  neuron_key TEXT NOT NULL,
  neurag_key TEXT NOT NULL,
  neuron     TEXT NOT NULL,
  neurag     TEXT NOT NULL,
  rationale  TEXT    DEFAULT '',
  weight     REAL    NOT NULL DEFAULT 1,
  created    REAL    NOT NULL,
  last_used  REAL    NOT NULL,
  promoted   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (neuron_key, neurag_key)
)
"""


def _open_local_turso(path: str):
    """Open the local pyturso engine, resilient to the L2 concurrent-open race.

    Retry a few times (re-ensuring the dir), then return None so the caller can
    degrade to sqlite3 on the SAME file instead of crashing — the libSQL/sqlite
    on-disk format is compatible. keep-in-sync with Neuron/db.py
    `_open_local_engine` and NeuRAG/db.py `_open_local_turso`.
    """
    last = None
    for attempt in range(3):
        try:
            return _local_turso.connect(path)
        except Exception as e:  # noqa: BLE001 — transient concurrent-open race
            last = e
            time.sleep(0.05 * (attempt + 1))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    import sys as _sys
    print(f"gray-matter: local Turso open failed ({last!r}) after retries — "
          f"degrading to sqlite3 (L2 guard).", file=_sys.stderr)
    return None


def _local_row_factory(cursor, row):
    """pyturso rows are tuples; bridges code reads them by name -> wrap in _Row."""
    if cursor.description is None:
        return row
    return _Row([c[0] for c in cursor.description], tuple(row))


def _connect():
    """Open the store, tiered: cloud Turso -> local Turso -> sqlite3. Fresh per
    call so concurrent processes never diverge on a stale in-RAM cache."""
    if REMOTE_TURSO:
        conn = _RemoteConn(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
        conn.execute(_SCHEMA)
        _maybe_migrate(conn)
        return conn
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open_local_turso(str(path)) if LOCAL_TURSO_ENGINE else None
    if conn is not None:
        conn.row_factory = _local_row_factory
    else:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    _maybe_migrate(conn)
    return conn


def _legacy_json() -> Path:
    ov = os.environ.get("GRAY_MATTER_BRIDGES", "")
    if ov.endswith(".json"):
        return Path(ov)
    return Path.home() / ".local" / "share" / "gray_matter" / "bridges.json"


def _maybe_migrate(conn) -> None:
    """Once: if the table is empty and a legacy bridges.json exists, import it."""
    try:
        if (conn.execute("SELECT COUNT(*) AS c FROM bridges").fetchone()["c"] or 0) > 0:
            return
    except Exception:
        return
    legacy = _legacy_json()
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except Exception:
        return
    for b in data if isinstance(data, list) else []:
        nc, nn = _clean(b.get("neuron", "")), _clean(b.get("neurag", ""))
        if not (_valid_endpoint(nc) and _valid_endpoint(nn)):
            continue
        now = time.time()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO bridges (neuron_key,neurag_key,neuron,neurag,"
                "rationale,weight,created,last_used,promoted) VALUES (?,?,?,?,?,?,?,?,?)",
                (nc.lower(), nn.lower(), nc, nn, _clean(b.get("rationale", ""), 500),
                 float(b.get("weight", 1) or 1), float(b.get("created", now) or now),
                 float(b.get("last_used", now) or now), 1 if b.get("promoted") else 0))
        except Exception:
            continue
    conn.commit()
    try:
        legacy.rename(legacy.with_suffix(".json.migrated"))
    except Exception:
        pass


def add_bridge(neuron_concept: str, neurag_node: str, rationale: str = "") -> bool:
    """Record a bridge. Idempotent on (neuron_concept, neurag_node): existing ->
    weight +1 and False; brand-new -> True. Ingest validation (F4) as before."""
    neuron_concept, neurag_node = _clean(neuron_concept), _clean(neurag_node)
    rationale = _clean(rationale, cap=500)
    if not (_valid_endpoint(neuron_concept) and _valid_endpoint(neurag_node)):
        return False
    if neuron_concept.lower() == neurag_node.lower():
        return False
    nk, gk = neuron_concept.lower(), neurag_node.lower()
    now = time.time()
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM bridges WHERE neuron_key=? AND neurag_key=?", (nk, gk)).fetchone()
        if exists is not None:
            # relative increment in SQL -> concurrent-safe (no stale read-modify-write)
            conn.execute(
                "UPDATE bridges SET weight=min(weight+1,?), last_used=?, "
                "rationale=CASE WHEN rationale IS NULL OR rationale='' THEN ? ELSE rationale END "
                "WHERE neuron_key=? AND neurag_key=?", (_WEIGHT_CAP, now, rationale, nk, gk))
            conn.commit()
            return False
        try:
            conn.execute(
                "INSERT INTO bridges (neuron_key,neurag_key,neuron,neurag,rationale,"
                "weight,created,last_used,promoted) VALUES (?,?,?,?,?,1,?,?,0)",
                (nk, gk, neuron_concept, neurag_node, rationale, now, now))
            conn.commit()
            return True
        except Exception:      # lost an insert race -> bump the winner instead
            conn.execute("UPDATE bridges SET weight=min(weight+1,?), last_used=? "
                         "WHERE neuron_key=? AND neurag_key=?", (_WEIGHT_CAP, now, nk, gk))
            conn.commit()
            return False
    finally:
        conn.close()


def bridges_for(topic: str, tags: "set[str] | None" = None,
                limit: "int | None" = None) -> list[dict]:
    """Bridges whose Neuron or NeuRAG endpoint matches the topic (either
    direction). Surfacing a bridge in a pulse *is* using it -> reinforce.
    Returned strongest-first; a just-crossed-threshold bridge is flagged
    `_just_promoted` (in-memory only, never persisted).

    Two ways to match, and neither is substring containment any more:

    * **whole-token runs.** The match used to be `endpoint in topic or topic in
      endpoint`, which is how an endpoint called `ast` matched "fastembed
      install" and `cache` matched "cached" — the same defect the crossref cue
      scan had before P0, on the same kind of short technical word. An endpoint
      now has to appear as a contiguous run of whole tokens.
    * **tag identity** (`tags`), which is the join DESIGN-EVOLUTION §4 asked
      for. The caller passes the NORMALIZED tag names NeuRAG resolved for this
      topic — from the `tags` table, the one object all three stores agree on —
      and an endpoint matches by being one of them. That reaches a bridge whose
      node NAME says nothing about the topic while its tags do, which no amount
      of string matching on the name could find.

    `tags` is passed in rather than looked up here on purpose: this runs in
    GM's pulse, and opening a NeuRAG vault (and its embedder) per pulse to
    resolve four words would be a poor trade. The caller already has the handle.

    `limit` caps how many are returned AND how many are reinforced — the two are
    the same thing, because surfacing is what counts as using.
    """
    t_tokens = _tokens(topic)
    if not t_tokens:
        return []
    tagset = {(x or "").strip().lower() for x in (tags or set())} - {""}
    now = time.time()
    conn = _connect()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM bridges").fetchall()]
        matched = []
        for b in rows:
            n_tok, r_tok = _tokens(b["neuron"]), _tokens(b["neurag"])
            hit = (_token_run(n_tok, t_tokens) or _token_run(r_tok, t_tokens)
                   or _token_run(t_tokens, n_tok) or _token_run(t_tokens, r_tok)
                   or b["neuron_key"] in tagset or b["neurag_key"] in tagset)
            if hit:
                matched.append(b)
        # Strongest first, THEN cut, THEN reinforce. Matching and reinforcing
        # used to be the same loop, so every match was strengthened whether the
        # caller showed it or not — and the docstring's own rule is that
        # SURFACING a bridge is what counts as using it. With tag identity one
        # shared tag can match dozens at once, which made that the difference
        # between a hint and a mass promotion.
        matched.sort(key=lambda b: b.get("weight", 1), reverse=True)
        out = matched if limit is None else matched[:max(0, int(limit))]
        for b in out:
            just = (min(b["weight"] + 1, _WEIGHT_CAP) >= _PROMOTE_AT) and not b["promoted"]
            conn.execute(
                "UPDATE bridges SET weight=min(weight+1,?), last_used=?, "
                "promoted=CASE WHEN min(weight+1,?)>=? THEN 1 ELSE promoted END "
                "WHERE neuron_key=? AND neurag_key=?",
                (_WEIGHT_CAP, now, _WEIGHT_CAP, _PROMOTE_AT, b["neuron_key"], b["neurag_key"]))
            b["weight"] = min(b["weight"] + 1, _WEIGHT_CAP)
            b["last_used"] = now
            if just:
                b["promoted"] = 1
                b["_just_promoted"] = True
        conn.commit()
    finally:
        conn.close()
    return out


def decay(amount: float = 1.0, max_idle_seconds: float = 7 * 24 * 3600,
          prune_below: float = 1.0) -> int:
    """Idle bridges lose `amount` weight; those below `prune_below` are dropped.
    Returns how many were pruned. Bridges are hypotheses — unused ones fade."""
    now = time.time()
    conn = _connect()
    try:
        before = conn.execute("SELECT COUNT(*) AS c FROM bridges").fetchone()["c"] or 0
        conn.execute("UPDATE bridges SET weight=weight-? WHERE ?-last_used > ?",
                     (amount, now, max_idle_seconds))
        conn.execute("DELETE FROM bridges WHERE weight < ?", (prune_below,))
        after = conn.execute("SELECT COUNT(*) AS c FROM bridges").fetchone()["c"] or 0
        conn.commit()
    finally:
        conn.close()
    return before - after


def all_bridges() -> list[dict]:
    conn = _connect()
    try:
        return [dict(r) for r in
                conn.execute("SELECT * FROM bridges ORDER BY weight DESC").fetchall()]
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Trasferimento fra tier (local <-> cloud)
# --------------------------------------------------------------------------

def _open_local():
    """Il tier locale ESPLICITO (bypassa la scelta automatica di _connect)."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open_local_turso(str(path)) if LOCAL_TURSO_ENGINE else None
    if conn is not None:
        conn.row_factory = _local_row_factory
    else:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _open_cloud():
    """Il tier cloud ESPLICITO. Alza ValueError se non è configurato."""
    if not REMOTE_TURSO:
        raise ValueError("cloud non configurato: servono GM_TURSO_DATABASE_URL "
                         "e un token (GM_TURSO_AUTH_TOKEN o TURSO_AUTH_TOKEN), "
                         "più l'extra cloud: pip install \"gray-matter[cloud]\"")
    conn = _RemoteConn(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
    conn.execute(_SCHEMA)
    return conn


_TRANSFER_COLS = ("neuron_key", "neurag_key", "neuron", "neurag", "rationale",
                  "weight", "created", "last_used", "promoted")


def transfer(direction: str = "to-cloud", *, dry_run: bool = False) -> dict:
    """Copia i bridge fra tier locale e cloud. Additivo, mai distruttivo.

    Un bridge già presente a destinazione viene FUSO, non sovrascritto: si tiene
    il `weight` più alto e il `last_used` più recente, così trasferire due volte
    (o nei due sensi) non perde rinforzo — l'operazione è idempotente.

    ``direction``: "to-cloud" (locale -> cloud) o "from-cloud" (cloud -> locale).
    """
    if direction not in ("to-cloud", "from-cloud"):
        raise ValueError("direction: 'to-cloud' o 'from-cloud'")
    src = _open_local() if direction == "to-cloud" else _open_cloud()
    try:
        rows = [dict(r) for r in src.execute("SELECT * FROM bridges").fetchall()]
    finally:
        src.close()
    if dry_run:
        return {"direction": direction, "read": len(rows), "written": 0,
                "merged": 0, "dry_run": True}

    dst = _open_cloud() if direction == "to-cloud" else _open_local()
    written = merged = 0
    try:
        for r in rows:
            existing = dst.execute(
                "SELECT weight, last_used FROM bridges WHERE neuron_key=? AND neurag_key=?",
                (r["neuron_key"], r["neurag_key"])).fetchone()
            if existing is None:
                dst.execute(
                    f"INSERT INTO bridges ({','.join(_TRANSFER_COLS)}) "
                    f"VALUES ({','.join('?' * len(_TRANSFER_COLS))})",
                    tuple(r[c] for c in _TRANSFER_COLS))
                written += 1
            else:
                dst.execute(
                    "UPDATE bridges SET weight=?, last_used=? "
                    "WHERE neuron_key=? AND neurag_key=?",
                    (max(r["weight"], existing["weight"]),
                     max(r["last_used"], existing["last_used"]),
                     r["neuron_key"], r["neurag_key"]))
                merged += 1
        dst.commit()
    finally:
        dst.close()
    return {"direction": direction, "read": len(rows), "written": written,
            "merged": merged, "dry_run": False}
