"""CLI entry points: neurag (standalone CLI) and neurag-mcp (server)."""

import argparse
import json as json_mod
import sys
from pathlib import Path

# NIENTE import pesanti a livello modulo: Gray Matter importa questo modulo
# solo per leggere build_parser() (catalogo GUI). Caricare qui db/chunker
# (sqlite/turso/embedder) rendeva l'introspezione lenta o — se una dipendenza
# mancava nel processo GUI — faceva sparire TUTTI i comandi NeuRAG dal
# control center. Gli import vivono in main(), dove servono davvero.


# Il parser sta in una funzione a sé: È l'elenco dei comandi (SSOT) e Gray Matter
# lo ispeziona per costruire la GUI (gray_matter/catalog.py). Aggiungere un
# subcomando qui lo fa comparire da solo anche nel control center.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NeuRAG — knowledge RAG CLI (neurag)")
    # Declared BEFORE the subparsers: `action="version"` prints and exits during
    # parsing, so it beats `required=True`. Without it `neurag --version` — the
    # installer's last line, and what the GUI reads — died with an argparse
    # usage error and left the completion banner showing a blank version.
    from neurag import __version__
    parser.add_argument("-V", "--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show knowledge base status")

    idx = sub.add_parser("chunk", help="Chunk a file/dir to stdout (does not save)")
    idx.add_argument("path", help="Directory or file to chunk")

    add = sub.add_parser("add-node", help="Add a node to the hierarchy")
    add.add_argument("name", help="Node name")
    add.add_argument("type", choices=["godnode", "fundamental", "specialization"], help="Node type")
    add.add_argument("--parent", default=None, help="Parent node name")
    add.add_argument("--triggers", nargs="*", default=[], help="Trigger keywords")

    ac = sub.add_parser("add-chunks", help="Attach chunks from stdin (JSON) to a node")
    ac.add_argument("node", help="Target node name")
    ac.add_argument("--file", help="JSON file with chunks array (default: stdin)")

    q = sub.add_parser("query", help="Search the knowledge base")
    q.add_argument("query", help="Search topic")
    q.add_argument("--top-n", type=int, default=5, help="Number of results (default 5)")
    q.add_argument("--json", action="store_true", help="Output as JSON")
    q.add_argument("--deep", action="store_true",
                   help="Include parked (dormant) nodes — see `recall`")

    rc = sub.add_parser("recall",
                        help="Search EVERY layer, parked nodes included "
                             "(nothing is ever deleted, only parked)")
    rc.add_argument("query", help="Search topic")
    rc.add_argument("--top-n", type=int, default=5, help="Number of results (default 5)")
    rc.add_argument("--json", action="store_true", help="Output as JSON")

    pk = sub.add_parser("park",
                        help="Report nodes idle enough to move to a dormant "
                             "layer. DRY RUN unless --apply")
    pk.add_argument("--apply", action="store_true",
                    help="Actually move them (default: only report)")
    pk.add_argument("--json", action="store_true", help="Output as JSON")

    up = sub.add_parser("unpark", help="Bring a parked node back to the active vault")
    up.add_argument("name", help="Node name")

    cf = sub.add_parser("confirm",
                        help="Mark two or more nodes as having been useful "
                             "TOGETHER: the links between them learn from it")
    cf.add_argument("names", nargs="+", help="Two or more node names")
    cf.add_argument("--json", action="store_true", help="Output as JSON")

    rl = sub.add_parser("related",
                        help="What else a node connects to, by spreading "
                             "activation (ranked by strength, not hop count)")
    rl.add_argument("name", help="Node name")
    rl.add_argument("--hops", type=int, default=2, help="Hops (default 2)")
    rl.add_argument("--limit", type=int, default=10, help="Max results (default 10)")
    rl.add_argument("--deep", action="store_true", help="Include parked nodes")
    rl.add_argument("--json", action="store_true", help="Output as JSON")

    dc = sub.add_parser("decay",
                        help="Weaken link weights and tag salience by the time "
                             "elapsed since the last run")
    dc.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("tree", help="Show node hierarchy")

    imp = sub.add_parser("import", help="Bulk-import a folder tree from a YAML mapping")
    imp.add_argument("mapping", help="Path to the YAML mapping file")

    ing = sub.add_parser("ingest",
                         help="Graph a folder: nodes from its structure, chunks, embeddings, links")
    ing.add_argument("path", help="Folder to graph")
    ing.add_argument("--godnode", default=None,
                     help="Root node to use/create (default: the folder name)")

    ren = sub.add_parser("rename-node", help="Rename a node (also updates the children's paths)")
    ren.add_argument("name", help="Current node name")
    ren.add_argument("new_name", help="New name")

    rem = sub.add_parser("remove-node", help="Delete a node and its whole subtree")
    rem.add_argument("name", help="Name of the node to delete")

    sub.add_parser("health", help="Structural audit of the vault (integrity check)")

    sub.add_parser("doctor", help="Environment + vault health snapshot (tier, embedder, gateway)")

    cfg_p = sub.add_parser("config",
                           help="Get/set tunable knobs (rerank on/off, rerank pool, ...)")
    cfg_p.add_argument("action", choices=["get", "set", "list"])
    cfg_p.add_argument("key", nargs="?", default="")
    cfg_p.add_argument("value", nargs="?", default=None)
    cfg_p.add_argument("--json", action="store_true",
                       help="Structured JSON output (used by the control center)")
    cfg_p.add_argument("--force", action="store_true",
                       help="Change embed_model/embed_dim even though the vault "
                            "already holds vectors (they become unusable until "
                            "`neurag reindex`)")

    rix = sub.add_parser("reindex",
                         help="Re-embed every chunk with the active model "
                              "(after changing embed_model)")
    rix.add_argument("--json", action="store_true",
                     help="Structured JSON output (used by the control center)")

    rep = sub.add_parser("repair",
                         help="Clean reinstall of NeuRAG ONLY (standalone, no GM): choose what to delete, then force-reinstall")
    rep.add_argument("--wipe-knowledge", action="store_true", help="delete knowledge.db")
    rep.add_argument("--wipe-config", action="store_true", help="delete the NeuRAG config (rerank, ...)")
    rep.add_argument("--no-reinstall", action="store_true",
                     help="clean only, do not reinstall the code")
    rep.add_argument("--reinstall", action="store_true",
                     help="run NeuRAG's OWN installer right away with --force (from the recorded paths)")
    rep.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    rep.add_argument("--json", action="store_true",
                     help="list the removable surfaces as JSON (used by the control center)")

    rpx = sub.add_parser("record-paths",
                         help="Record NeuRAG's source folder (used by the installer)")
    rpx.add_argument("--source", default="", help="NeuRAG's source folder (the repo)")

    reg = sub.add_parser("register",
                         help="Register NeuRAG's MCP server in your AI clients (standalone, no GM)")
    reg.add_argument("--client", default="all",
                     help="claude-desktop|claude-code|cursor|vscode|opencode|all (default: all)")
    reg.add_argument("--python", dest="python_exe", default="",
                     help="Python for the server (default: the installed venv)")
    reg.add_argument("--dry-run", action="store_true", help="show what would happen, write nothing")
    reg.add_argument("--force", action="store_true",
                     help="register directly even if GM still manages you (double registration)")

    der = sub.add_parser("deregister",
                         help="Remove NeuRAG from your AI clients' configs")
    der.add_argument("--client", default="all",
                     help="claude-desktop|claude-code|cursor|vscode|opencode|all (default: all)")

    der.add_argument("--json", action="store_true", help="output as JSON")

    uni = sub.add_parser("uninstall",
                         help="Uninstall: deregister from clients, optionally purge data")
    uni.add_argument("--purge-data", action="store_true", help="also delete knowledge.db")
    uni.add_argument("--json", action="store_true", help="output JSON for webgui integration")
    uni.add_argument("--yes", action="store_true", help="non-interactive: assume yes for prompts")

    gst = sub.add_parser("go-standalone",
                         help="NeuRAG leaves the GM gateway: it registers as a direct MCP server in your clients "
                              "and asks GM (if present) to stop managing it. Undo with "
                              "`gray-matter register --gateway`")
    gst.add_argument("--dry-run", action="store_true", help="show what would happen, write nothing")

    gui_p = sub.add_parser("gui",
                   help="Open the control center (shared Gray Matter GUI; installs GM if missing)")
    gui_p.add_argument("--shortcut-only", action="store_true",
                       help="only create the desktop icon and exit (used by the installer)")

    sub.add_parser("start", help="Start the NeuRAG server in the background (MCP stdio)")
    sub.add_parser("stop", help="Stop the NeuRAG server")

    return parser


