# ADR-009: Gray Matter Environment Registry

> Status: **Proposed** — 2026-07-26
> Relates to: ADR-008 (Memory Architecture), HANDOFF-2026-07-26

---

## Context

The Gray Matter ecosystem (GM + Neuron + NeuRAG) can run in two modes:
- **Full suite**: all tools in a shared venv (`%LOCALAPPDATA%\gray-matter\.venv`)
- **Standalone**: each tool in its own venv, possibly in different locations

The GUI (`webgui.py` + `catalog.py`) currently assumes all tools are importable from the same Python. When a tool runs standalone with its own venv, the GUI cannot discover or execute it.

**Root cause**: `catalog.py` uses `importlib.util.find_spec()` which only checks the current Python's path. `_python()` in `webgui.py` always returns `sys.executable` (GM's Python).

---

## Decision

Introduce **Gray Matter Environment (GME)** as a centralized registry folder that provides a single source of truth for all installed tools.

### Registry Location

```
%LOCALAPPDATA%\GrayMatterEnvironment\     (Windows)
~/.local/share/GrayMatterEnvironment/     (macOS/Linux)
```

### Folder Structure

```
GrayMatterEnvironment/
├── gray-matter.json       # metadata
├── neuron.json
├── neurag.json
├── gray-matter/           # venv + files (if consolidated)
│   └── .venv/
├── neuron/                # venv + files (if consolidated)
│   └── .venv/
└── neurag/                # venv + files (if consolidated)
    └── .venv/
```

### JSON Schema

Each tool writes a JSON file at the GME root:

```json
{
  "key": "neuron",
  "label": "Neuron",
  "version": "6.1.2",
  "venv": "C:\\Users\\...\\neuron\\.venv",
  "python": "C:\\Users\\...\\neuron\\.venv\\Scripts\\python.exe",
  "module": "neuron",
  "cli_module": "neuron.__main__",
  "status": "installed",
  "linked_to": "gray-matter",
  "source": "C:\\Desktop\\Gray Matter Environment\\neuron",
  "installed_at": "2026-07-26T12:00:00Z",
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
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | Unique identifier (`gray-matter`, `neuron`, `neurag`) |
| `label` | string | Human-readable name |
| `version` | string | Installed version (from `pyproject.toml`) |
| `venv` | string | Absolute path to the tool's venv |
| `python` | string | Absolute path to the Python executable in the venv |
| `module` | string | Python module name for `importlib.util.find_spec()` |
| `cli_module` | string | Module to invoke for CLI (`-m <cli_module>`) |
| `status` | enum | `installed` \| `error` \| `missing` \| `running` |
| `linked_to` | string\|null | `gray-matter` if GM-linked, `standalone` if independent |
| `source` | string | Path to the source checkout (for dev/reference) |
| `installed_at` | ISO8601 | Timestamp of last install/repair |
| `error` | string\|null | Last error message (if status=`error`) |
| `health` | object | Runtime metrics (populated on-demand) |

### Health Object

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int\|null | Process ID if running |
| `ping_ms` | float\|null | Latency of last health ping |
| `memory_mb` | float\|null | RSS memory usage |
| `cpu_percent` | float\|null | CPU utilization |
| `uptime_s` | int\|null | Seconds since process start |
| `last_check` | ISO8601\|null | When health was last checked |

---

## Consequences

### Positive
- **Single entry point**: any tool can discover siblings by reading GME folder
- **Multi-venv support**: GUI can execute tools in their correct Python
- **Health visibility**: real-time status in GUI sidebar
- **Migration path**: old installs can be consolidated into GME
- **Independent from GM**: tool can register even without GM installed

### Negative
- **Two sources of truth during transition**: GME JSON + `find_spec()` fallback
- **Health polling overhead**: `psutil` calls per tool (mitigated: on-demand only)
- **Migration complexity**: need to handle old venvs without breaking them

### Risks
- **Concurrent writes**: multiple installers writing to GME folder (mitigated: atomic JSON writes)
- **Stale JSON**: tool uninstalled but JSON remains (mitigated: status=`missing`, cleanup on next install)
- **Health race condition**: tool crashes between health checks (mitigated: `pid` check + `status` field)

---

## Alternatives Considered

### 1. Symlink-based discovery
- **Pros**: no data movement, instant
- **Cons**: Windows symlinks require admin/dev mode, breaks if original moved
- **Verdict**: rejected — too fragile for cross-platform tool

### 2. Physical move to GME
- **Pros**: clean single location
- **Cons**: requires admin rights, risky during migration, disk space during copy
- **Verdict**: rejected as default — offered as optional "consolidate" action

### 3. Registry-only (no venv movement)
- **Pros**: zero risk, instant, works now
- **Cons**: venvs scattered across system, but GME JSON points to them
- **Verdict**: **accepted** — the JSON is the SSOT, venv stays where it is

---

## Implementation Phases

| Phase | Description | Priority |
|-------|-------------|----------|
| 1 | Registry: installers write JSON to GME | Critical |
| 2 | Multi-venv: `_python()` reads JSON | Critical |
| 3 | Migration UI: detect old installs, consolidate button | Important |
| 4 | Health stream: top bar analytics (ping, mem, cpu) | Nice-to-have |

---

## References

- HANDOFF-2026-07-26.md — gap identification
- gray_matter/catalog.py — current discovery logic
- gray_matter/webgui.py — current execution logic
- gray_matter/clients.py — MCP registration (related but separate)
