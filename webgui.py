"""`gray-matter gui` — control center unico dell'ecosistema.

Struttura (SoC):

* **catalogo** (:mod:`gray_matter.catalog`) — *descrive* ambienti e comandi,
  leggendoli dalle CLI dei tool. Nessun elenco di comandi vive qui.
* **backend** (:class:`Api`, questo file) — *esegue*: un solo runner generico
  ``run(tool, command, args)`` per qualunque comando di qualunque ambiente.
  Prima c'era un metodo scritto a mano per comando (~60): la GUI era una copia
  delle CLI e restava indietro a ogni comando nuovo.
* **vista** (``webgui.html``) — *disegna* e basta.

Conseguenza: un subcomando aggiunto a una CLI compare nel control center da
solo. Gli ambienti in sidebar sono quelli davvero installati sulla macchina.

Trasporto invariato e uniforme nei due modi:

* **pywebview** (finestra nativa, WebView2 su Windows);
* **browser** (pywebview assente): ``http.server`` stdlib serve la pagina e
  smista ``POST /api/<metodo>`` agli stessi metodi di :class:`Api`.

In entrambi i casi la vista fa polling di :meth:`Api.poll_log` per l'output
streamato, così nessun thread worker spinge nulla nella UI.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from gray_matter import catalog

__all__ = ["Api", "main"]

_HTML = Path(__file__).with_name("webgui.html")
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_MAX_LOG = 4000

# Radice del workspace: in layout di sviluppo i tre repo sono cartelle sorelle.
_ENV_ROOT = Path(__file__).resolve().parent.parent
_PEER_GIT = {
    "neuron": "https://github.com/recla93/neuron",
    "neurag": "https://github.com/recla93/neurag",
}

# Come si invoca ogni ambiente. `-m <modulo>` e non il console-script: gli
# script stanno in Scripts/ e non sempre sono sul PATH del processo GUI —
# era la causa dei "command not found" nel pannello.
_MODULE_FOR = {
    "gray-matter": ["-m", "gray_matter.cli"],
    "neuron": ["-m", "neuron"],
    "neurag": ["-m", "neurag.cli"],
}


def _python() -> str:
    return sys.executable or "python"


def _gm_version() -> str:
    try:
        from gray_matter import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "?"


def _say(msg: str) -> None:
    """print() sicuro. Lo shortcut lancia la GUI con pythonw.exe, dove
    sys.stdout è None: un print() nudo uccideva il processo appena partito —
    era il "crasha da sola" della modalità browser."""
    try:
        if sys.stdout is not None:
            print(msg)
    except Exception:  # noqa: BLE001
        pass


def _cli_argv(tool: str, *cmd: str) -> list[str]:
    """argv per un comando CLI di un ambiente (``python -m <tool>.cli <cmd...>``).

    È la stessa via generica di :meth:`Api.run`: i pannelli speciali (config,
    repair, uninstall) passano da qui invece di importare gli interni di
    gray_matter — così restano tool-agnostici e loggano in modo uniforme.
    """
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    return [_python(), *base, *cmd]


def _argv_for(tool: str, command: str, args: dict, extra: str = "") -> list[str]:
    """Costruisce l'argv reale a partire dal comando e dai campi compilati.

    Gli argomenti arrivano dal catalogo, quindi il form riflette la CLI vera:
    i posizionali nell'ordine dichiarato, le opzioni come ``--flag valore``
    (o il solo flag se è booleano). Il campo libero finale resta per i casi
    che un form non copre.
    """
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    argv = [_python(), *base, command]
    for a in args.get("_order", []):
        spec = args["_spec"].get(a, {})
        val = args.get(a, "")
        if spec.get("is_flag"):
            if val:
                argv.append(spec["flag"])
        elif spec.get("flag"):
            if str(val).strip():
                argv += [spec["flag"], str(val).strip()]
        elif str(val).strip():                     # posizionale
            argv.append(str(val).strip())
    if extra.strip():
        import shlex
        argv += shlex.split(extra.strip(), posix=(os.name != "nt"))
    return argv


class Api:
    """Backend esposto alla vista. Ogni metodo ritorna dati JSON-abili.

    L'output lungo NON torna come valore: viene streamato riga per riga in un
    buffer che la vista svuota con :meth:`poll_log`, così la UI resta viva
    mentre un comando gira.
    """

    def __init__(self) -> None:
        self._log: deque = deque(maxlen=_MAX_LOG)
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._running: dict[str, str] = {}     # key -> etichetta mostrata

    # -- log ---------------------------------------------------------------
    def _emit(self, line: str, tag: str = "") -> None:
        with self._lock:
            self._log.append({"line": line, "tag": tag, "t": time.time()})

    def poll_log(self, _args: str = "") -> dict:
        with self._lock:
            lines = list(self._log)
            self._log.clear()
        return {"lines": lines, "running": dict(self._running)}

    def clear_log(self, _args: str = "") -> dict:
        with self._lock:
            self._log.clear()
        return {"ok": True}

    def copy_clipboard(self, args: str = "") -> dict:
        """Rete di sicurezza per il pulsante Copia: scrive `text` negli appunti
        di sistema quando la clipboard del WebView è bloccata (WebView2/pywebview).
        Usa lo strumento nativo dell'OS così non serve nessuna dipendenza."""
        req = json.loads(args) if args else {}
        text = req.get("text", "")
        try:
            if sys.platform == "win32":
                cmd = ["clip"]
            elif sys.platform == "darwin":
                cmd = ["pbcopy"]
            else:
                cmd = ["xclip", "-selection", "clipboard"] if shutil.which("xclip") \
                    else ["xsel", "--clipboard", "--input"]
            proc = subprocess.run(cmd, input=text.encode("utf-8"),
                                  creationflags=_CREATE_NO_WINDOW, timeout=5)
            return {"ok": proc.returncode == 0}
        except Exception as exc:  # noqa: BLE001 — nessuno strumento clipboard
            return {"ok": False, "error": str(exc)}

    # -- catalogo ----------------------------------------------------------
    def catalog(self, _args: str = "") -> dict:
        """Ambienti installati + comandi, raggruppati dal più grande al più piccolo.

        Mai sollevare: se il catalogo esplode la GUI deve dirlo, non morire.
        """
        try:
            envs = []
            for env in catalog.environments():
                envs.append({**env, "groups": catalog.grouped(env),
                             "installable": (not env["installed"]) and env["key"] != "gray-matter"})
            return {"envs": envs, "python": _python(), "version": _gm_version()}
        except BaseException as exc:  # noqa: BLE001 — anche SystemExit
            return {"envs": [], "python": _python(), "version": _gm_version(),
                    "error": f"catalogo non leggibile: {type(exc).__name__}: {exc}"}

    # -- esecuzione --------------------------------------------------------
    def _stream(self, argv: list[str], *, key: str, display: str) -> dict:
        """Esegue ``argv`` in background streamando stdout nel buffer di log."""
        existing = self._procs.get(key)
        if existing is not None and existing.poll() is None:
            self._emit(f"[!] '{display}' è già in esecuzione — attendi o premi Ferma.", "err")
            return {"ok": False, "busy": True}
        self._emit(f"$ {' '.join(argv)}", "cmd")
        self._running[key] = display

        def _run() -> None:
            try:
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONUTF8"] = "1"
                proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, bufsize=1,
                    encoding="utf-8", errors="replace",
                    creationflags=_CREATE_NO_WINDOW, env=env)
                self._procs[key] = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._emit(line.rstrip("\n"), _tag_of(line))
                proc.wait()
                self._emit(f"[{display}] terminato (exit {proc.returncode})",
                           "ok" if proc.returncode == 0 else "err")
            except FileNotFoundError:
                self._emit(f"[!] eseguibile non trovato: {argv[0]}", "err")
            except Exception as exc:  # noqa: BLE001
                self._emit(f"[{display}] {exc}", "err")
            finally:
                self._running.pop(key, None)

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def _capture(self, argv: list[str], *, timeout: float = 25) -> "tuple[bool, str, str]":
        """Esegue un comando CORTO e ne cattura stdout/stderr. Sincrono: SOLO per
        letture rapide (``config list --json``, ``repair --json``), mai per comandi
        lunghi — quelli restano non-bloccanti via :meth:`_stream`."""
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout,
                               creationflags=_CREATE_NO_WINDOW, env=env)
        except Exception as exc:  # noqa: BLE001 — eseguibile assente / timeout
            return False, "", str(exc)
        return r.returncode == 0, r.stdout, r.stderr

    def _terminal(self, argv: list[str], *, display: str, keep_open: bool = True) -> dict:
        """Apre ``argv`` in una finestra di terminale vera.

        Serve ai comandi interattivi (setup, uninstall, connect, ...): fanno
        domande, e nel pannello — che esegue con stdin chiuso — restavano
        appesi senza dire niente. Era il "clicco e non parte nulla".

        keep_open: se True (default), la finestra resta aperta a fine comando
                   per leggere l'esito (cmd /k). Se False, la finestra si chiude
                   automaticamente (cmd /c).
        """
        self._emit(f"$ {' '.join(argv)}", "cmd")
        self._emit(f"[{display}] è interattivo: si apre in una finestra di "
                   "terminale — continua lì.", "warn")
        try:
            if os.name == "nt":
                cmd_flag = "/k" if keep_open else "/c"
                subprocess.Popen(["cmd", cmd_flag, *argv],
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
                return {"ok": True}
            for term in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"),
                         ("konsole", "-e"), ("xterm", "-e")):
                if shutil.which(term[0]):
                    subprocess.Popen([*term, *argv])
                    return {"ok": True}
            self._emit("[!] nessun terminale trovato: esegui a mano: "
                       + " ".join(argv), "err")
            return {"ok": False, "error": "nessun terminale disponibile"}
        except Exception as exc:  # noqa: BLE001
            self._emit(f"[{display}] {exc}", "err")
            return {"ok": False, "error": str(exc)}

    def run(self, args: str = "") -> dict:
        """Esegue QUALUNQUE comando del catalogo. Unico punto di esecuzione."""
        req = json.loads(args) if args else {}
        tool, command = req.get("tool", ""), req.get("command", "")
        if not tool or not command:
            return {"ok": False, "error": "servono 'tool' e 'command'"}
        # Il comando deve esistere nel catalogo: la GUI non inventa comandi.
        env = next((e for e in catalog.environments() if e["key"] == tool), None)
        if env is None or not env["installed"]:
            return {"ok": False, "error": f"{tool} non è installato"}
        spec = next((c for c in env["commands"] if c["name"] == command), None)
        if spec is None:
            return {"ok": False, "error": f"{tool} non ha il comando '{command}'"}
        fields = req.get("args") or {}
        fields["_spec"] = {a["dest"]: a for a in spec["args"]}
        fields["_order"] = [a["dest"] for a in spec["args"]]
        # Argomenti obbligatori vuoti: meglio dirlo subito che far fallire
        # argparse dentro la console con un usage criptico.
        missing = [a["dest"] for a in spec["args"]
                   if a.get("required") and not str(fields.get(a["dest"], "")).strip()]
        if missing:
            return {"ok": False,
                    "error": f"compila prima: {', '.join(missing)}"}
        try:
            argv = _argv_for(tool, command, fields, req.get("extra", ""))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if spec.get("interactive"):
            return self._terminal(argv, display=f"{tool} {command}")
        return self._stream(argv, key=f"{tool}:{command}",
                            display=f"{tool} {command}")

    # -- config knobs (settings card) -------------------------------------
    def config_knobs(self, args: str = "") -> dict:
        """Knob correnti di un ambiente (key, value, type, default, help, suggest).

        Via CLI: ``<tool> config list --json`` — i metadati dei knob vivono nel
        tool che li possiede (SSOT), la GUI non importa più `settings`. Un tool
        senza config (es. Neuron) non ha il comando → il pannello non compare.
        """
        req = json.loads(args) if args else {}
        tool = req.get("tool", "")
        try:
            argv = _cli_argv(tool, "config", "list", "--json")
        except ValueError as exc:
            return {"ok": False, "knobs": [], "error": str(exc)}
        ok, out, err = self._capture(argv)
        if not ok:
            return {"ok": False, "knobs": [],
                    "error": err.strip() or out.strip() or f"{tool}: nessun config"}
        try:
            data = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "knobs": [], "error": f"config illeggibile: {exc}"}
        return {"ok": True, "knobs": data.get("knobs", []), "note": data.get("note", "")}

    def config_set(self, args: str = "") -> dict:
        """Persiste un knob via ``<tool> config set <key> <value> --json``,
        con eco in console. Il tool fa la coercizione di tipo e ritorna il valore
        effettivo."""
        req = json.loads(args) if args else {}
        tool, key, value = req.get("tool", ""), req.get("key", ""), req.get("value", "")
        try:
            argv = _cli_argv(tool, "config", "set", str(key), str(value), "--json")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        ok, out, err = self._capture(argv)
        if not ok:
            msg = err.strip() or out.strip() or "errore"
            self._emit(f"[{tool} config] {msg}", "err")
            return {"ok": False, "error": msg}
        try:
            data = json.loads(out)
        except Exception:  # noqa: BLE001
            data = {"key": key, "value": value}
        self._emit(f"[{tool} config] {data.get('key')} = {data.get('value')}", "ok")
        return {"ok": True, "key": data.get("key"), "value": data.get("value")}

    def stop(self, args: str = "") -> dict:
        """Ferma un comando in corso (o tutti, se non se ne indica uno)."""
        req = json.loads(args) if args else {}
        keys = [req["key"]] if req.get("key") else list(self._procs)
        stopped = 0
        for k in keys:
            p = self._procs.get(k)
            if p is not None and p.poll() is None:
                p.terminate()
                stopped += 1
                self._emit(f"[{k}] fermato su richiesta.", "warn")
        return {"ok": True, "stopped": stopped}

    # -- installazione ambienti -------------------------------------------
    def install_env(self, args: str = "") -> dict:
        """Installa un ambiente mancante: cartella sorella se c'è, else git clone."""
        req = json.loads(args) if args else {}
        key = req.get("key", "")
        if key not in _PEER_GIT:
            return {"ok": False, "error": f"non installabile: {key}"}
        sib = _ENV_ROOT / key
        find_links = [str(d / "vendor") for d in (_ENV_ROOT / "gray_matter", sib)
                      if (d / "vendor").is_dir()]
        pip = [_python(), "-m", "pip", "install", str(sib)]
        for fl in find_links:
            pip += ["--find-links", fl]
        if sib.is_dir():
            return self._stream(pip, key=f"install:{key}", display=f"installa {key}")
        if not shutil.which("git"):
            return {"ok": False,
                    "error": f"{key} non è qui e git non è disponibile: installalo a mano"}
        self._emit(f"[installa {key}] clono da {_PEER_GIT[key]}", "cmd")
        return self._stream([shutil.which("git"), "clone", _PEER_GIT[key], str(sib)],
                            key=f"install:{key}", display=f"clona {key}")

    # -- repair (clean reinstall + scelta cosa cancellare) -----------------
    def repair_state(self, args: str = "") -> dict:
        """Superfici cancellabili + reinstall, chieste al TOOL via ``<tool> repair
        --json`` (ogni tool conosce i PROPRI path/installer — SSOT). Da Neuron mostra
        solo Neuron, da NeuRAG solo NeuRAG, da Gray Matter tutta la suite."""
        req = json.loads(args) if args else {}
        scope = req.get("scope", "gray-matter")
        try:
            argv = _cli_argv(scope, "repair", "--json")
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "targets": []}
        ok, out, err = self._capture(argv)
        if not ok:
            return {"ok": False, "error": err.strip() or out.strip() or "repair non disponibile",
                    "targets": []}
        try:
            data = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"repair illeggibile: {exc}", "targets": []}
        return {"ok": True, "scope": data.get("scope", scope),
                "targets": data.get("targets", []),
                "reinstall": data.get("reinstall", "?"),
                "installer": bool(data.get("installer"))}

    def repair_run(self, args: str = "") -> dict:
        """Delega al TOOL: ``<tool> repair <wipe...> --reinstall``. I `wipe` sono i
        token CLI restituiti da repair_state (positional per GM, flag `--wipe-*`
        per Neuron/NeuRAG), così questa resta generica. Aperto in un TERMINALE:
        l'installer -Force è pesante e può fare domande — lì può rispondere, e
        non compete con la GUI (che gira dallo stesso venv)."""
        req = json.loads(args) if args else {}
        wipe = req.get("wipe") or []
        scope = req.get("scope", "gray-matter")
        self._emit(f"$ repair  scope={scope}  wipe={wipe or '(niente)'}", "cmd")
        try:
            argv = _cli_argv(scope, "repair", *wipe, "--reinstall")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return self._terminal(argv, display=f"repair {scope}", keep_open=False)

    # -- uninstall (card dedicata, non interactive) -------------------------
    # Solo Gray Matter espone il comando `uninstall` → la card compare solo per
    # GM (Neuron/NeuRAG escono dal gateway con go-standalone/deregister, non con
    # una disinstallazione dati). Tutto passa da `gray-matter uninstall --json`.

    def uninstall_state(self, args: str = "") -> dict:
        req = json.loads(args) if args else {}
        scope = req.get("scope", "gray-matter")
        try:
            argv = _cli_argv(scope, "uninstall", "--list", "--json")
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "scope": scope}
        ok, out, err = self._capture(argv)
        if not ok:
            return {"ok": False, "error": err.strip() or out.strip() or "uninstall non disponibile",
                    "scope": scope}
        try:
            data = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"uninstall illeggibile: {exc}", "scope": scope}
        return {"ok": True, "scope": data.get("scope", scope),
                "targets": data.get("targets", []), "data": data.get("data", [])}

    def uninstall_run(self, args: str = "") -> dict:
        req = json.loads(args) if args else {}
        scope = req.get("scope", "gray-matter")
        purge_data = bool(req.get("purge_data", False))
        self._emit(f"$ uninstall  scope={scope}  purge_data={purge_data}", "cmd")
        try:
            extra = ["--purge-data"] if purge_data else []
            argv = _cli_argv(scope, "uninstall", "--json", *extra)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        # Sincrono ma breve: reap/deregister/rimozione file, poi verifica. Timeout
        # generoso perché tocca i config dei client.
        ok, out, err = self._capture(argv, timeout=90)
        if not ok and not out.strip():
            msg = err.strip() or "uninstall fallito"
            self._emit(f"[uninstall] {msg}", "err")
            return {"ok": False, "error": msg}
        try:
            res = json.loads(out)
        except Exception as exc:  # noqa: BLE001
            self._emit(f"[uninstall] output illeggibile: {exc}", "err")
            return {"ok": False, "error": str(exc)}
        for r in res.get("results", []):
            name = r.get("name") or r.get("action")
            self._emit(f"  {'✓' if r.get('ok') else '✗'} {name}",
                       "ok" if r.get("ok") else "err")
        verification = res.get("verification", {"ok": res.get("ok"), "checks": {}})
        if verification.get("ok"):
            self._emit(f"[uninstall] {scope}: verificato ✓", "ok")
        else:
            failed = [k for k, v in verification.get("checks", {}).items() if not v]
            self._emit(f"[uninstall] {scope}: verifica ✗ ({', '.join(failed)})", "err")
        return {"ok": res.get("ok", verification.get("ok")),
                "results": res.get("results", []), "verification": verification}

    # -- gm_link (ri-aggancio tool standalone) -------------------------------

    def link_state(self, args: str = "") -> dict:
        """Stato gateway per la card gm_link: quali tool sono standalone e
        ricollegabili. USA --list --json del CLI come SSOT."""
        from gray_matter import clients
        installed = set(clients.installed_servers())
        unmanaged = clients.unmanaged_tools()
        tools = []
        for t in ("neuron", "neurag"):
            tools.append({
                "key": t,
                "installed": t in installed,
                "standalone": t in installed and t in unmanaged,
                "managed": t in installed and t not in unmanaged,
            })
        return {"ok": True, "tools": tools}

    def link_run(self, args: str = "") -> dict:
        """Esegui link per i tool selezionati."""
        req = json.loads(args) if args else {}
        selected = req.get("tools", [])
        if not selected:
            return {"ok": False, "error": "nessun tool selezionato"}
        from gray_matter import clients
        installed = set(clients.installed_servers())
        unmanaged = clients.unmanaged_tools()
        linked, skipped = [], []
        LINK_TOOL_SLUGS = {"neuron": ["neuron", "neuron5"], "neurag": ["neurag"]}
        for t in selected:
            if t not in ("neuron", "neurag"):
                skipped.append({"tool": t, "reason": "tool sconosciuto"})
            elif t not in installed:
                skipped.append({"tool": t, "reason": "non installato"})
            elif t not in unmanaged:
                skipped.append({"tool": t, "reason": "già gestito da GM"})
            else:
                clients.set_unmanaged(t, False)
                linked.append(t)
        reg, dereg = [], []
        if linked:
            reg = clients.register(["gray-matter"])
            drop = [s for t in linked for s in LINK_TOOL_SLUGS.get(t, [t])]
            dereg = clients.deregister(drop) if drop else []
        return {"ok": bool(linked), "linked": linked, "skipped": skipped,
                "details": reg + dereg}

    # -- process management ------------------------------------------------

    def process_list(self, args: str = "") -> dict:
        """Comandi lanciati DAL control center ancora vivi (fonte 'gui').

        ponytail: niente scan `tasklist`/lettura pids del daemon qui — toglieva il
        coupling a `executor`/`paths` E spawnava `tasklist` a OGNI render (era il
        flash + la latenza, task D). Il daemon GM di background si ferma dalla card
        `gray-matter → stop` (comando già nel catalogo). Aggiungere il daemon qui:
        serve una via CLI che ne esponga il PID (oggi non c'è) — non vale il costo.
        """
        processes = [{"pid": p.pid, "name": k, "status": "running", "source": "gui"}
                     for k, p in self._procs.items() if p.poll() is None]
        return {"ok": True, "processes": processes}

    def process_stop(self, args: str = "") -> dict:
        """Ferma un comando lanciato dalla GUI (per PID) o tutti."""
        req = json.loads(args) if args else {}
        target = req.get("pid")
        try:
            target = int(target) if target is not None else None
        except (ValueError, TypeError):
            return {"ok": False, "error": "pid non valido"}
        stopped = 0
        for k, p in list(self._procs.items()):
            if p.poll() is None and (target is None or p.pid == target):
                p.terminate()
                stopped += 1
                self._emit(f"[{k}] fermato.", "warn")
        return {"ok": True, "stopped": stopped}


