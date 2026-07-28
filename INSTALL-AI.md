# INSTALL-AI — Gray Matter (full suite: GM + bundled Neuron + NeuRAG)

> Instructions for an AI agent. Run in order, stop at the first error.
> This repo BUNDLES both tools as subdirectories (`neuron/`, `neurag/`) —
> the zip is self-contained. Model: MCP clients talk ONLY to `gray-matter`
> (the gateway); the tools run as GM-managed workers.

## 1. Install (one step — the unified installer does everything)

```bash
sh install.sh          # macOS/Linux   (Windows: install.cmd / install.ps1)
```

What it does: finds/bootstraps Python 3.10+ → one shared venv → installs GM +
bundled Neuron + NeuRAG (pyturso wheels from `neuron/vendor`, fastembed
best-effort) → `gray-matter install` (registers ONLY the gateway in every
detected MCP client with `.bak` backups, deploys session hooks, writes the
manifest) → Desktop GUI shortcut → opens the control center.

## 2. Verify

```bash
gray-matter doctor    # only gray-matter in clients; warns if vector tier degraded
gray-matter ping
python -m pytest neuron/tests gray_matter/tests neurag/tests -q
```

Restart your AI apps to load the gateway.

## 3. Rollback / removal

```bash
gray-matter uninstall --dry-run
gray-matter uninstall            # interactive: asks BEFORE touching memory
```

User memory (graphs, knowledge.db, bridges) is NEVER deleted without explicit
consent. Spec: `INSTALLER-UX` in the docs; paths: `paths.py`.
