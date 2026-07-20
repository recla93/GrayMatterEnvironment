"""`gray-matter gui` — web-based unified control center for the trio.

One window, three panels (Orchestrator/GM, Vault/NeuRAG, Memory/Neuron). The
view is ``webgui.html`` (HTML/CSS/JS); it calls the :class:`Api` backend over a
bridge. **All process management stays in Python** — pywebview only swaps the
view for the old Tkinter widgets.

Transport is uniform across two modes:

* **pywebview** (native window, Edge WebView2 on Windows): the view calls
  ``window.pywebview.api.<method>(argsJson)``.
* **browser fallback** (pywebview missing / headless): a stdlib
  ``http.server`` serves the page and dispatches ``POST /api/<method>`` to the
  same :class:`Api` methods, then the default browser is opened.

Either way the frontend polls :meth:`Api.poll_log` for streamed subprocess
output, so there is no thread-unsafe push from worker threads.
"""
from __future__ import annotations

import importlib.util
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

__all__ = ["Api", "main"]

_HTML = Path(__file__).with_name("webgui.html")
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# The workspace root holds the sibling project folders (dev layout). GM acts as
# the ecosystem hub: whichever tool you install pulls GM in, and from GM you can
# install the missing peers on a button — sibling `pip install -e` when the
# folder is here, else a git clone + install.
_ENV_ROOT = Path(__file__).resolve().parent.parent
_PEERS = {
    "neuron": {"label": "Neuron · memory", "module": "neuron", "dir": "Neuron",
               "git": "https://github.com/recla93/Neuron"},
    "neurag": {"label": "NeuRAG · vault", "module": "neurag", "dir": "neurag",
               "git": "https://github.com/recla93/neurag"},
}


def _python() -> str:
    return sys.executable or "python"