# GUI: gruppo di appartenenza di ogni comando, dal più grande al più piccolo.
COMMAND_GROUPS = {
    "status": "inspect", "tree": "inspect", "query": "inspect",
    "health": "inspect", "doctor": "inspect",
    "chunk": "maintenance", "add-node": "maintenance",
    "add-chunks": "maintenance", "import": "maintenance",
    "ingest": "maintenance", "reindex": "maintenance", "rename-node": "maintenance",
    "remove-node": "maintenance",
    "config": "tuning", "repair": "lifecycle", "record-paths": "lifecycle",
    "register": "lifecycle", "deregister": "lifecycle", "uninstall": "lifecycle",
    "go-standalone": "lifecycle", "gui": "lifecycle",
    "start": "lifecycle", "stop": "lifecycle",
}


def _cmd_go_standalone(dry_run: bool = False) -> None:
    """NeuRAG esce dal gateway: (a) si registra diretto nei client, (b) chiede a
    GM — se presente — di smettere di gestirlo (persistente + IPC best-effort).
    NON tocca l'entry `gray-matter` nei client finché un peer resta gestito da
    GM: quel giudizio è di GM (clients.release_tool)."""
    from neurag import clients as _clients
    print("NeuRAG go-standalone" + (" (dry-run)" if dry_run else "") + ":")
    for r in _clients.register_all(dry_run=dry_run):
        print(r.line())
    if dry_run:
        print("  [dry-run] not asking GM to release NeuRAG.")
        return
    try:
        from gray_matter import clients as _gm_clients
        for line in _gm_clients.release_tool("neurag"):
            print("  " + line)
    except ImportError:
        print("  Gray Matter not installed: NeuRAG was already standalone.")
    print("Done. Restart your AI apps. To go back to the gateway: gray-matter register --gateway")


def _cmd_uninstall(purge_data: bool = False, as_json: bool = False, yes: bool = False) -> None:
    """Uninstall NeuRAG: deregister from clients, optionally purge data."""
    from neurag.clients import deregister_all as _dereg_all
    from neurag.clients import SLUG
    results: list[dict] = []
    checks: dict[str, bool] = {}
    data_purged = False
    if as_json:
        dereg_results = _dereg_all(SLUG)
        for r in dereg_results:
            entry = {"name": r.client, "ok": r.ok, "action": r.action, "detail": r.detail}
            results.append(entry)
            checks[f"deregistered_{r.client}"] = r.ok
        if purge_data:
            from neurag import paths as _p
            db_dir = _p.data_dir()
            if db_dir.exists():
                import shutil
                shutil.rmtree(db_dir)
                data_purged = True
                checks["data_purged"] = True
            else:
                checks["data_purged"] = True
        print(json_mod.dumps({"ok": all(checks.values()), "results": results,
                              "verification": {"ok": all(checks.values()),
                                               "checks": checks}},
                             ensure_ascii=False))
        return
    print("Uninstall NeuRAG:")
    print("  1) Deregister from all AI clients")
    for r in _dereg_all(SLUG):
        print(f"     {'✓' if r.ok else '✗'} {r.line()}")
    if purge_data:
        from neurag import paths as _p
        db_dir = _p.data_dir()
        if db_dir.exists():
            if yes or input(f"  Also delete data at {db_dir}? [y/N] ").strip().lower() in ("y", "yes", "s", "si"):
                import shutil
                shutil.rmtree(db_dir)
                print(f"  [OK] removed {db_dir}")
            else:
                print(f"  Memory kept: {db_dir}")
        else:
            print("  Data dir not found — nothing to purge.")
    print("Done. Uninstall the package with: pip uninstall neurag")


