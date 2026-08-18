# Configuration — environment variables, config knobs, and data paths

> Single source of truth for every tunable across Neuron, Gray Matter, and NeuRAG.
> Values are verified against source code at the time of writing.

## Environment variables

### Neuron

| Variable | Default | Where read | Purpose |
|---|---|---|---|
| `NS_GRAPHS_DIR` | per-user (see Data paths) | `config.py:63` | Override graph store location |
| `NEURON_SLUG` | `"neuron5"` | `config.py:36` | Sub-directory name for the graph store (allows v5 beside older majors) |
| `NS_EMBED_MODEL` | `"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` | `server.py:163` | Embedding model name (384-dim). Changing requires full re-embed (`scripts/reembed.py`) |
| `NS_EMBED_DIM` | `"384"` | `models.py:76` | Embedding vector dimension. Must match `NS_EMBED_MODEL` |
| `NS_CONSOLIDATE_AUTO` | `""` (off) | `server.py:327` | Enable auto-consolidation every N turns (`"1"`, `"true"`, `"yes"`, `"on"` to enable) |
| `NEURON_CONSOLIDATE_EVERY` | `20` | `server.py:328` | Turns between auto-consolidation runs |
| `NEURON_CONSOLIDATE_PROTECT_SALIENCE` | `8` | `server.py:336` | Salience threshold: nodes at or above are never merged |
| `NEURON_TOPIC_SHIFT_THRESHOLD` | `0.3` | `server.py:135` | Cosine distance threshold for topic-shift detection |
| `NEURON_TANGENTIAL_EXPIRY_TURNS` | `5` | `models.py:45` | Inactive turns before tangential links are pruned |
| `NEURON_SALIENCE_DECAY_THRESHOLD` | `5` | `models.py:47` | Inactive turns before salience starts decaying |
| `NEURON_SALIENCE_DECAY_AMOUNT` | `1` | `models.py:48` | Salience points removed per decay tick |
| `NEURON_HEBBIAN_COOLDOWN` | `2` | `models.py:54` | Min turns between co-activation counts on the same link |
| `NEURON_HEBBIAN_UPGRADE_MEDIUM` | `3` | `models.py:55` | Co-activation count to promote tangential to medium |
| `NEURON_HEBBIAN_UPGRADE_STRONG` | `8` | `models.py:56` | Co-activation count to promote medium to strong |
| `NEURON_DRIFT_COOLDOWN` | `5` | `models.py:61` | Min turns between forming/reinforcing the same drift link |
| `NEURON_DRIFT_EXPIRY_TURNS` | `3` | `models.py:62` | Inactive turns before a drift link is pruned |
| `NEURON_SLEEP_IDLE_SECONDS` | `1800` (30 min) | `models.py:67` | Idle seconds before sleep-mode activates on next load |
| `NEURON_STAGE_FRESH_SECONDS` | `21600` (6h) | `models.py:68` | Staged stimulus validity duration |
| `NEURON_EPISODES_PER_NODE` | `5` | `models.py:71` | Max episodes (facts) per node |
| `NEURON_EPISODE_MAX_CHARS` | `200` | `models.py:72` | Max characters per episode (~40 tokens) |
| `NEURON_MAX_NODES` | `500` | `models.py:80` | Evict lowest-salience nodes beyond this cap |
| `NEURON_USER` | `""` | `server.py:1066` | Provenance tag for refs (`by` field in shared DB) |
| `TURSO_DATABASE_URL` | `""` | `db.py:41` | Remote Turso Cloud database URL |
| `TURSO_AUTH_TOKEN` | `""` | `db.py:42` | Remote Turso Cloud auth token |

### Gray Matter

| Variable | Default | Where read | Purpose |
|---|---|---|---|
| `GM_HOME` | `%LOCALAPPDATA%/gray_matter` (Win) or `~/.local/share/gray_matter` (Linux) | `paths.py` | Root directory for all GM data |
| `GM_PREWARM` | `"1"` if `prewarm` is True | `server.py` | Disable worker pre-warming at startup (`"0"` to skip) |
| `GM_NEURON_CLIENTS` | (auto-detected) | `executor.py` | Override path to Neuron client assets directory |
| `GM_GUI_NOBROWSER` | (unset) | `webgui.py` | If set, skip auto-opening browser for web GUI |
| `GM_GUI_SELFTEST` | (unset) | `webgui.py` | If set, auto-close webview after 1s (testing) |
| `GM_TURSO_DATABASE_URL` | (empty) | `bridges.py` | Cloud tier for GM bridges — its OWN Turso DB (`gm_bridges`), never Neuron's/NeuRAG's |
| `GM_TURSO_AUTH_TOKEN` | falls back to `TURSO_AUTH_TOKEN` | `bridges.py` | Auth token for the bridges DB (can be the shared group token) |
| `GRAY_MATTER_BRIDGES` | `<GM_HOME>/bridges.db` | `bridges.py` | Local bridges store path override (a legacy `.json` value migrates once to its `.db` sibling) |
| `GM_ENV_FILE` | `<GM_HOME>/.env` | `_env.py` | Explicit path to the GM-level `.env` |
| `GM_NO_DOTENV` | (unset) | `_env.py` | If set, skip loading the GM-level `.env` |

