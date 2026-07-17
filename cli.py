"""CLI entry points: neurag (standalone CLI) and neurag-mcp (server)."""

import argparse
import json as json_mod
import sys
from pathlib import Path

from neurag.db import KnowledgeGraph
from neurag.chunker import chunk_file, scan_directory


def main() -> None:
    parser = argparse.ArgumentParser(description="NeuRAG — knowledge RAG CLI (neurag)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show knowledge base status")

    idx = sub.add_parser("chunk", help="Chunk a file/dir to stdout (does not save)")
    idx.add_argument("path", help="Directory or file to chunk")

    add = sub.add_parser("add-node", help="Add a node to the hierarchy")
    add.add_argument("name", help="Node name")
    add.add_argument("type", choices=["godnode", "fundamental", "specialization"], help="Node type")
    add.add_argument("--parent", default=None, help="Parent node name")
    add.add_argument("--triggers", nargs="*", default=[], help="Trigger keywords")

    ac = sub.add_parser("add-chunks", help="Attach chunks from stdin (JSON) to a node")
    ac.add_argument("node", help="Target node name")
    ac.add_argument("--file", help="JSON file with chunks array (default: stdin)")

    q = sub.add_parser("query", help="Search the knowledge base")
    q.add_argument("query", help="Search topic")
    q.add_argument("--top-n", type=int, default=5, help="Number of results (default 5)")
    q.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("tree", help="Show node hierarchy")

    imp = sub.add_parser("import", help="Bulk-import a folder tree from a YAML mapping")
    imp.add_argument("mapping", help="Path to the YAML mapping file")

    sub.add_parser("health", help="Structural audit of the vault (integrity check)")

    args = parser.parse_args()
    db = KnowledgeGraph()

    if args.command == "status":
        s = db.status()
        print(f"Engine: {s['engine']}")
        print(f"DB:     {s['db_path']}")
        print(f"Nodes:  {s['nodes']}")
        print(f"Chunks: {s['chunks']}")
        print(f"Embedded: {s['embedded']} of {s['chunks']}")

    elif args.command == "chunk":
        path = Path(args.path)
        if not path.exists():
            print(f"Path not found: {args.path}", file=sys.stderr)
            sys.exit(1)
        chunks = []
        if path.is_file():
            chunks = chunk_file(path)
        else:
            for fp in scan_directory(path):
                chunks.extend(chunk_file(fp))
        print(json_mod.dumps([c.__dict__ for c in chunks], ensure_ascii=False, indent=2))

    elif args.command == "add-node":
        existing = db.get_node_by_name(args.name)
        if existing:
            print(f"Node '{args.name}' already exists (type={existing['node_type']}).")
            return
        parent_id = None
        if args.parent:
            parent = db.get_node_by_name(args.parent)
            if not parent:
                print(f"Parent '{args.parent}' not found.", file=sys.stderr)
                sys.exit(1)
            parent_id = parent["id"]
        node_id = db.add_node(name=args.name, node_type=args.type, parent_id=parent_id, triggers=args.triggers)
        node = db.get_node(node_id)
        print(f"Created {args.type} '{args.name}' at {node['path']}.")

    elif args.command == "add-chunks":
        node = db.get_node_by_name(args.node)
        if not node:
            print(f"Node '{args.node}' not found.", file=sys.stderr)
            sys.exit(1)
        if args.file:
            chunks = json_mod.loads(Path(args.file).read_text(encoding="utf-8"))
        else:
            chunks = json_mod.loads(sys.stdin.read())
        count = 0
        for c in chunks:
            db.add_chunk(node_id=node["id"], text=c["text"], source=c.get("source"), section=c.get("section"), chunk_index=c.get("chunk_index", 0))
            count += 1
        s = db.status()
        print(f"Attached {count} chunks to '{args.node}'. Total: {s['chunks']} chunks.")

    elif args.command == "query":
        node = db.find_node_by_trigger(args.query)
        chunks = []
        if node:
            print(f"Trigger match: {node['name']} (type={node['node_type']})")
            chunks = db.get_chunks(node["id"])
            if not chunks:
                rows = db._conn.execute("SELECT id FROM nodes WHERE parent_id = ?", (node["id"],)).fetchall()
                for r in rows:
                    chunks.extend(db.get_chunks(r["id"]))
        if not chunks:
            chunks = db.search(args.query, args.top_n)
        chunks = chunks[:args.top_n]

        if not chunks:
            print("No results.")
            return

        if args.json:
            print(json_mod.dumps(chunks, ensure_ascii=False, indent=2, default=str))
            return

        for i, c in enumerate(chunks):
            print(f"  [{i+1}] {c['source']} :: {c['section'] or ''}")
            print(f"       {c['text'][:200].replace(chr(10), ' ')}...")
            print()

    elif args.command == "tree":
        print(db.node_tree())

    elif args.command == "import":
        from neurag.importer import import_mapping
        report = import_mapping(db, args.mapping)
        print(f"Imported: {report['nodes']} nodes, {report['chunks']} chunks.")
        for s in report["skipped"]:
            print(f"  skipped: {s}")

    elif args.command == "health":
        h = db.health()
        print("Vault health:", "OK" if h["ok"] else f"{h['serious_count']} serious issue(s)")
        for k, v in h["issues"].items():
            if v:
                print(f"  [issue] {k}: {len(v)}")
        for k, v in h["warnings"].items():
            n = v if isinstance(v, int) else len(v)
            if n:
                print(f"  [warn]  {k}: {n}")


if __name__ == "__main__":
    main()