def _cmd_start() -> None:
    """Avvia il server NeuRAG come processo background.

    DEPENDENCIES:
    - neurag.paths.data_dir(): cartella dati per PID file
    - subprocess.Popen con stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL
    - sys.executable: interprete Python per lanciare `python -m neurag.cli`

    SAFETY CHECKS:
    1. PID file esistente + processo vivo → return (no-op)
    2. PID file corrotto (ValueError/OSError) → viene ignorato, sovrascritto
    3. FileNotFoundError (exe non trovato) → sys.exit(1), messaggio stderr
    4. Processo fallisce subito (poll != None dopo 1s) → PID file rimosso, sys.exit(1)

    FALLBACK:
    - Se PID file esistente ma processo morto → sovrascrive e avvia nuovo processo
    - Se PID file corrotto → viene ignorato, nuovo processo avviato
    """
    import os, subprocess, sys, time
    from pathlib import Path
    from neurag import paths as _paths

    pid_file = _paths.data_dir() / "neurag_server.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if _is_alive(pid):
                print(f"NeuRAG server already running (PID {pid}).")
                return
        except (ValueError, OSError):
            pass  # PID file corrotto: ignora, sovrascriverà

    # The HTTP bridge, not `neurag.server`. `server` is the STDIO transport: it
    # reads a client off stdin, and this spawns it with stdin=DEVNULL, so it
    # saw EOF and exited cleanly every single time — a daemon that cannot
    # possibly stay up. Neuron's `start` has always launched `neuron.bridge`
    # (port 8000); this is its twin on 8001, which is also what `webgui.py`
    # already expects for NeuRAG.
    cmd = [sys.executable, "-m", "neurag.bridge"]
    flags = 0
    if os.name == "nt":
        # NOT DETACHED_PROCESS: Windows ignores CREATE_NO_WINDOW when combined
        # with DETACHED_PROCESS (or CREATE_NEW_CONSOLE), and the detached child
        # allocates its own console -> the empty CMD window this was meant to
        # avoid. CREATE_NEW_PROCESS_GROUP just keeps it out of this console's
        # Ctrl-C, same fix already proven in gray_matter/server.py's own spawn.
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    # NOT DEVNULL. The child's output is the only account of why it died, and
    # throwing it away is what made this unfixable from the outside: the server
    # crashed on an MCP handshake error and all the user ever saw was "avviato"
    # followed by "not running".
    log = _paths.data_dir() / "neurag_server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
    except FileNotFoundError as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        sys.exit(1)

    pid_file.write_text(str(proc.pid), encoding="utf-8")
    # A fixed 1s slept straight through the failure it was meant to catch: the
    # crash landed at ~1.5s, after the import of the embedder. Watch for a few
    # seconds instead of guessing one, and stop as soon as it is settled.
    for _ in range(50):
        time.sleep(0.1)
        if proc.poll() is not None:
            break
    if proc.poll() is not None:
        print(f"NeuRAG server è fallito subito (exit {proc.returncode}).")
        tail = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-12:]
        if tail:
            print("--- " + str(log) + " ---", file=sys.stderr)
            print("\n".join(tail), file=sys.stderr)
        pid_file.unlink(missing_ok=True)
        sys.exit(1)
    print(f"NeuRAG server avviato (PID {proc.pid}) — log: {log}")


def _cmd_stop() -> None:
    """Ferma il server NeuRAG.

    DEPENDENCIES:
    - neurag.paths.data_dir(): cartella dati per PID file
    - os.kill(pid, 0): verifica processo vivo
    - os.kill(pid, SIGTERM/SIGKILL): terminazione

    SAFETY CHECKS:
    1. PID file non esistente → return (nessuna azione)
    2. PID file corrotto (ValueError/OSError) → rimosso
    3. Processo non vivo (PID non trovato) → PID file rimosso
    4. PermissionError → PID file rimosso, sys.exit(1)
    5. ProcessLookupError durante SIGTERM → già terminato, ignora
    6. SIGTERM non basta (dopo 2s) → SIGKILL come fallback

    FALLBACK:
    - Se SIGTERM fallisce (processo non risponde) → SIGKILL dopo 2s
    - Se PID file corrotto → viene rimosso
    - Se processo già morto → PID file rimosso
    """
    import os, signal, sys, time
    from pathlib import Path
    from neurag import paths as _paths

    pid_file = _paths.data_dir() / "neurag_server.pid"
    if not pid_file.exists():
        print("NeuRAG server not running (no PID file).")
        return
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        print("File PID corrotto.")
        pid_file.unlink(missing_ok=True)
        return
    if not _is_alive(pid):
        print(f"NeuRAG server not running (PID {pid} not found).")
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"Process {pid} already exited.")
    except PermissionError:
        print(f"Permission denied for PID {pid}.")
        pid_file.unlink(missing_ok=True)
        sys.exit(1)
    for _ in range(10):
        time.sleep(0.2)
        if not _is_alive(pid):
            break
    if _is_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    pid_file.unlink(missing_ok=True)
    print("NeuRAG server fermato.")