def _tag_of(line: str) -> str:
    low = line.lower()
    if any(w in low for w in ("error", "errore", "traceback", "[!!]", "failed")):
        return "err"
    if any(w in low for w in ("warning", "attenzione", "[!]")):
        return "warn"
    if any(w in low for w in ("[ok]", " ok", "done", "success")):
        return "ok"
    return ""


# --------------------------------------------------------------------------
# Trasporto
# --------------------------------------------------------------------------

def _build_server(api: Api):
    import http.server

    holder: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):        # niente rumore su stdout
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            self._send(200, holder["html"].encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]
            fn = getattr(api, name, None)
            if not self.path.startswith("/api/") or fn is None or name.startswith("_"):
                self._send(404, b'{"error":"unknown"}', "application/json")
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                result = fn(raw) if raw else fn()
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            self._send(200, json.dumps(result).encode("utf-8"), "application/json")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    holder["html"] = _HTML.read_text(encoding="utf-8").replace(
        "__GM_API_BASE__", f"http://127.0.0.1:{port}")
    return srv, port, holder["html"]


def _browser_mode(url: str, srv, reason: str) -> int:
    """Fallback universale: la pagina nel browser di sistema, server in vita."""
    import webbrowser
    _say(f"Gray Matter control center -> {url}  (browser; {reason})")
    if not os.environ.get("GM_GUI_NOBROWSER"):
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
    return 0


