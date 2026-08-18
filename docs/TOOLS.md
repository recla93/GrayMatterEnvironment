# MCP tools — complete reference

> Every MCP tool exposed by Neuron, Gray Matter, and NeuRAG. Signatures verified
> against source code. When using the Gray Matter gateway, all tools from all
> registered sub-servers are re-published under their original names.

---

## Gray Matter tools

These tools are defined by the Gray Matter orchestrator (`gray_matter/server.py`).

### gray_matter_pulse

Main orchestrator call. Calls Neuron `get_context` and NeuRAG `knowledge_query` in parallel, merges results, applies cache, fires flash on topic shifts.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Topic to search (max 200 chars) |
| `top_n` | integer | no | 5 | Number of NeuRAG chunks (1-10) |

**Returns:** Merged text from Neuron context + NeuRAG results + bridge links + flash + proactive neighbors.

### gray_matter_status

Show registered servers, cache state, and orchestrator counters.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### gray_matter_bridge

Persist a cross-store bridge: a link between a Neuron concept and a NeuRAG knowledge node. Idempotent.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `neuron_concept` | string | yes | — | Neuron concept/keyword |
| `neurag_node` | string | yes | — | NeuRAG node/topic |
| `rationale` | string | no | `""` | Why they connect |

---

## Neuron tools

All tools defined in `neuron/server.py`. The core loop is two steps per turn:
1. `pre_turn` (before replying) — load context
2. `store_turn` (after replying) — persist what is new

### pre_turn

MEMORY LOOP — STEP 1. Load relevant past context in one shot (status + get_context in compact form). Fold silently into your answer.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Current topic or question |
| `keywords` | string[] | no | `[]` | Additional keywords to broaden search |
| `max_tokens` | integer | no | 200 | Max output size in approx tokens |

### store_turn

MEMORY LOOP — STEP 2. Persist what is new into long-term memory. Curate for a clean graph.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Topic of the turn (3-5 words) |
| `keywords` | string[] | yes | — | Abstract keywords (3-5, concept nouns only) |
| `domain` | string | yes | — | Free-form label (e.g. `backend`, `AI`, `general`) |
| `intent` | string (enum) | yes | — | One of: `question`, `task`, `exploration`, `clarification`, `feedback` |
| `sentiment` | string (enum) | yes | — | One of: `neutral`, `positive`, `critical`, `urgent` |
| `context` | string | no | `""` | Context path (e.g. `java/spring`). Defaults to active context |
| `episode` | string | no | — | ONE compact fact sentence (max ~200 chars) |
| `entities` | string[] | no | `[]` | Explicit entities (max 15) |
| `tags` | string[] | no | `[]` | Free labels (max 10) |
| `references` | object[] | no | `[]` | File/URL/commit references (max 20) |
| `links` | object[] | no | `[]` | Typed edges between keywords |

**links[] schema:** `{ source: string, target: string, link_type: string (cause-effect|analogy|evolution|contrast|deepening|instance-of), weight: string (strong|medium|tangential), rationale: string (max 200 chars) }`

### get_context

Retrieve related nodes and links for a topic. Call before answering when prior context may be relevant.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Main keyword to search |
| `keywords` | string[] | no | `[]` | Additional keywords to broaden search |
| `depth` | integer | no | 1 | Search depth (1-3) |
| `max_tokens` | integer | no | 400 | Max output size in approx tokens |
| `format` | string (enum) | no | `"full"` | `"full"` (multi-line) or `"compact"` (single-line for injection) |
| `context` | string | no | `""` | Context path. Defaults to active context |

### confirm

Feedback signal: boost salience of useful keywords so they surface more prominently in future retrieval.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `keywords` | string[] | yes | — | Keywords that were actually useful |
| `boost` | integer | no | 2 | Salience boost (max 5) |
| `confidence` | number | no | 1.0 | How certain the context was useful (-1 to 1). NEGATIVE = refute: lowers trust |
| `context` | string | no | `""` | Context path. Defaults to active context |

### find_candidates

Screening: find existing similar keywords via vector search. Call before store_turn to avoid duplicates.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `keywords` | string[] | yes | — | Keywords to find similar candidates for |
| `top_n` | integer | no | 8 | Number of candidates |
| `context` | string | no | `""` | Context path. Defaults to active context |

### vector_search

Semantic vector search via Turso `vector_distance_cos` or Python cosine fallback.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `keywords` | string[] | yes | — | Query keywords |
| `top_n` | integer | no | 8 | Number of results |
| `context` | string | no | `""` | Context path. Defaults to active context |

### summary

Textual graph summary: top keywords, recent links, health, forgotten concepts.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### introspect

Neuron self-model (C3): strongest concepts, recent growth, weakest domain, loop compliance. Returns JSON.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `context` | string | no | `""` | Context path. Defaults to active context |

### forgotten

Find keywords not touched in N turns (decaying salience). With `near`, ranks dormant concepts by mid-band similarity to a topic.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `threshold` | integer | no | 5 | Inactivity turns threshold |
| `top_n` | integer | no | 10 | How many to show |
| `near` | string | no | — | Topic to rank dormant concepts against (mid-band 0.30-0.75) |
| `context` | string | no | `""` | Context path. Defaults to active context |

