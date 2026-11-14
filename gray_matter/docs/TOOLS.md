# Gray Matter — MCP tools reference

> Tools defined by the Gray Matter orchestrator (`gray_matter/server.py`).
> For Neuron and NeuRAG tools, see the [unified TOOLS reference](../../docs/TOOLS.md).

---

## gray_matter_pulse

The richer explicit read. Calls Neuron `pre_turn` (the facts) and NeuRAG `knowledge_query` in parallel, merges the results, adds the saved bridges for the topic and, at a topic shift, a flash (a dormant idea, decision or fix). Cached.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Topic to search (max 200 chars) |
| `top_n` | integer | no | 5 | Number of NeuRAG chunks (1-10) |

**Returns:** Neuron facts + NeuRAG excerpts, then bridges and flash within `proactive_budget_chars`.

## gray_matter_status

Show registered servers, cache state, and orchestrator counters.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## gray_matter_bridge

Save a bridge: a link between a Neuron concept and a NeuRAG node (its exact, existing name). Idempotent: the same pair again reinforces it. Bridges are never created automatically.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `neuron_concept` | string | yes | — | Neuron concept/keyword |
| `neurag_node` | string | yes | — | NeuRAG node, exact name |
| `rationale` | string | no | `""` | Why they connect |

---

## See also

- [Unified TOOLS.md](../../docs/TOOLS.md) — all tools from all projects
- [Architecture](../../docs/ARCHITECTURE.md) — how tools connect
- [Configuration](../../docs/CONFIGURATION.md) — env vars and config knobs
