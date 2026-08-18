# Data — database schemas, storage paths, backup and migration

> Where data lives, what the tables look like, and what the uninstaller touches.
> All schemas verified against source code.

---

## Neuron

### Storage location

| OS | Default path |
|---|---|
| Windows | `%LOCALAPPDATA%\neuron5\graphs\` |
| Linux | `~/.local/share/neuron5/graphs/` |

Override with `NS_GRAPHS_DIR`. Each context gets its own file: `graph_<context>.db`.
The `default` context stores in `graph_default.db`.

A seed database (`base_knowledge.db`) is bundled inside the package and read-only at runtime.

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

**Table: `episodes`**

| Column | Type | Constraints |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `keyword` | TEXT | NOT NULL |
| `turn` | INTEGER | NOT NULL |
| `text` | TEXT | NOT NULL |
| **PRIMARY KEY** | | `(context, keyword, turn)` |

Compact facts (max 200 chars) attached to keywords. Max 5 per node; oldest dropped during consolidation.

### Backup

Copy the `.db` file from the graph store directory. For Turso Cloud, use `turso db shell` or `turso db export`.

---

## Gray Matter

### Storage location

Root: `GM_HOME` (`%LOCALAPPDATA%\gray_matter` on Windows, `~/.local/share/gray_matter` on Linux).

### Files

| File | Format | Purpose |
|---|---|---|
| `config.json` | JSON | Tunable knob overrides (see [Configuration](CONFIGURATION.md)) |
| `bridges.json` | JSON | Cross-store bridge links (Neuron concept <-> NeuRAG node) |
| `manifest.json` | JSON | Install manifest: installed servers, hooks, data paths |

### bridges.json schema

Each entry:

```json
{
  "neuron": "concept_name",
  "neurag": "node_or_topic",
  "rationale": "why they connect",
  "weight": 1,
  "created_turn": 1,
  "last_used_turn": 5
}
```

Bridges reinforce their weight on each use (+1, capped at 1000). Unused bridges decay during idle periods (weight -1 after 7 days). At weight >= 5, the Neuron concept gets an auto-confirm.

---

## NeuRAG

### Storage location

| OS | Default path |
|---|---|
| All | `~/.local/share/neurag/knowledge.db` |

Override by passing `db_path` to `KnowledgeGraph()`.

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

Copy `~/.local/share/neurag/knowledge.db`.

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

There is no automated migration system. Schema changes are applied lazily at startup via `ALTER TABLE ADD COLUMN` (silently fails if column exists) and `CREATE TABLE IF NOT EXISTS`.

For Turso Cloud: run `neuron ensure-schema` once before multiple writers connect to avoid race conditions on a fresh shared DB.

---

## Next steps

- [Configuration](CONFIGURATION.md) — env vars and paths
- [Architecture](ARCHITECTURE.md) — how data flows through the system
- [Troubleshooting](TROUBLESHOOTING.md) — common data issues
