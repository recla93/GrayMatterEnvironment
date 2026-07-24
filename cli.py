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

    sub.add_parser("tree", help="Show node hierarchy")

    imp = sub.add_parser("import", help="Bulk-import a folder tree from a YAML mapping")
    imp.add_argument("mapping", help="Path to the YAML mapping file")

    ing = sub.add_parser("ingest",
                         help="Grafizza una cartella: nodi dalla struttura, chunk, embedding, link")
    ing.add_argument("path", help="Cartella da grafizzare")
    ing.add_argument("--godnode", default=None,
                     help="Nodo radice da usare/creare (default: nome della cartella)")

    ren = sub.add_parser("rename-node", help="Rinomina un nodo (aggiorna anche i path dei figli)")
    ren.add_argument("name", help="Nome attuale del nodo")
    ren.add_argument("new_name", help="Nuovo nome")

    rem = sub.add_parser("remove-node", help="Elimina un nodo e tutto il suo sottoalbero")
    rem.add_argument("name", help="Nome del nodo da eliminare")

    sub.add_parser("health", help="Structural audit of the vault (integrity check)")

    sub.add_parser("doctor", help="Environment + vault health snapshot (tier, embedder, gateway)")

    cfg_p = sub.add_parser("config",
                           help="Get/set tunable knobs (rerank on/off, rerank pool, ...)")
    cfg_p.add_argument("action", choices=["get", "set", "list"])
    cfg_p.add_argument("key", nargs="?", default="")
    cfg_p.add_argument("value", nargs="?", default=None)
    cfg_p.add_argument("--json", action="store_true",
                       help="Output JSON strutturato (usato dal control center)")

    rep = sub.add_parser("repair",
                         help="Reinstall pulito SOLO di NeuRAG (standalone, senza GM): scegli cosa cancellare, poi reinstalla forzato")
    rep.add_argument("--wipe-knowledge", action="store_true", help="cancella knowledge.db")
    rep.add_argument("--wipe-config", action="store_true", help="cancella il config NeuRAG (rerank, ...)")
    rep.add_argument("--no-reinstall", action="store_true",
                     help="solo pulizia, non reinstallare il codice")
    rep.add_argument("--reinstall", action="store_true",
                     help="lancia subito il PROPRIO installer con --force (dai path registrati)")
    rep.add_argument("--dry-run", action="store_true", help="mostra, non tocca nulla")
    rep.add_argument("--json", action="store_true",
                     help="elenca le superfici cancellabili in JSON (usato dal control center)")

    rpx = sub.add_parser("record-paths",
                         help="NeuRAG registra la sua cartella sorgente (usato dall'installer)")
    rpx.add_argument("--source", default="", help="Cartella sorgente di NeuRAG (repo)")

    reg = sub.add_parser("register",
                         help="Registra il server MCP di NeuRAG nei client AI (standalone, senza GM)")
    reg.add_argument("--client", default="all",
                     help="claude-desktop|claude-code|cursor|vscode|opencode|all (default: all)")
    reg.add_argument("--python", dest="python_exe", default="",
                     help="Python del server (default: il venv installato)")
    reg.add_argument("--dry-run", action="store_true", help="mostra, non scrive nulla")
    reg.add_argument("--force", action="store_true",
                     help="registra diretto anche se GM ti gestisce ancora (doppia registrazione)")

    der = sub.add_parser("deregister",
                         help="Rimuove NeuRAG dai config dei client AI")
    der.add_argument("--client", default="all",
                     help="claude-desktop|claude-code|cursor|vscode|opencode|all (default: all)")

    der.add_argument("--json", action="store_true", help="output as JSON")

    uni = sub.add_parser("uninstall",
                         help="Uninstall: deregister from clients, optionally purge data")
    uni.add_argument("--purge-data", action="store_true", help="also delete knowledge.db")
    uni.add_argument("--json", action="store_true", help="output JSON for webgui integration")
    uni.add_argument("--yes", action="store_true", help="non-interactive: assume yes for prompts")

    gst = sub.add_parser("go-standalone",
                         help="NeuRAG esce dal gateway GM: si registra come MCP diretto nei client "
                              "e chiede a GM (se presente) di non gestirlo più. Reversibile con "
                              "`gray-matter register --gateway`")
    gst.add_argument("--dry-run", action="store_true", help="mostra, non scrive nulla")

    gui_p = sub.add_parser("gui",
                   help="Apre il control center (GUI condivisa Gray Matter; se GM manca, la installa)")
    gui_p.add_argument("--shortcut-only", action="store_true",
                       help="crea solo l'icona desktop e esce (usato dall'installer)")

    sub.add_parser("start", help="Avvia il server NeuRAG in background (MCP stdio)")
    sub.add_parser("stop", help="Ferma il server NeuRAG")

    return parser


