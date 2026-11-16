"""The memory loop as a Claude Code hook (ADR-014, mock).

    python -I <path>/memhook.py recall   # UserPromptSubmit: context before the answer
    python -I <path>/memhook.py save     # Stop: did the turn save its facts? (ADR-015)

`-I` and the file path, not `-m`: `-m` puts the current folder first on
`sys.path`, and from the repo root it would import the source instead of the venv.

Talks only to the daemon, over the same authenticated IPC as the CLI and GUI.
`recall` is ONE request: the daemon builds context, KB pointer and flash with the
gateway's functions (`server._hook_recall`), already warm. No daemon, a timeout
or any error: the hook exits without writing anything. A missed recall costs less
than a blocked message.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TIMEOUT = 2.5            # seconds for the IPC request
BUDGET = 1200            # injected characters, ~300 tokens
PROFILE_BUDGET = 1000    # on top, once per session: user/habit facts (= Neuron's cap)
MIN_CHARS = 12
ACKS = {"ok", "si", "sì", "no", "grazie", "va bene", "perfetto", "fallo", "vai", "procedi"}


def _ipc(msg: dict) -> str:
    from gray_matter.cli import FAST_CONNECT, _send_ipc
    # Daemon down = no recall, in 0.5 s instead of Windows' ~2 s.
    r = _send_ipc(msg, TIMEOUT, connect_timeout=FAST_CONNECT)
    return "" if not isinstance(r, dict) or "error" in r else str(r.get("result") or "")


def worth_recalling(prompt: str) -> bool:
    p = prompt.strip()
    if len(p) < MIN_CHARS or p.startswith("/"):
        return False
    return p.lower().strip(" .!?") not in ACKS


def fit(text: str, budget: int = BUDGET) -> str:
    text = text.strip()
    return text if len(text) <= budget else text[:budget - 1] + "…"


def session_memory(transcript: str) -> tuple[bool, list]:
    """What this hook already injected in the session, read from the transcript:
    (a profile was shown, the fact ids shown). The transcript, not the daemon,
    is the record: the daemon forgets on restart, and a cold recall the hook gave
    up on (live 2026-11-08) showed nothing, so it must not count."""
    shown, ids = False, set()
    try:
        lines = Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False, []
    for ln in lines:
        if '"hook_additional_context"' not in ln:
            continue
        try:
            a = json.loads(ln).get("attachment") or {}
        except ValueError:
            continue
        for c in a.get("content") or []:
            c = str(c)
            shown = shown or "profile: [" in c
            ids.update(re.findall(r"#([0-9a-f]{8})\b", c))
    return shown, sorted(ids)


def recall(payload: dict) -> str:
    prompt = str(payload.get("prompt") or "")
    session = str(payload.get("session_id") or "")
    if not worth_recalling(prompt):
        # Tells the daemon this turn needs no save check (hosts without a transcript).
        if session:
            _ipc({"action": "turn", "session": session, "worth": False})
        return ""
    profile_shown, ids = session_memory(str(payload.get("transcript_path") or ""))
    # Nothing read from the transcript (none, or a host whose format is not
    # Claude Code's): the daemon's own per-session record decides the profile.
    profile = None if not (profile_shown or ids) else not profile_shown
    # No ping first: without a daemon the connection is refused at once, and _ipc gives ''.
    return fit(_ipc({"action": "recall", "prompt": prompt[:300], "session": session,
                     "profile": profile, "exclude": ids}),
               BUDGET + (0 if profile_shown else PROFILE_BUDGET))


# --- save: did the turn leave its facts? (ADR-015 phase 3) ------------------
#
# The model writes the fact; the hook checks it is there. It extracts nothing
# from the message: the trial version (ADR-014 D4) kept only words that were
# already nodes, and 4 messages out of 5 would have saved nothing. It reads only
# the transcript, so it works with the daemon down too.

SUBSTANTIVE_CHARS = 600   # an answer longer than this is a turn of substance
REMIND = ("[memory] This turn saved no fact. If there is something worth not "
          "repeating (progress, decisions, fixes, details, ideas, the user and their "
          "habits), call store_turn(facts=[{kind, text, concepts}], English only) and then stop. "
          "Not worth a fact: what git or the project files already record (commits, "
          "test runs, file contents). If there is nothing, stop without adding anything.")


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


# --- use: did the answer use what the recall showed? (ADR-015 D8) ------------
#
# Until 2026-11-16 a shown fact counted as used when the next store_turn shared a
# CONCEPT with it: 50 of the 81 confirmed live facts had only that, topic overlap.
# The reply is the evidence, and only this hook reads it. The same rule the
# ledger applies offline (gray_matter/bench/ledger.py imports it from here).

WORD = re.compile(r"[\w./\-]+", re.U)
DATE = re.compile(r"\d{1,2}/\d{1,2}(/\d{2,4})?")
# One recalled fact: "[kind] text (concept) #id". Not the profile's user/habit:
# always shown, so being used proves nothing about the recall.
RECALLED = re.compile(r"\[(?:idea|decision|fix|fact|progress)\]\s+(.+?)\s+#([0-9a-f]{8})\b")


def distinctive(text: str) -> set:
    """Words a model would not write by chance: long ones, or ones with a digit,
    a dot, a slash or an underscore (paths, versions, ids, identifiers)."""
    out = set()
    for w in WORD.findall(text.lower()):
        w = w.strip(".-/\\")
        if DATE.fullmatch(w):            # every fact starts with one: it proves nothing
            continue
        if len(w) >= 8 or (len(w) >= 3 and re.search(r"[\d._/\\]", w)):
            out.add(w)
    return out


def silently_used(fact_words: set, said: str, prompt: str = "") -> bool:
    """The answer reuses the fact: two of its distinctive words, or all of them
    when it has fewer than two. A word the user's own message already holds does
    not count: the model had it without the memory. shortcut: lexical, it misses
    a paraphrase; upgrade to embeddings if the A/B shows it undercounts."""
    words = {w for w in fact_words if w not in prompt}
    if not words:
        return False
    hit = sum(1 for w in words if w in said)
    return hit >= min(2, len(words))


def used_facts(entries: list) -> list:
    """Ids of the facts recalled for the last user message that its turn used:
    what the model wrote and passed to its tools, memory tools excluded (a
    store_turn restating a fact is the self-confirmation this replaces).

    A word the session already held BEFORE the recall proves nothing: the
    model had it without the memory (project vocabulary, the files it is
    working on). On the real sessions of 2026-11-16 the rule without this
    reported 38% of the shown facts, against the ledger's 21%."""
    prompt, shown, said, before = "", {}, [], []
    for e in entries:
        if _is_user_turn(e):
            c = (e.get("message") or {}).get("content")
            before += [prompt, *said]
            prompt = c if isinstance(c, str) else " ".join(
                b.get("text", "") for b in _blocks(e) if b.get("type") == "text")
            shown, said = {}, []
        elif e.get("type") == "attachment":
            a = e.get("attachment") if isinstance(e.get("attachment"), dict) else {}
            if a.get("type") == "hook_additional_context":
                for text, fid in RECALLED.findall(" ".join(str(c) for c in a.get("content") or [])):
                    shown.setdefault(fid, distinctive(text))
        elif e.get("type") == "assistant":
            for b in _blocks(e):
                if b.get("type") == "text":
                    said.append(str(b.get("text") or ""))
                elif b.get("type") == "tool_use" and not _is_memory_tool(str(b.get("name", ""))):
                    said.append(json.dumps(b.get("input"), ensure_ascii=False))
    low, known = " ".join(said).lower(), " ".join([prompt, *before]).lower()
    return sorted(fid for fid, words in shown.items() if silently_used(words, low, known))


