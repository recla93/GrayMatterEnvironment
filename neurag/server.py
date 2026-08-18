"""MCP server for NeuRAG (Turso hierarchical knowledge graph)."""

from __future__ import annotations

import json
import os
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
    return _tools()


def announced_tool_names() -> list[str]:
    """What `main()` tells Gray Matter this server serves.

    DERIVED from the tools themselves, the way Neuron does it
    (`autoregister("neuron", list(_HANDLERS.keys()))`). It used to be a
    hand-written list next to `autoregister`, and it had drifted twice:
    `knowledge_neighbors` and `skill` were both served and dispatched for
    releases while the gateway was never told they existed, so GM could not
    proxy tools that worked."""
    return [t.name for t in _tools()]


_VAULT_STATS: "str | None" = None


def _vault_note() -> str:
    """What the vault actually holds, for the `knowledge_query` description.

    A model decides whether to call a tool from the tool list, which is the one
    text always in front of it — a skill file is read only if it chooses to read
    one. And the decisive fact is not *how* to search, it is whether there is
    anything to find: "Search the knowledge base" gives no reason to spend a
    round-trip, while "2555 chunks of the user's own material" does. Same tool,
    same cost, opposite prior.

    Never raises and never blocks: a stat that fails costs the sentence, not the
    handshake. Computed once per process — the count moves with ingests, and a
    fresh number per `list_tools()` is not worth reopening the vault for.
    """
    global _VAULT_STATS
    if _VAULT_STATS is None:
        try:
            s = _get_db().status()
            if s.get("corrupt"):
                _VAULT_STATS = " The vault is not readable right now — call " \
                               "knowledge_status for the reason."
            elif not s.get("chunks"):
                _VAULT_STATS = " The vault is EMPTY: nothing to find until " \
                               "something is ingested, so do not search it yet."
            else:
                _VAULT_STATS = (f" Holds {s['chunks']} chunks across "
                                f"{s['nodes']} topics right now.")
        except Exception:  # noqa: BLE001 — mai al costo dell'handshake
            _VAULT_STATS = ""
    return _VAULT_STATS


def _tools() -> list[Tool]:
    """The single source of truth for what this server serves."""
    return [
        Tool(
            name="knowledge_ingest",
            description="Graph-ize a folder OR a single document server-side in ONE "
                        "call: nodes from the folder structure, chunks, embeddings, "
                        "links. Runs in background — returns a job id immediately; "
                        "poll knowledge_ingest_status. Re-ingesting the same file "
                        "REPLACES its chunks, so updating a document is just calling "
                        "this again. Prefer this over knowledge_index: no chunk text "
                        "travels through the model's context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Absolute path of a FOLDER (whole tree) or a SINGLE FILE to ingest"},
                    "godnode": {"type": "string",
                                "description": "Root node to use/create (default: folder name)"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="knowledge_ingest_status",
            description="Status of ingest jobs started with knowledge_ingest "
                        "(all jobs, or one via job_id).",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job id (optional)"},
                },
            },
        ),
        Tool(
            name="knowledge_index",
            description="Chunk a file or directory without saving. Returns JSON list of chunks. LLM then calls knowledge_add_node + knowledge_add_chunks to organize them. For whole folders prefer knowledge_ingest (server-side, no chunks through context).",
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
            description=(
                "Search the USER'S OWN indexed material — their documents, notes "
                "and code, not general knowledge." + _vault_note() +
                " Use it whenever the question could touch what they have "
                "indexed: answering from training data instead means answering "
                "about somebody else's version of the subject, confidently and "
                "unverifiably. Costs one round-trip; skip it for procedural "
                "turns, for general knowledge the vault would not hold, and for "
                "anything already answered in this conversation. Cite the node "
                "or source you used, so the user can check it."),
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
            name="knowledge_reindex",
            description="Re-embed every chunk with the currently active embedding model. Use after changing embed_model: vectors from two models are not comparable, so search returns noise until the vault is rebuilt. Only vectors change — chunk text, nodes and links are untouched, and the source files are not needed. For a chunk-SIZE change use knowledge_ingest instead (it re-chunks from disk).",
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
        Tool(
            name="knowledge_confirm",
            description="Mark results as having been USEFUL TOGETHER, so the links "
                        "between their nodes learn from it (Hebbian). Call it after an "
                        "answer actually helped — confirmation is the signal, "
                        "co-retrieval is not: retrieval is cheap and often wrong. "
                        "Reinforces only links that already exist, at most once per 2 "
                        "queries per link, promoting weight at 3 and 8 co-activations. "
                        "A reinforced link stops being derived, so it survives the next "
                        "ingest. JSON: {confirmed:[names], upgraded:[{source,target,weight}]}.",
            inputSchema={
                "type": "object",
                "properties": {
                    "names": {"type": "array", "items": {"type": "string"},
                              "description": "Two or more node names that were useful together"},
                },
                "required": ["names"],
            },
        ),
        Tool(
            name="knowledge_related",
            description="Associative expansion: spreading activation from a node, k hops "
                        "out, ranked by accumulated activation rather than hop count. "
                        "Surfaces what a direct match would miss. Pure graph walk (no "
                        "embedding). Parked nodes stay out unless deep=true. "
                        "JSON: {node, related:[{name, path, activation, layer}]}.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic/keyword to resolve to a node"},
                    "k": {"type": "integer", "description": "Hops (default 2)", "default": 2},
                    "limit": {"type": "integer", "description": "Max results (default 5)", "default": 5},
                    "deep": {"type": "boolean", "description": "Include parked nodes", "default": False},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="knowledge_remove_node",
            description="Delete a node and its entire subtree (children, chunks, links). "
                        "Runs server-side on the single DB writer (the Gray-Matter worker "
                        "or the standalone CLI) — never a second process.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the node to delete"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="knowledge_rename_node",
            description="Rename a node; updates the materialised path of itself and all "
                        "descendants. Server-side on the single DB writer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Current node name"},
                    "new_name": {"type": "string", "description": "New node name"},
                },
                "required": ["name", "new_name"],
            },
        ),
        Tool(
            name="knowledge_import",
            description="Bulk-import a folder tree from a YAML mapping (deterministic, no "
                        "LLM). Nodes + chunks created server-side on the single DB writer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "mapping": {"type": "string", "description": "Path to the YAML mapping file"},
                },
                "required": ["mapping"],
            },
        ),
        Tool(
            name="skill",
            description="Return the FULL text of a NeuRAG skill on demand — token-cheap, "
                        "fetch it only when you need the details. Call once per session "
                        "after the compact opener to load the retrieval workflow.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": _SKILL_NAMES,
                        "description": "Which skill: usage (the retrieval workflow — "
                                       "when to search, how to cite, when NOT to search).",
                        "default": "usage",
                    },
                },
            },
        ),
    ]


