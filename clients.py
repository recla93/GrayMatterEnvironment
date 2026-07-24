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
# Matrice client — stessa di neuron/clients.py (keep-in-sync)
# ---------------------------------------------------------------------------


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


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
# entry(python_exe) -> dict, format. Matrice identica a Neuron (senza zed/codex:
# decisione utente 2026-07-22 — claude-desktop, claude-code, cursor, vscode,
# opencode bastano; aggiungerne uno = copiare la riga da neuron/clients.py).
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
        "create_if_missing": True,
    },
    "vscode": {
        "label": "VS Code",
        "candidates": lambda: (
            [os.path.join(_env("APPDATA"), "Code", "User", "settings.json")]
            if _env("APPDATA")
            else [_home("Library", "Application Support", "Code", "User", "settings.json")]
            if sys.platform == "darwin"
            else [_home(".config", "Code", "User", "settings.json")]
        ),
        "keys": ["mcp", "servers"],
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
        "create_if_missing": True,
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

    multi_note = ""
    if len(existing) > 1:
        multi_note = ("più config trovati, uso il più recente: " + chosen
                      + " (anche: " + ", ".join(p for p in existing if p != chosen) + ")")

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
    chosen, _ = pick_existing(list(spec["candidates"]()))
    if chosen is None:
        return Result(client, True, "skipped", "config non trovato")
    data, kind = load_config(chosen)
    if kind in ("jsonc", "invalid"):
        return Result(client, False, "passo manuale richiesto",
                      f"config {kind}: rimuovi l'entry '{slug}' a mano", path=chosen)
    node = data
    for k in spec["keys"]:
        node = node.get(k) if isinstance(node, dict) else None
    if not isinstance(node, dict) or slug not in node:
        return Result(client, True, "skipped", "non registrato")
    node.pop(slug, None)
    backup(chosen)
    save_json(chosen, data)
    return Result(client, True, "deregistrato", path=chosen)


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
