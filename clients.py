"""Registrazione MCP standalone di NeuRAG — ``neurag register`` / ``neurag deregister``.

keep-in-sync con ``neuron/src/neuron/clients.py``: questo modulo è un clone
mirato di quell'engine (stessa matrice client, stessi path/shape JSON, stesse
cautele). NeuRAG è un modulo a sé — niente import da Neuron — quindi la logica
è replicata, ma ogni fix di parsing/scrittura va riportato in entrambi.

Regole di design (stdlib-only, come il resto di NeuRAG):
- Mai distruttivo: merge non-distruttivo, backup ``.neurag-bak`` prima di ogni
  scrittura, verify-after-write con rollback in caso di fallimento.
- JSONC (commenti/virgole finali) si LEGGE per diagnosi ma non si riscrive mai:
  perderemmo i commenti dell'utente. In quel caso si stampa uno snippet manuale
  VALIDO (``json.dumps``, backslash correttamente escapati).
- Claude Code: preferita la CLI ufficiale ``claude mcp add``. ``~/.claude.json``
  è il live state file — editarlo direttamente può essere sovrascritto in
  silenzio alla chiusura dell'app. Edit diretto solo come fallback.
- Entry via ``python -m neurag.server`` e NON via console-script ``neurag-mcp``:
  gli script in Scripts/ non sono sempre sul PATH del processo client (causa
  "command not found" — vedi ``gray_matter/webgui.py`` ``_MODULE_FOR``).
"""

from __future__ import annotations

import glob as _glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Callable

log = logging.getLogger("neurag.clients")

__all__ = [
    "Result", "register", "register_all", "deregister", "deregister_all",
    "default_server_python", "cli", "SLUG", "SERVER_ARGS", "CLIENTS",
]

SLUG = "neurag"
SERVER_ARGS = ["-m", "neurag.server"]   # entry MCP: python -m neurag.server


# ---------------------------------------------------------------------------
# Helpers: lettura tollerante, scrittura rigorosa
# ---------------------------------------------------------------------------


def read_text(path: str) -> str:
    """Legge un file di testo tollerando il BOM UTF-8."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        return fh.read()


def strip_jsonc(text: str) -> str:
    """Rimuove commenti // e /* */ e virgole finali — SOLO per la lettura.

    String-aware: i marcatori di commento dentro le stringhe JSON restano."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def load_config(path: str) -> tuple[Any, str]:
    """Ritorna ``(data, kind)`` con kind 'json' | 'jsonc' | 'invalid' | 'missing'."""
    if not os.path.exists(path):
        return None, "missing"
    raw = read_text(path)
    if not raw.strip():
        return {}, "json"
    try:
        return json.loads(raw), "json"
    except ValueError:
        pass
    try:
        return json.loads(strip_jsonc(raw)), "jsonc"
    except ValueError:
        return None, "invalid"


def save_json(path: str, data: Any) -> None:
    """Scrittura JSON rigorosa: UTF-8 senza BOM, indent 2, temp file + replace."""
    tmp = path + ".neurag-tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def backup(path: str) -> "str | None":
    if os.path.exists(path):
        bak = path + ".neurag-bak"
        shutil.copyfile(path, bak)
        return bak
    return None


