"""Grafizzazione automatica: cartelle → nodi, file → chunk, poi link.

Prima questa pipeline la faceva il MODELLO: `knowledge_index` restituiva i
chunk nel contesto LLM e il modello li ri-passava a `knowledge_add_node` /
`knowledge_add_chunks` — ogni chunk viaggiava due volte attraverso il contesto.
Qui invece è tutto server-side, in un colpo solo:

    scan → nodi dalla struttura cartelle → chunk → embedding → rebuild link

Regola di mappatura (auto, zero configurazione):
  * la radice diventa (o riusa) il godnode;
  * le cartelle di primo livello → fundamental;
  * le sottocartelle → specialization, figlie del nodo della cartella madre;
  * i file finiscono nel nodo della cartella che li contiene (quelli nella
    radice, nel godnode).
Cartelle nascoste/di build sono ignorate. I nodi possono poi essere
modificati dalla GUI o da CLI (`rename-node`, `remove-node`, `add-node`).

Due modi d'uso:
  * sincrono (:func:`auto_ingest`) — la CLI `neurag ingest` lo usa e la GUI
    ne streama il progresso riga per riga;
  * job in background (:func:`start_job`) — il tool MCP `knowledge_ingest`
    parte e risponde subito con un id; lo stato si legge con
    `knowledge_ingest_status`. Il thread apre una PROPRIA connessione al DB
    (sqlite non ama le connessioni condivise tra thread).
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from neurag.chunker import _SUPPORTED_EXTENSIONS

# Cartelle che non sono conoscenza: build, cache, VCS, ambienti.
# (Le cartelle che iniziano con "." sono già escluse da _skippable.)
#
# `cache` / `graphify-out` aggiunti dopo una misura su un albero reale: le
# cache di tool contengono JSON generati — indici di path, non conoscenza — e
# avvelenano tutto a valle. Ingerendo `neurag/` producevano migliaia di chunk
# in cui OGNI path del progetto compare come token, quindi ogni nome di nodo
# sembrava "menzionato" ovunque: il nodo `cache` risultava collegato a sei
# nodi con peso 1.0. Costo aggiuntivo: embedding e ricerca su testo che nessuno
# vorrà mai recuperare.
_SKIP_DIRS = {"__pycache__", "node_modules", "venv", ".venv", "build", "dist",
              "site-packages", "egg-info", "cache", "graphify-out",
              "htmlcov", "coverage"}


def _skippable(rel_parts: tuple) -> bool:
    return any(p.startswith(".") or p in _SKIP_DIRS or p.endswith(".egg-info")
               for p in rel_parts)


def auto_ingest(kg, root, godnode: "str | None" = None, say=None) -> dict:
    """Grafizza `root` dentro `kg`. Ritorna il report; `say(riga)` per il progresso."""
    say = say or (lambda s: None)
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"non è una cartella: {root}")

    report = {"godnode": "", "nodes": 0, "files": 0, "chunks": 0,
              "links": {}, "skipped": []}

    god = (godnode or root.name).strip()
    gn = kg.get_node_by_name(god)
    if gn is None:
        kg.add_node(name=god, node_type="godnode")
        gn = kg.get_node_by_name(god)
        report["nodes"] += 1
    report["godnode"] = god
    say(f"[godnode] {god}")

    # Cartelle → nodi, genitori prima dei figli (rglob ordinato = prefisso prima).
    node_for = {root: gn["id"]}
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        rel = d.relative_to(root).parts
        if _skippable(rel):
            continue
        parent_id = node_for.get(d.parent)
        if parent_id is None:               # dentro una cartella saltata
            continue
        ntype = "fundamental" if d.parent == root else "specialization"
        name = d.name
        existing = kg.get_node_by_name(name)
        if existing is not None and existing["parent_id"] != parent_id:
            # Omonimo sotto un altro ramo: disambigua col nome della madre.
            name = f"{d.parent.name} · {d.name}"
            existing = kg.get_node_by_name(name)
        if existing is not None:
            node_for[d] = existing["id"]    # riusa: l'ingest è ri-lanciabile
            continue
        node_for[d] = kg.add_node(name=name, node_type=ntype, parent_id=parent_id)
        report["nodes"] += 1
        say(f"[nodo] {'/'.join(rel)}  ({ntype})")

    # File → chunk nel nodo della propria cartella.
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        if f.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue
        if _skippable(f.relative_to(root).parts[:-1]):
            continue
        nid = node_for.get(f.parent)
        if nid is None:
            continue
        try:
            n = kg.index_into_node(f, nid)
        except Exception as exc:  # noqa: BLE001 — un file rotto non ferma il resto
            report["skipped"].append(f"{f.relative_to(root)}: {exc}")
            say(f"[!] saltato {f.relative_to(root)}: {exc}")
            continue
        report["files"] += 1
        report["chunks"] += n
        say(f"  {f.relative_to(root)} -> {n} chunk")

    say("[link] ricostruzione dei collegamenti…")
    report["links"] = kg.rebuild_links()
    say(f"[ok] nodi +{report['nodes']}, file {report['files']}, "
        f"chunk {report['chunks']}, saltati {len(report['skipped'])}")
    return report


# --------------------------------------------------------------------------
# Job in background (per il tool MCP: il worker resta caldo, il modello no-wait)
# --------------------------------------------------------------------------
JOBS: "dict[str, dict]" = {}
_MAX_JOBS = 20      # memoria dei job recenti; i più vecchi decadono


def start_job(root, godnode: "str | None" = None) -> dict:
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "root": str(root), "state": "running", "log": [],
           "report": None, "error": "", "t0": time.time(), "ms": None}
    while len(JOBS) >= _MAX_JOBS:
        JOBS.pop(next(iter(JOBS)))
    JOBS[jid] = job

    def _run() -> None:
        from neurag.db import KnowledgeGraph
        kg = None
        try:
            kg = KnowledgeGraph()           # connessione propria del thread
            job["report"] = auto_ingest(kg, root, godnode,
                                        say=lambda s: job["log"].append(s))
            job["state"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["state"] = "error"
            job["error"] = str(exc)
        finally:
            job["ms"] = round((time.time() - job["t0"]) * 1000)
            try:
                if kg is not None:
                    kg.close()
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_run, daemon=True).start()
    return job


def job_text(job: dict, tail: int = 12) -> str:
    """Riassunto leggibile di un job (per il tool di status)."""
    head = f"[{job['id']}] {job['state']}  root={job['root']}"
    if job["ms"] is not None:
        head += f"  ({job['ms']} ms)"
    lines = [head] + [f"  {l}" for l in job["log"][-tail:]]
    if job["state"] == "error":
        lines.append(f"  errore: {job['error']}")
    if job["state"] == "done" and job["report"]:
        r = job["report"]
        lines.append(f"  totale: nodi +{r['nodes']}, file {r['files']}, "
                     f"chunk {r['chunks']}, saltati {len(r['skipped'])}")
    return "\n".join(lines)