def save(payload: dict) -> str:
    """The reason to send the model back to work once, or "" to let it stop.
    Only for a real message (not an ack or a command) whose turn did work or
    answered at length, and only the first time: `stop_hook_active` means this
    Stop already follows our own block, and a second one would loop."""
    if payload.get("stop_hook_active"):
        return ""
    entries = _entries(str(payload.get("transcript_path") or ""))
    used = used_facts(entries)
    if used:      # best-effort like the recall: no daemon, no signal
        _ipc({"action": "call", "server": "neuron", "tool": "confirm", "args": {"facts": used}})
    prompt, wrote, work, chars = last_turn(entries)
    if not prompt:
        # No Claude Code transcript (Kimi, Codex): the daemon saw every store_turn.
        # Codex hands the answer over; Kimi nothing, so its turn counts as substantive.
        if _ipc({"action": "saved", "session": str(payload.get("session_id") or "")}) != "no":
            return ""
        answer = payload.get("last_assistant_message")
        return REMIND if answer is None or len(str(answer)) >= SUBSTANTIVE_CHARS else ""
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
    except Exception:  # noqa: BLE001 — a hook never breaks the user's message
        return
    if not text:
        return
    if "--plain" in argv:   # hosts that append raw stdout to the context (Kimi)
        if mode == "save":  # ...and block on exit 2, the reason on stderr
            sys.stderr.buffer.write(text.encode("utf-8"))
            sys.stderr.flush()
            sys.exit(2)
        sys.stdout.buffer.write(text.encode("utf-8"))
        return
    out = ({"decision": "block", "reason": text} if mode == "save" else
           {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": text}})
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main(sys.argv)
