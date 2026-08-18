"""Bulk import: build the hierarchy + index files from a YAML mapping.

The mapping describes the tree and which files/folders feed each node — a
deterministic, non-LLM loader (the LLM path is knowledge_index/add_node/add_chunks).
`sources` are resolved relative to the mapping file. List parents before children.

    godnode: Java                 # optional root godnode
    nodes:
      - name: Concurrency
        type: fundamental
        parent: Java              # by name; omit for a godnode
        triggers: [thread, lock]
        sources:                  # files or dirs to chunk into this node
          - notes/concurrency/
          - guides/threads.md
"""

from __future__ import annotations

from pathlib import Path


def import_mapping(kg, mapping_path) -> dict:
    try:
        import yaml  # PyYAML, optional
    except ImportError:
        raise ImportError("pip install neurag[yaml] for YAML mapping import")

    mapping_path = Path(mapping_path)
    data = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
    base = mapping_path.resolve().parent  # sources are relative to the mapping file
    report = {"nodes": 0, "chunks": 0, "skipped": []}

    god = data.get("godnode")
    if god and not kg.get_node_by_name(god):
        kg.add_node(name=god, node_type="godnode")
        report["nodes"] += 1

    for spec in data.get("nodes", []):
        name = spec["name"]
        node = kg.get_node_by_name(name)
        if node is None:
            parent = spec.get("parent") or god
            parent_id = None
            if parent:
                p = kg.get_node_by_name(parent)
                if p is None:
                    report["skipped"].append(f"{name}: parent '{parent}' not found (list parents first)")
                    continue
                parent_id = p["id"]
            nid = kg.add_node(name=name, node_type=spec["type"],
                              parent_id=parent_id, triggers=spec.get("triggers", []))
            report["nodes"] += 1
            node = kg.get_node(nid)

        for src in spec.get("sources", []):
            p = base / src
            if not p.exists():
                report["skipped"].append(f"{name}: source '{src}' not found")
                continue
            if p.is_file():
                report["chunks"] += kg.index_into_node(p, node["id"])
            else:
                report["chunks"] += kg.index_directory_into_node(p, node["id"])

    return report
