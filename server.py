"""Gray-Matter MCP server — proxy + orchestrator.

Runs as a stdio MCP server that:
1. Accepts tool calls from the client
2. Routes them to the right registered MCP server (Neuron, NeuRAG)
3. Returns the response to the client
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.types import Tool, TextContent

from gray_matter import __version__
from gray_matter.cache import ContextCache
from gray_matter.registry import Registry
from gray_matter import settings as _settings

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tunable knobs (see `gray-matter config`): read once at startup — `config set`
# takes effect on the next restart. Missing/unknown keys fall back to defaults.
_cfg = _settings.load()

# SSOT in cli.py: la CLI (e la GUI) devono conoscere host/porta SENZA
# importare questo modulo, che trascina `mcp` e tutto il server.
# _send_ipc/_recv_exact vivono in cli.py con host e porta (stesso SSOT). Qui ne
# esisteva una COPIA sincrona, resa irraggiungibile dall'omonima `async
# _recv_exact` definita più sotto: Python risolve i globali alla chiamata, così
# `_send_ipc` finiva per invocare la coroutine con 2 argomenti su 3 →
# TypeError. Effetto: _send_heartbeat/_send_registration fallivano SEMPRE →
# NeuRAG standalone moriva all'avvio (autoregister non è protetto) e Neuron non
# si registrava mai al gateway, in silenzio. Una copia sola, importata.
from gray_matter.cli import (GRAY_MATTER_HOST, GRAY_MATTER_PORT,  # noqa: E402
                             GRAY_MATTER_PORT_SPAN, resolve_port, write_port_file,
                             clear_port_file, port_is_free, gm_answers,
                             _send_ipc, IPC_TOOL_TIMEOUT)
HEARTBEAT_INTERVAL = _cfg["heartbeat_interval"]  # seconds
HEARTBEAT_TIMEOUT = 15.0  # seconds — after 3 missed beats, mark dead
IDLE_SLEEP_TIMEOUT = _cfg["idle_sleep_timeout"]  # sleep after this long idle

# ---------------------------------------------------------------------------
# IPC helpers (tiny TCP-based protocol for server <-> Gray-Matter)
# ---------------------------------------------------------------------------

def _send_registration(name: str, tool_names: list[str], socket_path: str, pid: int) -> dict:
    """Register this server with Gray-Matter."""
    return _send_ipc({
        "action": "register",
        "name": name,
        "tool_names": tool_names,
        "socket_path": socket_path,
        "pid": pid,
    })


def _send_heartbeat(name: str) -> dict:
    """Send a heartbeat ping."""
    return _send_ipc({
        "action": "heartbeat",
        "name": name,
    })


def _is_gray_matter_running() -> bool:
    """Check if a Gray-Matter process is listening on the IPC port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect((GRAY_MATTER_HOST, resolve_port()))
            s.close()
            return True
    except (ConnectionRefusedError, TimeoutError, OSError):
        return False


def autoregister(name: str, tool_names: list[str]) -> bool:
    """Auto-register with a running Gray-Matter. Returns True on success.

    If Gray-Matter is not running, spawns one first.
    Then registers this server.
    """
    # Spawn Gray-Matter if not running
    if not _is_gray_matter_running():
        _spawn_gray_matter()

    # Register (retry up to 3 times — race with spawn)
    pid = os.getpid()
    socket_path = f"tcp://{GRAY_MATTER_HOST}:{os.getpid() + 50000}"  # dummy, placeholder
    for attempt in range(3):
        result = _send_registration(name, tool_names, socket_path, pid)
        if "error" not in result:
            return True
        time.sleep(0.3)
    return False


def daemon_log_path():
    """Il log del daemon (G2): stdout+stderr del processo finiscono qui."""
    from gray_matter.paths import logs_dir
    return logs_dir() / "daemon.log"


