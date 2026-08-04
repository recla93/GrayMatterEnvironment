"""Persistent tool-call worker for ONE server module (neuron.server / neurag.server).

Imports the module ONCE — so Neuron's fastembed model loads once — then serves tool
calls over stdin/stdout as JSON lines. This is what makes Gray-Matter's pulse fast:
no cold-import (and no model reload) per call.

Freshness: for a graph-backed server (Neuron) the in-memory graph cache is cleared
before each call, so reads re-hit the DB and stay current while the expensive model
stays warm. NeuRAG queries hit SQL live, so nothing to clear there.

Protocol: one JSON request per line on stdin -> one JSON response per line on stdout.
    {"tool": "get_context", "args": {...}}  ->  {"ok": true, "text": "..."}
"""
import asyncio
import importlib
import json
import os
import sys
import time

from mcp import types as _mcp_types

# Freshness TTL: prima il graph cache veniva svuotato a OGNI chiamata, cioè
# grafo interamente riletto dal DB per ogni tool call — con pulse che ne fa
# 2-3 per turno, e sul tier Turso cloud ogni rilettura passa dalla rete, era
# QUESTO il collo dei 2-3s, non il calcolo dell'embedding (il modello è già
# caldo qui). Ora si rilegge al massimo ogni TTL secondi: dentro lo stesso
# turno il grafo resta in memoria. 0 = comportamento vecchio (clear sempre).
_FRESH_TTL = float(os.environ.get("GM_WORKER_FRESH_TTL", "5"))

# Checkpoint periodico (fix B): ogni N mutazioni il grafo viene salvato su
# disco, cosi' anche un kill sporco del processo (niente shutdown via pipe)
# perde al massimo l'ultimo intervallo, non l'intera sessione. 0 = off.
_CHECKPOINT_EVERY = int(os.environ.get("GM_WORKER_CHECKPOINT", "8"))
_MUTATING = {"store_turn", "auto", "consolidate", "prune", "merge", "dedup",
             "confirm", "dismiss"}
_mutations = 0


def main() -> None:
    # Il worker tiene aperto lo store: se resta indietro quando il daemon muore,
    # è un writer di troppo sullo stesso DB. Si registra da solo perché il PID
    # che vede lo spawner è quello del redirector del venv, non il suo.
    try:
        from gray_matter import pids as _pids
        _pids.record_self(f"worker:{sys.argv[1].split('.')[0]}")
    except Exception:  # noqa: BLE001 — il registro non deve mai bloccare il worker
        pass
    mod = importlib.import_module(sys.argv[1])   # e.g. "neuron.server"
    app = mod.app
    reg = getattr(mod, "_g", None)               # graph registry (Neuron); NeuRAG has none
    loop = asyncio.new_event_loop()
    last_clear = 0.0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            # F12: schema introspection. Return this server's real tool list
            # (name + description + inputSchema) so Gray-Matter can re-publish
            # accurate pass-through schemas instead of empty ones.
            if req.get("op") == "list_tools":
                lt = app.request_handlers[_mcp_types.ListToolsRequest]
                lresp = loop.run_until_complete(lt(_mcp_types.ListToolsRequest(method="tools/list")))
                lres = lresp.root if hasattr(lresp, "root") else lresp
                tools = [{"name": t.name, "description": t.description,
                          "inputSchema": t.inputSchema} for t in lres.tools]
                sys.stdout.write(json.dumps({"ok": True, "tools": tools}) + "\n")
                sys.stdout.flush()
                continue
            if req.get("op") == "shutdown":
                # Flush sincrono prima di morire: il gateway attende la fine.
                # Su Windows non esistono segnali (Popen.terminate() = kill duro),
                # questa pipe è l'unico modo per un checkpoint finale pulito.
                if reg is not None:
                    try:
                        reg.save_all()
                    except Exception:  # noqa: BLE001 — mai bloccare l'exit
                        pass
                sys.exit(0)
            # ponytail: removed reg._graphs.clear() — it caused L2 race condition
            # (multiple workers clearing + reloading the same DB simultaneously).
            # The Graph reads from SQLite on every query; no in-memory cache to stale.
            _t0 = time.monotonic()
            handler = app.request_handlers[_mcp_types.CallToolRequest]
            mcp_req = _mcp_types.CallToolRequest(
                params=_mcp_types.CallToolRequestParams(
                    name=req["tool"], arguments=req.get("args", {})
                )
            )
            resp = loop.run_until_complete(handler(mcp_req))
            # Checkpoint periodico: le mutazioni vengono flushato su disco
            # ogni _CHECKPOINT_EVERY, indipendentemente dallo shutdown pulito.
            global _mutations
            if reg is not None and req["tool"] in _MUTATING and _CHECKPOINT_EVERY > 0:
                _mutations += 1
                if _mutations >= _CHECKPOINT_EVERY:
                    try:
                        reg.save_all()
                    except Exception:  # noqa: BLE001 — mai rompere il turno
                        pass
                    _mutations = 0
            result = resp.root if hasattr(resp, "root") else resp
            text = ""
            if hasattr(result, "content") and result.content:
                text = result.content[0].text if hasattr(result.content[0], "text") else str(result.content[0])
            sys.stdout.write(json.dumps({
                "ok": True, "text": text,
                "ms": round((time.monotonic() - _t0) * 1000, 1)}) + "\n")
        except Exception as e:  # noqa: BLE001
            import traceback
            sys.stdout.write(json.dumps({"ok": False, "error": str(e),
                                         "trace": traceback.format_exc()}) + "\n")
        try:
            sys.stdout.flush()
        except OSError:
            # The parent went away mid-answer and the pipe is gone: nobody is
            # left to read this line. Was a noisy `OSError: [Errno 22]` at every
            # gateway shutdown, and now that the workers are long-lived and
            # shared it would fire on every daemon restart. Nothing to do but
            # stop — the next request cannot arrive either.
            break


if __name__ == "__main__":
    main()
