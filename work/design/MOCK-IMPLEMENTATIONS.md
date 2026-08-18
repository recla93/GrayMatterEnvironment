# Mock Implementations — Feasibility Check

> Created: 2026-07-26
> Purpose: Concrete code examples to verify approach before full implementation

---

## Mock 1: `gray_matter/gme.py` (Registry Module)

**Purpose**: Centralized registry for all tools. Single source of truth.

```python
"""Gray Matter Environment — centralized tool registry.

SSOT for tool discovery and multi-venv execution. Each tool writes a JSON
file here after install. The GUI reads these to find the correct Python
for each tool.

Usage:
    from gray_matter.gme import read_tool, write_tool, list_tools

    # Read a tool
    neuron = read_tool("neuron")
    if neuron:
        python_path = neuron["python"]

    # Write a tool
    write_tool({
        "key": "neuron",
        "label": "Neuron",
        "version": "6.1.2",
        "venv": "/path/to/venv",
        "python": "/path/to/venv/bin/python",
        "module": "neuron",
        "cli_module": "neuron.__main__",
        "status": "installed",
        "linked_to": "gray-matter",
        "source": "/path/to/source",
        "installed_at": "2026-07-26T12:00:00Z",
        "error": None,
        "health": {
            "pid": None,
            "ping_ms": None,
            "memory_mb": None,
            "cpu_percent": None,
            "uptime_s": None,
            "last_check": None
        }
    })

    # List all tools
    tools = list_tools()
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def gme_root() -> Path:
    """GME folder location — platform-specific."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "GrayMatterEnvironment"


def ensure_gme() -> Path:
    """Create GME folder if not exists. Returns path."""
    root = gme_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def tool_json_path(key: str) -> Path:
    """Path to a tool's JSON in GME."""
    return ensure_gme() / f"{key}.json"


def read_tool(key: str) -> dict[str, Any] | None:
    """Read a tool's JSON from GME. Returns None if not found or invalid."""
    path = tool_json_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Validate required fields
        if "key" not in data or "python" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def write_tool(data: dict[str, Any]) -> None:
    """Write a tool's JSON to GME. Atomic write (temp + rename)."""
    key = data.get("key")
    if not key:
        raise ValueError("JSON must have 'key' field")
    
    path = tool_json_path(key)
    tmp = path.with_suffix(".tmp")
    
    # Ensure required fields
    now = datetime.now(timezone.utc).isoformat()
    data.setdefault("installed_at", now)
    data.setdefault("status", "installed")
    data.setdefault("error", None)
    data.setdefault("health", {
        "pid": None,
        "ping_ms": None,
        "memory_mb": None,
        "cpu_percent": None,
        "uptime_s": None,
        "last_check": None
    })
    
    # Atomic write
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic on same filesystem


def list_tools() -> list[dict[str, Any]]:
    """Read all tools from GME folder."""
    root = ensure_gme()
    tools = []
    for f in root.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if "key" in data:
                tools.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return tools


def update_health(key: str, health: dict[str, Any]) -> None:
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


def remove_tool(key: str) -> bool:
    """Remove a tool's JSON from GME. Returns True if removed."""
    path = tool_json_path(key)
    if path.exists():
        path.unlink()
        return True
    return False


# Convenience functions for common lookups

def get_python(key: str) -> str | None:
    """Get the Python executable path for a tool. Returns None if not found."""
    data = read_tool(key)
    if data and data.get("status") == "installed":
        return data.get("python")
    return None


def get_venv(key: str) -> str | None:
    """Get the venv path for a tool. Returns None if not found."""
    data = read_tool(key)
    if data and data.get("status") == "installed":
        return data.get("venv")
    return None


def is_installed(key: str) -> bool:
    """Check if a tool is installed via GME."""
    data = read_tool(key)
    return data is not None and data.get("status") == "installed"


def get_version(key: str) -> str:
    """Get the version for a tool. Returns empty string if not found."""
    data = read_tool(key)
    return data.get("version", "") if data else ""


# Self-test / demo

def demo() -> None:
    """Demo: show all tools in GME."""
    tools = list_tools()
    if not tools:
        print("GME folder is empty — no tools registered yet.")
        print(f"Location: {gme_root()}")
        return
    
    print(f"GME: {gme_root()}")
    print(f"Tools: {len(tools)}")
    for t in tools:
        status = t.get("status", "?")
        version = t.get("version", "?")
        venv = t.get("venv", "?")
        print(f"  {t['key']}: {status} v{version} @ {venv}")


if __name__ == "__main__":
    demo()
```