class Api:
    """Backend exposed to the view. Every method returns JSON-able data.

    Long output does NOT come back as a return value — it is streamed line by
    line into a buffer that the view drains via :meth:`poll_log`. This keeps
    the UI responsive while a command runs and mirrors the old Tkinter queue.
    """

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen[str]] = {}
        self._keepalive: set[str] = set()
        self._bg_args: dict[str, list[str]] = {}
        self._restarts: dict[str, int] = {}
        self._stopping: set[str] = set()
        self._log_buf: deque[dict] = deque(maxlen=5000)
        self._lock = threading.Lock()
        # network stack state (Bridge + Tunnel), mirrors the Tkinter GUI
        self._net_state = "off"            # off | starting | up
        self._net_port = 8000
        self._tunnel_url = ""

    # -- log plumbing --------------------------------------------------------

    def _emit(self, line: str, tag: str = "") -> None:
        with self._lock:
            for part in line.splitlines() or [""]:
                self._log_buf.append({"line": part, "tag": tag})

    def poll_log(self, _args: str = "") -> list[dict]:
        """Drain and return buffered log lines (called on a timer by the view)."""
        with self._lock:
            out = list(self._log_buf)
            self._log_buf.clear()
        return out

    def clear_log(self, _args: str = "") -> dict:
        with self._lock:
            self._log_buf.clear()
        return {"ok": True}

    # -- generic streaming command ------------------------------------------

    def _stream(self, argv: list[str], *, key: str = "__fg__",
                display: str = "", cwd: "str | None" = None,
                env_extra: "dict[str, str] | None" = None) -> dict:
        """Run ``argv`` in the background, streaming stdout to the log buffer.

        Only one foreground command (``key='__fg__'``) runs at a time. Named
        keys (Bridge/Tunnel) coexist so the network stack stays up while the
        user runs other actions.
        """
        existing = self._procs.get(key)
        if existing is not None and existing.poll() is None:
            self._emit(f"[!] '{display or key}' is already running — wait or Stop.", "err")
            return {"ok": False, "busy": True}
        self._emit(f"$ {' '.join(argv)}", "cmd")

        def _run() -> None:
            try:
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONUTF8"] = "1"
                if env_extra:
                    env.update(env_extra)
                proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, encoding="utf-8", errors="replace",
                    creationflags=_CREATE_NO_WINDOW, env=env, cwd=cwd)
                self._procs[key] = proc
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._route(key, display, line.rstrip("\n"))
                proc.wait()
            except FileNotFoundError:
                self._emit(f"[!] command not found: {argv[0]}", "err")
            except Exception as exc:  # noqa: BLE001
                self._emit(f"[{display or key}] {exc}", "err")
            finally:
                self._on_done(key, display)

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def _route(self, key: str, display: str, line: str) -> None:
        """Tag a streamed line; detect the tunnel URL for the network stack."""
        tag = ""
        if key in ("Bridge", "Tunnel"):
            low = line.lower()
            tag = "err" if any(k in low for k in ("error", "fail", "traceback")) else "dim"
            if "trycloudflare.com" in line:
                import re
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
                if m:
                    self._tunnel_url = m.group(0)
                    self._net_state = "up"
                    self._emit(f"connector URL: {self._tunnel_url}/mcp", "ok")
            self._emit(f"[{key}] {line}", tag)
        else:
            self._emit(line, tag)

    def _on_done(self, key: str, display: str) -> None:
        proc = self._procs.pop(key, None)
        intentional = key in self._stopping
        self._stopping.discard(key)
        rc = proc.returncode if proc else 0
        if rc and not intentional:
            self._emit(f"[{display or key}] exited with code {rc}.", "err")
        elif key in ("Bridge", "Tunnel"):
            self._emit(f"[{key}] stopped.", "dim")
        # watchdog: revive a keep-alive process that died unexpectedly
        if key in self._keepalive and not intentional:
            n = self._restarts.get(key, 0) + 1
            self._restarts[key] = n
            delay = min(2.0 * (2 ** min(n - 1, 5)), 60.0)
            self._emit(f"[{key}] watchdog: restarting in {int(delay)}s (#{n})…", "dim")
            threading.Timer(delay, lambda: self._revive(key)).start()

    def _revive(self, key: str) -> None:
        if key in self._keepalive and (
                key not in self._procs or self._procs[key].poll() is not None):
            self._stream(self._bg_args.get(key, []), key=key, display=key)

    # -- orchestrator (gray-matter) -----------------------------------------

    def gm_status(self, _args: str = "") -> dict:
        """Fast structured status via the daemon IPC (no subprocess)."""
        try:
            from gray_matter.cli import _send_ipc
            r = _send_ipc({"action": "status"})
        except Exception as exc:  # noqa: BLE001
            return {"running": False, "error": str(exc)}
        if "error" in r:
            return {"running": False, "error": r["error"]}
        servers = [{"name": n, "status": i.get("status", "?"),
                    "pid": i.get("pid"), "tools": i.get("tool_names", []),
                    "collaborative": i.get("collaborative", True)}
                   for n, i in r.items()]
        return {"running": True, "servers": servers}

    def gm_start(self, _args: str = "") -> dict:
        return self._stream(["gray-matter", "start"], display="gm start")

    def gm_stop(self, _args: str = "") -> dict:
        return self._stream(["gray-matter", "stop"], display="gm stop")

    def gm_mode(self, args: str = "") -> dict:
        mode = json.loads(args or "{}").get("mode", "collaborate")
        return self._stream(["gray-matter", "mode", mode], display=f"mode {mode}")

    def gm_isolate(self, args: str = "") -> dict:
        name = json.loads(args or "{}").get("name", "")
        return self._stream(["gray-matter", "isolate", name], display=f"isolate {name}")

    def gm_collaborate(self, args: str = "") -> dict:
        name = json.loads(args or "{}").get("name", "")
        return self._stream(["gray-matter", "collaborate", name], display=f"collab {name}")

    def gm_bridges(self, _args: str = "") -> dict:
        return self._stream(["gray-matter", "bridges"], display="bridges")

    # -- ecosystem (GM as hub: detect + install peers) ----------------------

    def eco_status(self, _args: str = "") -> dict:
        """Which peers are importable, and which are here as sibling folders."""
        peers = []
        for key, p in _PEERS.items():
            try:
                installed = importlib.util.find_spec(p["module"]) is not None
            except Exception:  # noqa: BLE001 — a broken/partial install
                installed = False
            peers.append({
                "key": key, "label": p["label"], "installed": installed,
                "sibling": (_ENV_ROOT / p["dir"]).is_dir(),
            })
        return {"peers": peers}

    def _peer_steps(self, key: str) -> "list[list[str]] | None":
        """Command steps that install a peer: editable from the sibling folder,
        else git clone + editable. None = impossible (no git, no sibling)."""
        p = _PEERS.get(key)
        if not p:
            return None
        sib = _ENV_ROOT / p["dir"]
        # Turso is mandatory and pyturso has NO PyPI win_amd64 wheel: point pip
        # at the prebuilt wheels in Neuron/vendor so it never compiles from Rust.
        pip = [_python(), "-m", "pip", "install", "-e", str(sib)]
        vendor = _ENV_ROOT / "Neuron" / "vendor"
        if vendor.is_dir():
            pip += ["--find-links", str(vendor)]
        if sib.is_dir():
            return [pip]
        if shutil.which("git"):
            return [["git", "clone", p["git"], str(sib)], pip]
        return None

    def eco_install(self, args: str = "") -> dict:
        """Install a peer: editable from the sibling folder, else git clone it."""
        key = json.loads(args or "{}").get("key", "")
        steps = self._peer_steps(key)
        if steps is None:
            self._emit("[!] unknown peer, or git not found and no sibling folder.", "err")
            return {"ok": False, "error": "cannot install"}
        return self._run_seq(steps, display=f"install {key}")

    # -- setup wizard --------------------------------------------------------

    def setup_state(self, _args: str = "") -> dict:
        """Everything the Setup card needs: peers, manifest, detected clients."""
        out = {"peers": self.eco_status()["peers"]}
        try:
            from gray_matter import executor, paths
            st = executor.detect_state()
            out.update({"manifest": paths.manifest_path().exists(),
                        "clients": st.get("clients", []),
                        "orphans": len(st.get("orphan_pids", []))})
        except Exception as exc:  # noqa: BLE001
            out["error"] = str(exc)
        return out

    def setup_run(self, args: str = "") -> dict:
        """The wizard's Install: pip-install the selected missing peers, then
        `gray-matter install` (gateway registration + hooks + manifest).
        dry_run previews the gateway part without touching anything."""
        a = json.loads(args or "{}")
        dry = bool(a.get("dry_run"))
        installed = {p["key"]: p["installed"] for p in self.eco_status()["peers"]}
        steps: list[list[str]] = []
        for key in a.get("components") or []:
            if installed.get(key):
                continue
            peer = self._peer_steps(key)
            if peer is None:
                self._emit(f"[!] cannot install '{key}' (no sibling, no git) — skipping.", "err")
                continue
            if not dry:
                steps += peer
        steps.append([_python(), "-m", "gray_matter.cli", "install"]
                     + (["--dry-run"] if dry else []))
        return self._run_seq(steps, display="setup preview" if dry else "setup install")

    def setup_prefs_get(self, _args: str = "") -> dict:
        """Current settings (DEFAULTS + user overrides) for the wizard's prefs."""
        try:
            from gray_matter import settings
            return {"prefs": settings.load(), "defaults": settings.DEFAULTS}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def setup_prefs_set(self, args: str = "") -> dict:
        """Save wizard prefs: only known keys, type-coerced by settings.set.
        Effective on the next daemon (re)start — like `gray-matter config set`."""
        try:
            from gray_matter import settings
            saved, errors = [], []
            for k, v in (json.loads(args or "{}").get("prefs") or {}).items():
                try:
                    settings.set(k, v)
                    saved.append(k)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{k}: {exc}")
            self._emit(f"[prefs] saved: {', '.join(saved) or '-'}"
                       + (f" | errors: {'; '.join(errors)}" if errors else ""),
                       "err" if errors else "ok")
            if saved:
                self._emit("[prefs] restart the daemon (Stop/Start) to apply.", "")
            return {"ok": not errors, "saved": saved, "errors": errors}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def setup_test(self, _args: str = "") -> dict:
        """The wizard's Test: daemon reachability + full health snapshot."""
        return self._run_seq([[_python(), "-m", "gray_matter.cli", "ping"],
                              [_python(), "-m", "gray_matter.cli", "doctor"]],
                             display="setup test")

    def _run_seq(self, steps: "list[list[str]]", *, display: str = "") -> dict:
        """Run several commands in sequence in one thread, stopping on failure."""
        existing = self._procs.get("__fg__")
        if existing is not None and existing.poll() is None:
            self._emit("[!] a command is already running — wait or Stop.", "err")
            return {"ok": False, "busy": True}

        def _go() -> None:
            ok = True
            for argv in steps:
                self._emit(f"$ {' '.join(argv)}", "cmd")
                try:
                    env = os.environ.copy()
                    env["PYTHONUNBUFFERED"] = "1"
                    env["PYTHONUTF8"] = "1"
                    proc = subprocess.Popen(
                        argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1, encoding="utf-8", errors="replace",
                        creationflags=_CREATE_NO_WINDOW, env=env)
                    self._procs["__fg__"] = proc
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        self._emit(line.rstrip("\n"))
                    proc.wait()
                    if proc.returncode:
                        self._emit(f"[{display}] step failed (code {proc.returncode}) — stopping.", "err")
                        ok = False
                        break
                except FileNotFoundError:
                    self._emit(f"[!] command not found: {argv[0]}", "err")
                    ok = False
                    break
                except Exception as exc:  # noqa: BLE001
                    self._emit(f"[{display}] {exc}", "err")
                    ok = False
                    break
            self._procs.pop("__fg__", None)
            self._emit(f"[{display}] {'done.' if ok else 'aborted.'}", "ok" if ok else "err")

        threading.Thread(target=_go, daemon=True).start()
        return {"ok": True}

    # -- vault (neurag) ------------------------------------------------------

    def rag_status(self, _args: str = "") -> dict:
        return self._stream(["neurag", "status"], display="neurag status")

    def rag_tree(self, _args: str = "") -> dict:
        return self._stream(["neurag", "tree"], display="neurag tree")

    def rag_query(self, args: str = "") -> dict:
        q = json.loads(args or "{}").get("text", "").strip()
        if not q:
            return {"ok": False, "error": "empty query"}
        return self._stream(["neurag", "query", q], display="neurag query")

    def rag_import(self, args: str = "") -> dict:
        path = json.loads(args or "{}").get("path", "").strip()
        if not path:
            return {"ok": False, "error": "no file"}
        return self._stream(["neurag", "import", path], display="neurag import")

    # -- memory (neuron) -----------------------------------------------------

    def nr_overview(self, _args: str = "") -> dict:
        return self._stream(["neuron", "manage", "--overview"], display="overview")

    def nr_doctor(self, _args: str = "") -> dict:
        return self._stream(["neuron", "doctor"], display="doctor")

    def nr_consolidate(self, _args: str = "") -> dict:
        return self._stream(["neuron", "manage", "--consolidate"], display="consolidate")

    def nr_visualize(self, _args: str = "") -> dict:
        return self._stream(["neuron", "manage", "--visualize"], display="visualize")

    def nr_register(self, _args: str = "") -> dict:
        return self._stream(["neuron", "register", "--client", "all"], display="register")

    def nr_console(self, _args: str = "") -> dict:
        """Console is a stdin REPL — open it in a real terminal (the one case)."""
        return self._open_terminal(["neuron", "console"], "console")

    # -- setup wizard: register the installed trio in MCP clients ------------

    def wiz_detect(self, _args: str = "") -> dict:
        from gray_matter import clients as C
        return {"servers": C.installed_servers(), "clients": C.doctor()}

    def wiz_register(self, _args: str = "") -> dict:
        from gray_matter import clients as C
        servers = C.installed_servers()
        if not servers:
            self._emit("[!] no installed servers to register — install one first.", "err")
            return {"ok": False}
        self._emit(f"Registering {', '.join(servers)} in detected clients…", "cmd")
        results = C.register(servers, py=_python())
        for r in results:
            tag = "ok" if r.get("ok") else ("dim" if r.get("action") == "skipped" else "err")
            line = f"  {r['client']}: {r['action']}"
            if r.get("detail"):
                line += f" — {r['detail']}"
            self._emit(line, tag)
            if r.get("snippet"):
                self._emit("    add this by hand:", "dim")
                for ln in r["snippet"].splitlines():
                    self._emit("      " + ln, "dim")
        self._emit("Done. Restart your AI apps to pick up the servers.", "ok")
        return {"ok": True, "results": results}

    # -- Turso cloud form (delegates to neuron.connect) ---------------------

    def turso_test(self, args: str = "") -> dict:
        d = json.loads(args or "{}")
        url, token = d.get("url", "").strip(), d.get("token", "").strip()
        try:
            from neuron.connect import probe_connection, validate_url
        except Exception:
            return {"ok": False, "error": "Neuron not installed — Turso is a Neuron feature"}
        err = validate_url(url)
        if err:
            return {"ok": False, "error": err}
        if not token:
            return {"ok": False, "error": "auth token required"}
        try:
            ok, scheme, detail = probe_connection(url, token)
            return {"ok": ok, "scheme": scheme or "", "detail": detail}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def turso_save(self, args: str = "") -> dict:
        d = json.loads(args or "{}")
        url, token = d.get("url", "").strip(), d.get("token", "").strip()
        try:
            from neuron.connect import update_env_file
            env_path = os.path.join(os.getcwd(), ".env")
            update_env_file(env_path, {"TURSO_DATABASE_URL": url,
                                       "TURSO_AUTH_TOKEN": token})
        except Exception as exc:  # noqa: BLE001
            self._emit(f"[turso] save failed: {exc}", "err")
            return {"ok": False, "error": str(exc)}
        self._emit(f"[turso] credentials saved to {env_path} — restart Neuron to apply.", "ok")
        return {"ok": True, "path": env_path}

    # -- network stack (Bridge + Tunnel, watchdog) --------------------------

    def net_state(self, _args: str = "") -> dict:
        active = [n for n in ("Bridge", "Tunnel")
                  if n in self._procs and self._procs[n].poll() is None]
        return {"state": self._net_state, "active": active,
                "tunnel_url": self._tunnel_url}

    def net_start(self, _args: str = "") -> dict:
        missing = self._network_preflight()
        if missing:
            self._emit("Install the missing dependencies above, then retry.", "err")
            return {"ok": False, "missing": missing}
        self._net_state = "starting"
        self._tunnel_url = ""
        self._restarts.pop("Bridge", None)
        self._restarts.pop("Tunnel", None)
        self._keepalive.update(("Bridge", "Tunnel"))
        self._bg_args["Bridge"] = ["neuron", "bridge"]
        self._bg_args["Tunnel"] = ["neuron", "tunnel"]
        self._stream(["neuron", "bridge"], key="Bridge", display="Bridge")
        threading.Thread(target=self._await_bridge_then_tunnel, daemon=True).start()
        return {"ok": True}

    def _await_bridge_then_tunnel(self, port: int = 8000, timeout: float = 90.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "Tunnel" not in self._keepalive:      # user pressed Stop meanwhile
                return
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1.5):
                    pass
                self._emit(f"[Bridge] ready on 127.0.0.1:{port} — starting Tunnel…", "ok")
                self._stream(["neuron", "tunnel"], key="Tunnel", display="Tunnel")
                return
            except OSError:
                time.sleep(1.0)
        self._emit(f"[!] Bridge did not open port {port} within {int(timeout)}s — "
                   "Tunnel NOT started.", "err")
        self._keepalive.discard("Tunnel")
        self._net_state = "off"

    def net_stop(self, _args: str = "") -> dict:
        self._net_state = "off"
        self._keepalive.discard("Bridge")
        self._keepalive.discard("Tunnel")
        self._stopping.update(("Bridge", "Tunnel"))
        for name in ("Bridge", "Tunnel"):
            self._kill(name)
        self._tunnel_url = ""
        return {"ok": True}

    def _network_preflight(self) -> list[str]:
        missing: list[str] = []
        self._emit("Checking dependencies:", "dim")
        runner = next((r for r in ("mcp-proxy", "uvx", "uv", "pipx") if shutil.which(r)), None)
        if runner:
            self._emit(f"  ok  mcp-proxy runner: {runner}", "ok")
        else:
            missing.append("mcp-proxy runner (uv/pipx)")
            self._emit("  xx  no mcp-proxy runner (Bridge). Try: winget install astral-sh.uv", "err")
        if shutil.which("cloudflared"):
            self._emit("  ok  cloudflared (Tunnel)", "ok")
        else:
            missing.append("cloudflared")
            self._emit("  xx  cloudflared not found. Try: winget install Cloudflare.cloudflared", "err")
        return missing

    # -- process control -----------------------------------------------------

    def _kill(self, name: str) -> None:
        proc = self._procs.get(name)
        if proc and proc.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                    creationflags=_CREATE_NO_WINDOW)
                else:
                    proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            self._emit(f"[{name}] terminated.", "err")

    def stop_all(self, _args: str = "") -> dict:
        self._keepalive.clear()
        self._net_state = "off"
        for name in list(self._procs):
            self._stopping.add(name)
            self._kill(name)
        self._tunnel_url = ""
        self._emit("[all stopped]", "err")
        return {"ok": True}

    def _open_terminal(self, argv: list[str], display: str) -> dict:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["cmd", "/k", *argv],
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
            elif sys.platform == "darwin":
                script = " ".join(argv).replace('"', '\\"')
                subprocess.Popen(["osascript", "-e",
                                  f'tell app "Terminal" to do script "{script}"'])
            else:
                for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                    if shutil.which(term):
                        subprocess.Popen([term, "-e", *argv])
                        break
                else:
                    self._emit(f"[!] no terminal emulator — run `{' '.join(argv)}` manually.", "err")
                    return {"ok": False}
            self._emit(f"[{display}] opened in a new terminal.", "ok")
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            self._emit(f"[!] could not open terminal: {exc}", "err")
            return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Local HTTP server — the SINGLE transport. Both the pywebview window and the