# GUI: gruppo di appartenenza di ogni comando, dal più grande al più piccolo.
COMMAND_GROUPS = {
    "status": "inspect", "tree": "inspect", "query": "inspect",
    "health": "inspect", "doctor": "inspect",
    "chunk": "maintenance", "add-node": "maintenance",
    "add-chunks": "maintenance", "import": "maintenance",
    "ingest": "maintenance", "rename-node": "maintenance",
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
        print("  [dry-run] non chiedo a GM di rilasciare NeuRAG.")
        return
    try:
        from gray_matter import clients as _gm_clients
        for line in _gm_clients.release_tool("neurag"):
            print("  " + line)
    except ImportError:
        print("  Gray Matter non installato: NeuRAG era già standalone.")
    print("Fatto. Riavvia le app AI. Per tornare al gateway: gray-matter register --gateway")


def _cmd_uninstall(purge_data: bool = False, as_json: bool = False, yes: bool = False) -> None:
    """Uninstall NeuRAG: deregister from clients, optionally purge data."""
    from neurag.clients import deregister_all as _dereg_all
    from neurag.clients import SLUG
    if as_json:
        dereg_results = [{"client": r.client, "ok": r.ok, "action": r.action,
                        "detail": r.detail} for r in _dereg_all(SLUG)]
        out = {"scope": "neurag", "deregister": dereg_results, "data_purged": False}
        print(json_mod.dumps(out, ensure_ascii=False))
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
                print(f"NeuRAG server già in esecuzione (PID {pid}).")
                return
        except (ValueError, OSError):
            pass  # PID file corrotto: ignora, sovrascriverà

    cmd = [sys.executable, "-m", "neurag.server"]
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except FileNotFoundError as exc:
        print(f"Impossibile avviare: {exc}", file=sys.stderr)
        sys.exit(1)

    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(1.0)
    if proc.poll() is not None:
        print(f"NeuRAG server è fallito subito (exit {proc.returncode}).")
        pid_file.unlink(missing_ok=True)
        sys.exit(1)
    print(f"NeuRAG server avviato (PID {proc.pid})")


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
        print("NeuRAG server non in esecuzione (nessun file PID).")
        return
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        print("File PID corrotto.")
        pid_file.unlink(missing_ok=True)
        return
    if not _is_alive(pid):
        print(f"NeuRAG server non attivo (PID {pid} non trovato).")
        pid_file.unlink(missing_ok=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(f"Processo {pid} già terminato.")
    except PermissionError:
        print(f"Permesso negato per PID {pid}.")
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
        print(f"[gui] Gray Matter non è installato: lo installo ({label})…")
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
            print("Installa Gray Matter a mano (install.ps1/install.sh), poi rilancia `neurag gui`.")
            sys.exit(1)
        try:
            from gray_matter.webgui import main as gui_main
        except ImportError as exc:
            print(f"[gui] Gray Matter installato ma non importabile: {exc}")
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
    print("NeuRAG repair — scope: SOLO NeuRAG.")
    if not targets:
        print("  niente da cancellare (usa --wipe-knowledge e/o --wipe-config).")
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
            print(f"[!] impossibile cancellare {p}: {exc}")
    if args.no_reinstall:
        return
    # Auto-repair standalone (2026-07-22): NeuRAG conosce i PROPRI path — il
    # comando stampato (o lanciato con --reinstall) punta all'installer VERO.
    inst, argv_inst = _own_installer()
    if inst is None:
        print("Reinstall forzato del codice (bypassa il check versione):")
        print("  Windows:   install.ps1 -Force        mac/Linux: ./install.sh --force")
        print("  (sorgente non registrato: lancia `neurag record-paths --source <repo>`)")
        return
    if args.reinstall and not args.dry_run:
        import subprocess
        print(f"Reinstall forzato: {inst}")
        sys.exit(subprocess.call(argv_inst))
    print("Reinstall forzato del codice (bypassa il check versione):")
    print("  " + " ".join(f'"{a}"' if " " in a else a for a in argv_inst))
    print("  (oppure: neurag repair --reinstall)")


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


def _cmd_config(action: str, key: str = "", value=None,
                as_json: bool = False) -> None:
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
        print(f"[gm-neurag] {tool} -> errore: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print(r.get("result", ""))
    return True


def main() -> None:
    from neurag.db import KnowledgeGraph
    from neurag.chunker import chunk_file, scan_directory

    parser = build_parser()
    args = parser.parse_args()

    # `config` is a pure settings op — handle it BEFORE opening KnowledgeGraph
    # (which loads the embedder). No DB, no model, instant.
    if args.command == "config":
        _cmd_config(args.action, args.key, args.value, args.json)
        return

    # repair prima del DB: deve funzionare anche su vault corrotto/non-Turso.
    if args.command == "repair":
        _cmd_repair(args)
        return

    if args.command == "record-paths":
        from neurag import paths as _paths
        d = _paths.record_self(args.source or None)
        print(f"NeuRAG paths registrati in {_paths._self_registry()}")
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
            print(f"Stato:  DB CORROTTO — {s['error']}")
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
            chunks = db.search(args.query, args.top_n)
        chunks = chunks[:args.top_n]

        if not chunks:
            print("No results.")
            return

        if args.json:
            print(json_mod.dumps(chunks, ensure_ascii=False, indent=2, default=str))
            return

        for i, c in enumerate(chunks):
            text = c['text'][:200].replace(chr(10), ' ')
            print(f"  [{i+1}] {c['source']} :: {c['section'] or ''}")
            print(f"       {text.encode('cp1252', errors='replace').decode('cp1252')}...")
            print()

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
            print(f"Nodo '{args.name}' non trovato.", file=sys.stderr)
            sys.exit(1)
        db.rename_node(node["id"], args.new_name)
        print(f"[ok] '{args.name}' → '{args.new_name}' (path aggiornati).")

    elif args.command == "remove-node":
        node = db.get_node_by_name(args.name)
        if not node:
            print(f"Nodo '{args.name}' non trovato.", file=sys.stderr)
            sys.exit(1)
        n = db.delete_node(node["id"])
        print(f"[ok] eliminati {n} nodi (sottoalbero incluso).")

    elif args.command == "health":
        h = db.health()
        if h.get("corrupt"):
            print("Vault health: DB CORROTTO")
            print(f"  errore: {h['error']}")
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