def main(argv: "list[str] | None" = None) -> int:
    api = Api()
    srv, port, html = _build_server(api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    if os.environ.get("GM_GUI_BROWSER"):          # scelta esplicita dell'utente
        return _browser_mode(url, srv, "GM_GUI_BROWSER=1")
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001
        return _browser_mode(url, srv, "pywebview assente")

    # URL, NON html=: una pagina passata come stringa vive su about:blank e
    # WebView2 le blocca le fetch verso http://127.0.0.1 — finestra aperta,
    # zero card. Servita dal nostro stesso server è same-origin: tutto lecito.
    window = webview.create_window(
        "Gray Matter — Control Center", url=url,
        width=1180, height=780, min_size=(940, 620),
        background_color="#1a1b26")
    if os.environ.get("GM_GUI_SELFTEST"):
        def _close():
            time.sleep(1.0)
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=_close, daemon=True).start()
    try:
        # Su Windows si ESIGE WebView2 (edgechromium): senza, pywebview
        # ripiegherebbe su MSHTML (IE11), che non parla il JS della pagina —
        # finestra aperta, niente card, nessun errore. Meglio il browser vero.
        kwargs = {"debug": bool(os.environ.get("GM_GUI_DEBUG"))}
        if os.name == "nt":
            kwargs["gui"] = "edgechromium"
        # Set the window icon from the bundled .ico (best-effort, never block).
        try:
            _ico = Path(__file__).parent / "assets" / "gray-matter.ico"
            if _ico.is_file():
                kwargs["icon"] = str(_ico)
        except Exception:  # noqa: BLE001
            pass
        webview.start(**kwargs)
    except Exception as exc:  # noqa: BLE001 — WebView2 mancante o rotto
        _say(f"[!] finestra nativa non disponibile ({exc}) — apro nel browser.")
        return _browser_mode(url, srv, "WebView2 non disponibile")
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