def _is_alive(pid: int) -> bool:
    """True se il processo PID è vivo.

    DEPENDENCIES:
    - os.kill(pid, 0): signal 0 verifica esistenza senza inviare segnali

    SAFETY CHECKS:
    1. ProcessLookupError → processo non esiste, return False
    2. PermissionError → processo esiste ma non abbiamo permessi, return False
    3. OSError (WinError 87) → PID non valido su Windows, return False
    """
    import os
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _bootstrap_gray_matter() -> bool:
    """Installa gray-matter nello STESSO venv (extra ``[gui]``), streamando il
    progresso, e ritorna True se dopo diventa importabile. Prova in ordine:
    (1) la cartella sorella ``gray_matter`` del layout di sviluppo, (2) l'indice
    pip. keep-in-sync con neuron/__main__.py `_bootstrap_gray_matter`."""
    import subprocess, importlib, importlib.util
    from pathlib import Path
    from neurag import paths as _paths
    py = sys.executable or "python"
    candidates = []
    try:
        sib = _paths.source_dir().parent / "gray_matter"
        if (sib / "pyproject.toml").exists():
            argv = [py, "-m", "pip", "install", str(sib)]
            if (sib / "vendor").is_dir():
                argv += ["--find-links", str(sib / "vendor")]
            candidates.append(("cartella sorella", argv))
    except Exception:  # noqa: BLE001 — path non registrato
        pass
    # Wheel d'emergenza vendorato NEL package (viaggia nel wheel di NeuRAG): GM
    # ha solo `mcp` come dep, già presente qui → install completamente OFFLINE,
    # nessuna dipendenza da rete/PyPI/GitHub.
    vendor = Path(__file__).resolve().parent / "_gm_vendor"
    if vendor.is_dir() and any(vendor.glob("gray_matter-*.whl")):
        candidates.append(("wheel vendorato (offline)",
                           [py, "-m", "pip", "install", "--find-links", str(vendor),
                            "gray-matter"]))
    candidates.append(("indice pip", [py, "-m", "pip", "install", "gray-matter>=1.0"]))
    import shutil
    if shutil.which("git"):
        candidates.append(("GitHub", [py, "-m", "pip", "install",
                                      "git+https://github.com/recla93/gray-matter"]))
    for label, argv in candidates:
        print(f"[gui] Gray Matter is not installed: installing it ({label})...")
        try:
            subprocess.call(argv)
        except Exception as exc:  # noqa: BLE001
            print(f"[gui] install fallita ({label}): {exc}")
            continue
        importlib.invalidate_caches()
        if importlib.util.find_spec("gray_matter") is not None:
            print("[gui] Gray Matter installato.")
            return True
    return False


def _neurag_shortcut() -> None:
    """Crea/aggiorna l'icona desktop 'NeuRAG' (best-effort, idempotente). Usa la
    copia tool-local `neurag.shortcut`: funziona anche SENZA Gray Matter (lo usa
    l'installer standalone via `neurag gui --shortcut-only`)."""
    try:
        from neurag.shortcut import ensure_desktop_shortcut
        ensure_desktop_shortcut("neurag", "NeuRAG", ["-m", "neurag.cli", "gui"],
                                "NeuRAG — control center")
    except Exception:  # noqa: BLE001 — un'icona non deve mai bloccare nulla
        pass


def _cmd_gui(shortcut_only: bool = False) -> None:
    """GUI universale: il control center è UNO (gray_matter.webgui) e ogni tool
    lo apre. Se Gray Matter manca, lo bootstrappa nello stesso venv e rilancia.
    `--shortcut-only`: crea solo l'icona desktop e esce (installer, non serve GM)."""
    if shortcut_only:
        _neurag_shortcut()
        return
    try:
        from gray_matter.webgui import main as gui_main
    except ImportError:
        if not _bootstrap_gray_matter():
            print("Install Gray Matter manually (install.ps1/install.sh), then run `neurag gui` again.")
            sys.exit(1)
        try:
            from gray_matter.webgui import main as gui_main
        except ImportError as exc:
            print(f"[gui] Gray Matter is installed but cannot be imported: {exc}")
            sys.exit(1)
    # GM ora è presente: lascia un'icona desktop "NeuRAG" → doppio click d'ora in
    # poi (punta a `neurag gui`, che riapre il control center condiviso).
    _neurag_shortcut()
    gui_main()


def _cmd_repair(args) -> None:
    """Reinstall pulito SOLO di NeuRAG: wipe selettivo (knowledge.db / config),
    poi promemoria del reinstall forzato. Non tocca Neuron/GM. Gestito PRIMA di
    aprire il DB, così funziona anche su un vault corrotto o non-Turso."""
    import os
    from neurag import db as _dbmod, settings as _settings
    if getattr(args, "json", False):
        kdb, cfgp = Path(_dbmod._DEFAULT_DB), Path(_settings._config_path())
        inst, _ = _own_installer()
        print(json_mod.dumps({
            "scope": "neurag",
            "targets": [
                {"key": "--wipe-knowledge", "label": "Knowledge NeuRAG (knowledge.db)",
                 "path": str(kdb), "exists": kdb.exists()},
                {"key": "--wipe-config", "label": "Config NeuRAG (rerank, ...)",
                 "path": str(cfgp), "exists": cfgp.exists()}],
            "reinstall": "neurag (installer -Force)",
            "installer": inst is not None}))
        return
    targets = []
    if args.wipe_knowledge:
        targets.append(("knowledge.db", _dbmod._DEFAULT_DB))
    if args.wipe_config:
        targets.append(("config NeuRAG", _settings._config_path()))
    print("NeuRAG repair - scope: NeuRAG ONLY.")
    if not targets:
        print("  nothing to delete (use --wipe-knowledge and/or --wipe-config).")
    for label, p in targets:
        p = Path(p)
        if args.dry_run:
            print(f"[dry-run] cancellerei {label}: {p}")
            continue
        try:
            if p.exists():
                p.unlink()
                print(f"[ok] {label} cancellato: {p}")
            else:
                print(f"  {label} assente: {p}")
        except OSError as exc:
            print(f"[!] could not delete {p}: {exc}")
    if args.no_reinstall:
        return
    # Auto-repair standalone (2026-07-22): NeuRAG conosce i PROPRI path — il
    # comando stampato (o lanciato con --reinstall) punta all'installer VERO.
    inst, argv_inst = _own_installer()
    if inst is None:
        print("Force-reinstall the code (bypasses the version check):")
        print("  Windows:   install.ps1 -Force        mac/Linux: ./install.sh --force")
        print("  (source not recorded: run `neurag record-paths --source <repo>`)")
        return
    if args.reinstall and not args.dry_run:
        import subprocess
        print(f"Force-reinstalling: {inst}")
        sys.exit(subprocess.call(argv_inst))
    print("Force-reinstall the code (bypasses the version check):")
    print("  " + " ".join(f'"{a}"' if " " in a else a for a in argv_inst))
    print("  (or: neurag repair --reinstall)")


