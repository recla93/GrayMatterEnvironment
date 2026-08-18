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

# Per-client handshake assets (INSTALLER-UX §8b): the session-start hooks/plugins
# that inject the pre_turn/store_turn loop-guidance. They live in Neuron/clients/
# but their DEPLOY belongs to this unified installer, tracked in the manifest so
# uninstall removes exactly what was written. Clients without an entry rely on
# the MCP `instructions` GM serves at handshake.
HOOK_ASSETS = {
    "claude-code": "claude-code-hook/neuron_sessionstart_hook.py",
    "cowork": "cowork-plugin/neuron-guard",
    "opencode": "opencode-plugin/neuron-handshake.mjs",
    # codex consuma lo STESSO plugin cowork (formato .claude-plugin), non un
    # plugin nativo: lo copia nel suo cache e lo abilita in config.toml.
    "codex": "cowork-plugin/neuron-guard",
}


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
    # Handshake layer (§8b): deploy the per-client hook/plugin where one exists.
    # Only when Neuron is part of the install: the assets ship INSIDE the neuron
    # package and the hook injects Neuron's pre_turn/store_turn loop. On a
    # NeuRAG+GM install there is nothing to deploy — emitting the action anyway
    # produced a bogus "asset missing" error on a perfectly valid setup.
    if "neuron" in (state.get("installed") or []):
        for c in sorted(set(clients)):
            if c in HOOK_ASSETS:
                actions.append({"action": "deploy_hook", "client": c,
                                "asset": HOOK_ASSETS[c]})
    actions.append({"action": "write_manifest"})
    # GME registry (ADR-009) right after the manifest: the manifest answers
    # "what did we install", GME answers "which Python runs it". Emitted from
    # here rather than from the six shell installers because this is the step
    # every path reaches — the suite installs the peers with a bare pip and the
    # peers' own GME blocks only run in standalone mode. See gme.register_installed.
    actions.append({"action": "register_gme"})
    return actions


def record_install(state: dict, path=None):
    """Persist an install manifest reflecting `state`. The gateway is always marked
    registered; sub-tools are marked present (data ensured) but not registered."""
    import sys
    from gray_matter import paths as _paths   # lazy: keeps plan() import-free/testable
    m = _paths.Manifest.load(path)
    # The venv is the single biggest thing an install writes and it was recorded
    # nowhere, so uninstall could neither show it nor remove it. Recording it also
    # makes an install at the OLD location (<base>/gray-matter/.venv) removable by
    # a current uninstaller — both layouts are in the wild.
    if sys.prefix != sys.base_prefix:
        m.data["venv"] = sys.prefix
    for comp in state.get("installed", []):
        if comp != GATEWAY:
            m.record_component(comp, present=True, registered=False)
    m.record_component(GATEWAY, present=True, registered=True)
    if state.get("clients"):
        m.set_clients(state["clients"])
    # hooks: client -> deployed path(s), so uninstall knows exactly what to remove
    for client, dest in (state.get("hooks") or {}).items():
        for p in ([dest] if isinstance(dest, str) else dest):
            m.record_hook(client, p)
    m.save(path)
    return m