def _spawn_gray_matter() -> None:
    """Spawn Gray-Matter as a background process."""
    # Use python -m gray_matter.server to run the server module
    # Detach from parent process so it survives parent death
    cmd = [sys.executable, "-u", "-m", "gray_matter.server", "--daemon"]  # -u: log senza buffering
    creationflags = 0
    if sys.platform == "win32":
        # NIENTE DETACHED_PROCESS. Windows IGNORA CREATE_NO_WINDOW quando è
        # combinato con DETACHED_PROCESS (o CREATE_NEW_CONSOLE), e il figlio
        # staccato si alloca una console TUTTA SUA — la finestra CMD vuota che
        # compariva a ogni `gray-matter start`. Misurato sul posto:
        #   CREATE_NO_WINDOW | DETACHED_PROCESS -> console visibile
        #   CREATE_NO_WINDOW                    -> nessuna console
        #   CREATE_NO_WINDOW | NEW_PROCESS_GROUP-> nessuna console
        # DETACHED_PROCESS non serviva comunque a far sopravvivere il daemon:
        # su Windows i figli non muoiono col padre (non c'è kill dell'albero
        # senza un Job object). Il gruppo separato serve solo a NON prendere il
        # Ctrl-C della console che l'ha avviato.
        creationflags = (subprocess.CREATE_NO_WINDOW
                         | subprocess.CREATE_NEW_PROCESS_GROUP)

    # G2: stdout/stderr → logs/daemon.log (append) invece del buco nero — ogni
    # print e traceback diventa leggibile con `gray-matter logs [--follow]`.
    # Fallback DEVNULL se il file non è apribile (mai bloccare lo spawn).
    try:
        log_path = daemon_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
        out.write(f"\n--- spawn {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        out.flush()
    except OSError:
        out = None
    stdout_err = out if out is not None else subprocess.DEVNULL
    try:
        subprocess.Popen(
            cmd,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=stdout_err,
            stderr=stdout_err,
        )
    finally:
        if out is not None:
            out.close()  # parent FD closed; child inherited it


# ---------------------------------------------------------------------------
# Gray-Matter MCP Server
# ---------------------------------------------------------------------------

_registry = Registry.instance()
_last_call_time: float = time.time()
_flash_counter: int = 0

# ONE shared context cache. It used to be re-created inside every pulse, so it
# never hit — a silent "cache that never caches" bug. A single instance persists
# across calls and makes `gray-matter stats` hit-rate meaningful.
_ctx_cache = ContextCache(max_size=_cfg["cache_max_size"], ttl=_cfg["cache_ttl_seconds"])

# Lightweight observability counters, surfaced by `gray-matter stats` / `doctor`.
_stats: dict[str, float] = {"pulses": 0, "cache_hits": 0, "cache_misses": 0,
                            "flashes": 0, "bridges_added": 0, "pulse_ms_total": 0.0}

# D4 — conversation buffer: gli ultimi topic della sessione. Ogni pulse espande
# la query NeuRAG col contesto recente (recall migliore su domande incrementali);
# Neuron non ne ha bisogno (ha già la sua context window interna).
from collections import deque as _deque
_topic_buffer: "_deque[str]" = _deque(maxlen=3)


def _remember_topic(topic: str) -> None:
    if topic in _topic_buffer:          # ri-chiesto → torna in cima
        _topic_buffer.remove(topic)
    _topic_buffer.append(topic)


# Flash v1: fire on a topic shift (serendipity at transitions), rate-limited.
_last_topic: str = ""
_flashed: set = set()          # concepts already flashed this session (cooldown)
_calls_since_flash: int = 0
FLASH_MIN_GAP = _cfg["flash_min_gap"]   # min pulses between flashes (anti-spam)

# Stimulus safety-net (design §Decisioni 3): il motore degli stimoli è di Neuron
# (piggyback 🧠 sui suoi tool); se l'LLM smette di far passare stimoli per N
# turni-tool, GM lo rilancia LUI sul prossimo pass-through. Toggle/tuning in
# settings (→ GUI Preferences): stimulus_safety_net / stimulus_safety_gap.
STIM_SAFETY_NET = _cfg["stimulus_safety_net"]
STIM_SAFETY_GAP = _cfg["stimulus_safety_gap"]
_turns_since_stim: int = 0

# Quanto contesto GM inietta. Il punto del progetto è far RISPARMIARE token, e
# fino a qui la quantità era un effetto collaterale: il blocco proattivo (bridge,
# vicini, flash) non aveva alcun tetto, e 40 bridge che condividevano un tag
# facevano ~5000 token in una sola pulse. Ora è un budget, regolabile dalla GUI.
KNOWLEDGE_TOP_N = _cfg["knowledge_top_n"]
PROACTIVE_BUDGET = _cfg["proactive_budget_chars"]
# Quanti bridge al massimo per pulse. Non è un knob: il budget in caratteri è
# già la manopola: questo è solo la difesa che evita di RINFORZARE (e quindi
# promuovere) decine di bridge per poi scartarne il testo.
_BRIDGES_PER_PULSE = 5
# Quanto razionale mostrare per bridge. Lo store ne accetta 500 caratteri perché
# lì è documentazione che un umano legge in `gray-matter bridges`; iniettarli
# interi in una pulse voleva dire spendere il budget su cinque paragrafi.
_BRIDGE_WHY_CHARS = 80


def _fit(budget: int, blocks: list[str]) -> tuple[str, int]:
    """Take blocks in priority order, keeping each that still fits in `budget`.

    Trims by BLOCK, never mid-sentence: half a bridge line costs the same
    context as a whole one and reads like a bug. Returns the joined text and how
    many blocks were dropped, so the caller can say so instead of the reader
    wondering.

    A block too big to fit is SKIPPED, not a stop signal — a later, smaller one
    still gets in. These are independent hints, so more of them inside the same
    budget is worth more than a strict prefix of the priority order."""
    kept, used, dropped = [], 0, 0
    for b in blocks:
        if not b:
            continue
        if used + len(b) > budget:
            dropped += 1
            continue
        kept.append(b)
        used += len(b)
    return "\n\n".join(kept), dropped


def _stim_seen(text: str) -> None:
    """Un pulse/risposta che già porta stimoli (🧠/⚡) azzera il contatore."""
    global _turns_since_stim
    if "🧠" in text or "⚡" in text:
        _turns_since_stim = 0


async def _safety_net_note(tool_name: str, arguments: dict, result: str) -> str:
    """Rete di sicurezza: '' quasi sempre; una riga 🧠 quando il piggyback tace
    da STIM_SAFETY_GAP turni. Best-effort, mai bloccante, anti-recursione (parla
    col worker Neuron direttamente, non ri-entra in call_tool)."""
    global _turns_since_stim
    if not STIM_SAFETY_NET:
        return ""
    if "🧠" in result or "⚡" in result:
        _turns_since_stim = 0                     # lo stimolo è passato: riposa
        return ""
    _turns_since_stim += 1
    if _turns_since_stim < STIM_SAFETY_GAP:
        return ""
    neuron = _registry.get_server("neuron")
    if not neuron or not neuron.is_alive():
        return ""
    near = str(arguments.get("topic") or arguments.get("query") or "").strip()
    try:
        forgotten = (await _call_server_async(
            "neuron", "forgotten",
            {"threshold": 5, "near": near, "top_n": 1})).strip()
    except Exception:  # noqa: BLE001
        return ""
    if not forgotten or forgotten.startswith("["):
        return ""
    _turns_since_stim = 0
    _stats["flashes"] += 1
    return f"\n\n🧠 (GM safety-net) {forgotten}"


_is_sleeping: bool = False

app = Server("gray-matter")

# MCP handshake instructions (INSTALLER-UX §8b): the loop-guidance for clients
# that honor `instructions` (Cursor/VS Code/Codex) — no hook needed there. The
# per-client hooks stay for clients that ignore this field. Keep in sync with
# Neuron/clients/claude-code-hook (same loop, GM-gateway flavored).
GM_INSTRUCTIONS = (
    "Gray-Matter gateway: Neuron (persistent semantic memory) + NeuRAG (knowledge "
    "base) behind one proxy — their tools are served here pass-through.\n"
    "Each substantive turn: call pre_turn(topic, keywords) BEFORE replying (fold "
    "the returned context in silently), then store_turn(topic, keywords, links) "
    "AFTER, to persist what is new. gray_matter_pulse(topic) merges memory + "
    "knowledge + flash in one call.\n"
    "Keywords = 3-5 concept NOUNS (no verbs/paths); links typed, never a "
    "self-link; before minting a concept check find_candidates; never store "
    "secrets or tokens. Skip on procedural turns (ack/thanks/yes-no)."
)


  # server_name -> consecutive failures


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Dynamically list tools from all registered servers."""
    tools = []

    # Gray-Matter's own tools
    tools.append(Tool(
        name="gray_matter_pulse",
        description="Pre-contesto + chunk knowledge + flash. Chiama neuron_get_context e neurag_query in parallelo, unisce, usa cache.",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic da cercare"},
                "top_n": {
                    "type": "integer", "description": "Numero chunk (default 5)",
                    "default": 5, "minimum": 1, "maximum": 10,
                },
            },
            "required": ["topic"],
        },
    ))
    tools.append(Tool(
        name="gray_matter_status",
        description="Show Gray-Matter status: registered servers, cache, counters.",
        inputSchema={"type": "object", "properties": {}},
    ))
    tools.append(Tool(
        name="gray_matter_bridge",
        description="Persist a cross-store bridge: a link between a Neuron concept and a NeuRAG knowledge node the orchestrator found to relate. Recalled in future pulses on either endpoint.",
        inputSchema={
            "type": "object",
            "properties": {
                "neuron_concept": {"type": "string", "description": "Neuron concept/keyword"},
                "neurag_node": {"type": "string", "description": "NeuRAG node/topic"},
                "rationale": {"type": "string", "description": "Why they connect"},
            },
            "required": ["neuron_concept", "neurag_node"],
        },
    ))

    # Tools from registered servers (F12: re-publish REAL schemas, fetched once
    # from each worker and cached; fall back to an empty schema if unavailable so
    # list_tools never blocks on a cold/broken worker).
    for server in _registry.alive_servers():
        await _ensure_schemas(server)
        for tool_name in server.tool_names:
            meta = server.tool_schemas.get(tool_name) or {}
            tools.append(Tool(
                name=tool_name,
                description=meta.get("description") or f"({server.name}) {tool_name}",
                inputSchema=meta.get("inputSchema") or {"type": "object", "properties": {}},
            ))

    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    global _last_call_time, _flash_counter

    _last_call_time = time.time()
    _flash_counter += 1

    # --- Gray-Matter orchestrated tools ---

    if name == "gray_matter_pulse":
        global _is_sleeping
        _is_sleeping = False
        # Validate the topic (mirror of the bridge ingest guard): coerce, strip,
        # collapse whitespace, cap. Empty/whitespace-only -> nothing to search.
        topic = " ".join(str(arguments.get("topic", "")).split())[:200]
        if not topic:
            return [TextContent(type="text", text="pulse: empty topic.")]
        top_n = min(max(int(arguments.get("top_n", KNOWLEDGE_TOP_N)), 1), 10)
        _t0 = time.monotonic()
        _stats["pulses"] += 1
        _remember_topic(topic)   # D4: conversation buffer (anche sui cache hit)

        # Cache hit? (one shared cache — see _ctx_cache)
        cached = _ctx_cache.get(topic)
        if cached is not None:
            _stats["cache_hits"] += 1
            return [TextContent(type="text", text=cached)]
        _stats["cache_misses"] += 1

        # Collect calls to registered servers (track which is which for v3b).
        tasks, labels = [], []

        neuron = _registry.get_server("neuron")
        if neuron and neuron.is_alive() and neuron.collaborative:
            tasks.append(_call_server_async("neuron", "get_context", {"topic": topic, "depth": 1})); labels.append("neuron")

        neurag = _registry.get_server("neurag")
        if neurag and neurag.is_alive() and neurag.collaborative:
            # D4 — multi-turn RAG: espandi la query NeuRAG con i topic recenti
            # (Neuron ha già la sua context window; la cache resta keyed sul
            # topic puro, quindi l'espansione non inquina i cache hit).
            recent = [t for t in _topic_buffer if t != topic]
            rag_query = topic + (" " + " ".join(recent) if recent else "")
            tasks.append(_call_server_async("neurag", "knowledge_query", {"query": rag_query[:300], "top_n": top_n})); labels.append("neurag")

        if not tasks:
            return [TextContent(type="text", text="No servers available for pulse.")]

        # Parallel execution
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Auto-build cross-links once: if NeuRAG has nodes but zero links,
        # rebuild so future queries get link enrichment. One-shot per session.
        global _neurag_links_built
        if not _neurag_links_built and "neurag" in labels:
            try:
                status_raw = await _call_server_async("neurag", "knowledge_status", {})
                import json as _json
                ns = _json.loads(status_raw) if isinstance(status_raw, str) else status_raw
                if ns.get("links", 0) == 0 and ns.get("nodes", 0) > 1:
                    await _call_server_async("neurag", "knowledge_rebuild_links", {})
            except Exception:  # noqa: BLE001
                pass
            _neurag_links_built = True

        context_parts = []
        neurag_hit = False
        for lbl, r in zip(labels, results):
            if isinstance(r, Exception):
                context_parts.append(f"[error: {r}]")
            elif r:
                context_parts.append(r)
                if lbl == "neurag" and "No results" not in str(r):
                    neurag_hit = True

        response = "\n---\n".join(context_parts) if context_parts else "No results."

        # D3 — knowledge proattiva: vicini strutturati del nodo NeuRAG matchato
        # (parent/children/links, depth 2) non già presenti nella risposta.
        # JSON dal tool knowledge_neighbors: niente parsing di prosa (anti-F15).
        # Va PRIMA dei bridge: la stessa risposta porta i tag canonici del nodo,
        # ed è su quelli che i bridge fanno il join (§4). Un secondo round-trip
        # solo per chiedere quattro parole non lo vogliamo nella pulse.
        # Tutto ciò che segue è PROATTIVO: non l'ha chiesto nessuno, quindi vive
        # dentro `proactive_budget_chars`. A 0 la pulse resta solo le risposte
        # vere — che è una risposta legittima per chi ha il contesto stretto.
        proactive: list[str] = []
        neurag_tags: set[str] = set()
        if neurag_hit and PROACTIVE_BUDGET > 0:
            try:
                import json as _json
                raw = await _call_server_async(
                    "neurag", "knowledge_neighbors",
                    {"query": topic, "depth": 2, "limit": 5})
                data = _json.loads(raw)
                neurag_tags = {str(t) for t in (data.get("tags") or [])}
                fresh = [n["name"] for n in data.get("neighbors", [])
                         if n.get("name") and n["name"].lower() not in response.lower()][:3]
                if fresh:
                    proactive.append("💡 Potrebbe interessarti: " + ", ".join(fresh))
            except Exception:  # noqa: BLE001 — proattiva = best-effort, mai bloccare la pulse
                pass

        # Cross-store bridges the orchestrator has persisted for this topic.
        # Matched on whole tokens AND on the tag identity above — a bridge to a
        # node whose NAME says nothing about the topic is reachable through its
        # tags, which is the whole point of the substrate.
        rel = []
        if PROACTIVE_BUDGET > 0:
            from gray_matter.bridges import bridges_for
            # Il limite è anche sul RINFORZO: mostrare un bridge è ciò che conta
            # come usarlo, quindi non si rinforza quello che non entra.
            rel = bridges_for(topic, tags=neurag_tags, limit=_BRIDGES_PER_PULSE)
        if rel:
            # Un bridge per blocco, così il budget ne impacchetta quanti stanno
            # invece di scartarli in massa. E il razionale va TRONCATO: lo store
            # lo accetta fino a 500 caratteri perché è documentazione, ma qui è
            # un suggerimento iniettato — cinque razionali interi da soli
            # sfondavano il budget e facevano cadere tutti i bridge.
            for b in rel:
                why = (b.get("rationale") or "").strip()
                if len(why) > _BRIDGE_WHY_CHARS:
                    why = why[:_BRIDGE_WHY_CHARS - 1].rstrip() + "…"
                proactive.append(f"🔗 {b['neuron']} ↔ {b['neurag']}"
                                 + (f" — {why}" if why else ""))
            # B4 — bridge appena promosso (5+ usi reali): il concetto Neuron ha
            # dimostrato valore, confermalo (salience + trust). Best-effort.
            promoted = [b["neuron"] for b in rel if b.pop("_just_promoted", False)]
            if promoted:
                try:
                    await _call_server_async("neuron", "confirm",
                                             {"keywords": promoted, "confidence": 0.5})
                except Exception:  # noqa: BLE001
                    pass

        # Flash: serendipitous dormant-concept recall, fired at a topic shift.
        if PROACTIVE_BUDGET > 0:
            flash_note, concept = await _maybe_flash(topic)
            if flash_note:
                proactive.append(flash_note)
                # v3b auto-discovery: a mid-band dormant Neuron concept surfaced on a
                # topic where NeuRAG has real knowledge → that co-occurrence is a bridge
                # worth keeping. Persist it (idempotent, gated by the flash rate-limit).
                if concept and neurag_hit:
                    from gray_matter.bridges import add_bridge
                    if add_bridge(concept, topic, f"co-surfaced on '{topic}'"):
                        _stats["bridges_added"] += 1

        # Il flash è primo: è l'unico contenuto proattivo che non si può
        # ri-ottenere chiedendo (i bridge stanno in `gray-matter bridges`, i
        # vicini in `knowledge_neighbors`). Un flash tagliato è perso.
        extra, dropped = _fit(PROACTIVE_BUDGET, list(reversed(proactive)))
        if extra:
            response += "\n\n" + extra
        if dropped:
            response += (f"\n\n(+{dropped} spunti omessi: budget proattivo "
                         f"{PROACTIVE_BUDGET} char — `gray-matter config set "
                         f"proactive_budget_chars <n>`)")

        # Cache + record the real-work latency (this was a miss).
        _stim_seen(response)          # un pulse con stimoli ricarica il safety-net
        _ctx_cache.set(topic, response)
        _stats["pulse_ms_total"] += (time.monotonic() - _t0) * 1000

        return [TextContent(type="text", text=response)]

    if name == "gray_matter_status":
        lines = [
            f"Gray-Matter v{__version__}",
            f"Flash counter: {_flash_counter}",
            f"Servers: {len(_registry.all_servers())}",
            _registry.summary(),
        ]
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "gray_matter_bridge":
        from gray_matter.bridges import add_bridge
        created = add_bridge(arguments["neuron_concept"], arguments["neurag_node"],
                             arguments.get("rationale", ""))
        return [TextContent(type="text", text="Bridge saved." if created else "Bridge already exists.")]

    # A write to episodic memory can make a cached pulse stale: drop the entries
    # for the just-written topic so the next pulse rebuilds fresh (targeted, not a
    # full flush — other topics keep their cache).
    if name == "store_turn":
        _ctx_cache.invalidate_related(str(arguments.get("topic", "")))

    # --- Route to registered server (pass-through) ---
    server = _registry.find_server_by_tool(name)
    if server is None:
        return [TextContent(type="text", text=f"Tool '{name}' not found in any registered server.")]

    result = await _call_server_async(server.name, name, arguments)
    # Rete di sicurezza stimoli: se il piggyback di Neuron non passa da troppi
    # turni (LLM ha "dimenticato" i tool giusti), GM lo rilancia qui.
    note = await _safety_net_note(name, arguments, result or "")
    return [TextContent(type="text", text=(result or "(empty)") + note)]


# Persistent workers: one long-lived subprocess per server (imported once, model
# kept warm) instead of a cold-import subprocess per call. See gray_matter/_worker.py.
_workers: dict = {}          # server_name -> Popen
_worker_locks: dict = {}     # server_name -> asyncio.Lock (serialize the shared pipe)
_worker_lat: dict = {}       # server_name -> {calls, ms_total, last_ms} (tempo NEL tool)
_prewarmed: set = set()      # servers already warmed (D2), so we warm each once
_neurag_links_built: bool = False  # auto-build links once when links=0 and nodes>1

# Cheap read fired to warm a worker: spawns the subprocess (pays the import) and
# loads the model (Neuron's fastembed) BEFORE the first real pulse, so that pulse
# isn't the one paying the ~cold-start tax. Unknown servers get import-warm only.
_WARM_TOOL = {
    "neuron": ("status", {}),
    "neurag": ("knowledge_query", {"query": "warmup", "top_n": 1}),
}


async def _prewarm_workers():
    """D2: pre-warm persistent workers so the FIRST pulse is fast, not cold.

    Waits for servers to register (the registry starts empty), then spawns each
    collaborative server's worker and fires one cheap read to load its model.
    Best-effort: on any failure the server is left un-warmed and the lazy path in
    `_worker_for` still handles it on demand. Disable with GM_PREWARM=0."""
    if os.environ.get("GM_PREWARM", "1" if _cfg["prewarm"] else "0") == "0":
        return
    while True:
        for s in _registry.alive_servers():
            if s.name in _prewarmed or not s.collaborative:
                continue
            _prewarmed.add(s.name)                     # mark first: don't hammer on repeated failure
            tool, args = _WARM_TOOL.get(s.name, (None, None))
            try:
                if tool is None:
                    _worker_for(s.name)                # unknown server: at least pay the import now
                else:
                    await _call_server_async(s.name, tool, args)
            except Exception:  # noqa: BLE001
                _prewarmed.discard(s.name)             # let a later sweep (or lazy path) retry
        await asyncio.sleep(2)


def _worker_for(server_name: str):
    pkg = {"neurag": "neurag.server", "neuron": "neuron.server"}.get(server_name, server_name + ".server")
    p = _workers.get(server_name)
    if p is None or p.poll() is not None:        # not started, or died -> (re)spawn
        # Windows: suppress the console window for the worker (a piped child would
        # otherwise pop a visible CMD). GM's daemon already does this; the worker
        # didn't — harmless before, but the startup self-bootstrap now spawns it
        # eagerly, so the window showed at launch.
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        p = subprocess.Popen(
            [sys.executable, "-m", "gray_matter._worker", pkg],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
            creationflags=creationflags,
        )
        _workers[server_name] = p
    return p


async def _call_server_async(server_name: str, tool_name: str, arguments: dict) -> str:
    """Call a server tool via its persistent worker (imported once, model kept warm)."""
    lock = _worker_locks.setdefault(server_name, asyncio.Lock())
    async with lock:                              # one request at a time per pipe
        p = _worker_for(server_name)
        # get_running_loop, not get_event_loop: all three call sites are inside
        # coroutines, and get_event_loop() is deprecated when a loop is already
        # running (3.12+) — on 3.14 the no-loop case raises outright.
        loop = asyncio.get_running_loop()

        def _io() -> str:
            p.stdin.write(json.dumps({"tool": tool_name, "args": arguments}) + "\n")
            p.stdin.flush()
            return p.stdout.readline()

        try:
            # First Neuron call loads fastembed -> allow headroom.
            resp_line = await asyncio.wait_for(loop.run_in_executor(None, _io), timeout=60)
        except Exception as e:  # noqa: BLE001 — timeout or pipe error: drop the worker
            try:
                p.kill()
            except Exception:
                pass
            _workers.pop(server_name, None)
            _registry.mark_dead(server_name)
            return f"[{server_name}] error: {e}"

    if not resp_line:
        _registry.mark_dead(server_name)
        return f"[{server_name}] error: worker gave no response"
    try:
        resp = json.loads(resp_line)
    except Exception:
        return f"[{server_name}] error: bad worker response"
    if not resp.get("ok"):
        # ponytail: trace nel messaggio — L2 è intermittente, quando ricapita
        # vogliamo il traceback intero, non solo str(e)
        tail = f"\n{resp['trace']}" if resp.get("trace") else ""
        return f"[{server_name}] error: {resp.get('error')}{tail}"
    # Cronometro per server: il worker misura l'esecuzione del tool (modello
    # già caldo, senza pipe/proxy) — è il numero che dice DOVE va il tempo.
    if resp.get("ms") is not None:
        lat = _worker_lat.setdefault(server_name, {"calls": 0, "ms_total": 0.0, "last_ms": 0.0})
        lat["calls"] += 1
        lat["ms_total"] += float(resp["ms"])
        lat["last_ms"] = float(resp["ms"])
    return resp["text"]


async def _fetch_tool_schemas(server_name: str) -> dict:
    """F12: ask a server's worker for its real tool list (name -> {description,
    inputSchema}) so GM can re-publish accurate pass-through schemas. Best-effort:
    returns {} on any failure (caller falls back to an empty schema)."""
    lock = _worker_locks.setdefault(server_name, asyncio.Lock())
    async with lock:
        p = _worker_for(server_name)
        loop = asyncio.get_running_loop()

        def _io() -> str:
            p.stdin.write(json.dumps({"op": "list_tools"}) + "\n")
            p.stdin.flush()
            return p.stdout.readline()

        try:
            resp_line = await asyncio.wait_for(loop.run_in_executor(None, _io), timeout=60)
        except Exception:  # noqa: BLE001 — pipe/timeout: leave schemas unknown
            return {}
    try:
        resp = json.loads(resp_line)
    except Exception:  # noqa: BLE001
        return {}
    if not resp.get("ok"):
        return {}
    return {
        t["name"]: {"description": t.get("description") or "",
                    "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}}
        for t in resp.get("tools", []) if t.get("name")
    }


async def _ensure_schemas(server) -> None:
    """Populate a server's real tool schemas once (cached on the ServerEntry)."""
    if server.tool_schemas:
        return
    schemas = await _fetch_tool_schemas(server.name)
    if schemas:
        server.tool_schemas = schemas