def _own_installer():
    """(path, argv) dell'installer di NeuRAG in modalità force, dai PROPRI path
    (paths.source_dir()); (None, None) se non trovato.
    keep-in-sync con neuron/__main__.py `_own_installer`."""
    import os
    from neurag import paths as _paths
    src = _paths.source_dir()
    ps1, sh = src / "install.ps1", src / "install.sh"
    if os.name == "nt" and ps1.exists():
        return ps1, ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-Force"]
    if os.name != "nt" and sh.exists():
        return sh, ["sh", str(sh), "--force"]
    return None, None


def _knob_dict(k, cfg, settings) -> dict:
    """Metadati di un knob per la GUI (SSOT: vivono qui, nel tool che li possiede)."""
    d = settings.DEFAULTS[k]
    t = ("bool" if isinstance(d, bool) else "int" if isinstance(d, int)
         else "float" if isinstance(d, float) else "str")
    return {"key": k, "value": cfg.get(k), "default": d, "type": t,
            "help": getattr(settings, "HELP", {}).get(k, ""),
            "suggest": getattr(settings, "SUGGEST", {}).get(k, [])}


def _embed_change_blocked(key: str, value) -> str:
    """Refuse a model change that would strand the vault's existing vectors.

    Vectors from two models are not comparable — the cosine between them is
    noise, not a weak match. Before this, `neurag config set embed_model X`
    succeeded instantly and every stored vector silently became garbage; the
    only warning was prose in the knob's help text, which nothing enforced.
    Empty vault, unchanged value, or --force: allowed.
    """
    try:
        from neurag.db import KnowledgeGraph
        kg = KnowledgeGraph()
        try:
            embedded = kg._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        finally:
            kg.close()
    except Exception:  # noqa: BLE001 — can't open the vault: don't block config
        return ""
    if not embedded:
        return ""
    from neurag import settings
    if str(settings.get(key)) == str(value):
        return ""
    # ASCII only: this goes to a console that may be on the legacy cp1252
    # codepage, where a dash renders as mojibake (or raises).
    return (f"Refusing to change {key}: this vault holds {embedded} vector(s) built "
            f"with a different model, and vectors from two models are not "
            f"comparable - search would silently return noise.\n"
            f"  Change it and rebuild:  neurag config set {key} {value} --force "
            f"&& neurag reindex\n"
            f"  (chunk text is untouched; reindex only recomputes the vectors)")


def _cmd_reindex(as_json: bool = False) -> None:
    """Re-embed the whole vault with the active model."""
    from neurag.db import KnowledgeGraph
    kg = KnowledgeGraph()
    try:
        report = kg.reindex(say=None if as_json else (lambda s: print(s)))
    finally:
        kg.close()
    if as_json:
        print(json_mod.dumps(report))
    elif not report.get("ok"):
        print(f"reindex incompleto: {report.get('reason') or report.get('failed')} fallito/i",
              file=sys.stderr)
        sys.exit(1)


def _cmd_config(action: str, key: str = "", value=None,
                as_json: bool = False, force: bool = False) -> None:
    """Get/set/list NeuRAG knobs. Same shape as `gray-matter config` so the
    catalog-driven control center renders an identical toggle surface.
    `--json` emette i knob strutturati (value/default/type/help/suggest): la GUI
    li legge via CLI invece di importare `neurag.settings` (decoupling)."""
    from neurag import settings
    if action == "list":
        cfg = settings.load()
        if as_json:
            note = ""
            import os as _os
            if _os.environ.get("NEURAG_RERANK") is not None:
                note = ("Env NEURAG_RERANK ha la precedenza sul file "
                        f"(rerank effettivo: {'ON' if settings.rerank_enabled() else 'OFF'}).")
            print(json_mod.dumps({"knobs": [_knob_dict(k, cfg, settings)
                                            for k in sorted(settings.DEFAULTS)],
                                  "note": note}))
            return
        print("NeuRAG config (knob = valore):")
        for k in sorted(cfg):
            print(f"  {k:14} {cfg[k]}")
        if settings.rerank_enabled():
            print("  (rerank effettivo: ON)")
        return
    if action == "get":
        if not key:
            print("uso: neurag config get <key>", file=sys.stderr); sys.exit(1)
        val = settings.get(key)
        if val is None and key not in settings.DEFAULTS:
            print(f"chiave sconosciuta: {key}", file=sys.stderr); sys.exit(1)
        print(json_mod.dumps({"key": key, "value": val}) if as_json else val)
        return
    # set
    if not key or value is None:
        print("uso: neurag config set <key> <value>", file=sys.stderr); sys.exit(1)
    if key in ("embed_model", "embed_dim") and not force:
        blocked = _embed_change_blocked(key, value)
        if blocked:
            print(blocked, file=sys.stderr); sys.exit(2)
    try:
        cfg = settings.set(key, value)
    except KeyError as e:
        print(str(e), file=sys.stderr); sys.exit(1)
    if as_json:
        print(json_mod.dumps({"ok": True, "key": key, "value": cfg[key]}))
    else:
        print(f"{key} = {cfg[key]}")


