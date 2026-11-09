# Getting started — end-to-end tutorial

> Install → check → first memory → first knowledge → the control center.
> About 10 minutes. Every step shows what you should see.

## Prerequisites

- Python 3.10 or later (the installer can install it for you)
- An MCP client: Claude Desktop, Claude Code, Cursor, VS Code, OpenCode, …

## Step 1: install

### Option A — one-click installer (recommended)

| Where you got it | Windows | macOS / Linux |
|---|---|---|
| The `gray-matter` release download | double-click `install.cmd` | double-click `install.command`, or `sh install.sh` |
| This repository (`GrayMatterEnvironment`) | double-click `gray_matter\install.cmd` | `sh gray_matter/install.sh` |

It finds or installs Python, creates **one shared venv**, installs Gray Matter +
Neuron + NeuRAG, registers **only the gateway** (`gray-matter`) in every MCP client
it detects (with `.bak` backups), deploys the memory hooks, and puts a
**Gray Matter** shortcut on the desktop.

### Option B — pip, from a source checkout

```bash
git clone https://github.com/recla93/GrayMatterEnvironment.git
cd GrayMatterEnvironment

# Windows: pyturso comes from the vendored wheels
pip install --find-links neuron/vendor -e gray_matter -e neuron -e neurag
# macOS / Linux
pip install -e gray_matter -e neuron -e neurag

gray-matter install          # register the gateway in your MCP clients
```

**Restart your AI apps** after installing: they load the tool list only at start.

## Step 2: check

```bash
gray-matter doctor
```

You should see a block of `[ok]` lines about the installation (registry, hooks,
client entries, versions, processes), then:

```
Gray-Matter v1.8.0 — awake
  cache: 0 entries | bridges: 0
  [ok] neuron (alive, collab) worker+
  [ok] neurag (alive, collab) worker+
```

Every `[!!]` line comes with the fix on the line below it (`->`). Right after a
start NeuRAG may be missing for a few seconds: its worker is still loading the
model. If you see `[DEAD]`, run `gray-matter stop` then `gray-matter start`.

## Step 3: the memory loop

Your AI client does this on its own, guided by the instructions the gateway sends
it. It helps to know what it does:

1. **Before replying** it calls `pre_turn(topic=…)` and gets the facts the memory
   holds on that topic, each with an id like `#0a1b2c3d`. On a fresh install there
   are none: the memory starts empty and fills with use.
2. **After replying** it saves what is worth not repeating, as **facts**:

```
store_turn(facts=[{
  "kind": "decision",
  "text": "Tests use pytest fixtures, not unittest setUp: fixtures compose and need no base class.",
  "concepts": ["pytest", "fixtures"]
}])
```

A fact is one sentence with its why. `kind` is one of `progress`, `decision`,
`fix`, `fact`, `idea`, `user`, `habit`; `concepts` are 1-5 nouns that index it.
A fact that changes an older one passes `supersedes="<its id>"`: nothing is
deleted, the old one stops being shown.

3. When a recalled fact helped, `confirm(facts=["#0a1b2c3d"])` tells the memory so.

With Claude Code the installer also adds two hooks: one brings the memory in
before your message is read, the other checks at the end of a turn that the facts
were saved.

## Step 4: index your documents

Ask your AI, or call directly:

```
knowledge_ingest(path="/path/to/your/docs")
```

It returns a job id at once and works in the background (`knowledge_ingest_status`
to follow it). It creates nodes from the folder tree, chunks, embeddings and
links. Documents only by default (`.md .txt .pdf .docx`); add `code=true` for
source code. Re-ingesting a file replaces its chunks.

From the terminal the same is:

```bash
neurag ingest /path/to/your/docs
```

## Step 5: ask your documents

```
knowledge_query(query="how to configure logging", top_n=3)
```

Ask in the **language of the documents**: a question in another language finds
much less. Each result shows its node, source and date; at equal relevance the
newer document wins.

Old material you want to keep but not see every time can be declared history:

```bash
neurag archive "old-notes"            # out of normal search, never deleted
neurag archive "old-notes" --restore  # back again
```

`knowledge_query(..., archive=true)` still searches it.

## Step 6: memory + knowledge together

```
gray_matter_pulse(topic="logging")
```

One call: the memory's facts, the knowledge excerpts, the **bridges** you saved
between a memory concept and a knowledge node, and sometimes a **flash** — an old
idea or decision related to the topic.

A bridge is created on purpose, never automatically:

```
gray_matter_bridge(neuron_concept="logging", neurag_node="observability",
                   rationale="our logging rules live in the observability notes")
```

The NeuRAG end must be an existing node, by its exact name.

## Step 7: the control center

Open the **Gray Matter** shortcut on the desktop, or run `gray-matter gui`.

| Section | What you do there |
|---|---|
| Panoramica | state of the three tools, memory and knowledge counts |
| Grafi | the memory and the knowledge as an interactive graph; drag between them to create a bridge |
| Comandi operativi | everyday commands, one block per tool |
| Manutenzione grafo | clean, archive, back up |
| Manutenzione tool | install, repair, diagnose |
| Impostazioni | every setting of every tool, explained, with "reset to default" |
| Bridge | list, filter, create, edit, delete bridges — with the list of available nodes on both sides |
| Guida e legenda | what every symbol and word means |

Every command shows what it does, its arguments explained, and the exact command
line to copy.

If a banner says the control center **lost its server**, its process was closed —
usually by a reinstall, which stops every process of the venv. Close the window
and open Gray Matter again.

## Step 8: uninstall (optional)

```bash
gray-matter uninstall                 # the app only
gray-matter uninstall --purge-data    # also the memory, the knowledge and the bridges
```

The memory is never deleted without `--purge-data`.

---

## What just happened

1. **Gray Matter** runs as a background daemon. Your AI client sees one MCP server,
   `gray-matter`, and through it every tool of Neuron and NeuRAG.
2. **Neuron** keeps the memory of your conversations as typed facts, indexed by
   concepts. It starts empty.
3. **NeuRAG** keeps the knowledge from your documents, dated, in a tree of nodes.
4. **Bridges** are the links you make between the two; Gray Matter keeps them.

## Next steps

- [Tools](TOOLS.md) — every tool and parameter
- [CLI](CLI.md) — the same from the terminal
- [Configuration](CONFIGURATION.md) — settings and environment variables
- [Architecture](ARCHITECTURE.md) — how it works inside
- [Troubleshooting](TROUBLESHOOTING.md) — symptom → cause → fix
