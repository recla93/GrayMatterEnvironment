# Changelog — Gray Matter

## v0.2.0 (2026-07-20)

### Wizard GUI
- Setup card: component selection (Neuron/NeuRAG) + Preview/Install/Test
- Preferences card: dynamic settings from `settings.py` DEFAULTS
- Turso connection card (existing)
- Backend: `setup_state`, `setup_run`, `setup_test`, `setup_prefs_get/set`

### Gateway flip
- `register --gateway` evicts neuron/neurag, registers only GM
- Daemon singleton via exclusive bind
- MSIX config support (Claude Desktop Packages path)

### Settings CLI
- `gray-matter config get|set|list` backed by `settings.py`

### Cache improvements
- Dynamic TTL based on topic heat
- Multi-topic accumulation (removed clear on topic change)
- `invalidate_related(topic)` post `store_turn`

### Installer/Uninstaller
- `executor.py`: dispatch on `installer.plan()` / `uninstaller.plan()`
- Steps: reap, ensure_data, install, register, deploy_hook, write_manifest
- Uninstall: interactive data deletion, `.bak` restore
- Hook deployment: claude-code, cowork, opencode

### Fixes
- F0: Worker persistent processes (no re-import per call)
- F1: IPC length-prefixed read fixed
- F2: `_restart_dead_servers` now respawns
- F19: Cache singleton (no more recreate per pulse)
- F20: Cache no longer clears on topic change
- F21: Cache invalidation post store_turn
- F22: Bridge ingest validation
- F23: Pulse topic validation

### Tests
- 38 tests passing (test_executor, test_cache_dynamic_ttl, test_topic_buffer, etc.)