_SUBSERVER_MODULES = {"neuron": "neuron.server", "neurag": "neurag.server"}


def detect_subservers() -> list[str]:
    """Installed sub-servers importable right now (gateway self-discovery).

    Un tool andato standalone (`<tool> go-standalone` / `gray-matter deregister
    --tool ...`) è escluso anche se importabile: ha la sua entry MCP diretta nei
    client — ri-gestirlo qui duplicherebbe i suoi tool."""
    import importlib.util
    try:
        from gray_matter.clients import unmanaged_tools
        skip = unmanaged_tools()
    except Exception:  # noqa: BLE001 — mai bloccare il bootstrap
        skip = set()
    out = []
    for name, mod in _SUBSERVER_MODULES.items():
        if name in skip:
            continue
        try:
            if importlib.util.find_spec(mod) is not None:
                out.append(name)
        except Exception:  # noqa: BLE001 — broken/partial install
            pass
    return out


async def _bootstrap_subservers() -> None:
    """Gateway model: the client launches only GM, so the sub-servers no longer
    auto-register via IPC. GM self-discovers the installed ones, fetches their real
    tools from the worker (F12) and registers them as MANAGED so `list_tools`
    re-publishes them. Best-effort; a sub-server that fails to answer is skipped
    (a later autoregister or a retry can still add it)."""
    for name in detect_subservers():
        if _registry.get_server(name):
            continue
        schemas = await _fetch_tool_schemas(name)
        if schemas:
            _registry.register_managed(name, list(schemas), schemas)


