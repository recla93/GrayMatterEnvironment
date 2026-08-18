# Risk Analysis & Side Effects

> Relates to: ADR-009-GME-REGISTRY.md, IMPLEMENTATION-PLAN.md
> Created: 2026-07-26

---

## 1. Files Being Modified

### Critical Files (High Risk)

| File | Change | Risk Level | Potential Side Effects |
|------|--------|------------|------------------------|
| `gray_matter/catalog.py` | GME lookup in `environments()` | **High** | - Breaking existing `find_spec()` logic<br>- Version detection changes<br>- Command discovery fails if GME stale |
| `gray_matter/webgui.py` | `_python_for_tool()` replaces `_python()` | **High** | - Commands fail if Python path wrong<br>- Multi-venv execution breaks<br>- GUI crashes if GME unreadable |
| `gray_matter/install.ps1` | GME JSON write | **Medium** - PowerShell syntax errors<br>- JSON encoding issues<br>- Path escaping on Windows |
| `gray_matter/install.sh` | GME JSON write | **Medium** - Shell syntax errors<br>- JSON encoding issues<br>- Path differences across Linux/macOS |

### Medium Risk Files

| File | Change | Risk Level | Potential Side Effects |
|------|--------|------------|------------------------|
| `neuron/install.ps1` | GME JSON write | **Medium** | - Same as GM installer<br>- Standalone mode may not write GME |
| `neuron/install.sh` | GME JSON write | **Medium** | - Same as GM installer<br>- Standalone mode may not write GME |
| `neurag/install.ps1` | GME JSON write | **Medium** | - Same as GM installer<br>- Standalone mode may not write GME |
| `neurag/install.sh` | GME JSON write | **Medium** | - Same as GM installer<br>- Standalone mode may not write GME |

### Low Risk Files

| File | Change | Risk Level | Potential Side Effects |
|------|--------|------------|------------------------|
| `gray_matter/gme.py` (NEW) | Registry module | **Low** | - New module, no existing code to break<br>- Must be imported correctly |
| `gray_matter/clients.py` | None (reference only) | **None** | - Related but not modified |

---

## 2. Specific Side Effects

### 2.1 JSON Encoding Issues

**Problem**: PowerShell `ConvertTo-Json` may produce different JSON than Python `json.dumps()`.

**Example**:
```powershell
# PowerShell (problematic)
@{key="neuron"} | ConvertTo-Json
# Output: {"key":"neuron"}  (no indentation)

# Python (expected)
json.dumps({"key": "neuron"}, indent=2)
# Output: {
#   "key": "neuron"
# }
```

**Mitigation**:
- Use consistent indentation (2 spaces)
- Validate JSON after write (try-read)
- Test cross-platform JSON compatibility

### 2.2 Path Escaping on Windows

**Problem**: Backslashes in JSON must be escaped.

**Example**:
```json
{
  "venv": "C:\\Users\\...\\neuron\\.venv"  // correct
}
```

**Mitigation**:
- PowerShell: use `-EscapeHandling` or manual escaping
- Bash: use single quotes for JSON, double for paths
- Always validate JSON structure after write

### 2.3 Concurrent Writes

**Problem**: Multiple installers writing to GME simultaneously.

**Scenario**: User runs `install.ps1` for GM while Neuron's installer writes its JSON.

**Mitigation**:
- Atomic writes (write to `.tmp`, then rename)
- GME folder uses user permissions (no admin required)
- Each tool writes only its own JSON (no shared file)

### 2.4 Stale JSON After Uninstall

**Problem**: Tool uninstalled but JSON remains in GME.

**Scenario**: User uninstalls Neuron via CLI, but GME JSON still shows `status: "installed"`.

**Mitigation**:
- Uninstall scripts call `gme.mark_missing(key)`
- GUI shows "stale" status and offers cleanup
- Next install overwrites stale JSON

### 2.5 Health Race Condition

**Problem**: Tool crashes between health checks.

**Scenario**: Health check shows `pid: 12345`, tool crashes, next check 30s later.

**Mitigation**:
- Check `pid` is alive before reporting metrics
- Graceful degradation: show "stopped" if process gone
- Update `status` field immediately on crash detection

### 2.6 psutil Not Installed

**Problem**: `psutil` not available for health metrics.

**Scenario**: Minimal install without `psutil` dependency.

**Mitigation**:
- Best-effort: skip metrics if `psutil` unavailable
- Show only basic status (installed/stopped)
- Document `psutil` as optional dependency

### 2.7 GME Folder Permissions

**Problem**: User cannot write to `%LOCALAPPDATA%`.

**Scenario**: Corporate environment with restricted permissions.

**Mitigation**:
- GME folder created with user permissions (not admin)
- Fallback: if GME unwritable, use `find_spec()` (existing behavior)
- Log warning but don't block install

---

## 3. Cross-Module Dependencies

### 3.1 catalog.py → gme.py

**Dependency**: `catalog.py` imports `gme.py` for registry lookup.

**Risk**: If `gme.py` has import errors, `catalog.py` fails.

**Mitigation**:
- Lazy import: `from gray_matter.gme import ...` inside function
- Try-except around import
- Fallback to `find_spec()` if import fails

### 3.2 webgui.py → gme.py

**Dependency**: `webgui.py` imports `gme.py` for Python path lookup.

**Risk**: If `gme.py` has errors, commands fail to execute.

**Mitigation**:
- Lazy import inside `_python_for_tool()`
- Fallback to `_python()` (existing behavior)
- Log error but don't crash GUI