### prune

Force prune inactive tangential links.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `context` | string | no | `""` | Context path. Defaults to active context |
| `dry_run` | boolean | no | false | Preview: list what would be pruned without deleting |

### consolidate

Merge near-duplicate concepts (cosine) and archive low-salience orphans to `_graveyard`. Safe to run periodically.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `context` | string | no | `""` | Context path. Defaults to active context |
| `merge` | boolean | no | true | Merge near-duplicate nodes |
| `drop_orphans` | boolean | no | true | Archive low-salience orphan nodes |
| `sim_threshold` | number | no | 0.85 | Cosine threshold for merging |

### dedup

Toggle keyword deduplication. Output reports the resulting ON/OFF state.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `enable` | boolean | no | (toggle) | Set explicitly. Omit to toggle |

### flash

Toggle semantic flashbacks.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### reset

Reset the graph and start over. DESTRUCTIVE and irreversible.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `confirm` | boolean | yes | — | Must be true to wipe the graph |
| `context` | string | no | `""` | Context path. Defaults to active context |

### extract

Automatic semantic extraction from text: keyword, topic, domain, intent, sentiment, entities. Heuristic (0 token cost).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | Text to analyze |
| `context` | string | no | `""` | Context path. Defaults to active context |

### auto

POST fallback (0-token): one-shot extract + topic-shift + auto-link + save. Prefer curated store_turn when possible.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | User message to analyze and archive |
| `context` | string | no | `""` | Context path. Defaults to active context |

### export

Export the complete graph as JSON.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `context` | string | no | `""` | Context path. Defaults to active context |

### merge

Merge duplicate or near-duplicate nodes. Moves all links from aliases into canonical, sums salience, then deletes aliases.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `canonical` | string | yes | — | The keyword to keep as the single authoritative node |
| `aliases` | string[] | yes | — | Keywords to absorb into canonical and delete |
| `context` | string | no | `""` | Context path. Defaults to active context |

### switch_context

Switch active context (creates if new). E.g. `java/spring`, `python/django`.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `context` | string | yes | — | Context path to switch to |

### list_contexts

List all available contexts with metadata.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `parent` | string | no | — | Optional parent filter |

### help

Show every Neuron command (one line each) plus how to use Neuron well.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### skill

Return the full text of a Neuron skill/playbook on demand.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string (enum) | no | `"playbook"` | `playbook` (full PRE/POST workflow) or `curated` (clean-graph patterns) |

### status

Current graph state: node/link counts, health, and active configuration (DB tier, active context). Read-only — the safe first call to inspect the memory graph.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

---

## NeuRAG tools

All tools defined in `neurag/server.py`. The knowledge base uses a hierarchical node tree (godnode/fundamental/specialization) with chunked content.

### knowledge_index

Chunk a file or directory without saving. Returns JSON list of chunks. LLM then calls `knowledge_add_node` + `knowledge_add_chunks` to organize them.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Absolute path to a file or directory to chunk |

### knowledge_add_node

Create a node in the hierarchy.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | — | Node name (e.g. `Java`, `Spring_Boot`) |
| `node_type` | string (enum) | yes | — | `godnode` (root topic), `fundamental` (area), `specialization` (deep dive) |
| `parent_name` | string | no | — | Parent node name. Omit for godnode. Required for fundamental and specialization |
| `triggers` | string[] | no | `[]` | Keywords that activate this node on knowledge_query |

### knowledge_add_chunks

Attach previously indexed chunks to a node.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `node_name` | string | yes | — | Target node name |
| `chunks` | object[] | yes | — | Chunks from knowledge_index output |

**chunks[] schema:** `{ text: string, source: string, section: string, chunk_index: integer }`

### knowledge_query

Search the knowledge base for chunks relevant to a topic. Three-tier fallback: trigger match → vector SQL → Python cosine / TF-IDF.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Topic or question |
| `top_n` | integer | no | 5 | Number of results (1-10) |

### knowledge_status

Show knowledge base status: engine, node count, chunk count.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### knowledge_tree

Show the hierarchical node tree from root.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### knowledge_health

Structural audit: broken hierarchy, tiny/empty chunks, duplicate names (serious) + orphan nodes, chunks without source, nodes without triggers (warnings). Read-only.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### knowledge_link_graph

Show all node links (tag_overlap, cross_ref) with weights and evidence.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### knowledge_rebuild_links

Clear all links and rebuild from tags (Jaccard) + cross-refs (shared source files). Returns count of links created.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

### knowledge_neighbors

Structured neighborhood of a node. BFS over parent/children/links up to `depth` hops. SQL-only, no embeddings.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Topic/keyword to resolve to a node (trigger match first, exact name second) |
| `depth` | integer | no | 2 | Hops (1-3) |
| `limit` | integer | no | 5 | Max neighbors (1-20) |

**Returns:** JSON `{ node: {name, path}, neighbors: [{name, path, node_type, relation, distance}] }`. Empty node = no match.

---

## Next steps

- [CLI reference](CLI.md) — all command-line commands
- [Configuration](CONFIGURATION.md) — env vars and config knobs
- [Architecture](ARCHITECTURE.md) — how the tools connect
