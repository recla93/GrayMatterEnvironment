# Graph Extraction Integration Plan

## Current State

### Neuron (`generate_graph_html.py`)
- **Fully functional HTML graph visualizer** (v2, T61)
- Force-directed physics (ForceAtlas2)
- Time-travel slider (replay graph turn by turn)
- Domain/type filters
- Insights panel (hubs, dormant, synapses)
- Style customization (Obsidian-like controls)
- Cross-context bridges
- Works on all tiers (local SQLite, local Turso, Turso Cloud)

### NeuRAG (`db.py:get_link_graph()`)
- Provides `get_link_graph()` method returning links with node info
- No HTML visualization yet
- No timeline feature
- **No uninstall command** - only `register`/`deregister`

### Gray Matter
- Bridges connect neuron concepts ↔ neurag nodes
- `bridges_for()` recalls bridges by topic
- Uninstall card only shows for GM itself
- NeuRAG lacks uninstall command

## Features Requested by User

### Uninstall Card for All Three Tools
**Goal:** Each tool (GM, Neuron, NeuRAG) should have its own uninstall card in the webgui.

**Implementation Plan:**
1. Add `uninstall` command to NeuRAG CLI (similar to Neuron's `setup --uninstall`)
2. Modify GM webgui to detect and show uninstall cards for all tools
3. Add uninstall cards for Neuron and NeuRAG in webgui
4. Create uninstaller module for NeuRAG (similar to GM's uninstaller)

**NeuRAG Uninstall Requirements:**
- `neurag uninstall` — deregister from clients, optionally purge data
- `neurag uninstall --purge-data` — also delete knowledge.db
- `neurag uninstall --json` — JSON output for webgui
- Similar to `neuron setup --uninstall`

**GM Webgui Changes:**
- Detect if tool has uninstall command
- Show uninstall card for each tool
- Call tool's uninstall with proper args