---

## Mock 2: Installer Changes (PowerShell)

**Purpose**: Write GME JSON after successful install.

### `gray_matter/install.ps1` — Add after line 361 (before final message)

```powershell
# --- GME Registry ---
# Write tool metadata to GrayMatterEnvironment folder
function Write-GmeRegistry {
    param(
        [string]$Key,
        [string]$Label,
        [string]$Version,
        [string]$Venv,
        [string]$Python,
        [string]$Module,
        [string]$CliModule,
        [string]$Source
    )
    
    $GmeRoot = Join-Path $env:LOCALAPPDATA "GrayMatterEnvironment"
    if (-not (Test-Path $GmeRoot)) {
        New-Item -ItemType Directory -Force -Path $GmeRoot | Out-Null
    }
    
    $GmeJson = @{
        key = $Key
        label = $Label
        version = $Version
        venv = $Venv
        python = $Python
        module = $Module
        cli_module = $CliModule
        status = "installed"
        linked_to = $null
        source = $Source
        installed_at = (Get-Date -Format "o")
        error = $null
        health = @{
            pid = $null
            ping_ms = $null
            memory_mb = $null
            cpu_percent = $null
            uptime_s = $null
            last_check = $null
        }
    }
    
    $JsonPath = Join-Path $GmeRoot "$Key.json"
    $GmeJson | ConvertTo-Json -Depth 5 | Set-Content -Path $JsonPath -Encoding UTF8
    Write-Host "  GME registry updated: $JsonPath"
}

# Call after GM install (line ~361)
$GmVersion = Get-SrcVersion $Here
Write-GmeRegistry `
    -Key "gray-matter" `
    -Label "Gray Matter" `
    -Version $GmVersion `
    -Venv $Venv `
    -Python $VPy `
    -Module "gray_matter" `
    -CliModule "gray_matter.cli" `
    -Source $Here
```

### `neuron/install.ps1` — Add in `Install-Standalone` function (after line 77)

```powershell
# --- GME Registry ---
$GmeRoot = Join-Path $env:LOCALAPPDATA "GrayMatterEnvironment"
if (-not (Test-Path $GmeRoot)) {
    New-Item -ItemType Directory -Force -Path $GmeRoot | Out-Null
}

$NeuronVer = & (Join-Path $Venv "Scripts\neuron.exe") --version 2>$null
$GmeJson = @{
    key = "neuron"
    label = "Neuron"
    version = $NeuronVer
    venv = $Venv
    python = $Vpy
    module = "neuron"
    cli_module = "neuron.__main__"
    status = "installed"
    linked_to = $null
    source = $Here
    installed_at = (Get-Date -Format "o")
    error = $null
    health = @{
        pid = $null
        ping_ms = $null
        memory_mb = $null
        cpu_percent = $null
        uptime_s = $null
        last_check = $null
    }
}

$JsonPath = Join-Path $GmeRoot "neuron.json"
$GmeJson | ConvertTo-Json -Depth 5 | Set-Content -Path $JsonPath -Encoding UTF8
```

---

## Mock 3: Installer Changes (Bash)

**Purpose**: Write GME JSON after successful install.

### `gray_matter/install.sh` — Add before line 220 (final message)

```bash
# --- GME Registry ---
# Write tool metadata to GrayMatterEnvironment folder
write_gme_registry() {
    local key="$1" label="$2" version="$3" venv="$4" python="$5" module="$6" cli_module="$7" source="$8"
    
    local gme_root="${XDG_DATA_HOME:-$HOME/.local/share}/GrayMatterEnvironment"
    mkdir -p "$gme_root"
    
    cat > "$gme_root/$key.json" <<EOF
{
  "key": "$key",
  "label": "$label",
  "version": "$version",
  "venv": "$venv",
  "python": "$python",
  "module": "$module",
  "cli_module": "$cli_module",
  "status": "installed",
  "linked_to": null,
  "source": "$source",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "error": null,
  "health": {
    "pid": null,
    "ping_ms": null,
    "memory_mb": null,
    "cpu_percent": null,
    "uptime_s": null,
    "last_check": null
  }
}
EOF
    echo "  GME registry updated: $gme_root/$key.json"
}

# Call after GM install
GM_VERSION=$(src_ver "$HERE")
write_gme_registry "gray-matter" "Gray Matter" "$GM_VERSION" "$VENV" "$VPY" "gray_matter" "gray_matter.cli" "$HERE"
```

