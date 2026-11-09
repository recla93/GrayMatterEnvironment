# CLI reference — all command-line commands

> Every command of `gray-matter`, `neuron` and `neurag`, as of gray_matter 1.8.0,
> neuron 6.10.0 and neurag 1.8.0. The lists come from each tool's own `--help`;
> run `<command> <subcommand> --help` for every flag.
>
> Prefer clicking? The control center (`gray-matter gui`) has every command below,
> grouped by what you want to do, with each argument explained and the exact command
> line to copy.

---

## Gray Matter — `gray-matter`

### Everyday

| Command | What it does |
|---|---|
| `gray-matter gui` | Open the control center (window, or the browser if no native window is available) |
| `gray-matter doctor` | Health check in two blocks: the installation (registry, hooks, client entries, versions, processes) and the runtime (servers, workers, cache, bridges, storage). Every `[!!]` line has its fix below it |
| `gray-matter status` | Registered servers, their state, PIDs and tools |
| `gray-matter stats` | Pulses, cache hit rate, flashes, bridges, average latency |
| `gray-matter logs` | The daemon log |
| `gray-matter start` / `stop` / `ping` | Start, stop, or check the background daemon |

### Memory ↔ knowledge

| Command | What it does |
|---|---|
| `gray-matter bridges` | List the saved bridges, strongest first |
| `gray-matter promote [--apply]` | Turn proven Neuron facts into NeuRAG knowledge. Dry run unless `--apply` |
| `gray-matter backup [--force]` | Copy Neuron's graphs, NeuRAG's vault and the bridges into `<suite>/backups/gm-graph-backup_<day>/`. Once a day, keeps 7 |
| `gray-matter knowledge status` \| `rebuild-links` \| `link-graph` | NeuRAG management through Gray Matter |
| `gray-matter gm-neuron <tool> ['<json>']` | Call any Neuron tool through the daemon, e.g. `gray-matter gm-neuron pre_turn '{"topic":"kotlin"}'` |
| `gray-matter gm-neurag <tool> ['<json>']` | Call any NeuRAG tool through the daemon, e.g. `gray-matter gm-neurag knowledge_query '{"query":"spring"}'` |

### Collaboration between the tools

| Command | What it does |
|---|---|
| `gray-matter isolate <name>` | Leave `neuron` or `neurag` out of the combined pulse (still callable directly) |
| `gray-matter collaborate <name>` | Put it back |
| `gray-matter mode collaborate` \| `separate` | The same for all servers |

### Installation and maintenance

| Command | What it does |
|---|---|
| `gray-matter install [--dry-run]` | Idempotent gateway install: clean orphans, register `gray-matter` in the clients, deploy the hooks, write the manifest |
| `gray-matter register [--gateway]` | Register the installed servers in the MCP clients; `--gateway` registers only `gray-matter` |
| `gray-matter deregister <tool>` | Take a tool off the gateway and register it directly in the clients |
| `gray-matter link` | The inverse: re-attach standalone tools to the gateway |
| `gray-matter repair` | Clean repair: choose what to delete, then reinstall |
| `gray-matter reap [--all] [--dry-run]` | Stop suite processes left behind (orphans only, unless `--all`) |
| `gray-matter uninstall [--dry-run] [--purge-data] [--yes]` | Remove Gray Matter. The memory is deleted only with `--purge-data` |
| `gray-matter config list` \| `get <key>` \| `set <key> <value>` | Read or change a setting (flash rate, cache TTL, proactive budget, …) |
| `gray-matter cloud setup` \| `wire` \| `status` \| `teardown` | Turso cloud storage |
| `gray-matter bridges-transfer` | Move bridges between the local and the cloud tier |
| `gray-matter bridge` | Serve the whole suite over HTTP for remote connectors (Bearer token required) |
| `gray-matter record-env` | Record the source folders of the three tools (used by the installer) |

---

## Neuron — `neuron`

