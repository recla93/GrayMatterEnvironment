# Dati — schemi database, percorsi di storage, backup e migrazione

> Dove vivono i dati, come sono strutturate le tabelle, e cosa tocca il disinstallatore.
> Tutti gli schemi verificati contro il codice sorgente.

---

## Neuron

### Posizione storage

| SO | Percorso predefinito |
|---|---|
| Windows | `%LOCALAPPDATA%\neuron5\graphs\` |
| Linux | `~/.local/share/neuron5/graphs/` |

Sovrascrivere con `NS_GRAPHS_DIR`. Ogni contesto ha il suo file: `graph_<context>.db`.
Il contesto `default` si memorizza in `graph_default.db`.

Un database seed (`base_knowledge.db`) e bundled nel package e read-only a runtime.

### Schema (per file grafo)

**Tabella: `meta`**

| Colonna | Tipo | Vincoli |
|---|---|---|
| `key` | TEXT | PRIMARY KEY |
| `value` | TEXT | |

Memorizza contatori di isteresi del dominio (`signal_domain`, `signal_count`).

**Tabella: `nodes`**

| Colonna | Tipo | Default | Note |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `context` | TEXT | `'default'` | Chiave di scope per multi-contesto in un solo DB |
| `keyword` | TEXT | | Nome del concetto (minuscolo) |
| `turn` | INTEGER | | Turno di ultima attivita |
| `topic` | TEXT | | Topic del turno |
| `domain` | TEXT | | Label dominio (es. `backend`, `AI`) |
| `sentiment` | TEXT | | `neutral`, `positive`, `critical`, `urgent` |
| `salience` | INTEGER | | Punteggio di rinforzo hebbiano |
| `entities` | TEXT | `'[]'` | Array JSON |
| `tags` | TEXT | `'[]'` | Array JSON |
| `refs` | TEXT | `'[]'` | Array JSON |
| `trust` | REAL | `0` | Punteggio fiducia (0-1, alimenta il ranking) |

**Tabella: `node_vectors`**

| Colonna | Tipo | Vincoli |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `keyword` | TEXT | NOT NULL |
| `embedding` | BLOB | NOT NULL (float32 384-dim impacchettato con `struct.pack`) |
| `dim` | INTEGER | NOT NULL |
| **PRIMARY KEY** | | `(context, keyword)` |

**Tabella: `links`**

| Colonna | Tipo | Default | Note |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `context` | TEXT | `'default'` | |
| `source` | TEXT | | Keyword sorgente |
| `target` | TEXT | | Keyword target |
| `link_type` | TEXT | | `strong`, `medium`, `tangential`, `drift` |
| `weight` | TEXT | | Nome classe peso |
| `rationale` | TEXT | | Motivazione leggibile |
| `created_turn` | INTEGER | | Turno di creazione |
| `last_active_turn` | INTEGER | | Turno di ultimo rafforzamento |
| `inactive_turns` | INTEGER | | Turni consecutivi senza attivita |
| `co_activation_count` | INTEGER | `0` | Contatore rinforzo hebbiano |
| `target_context` | TEXT | | Per link drift: il contesto straniero |

**Indici:** `idx_links_source` su `source`, `idx_links_target` su `target`, `idx_links_turn` su `created_turn`.

**Tabella: `_graveyard`**

| Colonna | Tipo | Note |
|---|---|---|
| `context` | TEXT | |
| `keyword` | TEXT | |
| `salience` | INTEGER | |
| `domain` | TEXT | |
| `reason` | TEXT | Perche archiviato |
| `turn` | INTEGER | |

Gli orfani a bassa salience vengono archiviati qui (recuperabili via `export`).

**Tabella: `refs`**

| Colonna | Tipo | Vincoli |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `keyword` | TEXT | NOT NULL |
| `path` | TEXT | NOT NULL |
| `project_id` | TEXT | NOT NULL, DEFAULT `''` |
| `by` | TEXT | NOT NULL, DEFAULT `''` |
| **PRIMARY KEY** | | `(context, keyword, path, project_id, by)` |

**Tabella: `episodes`**

| Colonna | Tipo | Vincoli |
|---|---|---|
| `context` | TEXT | NOT NULL, DEFAULT `'default'` |
| `keyword` | TEXT | NOT NULL |
| `turn` | INTEGER | NOT NULL |
| `text` | TEXT | NOT NULL |
| **PRIMARY KEY** | | `(context, keyword, turn)` |

Fatti compatti (max 200 caratteri) allegati alle keyword. Max 5 per nodo; i piu vecchi vengono eliminati durante il consolidamento.

### Backup

Copia il file `.db` dalla directory del graph store. Per Turso Cloud, usa `turso db shell` o `turso db export`.

---

## Gray Matter

### Posizione storage

Radice: `GM_HOME` (`%LOCALAPPDATA%\gray_matter` su Windows, `~/.local/share/gray_matter` su Linux).

### File

| File | Formato | Scopo |
|---|---|---|
| `config.json` | JSON | Override knob (vedi [Configurazione](CONFIGURATION.it.md)) |
| `bridges.json` | JSON | Link bridge cross-store (concetto Neuron <-> nodo NeuRAG) |
| `manifest.json` | JSON | Manifest install: server installati, hook, percorsi dati |

### Schema bridges.json

Ogni voce:

```json
{
  "neuron": "nome_concetto",
  "neurag": "nodo_o_topic",
  "rationale": "perche sono collegati",
  "weight": 1,
  "created_turn": 1,
  "last_used_turn": 5
}
```

I bridge rafforzano il loro peso ad ogni uso (+1, cap a 1000). I bridge inutilizzati decadono durante i periodi di idle (peso -1 dopo 7 giorni). A peso >= 5, il concetto Neuron riceve un auto-confirm.

---

## NeuRAG

### Posizione storage

| SO | Percorso predefinito |
|---|---|
| Tutti | `~/.local/share/neurag/knowledge.db` |

Sovrascrivere passando `db_path` a `KnowledgeGraph()`.

### Schema

**Tabella: `nodes`**

| Colonna | Tipo | Vincoli | Note |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | id=0 e la radice assoluta (`/`) |
| `name` | TEXT | NOT NULL | Nome visualizzato |
| `node_type` | TEXT | NOT NULL, CHECK IN (`godnode`, `fundamental`, `specialization`) | Gerarchia a tre livelli |
| `parent_id` | INTEGER | FK `nodes(id)` ON DELETE CASCADE | NULL per la radice |
| `path` | TEXT | NOT NULL | Percorso materializzato (es. `/Java/Spring_Boot`) |
| `tags` | TEXT | DEFAULT `'[]'` | Array JSON di keyword tag |
| `triggers` | TEXT | DEFAULT `'[]'` | Array JSON di keyword trigger (per ricerca veloce) |
| `created_at` | TEXT | DEFAULT `datetime('now')` | |

**Indici:** `idx_nodes_parent` su `parent_id`, `idx_nodes_path` su `path`.

**Dati seed:** `INSERT OR IGNORE INTO nodes (id, name, node_type, parent_id, path) VALUES (0, '/', 'godnode', NULL, '/')`.

**Tabella: `chunks`**

| Colonna | Tipo | Vincoli | Note |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | |
| `node_id` | INTEGER | NOT NULL, FK `nodes(id)` ON DELETE CASCADE | Nodo padre |
| `text` | TEXT | NOT NULL | Contenuto del chunk |
| `source` | TEXT | nullable | Percorso file originale |
| `section` | TEXT | nullable | Intestazione/sezione nel sorgente |
| `chunk_index` | INTEGER | DEFAULT 0 | Ordine nel file |
| `embedding` | BLOB | nullable | Vettore float32 384-dim (impacchettato con `struct.pack`) |
| `created_at` | TEXT | DEFAULT `datetime('now')` | |

**Indice:** `idx_chunks_node` su `node_id`.

**Tabella: `node_links`**

| Colonna | Tipo | Vincoli | Note |
|---|---|---|---|
| `source_id` | INTEGER | NOT NULL, FK `nodes(id)` ON DELETE CASCADE | |
| `target_id` | INTEGER | NOT NULL, FK `nodes(id)` ON DELETE CASCADE | |
| `link_type` | TEXT | NOT NULL, CHECK IN (`tag_overlap`, `cross_ref`, `semantic`) | `semantic` definito nello schema ma non costruito da `rebuild_links()` attuale |
| `weight` | REAL | DEFAULT 1.0 | 0.0-1.0 Jaccard o overlap normalizzato |
| `evidence` | TEXT | DEFAULT `''` | Giustificazione leggibile |
| `created_at` | TEXT | DEFAULT `datetime('now')` | |
| `updated_at` | TEXT | DEFAULT `datetime('now')` | |
| **PRIMARY KEY** | | `(source_id, target_id, link_type)` | Un link per tipo per coppia |

**Indici:** `idx_links_source` su `source_id`, `idx_links_target` su `target_id`.

---

## Cosa tocca il disinstallatore

| Componente | `gray-matter uninstall` | `--purge-data` |
|---|---|---|
| Codice Gray Matter | Rimosso | Rimosso |
| Hook GM nei client MCP | deregistrati | deregistrati |
| `GM_HOME` (config, bridge, manifest) | Prompt interattivo per percorso | Rimosso senza chiedere |
| Graph store Neuron | Prompt interattivo | Rimosso se confermato |
| knowledge.db NeuRAG | Prompt interattivo | Rimosso se confermato |

---

## Migrazione

Non esiste un sistema automatico di migrazione. Le modifiche allo schema vengono applicate pigramente all'avvio via `ALTER TABLE ADD COLUMN` (fallisce silenziosamente se la colonna esiste) e `CREATE TABLE IF NOT EXISTS`.

Per Turso Cloud: eseguire `neuron ensure-schema` una volta prima che piu writer si connettano per evitare condizioni di gara su un DB condiviso fresco.

---

## Prossimi passi

- [Configurazione](CONFIGURATION.it.md) — env var e percorsi
- [Architettura](ARCHITECTURE.it.md) — come i dati fluiscono nel sistema
- [Risoluzione problemi](TROUBLESHOOTING.it.md) — problemi comuni con i dati