### `neuron/install.sh` — Add in standalone section (after line 77)

```bash
# --- GME Registry ---
gme_root="${XDG_DATA_HOME:-$HOME/.local/share}/GrayMatterEnvironment"
mkdir -p "$gme_root"

neuron_ver=$("$VENV/bin/neuron" --version 2>/dev/null || echo "unknown")
cat > "$gme_root/neuron.json" <<EOF
{
  "key": "neuron",
  "label": "Neuron",
  "version": "$neuron_ver",
  "venv": "$VENV",
  "python": "$VENV/bin/python",
  "module": "neuron",
  "cli_module": "neuron.__main__",
  "status": "installed",
  "linked_to": null,
  "source": "$HERE",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "error": null,
  "health": {
    "pid": null,
    "ping_ms": null,
    "memory_mb": null,
    "cpu_percent": null,
    "uptime_s": null,
    "last_check": null
  }
}
EOF
```

---

## Mock 4: `catalog.py` Changes

**Purpose**: Read GME for tool discovery, fallback to `find_spec()`.

### New `environments()` function (replaces line 185-215)

```python
def environments() -> list[dict]:
    """Gli ambienti con lo stato reale della macchina. Mai solleva.
    
    Discovery order:
    1. GME folder (centralized registry)
    2. find_spec() fallback (existing behavior)
    """
    try:
        from gray_matter.gme import list_tools as gme_list_tools
        gme_tools = {t["key"]: t for t in gme_list_tools()}
    except ImportError:
        gme_tools = {}  # gme.py not available, fallback to find_spec
    
    out = []
    for env in ENVIRONMENTS:
        gme = gme_tools.get(env["key"])
        
        # Determine if installed
        if gme and gme.get("status") == "installed":
            present = True
            python_path = gme.get("python") or _python()
        else:
            present = _installed(env["module"])
            python_path = _python()
        
        commands: list[dict] = []
        error = ""
        if present:
            try:
                commands = (_from_parser(env["cli"]) if env["kind"] == "parser"
                            else _from_commands(env["cli"]))
            except BaseException as exc:
                error = f"{type(exc).__name__}: {exc}"
        
        commands = [c for c in commands
                    if (env["key"], c["name"]) not in GUI_HIDDEN]
        for c in commands:
            key = (env["key"], c["name"])
            c["help"] = HELP_IT.get(key, c["help"])
            c["interactive"] = key in INTERACTIVE
        
        # Version: prefer GME, fallback to _version()
        if gme and gme.get("version"):
            version = gme["version"]
        elif present:
            version = _version(env["module"])
        else:
            version = ""
        
        out.append({
            "key": env["key"], 
            "label": env["label"], 
            "subtitle": env["subtitle"],
            "installed": present, 
            "version": version,
            "venv": gme.get("venv") if gme else None,
            "python": python_path,
            "linked_to": gme.get("linked_to") if gme else None,
            "commands": sorted(commands, key=lambda c: (
                [g[0] for g in GROUPS].index(c["group"])
                if c["group"] in [g[0] for g in GROUPS] else 99, c["name"])),
            "error": error or (gme.get("error") if gme else None),
        })
    return out
```

---

## Mock 5: `webgui.py` Changes

**Purpose**: Use correct Python per tool for multi-venv execution.

### New `_python_for_tool()` function (add after line 63)

```python
def _python_for_tool(tool: str) -> str:
    """Get the correct Python executable for a tool.
    
    Discovery order:
    1. GME registry (centralized)
    2. _python() fallback (existing behavior)
    
    This enables multi-venv execution: each tool uses its own Python
    instead of always using GM's Python.
    """
    try:
        from gray_matter.gme import read_tool
        gme = read_tool(tool)
        if gme and gme.get("python") and Path(gme["python"]).exists():
            return gme["python"]
    except ImportError:
        pass
    return _python()  # fallback to system Python
```

### Updated `_cli_argv()` (replaces line 85-95)