The GM daemon loads `<GM_HOME>/.env` at startup (real env always wins; disabled
under pytest). Spawned workers inherit the daemon's environment, so this one
file can carry the whole trio's cloud credentials: `TURSO_*` (Neuron),
`NEURAG_TURSO_*` (NeuRAG), `GM_TURSO_*` (bridges) — three SEPARATE databases,
one optional shared group token. Two ways to fill it, both idempotent:
`gray-matter cloud setup` auto-provisions group/DBs/token — if the `turso` CLI
is missing it offers to install it (official installer, pinned via
`GM_TURSO_CLI_VERSION`; opt out with `--no-cli-install` / `GM_TURSO_CLI_INSTALL=0`,
manual guide printed on decline) — while `gray-matter cloud wire --neuron-url … --neurag-url …
--gm-url …` needs NO turso CLI — paste the URLs (and one token) from the Turso
dashboard; partial wiring is fine. The "Cloud group…" GUI panel exposes both.
`cloud status` reports each component's tier; `cloud teardown` unwires the env
vars without touching the cloud DBs.

### NeuRAG

| Variable | Default | Where read | Purpose |
|---|---|---|---|
| `NEURAG_EMBEDDER` | `"auto"` | `embedder.py:56` | Embedder selection: `auto` (fastembed if available), `fastembed` (strict), `null` (lexical only) |
| `NEURAG_EMBED_MODEL` | `"sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"` | `embedder.py:20` | Overrides FastEmbed model name |
| `NS_EMBED_MODEL` | (same as above) | `embedder.py:21` | Shared with Neuron — single env governs both |
| `NEURAG_TURSO_DATABASE_URL` | (empty) | `db.py` | Remote Turso Cloud database URL — NeuRAG's OWN DB (never Neuron's: they collide on `nodes`) |
| `NEURAG_TURSO_AUTH_TOKEN` | falls back to `TURSO_AUTH_TOKEN` | `db.py` | Auth token (can be the shared group token) |

## Gray Matter config knobs

Managed via `gray-matter config get|set|list`. Stored in `config.json` inside `GM_HOME`.

| Key | Default | Type | Purpose |
|---|---|---|---|
| `flash_min_gap` | `3` | int | Min pulses between flash events (anti-spam) |
| `stimulus_safety_net` | `true` | bool | GM re-launches the stimulus when Neuron's piggyback goes silent (LLM forgot the tools) |
| `stimulus_safety_gap` | `5` | int | Tool turns without 🧠/⚡ before the safety net fires |
| `cache_ttl_seconds` | `60` | float | Base TTL for the context cache |
| `cache_max_size` | `100` | int | LRU cap for the context cache |
| `prewarm` | `true` | bool | Pre-warm persistent workers at start |
| `heartbeat_interval` | `5.0` | float | Server liveness ping interval (seconds) |
| `idle_sleep_timeout` | `600.0` | float | Seconds of idle before servers are marked sleeping |

## NeuRAG config knobs

Managed via `neurag config get|set|list` (and, when Gray Matter is installed, from the control center — a dedicated **Settings card** renders each knob as a toggle/picker that saves on change; knobs self-describe via `settings.HELP`/`SUGGEST`). Stored in `~/.local/share/neurag/config.json`, a file **separate from `knowledge.db`** so a DB rebuild never touches settings. Works for every install, including NeuRAG standalone.

| Key | Default | Type | Purpose |
|---|---|---|---|

The cross-encoder rerank stage was removed in 2026-07: measured on the benchmark it left recall@5 unchanged, made the *concept* half of MRR worse (0.780 → 0.741) and cost 17x latency (397ms → 6815ms per query). The rule worth keeping: `recall@50 − recall@5` is the ceiling of any reranker, since it reorders and never retrieves — measure that before adding one back.

## Data paths

### Neuron graph store

Resolved by `config.py:graphs_dir()`:

| OS | Default path |
|---|---|
| Windows | `%LOCALAPPDATA%\neuron5\graphs\` |
| Linux | `~/.local/share/neuron5/graphs/` |

Override with `NS_GRAPHS_DIR`. Each context gets its own file: `graph_<context>.db`.

### Gray Matter data

Root: `GM_HOME` (`%LOCALAPPDATA%\gray_matter` on Windows, `~/.local/share/gray_matter` on Linux).

| File/Dir | Purpose |
|---|---|
| `config.json` | Tunable knobs (overrides only) |
| `bridges.json` | Cross-store bridge links |
| `manifest.json` | Install manifest (installed servers, hooks, data paths) |

### NeuRAG data

| OS | Default path |
|---|---|
| All | `~/.local/share/neurag/knowledge.db` |

Override by passing `db_path` to `KnowledgeGraph()`.

## Storage tiers (degradation)

### Neuron

| Tier | Engine | Vector search | When |
|---|---|---|---|
| Remote Turso (cloud) | libsql-client | SQL `vector_distance_cos()` | `TURSO_DATABASE_URL` + `TURSO_AUTH_TOKEN` set, `libsql-client` installed |
| Local pyturso | pyturso | SQL `vector_distance_cos()` | pyturso installed, no cloud creds |
| SQLite fallback | sqlite3 | Python brute-force cosine | Neither pyturso nor cloud available |

Check current tier: `neuron status` output shows `Engine: Turso (cloud)`, `Turso (local)`, or `SQLite`.

### NeuRAG

| Tier | Engine | Vector search | When |
|---|---|---|---|
| Local pyturso | pyturso | SQL `vector_distance_cos()` | pyturso installed |
| SQLite fallback | sqlite3 | Python brute-force cosine or TF-IDF | pyturso not available |

Check current tier: `gray-matter doctor` shows `NeuRAG vector tier DEGRADED` when on sqlite3.

## Version reference

At the time of writing (July 2026):

| Component | Version | Source |
|---|---|---|
| Neuron | 6.1.0 | `pyproject.toml` |
| Gray Matter | 1.1.0 | `__version__.py` |
| NeuRAG | 1.2.0 | `pyproject.toml` |
| MCP protocol | >=1.28.0,<2.0 | Neuron `pyproject.toml` |
| pyturso | ==0.6.1 | Neuron `pyproject.toml` (pinned) |
| fastembed | >=0.5.0,<1.0 | Neuron `pyproject.toml` |
