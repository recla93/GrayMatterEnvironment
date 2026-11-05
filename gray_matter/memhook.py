"""Il loop di memoria come hook di Claude Code (ADR-014, mock).

    python -I <percorso>/memhook.py recall   # UserPromptSubmit: contesto prima della risposta
    python -I <percorso>/memhook.py save     # Stop: cosa registrerebbe a fine turno (dry-run)

`-I` e il percorso del file, non `-m`: `-m` mette la cartella corrente in testa a
`sys.path`, e dalla radice del repo importerebbe il sorgente invece del venv.

Parla solo col daemon, via lo stesso IPC autenticato di CLI e GUI. Daemon assente,
timeout o qualunque errore: l'hook esce senza scrivere niente. Un ricordo mancato
costa meno di un messaggio bloccato.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TIMEOUT = 2.5            # secondi per chiamata IPC
BUDGET = 1200            # caratteri iniettati, ~300 token
MIN_CHARS = 12
KB_MIN_COS = 0.55        # ponytail: soglia stimata, da tarare sul log del dry-run
ACKS = {"ok", "si", "sì", "no", "grazie", "va bene", "perfetto", "fallo", "vai", "procedi"}


def _call(server: str, tool: str, args: dict) -> str:
    from gray_matter.cli import _send_ipc
    r = _send_ipc({"action": "call", "server": server, "tool": tool, "args": args}, TIMEOUT)
    return "" if not isinstance(r, dict) or "error" in r else str(r.get("result") or "")


def worth_recalling(prompt: str) -> bool:
    p = prompt.strip()
    if len(p) < MIN_CHARS or p.startswith("/"):
        return False
    return p.lower().strip(" .!?") not in ACKS


def _keywords(prompt: str) -> tuple[str, list]:
    try:
        d = json.loads(_call("neuron", "extract", {"text": prompt}) or "{}")
    except ValueError:
        return "", []
    return str(d.get("topic", "")), list(d.get("keywords", []))[:5]


def flash_concept(forgotten: str) -> str:
    """Il primo concetto dell'uscita di `forgotten`, o ''."""
    lines = [ln for ln in forgotten.splitlines()[1:] if ln.startswith("  ")]
    return lines[0].split()[0] if lines else ""


def kb_pointer(kq: str) -> str:
    m = re.search(r"\[1\]\s+(.+?)\s+\(cos ([0-9.]+)\)", kq)
    if not m or float(m.group(2)) < KB_MIN_COS:
        return ""
    return f"📚 La KB ha materiale: {m.group(1)} (cos {m.group(2)}) → knowledge_query per il dettaglio"


def _seen_file(session: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", session)[:64] or "nosession"
    return Path(tempfile.gettempdir()) / f"gm-memhook-{safe}.json"


def _take_new(session: str, concept: str) -> bool:
    """True la prima volta che `concept` emerge in questa sessione."""
    f = _seen_file(session)
    try:
        seen = set(json.loads(f.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    if concept in seen:
        return False
    seen.add(concept)
    try:
        f.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except OSError:
        pass
    return True


def compose(context: str, concept: str, pointer: str) -> str:
    parts = [context.strip()] if context.strip() else []
    if concept and concept not in context:
        parts.append(f"⚡ Ne avevate già parlato: {concept} → recall o get_context se serve")
    if pointer:
        parts.append(pointer)
    out = "\n".join(parts)
    return out if len(out) <= BUDGET else out[:BUDGET - 1] + "…"


def recall(payload: dict) -> str:
    prompt = str(payload.get("prompt") or "")
    if not worth_recalling(prompt):
        return ""
    from gray_matter.cli import GRAY_MATTER_HOST, gm_answers, resolve_port
    if not gm_answers(GRAY_MATTER_HOST, resolve_port()):
        return ""
    q = prompt[:300]
    topic, kws = _keywords(q)
    with ThreadPoolExecutor(3) as ex:
        ctx = ex.submit(_call, "neuron", "pre_turn", {"topic": topic or q[:120], "keywords": kws})
        fg = ex.submit(_call, "neuron", "forgotten", {"threshold": 5, "near": q, "top_n": 1})
        kb = ex.submit(_call, "neurag", "knowledge_query", {"query": q, "top_n": 1})
        context, forgotten, kq = ctx.result(), fg.result(), kb.result()
    concept = flash_concept(forgotten)
    if concept and not _take_new(str(payload.get("session_id") or ""), concept):
        concept = ""
    return compose(context, concept, kb_pointer(kq))


# --- save (dry-run) ----------------------------------------------------------

def _entries(transcript: str) -> list:
    try:
        lines = Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _blocks(e: dict) -> list:
    c = (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _is_user_turn(e: dict) -> bool:
    if e.get("type") != "user" or e.get("isSidechain") or e.get("isMeta"):
        return False
    return not any(b.get("type") == "tool_result" for b in _blocks(e))


def last_turn(entries: list) -> tuple[str, bool]:
    """(testo dell'ultimo messaggio vero dell'utente, store_turn chiamato dopo?)"""
    prompt, saved = "", False
    for e in entries:
        if _is_user_turn(e):
            c = (e.get("message") or {}).get("content")
            prompt = c if isinstance(c, str) else " ".join(
                b.get("text", "") for b in _blocks(e) if b.get("type") == "text")
            saved = False
        elif any(b.get("type") == "tool_use" and str(b.get("name", "")).endswith("store_turn")
                 for b in _blocks(e)):
            saved = True
    return prompt, saved


def existing(keywords: list) -> list:
    """Le parole che sono già nomi di nodi: le altre non diventano concetti."""
    if not keywords:
        return []
    out = _call("neuron", "find_candidates", {"keywords": keywords, "top_n": 20})
    names = {ln.split()[0] for ln in out.splitlines() if "sim=" in ln}
    return [k for k in keywords if k in names]


def save(payload: dict) -> str:
    prompt, saved = last_turn(_entries(str(payload.get("transcript_path") or "")))
    if saved or not worth_recalling(prompt):
        return ""
    from gray_matter.cli import GRAY_MATTER_HOST, gm_answers, resolve_port
    if not gm_answers(GRAY_MATTER_HOST, resolve_port()):
        return ""
    topic, kws = _keywords(prompt[:600])
    keep = existing(kws)
    from gray_matter.paths import logs_dir
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "session": payload.get("session_id"),
           "topic": topic, "extracted": kws, "would_store": keep, "prompt": prompt[:200]}
    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
        with open(logs_dir() / "memhook-save.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return ""                                   # dry-run: niente nel contesto


def main(argv: list) -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
        mode = argv[1] if len(argv) > 1 else ""
        if not isinstance(payload, dict) or mode not in ("recall", "save"):
            return
        text = recall(payload) if mode == "recall" else save(payload)
    except Exception:  # noqa: BLE001 — un hook non rompe mai il messaggio dell'utente
        return
    if text:
        out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                      "additionalContext": text}}
        sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main(sys.argv)