# browser fallback point at http://127.0.0.1:<port>/ , so the frontend always
# talks plain fetch to a real http origin. No js_api bridge, no file:// content
# (which on Windows left window.pywebview undefined and the buttons dead).
# ---------------------------------------------------------------------------

def _build_server(api: Api):
    """Start the local API server. Returns (server, port, injected_html).

    The page's own absolute address is baked into the HTML (``__GM_API_BASE__``)
    so the frontend fetches an absolute URL — which works whether pywebview
    renders the page from an http origin or from a file:// window. CORS headers
    (plus an OPTIONS preflight handler) let a file:// page reach the server.
    """
    import http.server

    holder = {"html": ""}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a):  # silence default logging
            pass

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:               # CORS preflight
            self.send_response(204)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, holder["html"].encode("utf-8"),
                           "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            if not self.path.startswith("/api/"):
                self._send(404, b"not found", "text/plain")
                return
            method = self.path[len("/api/"):]
            fn = getattr(api, method, None)
            if fn is None or method.startswith("_"):
                self._send(404, b'{"error":"no such method"}',
                           "application/json")
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                result = fn(raw) if raw else fn()
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            self._send(200, json.dumps(result).encode("utf-8"),
                       "application/json")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    holder["html"] = _HTML.read_text(encoding="utf-8").replace(
        "__GM_API_BASE__", f"http://127.0.0.1:{port}")
    return srv, port, holder["html"]


def main(argv: "list[str] | None" = None) -> int:
    api = Api()
    srv, port, html = _build_server(api)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"

    try:
        import webview  # noqa: F401
    except Exception:
        import webbrowser
        print(f"Gray Matter control center → {url}  (browser; pywebview not installed)")
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

    # html= (with the absolute API base baked in) renders reliably on WebView2;
    # the frontend reaches the server by absolute URL + CORS, so the file://
    # origin that broke relative fetch no longer matters.
    window = webview.create_window(
        "Gray Matter — Control Center", html=html,
        width=1080, height=720, min_size=(900, 600),
        background_color="#1a1b26")
    if os.environ.get("GM_GUI_SELFTEST"):
        def _close():
            time.sleep(1.0)
            try:
                window.destroy()
            except Exception:
                pass
        threading.Thread(target=_close, daemon=True).start()
    try:
        webview.start()
    finally:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
