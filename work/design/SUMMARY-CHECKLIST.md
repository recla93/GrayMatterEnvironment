# GUI Refactor — Summary & Checklist

> Created: 2026-07-26
> Relates to: ADR-009-GME-REGISTRY.md, IMPLEMENTATION-PLAN.md, RISK-ANALYSIS.md

---

## TL;DR

Introduce **Gray Matter Environment (GME)** — a centralized registry folder where all tools (GM, Neuron, NeuRAG) register their metadata. This enables multi-venv execution, health monitoring, and migration from old installs.

**Key insight**: The GME JSON is the SSOT for "where is this tool's Python?" — the venv stays where it is, no risky moves required.

---

## Architecture at a Glance

```
%LOCALAPPDATA%\GrayMatterEnvironment\
├── gray-matter.json       ← metadata (version, venv, python, status, health)
├── neuron.json
├── neurag.json
├── gray-matter\           ← optional: consolidated venv
├── neuron\                ← optional: consolidated venv
└── neurag\                ← optional: consolidated venv
```

**Flow**:
1. Installer writes JSON to GME after successful install
2. `catalog.py` reads GME for tool discovery (fallback: `find_spec()`)
3. `webgui.py` reads GME for correct Python path (fallback: `sys.executable`)
4. Health metrics populated on-demand (ping, mem, cpu)

---

## Implementation Checklist

### Phase 1: Registry (Critical)

- [ ] Create `gray_matter/gme.py` module
  - [ ] `gme_root()` — folder location
  - [ ] `ensure_gme()` — create folder
  - [ ] `read_tool(key)` — read JSON
  - [ ] `write_tool(data)` — write JSON (atomic)
  - [ ] `list_tools()` — read all JSONs
  - [ ] `update_health(key, health)` — update health section
  - [ ] `mark_missing(key)` — mark as uninstalled

- [ ] Update `gray_matter/install.ps1`
  - [ ] Add GME JSON write after GM install
  - [ ] Test: install GM → verify JSON exists

- [ ] Update `gray_matter/install.sh`
  - [ ] Add GME JSON write after GM install
  - [ ] Test: install GM → verify JSON exists

- [ ] Update `neuron/install.ps1`
  - [ ] Add GME JSON write after Neuron install
  - [ ] Test: install Neuron → verify JSON exists

- [ ] Update `neuron/install.sh`
  - [ ] Add GME JSON write after Neuron install
  - [ ] Test: install Neuron → verify JSON exists

- [ ] Update `neurag/install.ps1`
  - [ ] Add GME JSON write after NeuRAG install
  - [ ] Test: install NeuRAG → verify JSON exists

- [ ] Update `neurag/install.sh`
  - [ ] Add GME JSON write after NeuRAG install
  - [ ] Test: install NeuRAG → verify JSON exists

- [ ] Unit tests for `gme.py`
  - [ ] test_read_tool
  - [ ] test_write_tool
  - [ ] test_list_tools
  - [ ] test_update_health
  - [ ] test_mark_missing
  - [ ] test_concurrent_writes

### Phase 2: Multi-Venv Execution (Critical)

- [ ] Update `gray_matter/catalog.py`
  - [ ] Add GME lookup in `environments()`
  - [ ] Fallback to `find_spec()` if GME missing
  - [ ] Include `venv`, `python`, `linked_to` in output
  - [ ] Test: existing installs without GME still work

- [ ] Update `gray_matter/webgui.py`
  - [ ] Add `_python_for_tool(tool)` function
  - [ ] Update `_argv_for()` to use `_python_for_tool()`
  - [ ] Update `_cli_argv()` to use `_python_for_tool()`
  - [ ] Fallback to `_python()` if GME missing
  - [ ] Test: commands execute with correct Python

- [ ] Integration tests
  - [ ] GM + Neuron in separate venvs → GUI discovers both
  - [ ] Commands execute with correct Python per tool
  - [ ] Fallback works when GME folder missing

