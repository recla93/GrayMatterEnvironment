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
    from turso import connect as turso_connect
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
        db_str = str(self._db_path)
        # Turso engine whenever pyturso is installed — ALSO for local files
        # (embedded libSQL legge il formato SQLite): sblocca vector_distance_cos
        # nativa in SQL invece del coseno in Python. Prima veniva usato solo per
        # URL cloud, quindi il tier locale girava sempre su sqlite3 stdlib.
        use_turso = TURSO_AVAILABLE
        self._vector_sql = use_turso
        if use_turso:
            self._conn = turso_connect(db_str)
            def _row_factory(cursor, row):
                if cursor.description is None:
                    return row
                cols = [c[0] for c in cursor.description]
                return _CompatRow(cols, row)
            self._conn.row_factory = _row_factory
        else:
            self._conn = sqlite3.connect(db_str)
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

    def delete_node(self, node_id: int) -> int:
        """Delete a node and its whole subtree — EXPLICIT bottom-up deletes.

        Non si appoggia alle FK ``ON DELETE CASCADE``: pyturso 0.6.1 va in
        stack overflow C sul trigger ricorsivo della cascade (audit
        2026-07-20). Qui cancelliamo noi, foglie prima (ORDER BY path DESC),
        per ogni id prima chunks e links poi la riga nodo — nessuna cascade
        ricorsiva da innescare. Funziona identico sul tier sqlite3.
        Ritorna quanti nodi sono stati rimossi (0 = id inesistente)."""
        start = self.get_node(node_id)
        if not start:
            return 0
        # get_descendants ordina per path ASC (genitori prima): invertito, ogni
        # figlio ('P/x' > 'P') precede il suo genitore → mai un DELETE su un
        # nodo che ha ancora figli, quindi la cascade FK non parte mai.
        doomed = [d["id"] for d in reversed(self.get_descendants(node_id))]
        doomed.append(node_id)                     # la radice per ultima
        for nid in doomed:
            self._conn.execute("DELETE FROM chunks WHERE node_id = ?", (nid,))
            self._conn.execute(
                "DELETE FROM node_links WHERE source_id = ? OR target_id = ?",
                (nid, nid))
            self._conn.execute("DELETE FROM nodes WHERE id = ?", (nid,))
        self._conn.commit()
        return len(doomed)

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
        node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        chunk_count = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded = self._conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()[0]
        db_str = str(self._db_path)
        engine = "turso" if getattr(self, "_vector_sql", False) else "sqlite"
        return {
            "engine": engine,
            "embedder": self._embedder.name,
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
