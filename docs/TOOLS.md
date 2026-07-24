# NeuRAG — MCP tools reference

> Tools defined by the NeuRAG knowledge base (`neurag/server.py`).
> For Gray Matter and Neuron tools, see the [unified TOOLS reference](../../docs/TOOLS.md).

---

## knowledge_index

Chunk a file or directory without saving. Returns JSON list of chunks. LLM then calls `knowledge_add_node` + `knowledge_add_chunks` to organize them.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Absolute path to a file or directory to chunk |

## knowledge_add_node

Create a node in the hierarchy.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | — | Node name (e.g. `Java`, `Spring_Boot`) |
| `node_type` | string (enum) | yes | — | `godnode` (root topic), `fundamental` (area), `specialization` (deep dive) |
| `parent_name` | string | no | — | Parent node name. Omit for godnode. Required for fundamental and specialization |
| `triggers` | string[] | no | `[]` | Keywords that activate this node on knowledge_query |

## knowledge_add_chunks

Attach previously indexed chunks to a node.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `node_name` | string | yes | — | Target node name |
| `chunks` | object[] | yes | — | Chunks from knowledge_index output |

**chunks[] schema:** `{ text: string, source: string, section: string, chunk_index: integer }`

## knowledge_query

Search the knowledge base for chunks relevant to a topic. Three-tier fallback: trigger match → vector SQL → Python cosine / TF-IDF.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Topic or question |
| `top_n` | integer | no | 5 | Number of results (1-10) |

## knowledge_status

Show knowledge base status: engine, node count, chunk count.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## knowledge_tree

Show the hierarchical node tree from root.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## knowledge_health

Structural audit: broken hierarchy, tiny/empty chunks, duplicate names (serious) + orphan nodes, chunks without source, nodes without triggers (warnings). Read-only.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## knowledge_link_graph

Show all node links (tag_overlap, cross_ref) with weights and evidence.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## knowledge_rebuild_links

Clear all links and rebuild from tags (Jaccard) + cross-refs (shared source files). Returns count of links created.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## knowledge_neighbors

Structured neighborhood of a node. BFS over parent/children/links up to `depth` hops. SQL-only, no embeddings.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Topic/keyword to resolve to a node (trigger match first, exact name second) |
| `depth` | integer | no | 2 | Hops (1-3) |
| `limit` | integer | no | 5 | Max neighbors (1-20) |

**Returns:** JSON `{ node: {name, path}, neighbors: [{name, path, node_type, relation, distance}] }`. Empty node = no match.

---

## See also

- [Unified TOOLS.md](../../docs/TOOLS.md) — all tools from all projects
- [Architecture](../../docs/ARCHITECTURE.md) — how the tools connect
- [Configuration](../../docs/CONFIGURATION.md) — env vars and config knobs
