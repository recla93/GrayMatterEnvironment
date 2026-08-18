# CLI reference — all command-line commands

> Every CLI entry point across Neuron, Gray Matter, and NeuRAG. Verified against
> source code. Gray Matter entry point: `gray-matter`. Neuron: `neuron`. NeuRAG: `neurag`.

---

## Gray Matter CLI

Entry point: `gray-matter` (defined in `gray_matter/cli.py`).

### gray-matter status

Show registered servers, their status, PIDs, tools, and collaboration mode.

```
gray-matter status
```

### gray-matter start

Spawn Gray Matter as a background daemon. Polls up to 3s for port bind.

```
gray-matter start
```

### gray-matter stop

Send shutdown IPC to the daemon.

```
gray-matter stop
```

### gray-matter ping

Check if the daemon is listening on `:9876`.

```
gray-matter ping
```

### gray-matter isolate \<name\>

Exclude a server from the combined pulse (still callable directly).

```
gray-matter isolate neuron
gray-matter isolate neurag
```

### gray-matter collaborate \<name\>

Re-include a server in the combined pulse.

```
gray-matter collaborate neuron
```

### gray-matter mode \<mode\>

Set ALL servers to `collaborate` or `separate`.

```
gray-matter mode collaborate
gray-matter mode separate
```

### gray-matter gui

Open the web control center. Add `--classic` for the legacy Tkinter GUI.

```
gray-matter gui
gray-matter gui --classic
```

### gray-matter register

Register installed trio servers in detected MCP clients. Add `--gateway` for proxy model (register only gray-matter, evict neuron/neurag).

```
gray-matter register
gray-matter register --gateway
```

### gray-matter install

Idempotent gateway install: reap orphans, ensure data dirs, register GM in clients, deploy hooks, write manifest.

```
gray-matter install
gray-matter install --dry-run
```

### gray-matter uninstall

Remove Gray Matter. Memory deletion is interactive unless `--purge-data`.

```
gray-matter uninstall
gray-matter uninstall --purge-data --yes
gray-matter uninstall --dry-run
```

### gray-matter bridges

List persisted cross-store bridges (sorted by weight).

```
gray-matter bridges
```

### gray-matter stats

Show orchestrator counters: pulse count, cache hit rate, flashes, bridges, avg latency.

```
gray-matter stats
```

### gray-matter doctor

Health snapshot: servers, workers, cache, bridges, NeuRAG engine tier.

```
gray-matter doctor
```

### gray-matter knowledge \<subcmd\>

NeuRAG knowledge base management.

```
gray-matter knowledge status
gray-matter knowledge rebuild-links
gray-matter knowledge link-graph
```

### gray-matter gm-neuron \<tool\> \[args\]

Call any Neuron tool via the GM orchestrator.

```
gray-matter gm-neuron pre_turn '{"topic":"kotlin coroutines"}'
gray-matter gm-neuron status
```

### gray-matter gm-neurag \<tool\> \[args\]

Call any NeuRAG tool via the GM orchestrator.

```
gray-matter gm-neurag knowledge_query '{"query":"spring boot"}'
gray-matter gm-neurag knowledge_status
```

### gray-matter config \<action\> \[key\] \[value\]

Get, set, or list tunable knobs.

```
gray-matter config list
gray-matter config get flash_min_gap
gray-matter config set cache_ttl_seconds 120
```

---

## Neuron CLI

Entry point: `neuron` (defined in `neuron/__main__.py`).

Default (no subcommand) runs the MCP stdio server.

### neuron (no args)

Start the MCP stdio server. Accepts isolation flags:

| Flag | Purpose |
|---|---|
| `--graphs-dir PATH` | Override store location (sets `NS_GRAPHS_DIR`) |
| `--local` | Force local tier: drops `TURSO_*` creds |
| `--slug NAME` | Identity override (sets `NEURON_SLUG`) |

```
neuron
neuron --graphs-dir ./my-store --local
```

### neuron init

Client wiring (no heavy server import). Delegates to `neuron/init.py`.

```
neuron init
```

### neuron register

Register the MCP server in detected AI clients. Delegates to `neuron/clients.py`.

```
neuron register
```

### neuron doctor

Diagnose and repair client registrations. Delegates to `neuron/clients.py`.

```
neuron doctor
```

### neuron consolidate

Merge near-duplicate nodes + archive orphans. Can target a specific context.

```
neuron consolidate
neuron consolidate --context java/spring
neuron consolidate --no-merge --sim-threshold 0.9
```

| Flag | Default | Description |
|---|---|---|
| `--context` | all contexts | Target a single context |
| `--no-merge` | false | Skip merging near-duplicates |
| `--no-drop-orphans` | false | Skip archiving orphans |
| `--sim-threshold` | 0.85 | Cosine threshold for merging |

### neuron setup

Lifecycle CLI (install, update, uninstall). Delegates to `neuron/setup.py`.

```
neuron setup
```

### neuron manage

Day-to-day management CLI. Delegates to `neuron/manage.py`.

```
neuron manage
```

### neuron bridge

Expose the stdio server over HTTP for remote connectors. Delegates to `neuron/bridge.py`.

```
neuron bridge
```

### neuron connect

Connect and test a Turso Cloud DB, then save to `.env`. Delegates to `neuron/connect.py`.

```
neuron connect
```

### neuron console

Read-only graph diagnostics. Add `--watch` to follow.

```
neuron console
neuron console --watch
```

### neuron tunnel

Public HTTPS via cloudflared (pairs with bridge). Delegates to `neuron/tunnel.py`.

```
neuron tunnel
```

### neuron gui

Tkinter visual hub (also the windowed `neuron-gui` exe). Delegates to `neuron/gui.py`.

```
neuron gui
```

---

## NeuRAG CLI

Entry point: `neurag` (defined in `neurag/cli.py`).

### neurag status

Show knowledge base status: engine, DB path, node count, chunk count, embedded count.

```
neurag status
```

### neurag chunk \<path\>

Chunk a file or directory to stdout as JSON (does not save).

```
neurag chunk ./my-docs
neurag chunk README.md
```

### neurag add-node \<name\> \<type\>

Add a node to the hierarchy.

```
neurag add-node Java godnode
neurag add-node Spring_Boot fundamental --parent Java --triggers spring boot microservices
```

| Flag | Description |
|---|---|
| `--parent` | Parent node name (required for fundamental/specialization) |
| `--triggers` | Trigger keywords (space-separated) |

### neurag add-chunks \<node\>

Attach chunks from JSON (stdin or file) to a node.

```
neurag add-chunks Java --file chunks.json
echo '[{"text":"...","source":"..."}]' | neurag add-chunks Java
```

| Flag | Description |
|---|---|
| `--file` | JSON file with chunks array (default: stdin) |

### neurag query \<query\>

Search the knowledge base. Trigger match first, then falls back to lexical/semantic.

```
neurag query "spring boot configuration"
neurag query "kotlin coroutines" --top-n 3 --json
```

| Flag | Default | Description |
|---|---|---|
| `--top-n` | 5 | Number of results |
| `--json` | false | Output as JSON |

### neurag tree

Print the full node hierarchy.

```
neurag tree
```

### neurag import \<mapping\>

Bulk import from a YAML mapping file.

```
neurag import mapping.yaml
```

### neurag health

Structural audit: integrity check (broken hierarchy, empty chunks, duplicates).

```
neurag health
```

---

## Next steps

- [MCP tools](TOOLS.md) — full tool signatures
- [Configuration](CONFIGURATION.md) — env vars and config knobs
- [Troubleshooting](TROUBLESHOOTING.md) — common issues
