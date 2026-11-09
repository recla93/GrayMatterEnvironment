# Data — database schemas, storage paths, backup and migration

> Where data lives, what the tables look like, and what the uninstaller touches.
> All schemas verified against source code.

---

## Where everything lives

All three tools keep their data under **one suite folder**:

| OS | Suite folder |
|---|---|
| Windows | `%LOCALAPPDATA%\GrayMatterEnvironment\` |
| Linux / macOS | `$XDG_DATA_HOME/GrayMatterEnvironment/`, default `~/.local/share/GrayMatterEnvironment/` |

| Inside it | What |
|---|---|
| `neuron/graphs/` | Neuron's memory: one `graph_<context>.db` per context |
| `neurag/knowledge.db`, `neurag/config.json` | NeuRAG's knowledge base and settings |
| `graymatter/` | Gray Matter: `bridges.db`, `config.json`, `manifest.json`, `pids.json`, `state.db` |
| `registry/` | Which tools are installed and where (read by the control center) |
| `backups/` | The daily copy of the three stores |

`gray-matter doctor` and the control center show the real paths on your machine.
Older installs used separate roots (`neuron5`, `~/.local/share/neurag` on every OS):
they are moved under the suite folder on start.

---

## Neuron

### Storage location

`<suite>/neuron/graphs/`, one file per context: `graph_<context>.db` (`default` →
`graph_default.db`). Override with `NS_GRAPHS_DIR`.

Neuron ships no seed database: a new context starts empty. Versions before 6.9.0 shipped one
(`base_knowledge.db`, Neuron's own manual). Seed nodes that versions before 6.6 copied into a
graph are removed on load, unless the user worked with them (topic rewritten, a fact, a link
of theirs).

### Schema (per graph file)

**Table: `meta`**

| Column | Type | Constraints |
|---|---|---|
| `key` | TEXT | PRIMARY KEY |
| `value` | TEXT | |

Stores domain-hysteresis counters (`signal_domain`, `signal_count`).

**Table: `nodes`**

| Column | Type | Default | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `context` | TEXT | `'default'` | Scoping key for multi-context in one DB |
| `keyword` | TEXT | | The concept name (lowercase) |
| `turn` | INTEGER | | Turn when last active |
| `topic` | TEXT | | Topic of the turn |
| `domain` | TEXT | | Domain label (e.g. `backend`, `AI`) |
| `sentiment` | TEXT | | `neutral`, `positive`, `critical`, `urgent` |
| `salience` | INTEGER | | Hebbian reinforcement score |
| `entities` | TEXT | `'[]'` | JSON array |
| `tags` | TEXT | `'[]'` | JSON array |
| `refs` | TEXT | `'[]'` | JSON array |
| `trust` | REAL | `0` | Trust score (0-1, feeds ranking) |

**Table: `node_vectors`**

| Column | Type | Constraints |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `keyword` | TEXT | NOT NULL |
| `embedding` | BLOB | NOT NULL (384-dim float32 packed with `struct.pack`) |
| `dim` | INTEGER | NOT NULL |
| **PRIMARY KEY** | | `(context, keyword)` |

**Table: `links`**

| Column | Type | Default | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `context` | TEXT | `'default'` | |
| `source` | TEXT | | Source keyword |
| `target` | TEXT | | Target keyword |
| `link_type` | TEXT | | `cause-effect`, `analogy`, `evolution`, `contrast`, `deepening`, `instance-of` |
| `weight` | TEXT | | `strong`, `medium`, `tangential` |
| `rationale` | TEXT | | Human-readable reason |
| `created_turn` | INTEGER | | Turn when created |
| `last_active_turn` | INTEGER | | Turn when last reinforced |
| `inactive_turns` | INTEGER | | Consecutive turns without activity |
| `co_activation_count` | INTEGER | `0` | Hebbian reinforcement counter |
| `target_context` | TEXT | | For drift links: the foreign context |

**Indexes:** `idx_links_source` on `source`, `idx_links_target` on `target`, `idx_links_turn` on `created_turn`.

**Table: `_graveyard`**

| Column | Type | Notes |
|---|---|---|
| `context` | TEXT | |
| `keyword` | TEXT | |
| `salience` | INTEGER | |
| `domain` | TEXT | |
| `reason` | TEXT | Why archived |
| `turn` | INTEGER | |

Low-salience orphans are archived here (recoverable via `export`).

**Table: `refs`**

| Column | Type | Constraints |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `keyword` | TEXT | NOT NULL |
| `path` | TEXT | NOT NULL |
| `project_id` | TEXT | NOT NULL, DEFAULT `''` |
| `by` | TEXT | NOT NULL, DEFAULT `''` |
| **PRIMARY KEY** | | `(context, keyword, path, project_id, by)` |

**Table: `facts`** — the unit of memory (ADR-015)

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` | |
| `id` | TEXT | NOT NULL | Short id shown as `#0a1b2c3d` |
| `kind` | TEXT | NOT NULL | `progress`, `decision`, `fix`, `fact`, `idea`, `user`, `habit` |
| `text` | TEXT | NOT NULL | One sentence with its why |
| `turn` | INTEGER | | Turn it was saved in |
| `created_at` | TEXT | NOT NULL | |
| `source` | TEXT | NOT NULL | Where it came from (`migration` for facts converted from old episodes) |
| `supersedes` | TEXT | | Id of the fact it replaces |
| `status` | TEXT | NOT NULL, DEFAULT `'active'` | `superseded` once a newer fact replaces it |
| `owner`, `space` | TEXT | DEFAULT `''` | Who wrote it, for shared stores |
| `confirmed` | INTEGER | NOT NULL, DEFAULT 0 | How many times it was confirmed useful |
| **PRIMARY KEY** | | `(context, id)` | |

