"""Turso/ SQLite-backed hierarchical knowledge graph with vector embeddings.

Single-database design using Turso (SQLite-compatible) with an extension for
vector cosine-similarity search (384-dim, same as Neuron). When Turso is not
available, falls back to pure SQLite (vector search via Python brute-force).
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import struct
from pathlib import Path
from typing import Optional

try:
    from pyturso import connect as turso_connect
    TURSO_AVAILABLE = True
except ImportError:
    TURSO_AVAILABLE = False

from neurag.chunker import chunk_file, scan_directory
from neurag.embedder import get_embedder

_DEFAULT_DB_DIR = Path.home() / ".local" / "share" / "neurag"
_DEFAULT_DB = _DEFAULT_DB_DIR / "knowledge.db"

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
"""


class KnowledgeGraph:
    """Hierarchical knowledge graph with vector search.

    Uses Turso (libsql) when available via pyturso, falls back to sqlite3.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or _DEFAULT_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()
        self._init_schema()
        self._embedder = get_embedder()  # auto: fastembed if present, else null (lexical)

    # -- connection ---------------------------------------------------------

    def _connect(self) -> None:
        if TURSO_AVAILABLE:
            # Turso (libsql) — local file
            self._conn = turso_connect(str(self._db_path))
        else:
            self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _init_schema(self) -> None:
        for stmt in SCHEMA_SQL.split(";"):
            s = stmt.strip()
            if s:
                self._conn.execute(s)
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
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
        chunks = chunk_file(filepath)
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
        for fp in scan_directory(root):
            total += self.index_into_node(fp, node_id)
        return total

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
        embeddings exist, else lexical TF-IDF. Returns chunk rows, best first."""
        rows = [dict(r) for r in self._conn.execute("SELECT * FROM chunks").fetchall()]
        if not rows:
            return []
        qv = self._get_embedding(query)
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
        node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        chunk_count = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        engine = "turso" if TURSO_AVAILABLE else "sqlite3"
        return {
            "engine": engine,
            "embedder": self._embedder.name,
            "db_path": str(self._db_path),
            "nodes": node_count,
            "chunks": chunk_count,
            "embedded": embedded,
            "embedding_dim": 384,
        }

    # -- health: structural integrity (L1, deterministic) -------------------

    def health(self) -> dict:
        """Structural audit of the vault (no LLM, no embeddings). Flags problems;
        it never deletes — NeuRAG is a curated source of truth. `ok` is False only
        for the serious issues (broken hierarchy, tiny chunks, duplicate names)."""
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