async def _sleep_monitor():
    """Background: if idle > IDLE_SLEEP_TIMEOUT, flag sleep.

    Sleep means servers are marked 'sleeping'. First client call wakes them.
    """
    global _is_sleeping
    while True:
        await asyncio.sleep(30)
        now = time.time()
        idle = now - _last_call_time

        if idle > IDLE_SLEEP_TIMEOUT and not _is_sleeping:
            _is_sleeping = True
            for s in _registry.all_servers():
                s.status = "sleeping"
            # Idle maintenance: let unused bridges (unconfirmed hypotheses) decay.
            try:
                from gray_matter.bridges import decay
                decay()
            except Exception:  # noqa: BLE001
                pass
        elif idle < IDLE_SLEEP_TIMEOUT and _is_sleeping:
            _is_sleeping = False


async def _reap_dead_workers():
    """A server marked dead means its CLIENT stopped heart-beating. We must NOT
    kill that pid — in the additive model it's the client's own process, not
    ours (the old code SIGTERM'd it, a real bug). What Gray-Matter actually owns
    is the persistent worker subprocess; drop it so the next call to that server
    respawns a fresh worker via `_worker_for`."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL * 2)
        for server in _registry.all_servers():
            if server.status != "dead":
                continue
            p = _workers.pop(server.name, None)
            if p is not None:
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass


def _build_stats() -> dict:
    """Live observability counters — the orchestrator's tachometer."""
    from gray_matter.bridges import all_bridges
    hits, misses = _stats["cache_hits"], _stats["cache_misses"]
    total = hits + misses
    return {
        "pulses": int(_stats["pulses"]),
        "cache_hits": int(hits),
        "cache_misses": int(misses),
        "cache_hit_rate": round(hits / total, 3) if total else 0.0,
        "cache_size": _ctx_cache.size(),
        "flashes": int(_stats["flashes"]),
        "bridges_added_session": int(_stats["bridges_added"]),
        "bridges_total": len(all_bridges()),
        "avg_miss_ms": round(_stats["pulse_ms_total"] / misses, 1) if misses else 0.0,
        "workers_alive": [n for n, p in _workers.items() if p.poll() is None],
        "worker_latency": {n: {"calls": v["calls"],
                               "avg_ms": round(v["ms_total"] / v["calls"], 1) if v["calls"] else 0.0,
                               "last_ms": v["last_ms"]}
                           for n, v in _worker_lat.items()},
    }