Facts are **append-only**: nothing evicts them, merging or archiving a concept
does not delete them, and a newer fact marks the older one `superseded`.

**Table: `fact_concepts`** — the index from facts to concepts

| Column | Type | Constraints |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `fact_id` | TEXT | NOT NULL |
| `keyword` | TEXT | NOT NULL |
| **PRIMARY KEY** | | `(context, fact_id, keyword)` |

**Table: `episodes`** — legacy

Before 6.10.0 a fact was an "episode" attached to a keyword (max 5 per node, the
oldest dropped). The table is still read, never written: on load every episode
is converted once into a `fact` with `source = 'migration'`.

### Backup

Two layers, local tier only (for Turso Cloud use `turso db export`):

- **Neuron's own**: on the first open of a graph each day, `db.snapshot()` writes `<graphs>/_backups/<name>.<YYYY-MM-DD>.db` (keeps `NEURON_BACKUP_KEEP`, default 5) plus `<name>.pre-consolidate.db` before every consolidation.
- **Suite-level** (Gray Matter, below): one folder per day with all three stores.

---

## Gray Matter

### Storage location

`<suite>/graymatter/` (override with `GM_HOME`).

### Files

| File | Format | Purpose |
|---|---|---|
| `bridges.db` | SQLite / Turso | Cross-store bridges (Neuron concept ↔ NeuRAG node) |
| `config.json` | JSON | Setting overrides (see [Configuration](CONFIGURATION.md)) |
| `manifest.json` | JSON | Install manifest: what was registered and written, so uninstall removes exactly that |
| `pids.json` | JSON | The suite's running processes (for `reap` and `doctor`) |
| `state.db` | SQLite | Daemon state |

### Backup

The daemon copies the three stores once a day into `<suite root>/backups/`:

```
gm-graph-backup_2026-09-13/
  gray-matter/  bridges.db
  neuron/       graph_*.db  _cross_links.json
  neurag/       knowledge.db  config.json
```

Keeps the last 7 days (`GM_BACKUP_KEEP`, `0` disables). Sources are `paths.data_paths()`, the same inventory the uninstaller reads. SQLite files are copied through the backup API over a `mode=ro` connection, so a live WAL is folded into the copy and left untouched for the worker. `gray_matter backup` runs it by hand (no daemon needed); `--force` redoes today's folder — the automatic copy is from the start of the day, so run it before anything that does not undo.

### Bridges

Each bridge has: `neuron` (a concept, or `#id` of a fact), `neurag` (the exact
name of an existing node), `rationale`, `weight`, `created`, `last_used`,
`promoted`.

Bridges are created only on purpose — `gray_matter_bridge`, `gray-matter promote`,
or the control center — never by a pulse or a flash. Showing a bridge reinforces
its weight (+1, capped at 1000); unused bridges decay during idle periods (weight
-1 after 7 days unused, removed below 1.0). See them with `gray-matter bridges`
or in the control center's **Bridge** view.

---

## NeuRAG

### Storage location

`<suite>/neurag/knowledge.db`, settings in `<suite>/neurag/config.json`.

### Schema

