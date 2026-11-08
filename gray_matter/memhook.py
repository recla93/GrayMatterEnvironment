"""Il loop di memoria come hook di Claude Code (ADR-014, mock).

    python -I <percorso>/memhook.py recall   # UserPromptSubmit: contesto prima della risposta
    python -I <percorso>/memhook.py save     # Stop: il turno ha salvato i suoi fatti? (ADR-015)

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


def worth_recalling(prompt: str) -> bool:
    p = prompt.strip()
    if len(p) < MIN_CHARS or p.startswith("/"):
        return False
    return p.lower().strip(" .!?") not in ACKS


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


# --- save: il turno ha lasciato i suoi fatti? (ADR-015 fase 3) ---------------
#
# Il fatto lo scrive il modello; l'hook controlla che ci sia. Non estrae niente
# dal messaggio: la versione di prova (ADR-014 D4) teneva solo le parole gia'
# nodi, e 4 messaggi su 5 non avrebbero salvato niente. Legge solo il
# transcript, quindi funziona anche a daemon spento.

SUBSTANTIVE_CHARS = 600   # una risposta piu' lunga di cosi' e' un turno di sostanza
REMIND = ("[memoria] Questo turno non ha salvato nessun fatto. Se c'e' qualcosa da non "
          "dover ripetere (avanzamenti, decisioni, fix, dettagli, idee, l'utente e le sue "
          "abitudini), chiama store_turn(facts=[{kind, text, concepts}]) e poi chiudi. "
          "Se non c'e' niente, chiudi senza aggiungere altro.")


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


def _is_memory_tool(name: str) -> bool:
    return "gray-matter" in name or "neuron" in name.lower()


def _wrote_fact(b: dict) -> bool:
    """A store_turn that carries a fact: `facts` with an entry, or the legacy
    `episode`. One with only keywords saves words, which is what ADR-015 ends."""
    if b.get("type") != "tool_use" or not str(b.get("name", "")).endswith("store_turn"):
        return False
    a = b.get("input") if isinstance(b.get("input"), dict) else {}
    return bool(a.get("facts")) or bool(str(a.get("episode") or "").strip())


def last_turn(entries: list) -> tuple[str, bool, int, int]:
    """For the last real user message: (its text, a fact was saved after it,
    tool calls that did work — memory tools excluded —, characters answered)."""
    prompt, wrote, work, chars = "", False, 0, 0
    for e in entries:
        if _is_user_turn(e):
            c = (e.get("message") or {}).get("content")
            prompt = c if isinstance(c, str) else " ".join(
                b.get("text", "") for b in _blocks(e) if b.get("type") == "text")
            wrote, work, chars = False, 0, 0
            continue
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if _wrote_fact(b):
                wrote = True
            elif b.get("type") == "tool_use" and not _is_memory_tool(str(b.get("name", ""))):
                work += 1
            elif b.get("type") == "text":
                chars += len(str(b.get("text") or ""))
    return prompt, wrote, work, chars


def save(payload: dict) -> str:
    """The reason to send the model back to work once, or "" to let it stop.
    Only for a real message (not an ack or a command) whose turn did work or
    answered at length, and only the first time: `stop_hook_active` means this
    Stop already follows our own block, and a second one would loop."""
    if payload.get("stop_hook_active"):
        return ""
    prompt, wrote, work, chars = last_turn(_entries(str(payload.get("transcript_path") or "")))
    if wrote or not worth_recalling(prompt):
        return ""
    if work == 0 and chars < SUBSTANTIVE_CHARS:
        return ""
    return REMIND


def main(argv: list) -> None:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
        mode = argv[1] if len(argv) > 1 else ""
        if not isinstance(payload, dict) or mode not in ("recall", "save"):
            return
        text = recall(payload) if mode == "recall" else save(payload)
    except Exception:  # noqa: BLE001 — un hook non rompe mai il messaggio dell'utente
        return
    if not text:
        return
    out = ({"decision": "block", "reason": text} if mode == "save" else
           {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": text}})
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main(sys.argv)
