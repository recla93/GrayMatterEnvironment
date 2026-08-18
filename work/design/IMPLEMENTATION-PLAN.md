# Implementation Plan: GME Registry + Multi-Venv GUI

> Relates to: ADR-009-GME-REGISTRY.md
> Created: 2026-07-26

---

## Phase 1: Registry (GME Folder)

### Goal
Every installer writes a JSON file to GME folder after successful install.

### Files to Modify

| File | Change | Risk |
|------|--------|------|
| `gray_matter/install.ps1` | Write `gray-matter.json` to GME after install | Low |
| `gray_matter/install.sh` | Write `gray-matter.json` to GME after install | Low |
| `neuron/install.ps1` | Write `neuron.json` to GME after install | Low |
| `neuron/install.sh` | Write `neuron.json` to GME after install | Low |
| `neurag/install.ps1` | Write `neurag.json` to GME after install | Low |
| `neurag/install.sh` | Write `neurag.json` to GME after install | Low |

### New Module: `gray_matter/gme.py`

Registry logic extracted into a shared module:

```python
"""Gray Matter Environment — centralized tool registry."""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# GME folder location
def gme_root() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "GrayMatterEnvironment"

def ensure_gme() -> Path:
    """Create GME folder if not exists."""
    root = gme_root()
    root.mkdir(parents=True, exist_ok=True)
    return root

def tool_json_path(key: str) -> Path:
    """Path to a tool's JSON in GME."""
    return ensure_gme() / f"{key}.json"

def read_tool(key: str) -> dict | None:
    """Read a tool's JSON from GME. Returns None if not found."""
    path = tool_json_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

def write_tool(data: dict) -> None:
    """Write a tool's JSON to GME. Atomic write (write to temp, rename)."""
    key = data.get("key")
    if not key:
        raise ValueError("JSON must have 'key' field")
    path = tool_json_path(key)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic on same filesystem

def list_tools() -> list[dict]:
    """Read all tools from GME folder."""
    root = ensure_gme()
    tools = []
    for f in root.glob("*.json"):
        try:
            tools.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return tools

def update_health(key: str, health: dict) -> None:
    """Update health section of a tool's JSON."""
    data = read_tool(key)
    if data is None:
        return
    data["health"] = health
    data["health"]["last_check"] = datetime.now(timezone.utc).isoformat()
    write_tool(data)

def mark_missing(key: str) -> None:
    """Mark a tool as missing (uninstalled but JSON remains)."""
    data = read_tool(key)
    if data:
        data["status"] = "missing"
        write_tool(data)
```

### Installer Changes

Each installer adds a step after successful install:

**PowerShell (`install.ps1`)**:
```powershell
# Write GME registry
$GmeRoot = Join-Path $env:LOCALAPPDATA "GrayMatterEnvironment"
if (-not (Test-Path $GmeRoot)) { New-Item -ItemType Directory -Force -Path $GmeRoot | Out-Null }
$GmeJson = @{
    key = "gray-matter"
    label = "Gray Matter"
    version = (Get-SrcVersion $Here)
    venv = $Venv
    python = $VPy
    module = "gray_matter"
    cli_module = "gray_matter.cli"
    status = "installed"
    linked_to = $null
    source = $Here
    installed_at = (Get-Date -Format "o")
    error = $null
    health = @{ pid=$null; ping_ms=$null; memory_mb=$null; cpu_percent=$null; uptime_s=$null; last_check=$null }
} | ConvertTo-Json -Depth 5
$GmeJson | Set-Content (Join-Path $GmeRoot "gray-matter.json") -Encoding UTF8
```

**Bash (`install.sh`)**:
```bash
# Write GME registry
GME_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/GrayMatterEnvironment"
mkdir -p "$GME_ROOT"
cat > "$GME_ROOT/gray-matter.json" <<EOF
{
  "key": "gray-matter",
  "label": "Gray Matter",
  "version": "$(src_ver "$HERE")",
  "venv": "$VENV",
  "python": "$VPY",
  "module": "gray_matter",
  "cli_module": "gray_matter.cli",
  "status": "installed",
  "linked_to": null,
  "source": "$HERE",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "error": null,
  "health": {"pid": null, "ping_ms": null, "memory_mb": null, "cpu_percent": null, "uptime_s": null, "last_check": null}
}
EOF
```