def _run_via_gm(tool: str, tool_args: dict) -> bool:
    """Se Gray-Matter è vivo e gestisce NeuRAG, instrada il comando al worker
    persistente di GM (single-writer: un solo processo tiene il lock pyturso sul
    .db). Ritorna True se instradato (output già stampato); False se GM assente o
    NeuRAG è in standalone (il chiamante apre il DB in locale, dove non c'è
    conflitto di lock e KnowledgeGraph usa Turso via wheel vendorate)."""
    try:
        from gray_matter.cli import _send_ipc
        from neurag.clients import gm_still_manages
    except Exception:  # noqa: BLE001 — GM non installato: standalone puro
        return False
    try:
        if not _send_ipc({"action": "ping"}).get("gm"):
            return False
    except Exception:  # noqa: BLE001 — daemon non raggiungibile
        return False
    if not gm_still_manages("neurag"):
        return False
    try:
        r = _send_ipc({"action": "gm-neurag", "tool": tool, "args": tool_args})
    except Exception as e:  # noqa: BLE001
        print(f"neurag: GM raggiungibile ma tool fallito ({e}); riprovo in locale.",
              file=sys.stderr)
        return False
    if "error" in r:
        print(f"[gm-neurag] {tool} -> error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print(r.get("result", ""))
    return True


def main() -> None:
    """Entry point. Thin on purpose — see `_dispatch` for the actual commands.

    A corrupt vault is the one failure every command shares, and it used to
    arrive as a raw pyturso traceback naming a missing table. `VaultUnavailable`
    already carries the cause and the recovery command, so all this has to do is
    stop it from being printed as a crash."""
    from neurag.db import VaultUnavailable
    try:
        _dispatch()
    except VaultUnavailable as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


def _dispatch() -> None:
    from neurag.db import KnowledgeGraph
    from neurag.chunker import chunk_file, scan_directory

    # I chunk contengono testo arbitrario (codice, doc, CJK, frecce): su una
    # console Windows cp1252 il primo carattere fuori tabella faceva morire il
    # comando con UnicodeEncodeError. Degrada a '?' invece di perdere l'output.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if not callable(_reconfigure):   # pytest/GUI/pipe: wrapper senza reconfigure
            continue
        try:
            _reconfigure(errors="replace")
        except (OSError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args()

    # `config` is a pure settings op — handle it BEFORE opening KnowledgeGraph
    # (which loads the embedder). No DB, no model, instant.
    if args.command == "config":
        _cmd_config(args.action, args.key, args.value, args.json, args.force)
        return

    if args.command == "reindex":
        _cmd_reindex(args.json)
        return

    # repair prima del DB: deve funzionare anche su vault corrotto/non-Turso.
    if args.command == "repair":
        _cmd_repair(args)
        return

    if args.command == "record-paths":
        from neurag import paths as _paths
        d = _paths.record_self(args.source or None)
        print(f"NeuRAG paths recorded in {_paths._self_registry()}")
        print(f"  source: {d.get('source', _paths.source_dir())}")
        return

    # Lifecycle standalone: PRIMA di aprire il DB (niente embedder, niente vault).
    if args.command == "register":
        from neurag import clients as _clients
        sys.exit(_clients.cli("register", args.client, args.python_exe,
                              args.dry_run, args.force))
    if args.command == "deregister":
        from neurag import clients as _clients
        sys.exit(_clients.cli("deregister", args.client))
    if args.command == "uninstall":
        _cmd_uninstall(args.purge_data, args.json, args.yes)
        return
    if args.command == "go-standalone":
        _cmd_go_standalone(args.dry_run)
        return
    if args.command == "gui":
        _cmd_gui(args.shortcut_only)
        return
    if args.command == "start":
        _cmd_start()
        return
    if args.command == "stop":
        _cmd_stop()
        return

    # --- Single-writer via Gray-Matter -------------------------------------
    # Se GM è vivo e gestisce NeuRAG, le scritture passano dal suo worker
    # persistente (evita conflitti di lock su scritture concorrenti). Le
    # letture funzionano sempre via shared lock, anche con GM attivo.
    if args.command in ("status", "tree", "health", "query"):
        _map = {
            "status": ("knowledge_status", {}),
            "tree": ("knowledge_tree", {}),
            "health": ("knowledge_health", {}),
            "query": ("knowledge_query", {"query": getattr(args, "query", ""), "top_n": getattr(args, "top_n", 5)}),
        }
        tool, targs = _map[args.command]
        if _run_via_gm(tool, targs):
            return
    elif args.command == "add-node":
        if _run_via_gm("knowledge_add_node", {
            "name": args.name, "node_type": args.type,
            "parent_name": args.parent, "triggers": list(args.triggers),
        }):
            return
    elif args.command == "add-chunks":
        if args.file:
            chunks = json_mod.loads(Path(args.file).read_text(encoding="utf-8"))
        else:
            chunks = json_mod.loads(sys.stdin.read())
        if _run_via_gm("knowledge_add_chunks", {"node_name": args.node, "chunks": chunks}):
            return
        # Fallback standalone: GM assente -> nessun lock, apri il DB in locale.
        db = KnowledgeGraph()
        node = db.get_node_by_name(args.node)
        if not node:
            print(f"Node '{args.node}' not found.", file=sys.stderr); sys.exit(1)
        count = 0
        for c in chunks:
            db.add_chunk(node_id=node["id"], text=c["text"], source=c.get("source"),
                         section=c.get("section"), chunk_index=c.get("chunk_index", 0))
            count += 1
        s = db.status()
        print(f"Attached {count} chunks to '{args.node}'. Total: {s['chunks']} chunks.")
        return
    elif args.command == "import":
        if _run_via_gm("knowledge_import", {"mapping": args.mapping}):
            return
    elif args.command == "ingest":
        if _run_via_gm("knowledge_ingest",
                       {"path": str(Path(args.path)), "godnode": args.godnode}):
            return
    elif args.command == "rename-node":
        if _run_via_gm("knowledge_rename_node",
                       {"name": args.name, "new_name": args.new_name}):
            return
    elif args.command == "remove-node":
        if _run_via_gm("knowledge_remove_node", {"name": args.name}):
            return

    # Turso è il tier di default: KnowledgeGraph prova ad acquisirlo dalle
    # wheel (X tentativi). Le letture funzionano sempre (shared lock); le
    # scritture passano da GM quando attivo (_run_via_gm sopra).
    db = KnowledgeGraph()

    if args.command == "status":
        s = db.status()
        print(f"Engine: {s['engine']}")
        print(f"DB:     {s['db_path']}")
        if s.get("corrupt"):
            print(f"Status: DB CORRUPTED - {s['error']}")
            print(f"        → {s['hint']}")
            sys.exit(1)
        print(f"Nodes:  {s['nodes']}")
        print(f"Chunks: {s['chunks']}")
        print(f"Embedded: {s['embedded']} of {s['chunks']}")

    elif args.command == "chunk":
        path = Path(args.path)
        if not path.exists():
            print(f"Path not found: {args.path}", file=sys.stderr)
            sys.exit(1)
        chunks = []
        if path.is_file():
            chunks = chunk_file(path)
        else:
            for fp in scan_directory(path):
                chunks.extend(chunk_file(fp))
        print(json_mod.dumps([c.__dict__ for c in chunks], ensure_ascii=False, indent=2))

    elif args.command == "add-node":
        existing = db.get_node_by_name(args.name)
        if existing:
            print(f"Node '{args.name}' already exists (type={existing['node_type']}).")
            return
        parent_id = None
        if args.parent:
            parent = db.get_node_by_name(args.parent)
            if not parent:
                print(f"Parent '{args.parent}' not found.", file=sys.stderr)
                sys.exit(1)
            parent_id = parent["id"]
        node_id = db.add_node(name=args.name, node_type=args.type, parent_id=parent_id, triggers=args.triggers)
        node = db.get_node(node_id)
        print(f"Created {args.type} '{args.name}' at {node['path']}.")

    elif args.command == "add-chunks":
        node = db.get_node_by_name(args.node)
        if not node:
            print(f"Node '{args.node}' not found.", file=sys.stderr)
            sys.exit(1)
        if args.file:
            chunks = json_mod.loads(Path(args.file).read_text(encoding="utf-8"))
        else:
            chunks = json_mod.loads(sys.stdin.read())
        count = 0
        for c in chunks:
            db.add_chunk(node_id=node["id"], text=c["text"], source=c.get("source"), section=c.get("section"), chunk_index=c.get("chunk_index", 0))
            count += 1
        s = db.status()
        print(f"Attached {count} chunks to '{args.node}'. Total: {s['chunks']} chunks.")

    elif args.command == "query":
        node = db.find_node_by_trigger(args.query)
        chunks = []
        if node:
            print(f"Trigger match: {node['name']} (type={node['node_type']})")
            chunks = db.get_chunks(node["id"])
            if not chunks:
                rows = db._conn.execute("SELECT id FROM nodes WHERE parent_id = ?", (node["id"],)).fetchall()
                for r in rows:
                    chunks.extend(db.get_chunks(r["id"]))
        if not chunks:
            chunks = db.search(args.query, args.top_n, deep=args.deep)
        chunks = chunks[:args.top_n]

        if not chunks:
            print("No results." if args.deep else
                  "No results. Parked nodes are excluded — try `neurag recall`.")
            return

        if args.json:
            print(json_mod.dumps(chunks, ensure_ascii=False, indent=2, default=str))
            return

        for i, c in enumerate(chunks):
            text = c['text'][:200].replace(chr(10), ' ')
            print(f"  [{i+1}] {c['source']} :: {c['section'] or ''}")
            print(f"       {text.encode('cp1252', errors='replace').decode('cp1252')}...")
            print()

    elif args.command == "recall":
        hits = db.recall(args.query, args.top_n)
        if not hits:
            print("No results, in any layer.")
            return
        if args.json:
            print(json_mod.dumps(hits, ensure_ascii=False, indent=2, default=str))
            return
        parked = {n["id"]: n["layer"] for n in
                  (db.get_node(h["node_id"]) or {"id": 0, "layer": 2} for h in hits)}
        for i, c in enumerate(hits):
            layer = parked.get(c["node_id"], db.LAYER_ACTIVE) or db.LAYER_ACTIVE
            mark = "" if layer <= db.LAYER_ACTIVE else f"  [L{layer} dormant]"
            text = c["text"][:200].replace(chr(10), " ")
            print(f"  [{i+1}] {c['source']} :: {c['section'] or ''}{mark}")
            print(f"       {text.encode('cp1252', errors='replace').decode('cp1252')}...")
            print()

    elif args.command == "park":
        report = db.park(apply=args.apply)
        if args.json:
            print(json_mod.dumps(report, ensure_ascii=False, indent=2, default=str))
            return
        if not report["count"]:
            print("[ok] Nothing idle enough to park.")
        else:
            verb = "Parked" if report["applied"] else "Would park (dry run)"
            print(f"{verb}: {report['count']} node(s)")
            for c in report["candidates"][:40]:
                print(f"  L{c['from_layer']} -> L{c['to_layer']}  {c['path']}  "
                      f"(idle {c['idle_days']}d, max link {c['max_link_weight']})")
            if not report["applied"]:
                print("\nNothing was changed. Re-run with --apply to move them.")
                print("Parked nodes stay searchable via `neurag recall`.")
        print(f"layers: {db.layer_counts()}")

    elif args.command == "unpark":
        node = db.get_node_by_name(args.name)
        if not node:
            print(f"Node '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        db.unpark(node["id"])
        print(f"[ok] '{args.name}' back in the active vault (L2).")

    elif args.command == "confirm":
        nodes = [db.get_node_by_name(n) for n in args.names]
        missing = [n for n, node in zip(args.names, nodes) if not node]
        if missing:
            print(f"Node(s) not found: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)
        if len(nodes) < 2:
            print("confirm needs at least two nodes — a co-activation is a PAIR.",
                  file=sys.stderr)
            sys.exit(1)
        by_id = {n["id"]: n["name"] for n in nodes}
        upgraded = db.confirm([n["id"] for n in nodes])
        if args.json:
            print(json_mod.dumps({"confirmed": list(by_id.values()),
                                  "upgraded": upgraded}, ensure_ascii=False,
                                 indent=2, default=str))
            return
        print(f"[ok] confermati: {', '.join(by_id.values())}")
        if not upgraded:
            print("  nessun link promosso (cooldown, o peso già al massimo, "
                  "o nessun link tra questi nodi da rinforzare).")
        for u in upgraded:
            print(f"  {by_id.get(u['source_id'], u['source_id'])} -> "
                  f"{by_id.get(u['target_id'], u['target_id'])}: "
                  f"peso {u['weight']:.2f} (co-attivazioni {u['co_activation_count']})")

    elif args.command == "related":
        node = db.get_node_by_name(args.name)
        if not node:
            print(f"Node '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        rel = db.related_nodes(node["id"], k=args.hops, limit=args.limit,
                               deep=args.deep)
        if args.json:
            print(json_mod.dumps(rel, ensure_ascii=False, indent=2, default=str))
            return
        if not rel:
            print("Nessun nodo raggiunto. Servono link: prova `neurag "
                  "knowledge_rebuild_links` o `--deep` se i vicini sono parcheggiati."
                  if not args.deep else "Nessun nodo raggiunto.")
            return
        print(f"Da '{node['name']}', {args.hops} salti:")
        for r in rel:
            mark = "" if r["layer"] <= db.LAYER_ACTIVE else f"  [L{r['layer']} dormant]"
            print(f"  {r['activation']:.3f}  {r['path']}{mark}")

    elif args.command == "decay":
        report = db.decay()
        if args.json:
            print(json_mod.dumps(report, ensure_ascii=False, indent=2, default=str))
            return
        print(f"[ok] {report['days']} day(s) elapsed -> "
              f"{report['links']} link(s), {report['tags']} tag(s) weakened.")

    elif args.command == "tree":
        print(db.node_tree())

    elif args.command == "import":
        from neurag.importer import import_mapping
        report = import_mapping(db, args.mapping)
        print(f"Imported: {report['nodes']} nodes, {report['chunks']} chunks.")
        for s in report["skipped"]:
            print(f"  skipped: {s}")

    elif args.command == "ingest":
        from neurag.ingest import auto_ingest
        report = auto_ingest(db, args.path, args.godnode, say=print)
        if report["skipped"]:
            sys.exit(2)   # completato ma con file saltati: esito visibile in GUI

    elif args.command == "rename-node":
        node = db.get_node_by_name(args.name)
        if not node:
            print(f"Node '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        db.rename_node(node["id"], args.new_name)
        print(f"[ok] '{args.name}' → '{args.new_name}' (path aggiornati).")

    elif args.command == "remove-node":
        node = db.get_node_by_name(args.name)
        if not node:
            print(f"Node '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        n = db.delete_node(node["id"])
        print(f"[ok] deleted {n} nodes (subtree included).")

    elif args.command == "health":
        h = db.health()
        if h.get("corrupt"):
            print("Vault health: DB CORROTTO")
            print(f"  error: {h['error']}")
            print(f"  → {h['hint']}")
            sys.exit(1)
        print("Vault health:", "OK" if h["ok"] else f"{h['serious_count']} serious issue(s)")
        for k, v in h["issues"].items():
            if v:
                print(f"  [issue] {k}: {len(v)}")
        for k, v in h["warnings"].items():
            n = v if isinstance(v, int) else len(v)
            if n:
                print(f"  [warn]  {k}: {n}")

    elif args.command == "doctor":
        from neurag import __version__
        from neurag import db as _dbmod
        s = db.status()
        print(f"NeuRAG v{__version__}")
        print(f"  engine:   {s['engine']}")
        if _dbmod.REMOTE_TURSO:
            print("  turso:    cloud configured (NEURAG_TURSO_DATABASE_URL)")
        elif _dbmod.TURSO_AVAILABLE:
            print("  turso:    local engine available (pyturso) — native vector SQL")
        else:
            print("  turso:    not importable — install with: pip install \"neurag[turso]\"")
        turso_errs = s.get("turso_errors", [])
        if turso_errs:
            print("  turso:    install errors:")
            for e in turso_errs:
                print(f"              - {e}")
        emb = s["embedder"]
        hint = "" if emb == "fastembed" else "  (lexical TF-IDF; pip install \"neurag[semantic]\" for vectors)"
        print(f"  embedder: {emb}{hint}")
        rr = s.get("reranker", "null")
        print(f"  reranker: {'OFF' if rr == 'null' else 'ON (' + rr + ')'}"
              "  (neurag config set rerank on)")
        print(f"  db:       {s['db_path']}")
        if s.get("corrupt"):
            print(f"  content:  DB CORROTTO — {s['error']}")
            print(f"            → {s['hint']}")
        else:
            print(f"  content:  {s['nodes']} nodes, {s['chunks']} chunks, {s['embedded']} embedded")
        try:
            import gray_matter  # noqa: F401
            print("  gateway:  Gray-Matter present (fronts NeuRAG)")
        except ImportError:
            print("  gateway:  standalone (Gray-Matter not installed)")
        h = db.health()
        print("  vault:    " + ("OK" if h["ok"] else f"{h['serious_count']} serious issue(s)"))


if __name__ == "__main__":
    main()