def manual_snippet(nested_keys: list[str], key: str, entry: dict) -> str:
    """Snippet da incollare a mano, SEMPRE JSON valido (json.dumps escapa)."""
    inner: Any = {key: entry}
    for k in reversed(nested_keys):
        inner = {k: inner}
    return json.dumps(inner, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# TOML (Codex) — replace/append della SOLA sezione, mai overwrite del file
# ---------------------------------------------------------------------------


def toml_upsert_section(text: str, section: str, body_lines: list[str]) -> str:
    """Sostituisce il blocco ``[section]`` se c'e', altrimenti lo appende. Tutto
    il resto del file resta byte-per-byte (keep-in-sync con neuron/clients.py)."""
    new_block = f"[{section}]\n" + "\n".join(body_lines) + "\n"
    pattern = re.compile(r"(?ms)^\[" + re.escape(section) + r"\]\s*?\n.*?(?=^\[|\Z)")
    if pattern.search(text):
        # lambda: il blocco contiene backslash Windows che re.sub
        # interpreterebbe come escape.
        return pattern.sub(lambda _m: new_block, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if text.strip() else "") + new_block


def codex_entry_lines(python_exe: str) -> list[str]:
    return [
        "command = " + json.dumps(python_exe),   # json string == TOML basic string
        "args = " + json.dumps(SERVER_ARGS),
    ]


# ---------------------------------------------------------------------------
# Matrice client — stessa di neuron/clients.py (keep-in-sync)
# ---------------------------------------------------------------------------


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


def _vscode_user_dir() -> str:
    """VS Code's per-user config dir, per-OS."""
    if _env("APPDATA"):
        return os.path.join(_env("APPDATA"), "Code", "User")
    if sys.platform == "darwin":
        return _home("Library", "Application Support", "Code", "User")
    return _home(".config", "Code", "User")


def windsurf_candidates() -> list[str]:
    """Windsurf (Cognition). Primary is Codeium's own MCP file; the second is
    the VS Code-fork layout, since Windsurf is a VS Code fork and newer builds
    follow it. Not verified on this machine (Windsurf not installed) — which is
    exactly why both are probed and `create_if_missing` stays False: a wrong
    guess costs a "skipped", never an invented config in the wrong place."""
    cands = [_home(".codeium", "windsurf", "mcp_config.json")]
    if _env("APPDATA"):
        cands.append(os.path.join(_env("APPDATA"), "Windsurf", "User", "mcp.json"))
    elif sys.platform == "darwin":
        cands.append(_home("Library", "Application Support", "Windsurf", "User", "mcp.json"))
    else:
        cands.append(_home(".config", "Windsurf", "User", "mcp.json"))
    return cands


def vscode_candidates() -> list[str]:
    """`mcp.json` FIRST, then `settings.json`.

    VS Code 1.102 moved MCP servers into a dedicated `User/mcp.json`. Writing
    only to settings.json put the entry where a current VS Code never looks,
    and deregister could not SEE a server that lived in mcp.json — so an
    uninstall left it running. Keep-in-sync with neuron/clients.py.
    """
    d = _vscode_user_dir()
    return [os.path.join(d, "mcp.json"), os.path.join(d, "settings.json")]


def vscode_keys_for(path: str) -> list[str]:
    """mcp.json IS the MCP file → servers sit at the root."""
    return ["servers"] if os.path.basename(path).lower() == "mcp.json" else ["mcp", "servers"]


def claude_desktop_candidates() -> list[str]:
    """Install classico %APPDATA% E il pacchetto Microsoft Store (MSIX),
    più le posizioni macOS/Linux."""
    cands = []
    appdata = _env("APPDATA")
    if appdata:
        cands.append(os.path.join(appdata, "Claude", "claude_desktop_config.json"))
    localapp = _env("LOCALAPPDATA")
    if localapp:
        cands.extend(
            os.path.join(p, "LocalCache", "Roaming", "Claude", "claude_desktop_config.json")
            for p in sorted(_glob.glob(os.path.join(localapp, "Packages", "Claude_*")))
        )
    if sys.platform == "darwin":
        cands.append(_home("Library", "Application Support", "Claude",
                           "claude_desktop_config.json"))
    elif os.name != "nt":
        cands.append(_home(".config", "Claude", "claude_desktop_config.json"))
    return cands


def pick_existing(candidates: list[str]) -> tuple["str | None", list[str]]:
    """Ritorna (scelto, tutti_esistenti). Più hit → vince il più recente."""
    existing = [p for p in candidates if os.path.exists(p)]
    if not existing:
        return None, []
    chosen = max(existing, key=lambda p: os.path.getmtime(p))
    return chosen, existing


# Ogni spec: candidates() -> list[str], keys = path annidato alla mappa server,
# entry(python_exe) -> dict, format.
#
# Matrice IDENTICA a Neuron e a Gray-Matter (2026-07-29). Supera la riduzione a
# 5 client del 2026-07-22 ("zed/codex non servono"): chi sceglie NeuRAG non deve
# ritrovarsi in silenzio meno target di chi sceglie Neuron. `test_client_targeting`
# fallisce se le tre matrici divergono. `vscode` copre anche GitHub Copilot, che
# legge lo stesso `User/mcp.json`.
CLIENTS: dict[str, dict[str, Any]] = {
    "claude-desktop": {
        "label": "Claude Desktop",
        "candidates": claude_desktop_candidates,
        "keys": ["mcpServers"],
        "entry": lambda py: {"command": py, "args": list(SERVER_ARGS)},
        "format": "json",
        "create_if_missing": False,
    },
    "claude-code": {
        "label": "Claude Code",
        "candidates": lambda: [_home(".claude.json")],
        "keys": ["mcpServers"],
        "entry": lambda py: {"command": py, "args": list(SERVER_ARGS)},
        "format": "json",
        "create_if_missing": False,
        "live_state_file": True,   # preferita la CLI `claude mcp add`
    },
    "cursor": {
        "label": "Cursor",
        "candidates": lambda: [_home(".cursor", "mcp.json")],
        "keys": ["mcpServers"],
        "entry": lambda py: {"command": py, "args": list(SERVER_ARGS)},
        "format": "json",
        # False like every other client: creating a config for an app that is
        # not installed litters the disk and — worse — makes detect_state()
        # report that client as present forever after, so GM keeps deploying
        # hooks into it. Verified on a real machine: Cursor and OpenCode were
        # NOT installed and the installer wrote ~/.cursor/mcp.json and
        # ~/.config/opencode/opencode.json anyway.
        "create_if_missing": False,
    },
    "vscode": {
        "label": "VS Code",
        "candidates": vscode_candidates,
        # Two shapes, picked by WHICH file exists (see keys_for):
        #   User/mcp.json      -> {"servers": {...}}          (VS Code 1.102+)
        #   User/settings.json -> {"mcp": {"servers": {...}}} (older inline form)
        "keys": ["mcp", "servers"],
        "keys_for": vscode_keys_for,
        "entry": lambda py: {"type": "stdio", "command": py, "args": list(SERVER_ARGS)},
        "format": "json",   # spesso JSONC in the wild → snippet manuale
        "create_if_missing": False,
    },
    "opencode": {
        "label": "OpenCode",
        "candidates": lambda: [_home(".config", "opencode", "opencode.json")],
        "keys": ["mcp"],
        "entry": lambda py: {"command": [py, *SERVER_ARGS], "type": "local"},
        "format": "json",
        "create_if_missing": False,
    },
    "windsurf": {
        "label": "Windsurf",
        "candidates": windsurf_candidates,
        "keys": ["mcpServers"],
        "entry": lambda py: {"command": py, "args": list(SERVER_ARGS)},
        "format": "json",
        "create_if_missing": False,
    },
    "zed": {
        "label": "Zed",
        "candidates": lambda: (
            [os.path.join(_env("APPDATA"), "Zed", "settings.json")]
            if _env("APPDATA") else [_home(".config", "zed", "settings.json")]
        ),
        "keys": ["context_servers"],
        "entry": lambda py: {"command": py, "args": list(SERVER_ARGS)},
        "format": "json",
        "create_if_missing": False,
    },
    "codex": {
        "label": "Codex CLI",
        "candidates": lambda: [_home(".codex", "config.toml")],
        "keys": ["mcp_servers"],
        "entry": lambda py: {"command": py, "args": list(SERVER_ARGS)},
        "format": "toml",
        "create_if_missing": False,
    },
}


# ---------------------------------------------------------------------------
# Registrazione
# ---------------------------------------------------------------------------


class Result:
    def __init__(self, client: str, ok: bool, action: str, detail: str = "",
                 snippet: str = "", path: str = ""):
        self.client, self.ok, self.action = client, ok, action
        self.detail, self.snippet, self.path = detail, snippet, path

    def line(self) -> str:
        mark = "[OK]" if self.ok else ("[--]" if self.action == "skipped" else "[!!]")
        s = f"  {mark} {self.client}: {self.action}"
        if self.detail:
            s += f" — {self.detail}"
        if self.snippet:
            s += "\n       Aggiungi a mano in " + (self.path or "il config") + ":\n"
            s += "\n".join("         " + ln for ln in self.snippet.splitlines())
        return s


def _claude_argv(*args) -> "list[str] | None":
    """Argv per la CLI `claude`, funzionante ANCHE su Windows: `claude` è uno
    shim .cmd (npm) e CreateProcess non esegue i .cmd → wrapper `cmd /c`.
    (keep-in-sync: stesso fix in gray_matter/clients.py, 2026-07-21)."""
    exe = shutil.which("claude")
    if not exe:
        return None
    argv = [exe, *args]
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        argv = ["cmd", "/c", *argv]
    return argv


# Windows: nascondi la console dei child (claude CLI) — se lanciato da GUI/pythonw
# lampeggiava un CMD. Il flag va nel runner DI DEFAULT, non nei call-site: un
# runner iniettato dai test non deve ricevere `creationflags` a forza.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _default_run(*args, **kwargs):
    kwargs.setdefault("creationflags", _NO_WINDOW)
    return subprocess.run(*args, **kwargs)


def register_claude_code_via_cli(slug: str, python_exe: str,
                                 runner: "Callable | None" = None) -> bool:
    """`claude mcp add --scope user <slug> <python> -- -m neurag.server`."""
    run = runner or _default_run
    argv = _claude_argv("mcp", "add", "--scope", "user", slug, python_exe,
                        "--", *SERVER_ARGS)
    if argv is None:
        return False
    try:
        r = run(argv, capture_output=True, text=True, timeout=60)
        if getattr(r, "returncode", 1) == 0:
            return True
        # già registrato = idempotente, non un errore
        tail = ((getattr(r, "stderr", "") or getattr(r, "stdout", "") or "")
                .strip().splitlines() or ["?"])[-1]
        return "already exists" in tail.lower()
    except Exception as e:  # noqa: BLE001
        log.debug("`claude mcp add` fallita: %s", e)
        return False


def register(client: str, slug: str = SLUG, python_exe: str = "",
             dry_run: bool = False) -> Result:
    # Guard on the WRITE function, not register_all(): the client picker
    # loops over register() directly and drove past a guard placed there.
    # Keep-in-sync with neuron/clients.py.
    dry_run = dry_run or bool(os.environ.get("GM_NO_CLIENT_REGISTER", "").strip())
    spec = CLIENTS.get(client)
    if spec is None:
        return Result(client, False, "client sconosciuto",
                      f"noti: {', '.join(sorted(CLIENTS))}")
    python_exe = python_exe or default_server_python()
    entry = spec["entry"](python_exe)
    keys: list[str] = spec["keys"]

    # Claude Code passa dalla CLI ufficiale quando c'è
    if spec.get("live_state_file") and shutil.which("claude") and not dry_run:
        if register_claude_code_via_cli(slug, python_exe):
            return Result(client, True, "registrato via `claude mcp add`",
                          "CLI ufficiale — sicura sul live state file")
        # CLI presente ma fallita → si prosegue sul file con warning.

    chosen, existing = pick_existing(list(spec["candidates"]()))
    if chosen is None:
        if not spec.get("create_if_missing"):
            return Result(client, True, "skipped", "config non trovato (app non installata?)")
        chosen = spec["candidates"]()[0]
        os.makedirs(os.path.dirname(chosen), exist_ok=True)

    # Alcuni client tengono la mappa server a profondità diversa a seconda di
    # QUALE loro file esiste (VS Code: mcp.json vs settings.json), quindi il
    # nesting si risolve solo dopo aver scelto il file. `keys` statico resta il
    # default per tutti gli altri.
    if spec.get("keys_for"):
        keys = spec["keys_for"](chosen)

    multi_note = ""
    if len(existing) > 1:
        multi_note = ("più config trovati, uso il più recente: " + chosen
                      + " (anche: " + ", ".join(p for p in existing if p != chosen) + ")")

    # -- TOML (Codex): upsert MIRATO della sezione, mai overwrite del file ----
    if spec.get("format") == "toml":
        old_txt = read_text(chosen) if os.path.exists(chosen) else ""
        new_txt = toml_upsert_section(old_txt, f"{keys[0]}.{slug}",
                                      codex_entry_lines(python_exe))
        if dry_run:
            return Result(client, True, "would write (dry-run)", multi_note, path=chosen)
        bak = backup(chosen)
        with open(chosen, "w", encoding="utf-8") as fh:
            fh.write(new_txt)
        # verify-after-write: la nostra sezione c'e' e il resto e' preservato
        after = read_text(chosen)
        if f"[{keys[0]}.{slug}]" not in after:
            if bak:
                shutil.copyfile(bak, chosen)
            return Result(client, False, "verifica scrittura fallita, rollback", path=chosen)
        return Result(client, True, "registrato (TOML section upsert)", multi_note, path=chosen)

    data, kind = load_config(chosen)
    if kind in ("jsonc", "invalid"):
        # mai riscrivere JSONC/file rotti: snippet VALIDO per la mano dell'utente
        snip = manual_snippet(keys, slug, entry)
        why = ("il config usa commenti/virgole finali (JSONC)" if kind == "jsonc"
               else "il config non è JSON parseabile")
        return Result(client, False, "passo manuale richiesto", why, snippet=snip, path=chosen)
    if kind == "missing":
        data = {}
    if not isinstance(data, dict):
        return Result(client, False, "passo manuale richiesto",
                      "la radice del config non è un oggetto JSON",
                      snippet=manual_snippet(keys, slug, entry), path=chosen)

    if dry_run:
        return Result(client, True, "scriverei (dry-run)", multi_note, path=chosen)

    bak = backup(chosen)
    node = data
    for k in keys:
        nxt = node.get(k)
        if not isinstance(nxt, dict):
            nxt = {}
            node[k] = nxt
        node = nxt
    node[slug] = entry
    save_json(chosen, data)

    # verify-after-write + rollback
    reread, rkind = load_config(chosen)
    n: Any = reread if (rkind == "json" and isinstance(reread, dict)) else None
    for k in keys:
        n = n.get(k) if isinstance(n, dict) else None
    if not (isinstance(n, dict) and slug in n):
        if bak:
            shutil.copyfile(bak, chosen)
        return Result(client, False, "verifica scrittura fallita, rollback", path=chosen)

    warn = multi_note
    if spec.get("live_state_file"):
        warn = ((warn + "; ") if warn else "") + \
            "editato il live state file di Claude Code (CLI non trovata) — riavvia " \
            "l'app; se l'entry sparisce, installa la CLI `claude` e rilancia"
    return Result(client, True, "registrato", warn, path=chosen)


def detected_clients() -> list[str]:
    """Clients whose config actually exists on this machine."""
    out = []
    for name, spec in CLIENTS.items():
        chosen, _ = pick_existing(list(spec["candidates"]()))
        if chosen:
            out.append(name)
    return out


def resolve_clients(selector: str, *, interactive: bool = True) -> "list[str] | None":
    """'all' | 'detected' | 'ask' | 'a,b,c'. None = the user aborted.
    Keep-in-sync with neuron/clients.py:resolve_clients."""
    selector = (selector or "all").strip()
    if selector == "all":
        return list(CLIENTS)
    if selector == "detected":
        return detected_clients()
    if selector == "ask":
        if not interactive or not sys.stdin or not sys.stdin.isatty():
            return detected_clients()
        return _pick_clients_interactively()
    names = [n.strip() for n in selector.split(",") if n.strip()]
    unknown = [n for n in names if n not in CLIENTS]
    if unknown:
        raise ValueError(f"unknown client(s): {', '.join(unknown)} — "
                         f"known: {', '.join(sorted(CLIENTS))}")
    return names


def _pick_clients_interactively() -> "list[str] | None":
    found = set(detected_clients())
    names = list(CLIENTS)
    print("\n  Register the MCP server in which clients?")
    for i, name in enumerate(names, 1):
        mark = "x" if name in found else " "
        note = "" if name in found else "   (not detected)"
        print(f"    [{mark}] {i}) {CLIENTS[name]['label']}{note}")
    print("\n  Enter = the detected ones, 'all', 'none', or numbers like 1,3,4")
    try:
        raw = input("  Choice [detected]: ").strip().lower()
    except EOFError:
        # Nobody there to answer: take the safe default rather than registering
        # NOTHING — an installer must not silently no-op on an unreadable prompt.
        print("detected (no input available)")
        return sorted(found, key=names.index)
    except KeyboardInterrupt:
        print()
        return None
    if not raw or raw == "detected":
        return sorted(found, key=names.index)
    if raw == "all":
        return names
    if raw in ("none", "skip", "-"):
        return []
    picked = []
    for tok in raw.replace(" ", ",").split(","):
        if not tok:
            continue
        if tok.isdigit() and 1 <= int(tok) <= len(names):
            picked.append(names[int(tok) - 1])
        elif tok in CLIENTS:
            picked.append(tok)
        else:
            print(f"  (ignoring '{tok}' — not a client)")
    return list(dict.fromkeys(picked))


def register_all(slug: str = SLUG, python_exe: str = "",
                 dry_run: bool = False) -> list[Result]:
    python_exe = python_exe or default_server_python()
    return [register(c, slug, python_exe, dry_run) for c in CLIENTS]


def deregister(client: str, slug: str = SLUG) -> Result:
    """Rimuove la NOSTRA entry da un config client. Non-distruttivo: solo JSON
    (JSONC mai riscritto), backup, Claude Code via CLI quando c'è."""
    spec = CLIENTS.get(client)
    if spec is None:
        return Result(client, False, "client sconosciuto")
    if spec.get("live_state_file") and shutil.which("claude"):
        argv = _claude_argv("mcp", "remove", "--scope", "user", slug)
        if argv is not None:
            try:  # entry assente -> exit != 0: va bene, vogliamo solo che sparisca
                subprocess.run(argv, capture_output=True, text=True, timeout=60,
                               creationflags=_NO_WINDOW)
                return Result(client, True, "deregistrato via `claude mcp remove`")
            except Exception:  # noqa: BLE001
                pass
    chosen, existing = pick_existing(list(spec["candidates"]()))
    if chosen is None:
        return Result(client, True, "skipped", "config non trovato")

    # Si passano TUTTI i config del client, non solo il più recente: la register
    # scrive in un file solo, ma l'entry da togliere può stare in un altro (VS
    # Code tiene sia mcp.json sia settings.json; Claude Desktop ha la copia
    # classica e quella MSIX). Pulire solo `chosen` è come un uninstall lasciava
    # dietro un server ancora vivo. Keep-in-sync con neuron/clients.py.
    removed, manual = [], []
    for path in existing:
        if spec.get("format") == "toml":
            old_txt = read_text(path)
            pattern = re.compile(r"(?ms)^\[mcp_servers\." + re.escape(slug)
                                 + r"\]\s*?\r?\n.*?(?=^\[|\Z)")
            if not pattern.search(old_txt):
                continue
            backup(path)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(pattern.sub("", old_txt))
            removed.append(path)
            continue

        data, kind = load_config(path)
        if kind in ("jsonc", "invalid"):
            manual.append(path)
            continue
        keys = spec["keys_for"](path) if spec.get("keys_for") else spec["keys"]
        node = data
        for k in keys:
            node = node.get(k) if isinstance(node, dict) else None
        if not isinstance(node, dict) or slug not in node:
            continue
        node.pop(slug, None)
        backup(path)
        save_json(path, data)
        removed.append(path)

    if removed:
        note = f"anche: {', '.join(removed[1:])}" if len(removed) > 1 else ""
        return Result(client, True, "deregistrato", note, path=removed[0])
    if manual:
        return Result(client, False, "passo manuale richiesto",
                      f"config JSONC/invalido: rimuovi l'entry '{slug}' a mano",
                      path=manual[0])
    return Result(client, True, "skipped", "non registrato")


def deregister_all(slug: str = SLUG) -> list[Result]:
    return [deregister(c, slug) for c in CLIENTS]


# ---------------------------------------------------------------------------
# Python del server
# ---------------------------------------------------------------------------


def default_server_python() -> str:
    """Il python che DEVE lanciare il server: il venv installato se esiste
    (standalone NeuRAG o venv condiviso GM), altrimenti l'interprete corrente
    (che sta già eseguendo NeuRAG, quindi lo sa importare)."""
    home = os.environ.get("NEURAG_HOME")
    bases = []
    if home:
        bases.append(os.path.join(home, ".venv"))
    if os.name == "nt":
        la = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        bases += [os.path.join(la, "neurag", ".venv"),
                  os.path.join(la, "gray-matter", ".venv")]
    bases += [_home(".local", "share", "neurag", ".venv"),
              _home(".local", "share", "gray-matter", ".venv")]
    exe = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    for b in bases:
        cand = os.path.join(b, *exe)
        if os.path.exists(cand):
            return cand
    return sys.executable


# ---------------------------------------------------------------------------
# CLI (chiamata da neurag.cli: `neurag register` / `neurag deregister`)
# ---------------------------------------------------------------------------


def gm_still_manages(tool: str) -> bool:
    """True se Gray Matter è presente e gestisce ANCORA `tool` (non l'ha rilasciato
    in `unmanaged`). Import guardato: senza GM (standalone puro) → False e la
    registrazione diretta procede liberamente. `tool` = 'neuron' | 'neurag'.
    keep-in-sync con neuron/clients.py."""
    try:
        from gray_matter import settings as _gm
        unmanaged = str(_gm.load().get("unmanaged", ""))
    except Exception:  # noqa: BLE001 — GM assente o config illeggibile = standalone
        return False
    names = {p.strip() for p in unmanaged.split(",") if p.strip()}
    return tool not in names


def _guard_direct_register(tool: str, force: bool, dry_run: bool) -> bool:
    """Blocca la registrazione DIRETTA se GM gestisce ancora il tool (doppia
    registrazione). Ritorna True se si può procedere. `go-standalone` NON passa
    di qui: fa register+release in modo atomico. keep-in-sync con neuron."""
    if force or dry_run or not gm_still_manages(tool):
        return True
    print(f"[!] Gray Matter ti gestisce ancora (modello gateway): registrarti")
    print( "    diretto ora crea una DOPPIA registrazione nei client.")
    print(f"    → entra in standalone pulito:  {tool} go-standalone")
    print(f"    → oppure rilascia da GM:        gray-matter deregister {tool}")
    print(f"    → forzare comunque:             {tool} register --force")
    return False


def cli(cmd: str, client: str = "all", python_exe: str = "",
        dry_run: bool = False, force: bool = False) -> int:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    py = python_exe or default_server_python()
    if cmd == "register":
        if not _guard_direct_register("neurag", force, dry_run):
            return 1
        results = (register_all(SLUG, py, dry_run) if client == "all"
                   else [register(client, SLUG, py, dry_run)])
    else:
        results = (deregister_all(SLUG) if client == "all"
                   else [deregister(client, SLUG)])
    for r in results:
        print(r.line())
    return 0 if all(r.ok or r.action == "skipped" for r in results) else 1
