"""GM-centric installer orchestration (INSTALLER-UX §5).

The idempotency brain is the pure `plan()` — fully testable, no side effects. The
effectful steps it emits (reap processes, spawn/upgrade GM, register in clients,
write manifest) are executed by thin wrappers run **locally** (they touch the OS,
the 6 client configs and live processes, so they can't be verified in the sandbox).

Two decisions are hard-coded here, matching the proxy model:
  - register **only the gateway** (Gray-Matter) in MCP clients — never the
    sub-servers, which run as GM-managed workers;
  - idempotent: install GM only if missing; reap orphan processes before writing.
"""
from __future__ import annotations

GATEWAY = "gray_matter"   # the ONLY server registered in MCP clients (§1 proxy model)


def plan(state: dict) -> list[dict]:
    """Turn a detected state into an ordered, idempotent action list (pure).

    ``state`` keys (all optional):
      installed:    list of trio components present/requested (e.g. ["neuron"])
      gm_present:   bool — is a healthy Gray-Matter already installed?
      clients:      list of detected MCP clients to (re)register
      orphan_pids:  list of stale trio PIDs to terminate first
    """
    actions: list[dict] = []
    orphans = state.get("orphan_pids") or []
    if orphans:
        actions.append({"action": "reap", "pids": list(orphans)})
    # Sub-tools get their data dir ensured but are NOT registered in clients.
    for comp in state.get("installed", []):
        if comp != GATEWAY:
            actions.append({"action": "ensure_data", "component": comp})
    if not state.get("gm_present"):
        actions.append({"action": "install", "component": GATEWAY})
    clients = state.get("clients") or []
    if clients:
        actions.append({"action": "register", "target": GATEWAY,
                        "clients": sorted(set(clients))})
    actions.append({"action": "write_manifest"})
    return actions


def record_install(state: dict, path=None):
    """Persist an install manifest reflecting `state`. The gateway is always marked
    registered; sub-tools are marked present (data ensured) but not registered."""
    from gray_matter import paths as _paths   # lazy: keeps plan() import-free/testable
    m = _paths.Manifest.load(path)
    for comp in state.get("installed", []):
        if comp != GATEWAY:
            m.record_component(comp, present=True, registered=False)
    m.record_component(GATEWAY, present=True, registered=True)
    if state.get("clients"):
        m.set_clients(state["clients"])
    m.save(path)
    return m