async def _build_doctor() -> dict:
    """Health snapshot: servers, workers, cache, bridges (+ vector tier NeuRAG)."""
    from gray_matter.bridges import all_bridges
    servers = [{
        "name": s.name, "status": s.status, "alive": s.is_alive(),
        "collaborative": s.collaborative,
        "worker": s.name in _workers and _workers[s.name].poll() is None,
    } for s in _registry.all_servers()]
    out = {
        "version": __version__,
        "sleeping": _is_sleeping,
        "servers": servers,
        "cache_size": _ctx_cache.size(),
        "bridges_total": len(all_bridges()),
    }
    # Degradato mai silenzioso (nota Claudio 2026-07-20): se NeuRAG gira sul
    # tier sqlite3 (niente pyturso → coseno in Python), il doctor deve dirlo.
    neurag = _registry.get_server("neurag")
    if neurag and neurag.is_alive():
        try:
            import json as _json
            raw = await _call_server_async("neurag", "knowledge_status", {})
            out["neurag_engine"] = _json.loads(raw).get("engine", "?")
        except Exception:  # noqa: BLE001 — best-effort, il doctor non deve rompersi
            pass
    # Doctor esteso (passo 5): tier di TUTTI e 3 + se il cross-store è attivo.
    # Env reale > .env GM (stessa precedenza del runtime); best-effort sempre.
    try:
        from gray_matter import bridges as _b, cloud as _cloud
        saved = _cloud.read_env_file(_cloud.default_env_file())

        def _has(key: str) -> bool:
            return bool(os.environ.get(key, "").strip() or saved.get(key))

        shared = _has("TURSO_AUTH_TOKEN")
        out["tiers"] = {
            "neuron": "Turso (cloud)" if _has("TURSO_DATABASE_URL") and shared
                      else "local",
            "neurag": out.get("neurag_engine")
                      or ("Turso (cloud)" if _has("NEURAG_TURSO_DATABASE_URL")
                          and (shared or _has("NEURAG_TURSO_AUTH_TOKEN")) else "local"),
            "gm_bridges": "Turso (cloud)" if _b.REMOTE_TURSO else "SQLite (local)",
        }
    except Exception:  # noqa: BLE001
        pass

    def _collab(name: str) -> bool:
        s = _registry.get_server(name)
        return bool(s and s.is_alive() and s.collaborative)

    # Cross-store = i bridge possono lavorare: entrambi gli store vivi e nel
    # pulse combinato (uno isolato/spento = niente collegamenti, per design).
    out["cross_store"] = _collab("neuron") and _collab("neurag")
    return out


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _first_concept(text: str) -> str:
    # ponytail: parse the top keyword out of forgotten's text output (fragile; a
    # structured return would be cleaner — deferred to the persistence refactor).
    for line in text.splitlines():
        s = line.strip()
        if not s or s.endswith(":") or s.startswith(("Total:", "No ")):
            continue
        return s.split()[0]
    return ""