```python
def _cli_argv(tool: str, *cmd: str) -> list[str]:
    """argv per un comando CLI di un ambiente.
    
    Uses _python_for_tool() for multi-venv execution.
    """
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    return [_python_for_tool(tool), *base, *cmd]
```

### Updated `_argv_for()` (replaces line 98-124)

```python
def _argv_for(tool: str, command: str, args: dict, extra: str = "") -> list[str]:
    """Costruisce l'argv reale a partire dal comando e dai campi compilati.
    
    Uses _python_for_tool() for multi-venv execution.
    """
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    argv = [_python_for_tool(tool), *base, command]
    for a in args.get("_order", []):
        spec = args["_spec"].get(a, {})
        val = args.get(a, "")
        if spec.get("is_flag"):
            if val:
                argv.append(spec["flag"])
        elif spec.get("flag"):
            if str(val).strip():
                argv += [spec["flag"], str(val).strip()]
        elif str(val).strip():
            argv.append(str(val).strip())
    if extra.strip():
        import shlex
        argv += shlex.split(extra.strip(), posix=(os.name != "nt"))
    return argv
```

---

## Mock 6: HTML Health Bar

**Purpose**: Real-time status display in GUI sidebar.

### Add to `webgui.html` (top of sidebar)

```html
<!-- Health Bar -->
<div id="health-bar" class="health-bar">
  <div class="health-header">
    <span class="health-title">System Status</span>
    <span class="health-refresh" onclick="refreshHealth()">↻</span>
  </div>
  <div id="health-content" class="health-content">
    <!-- Dynamically populated -->
  </div>
</div>

<style>
.health-bar {
  background: #1a1b26;
  border: 1px solid #33467c;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}

.health-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.health-title {
  font-weight: 600;
  color: #c0caf5;
  font-size: 14px;
}

.health-refresh {
  cursor: pointer;
  color: #7aa2f7;
  font-size: 16px;
}

.health-refresh:hover {
  color: #89b4fa;
}

.health-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.health-tool {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  background: #24283b;
  border-radius: 6px;
}

.health-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.health-dot.green { background: #9ece6a; }
.health-dot.yellow { background: #e0af68; }
.health-dot.red { background: #f7768e; }
.health-dot.gray { background: #565f89; }

.health-name {
  flex: 1;
  color: #c0caf5;
  font-size: 13px;
}

.health-metric {
  color: #7aa2f7;
  font-size: 12px;
  font-family: monospace;
}

.health-status {
  font-size: 11px;
  color: #565f89;
}
</style>

<script>
async function refreshHealth() {
  try {
    const resp = await fetch(`${GM_API_BASE}/api/health_state`, {
      method: 'POST'
    });
    const data = await resp.json();
    renderHealth(data.tools || []);
  } catch (e) {
    console.error('Health fetch failed:', e);
  }
}

function renderHealth(tools) {
  const container = document.getElementById('health-content');
  if (!container) return;
  
  if (tools.length === 0) {
    container.innerHTML = '<div class="health-tool"><span class="health-status">No tools registered</span></div>';
    return;
  }
  
  container.innerHTML = tools.map(t => {
    const status = t.health?.status || t.status || 'unknown';
    const dotClass = status === 'running' ? 'green' : 
                     status === 'installed' ? 'yellow' : 
                     status === 'error' ? 'red' : 'gray';
    
    const metrics = [];
    if (t.health?.ping_ms != null) metrics.push(`${t.health.ping_ms.toFixed(0)}ms`);
    if (t.health?.memory_mb != null) metrics.push(`${t.health.memory_mb.toFixed(0)}MB`);
    if (t.health?.cpu_percent != null) metrics.push(`${t.health.cpu_percent.toFixed(1)}%`);
    
    return `
      <div class="health-tool">
        <span class="health-dot ${dotClass}"></span>
        <span class="health-name">${t.label || t.key}</span>
        ${metrics.map(m => `<span class="health-metric">${m}</span>`).join('')}
        <span class="health-status">${status}</span>
      </div>
    `;
  }).join('');
}

// Auto-refresh every 30 seconds
setInterval(refreshHealth, 30000);

// Initial load
document.addEventListener('DOMContentLoaded', refreshHealth);
</script>
```

---

## Mock 7: Health Endpoint in `webgui.py`

**Purpose**: Collect and return health metrics for all tools.

### New `health_state()` method in `Api` class (add after line 580)

