"""MCP server for NeuRAG (Turso hierarchical knowledge graph)."""

from __future__ import annotations

import json
import threading
import sys
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

from neurag import __version__
from neurag.db import KnowledgeGraph

# Gray-Matter auto-registration (optional)
try:
    from gray_matter.server import autoregister, auto_register_and_run
    _GM_AVAILABLE = True
except ImportError:
    _GM_AVAILABLE = False


def _get_db() -> KnowledgeGraph:
    global _db
    if _db is None:
        _db = KnowledgeGraph()
    return _db


_db: KnowledgeGraph | None = None

app = Server("neurag", version=__version__)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge_index",
            description="Chunk a file or directory without saving. Returns JSON list of chunks. LLM then calls knowledge_add_node + knowledge_add_chunks to organize them.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to a file or directory to chunk",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="knowledge_add_node",
            description="Create a node in the hierarchy.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Node name (e.g. Java, JVM, Spring_Boot)"},
                    "node_type": {
                        "type": "string",
                        "enum": ["godnode", "fundamental", "specialization"],
                        "description": "godnode=root topic, fundamental=area, specialization=deep dive",
                    },
                    "parent_name": {
                        "type": "string",
                        "description": "Parent node name. Omit or empty for godnode (goes under root). Required for fundamental and specialization.",
                    },
                    "triggers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Keywords that activate this node on knowledge_query (optional)",
                    },
                },
                "required": ["name", "node_type"],
            },
        ),
        Tool(
            name="knowledge_add_chunks",
            description="Attach previously indexed chunks to a node.",
            inputSchema={
                "type": "object",
                "properties": {
                    "node_name": {"type": "string", "description": "Target node name"},
                    "chunks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "source": {"type": "string"},
                                "section": {"type": "string"},
                                "chunk_index": {"type": "integer"},
                            },
                        },
                        "description": "Chunks to attach (from knowledge_index output)",
                    },
                },
                "required": ["node_name", "chunks"],
            },
        ),
        Tool(
            name="knowledge_query",
            description="Search the knowledge base for chunks relevant to a topic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic or question"},
                    "top_n": {
                        "type": "integer", "description": "Number of results (1-10, default 5)",
                        "default": 5, "minimum": 1, "maximum": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="knowledge_status",
            description="Show knowledge base status: engine, node count, chunk count.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="knowledge_tree",
            description="Show the hierarchical node tree.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="knowledge_health",
            description="Structural audit of the vault: broken hierarchy, tiny/empty chunks, duplicate names (serious) + orphan nodes, chunks without source, nodes without triggers (warnings). Read-only — flags, never deletes.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="knowledge_link_graph",
            description="Show all node links (tag_overlap, cross_ref) with weights and evidence.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="knowledge_rebuild_links",
            description="Clear all links and rebuild from tags + cross-refs. Returns count of links created.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="knowledge_neighbors",
            description="D3 — structured neighborhood of a node, resolved from a query (trigger match, then exact name). BFS over parent/children/links up to `depth` hops. JSON: {node, neighbors:[{name, path, node_type, relation, distance}]}. Empty node = no match. Cheap (SQL-only) — built for Gray Matter's proactive-knowledge pulse.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic/keyword to resolve to a node (trigger match first, exact name second)"},
                    "depth": {"type": "integer", "description": "Hops (1-3, default 2)", "default": 2},
                    "limit": {"type": "integer", "description": "Max neighbors (default 5)", "default": 5},
                },
                "required": ["query"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    db = _get_db()

    if name == "knowledge_neighbors":
        import json as _json
        query = " ".join(str(arguments.get("query", "")).split())[:200]
        if not query:
            return [TextContent(type="text", text=_json.dumps({"node": None, "neighbors": []}))]
        node = db.find_node_by_trigger(query) or db.get_node_by_name(query)
        if not node:  # fallback: try single words of a multi-word topic
            for w in query.split():
                node = db.find_node_by_trigger(w) or db.get_node_by_name(w)
                if node:
                    break
        if not node:
            return [TextContent(type="text", text=_json.dumps({"node": None, "neighbors": []}))]
        depth = min(max(int(arguments.get("depth", 2)), 1), 3)
        limit = min(max(int(arguments.get("limit", 5)), 1), 20)
        neigh = db.get_neighbors(node["id"], depth=depth, limit=limit)
        return [TextContent(type="text", text=_json.dumps(
            {"node": {"name": node["name"], "path": node.get("path")},
             "neighbors": neigh}, ensure_ascii=False))]

    if name == "knowledge_index":
        path = Path(arguments["path"])
        if not path.exists():
            return [TextContent(type="text", text=f"Path not found: {path}")]
        import json as _json
        from neurag.chunker import chunk_file, scan_directory
        chunks = []
        if path.is_file():
            chunks = chunk_file(path)
        else:
            for fp in scan_directory(path):
                chunks.extend(chunk_file(fp))
        if not chunks:
            return [TextContent(type="text", text="No chunks produced.")]
        data = [_json.dumps({"text": c.text, "source": c.source, "section": c.section, "chunk_index": c.chunk_index}, ensure_ascii=False) for c in chunks]
        return [TextContent(type="text", text="[\n" + ",\n".join(data) + "\n]")]

    if name == "knowledge_add_node":
        name = arguments["name"]
        node_type = arguments["node_type"]
        parent_name = arguments.get("parent_name")
        triggers = arguments.get("triggers", [])
        existing = db.get_node_by_name(name)
        if existing:
            return [TextContent(type="text", text=f"Node '{name}' already exists (type={existing['node_type']}).")]
        parent_id = None
        if parent_name:
            parent = db.get_node_by_name(parent_name)
            if not parent:
                return [TextContent(type="text", text=f"Parent node '{parent_name}' not found. Create it first.")]
            parent_id = parent["id"]
        node_id = db.add_node(name=name, node_type=node_type, parent_id=parent_id, triggers=triggers)
        node = db.get_node(node_id)
        return [TextContent(type="text", text=f"Created {node_type} '{name}' at {node['path']}.")]

    if name == "knowledge_add_chunks":
        node_name = arguments["node_name"]
        node = db.get_node_by_name(node_name)
        if not node:
            return [TextContent(type="text", text=f"Node '{node_name}' not found.")]
        chunks = arguments["chunks"]
        count, skipped = 0, 0
        for c in chunks:
            # F4 (ingest validation) — reject junk at the door: non-dict, missing
            # or whitespace-only text. Short-but-real chunks stay (code lines are
            # legitimately short); emptiness is the only objective junk signal.
            text = (c.get("text") or "").strip() if isinstance(c, dict) else ""
            if not text:
                skipped += 1
                continue
            db.add_chunk(
                node_id=node["id"],
                text=text,
                source=c.get("source"),
                section=c.get("section"),
                chunk_index=c.get("chunk_index", 0),
            )
            count += 1
        msg = f"Attached {count} chunks to '{node_name}'."
        if skipped:
            msg += f" Skipped {skipped} empty/invalid."
        return [TextContent(type="text", text=msg)]

    if name == "knowledge_query":
        query = arguments["query"]
        top_n = min(int(arguments.get("top_n", 5)), 10)
        node = db.find_node_by_trigger(query)
        if node:
            children = db.get_children(node["id"])
            node_chunks = db.get_chunks(node["id"])
            lines = [f"Trigger match: {node['path']} ({len(children)} children, {len(node_chunks)} chunks)"]
            if children:
                lines.append("Children:")
                for c in children:
                    lines.append(f"  {c['node_type']}: {c['name']}")
            if node_chunks:
                lines.append("Chunks:")
                for c in node_chunks[:top_n]:
                    lines.append(f"  [{c['chunk_index']}] {c['source']} :: {c['section'] or ''}")
                    lines.append(f"       {c['text'][:200]}...")
            return [TextContent(type="text", text="\n".join(lines))]
        # Fallback: semantic (embedder on) or lexical TF-IDF ranking
        top = db.search(query, top_n)
        if not top:
            return [TextContent(type="text", text="No results found.")]
        lines = [f"Query: {query}", f"Top {len(top)} results:", ""]
        for i, c in enumerate(top):
            lines.append(f"  [{i+1}] {c['source']} :: {c['section'] or ''}")
            lines.append(f"       {c['text'][:200]}...")
            lines.append("")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "knowledge_status":
        s = db.status()
        return [TextContent(type="text", text=json.dumps(s, indent=2))]

    if name == "knowledge_tree":
        return [TextContent(type="text", text=db.node_tree() or "(empty)")]

    if name == "knowledge_health":
        return [TextContent(type="text", text=json.dumps(db.health(), indent=2))]

    if name == "knowledge_link_graph":
        graph = db.get_link_graph()
        if not graph:
            return [TextContent(type="text", text="No links. Run knowledge_rebuild_links first.")]
        lines = []
        for l in graph:
            lines.append(f"{l['source_name']} --[{l['link_type']}, w={l['weight']:.2f}]--> {l['target_name']}")
            if l.get("evidence"):
                lines.append(f"  evidence: {l['evidence']}")
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "knowledge_rebuild_links":
        result = db.rebuild_links()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    """Start NeuRAG MCP server with optional Gray-Matter registration."""
    tool_names = [
        "knowledge_index",
        "knowledge_add_node",
        "knowledge_add_chunks",
        "knowledge_query",
        "knowledge_status",
        "knowledge_tree",
        "knowledge_health",
        "knowledge_link_graph",
        "knowledge_rebuild_links",
    ]

    # Gray-Matter auto-registration (non-blocking)
    if _GM_AVAILABLE:
        autoregister("neurag", tool_names)
        def _hb():
            from gray_matter.server import _send_heartbeat
            import time
            while True:
                time.sleep(5)
                _send_heartbeat("neurag")
        t = threading.Thread(target=_hb, daemon=True)
        t.start()

    import asyncio
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="neurag",
                    server_version=__version__,
                ),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