async def _maybe_flash(topic: str):
    """Flash v1/v2 — returns (note, concept). `concept` is the dormant keyword
    surfaced (or ""), which pulse uses to auto-persist a cross-store bridge (v3b).
    Fires at a topic shift, mid-band `near` selection, rate-limited by a min gap +
    a per-session per-concept cooldown."""
    global _last_topic, _calls_since_flash
    _calls_since_flash += 1
    shifted = _norm(topic) != _norm(_last_topic)
    _last_topic = topic
    if not shifted or _calls_since_flash < FLASH_MIN_GAP:
        return "", ""

    neuron = _registry.get_server("neuron")
    if not neuron or not neuron.is_alive():
        return "", ""
    forgotten = (await _call_server_async("neuron", "forgotten", {"threshold": 5, "near": topic, "top_n": 1})).strip()
    if not forgotten or forgotten.startswith("["):   # skip empties / "[neuron] error: ..."
        return "", ""
    key = forgotten[:80]
    if key in _flashed:                              # per-concept cooldown
        return "", ""
    _flashed.add(key)
    _calls_since_flash = 0
    _stats["flashes"] += 1
    return f"⚡ Flashback: {forgotten}", _first_concept(forgotten)


# ---------------------------------------------------------------------------
# IPC listener (background) — receives registrations, heartbeats
# ---------------------------------------------------------------------------

