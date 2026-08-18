# Gray Matter — MCP tools reference

> Tools defined by the Gray Matter orchestrator (`gray_matter/server.py`).
> For Neuron and NeuRAG tools, see the [unified TOOLS reference](../../docs/TOOLS.md).

---

## gray_matter_pulse

Main orchestrator call. Calls Neuron `get_context` and NeuRAG `knowledge_query` in parallel, merges results, applies cache, fires flash on topic shifts.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | yes | — | Topic to search (max 200 chars) |
| `top_n` | integer | no | 5 | Number of NeuRAG chunks (1-10) |

**Returns:** Merged text from Neuron context + NeuRAG results + bridge links + flash + proactive neighbors.

## gray_matter_status

Show registered servers, cache state, and orchestrator counters.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| (none) | | | | |

## gray_matter_bridge

Persist a cross-store bridge: a link between a Neuron concept and a NeuRAG knowledge node. Idempotent.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `neuron_concept` | string | yes | — | Neuron concept/keyword |
| `neurag_node` | string | yes | — | NeuRAG node/topic |
| `rationale` | string | no | `""` | Why they connect |

---

## See also

- [Unified TOOLS.md](../../docs/TOOLS.md) — all tools from all projects
- [Architecture](../../docs/ARCHITECTURE.md) — how tools connect
- [Configuration](../../docs/CONFIGURATION.md) — env vars and config knobs
