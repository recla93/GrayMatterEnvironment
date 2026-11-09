# MCP tools — complete reference

> Every MCP tool exposed by Gray Matter, Neuron and NeuRAG, as of gray_matter 1.8.0,
> neuron 6.10.0 and neurag 1.8.0. The parameters below are generated from the servers'
> own schemas (`list_tools`), not written by hand.

## Which tools a client sees

Each server **announces** a small core set and keeps the rest as **admin tools**.
Admin tools are not shown to the AI client (every schema costs tokens in every
session), but they still answer when called by name, and the CLI and the control
center use them.

| Server | Announced by default | Announce everything |
|---|---|---|
| Neuron | 8 tools (the memory loop) | `NEURON_TOOLS=all` |
| NeuRAG | 7 tools (ingest + search) | `NEURAG_TOOLS=all` |
| Gray Matter | its 4 own tools + the announced tools of Neuron and NeuRAG, under their own names | `GM_TOOLS=all` adds the internal blackboard tools (`gray_matter_state_*`) |

With the Gray Matter gateway (the default install) a client registers **only**
`gray-matter`; Neuron and NeuRAG run behind it as workers and their tools are passed
through unchanged.

---

## Gray Matter

Defined in `gray_matter/server.py`.

### gray_matter_pulse

The richer explicit read: Neuron's facts for the topic (as `pre_turn`), NeuRAG's
knowledge excerpts, saved bridges and a flash, in one call.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Topic to search for |
| `top_n` | integer | no | 5 | Number of knowledge chunks (1-10) |

### gray_matter_brainstorm

What surrounds a problem, with its history: mid-band memory nodes (related but not
obvious) with their facts and link rationales — a past decision, a bug solved once —
plus the nearest knowledge chunks. For dilemmas, problems and decisions.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `seed` | string | yes | — | The problem, dilemma or decision, in one sentence |
| `n` | integer | no | 5 | Memory nodes to show (max 10); knowledge chunks are capped at 3 |

### gray_matter_bridge

Save a bridge: a link between a Neuron concept and a NeuRAG node. It is recalled in
later pulses on either end. Idempotent: the same pair again reinforces it.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `neuron_concept` | string | yes | — | Neuron concept (keyword) |
| `neurag_node` | string | yes | — | NeuRAG node, by its exact name |
| `rationale` | string | no | `""` | Why they connect |

Bridges can also be created, edited and removed by hand in the control center
(**Bridge** view, or by dragging in the **Grafi** view).

### gray_matter_status

Registered servers, cache and counters. No parameters.

---

## Neuron — the memory loop

Defined in `neuron/src/neuron/server.py`. Every substantive turn is two calls:

1. `pre_turn` **before** replying — loads the facts relevant to the topic;
2. `store_turn` **after** replying — saves what is worth not repeating, as facts.

The **fact** is the unit of memory: one sentence with its why, a kind, and 1-5
concept nouns that index it. Facts are append-only: a newer fact *supersedes* an
older one, nothing is evicted.

### pre_turn

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Current topic or question |
| `keywords` | string[] | no | — | Extra keywords to broaden the search |
| `max_tokens` | integer | no | 200 | Size of the returned context |
| `profile` | boolean | no | false | Also return the active `user` and `habit` facts. Once per session; Gray Matter sets it for you |
| `exclude` | string[] | no | — | Fact ids already shown this session, so they do not come back. Gray Matter sets it for you |
| `fact_nodes` | integer | no | 3 | How many top-ranked nodes contribute facts (minimum 1) |
| `mode` | `semantic` \| `focus` | no | `semantic` | `focus` boosts the active task |
| `focus` | string | no | `""` | Active task for focus mode (injected by Gray Matter) |

Each fact comes back with its id (`#0a1b2c3d`): pass it to `confirm` when it helped,
or to `store_turn` as `supersedes` when you replace it.

### store_turn

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `facts` | object[] | no | — | The memory of this turn: 0-3 facts, one sentence each (see below) |
| `topic` | string | no | the first fact | Topic of the turn (3-5 words) |
| `keywords` | string[] | no | — | Extra concepts; the facts' concepts are added anyway |
| `links` | object[] | no | — | Typed links between concepts (see below) |
| `references` | object[] | no | — | Files, URLs or commits the turn touched: `{type: file\|url\|commit, path, description}` |
| `domain` | string | no | `general` | Keep `general`. The same other value on two consecutive turns **switches** the active context |
| `context` | string | no | active | Context path |