async def _recv_exact_async(loop, conn, n: int) -> "bytes | None":
    """Read exactly n bytes from a non-blocking socket, or None on short read.

    Suffisso `_async` non decorativo: si chiamava `_recv_exact` come l'omonima
    sincrona di cli.py e la copriva silenziosamente a livello di modulo."""
    buf = b""
    while len(buf) < n:
        try:
            chunk = await loop.sock_recv(conn, n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


async def _recv_message(loop, conn) -> bytes:
    """One length-prefixed message: 4-byte big-endian length, then exactly that
    many bytes. Returns the payload (b'' on short read / bad frame). This is the
    fix for the old `data[4:]` single-recv assumption that broke on any message
    split across TCP segments."""
    header = await _recv_exact_async(loop, conn, 4)
    if header is None:
        return b""
    (length,) = struct.unpack("!I", header)
    if length <= 0 or length > 1_000_000:      # sanity guard vs junk/oversize
        return b""
    payload = await _recv_exact_async(loop, conn, length)
    return payload or b""


async def _ipc_listener(*, exit_on_busy: bool = True):
    """Background task: listens for incoming IPC connections (registrations, heartbeats).

    exit_on_busy: a daemon that finds :9876 taken is a duplicate and must die
    (SystemExit escapes asyncio). A stdio instance (main) must instead keep
    serving MCP without a listener — its managed workers don't need the port."""
    loop = asyncio.get_running_loop()
    # Singleton PRESERVATO ma porta DINAMICA: se su una porta candidata risponde
    # GIÀ un GM (probe `ping`), siamo un duplicato e moriamo. Se la porta è presa
    # da un processo ESTRANEO, si scala alla prima libera invece di non partire
    # mai. La porta scelta va nel rendezvous file, così i client la seguono.
    if gm_answers(GRAY_MATTER_HOST, resolve_port()):
        if exit_on_busy:
            raise SystemExit(0)   # un GM è già vivo: duplicato → muori
        return                    # istanza stdio: serve MCP senza listener
    server_sock = None
    chosen = None
    for port in range(GRAY_MATTER_PORT, GRAY_MATTER_PORT + GRAY_MATTER_PORT_SPAN):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((GRAY_MATTER_HOST, port))
        except OSError:
            s.close()
            # occupata: se è un GM è un duplicato (muori), altrimenti prova la prossima
            if gm_answers(GRAY_MATTER_HOST, port):
                if exit_on_busy:
                    raise SystemExit(0)
                return
            if not exit_on_busy:
                # stdio mode: non cercare un'altra porta — salta l'ascolto IPC
                return
            continue
        server_sock, chosen = s, port
        break
    if server_sock is None:
        # nessuna porta libera nell'intervallo: non possiamo servire l'IPC
        if exit_on_busy:
            raise SystemExit(1)
        return
    write_port_file(chosen)       # i client leggono qui la porta reale
    if chosen != GRAY_MATTER_PORT:
        print(f"gray-matter: porta preferita {GRAY_MATTER_PORT} occupata → uso {chosen}",
              file=sys.stderr)
    server_sock.listen(5)
    server_sock.setblocking(False)

    while True:
        try:
            conn, addr = await loop.sock_accept(server_sock)
            conn.setblocking(False)
            data = await _recv_message(loop, conn)
            if data:
                try:
                    msg = json.loads(data.decode("utf-8"))
                    action = msg.get("action")
                    response = {}

                    if action == "ping":
                        # Probe di identità: distingue un GM da un'app estranea
                        # sulla stessa porta (usato dal singleton + rendezvous).
                        response = {"status": "ok", "gm": True}
                    elif action == "register":
                        _registry.register(
                            name=msg["name"],
                            tool_names=msg["tool_names"],
                            socket_path=msg["socket_path"],
                            pid=msg["pid"],
                        )
                        response = {"status": "ok", "message": f"Registered {msg['name']}"}
                    elif action == "heartbeat":
                        ok = _registry.heartbeat(msg["name"])
                        response = {"status": "ok" if ok else "unknown"}
                    elif action == "unregister":
                        _registry.unregister(msg["name"])
                        response = {"status": "ok"}
                    elif action == "isolate":
                        ok = _registry.set_collaborative(msg["name"], False)
                        response = {"status": "ok" if ok else "unknown"}
                    elif action == "collaborate":
                        ok = _registry.set_collaborative(msg["name"], True)
                        response = {"status": "ok" if ok else "unknown"}
                    elif action == "mode":
                        want = msg.get("mode") == "collaborate"
                        for s in _registry.all_servers():
                            s.collaborative = want
                        response = {"status": "ok"}
                    elif action == "status":
                        response = _registry.to_dict()
                    elif action == "stats":
                        response = _build_stats()
                    elif action == "doctor":
                        response = await _build_doctor()
                    elif action == "knowledge_cmd":
                        tool_name = msg.get("tool", "knowledge_status")
                        tool_args = msg.get("args", {})
                        try:
                            result = await _call_server_async("neurag", tool_name, tool_args)
                            response = {"result": result}
                        except Exception as e:
                            response = {"error": str(e)}
                    elif action == "gm-neuron":
                        tool_name = msg.get("tool")
                        tool_args = msg.get("args", {})
                        if not tool_name:
                            response = {"error": "Missing 'tool' parameter"}
                        else:
                            try:
                                result = await _call_server_async("neuron", tool_name, tool_args)
                                response = {"result": result}
                            except Exception as e:
                                response = {"error": str(e)}
                    elif action == "gm-neurag":
                        tool_name = msg.get("tool")
                        tool_args = msg.get("args", {})
                        if not tool_name:
                            response = {"error": "Missing 'tool' parameter"}
                        else:
                            try:
                                result = await _call_server_async("neurag", tool_name, tool_args)
                                response = {"result": result}
                            except Exception as e:
                                response = {"error": str(e)}
                    elif action == "shutdown":
                        response = {"status": "ok"}
                        # Graceful shutdown
                        conn.sendall(struct.pack("!I", len(json.dumps(response).encode("utf-8"))) + json.dumps(response).encode("utf-8"))
                        conn.close()
                        server_sock.close()
                        os._exit(0)
                    else:
                        response = {"error": f"Unknown action: {action}"}

                    resp = json.dumps(response).encode("utf-8")
                    await loop.sock_sendall(conn, struct.pack("!I", len(resp)) + resp)
                except (json.JSONDecodeError, KeyError) as e:
                    pass
            conn.close()
        except OSError:
            await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Heartbeat monitor (background) — marks dead servers
# ---------------------------------------------------------------------------

async def _heartbeat_monitor():
    """Background task: check heartbeats, mark dead servers."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        now = time.time()
        for server in _registry.all_servers():
            if server.managed:
                continue   # worker-backed: liveness is the process, not a heartbeat
            if server.status == "alive" and (now - server.last_heartbeat) > HEARTBEAT_TIMEOUT:
                server.status = "dead"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _init_options() -> InitializationOptions:
    """Handshake metadata for stdio mode. `capabilities` is a REQUIRED pydantic
    field — omitting it (as the old inline construction did) raises at the very
    first stdio startup, which daemon-only runs never exercised."""
    from mcp.server.lowlevel import NotificationOptions
    return InitializationOptions(
        server_name="gray-matter",
        server_version=__version__,
        capabilities=app.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
        instructions=GM_INSTRUCTIONS,
    )


def main() -> None:
    """Run Gray-Matter as a stdio MCP server with background IPC listener."""
    _record_self("stdio")
    async def _run():
        # Start background tasks
        ipc_task = asyncio.create_task(_ipc_listener(exit_on_busy=False))
        hb_task = asyncio.create_task(_heartbeat_monitor())
        sleep_task = asyncio.create_task(_sleep_monitor())
        reap_task = asyncio.create_task(_reap_dead_workers())
        prewarm_task = asyncio.create_task(_prewarm_workers())

        # Gateway model: self-discover installed sub-servers as managed workers
        # (they no longer autoregister when the client launches only GM).
        await _bootstrap_subservers()

        # Start stdio MCP server
        from mcp.server.stdio import stdio_server
        async with stdio_server() as (read_stream, write_stream):
            await app.run(
                read_stream,
                write_stream,
                _init_options(),
            )

        # Cleanup
        ipc_task.cancel()
        hb_task.cancel()
        sleep_task.cancel()
        reap_task.cancel()
        prewarm_task.cancel()

    asyncio.run(_run())


def auto_register_and_run(name: str, tool_names: list[str]) -> None:
    """Called by a server (Neuron, NeuRAG) on startup.

    Tries to register with existing Gray-Matter.
    If Gray-Matter is not running, spawns one first,
    then runs the server's own MCP main loop.
    """
    autoregister(name, tool_names)

    # Start heartbeat in background
    import threading
    def _heartbeat_loop():
        while True:
            time.sleep(HEARTBEAT_INTERVAL)
            _send_heartbeat(name)
    t = threading.Thread(target=_heartbeat_loop, daemon=True)
    t.start()


def _record_self(role: str) -> None:
    """Iscrive questo processo al registro dei PID (INSTALLER-UX §7).

    Best-effort e mai bloccante: senza registro la suite funziona lo stesso,
    è `doctor` che smette di poter dire "questi due sono rimasti indietro".
    """
    try:
        from gray_matter import pids as _pids
        _pids.record_self(role)
    except Exception:  # noqa: BLE001
        pass


def run_daemon() -> None:
    """Registry/orchestrator only: IPC listener (:9876) + monitors, NO stdio MCP.
    This is how Gray-Matter runs when started as a background daemon (autoregister
    or `gray-matter start`) — there's no MCP client to attach stdio to, so main()'s
    stdio_server() would just exit on a detached process."""
    _record_self("daemon")

    async def _run():
        # Stessa self-discovery di main(): era cablata SOLO nel ramo stdio, così
        # un daemon avviato con `gray-matter start` (o spawnato da autoregister)
        # restava con il registro vuoto — `status` diceva "Servers: 0" e ogni
        # gm-neuron/gm-neurag moriva con "worker gave no response". I due rami
        # devono partire dallo stesso stato: è lo stesso gateway.
        #
        # In BACKGROUND, non awaited prima del listener: il bootstrap interroga
        # i worker (spawn del subprocess + caricamento del modello) e può durare
        # decine di secondi. Awaitarlo qui teneva la porta IPC chiusa per tutto
        # quel tempo: `gray-matter start` diceva "started" e un `doctor` subito
        # dopo rispondeva "not running" con connessione rifiutata. main() fa lo
        # stesso: crea il task del listener PRIMA di aspettare il bootstrap.
        boot = asyncio.create_task(_bootstrap_subservers())
        boot.add_done_callback(lambda t: t.cancelled() or t.exception())
        await asyncio.gather(
            _ipc_listener(),
            _heartbeat_monitor(),
            _sleep_monitor(),
            _reap_dead_workers(),
        )
    asyncio.run(_run())


if __name__ == "__main__":
    import sys
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        main()
