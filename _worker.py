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


def main() -> None:
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
            now = time.monotonic()
            if (reg is not None and hasattr(reg, "_graphs")
                    and now - last_clear >= _FRESH_TTL):
                try:
                    reg._graphs.clear()          # freshness: re-read DB, keep model warm
                    last_clear = now
                except Exception:
                    pass
            _t0 = time.monotonic()
            handler = app.request_handlers[_mcp_types.CallToolRequest]
            mcp_req = _mcp_types.CallToolRequest(
                params=_mcp_types.CallToolRequestParams(
                    name=req["tool"], arguments=req.get("args", {})
                )
            )
            resp = loop.run_until_complete(handler(mcp_req))
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
        sys.stdout.flush()


if __name__ == "__main__":
    main()