**`facts[]`:**

| Field | Required | Description |
|---|---|---|
| `text` | yes | One sentence with its why, ideally under 400 characters |
| `kind` | no (default `fact`) | `progress`, `decision`, `fix`, `fact`, `idea`, `user` (who the user is, what they want), `habit` (how they work) |
| `concepts` | no (default: the turn's) | 1-5 concept **nouns** that index the fact — never verbs or filler |
| `supersedes` | no | Id of the older fact this one replaces |

A fact nearly identical to an existing one is saved and flagged, not merged.
Never store secrets or tokens.

**`links[]`:** `{source, target, link_type, weight, rationale}` with `link_type` one of
`cause-effect`, `analogy`, `evolution`, `contrast`, `deepening`, `instance-of`, and
`weight` one of `strong`, `medium`, `tangential`. Never link a concept to itself.

Example:

```json
store_turn(facts=[{
  "kind": "fix",
  "text": "The control center showed 'Failed to fetch' because a reinstall stops its server; it now shows one banner.",
  "concepts": ["gui", "reinstall"]
}])
```

### confirm

A recalled fact or concept was useful.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `facts` | string[] | no | — | Ids of recalled facts that shaped the answer (`#0a1b2c3d`); each counts one use |
| `keywords` | string[] | no | — | Concepts that were useful; boosts their salience |
| `boost` | integer | no | 2 | Salience boost (max 5) |
| `confidence` | number | no | 1.0 | -1 to 1. **Negative = refute**: the context was wrong, trust goes down |
| `context` | string | no | active | Context path |

Citing or superseding a fact in `store_turn` already counts as a use.

### The other announced tools

| Tool | Parameters | What it does |
|---|---|---|
| `status` | — | Nodes, links, health, configuration. The safe first call |
| `switch_context` | `context` (required) | Switch the active context (created if new), e.g. `java/spring` |
| `list_contexts` | `parent` | All contexts with metadata |
| `help` | — | Every Neuron command in one line each |
| `skill` | `name`: `playbook` (default) \| `curated` | Full text of the workflow (`playbook`) or of the clean-graph rules (`curated`) |

### Admin tools (`NEURON_TOOLS=all`)

All except `summary`, `dedup` and `flash` also take an optional `context` (defaults
to the active one).

| Tool | Parameters | What it does |
|---|---|---|
| `get_context` | `topic`*, `keywords`, `depth` (1-3, 1), `max_tokens` (400), `format` (`full` \| `compact`), `profile` | Nodes and links around a topic. `pre_turn` covers it in the loop |
| `find_candidates` | `keywords`*, `top_n` (8) | Existing similar keywords (vector search) |
| `vector_search` | `keywords`*, `top_n` (8) | Semantic search over the concept embeddings |
| `around` | `topic`*, `n` (8, max 20) | Mid-band nodes (similarity 0.30-0.75) with their facts and link reasons; raw material for `gray_matter_brainstorm` |
| `forgotten` | `threshold` (5), `top_n` (10), `near`, `facts`, `exclude` | Concepts not touched for N turns; with `near` ranked by similarity; with `facts=true` dormant facts (what a flash shows) |
| `dismiss` | `keywords`*, `penalty` (3), `trust_penalty` (0.5) | The recalled context was misleading: lower salience and trust |
| `recall` | `keyword`*, `base_salience` (3) | Bring an archived (graveyard) concept back |
| `summary` | — | Top keywords, recent links, health |
| `introspect` | — | Self-model: strongest concepts, growth, weakest domain, loop compliance (JSON) |
| `export` | — | The whole graph as JSON (concepts, links, facts) |
| `merge` | `canonical`*, `aliases`* | Fold duplicates into one concept |
| `consolidate` | `merge` (true), `drop_orphans` (false), `confirm_mass_drop` (false), `sim_threshold` (0.85) | Merge near-duplicates; optionally archive orphans. A drop above 20% is refused without `confirm_mass_drop`; a backup is taken first |
| `prune` | `dry_run` (false) | Remove inactive tangential links |
| `dedup` | `enable` | Toggle keyword deduplication |
| `flash` | — | Toggle flashbacks |
| `extract` | `text`* | Heuristic extraction (keyword, topic, domain, intent, sentiment) — no LLM |
| `auto` | `text`* | Zero-token fallback: extract and save in one shot. Prefer a curated `store_turn` |
| `reset` | `confirm`* (must be `true`) | **Wipe the graph. Irreversible** |

`*` = required.

---

## NeuRAG — the knowledge base

Defined in `neurag/server.py`. Knowledge lives in a tree of nodes (`godnode` →
`fundamental` → `specialization`) holding chunks of the user's documents. Each chunk
carries the **date of its document**; at equal relevance the newer one wins.

### knowledge_query

Search the user's own indexed material.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Topic or question, **in the documents' language** (another language finds much less) |
| `top_n` | integer | no | 5 | Results (1-10); 2-3 is usually enough, each costs ~100 tokens |
| `archive` | boolean | no | false | Also search nodes declared history (see `knowledge_archive`) |

Every result shows its node, source and date; archived results are marked `[archive]`.

### knowledge_ingest

Turn a folder or a single document into nodes, chunks, embeddings and links, server
side, in the background. Re-ingesting a file replaces its chunks.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | — | Absolute path of a folder (whole tree) or of one file |
| `godnode` | string | no | folder name | Root node to use or create |
| `code` | boolean | no | false | Also chunk source code. Default: documents only (`.md .txt .pdf .docx`) |

Returns a job id; follow it with `knowledge_ingest_status`.

### The other announced tools

| Tool | Parameters | What it does |
|---|---|---|
| `knowledge_ingest_status` | `job_id` | Status of ingest jobs |
| `knowledge_status` | — | Engine, node count, chunk count |
| `knowledge_tree` | — | The node tree |
| `knowledge_confirm` | `names`* (2+) | These nodes were useful **together**: strengthens the existing links between them |
| `knowledge_skill` | `name`: `usage` | Full text of the retrieval workflow |

### Admin tools (`NEURAG_TOOLS=all`)

| Tool | Parameters | What it does |
|---|---|---|
| `knowledge_archive` | `name`*, `restore` (false) | Declare a node and its subtree history: out of normal search, reachable with `archive=true`, never deleted. `restore=true` brings it back |
| `knowledge_neighbors` | `query`*, `depth` (2, 1-3), `limit` (5) | Neighborhood of a node; the exact name is tried first. JSON `{node, neighbors}` |
| `knowledge_related` | `query`*, `k` (2), `limit` (5), `deep` (false) | Spreading activation from a node |
| `knowledge_link_graph` | `format`: `text` (default) \| `json` | All links with weights; `json` gives `{nodes, links}` for the control center's graph view |
| `knowledge_health` | — | Structural audit, read-only |
| `knowledge_rebuild_links` | — | Rebuild every link from tags and cross-references |
| `knowledge_reindex` | — | Re-embed every chunk after changing the embedding model |
| `knowledge_rename_node` | `name`*, `new_name`* | Rename a node and update its subtree's paths |
| `knowledge_remove_node` | `name`* | **Delete** a node and its whole subtree |
| `knowledge_import` | `mapping`* | Bulk-import a folder tree from a YAML mapping |
| `knowledge_index` | `path`* | Chunk without saving (for the manual flow below) |
| `knowledge_add_node` | `name`*, `node_type`* (`godnode` \| `fundamental` \| `specialization`), `parent_name`, `triggers` | Create a node |
| `knowledge_add_chunks` | `node_name`*, `chunks`* | Attach chunks from `knowledge_index`: `{text, source, section, chunk_index}` |

`*` = required. Prefer `knowledge_ingest` over the manual `knowledge_index` →
`knowledge_add_node` → `knowledge_add_chunks` flow: no chunk text travels through
the model's context.

---

## Next steps

- [CLI reference](CLI.md) — the same operations from the command line
- [Configuration](CONFIGURATION.md) — environment variables and settings
- [Architecture](ARCHITECTURE.md) — how the three servers connect