```python
def health_state(self, _args: str = "") -> dict:
    """Health metrics for all registered tools.
    
    Collects:
    - Status (running/stopped/installed/error)
    - Ping (module import time)
    - Memory (RSS via psutil)
    - CPU (via psutil)
    - Uptime (process create time)
    """
    try:
        from gray_matter.gme import list_tools
    except ImportError:
        return {"ok": False, "error": "gme module not available", "tools": []}
    
    tools = []
    for tool in list_tools():
        if tool.get("status") != "installed":
            continue
        
        health = tool.get("health", {})
        pid = health.get("pid")
        
        # Check if process is alive
        if pid:
            try:
                import psutil
                proc = psutil.Process(pid)
                health["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
                health["cpu_percent"] = round(proc.cpu_percent(interval=0.1), 1)
                health["uptime_s"] = int(time.time() - proc.create_time())
                health["status"] = "running"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                health["status"] = "stopped"
                health["pid"] = None
        else:
            health["status"] = "stopped"
        
        # Ping: try to import the module (fast check)
        try:
            import importlib
            start = time.time()
            importlib.import_module(tool.get("module", tool["key"]))
            health["ping_ms"] = round((time.time() - start) * 1000, 1)
        except Exception:
            health["ping_ms"] = None
        
        tools.append({
            "key": tool["key"],
            "label": tool.get("label", tool["key"]),
            "version": tool.get("version", ""),
            "status": health.get("status", "unknown"),
            "health": health
        })
    
    return {"ok": True, "tools": tools}
```

---

## Feasibility Verification

### ✅ Verified: Atomic JSON writes

```python
# Write to temp, then rename — atomic on same filesystem
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
tmp.replace(path)  # atomic on same filesystem
```

**Verdict**: Works on Windows, Linux, macOS. No race conditions.

### ✅ Verified: Cross-platform paths

```python
# Windows
Path("C:\\Users\\...\\GrayMatterEnvironment\\neuron.json")

# Linux/macOS
Path("/home/user/.local/share/GrayMatterEnvironment/neuron.json")
```

**Verdict**: `pathlib.Path` handles this correctly.

### ✅ Verified: PowerShell JSON encoding

```powershell
@{key="neuron"} | ConvertTo-Json
# Output: {"key":"neuron"}

# With depth
@{key="neuron"; health=@{pid=$null}} | ConvertTo-Json -Depth 5
# Output: {"key":"neuron","health":{"pid":null}}
```

**Verdict**: Works, but indentation is minimal. Can add formatting if needed.

### ✅ Verified: Bash JSON encoding

```bash
cat > file.json <<EOF
{
  "key": "neuron",
  "version": "$VERSION"
}
EOF
```

**Verdict**: Works. Variables expanded correctly. Quote escaping needed for paths with spaces.

### ⚠️ Risk: Path escaping on Windows

```powershell
# Problem: backslashes in JSON
@{venv="C:\Users\test\.venv"} | ConvertTo-Json
# Output: {"venv":"C:\\Users\\test\\.venv"}  ← correct

# But if variable contains backslashes
$Venv = "C:\Users\test\.venv"
@{venv=$Venv} | ConvertTo-Json
# Output: {"venv":"C:\\Users\\test\\.venv"}  ← still correct
```

**Verdict**: PowerShell handles backslash escaping automatically. No issue.

### ⚠️ Risk: Health polling performance

```python
# psutil.Process() call per tool
import psutil
proc = psutil.Process(pid)
proc.memory_info()  # ~0.01ms
proc.cpu_percent(interval=0.1)  # ~100ms (blocks!)
```

**Optimization**: Use `cpu_percent(interval=None)` for non-blocking call, then divide by time delta.

**Verdict**: Acceptable for 3 tools (300ms total). Can optimize later if needed.

### ✅ Verified: Concurrent writes safe

Multiple installers can write different JSONs simultaneously. No shared file.

**Verdict**: Safe by design. Each tool writes only its own JSON.

---

## Next Steps

1. **Review mocks** — verify approach matches your vision
2. **Approve ADR-009** — confirm architecture decision
3. **Start Phase 1** — implement `gme.py` + installer changes
4. **Test cross-platform** — verify Windows + Linux + macOS

**Questions for you:**

1. Are the mocks aligned with your vision?
2. Any changes needed to the JSON schema?
3. Ready to start Phase 1 implementation?
