"""Il loop di memoria come hook di Claude Code (ADR-014, mock).

    python -I <percorso>/memhook.py recall   # UserPromptSubmit: contesto prima della risposta
    python -I <percorso>/memhook.py save     # Stop: cosa registrerebbe a fine turno (dry-run)

`-I` e il percorso del file, non `-m`: `-m` mette la cartella corrente in testa a
`sys.path`, e dalla radice del repo importerebbe il sorgente invece del venv.

Parla solo col daemon, via lo stesso IPC autenticato di CLI e GUI. `recall` e' UNA
richiesta: il daemon compone contesto, puntatore KB e flash con le funzioni del
gateway (`server._hook_recall`), gia' caldo. Daemon assente, timeout o qualunque
errore: l'hook esce senza scrivere niente. Un ricordo mancato costa meno di un
messaggio bloccato.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

TIMEOUT = 2.5            # secondi per la richiesta IPC
BUDGET = 1200            # caratteri iniettati, ~300 token
MIN_CHARS = 12
ACKS = {"ok", "si", "sì", "no", "grazie", "va bene", "perfetto", "fallo", "vai", "procedi"}


def _ipc(msg: dict) -> str:
    from gray_matter.cli import FAST_CONNECT, _send_ipc
    # Daemon spento = niente ricordo, in 0,5 s invece dei ~2 s di Windows.
    r = _send_ipc(msg, TIMEOUT, connect_timeout=FAST_CONNECT)
    return "" if not isinstance(r, dict) or "error" in r else str(r.get("result") or "")


def _call(server: str, tool: str, args: dict) -> str:
    return _ipc({"action": "call", "server": server, "tool": tool, "args": args})


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


def fit(text: str) -> str:
    text = text.strip()
    return text if len(text) <= BUDGET else text[:BUDGET - 1] + "…"


def recall(payload: dict) -> str:
    prompt = str(payload.get("prompt") or "")
    if not worth_recalling(prompt):
        return ""
    # Nessun ping prima: senza daemon la connessione e' rifiutata subito, e _ipc da' ''.
    return fit(_ipc({"action": "recall", "prompt": prompt[:300],
                     "session": str(payload.get("session_id") or "")}))


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
    topic, kws = _keywords(prompt[:600])
    if not topic and not kws:                   # daemon assente o estrazione vuota
        return ""
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
