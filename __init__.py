"""neurag — standalone MCP RAG for knowledge retrieval.

Turso (libsql/SQLite) hierarchical knowledge graph with vector embeddings.
Designed to work as:
- a standalone MCP server for any client (Cursor, Claude, OpenCode, etc.)
- a knowledge companion alongside Neuron MCP

The bridge to Neuron is by convention, not by dependency: Neuron clients that detect
both MCP servers can route get_context queries to neurag knowledge_query.
"""

__version__ = "1.3.1"