`neuron` with no arguments runs the MCP server on stdio: your AI client does that.
Server-only isolation flags: `--graphs-dir PATH`, `--local` (ignore Turso
credentials), `--slug NAME`.

| Command | What it does |
|---|---|
| `neuron gui` | The shared control center (installs Gray Matter on first run) |
| `neuron console [--watch]` | Read-only graph diagnostics |
| `neuron doctor` | Diagnose and repair the client registrations |
| `neuron manage` | Interactive day-to-day graph management |
| `neuron consolidate [--context C] [--no-merge] [--no-drop-orphans] [--sim-threshold 0.85]` | Merge near-duplicate concepts and archive orphans |
| `neuron config` | Read or change Neuron's settings (concepts per graph) |
| `neuron setup` | Install, update, repair |
| `neuron register` | Register Neuron in the AI clients |
| `neuron init` | Wire up the clients without loading the server |
| `neuron connect` | Connect and test a Turso Cloud database, then save it |
| `neuron start` / `stop` | Run Neuron in the background (HTTP bridge) |
| `neuron bridge` / `tunnel` | Expose the server over HTTP / over public HTTPS (cloudflared) |
| `neuron repair` | Reinstall Neuron only, choosing whether to wipe the memory |
| `neuron go-standalone` | Leave the gateway and register directly (undo: `gray-matter register --gateway`) |
| `neuron migrate` | Move graphs from the old `neuron5` slug |
| `neuron record-paths` | Record the source folder (used by the installer) |

---

## NeuRAG — `neurag`

### Add and search knowledge

| Command | What it does |
|---|---|
| `neurag ingest <path> [--godnode NAME] [--code]` | Turn a folder or one document into nodes, chunks, embeddings, links. Documents only unless `--code` |
| `neurag query "<question>" [--top-n 5] [--json]` | Search the knowledge base. Ask in the documents' language |
| `neurag recall "<question>"` | Search every layer, parked and archived nodes included |
| `neurag related <node>` | What else a node connects to (spreading activation) |
| `neurag confirm <node> <node> …` | These nodes were useful together: their links learn from it |
| `neurag tree` | The node tree |
| `neurag status` | Engine, database, node and chunk counts |

### Organize

| Command | What it does |
|---|---|
| `neurag archive <node> [--restore]` | Declare a node history: out of normal search, never deleted. `--restore` brings it back |
| `neurag park [--apply]` / `unpark <node>` | Move idle nodes to a dormant layer (dry run unless `--apply`) / bring one back |
| `neurag rename-node <old> <new>` | Rename a node and update its subtree |
| `neurag remove-node <node>` | **Delete** a node and its whole subtree |
| `neurag decay` | Weaken links and tags by the time since the last run |
| `neurag import <mapping.yaml>` | Bulk-import a folder tree from a YAML mapping |
| `neurag chunk <path>` → `add-node <name> <type>` → `add-chunks <node>` | The manual flow: chunk to JSON, create a node, attach the chunks |

### Health and installation

| Command | What it does |
|---|---|
| `neurag health` | Structural audit of the vault, read-only |
| `neurag doctor` | Environment and vault snapshot (tier, embedder, gateway) |
| `neurag config` | Read or change settings (embedding model, chunk size, …) |
| `neurag reindex` | Re-embed every chunk after changing the embedding model |
| `neurag gui` | The shared control center |
| `neurag start` / `stop` | Run NeuRAG in the background |
| `neurag register` / `deregister` | Add or remove NeuRAG in the AI clients (standalone) |
| `neurag go-standalone` | Leave the gateway (undo: `gray-matter register --gateway`) |
| `neurag repair` / `uninstall` | Reinstall NeuRAG only / uninstall it, optionally purging data |
| `neurag record-paths` | Record the source folder (used by the installer) |

---

## Next steps

- [MCP tools](TOOLS.md) — the same operations as AI tools
- [Configuration](CONFIGURATION.md) — settings and environment variables
- [Troubleshooting](TROUBLESHOOTING.md) — symptom → cause → fix
