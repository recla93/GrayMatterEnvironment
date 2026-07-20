# Changelog — NeuRAG

## v0.3.0 (2026-07-20)

### New features
- `link_graph`: shows all node links with weights and evidence
- `rebuild_links`: clears and rebuilds links from tags + cross-refs
- Source attribution in `knowledge_query` results (D1)

### Database improvements
- Turso mandatory (pyturso==0.6.1) for vector search
- `_FixedEmbedder` test helper for deterministic embeddings

### Installer unification
- Canonical install via `install.ps1` / `install.sh` delegating to GM
- Vendored pyturso wheels (py310-314 win_amd64)

### Documentation
- README.md added
- INSTALL-AI.md (EN) + INSTALL-AI.it.md (IT)
- DESIGN-CROSSLINKS.md

### Tests
- 30+ tests passing (test_node_links, test_vector_sql, test_neighbors)
- Vector SQL test with Turso engine verification

## v0.2.0 (2026-07-18)

- Source attribution in knowledge_query (D1)
- AST chunking + symbol tags → triggers
- knowledge_health L1
- Installer bundle GM + wheels
