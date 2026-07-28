"""GM uninstaller + legacy scan (INSTALLER-UX §6).

Pure planning brain (`plan`, `legacy_scan_plan`) — fully testable, no side effects.
The effectful steps it emits (kill processes, deregister clients, remove files) run
**locally** (they touch live processes, the 6 client configs and the disk).

Data policy = INTERACTIVE (user's choice): the user's memory (graph/DB/bridges)
becomes `ask_data` actions — never removed without an explicit yes. `purge_data=True`
downgrades them to `remove_data` for a full wipe.
"""
from __future__ import annotations


def plan(manifest: dict, *, purge_data: bool = False,
         orphan_pids=None, data_paths=None) -> list[dict]:
    """Ordered, precise removal plan from an install manifest.

    Order: reap live processes → deregister from clients → remove per-client hooks
    → remove code/binaries → handle the memory (ask, or wipe if purge_data)."""
    actions: list[dict] = []
    orphans = orphan_pids or []
    if orphans:
        actions.append({"action": "reap", "pids": list(orphans)})
    clients = (manifest or {}).get("clients") or []
    if clients:
        actions.append({"action": "deregister", "clients": sorted(set(clients))})
    hooks = (manifest or {}).get("hooks") or {}
    for client, hpaths in sorted(hooks.items()):
        for p in hpaths:
            actions.append({"action": "remove_hook", "client": client, "path": p})
    actions.append({"action": "remove_code"})   # app/, config.json, logs/, manifest, pids
    # The GME registry entry outlives the code unless we say so: catalog.py and
    # webgui.py would keep handing out a `python` path into a venv that is no
    # longer there. Marked *missing* rather than deleted so a later reinstall
    # (and the migration card) still sees the tool was once registered here.
    actions.append({"action": "unregister_gme", "key": "gray-matter"})
    for name, path in sorted((data_paths or {}).items()):
        actions.append({"action": "remove_data" if purge_data else "ask_data",
                        "name": name, "path": str(path)})
    return actions


# What a `--deep` legacy scan hunts for on the host PC. Descriptors only — the
# actual filesystem/process/config walk is effectful and runs locally.
LEGACY_TARGETS = [
    {"kind": "old_slug",     "desc": "data dir del vecchio slug 'neuron5' (lo slug attuale è 'neuron')"},
    {"kind": "old_name",     "desc": "artefatti 'neural-stimulus'/'neural_stimulus' (vecchio nome)"},
    {"kind": "path_scripts", "desc": "script neuron*/gray-matter rimasti su PATH"},
    {"kind": "stale_client", "desc": "entry MCP orfane nei config client (slug non installato)"},
    {"kind": "orphan_procs", "desc": "processi neuron/neurag/gray_matter vivi non tracciati"},
]


def legacy_scan_plan() -> list[dict]:
    return list(LEGACY_TARGETS)
