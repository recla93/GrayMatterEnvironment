# INSTALL-AI — NeuRAG (knowledge base gerarchica)

> Istruzioni per un agente AI. NeuRAG può lavorare standalone, ma il modello
> raccomandato è dietro il gateway Gray Matter (bundle-ato in ogni install).

## Percorso raccomandato (via Gray Matter)

```bash
pip install -e .                       # dal root di neurag
pip install -e ../gray_matter          # il gateway, se presente nel checkout
gray-matter install --dry-run
gray-matter install                    # registra SOLO gray-matter nei client
gray-matter doctor
```

## Standalone (senza Gray Matter)

```bash
pip install -e .
# registrazione manuale nel client MCP (entry stdio):
#   command: python   args: ["-m", "neurag.server"]
python -m pytest test -q               # attesi tutti verdi
```

## Dati, ingest, rollback

- Knowledge base: `<data-dir>/neurag/knowledge.db` (Turso/SQLite; mai toccata dall'install).
- Ingest: `knowledge_index <dir>` o import bulk YAML (`neurag/importer.py`);
  chunking adattivo per .md/.py/.kt/.java/.pdf/.docx/.yaml.
- Embedding: default lessicale (nessuna dipendenza); FastEmbed auto se installato.
- Salute vault: tool `knowledge_health` (orfani, gerarchia rotta, chunk vuoti).
- Rimozione: `gray-matter uninstall` (interattivo sui dati) o ripristino `.bak`.