# Skills served as MCP tools, not as client plugin files: a plugin reaches one
# client (Cowork), a tool reaches every client that speaks MCP. Same reason
# Neuron serves `skill` — keep the two registries the same shape.
_SKILLS: dict[str, tuple[str, ...]] = {
    "usage": ("skills", "usage.md"),
}
_SKILL_NAMES = list(_SKILLS)


def _read_skill(parts: tuple[str, ...]) -> str:
    """Read a packaged skill file via importlib.resources (works from the wheel).

    Falls back to the repo-root copy when running from a bare source checkout.
    Mirrors neuron.funnel._read_skill."""
    from importlib.resources import files
    try:
        return files("neurag").joinpath(*parts).read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — source checkout without packaged data
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "neurag", *parts), encoding="utf-8") as fh:
            return fh.read()


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch, with the one failure every tool shares turned into an answer.

    A vault that will not open reached the MCP framework as an unhandled
    exception, which the client renders as "Internal Server Error" — the same
    dead end 1.1.1 fixed for `knowledge_status`/`knowledge_health` and left open
    for every other tool. `VaultUnavailable` already carries the cause and the
    recovery command, so the model gets told what happened instead of that
    something did."""
    from neurag.db import VaultUnavailable
    try:
        return await _call_tool(name, arguments)
    except VaultUnavailable as exc:
        return [TextContent(type="text", text=str(exc))]


async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "skill":
        which = str(arguments.get("name") or "usage").strip()
        parts = _SKILLS.get(which)
        if parts is None:
            return [TextContent(type="text", text=(
                f"unknown skill '{which}' — available: {', '.join(_SKILL_NAMES)}"))]
        try:
            return [TextContent(type="text", text=_read_skill(parts))]
        except OSError as exc:
            return [TextContent(type="text", text=f"skill '{which}' unreadable: {exc}")]

    db = _get_db()

    if name == "knowledge_confirm":
        import json as _json
        names = [str(n) for n in (arguments.get("names") or [])]
        nodes = [n for n in (db.get_node_by_name(x) for x in names) if n]
        if len(nodes) < 2:
            return [TextContent(type="text", text=_json.dumps(
                {"confirmed": [n["name"] for n in nodes], "upgraded": [],
                 "note": "need at least two known nodes to reinforce a link"}))]
        upgraded = db.confirm([n["id"] for n in nodes])
        by_id = {n["id"]: n["name"] for n in nodes}
        return [TextContent(type="text", text=_json.dumps({
            "confirmed": [n["name"] for n in nodes],
            "upgraded": [{"source": by_id.get(u["source_id"], u["source_id"]),
                          "target": by_id.get(u["target_id"], u["target_id"]),
                          "weight": round(u["weight"], 3),
                          "co_activation_count": u["co_activation_count"]}
                         for u in upgraded]}, ensure_ascii=False))]

    if name == "knowledge_related":
        import json as _json
        query = " ".join(str(arguments.get("query", "")).split())[:200]
        node = (db.find_node_by_trigger(query) or db.get_node_by_name(query)) if query else None
        if not node:
            return [TextContent(type="text", text=_json.dumps({"node": None, "related": []}))]
        related = db.related_nodes(node["id"],
                                  k=int(arguments.get("k", 2)),
                                  limit=int(arguments.get("limit", 5)),
                                  deep=bool(arguments.get("deep", False)))
        return [TextContent(type="text", text=_json.dumps(
            {"node": node["name"], "related": related}, ensure_ascii=False))]

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
        # The node's canonical tag names travel with the answer. Gray Matter
        # matches its cross-store bridges on tag IDENTITY (DESIGN-EVOLUTION §4),
        # and this is the only object all three stores agree on — sending it
        # here costs nothing, where a second round-trip in GM's pulse to ask for
        # four words would not be free.
        return [TextContent(type="text", text=_json.dumps(
            {"node": {"name": node["name"], "path": node.get("path")},
             "tags": db.node_tag_names(node["id"]),
             "neighbors": neigh}, ensure_ascii=False))]

    if name == "knowledge_ingest":
        from neurag.ingest import start_job
        path = Path(arguments["path"])
        if not path.exists():
            return [TextContent(type="text", text=f"Path not found: {path}")]
        job = start_job(path, arguments.get("godnode"))
        return [TextContent(type="text", text=(
            f"Ingest started: job {job['id']} on {path}. "
            f"Poll knowledge_ingest_status to follow progress."))]

    if name == "knowledge_ingest_status":
        from neurag.ingest import JOBS, job_text
        jid = arguments.get("job_id")
        if jid:
            job = JOBS.get(jid)
            if job is None:
                return [TextContent(type="text", text=f"No such job: {jid}")]
            return [TextContent(type="text", text=job_text(job))]
        if not JOBS:
            return [TextContent(type="text", text="No ingest jobs this session.")]
        return [TextContent(type="text",
                            text="\n\n".join(job_text(j) for j in JOBS.values()))]

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

    if name == "knowledge_reindex":
        result = db.reindex()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "knowledge_remove_node":
        name = arguments["name"]
        node = db.get_node_by_name(name)
        if not node:
            return [TextContent(type="text", text=f"Node '{name}' not found.")]
        n = db.delete_node(node["id"])
        return [TextContent(type="text",
                            text=f"[ok] eliminati {n} nodi (sottoalbero incluso).")]

    if name == "knowledge_rename_node":
        name = arguments["name"]
        new_name = arguments["new_name"]
        node = db.get_node_by_name(name)
        if not node:
            return [TextContent(type="text", text=f"Nodo '{name}' non trovato.")]
        db.rename_node(node["id"], new_name)
        return [TextContent(type="text",
                            text=f"[ok] '{name}' → '{new_name}' (path aggiornati).")]

    if name == "knowledge_import":
        from neurag.importer import import_mapping
        report = import_mapping(db, arguments["mapping"])
        txt = f"Imported: {report['nodes']} nodes, {report['chunks']} chunks."
        if report.get("skipped"):
            txt += "\n" + "\n".join(f"  skipped: {s}" for s in report["skipped"])
        return [TextContent(type="text", text=txt)]

    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    """Start NeuRAG MCP server with optional Gray-Matter registration."""
    tool_names = announced_tool_names()

    # Gray-Matter auto-registration (non-blocking). Se NeuRAG è andato
    # standalone (go-standalone), NON deve ri-registrarsi al gateway anche se
    # GM è importabile nello stesso venv: i suoi tool sarebbero pubblicati due
    # volte (entry diretta + proxy GM).
    gm_manages_us = _GM_AVAILABLE
    if _GM_AVAILABLE:
        try:
            from gray_matter.clients import unmanaged_tools
            gm_manages_us = "neurag" not in unmanaged_tools()
        except Exception:  # noqa: BLE001 — GM vecchio senza unmanaged_tools
            pass
    if gm_manages_us:
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
    from mcp.server.lowlevel import NotificationOptions
    from mcp.server.stdio import stdio_server

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="neurag",
                    server_version=__version__,
                    # REQUIRED pydantic field since the MCP SDK bump (1.28).
                    # Without it every stdio start died on a ValidationError
                    # before serving a single tool — and `SERVERS["neurag"]` is
                    # `-m neurag.server`, so that is what every client registers.
                    # Gray Matter hit this exact failure and fixed it in its
                    # `_init_options()`; the fix never crossed over, and nothing
                    # noticed because the daemon path never builds these options.
                    capabilities=app.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={},
                    ),
                ),
            )

    asyncio.run(_run())


if __name__ == "__main__":
    main()
