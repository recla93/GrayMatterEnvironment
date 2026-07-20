# INSTALL-AI — NeuRAG (hierarchical knowledge base)

> Instructions for an AI agent. NeuRAG can run standalone, but the recommended
> model is behind the Gray Matter gateway (bundled with every install).
> Versione italiana: `INSTALL-AI.it.md`.

## Recommended path (via Gray Matter)

```bash
pip install -e .                       # from the neurag root
pip install -e ../gray_matter          # the gateway, if present in the checkout
gray-matter install --dry-run
gray-matter install                    # registers ONLY gray-matter in clients
gray-matter doctor
```

## Standalone (without Gray Matter)

```bash
pip install -e .
# manual registration in the MCP client (stdio entry):
#   command: python   args: ["-m", "neurag.server"]
python -m pytest test -q               # expect all green
```

## Data, ingest, rollback

- Knowledge base: `<data-dir>/neurag/knowledge.db` (Turso/SQLite; never touched by install).
- Ingest: `knowledge_index <dir>` or bulk YAML import (`neurag/importer.py`);
  adaptive chunking for .md/.py/.kt/.java/.pdf/.docx/.yaml.
- Embedding: lexical by default (zero deps); FastEmbed auto-detected if installed.
- Vault health: `knowledge_health` tool (orphans, broken hierarchy, empty chunks).
- Removal: `gray-matter uninstall` (interactive on data) or restore the `.bak` files.