### 3.3 Installers → gme.py

**Dependency**: Installers write JSON to GME folder.

**Risk**: If GME folder creation fails, install continues but no registry entry.

**Mitigation**:
- Best-effort: try to write GME, catch exceptions
- Install succeeds even if GME write fails
- Log warning for user visibility

---

## 4. Backward Compatibility

### 4.1 Existing Installs Without GME

**Scenario**: User has GM + Neuron installed in shared venv, no GME folder.

**Behavior**:
- `catalog.py` finds tools via `find_spec()` (existing logic)
- `_python()` returns `sys.executable` (existing behavior)
- GUI works exactly as before

**Validation**:
- Test: install GM without GME → verify GUI works
- Test: add GME → verify tools still discovered

### 4.2 Mixed Mode (Some Tools in GME, Some Not)

**Scenario**: GM in GME, Neuron installed standalone outside GME.

**Behavior**:
- GM discovered via GME JSON
- Neuron discovered via `find_spec()` fallback
- `_python_for_tool()` returns correct path for GM, fallback for Neuron

**Validation**:
- Test: GM in GME, Neuron outside → verify both work
- Test: migrate Neuron to GME → verify still works

### 4.3 GME Folder Deleted

**Scenario**: User manually deletes GME folder.

**Behavior**:
- All tools fall back to `find_spec()` discovery
- `_python()` falls back to `sys.executable`
- GUI works as before, no health metrics

**Validation**:
- Test: delete GME folder → verify GUI graceful degradation
- Test: recreate GME → verify tools rediscovered

---

## 5. Migration Risks

### 5.1 Venv Movement Failure

**Scenario**: User clicks "Consolidate" but venv movement fails (permissions, disk space).

**Mitigation**:
- Backup original location before move
- Rollback if movement fails
- Keep JSON pointing to original location
- Show error message with manual instructions

### 5.2 Venv Movement Breaks Tool

**Scenario**: Tool was using hardcoded paths, movement breaks imports.

**Mitigation**:
- Test movement on clean install first
- Document known issues (hardcoded paths)
- Offer "Register Only" option (no movement)

### 5.3 Disk Space Issues

**Scenario**: Moving venv requires temporary double disk space.

**Mitigation**:
- Check available space before movement
- Warn user if insufficient space
- Offer "Register Only" as alternative

---

## 6. Performance Risks

### 6.1 Health Polling Overhead

**Scenario**: `psutil.Process()` calls every 30s per tool.

**Impact**: Minimal (CPU: <0.1%, Memory: <1MB)

**Mitigation**:
- Poll only when GUI is open
- Poll only for `status: "running"` tools
- Configurable interval (default 30s)

### 6.2 JSON Read/Write Frequency

**Scenario**: Multiple tools reading GME folder simultaneously.

**Impact**: Minimal (JSON files are small, <1KB each)

**Mitigation**:
- Read on-demand (not cached)
- Write only on install/uninstall/health update
- Atomic writes prevent corruption

---

## 7. Testing Gaps

### 7.1 Missing Tests

| Test Case | Priority | Risk if Missing |
|-----------|----------|------------------|
| Cross-platform JSON compatibility | High | Windows/Linux JSON differences |
| Concurrent installer writes | Medium | Race condition corruption |
| Health polling under load | Medium | GUI slowdown |
| Migration rollback | High | Broken installs |
| Stale JSON cleanup | Low | UI confusion |

### 7.2 Test Environment Needs

- Windows 10/11 with PowerShell 5.1+
- macOS with Bash 3.2+
- Linux with Bash 4.0+
- Python 3.10+ with/without `psutil`
- Multiple venv configurations (shared, standalone, mixed)

---

## 8. Rollback Procedures

### 8.1 Phase 1 Rollback (Registry)

```bash
# Delete GME folder
rm -rf ~/.local/share/GrayMatterEnvironment  # Linux/macOS
rmdir /s /q "%LOCALAPPDATA%\GrayMatterEnvironment"  # Windows
```

**Effect**: All tools revert to `find_spec()` discovery. No data loss.

### 8.2 Phase 2 Rollback (Multi-Venv)

- Revert `catalog.py` changes (remove GME lookup)
- Revert `webgui.py` changes (remove `_python_for_tool()`)

**Effect**: GUI uses `sys.executable` for all tools. Existing behavior restored.

### 8.3 Phase 3 Rollback (Migration UI)

- Hide migration card in GUI
- Disable consolidation buttons

**Effect**: No migration UI, existing installs unchanged.

### 8.4 Phase 4 Rollback (Health Stream)

- Remove health bar from GUI
- Disable health polling

**Effect**: No health metrics, no performance overhead.

---

## 9. Monitoring & Observability

### 9.1 Logging

- GME operations logged to `gray_matter.log`
- Health check results logged at DEBUG level
- Migration attempts logged at INFO level

### 9.2 Metrics

- GME folder size (monitor for stale JSONs)
- Health check frequency (monitor for performance)
- Migration success rate (monitor for issues)

### 9.3 Alerts

- GME folder creation failure (WARNING)
- Health check timeout (WARNING)
- Migration failure (ERROR)

---

## 10. Documentation Updates

### 10.1 User-Facing Docs

- INSTALL.md: add GME folder explanation
- TROUBLESHOOTING.md: add GME-related issues
- GUI screenshots: update with health bar

### 10.2 Developer Docs

- ADR-009: architecture decision record (this file)
- CONTRIBUTING.md: add GME development guidelines
- API docs: add `gme.py` module documentation