**Table: `nodes`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | id=0 is the absolute root (`/`) |
| `name` | TEXT | NOT NULL | Display name |
| `node_type` | TEXT | NOT NULL, CHECK IN (`godnode`, `fundamental`, `specialization`) | Three-tier hierarchy |
| `parent_id` | INTEGER | FK `nodes(id)` ON DELETE CASCADE | NULL for root |
| `path` | TEXT | NOT NULL | Materialized path (e.g. `/Java/Spring_Boot`) |
| `tags` | TEXT | DEFAULT `'[]'` | JSON array of tag keywords |
| `triggers` | TEXT | DEFAULT `'[]'` | JSON array of trigger keywords (for fast lookup) |
| `created_at` | TEXT | DEFAULT `datetime('now')` | |
| `layer` | INTEGER | DEFAULT 2 | 2 = active, 3 = dormant (parked or archived as history), 4 = deep dormant. Nothing in a dormant layer is deleted; it is only left out of the default search |
| `last_used` | TEXT | | When the node last answered something (parking reads this) |

**Indexes:** `idx_nodes_parent` on `parent_id`, `idx_nodes_path` on `path`.

**Seed data:** `INSERT OR IGNORE INTO nodes (id, name, node_type, parent_id, path) VALUES (0, '/', 'godnode', NULL, '/')`.

**Table: `chunks`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `node_id` | INTEGER | NOT NULL, FK `nodes(id)` ON DELETE CASCADE | Parent node |
| `text` | TEXT | NOT NULL | The chunk content |
| `source` | TEXT | nullable | Original file path |
| `section` | TEXT | nullable | Heading/section within the source |
| `chunk_index` | INTEGER | DEFAULT 0 | Order within the file |
| `embedding` | BLOB | nullable | 384-dim float32 vector (packed with `struct.pack`) |
| `created_at` | TEXT | DEFAULT `datetime('now')` | |
| `doc_date` | TEXT | nullable | Date of the document, `YYYY-MM-DD`: from the file name, its first lines, or its last modification. At equal relevance search prefers the newer document |

**Index:** `idx_chunks_node` on `node_id`.

**Table: `node_links`**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `source_id` | INTEGER | NOT NULL, FK `nodes(id)` ON DELETE CASCADE | |
| `target_id` | INTEGER | NOT NULL, FK `nodes(id)` ON DELETE CASCADE | |
| `link_type` | TEXT | NOT NULL, CHECK IN (`tag_overlap`, `cross_ref`, `semantic`) | `semantic` defined in schema but not built by current `rebuild_links()` |
| `weight` | REAL | DEFAULT 1.0 | 0.0-1.0 Jaccard or normalized chunk overlap |
| `evidence` | TEXT | DEFAULT `''` | Human-readable justification |
| `created_at` | TEXT | DEFAULT `datetime('now')` | |
| `updated_at` | TEXT | DEFAULT `datetime('now')` | |
| **PRIMARY KEY** | | `(source_id, target_id, link_type)` | One link per type per pair |

**Indexes:** `idx_links_source` on `source_id`, `idx_links_target` on `target_id`.

### Backup

No backup of its own: the suite-level daily copy (Gray Matter, above) includes `knowledge.db` and `config.json`. Standalone: copy `knowledge.db`.

---

## What the uninstaller touches

| Component | `gray-matter uninstall` | `--purge-data` |
|---|---|---|
| Gray Matter code | Removed | Removed |
| GM hooks in MCP clients | Deregistered | Deregistered |
| `GM_HOME` (config, bridges, manifest) | Interactive prompt per path | Removed without asking |
| Neuron graph store | Interactive prompt | Removed if confirmed |
| NeuRAG knowledge.db | Interactive prompt | Removed if confirmed |

---

## Migration

Migrations run **at startup**, idempotent, with no command to remember:

- **Neuron** brings every graph file of an older version up to the current schema
  when the server (or Gray Matter's worker) starts — not the day a context is next
  opened. It takes the daily backup first, then converts old episodes into facts.
- **NeuRAG** adds new columns with `ALTER TABLE ADD COLUMN` and fills `doc_date`
  for existing chunks from their source files, without a re-ingest.
- **Gray Matter** moves data from the old separate roots under the suite folder.

New tables use `CREATE TABLE IF NOT EXISTS`.

For Turso Cloud: run `neuron ensure-schema` once before multiple writers connect to avoid race conditions on a fresh shared DB.

---

## Next steps

- [Configuration](CONFIGURATION.md) — env vars and paths
- [Architecture](ARCHITECTURE.md) — how data flows through the system
- [Troubleshooting](TROUBLESHOOTING.md) — common data issues