### Phase 3: Migration UI (Important)

- [ ] Add migration detection in `catalog.py`
  - [ ] `detect_old_installs()` — find tools outside GME
  - [ ] `_find_venv_for(module)` — locate venv

- [ ] Add migration card in `webgui.html`
  - [ ] Show detected old installs
  - [ ] "Migrate" button per tool
  - [ ] "Migrate All" button
  - [ ] "Register Only" option (no venv movement)

- [ ] Add migration endpoint in `webgui.py`
  - [ ] `migrate_state()` — show migration status
  - [ ] `migrate_run()` — execute migration
  - [ ] Backup before movement
  - [ ] Rollback on failure

- [ ] Unit tests
  - [ ] test_detect_old_installs
  - [ ] test_migrate_register_only
  - [ ] test_migrate_consolidate
  - [ ] test_migrate_rollback

### Phase 4: Health Stream (Nice-to-have)

- [ ] Add health collection in `gray_matter/gme.py`
  - [ ] `collect_health(key)` — gather metrics
  - [ ] `start_health_poller()` — background thread
  - [ ] `stop_health_poller()` — stop polling

- [ ] Add health bar in `webgui.html`
  - [ ] Top bar with tool status
  - [ ] Show: status, ping, memory, cpu
  - [ ] Auto-refresh every 30s

- [ ] Add health endpoint in `webgui.py`
  - [ ] `health_state()` — return all tool health
  - [ ] `health_check(key)` — check single tool

- [ ] Unit tests
  - [ ] test_collect_health_running
  - [ ] test_collect_health_stopped
  - [ ] test_health_polling

---

## Testing Strategy

### Unit Tests (per phase)

- Phase 1: `test_gme.py` — all gme.py functions
- Phase 2: `test_catalog_gme.py`, `test_webgui_python.py`
- Phase 3: `test_migration.py` — detection, register, consolidate
- Phase 4: `test_health.py` — collection, polling, display

### Integration Tests (cross-phase)

- Full install cycle: install → GME JSON → GUI discovers → commands work
- Multi-venv: GM + Neuron separate → GUI executes both
- Migration: detect old → migrate → verify GME updated
- Health: start tool → verify metrics populated

### Regression Tests (safety net)

- Existing installs without GME still work
- `find_spec()` fallback functions correctly
- GUI does not crash if GME folder is missing
- Uninstall cleans up GME JSON

---

## Risk Mitigation

| Risk | Mitigation | Status |
|------|------------|--------|
| JSON encoding issues | Validate after write, cross-platform tests | [ ] |
| Path escaping on Windows | Manual escaping, validate structure | [ ] |
| Concurrent writes | Atomic writes (temp + rename) | [ ] |
| Stale JSON after uninstall | `mark_missing()` in uninstall scripts | [ ] |
| Health race condition | Check `pid` alive, graceful degradation | [ ] |
| psutil not installed | Best-effort, skip metrics if unavailable | [ ] |
| GME folder permissions | User permissions, fallback to find_spec | [ ] |
| Migration breaks tool | Backup before move, rollback on failure | [ ] |

---

## Rollback Plan

### Phase 1
- Delete GME folder → all tools revert to `find_spec()`

### Phase 2
- Revert `catalog.py` and `webgui.py` → use `sys.executable`

### Phase 3
- Hide migration card → no migration UI

### Phase 4
- Remove health bar → no metrics overhead

**All phases are independent — no single phase blocks the others.**

---

## Documentation

- [ ] ADR-009-GME-REGISTRY.md — architecture decision record
- [ ] IMPLEMENTATION-PLAN.md — detailed implementation plan
- [ ] RISK-ANALYSIS.md — risk analysis and side effects
- [ ] This file — summary and checklist

---

## Next Steps

1. Review all documents with team
2. Approve ADR-009
3. Start Phase 1 implementation
4. Iterate through phases 1-4