### Testing Phase 1

- Unit tests for `gme.py`: read, write, list, update_health, mark_missing
- Integration test: install GM → verify JSON exists and is valid
- Cross-platform: test on Windows + Linux paths

---

## Phase 2: Multi-Venv Execution

### Goal
`_python()` and `_argv_for()` in `webgui.py` use the correct Python per tool.

### Files to Modify

| File | Change | Risk |
|------|--------|------|
| `gray_matter/webgui.py` | `_python()` reads GME JSON | Medium |
| `gray_matter/catalog.py` | `environments()` reads GME JSON | Medium |

### Changes to `catalog.py`

```python
def environments() -> list[dict]:
    """Gli ambienti con lo stato reale della macchina."""
    from gray_matter.gme import list_tools, read_tool
    
    # Try GME first, fallback to find_spec
    gme_tools = {t["key"]: t for t in list_tools()}
    
    out = []
    for env in ENVIRONMENTS:
        gme = gme_tools.get(env["key"])
        
        # Determine if installed
        if gme and gme.get("status") == "installed":
            present = True
            python_path = gme.get("python", _python())
        else:
            present = _installed(env["module"])
            python_path = _python()
        
        commands = []
        error = ""
        if present:
            try:
                commands = (_from_parser(env["cli"]) if env["kind"] == "parser"
                            else _from_commands(env["cli"]))
            except BaseException as exc:
                error = f"{type(exc).__name__}: {exc}"
        
        # ... rest of logic
        
        out.append({
            "key": env["key"],
            "label": env["label"],
            "subtitle": env["subtitle"],
            "installed": present,
            "version": gme.get("version", "") if gme else (_version(env["module"]) if present else ""),
            "venv": gme.get("venv") if gme else None,
            "python": python_path,
            "linked_to": gme.get("linked_to") if gme else None,
            "commands": sorted(...),
            "error": error or (gme.get("error") if gme else None),
        })
    return out
```

### Changes to `webgui.py`

```python
def _python_for_tool(tool: str) -> str:
    """Get the correct Python executable for a tool."""
    from gray_matter.gme import read_tool
    gme = read_tool(tool)
    if gme and gme.get("python") and Path(gme["python"]).exists():
        return gme["python"]
    return _python()  # fallback to system Python

def _argv_for(tool: str, command: str, args: dict, extra: str = "") -> list[str]:
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    argv = [_python_for_tool(tool), *base, command]
    # ... rest unchanged
```

### Testing Phase 2

- Unit test: `_python_for_tool()` returns correct path from GME
- Integration test: install GM + Neuron in separate venvs → GUI discovers both
- Regression test: existing installs without GME still work via fallback

---

## Phase 3: Migration UI

### Goal
Detect old-style installs and offer consolidation into GME.

### Detection Logic

```python
def detect_old_installs() -> list[dict]:
    """Find tools installed outside GME."""
    from gray_matter.gme import list_tools, gme_root
    
    gme_tools = {t["key"]: t for t in list_tools()}
    old_installs = []
    
    for env in ENVIRONMENTS:
        if env["key"] in gme_tools:
            continue  # already in GME
        
        # Check if installed via find_spec
        if _installed(env["module"]):
            # Try to find the venv
            venv_path = _find_venv_for(env["module"])
            old_installs.append({
                "key": env["key"],
                "label": env["label"],
                "venv": str(venv_path) if venv_path else None,
                "python": sys.executable,  # current Python (may be wrong)
            })
    
    return old_installs

def _find_venv_for(module: str) -> Path | None:
    """Try to locate the venv for a module."""
    # Check common locations
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / module / ".venv",
        Path(os.path.expanduser("~")) / ".local" / "share" / module / ".venv",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
```

### GUI Changes

Add a "Migration" card in the sidebar:

```
┌─────────────────────────────────────┐
│ ⚠️ Old installs detected           │
│                                     │
│ Neuron: venv at C:\...\neuron\.venv │
│ [Migrate to GME]                    │
│                                     │
│ NeuRAG: venv at C:\...\neurag\.venv │
│ [Migrate to GME]                    │
│                                     │
│ [Migrate All]                       │
└─────────────────────────────────────┘
```

### Migration Flow

1. **Register only** (default): write JSON to GME, venv stays in place
2. **Consolidate** (optional): move venv into GME folder
   - Requires elevated permissions on Windows
   - Creates backup of original location
   - Updates JSON with new venv path

### Testing Phase 3

- Unit test: `detect_old_installs()` finds tools outside GME
- Integration test: migrate tool → verify JSON updated, venv moved (if consolidate)
- UI test: migration card shows correct tools, buttons work

---

## Phase 4: Health Stream

### Goal
Real-time status bar showing tool health metrics.

### Health Collection

```python
def collect_health(tool_key: str) -> dict:
    """Collect health metrics for a tool."""
    from gray_matter.gme import read_tool
    import time
    
    data = read_tool(tool_key)
    if not data:
        return {"status": "missing"}
    
    health = data.get("health", {})
    pid = health.get("pid")
    
    if pid:
        try:
            import psutil
            proc = psutil.Process(pid)
            health["memory_mb"] = proc.memory_info().rss / 1024 / 1024
            health["cpu_percent"] = proc.cpu_percent(interval=0.1)
            health["uptime_s"] = time.time() - proc.create_time()
            health["status"] = "running"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            health["status"] = "stopped"
            health["pid"] = None
    else:
        health["status"] = "stopped"
    
    # Ping: try to import the module (fast check)
    try:
        start = time.time()
        import importlib
        importlib.import_module(data.get("module", tool_key))
        health["ping_ms"] = (time.time() - start) * 1000
    except Exception:
        health["ping_ms"] = None
    
    return health
```

### GUI Display

Top bar in `webgui.html`:

```html
<div class="health-bar">
  <div class="tool-status" data-tool="neuron">
    <span class="dot green"></span>
    <span class="name">Neuron</span>
    <span class="metric">12ms</span>
    <span class="metric">45MB</span>
    <span class="metric">2%</span>
  </div>
  <!-- ... other tools -->
</div>
```

### Polling

- Health checked every 30 seconds (configurable)
- Only for tools with `status: "running"`
- Background thread, non-blocking

### Testing Phase 4

- Unit test: `collect_health()` returns valid metrics
- Integration test: start tool → verify health populated
- UI test: health bar updates in real-time

---

## Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Concurrent JSON writes | Low | Medium | Atomic writes (temp + rename) |
| Stale JSON after uninstall | Medium | Low | `mark_missing()` on uninstall, cleanup on next install |
| Health race condition | Medium | Low | `pid` check + `status` field, graceful degradation |
| Migration breaks existing install | Low | High | Backup before move, fallback to `find_spec()` |
| psutil not installed | High | Low | Best-effort, skip metrics if unavailable |
| GME folder permissions | Low | High | Create with user permissions, no admin required |

---

## Testing Strategy

### Unit Tests

- `test_gme.py`: all `gme.py` functions
- `test_catalog_gme.py`: `environments()` with GME data
- `test_webgui_python.py`: `_python_for_tool()` with/without GME

### Integration Tests

- Full install cycle: install → GME JSON created → GUI discovers tool
- Multi-venv: install GM + Neuron separately → GUI executes both
- Migration: detect old → migrate → verify GME updated

### Regression Tests

- Existing installs without GME still work
- `find_spec()` fallback functions correctly
- GUI does not crash if GME folder is missing

---

## Rollback Plan

If GME causes issues:

1. **Phase 1**: Delete GME folder → installers revert to old behavior
2. **Phase 2**: `_python()` fallback to `sys.executable` (existing behavior)
3. **Phase 3**: Migration UI hidden, no consolidation
4. **Phase 4**: Health bar hidden, no metrics collected

All phases have independent fallbacks — no single phase blocks the others.
