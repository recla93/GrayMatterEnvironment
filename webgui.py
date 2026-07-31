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
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
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


def _same_interpreter(a: str, b: str) -> bool:
    """Do these two paths mean the same Python?

    `pythonw.exe` and `python.exe` are the SAME install: one is the windowless
    launcher. The control center is started by the desktop shortcut, so it runs
    under `pythonw.exe`, while registration writes `sys.executable` from a
    console run — `python.exe`. Comparing the strings flagged every correctly
    registered client as "points at a DIFFERENT install", on every machine,
    always.

    That is worse than cosmetic. The clients panel is the error register: it
    exists so a real problem stands out, and an alarm that is always on teaches
    you to ignore the one time it means something.
    """
    def norm(p: str) -> str:
        p = os.path.normcase(os.path.normpath(p or ""))
        base = os.path.basename(p)
        if base == "pythonw.exe":                      # stesso venv, altro launcher
            p = os.path.join(os.path.dirname(p), "python.exe")
        return p
    return norm(a) == norm(b)


def _python_for_tool(tool: str) -> str:
    """Get the correct Python executable for a tool.
    
    Discovery order:
    1. GME registry (centralized)
    2. _python() fallback (existing behavior)
    
    This enables multi-venv execution: each tool uses its own Python
    instead of always using GM's Python.
    """
    try:
        # get_python(), not read_tool(): the helper gates on status == installed.
        # Reading the raw dict handed back the venv path of a tool the uninstall
        # had already marked *missing* — the GUI then exec'd a python that was
        # no longer on disk. The .exists() check below stays as the second guard
        # (a venv can vanish without anyone marking anything).
        from gray_matter.gme import get_python
        py = get_python(tool)
        if py and Path(py).exists():
            return py
    except ImportError:
        pass
    return _python()  # fallback to system Python


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

    Uses _python_for_tool() for multi-venv execution.
    """
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    return [_python_for_tool(tool), *base, *cmd]


def _argv_for(tool: str, command: str, args: dict, extra: str = "") -> list[str]:
    """Costruisce l'argv reale a partire dal comando e dai campi compilati.

    Uses _python_for_tool() for multi-venv execution.
    """
    base = _MODULE_FOR.get(tool)
    if base is None:
        raise ValueError(f"ambiente sconosciuto: {tool}")
    argv = [_python_for_tool(tool), *base, command]
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
    def catalog(self, args: str = "") -> dict:
        """Ambienti installati + comandi, raggruppati dal più grande al più piccolo.

        Accetta ``{"lang": "it"|"en"}``: le descrizioni dei comandi seguono la
        lingua scelta nella GUI. Prima arrivavano sempre in italiano anche con
        l'interfaccia in inglese — bottoni tradotti e spiegazioni no.

        Mai sollevare: se il catalogo esplode la GUI deve dirlo, non morire.
        """
        try:
            req = json.loads(args) if args else {}
            lang = req.get("lang") or "it"
            envs = []
            for env in catalog.environments(lang):
                envs.append({**env, "groups": catalog.grouped(env),
                             "installable": (not env["installed"]) and env["key"] != "gray-matter"})
            return {"envs": envs, "python": _python(), "version": _gm_version()}
        except BaseException as exc:  # noqa: BLE001 — anche SystemExit
            return {"envs": [], "python": _python(), "version": _gm_version(),
                    "error": f"catalogo non leggibile: {type(exc).__name__}: {exc}"}

    # -- esecuzione --------------------------------------------------------
    @staticmethod
    def _op_log(key: str) -> Path:
        from gray_matter.gme import gme_root      # lazy, come gli altri usi qui
        p = gme_root() / "logs" / (re.sub(r"[^A-Za-z0-9._-]", "_", key) + ".log")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def operation_log(self, args: str = "") -> dict:
        """L'esito dell'ultima operazione lunga, letto DAL DISCO.

        Serve perché alcune operazioni uccidono chi le guarda. `install.ps1`
        chiama `Stop-VenvProcesses`, che termina ogni processo avviato dal venv
        di Gray Matter — e il control center è uno di quelli, perché gira da
        `…\\.venv\\Scripts\\pythonw.exe`. La scelta è giusta (quei processi
        tengono i file che pip deve sostituire) ma il prezzo lo pagava l'utente:
        premi "Ripara", la finestra sparisce, e non sai se l'installazione sia
        partita, finita o esplosa.

        Il log su file è l'unica cosa che sopravvive: il figlio non muore col
        padre su Windows, quindi l'installer continua e continua a scrivere.
        `running=True` senza riga di uscita significa "in corso, oppure
        interrotta" — e in entrambi i casi quello che era arrivato è qui.
        """
        req = json.loads(args) if args else {}
        key = req.get("key") or ""
        p = self._op_log(key) if key else None
        if not p or not p.exists():
            return {"ok": True, "found": False, "key": key}
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        exit_line = next((l for l in reversed(lines) if l.startswith("[exit ")), None)
        return {"ok": True, "found": True, "key": key,
                "running": exit_line is None,
                "exit": int(exit_line[6:-1]) if exit_line else None,
                "when": p.stat().st_mtime,
                "tail": lines[-200:]}

    def _stream(self, argv: list[str], *, key: str, display: str,
                to_log: bool = False) -> dict:
        """Esegue ``argv`` in background streamando stdout nel buffer di log.

        `to_log=True` scrive ANCHE su file, per le operazioni che possono
        chiudere il control center mentre girano (vedi `operation_log`)."""
        existing = self._procs.get(key)
        if existing is not None and existing.poll() is None:
            self._emit(f"[!] '{display}' è già in esecuzione — attendi o premi Ferma.", "err")
            return {"ok": False, "busy": True}
        self._emit(f"$ {' '.join(argv)}", "cmd")
        self._running[key] = display

        log_fh = None
        if to_log:
            try:
                log_fh = open(self._op_log(key), "w", encoding="utf-8")
                log_fh.write(f"$ {' '.join(argv)}\n")
                log_fh.flush()
            except OSError:
                log_fh = None      # un log che non si apre non ferma il comando

        def _emit_both(line: str, tag: str) -> None:
            self._emit(line, tag)
            if log_fh:
                try:
                    # flush a ogni riga: questo processo può essere terminato in
                    # qualsiasi momento DALL'operazione stessa, e ciò che non è
                    # su disco in quell'istante è perso.
                    log_fh.write(line + "\n")
                    log_fh.flush()
                except OSError:
                    pass

        def _run() -> None:
            try:
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONUTF8"] = "1"
                # stdin=PIPE, non DEVNULL: i comandi che fanno domande (setup,
                # connect, cloud, repair) si rispondono QUI, dalla riga di input
                # sotto la console. Prima venivano dirottati su una finestra
                # `cmd /k` con CREATE_NEW_CONSOLE — la finestra nera che
                # spuntava dalla GUI. Con stdin collegato il pannello è un
                # terminale a tutti gli effetti e la finestra non serve più.
                proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE, text=True, bufsize=1,
                    encoding="utf-8", errors="replace",
                    creationflags=_CREATE_NO_WINDOW, env=env)
                self._procs[key] = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    _emit_both(line.rstrip("\n"), _tag_of(line))
                proc.wait()
                _emit_both(f"[{display}] terminato (exit {proc.returncode})",
                           "ok" if proc.returncode == 0 else "err")
                if log_fh:
                    # Il terminatore che `operation_log` cerca: senza, la
                    # lettura successiva dice "in corso o interrotta", che è
                    # esattamente la verità quando il control center è stato
                    # ucciso a metà.
                    log_fh.write(f"[exit {proc.returncode}]\n")
                    log_fh.flush()
            except FileNotFoundError:
                _emit_both(f"[!] eseguibile non trovato: {argv[0]}", "err")
            except Exception as exc:  # noqa: BLE001
                _emit_both(f"[{display}] {exc}", "err")
            finally:
                self._running.pop(key, None)
                if log_fh:
                    try:
                        log_fh.close()
                    except OSError:
                        pass

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

    def send_input(self, args: str = "") -> dict:
        """Manda una riga allo stdin del comando in esecuzione.

        È la metà mancante di :meth:`_stream`: i comandi interattivi facevano
        una domanda e restavano appesi perché stdin era chiuso, e la GUI li
        dirottava in una finestra `cmd` per farli rispondere. Ora la risposta
        arriva da qui e la finestra non serve.
        """
        req = json.loads(args) if args else {}
        text = str(req.get("text", ""))
        key = req.get("key") or next(iter(self._running), None)
        proc = self._procs.get(key) if key else None
        if proc is None or proc.poll() is not None or proc.stdin is None:
            self._emit("[!] no running command to answer.", "err")
            return {"ok": False, "error": "no running command"}
        try:
            proc.stdin.write(text + "\n")
            proc.stdin.flush()
        except (OSError, ValueError) as exc:   # pipe chiusa mentre si scriveva
            self._emit(f"[!] could not send input: {exc}", "err")
            return {"ok": False, "error": str(exc)}
        # Eco della risposta: lo stdin non passa dallo stdout del figlio, quindi
        # senza questa riga la console mostrerebbe la domanda e mai la risposta.
        self._emit(f"> {text}", "cmd")
        return {"ok": True}

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
            # Non apre più una finestra: il comando fa le sue domande QUI e si
            # risponde dalla riga di input sotto la console (send_input).
            self._emit(f"[{tool} {command}] asks questions — answer in the "
                       "input box below the console.", "warn")
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
        per Neuron/NeuRAG), così questa resta generica.

        Gira nella console della GUI, non più in una finestra `cmd` a parte:
        l'installer -Force è lungo e può fare domande, e ora può riceverle e
        rispondere da qui (`send_input`). Il vantaggio non è solo estetico —
        l'output di una riparazione fallita finisce nel log della GUI, dove lo
        si può copiare, invece di sparire con la finestra alla chiusura.
        """
        req = json.loads(args) if args else {}
        wipe = req.get("wipe") or []
        scope = req.get("scope", "gray-matter")
        self._emit(f"$ repair  scope={scope}  wipe={wipe or '(nothing)'}", "cmd")
        try:
            argv = _cli_argv(scope, "repair", *wipe, "--reinstall")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        # to_log: la riparazione lancia l'installer, che ferma ogni processo
        # del venv — questo control center compreso. Il file è l'unico posto in
        # cui l'esito può sopravvivere a chi lo stava guardando.
        return self._stream(argv, key=f"{scope}:repair",
                            display=f"repair {scope}", to_log=True)

    # -- uninstall (card dedicata, non interactive) -------------------------
    # Ogni tool può esporre il proprio uninstall. GM gestisce il proprio
    # nativamente; per neuron e neurag si invoca il loro CLI.
    # La card compare per ogni tool installato che supporta uninstall.

    def uninstall_state(self, args: str = "") -> dict:
        req = json.loads(args) if args else {}
        scope = req.get("scope", "gray-matter")
        tools = self._detect_uninstall_tools()
        if scope not in tools:
            return {"ok": False, "error": f"uninstall non disponibile per '{scope}'", "scope": scope}
        argv = tools[scope]
        try:
            argv = _cli_argv(*argv)
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
        tools = self._detect_uninstall_tools()
        if scope not in tools:
            return {"ok": False, "error": f"uninstall non disponibile per '{scope}'", "scope": scope}
        argv_template = tools[scope]
        try:
            extra = ["--purge-data"] if purge_data else []
            argv = _cli_argv(*argv_template, *extra)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
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

    def _detect_uninstall_tools(self) -> dict[str, tuple[str, ...]]:
        """Restituisce {scope: argv_template} per ogni tool con uninstall.

        Tutti gli scope sono inclusi: se un tool non è installato il
        comando fallisce con un messaggio chiaro nel risultato JSON."""
        tools: dict[str, tuple[str, ...]] = {}
        tools["gray-matter"] = ("gray-matter", "uninstall", "--list", "--json")
        tools["neuron"] = ("neuron", "setup", "--uninstall", "--json")
        tools["neurag"] = ("neurag", "uninstall", "--json")
        return tools

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

    # -- health metrics -----------------------------------------------------
    def health_state(self, _args: str = "") -> dict:
        """Health metrics for all installed tools.
        
        Reads from catalog (SSOT for installed tools) and enriches with
        GME health data when available. Falls back to catalog when GME
        has no entries (dev/shared-venv setups).
        
        Collects:
        - Status (running/stopped/installed/error)
        - Ping (module import time)
        - Memory (RSS via psutil, best-effort)
        - CPU (via psutil, best-effort)
        - Uptime (process create time)
        """
        # Build GME lookup for enrichment
        gme_map = {}
        try:
            from gray_matter.gme import list_tools as gme_list
            gme_map = {t["key"]: t for t in gme_list()}
        except ImportError:
            pass
        
        tools = []
        for env in catalog.environments():
            if not env.get("installed"):
                continue
            
            gme = gme_map.get(env["key"], {})
            health = gme.get("health", {})
            pid = health.get("pid")
            
            # Check if process is alive via psutil (best-effort)
            if pid:
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    health["memory_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
                    health["cpu_percent"] = round(proc.cpu_percent(interval=0.1), 1)
                    health["uptime_s"] = int(time.time() - proc.create_time())
                    health["status"] = "running"
                except ImportError:
                    health["status"] = "running" if pid else "stopped"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    health["status"] = "stopped"
                    health["pid"] = None
            else:
                health["status"] = "stopped"
            
            # Ping: try to import the module (fast check)
            try:
                import importlib
                start = time.time()
                importlib.import_module(env.get("module", env["key"]))
                health["ping_ms"] = round((time.time() - start) * 1000, 1)
            except Exception:  # noqa: BLE001
                health["ping_ms"] = None
            
            tools.append({
                "key": env["key"],
                "label": env.get("label", env["key"]),
                "version": env.get("version", ""),
                "status": health.get("status", "unknown"),
                "health": health,
            })
        
        return {"ok": True, "tools": tools}

    # -- infrastructure ---------------------------------------------------
    def tunnel_state(self, _args: str = "") -> dict:
        """Tunnel status: backend detection, public URL, config."""
        backends = []
        if shutil.which("cloudflared"):
            backends.append("cloudflared")
        try:
            import importlib
            if importlib.util.find_spec("neuron.tunnel"):
                backends.append("neuron.tunnel")
        except Exception:  # noqa: BLE001
            pass

        config = {}
        try:
            from neuron.tunnel import _tunnel_config_path, _load_tunnel_config
            cfg_path = _tunnel_config_path()
            if cfg_path.exists():
                config = _load_tunnel_config()
        except (ImportError, Exception):  # noqa: BLE001
            pass

        has_cf_creds = False
        try:
            from neuron.tunnel import _has_cf_credentials
            has_cf_creds = _has_cf_credentials()
        except (ImportError, Exception):  # noqa: BLE001
            pass

        return {
            "ok": True,
            "backends": backends,
            "config": config,
            "has_cloudflare_creds": has_cf_creds,
        }

    def bridge_state(self, _args: str = "") -> dict:
        """Bridge status: which bridges are available, ports, full suite detection."""
        import importlib
        gm_detected = importlib.util.find_spec("gray_matter.server") is not None

        bridges = []
        for key, module, default_port in [
            ("gray-matter", "gray_matter.bridge", 8002),
            ("neuron", "neuron.bridge", 8000),
            ("neurag", "neurag.bridge", 8001),
        ]:
            available = importlib.util.find_spec(module) is not None
            bridges.append({
                "key": key,
                "available": available,
                "default_port": default_port,
                "escalates_to_gm": gm_detected and key != "gray-matter",
            })

        active_bridges = []
        for port in (8000, 8001, 8002):
            try:
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        active_bridges.append(port)
            except Exception:  # noqa: BLE001
                pass

        return {
            "ok": True,
            "bridges": bridges,
            "full_suite": gm_detected,
            "active_ports": active_bridges,
        }

    def cloud_state(self, _args: str = "") -> dict:
        """Cloud Turso connection status per database."""
        dbs = {}

        neuron_url = os.environ.get("TURSO_DATABASE_URL", "")
        neuron_token = os.environ.get("TURSO_AUTH_TOKEN", "")
        dbs["neuron"] = {
            "configured": bool(neuron_url and neuron_token),
            "url": neuron_url[:50] + "..." if len(neuron_url) > 50 else neuron_url,
            "env_var": "TURSO_DATABASE_URL",
        }

        neurag_url = os.environ.get("NEURAG_TURSO_DATABASE_URL") or os.environ.get("TURSO_DATABASE_URL", "")
        neurag_token = os.environ.get("NEURAG_TURSO_AUTH_TOKEN") or os.environ.get("TURSO_AUTH_TOKEN", "")
        dbs["neurag"] = {
            "configured": bool(neurag_url and neurag_token),
            "url": neurag_url[:50] + "..." if len(neurag_url) > 50 else neurag_url,
            "env_var": "NEURAG_TURSO_DATABASE_URL",
        }

        gm_url = os.environ.get("GM_TURSO_DATABASE_URL") or os.environ.get("TURSO_DATABASE_URL", "")
        gm_token = os.environ.get("GM_TURSO_AUTH_TOKEN") or os.environ.get("TURSO_AUTH_TOKEN", "")
        dbs["gm"] = {
            "configured": bool(gm_url and gm_token),
            "url": gm_url[:50] + "..." if len(gm_url) > 50 else gm_url,
            "env_var": "GM_TURSO_DATABASE_URL",
        }

        return {"ok": True, "databases": dbs}

    # -- MCP clients: detect / verify / merge --------------------------------
    def clients_state(self, _args: str = "") -> dict:
        """DETECT + VERIFY every MCP client, including what is WRONG.

        This is the error register: a config we cannot parse, or one pointing at
        an interpreter that no longer exists, is reported instead of silently
        skipped. Nothing is written here — this call is read-only.
        """
        try:
            from gray_matter import clients as C
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        me = _python()
        out = []
        for key, spec in C.CLIENTS.items():
            try:
                paths = [p for p in spec["paths"]() if os.path.exists(p)]
            except Exception as exc:  # noqa: BLE001 — a broken path lambda
                out.append({"key": key, "label": spec["label"], "detected": False,
                            "problem": f"path probe failed: {exc}"})
                continue
            if not paths:
                out.append({"key": key, "label": spec["label"], "detected": False,
                            "registered": False, "problem": None})
                continue

            files = []
            for p in paths:
                info = {"path": p, "readable": True, "registered": False,
                        "command": None, "problem": None}
                try:
                    raw = Path(p).read_text(encoding="utf-8-sig")
                except OSError as exc:
                    info.update(readable=False, problem=f"unreadable: {exc}")
                    files.append(info)
                    continue
                if spec.get("format") == "toml":
                    info["registered"] = "[mcp_servers.gray-matter]" in raw
                    m = re.search(r"(?ms)^\[mcp_servers\.gray-matter\].*?^command\s*=\s*\"(.*?)\"",
                                  raw)
                    info["command"] = m.group(1).replace("\\\\", "\\") if m else None
                else:
                    try:
                        data = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        # JSONC or genuinely broken. We never rewrite these —
                        # say so, loudly, instead of pretending it is fine.
                        info.update(readable=False,
                                    problem="not plain JSON (comments/trailing commas?) — "
                                            "this config is never rewritten automatically")
                        files.append(info)
                        continue
                    node = data
                    for k in C.keys_for(spec, p):
                        node = node.get(k) if isinstance(node, dict) else None
                    if isinstance(node, dict) and "gray-matter" in node:
                        info["registered"] = True
                        cmd = node["gray-matter"].get("command")
                        info["command"] = cmd[0] if isinstance(cmd, list) else cmd
                if info["registered"] and info["command"]:
                    if not os.path.exists(info["command"]):
                        info["problem"] = ("registered, but the interpreter is GONE: "
                                           f"{info['command']}")
                    elif me and not _same_interpreter(info["command"], me):
                        info["problem"] = ("points at a DIFFERENT install: "
                                           f"{info['command']}")
                files.append(info)

            out.append({
                "key": key, "label": spec["label"], "detected": True,
                "registered": any(f["registered"] for f in files),
                "problem": next((f["problem"] for f in files if f["problem"]), None),
                "files": files,
            })
        problems = [c for c in out if c.get("problem")]
        return {"ok": True, "python": me, "clients": out,
                "problem_count": len(problems)}

    def clients_register(self, args: str = "") -> dict:
        """MERGE the gateway entry into the selected clients. Never destructive:
        `clients.register` backs up, merges into the existing config and verifies
        the write. Every per-client outcome is returned, failures included.

        Args (JSON): {"clients": ["cursor", ...], "gateway": true}
        """
        try:
            from gray_matter import clients as C
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        try:
            payload = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"bad request: {exc}"}
        picked = payload.get("clients") or []
        if not isinstance(picked, list) or not picked:
            return {"ok": False, "error": "select at least one client"}
        unknown = [c for c in picked if c not in C.CLIENTS]
        if unknown:
            return {"ok": False, "error": f"unknown client(s): {', '.join(unknown)}"}

        # `register_flow`, not `register`: the same entry point `gray-matter
        # register` uses, so the panel and the installer cannot drift again.
        # They already had — only the CLI reset the unmanaged list on a gateway
        # flip, so the identical button left two different registry states.
        results = C.register_flow(gateway=bool(payload.get("gateway", True)),
                                  only=picked, py=_python())
        failed = [r for r in results if not r.get("ok") and r.get("action") != "skipped"]
        return {"ok": not failed, "results": results, "failed": len(failed)}

    # -- migration ----------------------------------------------------------
    def migrate(self, args: str = "") -> dict:
        """Migrate old installs to GME registry.
        
        Args (JSON):
            - tool: migrate a single tool by key
            - all: if True, migrate all detected old installs
        """
        try:
            from gray_matter.gme import migrate_tool, migrate_all, detect_old_installs
        except ImportError:
            return {"ok": False, "error": "gme module not available"}

        # Unguarded json.loads turned any malformed payload into a raw traceback
        # in the GUI's error card. This endpoint is the migration button — the one
        # place a user lands when their install is already in a bad state.
        try:
            req = json.loads(args) if args else {}
        except json.JSONDecodeError:
            return {"ok": False, "error": "richiesta non valida"}
        
        if req.get("all"):
            r = migrate_all()
            if r.get("migrated"):
                self._emit(f"[migrate] {len(r['migrated'])} tools registered in GME", "ok")
            if r.get("errors"):
                for e in r["errors"]:
                    self._emit(f"[migrate] {e}", "err")
            return r
        
        tool = req.get("tool", "")
        if not tool:
            # Return list of old installs (detection only)
            old = detect_old_installs()
            return {"ok": True, "old_installs": old}
        
        r = migrate_tool(tool)
        if r.get("ok"):
            self._emit(f"[migrate] {tool} registered in GME", "ok")
        else:
            self._emit(f"[migrate] {tool}: {r.get('error', 'failed')}", "err")
        return r


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
            # The page is served over http, not file://, so a relative path to
            # assets/ would 404. One tiny route beats inlining a 1.4 MB logo as
            # base64 into every page load.
            if self.path.split("?", 1)[0] == "/logo.png":
                logo = Path(__file__).with_name("assets") / "GM.png"
                try:
                    self._send(200, logo.read_bytes(), "image/png")
                except OSError:
                    self._send(404, b"", "image/png")   # header hides it via onerror
                return
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
                # `str(exc)` alone is a symptom with no address. "'str' object
                # has no attribute 'get'" was reported from the clients panel
                # and cost an hour of guessing, because the one thing that says
                # WHERE — the traceback — was discarded here, at the only point
                # where it still exists. The panel keeps showing the short
                # message; `where` gives whoever is debugging the file and line,
                # and the console line survives even if the browser is closed.
                tb = traceback.format_exc()
                print(f"[gui] {name} failed:\n{tb}", file=sys.stderr, flush=True)
                result = {"error": str(exc), "endpoint": name,
                          "where": tb.strip().splitlines()[-3:]}
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
        # Close only once the page is actually LOADED. The old fixed 1.0s slept
        # straight through a WebView2 cold start (several seconds on first run)
        # and destroyed the window mid-initialisation, so the self-test — the
        # one tool for verifying the GUI — ended in an E_ABORT stack trace on a
        # perfectly healthy install. A verifier that cries wolf is worse than
        # none. Env-tunable, and the timeout is still a hard backstop so a truly
        # hung WebView2 cannot wedge the process forever.
        _budget = float(os.environ.get("GM_GUI_SELFTEST_TIMEOUT", "45"))
        _loaded = threading.Event()
        try:
            window.events.loaded += _loaded.set
        except Exception:  # noqa: BLE001 — older pywebview: fall back to the timer
            pass

        def _close():
            if not _loaded.wait(_budget):
                _say("[selftest] page never signalled 'loaded' — closing anyway.")
            else:
                _say("[selftest] page loaded — closing.")
                time.sleep(0.5)     # let the first paint land before teardown
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
