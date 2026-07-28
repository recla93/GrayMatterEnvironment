"""Gray-Matter CLI: start, stop, status, logs."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path

from gray_matter import __version__

# Endpoint IPC del daemon. Duplicati (e non importati da `server`) di
# proposito: importare `gray_matter.server` qui trascinava `mcp` e l'intero
# server dentro OGNI processo che tocca la CLI — GUI compresa. Se `mcp`
# mancava nel processo GUI, il catalogo risultava "illeggibile" e nessun
# pulsante funzionava. `server.py` importa questi valori da qui (SSOT).
GRAY_MATTER_HOST = "127.0.0.1"
GRAY_MATTER_PORT = 9876          # porta PREFERITA (non più fissa: vedi sotto)
GRAY_MATTER_PORT_SPAN = 40       # quante porte scandire se la preferita è occupata

# Porta DINAMICA (2026-07-22): 9876 era fissa e faceva anche da singleton. Se
# un'ALTRA app la occupava, GM non partiva mai. Ora il daemon prova 9876 e, se
# è presa da un processo estraneo, scala alla prima libera; la porta scelta va
# in un rendezvous file che i client leggono per "seguire" il daemon. Il
# singleton resta: se su quella porta risponde GIÀ un GM, il nuovo esce.

def _port_file() -> "Path":
    from gray_matter import paths as _paths
    return _paths.gm_home() / "port"


def resolve_port() -> int:
    """La porta su cui il daemon è (o sarà) — dal rendezvous file, else preferita."""
    try:
        return int(_port_file().read_text(encoding="utf-8").strip())
    except Exception:  # noqa: BLE001 — assente/illeggibile: usa la preferita
        return GRAY_MATTER_PORT


def write_port_file(port: int) -> None:
    try:
        p = _port_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(port), encoding="utf-8")
    except OSError:
        pass


def clear_port_file() -> None:
    try:
        _port_file().unlink(missing_ok=True)
    except OSError:
        pass


def port_is_free(host: str, port: int) -> bool:
    """True se possiamo fare bind di (host, port) adesso (nessuno la tiene)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from sock, or return b'' on short/failed read.

    recv() returns whatever has ARRIVED, not what was asked for: any response
    bigger than one TCP segment (~1.4 KB — `status` with the full tool lists,
    `bridges`, `logs`, every gm-neuron/gm-neurag result) came back truncated
    and json.loads blew up with a raw traceback. `server.py` grew this loop
    when the IPC framing was fixed; the CLI side kept the single-recv version.
    Now there is one copy, here (the IPC SSOT), and server.py imports it.
    """
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return buf


def gm_answers(host: str, port: int, timeout: float = 0.4) -> bool:
    """True se su (host, port) risponde un Gray-Matter (probe `ping`)."""
    try:
        payload = json.dumps({"action": "ping"}).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            s.sendall(struct.pack("!I", len(payload)) + payload)
            hdr = _recv_exact(s, 4)
            if not hdr:
                return False
            (n,) = struct.unpack("!I", hdr)
            resp = json.loads(_recv_exact(s, n).decode("utf-8"))
            return bool(resp.get("gm"))
    except Exception:  # noqa: BLE001 — refused/timeout/garbage = non è GM
        return False


# Le risposte a `status`/`bridges`/`logs` sono immediate; una chiamata a un tool
# (gm-neuron/gm-neurag) passa dal worker e, col modello di embedding freddo,
# paga i 3-5s del primo caricamento — con il vecchio timeout fisso a 3s il primo
# gm-neuron falliva SEMPRE con "timed out".
IPC_TIMEOUT = 3.0
IPC_TOOL_TIMEOUT = 60.0


def _send_ipc(data: dict, timeout: float = IPC_TIMEOUT) -> dict:
    """Send a JSON IPC message to the local Gray-Matter process."""
    payload = json.dumps(data).encode("utf-8")
    length = struct.pack("!I", len(payload))
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((GRAY_MATTER_HOST, resolve_port()))
            s.sendall(length + payload)
            hdr = _recv_exact(s, 4)
            if not hdr:
                return {"error": "no response"}
            resp_len = struct.unpack("!I", hdr)[0]
            if resp_len <= 0 or resp_len > 1_000_000:
                return {"error": "invalid response length"}
            resp_data = _recv_exact(s, resp_len)
            if not resp_data:
                return {"error": "incomplete response"}
            return json.loads(resp_data.decode("utf-8"))
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        return {"error": str(e)}
    except (struct.error, UnicodeDecodeError, json.JSONDecodeError) as e:
        return {"error": f"malformed response: {e}"}


def cmd_status() -> None:
    result = _send_ipc({"action": "status"})
    if "error" in result:
        print(f"Gray-Matter not running ({result['error']}).")
        sys.exit(1)
    print(f"Gray-Matter v{__version__}")
    print(f"Servers: {len(result)}")
    for name, info in result.items():
        status = info.get("status", "unknown")
        tools = ", ".join(info.get("tool_names", []))
        pid = info.get("pid", "?")
        collab = "collab" if info.get("collaborative", True) else "ISOLATED"
        print(f"  {name} ({status}, {collab}) pid={pid} tools=[{tools}]")


def cmd_stats() -> None:
    r = _send_ipc({"action": "stats"})
    if "error" in r:
        print(f"Gray-Matter not running ({r['error']}).")
        sys.exit(1)
    print("Gray-Matter stats:")
    order = ["pulses", "cache_hits", "cache_misses", "cache_hit_rate", "cache_size",
             "flashes", "bridges_added_session", "bridges_total", "avg_miss_ms",
             "workers_alive"]
    for k in order:
        if k in r:
            print(f"  {k:22} {r[k]}")


def cmd_doctor() -> None:
    r = _send_ipc({"action": "doctor"})
    if "error" in r:
        print(f"Gray-Matter not running ({r['error']}).")
        sys.exit(1)
    print(f"Gray-Matter v{r.get('version')} — {'sleeping' if r.get('sleeping') else 'awake'}")
    print(f"  cache: {r.get('cache_size')} entries | bridges: {r.get('bridges_total')}")
    servers = r.get("servers", [])
    if not servers:
        print("  (no servers registered)")
    for s in servers:
        mark = "ok" if s.get("alive") else "DEAD"
        collab = "collab" if s.get("collaborative") else "ISOLATED"
        worker = "worker+" if s.get("worker") else "worker-"
        print(f"  [{mark}] {s['name']} ({s.get('status')}, {collab}) {worker}")
    tiers = r.get("tiers") or {}
    if tiers:
        print("  tiers: " + " | ".join(f"{k}: {v}" for k, v in tiers.items()))
    if "cross_store" in r:
        print("  cross-store (bridges): " +
              ("ACTIVE" if r["cross_store"]
               else "inactive — serve neuron+neurag vivi e collaborativi"))
    if r.get("neurag_engine") == "sqlite":
        print("  [!!] NeuRAG vector tier DEGRADED (sqlite3, Python cosine) — "
              "full tier: pip install neurag[turso]  (wheels in Neuron/vendor)")
    _report_processes()


def _report_processes() -> None:
    """Processi della suite ancora vivi, e quali hanno perso il genitore.

    Era il buco di INSTALLER-UX §7: il registro dei PID non veniva scritto da
    nessuno, quindi `doctor` non poteva accorgersi di niente e i server
    restavano indietro a ogni riavvio di un client — più writer sullo stesso
    store, che è esattamente il rischio di clobber di L1/L2.
    """
    try:
        from gray_matter import pids as _pids
        live, orphans = _pids.tracked(), _pids.orphans()
    except Exception as exc:  # noqa: BLE001
        print(f"  processes: registry unreadable ({exc})")
        return
    if not live:
        print("  processes: none tracked")
        return
    roles: dict = {}
    for e in live:
        roles[e.get("role", "?")] = roles.get(e.get("role", "?"), 0) + 1
    print("  processes: " + ", ".join(f"{n}x {r}" for r, n in sorted(roles.items())))
    if orphans:
        print(f"  [!!] {len(orphans)} orphan(s) — the process that launched them "
              "is gone, but they still hold the store:")
        for e in orphans:
            print(f"       pid {e['pid']} ({e.get('role', '?')})")
        print("       clean them up with:  gray-matter reap")


def cmd_reap(dry_run: bool = False, all_procs: bool = False) -> None:
    """Termina i processi della suite rimasti indietro.

    Default: SOLO gli orfani, cioè quelli il cui genitore non esiste più. I
    server che stanno servendo un client AI vivo non si toccano — è la
    differenza fra una pulizia e un piede nella porta. `--all` li prende tutti
    (ma non se stessi), per quando si vuole davvero ripartire da zero.
    """
    import subprocess          # locale come altrove in questo modulo
    from gray_matter import pids as _pids
    targets = _pids.tracked() if all_procs else _pids.orphans()
    targets = [e for e in targets if e["pid"] != os.getpid()]
    if not targets:
        print("Nothing to reap: no orphan processes." if not all_procs
              else "Nothing to reap: no tracked processes.")
        return
    for e in targets:
        label = f"pid {e['pid']} ({e.get('role', '?')})"
        if dry_run:
            print(f"  [dry-run] would terminate {label}")
            continue
        try:
            if os.name == "nt":
                # /T: anche l'albero — il redirector del venv e il processo
                # vero sono due PID, e uccidere solo il padre lascia in giro
                # proprio quello che tiene aperto il DB.
                subprocess.run(["taskkill", "/PID", str(e["pid"]), "/T", "/F"],
                               capture_output=True, timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os.kill(e["pid"], signal.SIGTERM)
            _pids.forget(e["pid"])
            print(f"  terminated {label}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] could not terminate {label}: {exc}")
    print(f"Reaped {len(targets)} process(es).")


def _knob_dict(k, cfg, settings) -> dict:
    """Metadati di un knob per la GUI (SSOT: vivono nel tool che li possiede)."""
    d = settings.DEFAULTS[k]
    t = ("bool" if isinstance(d, bool) else "int" if isinstance(d, int)
         else "float" if isinstance(d, float) else "str")
    return {"key": k, "value": cfg.get(k), "default": d, "type": t,
            "help": getattr(settings, "HELP", {}).get(k, ""),
            "suggest": getattr(settings, "SUGGEST", {}).get(k, [])}


def cmd_config(action: str, key: str = "", value=None,
               as_json: bool = False) -> None:
    """`--json` emette i knob strutturati (value/default/type/help/suggest): la
    GUI li legge via CLI invece di importare `gray_matter.settings` (decoupling)."""
    from gray_matter import settings
    if action == "list":
        cfg = settings.load()
        if as_json:
            print(json.dumps({"knobs": [_knob_dict(k, cfg, settings)
                                        for k in sorted(settings.DEFAULTS)],
                              "note": ""}))
            return
        print("Gray-Matter config (knob = valore):")
        for k in sorted(cfg):
            print(f"  {k:22} {cfg[k]}")
        return
    if action == "get":
        if not key:
            print("uso: gray-matter config get <key>"); sys.exit(1)
        val = settings.get(key)
        if val is None:
            print(f"chiave sconosciuta: {key}"); sys.exit(1)
        print(json.dumps({"key": key, "value": val}) if as_json else val)
        return
    # set
    if not key or value is None:
        print("uso: gray-matter config set <key> <value>"); sys.exit(1)
    try:
        cfg = settings.set(key, value)
    except KeyError as e:
        print(str(e)); sys.exit(1)
    if as_json:
        print(json.dumps({"ok": True, "key": key, "value": cfg[key]}))
    else:
        print(f"{key} = {cfg[key]}")


def cmd_stop() -> None:
    result = _send_ipc({"action": "shutdown"})
    if "error" in result:
        print(f"Gray-Matter not running ({result['error']}).")
        sys.exit(1)
    print("Gray-Matter stopped.")


def cmd_start() -> None:
    from gray_matter.server import _spawn_gray_matter, _is_gray_matter_running
    if _is_gray_matter_running():
        print("Gray-Matter already running.")
        return
    _spawn_gray_matter()
    for _ in range(30):          # up to ~3s for the daemon to bind :9876 (cold Python start)
        time.sleep(0.1)
        if _is_gray_matter_running():
            print("Gray-Matter started.")
            return
    print("Failed to start Gray-Matter.")
    sys.exit(1)


def cmd_ping() -> None:
    from gray_matter.server import _is_gray_matter_running
    if _is_gray_matter_running():
        print("Gray-Matter is running.")
    else:
        print("Gray-Matter is not running.")
        sys.exit(1)


def _not_running(r: dict) -> bool:
    if "error" in r:
        print(f"Gray-Matter not running ({r['error']}).")
        return True
    return False


def cmd_isolate(name: str) -> None:
    r = _send_ipc({"action": "isolate", "name": name})
    if _not_running(r):
        return
    print(f"Isolated '{name}': out of the combined pulse, still callable directly."
          if r.get("status") == "ok" else f"No such server: {name}.")


def cmd_collaborate(name: str) -> None:
    r = _send_ipc({"action": "collaborate", "name": name})
    if _not_running(r):
        return
    print(f"'{name}' back in the combined pulse."
          if r.get("status") == "ok" else f"No such server: {name}.")


def cmd_mode(mode: str) -> None:
    r = _send_ipc({"action": "mode", "mode": mode})
    if _not_running(r):
        return
    print(f"Mode: {mode} (all servers).")


def cmd_register(gateway: bool = False) -> None:
    """Register every installed trio server in the detected MCP clients.

    --gateway: proxy model — register ONLY gray-matter, evict neuron/neurag
    (GM self-bootstraps them as managed workers)."""
    from gray_matter import clients
    servers = ["gray-matter"] if gateway else clients.installed_servers()
    if not servers:
        print("No installed servers to register (install one first).")
        return
    verb = "Gateway flip: registering" if gateway else "Registering"
    print(f"{verb} {', '.join(servers)} in detected MCP clients...")
    if gateway:
        # Round-trip del go-standalone: tornare al gateway riprende in gestione
        # TUTTI i tool (azzera la lista unmanaged) ed evict le entry dirette.
        clients.clear_unmanaged()
    for r in clients.register(servers, gateway=gateway):
        mark = "OK" if r.get("ok") else ("--" if r.get("action") == "skipped" else "!!")
        line = f"  [{mark}] {r['client']}: {r['action']}"
        if r.get("detail"):
            line += f" — {r['detail']}"
        print(line)
        if r.get("snippet"):
            print("       add by hand:")
            for ln in r["snippet"].splitlines():
                print("         " + ln)
    print("Done. Restart your AI apps to load the servers.")


def cmd_deregister(tool: str) -> None:
    """Deregister per-tool (go-standalone lato GM): evict `tool` dal gateway
    (GM smette di gestirlo) e triggera la SUA registrazione MCP diretta nei
    client. Reversibile: `gray-matter register --gateway` riprende tutto."""
    from gray_matter import clients
    tools = ["neuron", "neurag"] if tool == "all" else [tool]
    for t in tools:
        print(f"— {t} → standalone:")
        for ln in clients.standalone_register_tool(t):
            print("  " + ln)
        for ln in clients.release_tool(t):
            print("  " + ln)
    print("Done. Restart your AI apps. Back to the gateway: gray-matter register --gateway")


# Slug delle entry MCP DIRETTE per tool (da togliere quando torna sotto gateway).
_LINK_TOOL_SLUGS = {"neuron": ["neuron", "neuron5"], "neurag": ["neurag"]}
_LINK_TOOLS = ("neuron", "neurag")


def cmd_link(tools: "list[str] | None" = None, list_only: bool = False,
             as_json: bool = False, dry_run: bool = False) -> None:
    """Ri-aggancia al gateway i tool andati standalone — l'INVERSO di
    `deregister`/go-standalone (NON è "aggiungere config": è "GM torna a
    gestirli"). GM riprende a spawnarli e a ripubblicarne i tool; l'entry MCP
    DIRETTA del tool sparisce dai client (resta solo `gray-matter`). `--list`
    mostra lo stato; senza tool ricollega TUTTI gli standalone installati."""
    from gray_matter import clients
    installed = set(clients.installed_servers())
    unmanaged = clients.unmanaged_tools()
    if list_only:
        items = [{"key": t, "label": t, "installed": t in installed,
                  "managed": (t in installed) and (t not in unmanaged),
                  "standalone": (t in installed) and (t in unmanaged)}
                 for t in _LINK_TOOLS]
        if as_json:
            print(json.dumps({"tools": items}))
            return
        print("Gateway status per tool:")
        for it in items:
            st = ("non installato" if not it["installed"]
                  else "STANDALONE — ricollegabile" if it["standalone"]
                  else "già gestito da GM")
            print(f"  {it['key']:8} {st}")
        return
    sel = [t for t in (tools or sorted(unmanaged & installed)) if t in _LINK_TOOLS]
    linked, skipped = [], []
    for t in sel:
        if t not in installed:
            skipped.append({"tool": t, "reason": "non installato"})
        elif t not in unmanaged:
            skipped.append({"tool": t, "reason": "già gestito da GM"})
        else:
            if not dry_run:
                clients.set_unmanaged(t, False)
            linked.append(t)
    # Riporta l'entry gateway `gray-matter` (senza evict globale) e toglie SOLO le
    # entry dirette dei tool ricollegati — gli altri standalone restano intatti.
    reg, dereg = [], []
    if linked and not dry_run:
        reg = clients.register(["gray-matter"])
        drop = [s for t in linked for s in _LINK_TOOL_SLUGS.get(t, [t])]
        dereg = clients.deregister(drop) if drop else []
    if as_json:
        print(json.dumps({"linked": linked, "skipped": skipped, "dry_run": dry_run}))
        return
    prefix = "[dry-run] " if dry_run else ""
    if not linked:
        detail = "; ".join(f"{s['tool']}: {s['reason']}" for s in skipped)
        print(f"{prefix}No tool re-linked{(' (' + detail + ')') if detail else ''}.")
        return
    print(f"{prefix}Re-linked to the gateway: {', '.join(linked)}")
    for r in reg + dereg:
        mark = "OK" if r.get("ok") else ("--" if r.get("action") == "skipped" else "!!")
        print(f"  [{mark}] {r.get('client')}: {r.get('action')}")
    if not dry_run:
        print("Done. Restart your AI apps (the daemon picks the managed workers back up).")


def _print_results(results: list) -> None:
    for r in results:
        mark = "OK" if r.get("ok") else "!!"
        line = f"  [{mark}] {r['action']}"
        for key in ("component", "client", "name", "path", "detail"):
            if isinstance(r.get(key), str):
                line += f" {r[key]}" if key != "detail" else f" — {r[key]}"
        print(line)
        for s in (r.get("clients") if isinstance(r.get("clients"), list) else []):
            smark = "OK" if s.get("ok") else ("--" if s.get("action") == "skipped" else "!!")
            print(f"       [{smark}] {s.get('client')}: {s.get('action')}"
                  + (f" — {s['detail']}" if s.get("detail") else ""))


def cmd_install(dry_run: bool = False) -> None:
    """Idempotent install: reap orphans, ensure data dirs, register ONLY the
    gateway, deploy per-client hooks, write manifest (INSTALLER-UX §5)."""
    from gray_matter import executor
    print(("[dry-run] " if dry_run else "") + "Installing (gateway model)...")
    _print_results(executor.execute_install(dry_run=dry_run))
    print("Done." + ("" if dry_run else " Restart your AI apps."))


def _uninstall_targets() -> dict:
    """Superfici rimovibili di GM + il loro stato reale (per il pannello GUI).
    SSOT: vive qui, GM possiede questi path."""
    from gray_matter import paths
    manifest = paths.Manifest.load().data if paths.manifest_path().exists() else {}
    clients_list = manifest.get("clients") or []
    targets = [
        {"key": "hooks", "label": "Hook nei client",
         "path": "(configurazioni client)", "exists": bool(clients_list)},
        {"key": "code", "label": "Codice Gray Matter",
         "path": str(paths.app_dir()), "exists": paths.app_dir().exists()},
    ]
    data = [{"key": n, "name": n.replace("_", " "), "path": str(p), "exists": p.exists()}
            for n, p in [("neuron_graphs", paths.neuron_graphs()),
                         ("neurag_db", paths.neurag_db()),
                         ("gm_bridges", paths.gm_bridges()),
                         ("neurag_config", paths.neurag_config())]]
    return {"scope": "gray-matter", "targets": targets, "data": data}


def _verify_uninstall() -> dict:
    """Accerta che GM sia davvero sparito: file rimossi + deregistrato dai client."""
    from gray_matter import paths, clients as _clients
    checks = {
        "app_dir": not paths.app_dir().exists(),
        "manifest": not paths.manifest_path().exists(),
        "config": not paths.config_file().exists(),
        "logs": not paths.logs_dir().exists(),
        "pids": not paths.pids_path().exists(),
    }
    for entry in _clients.doctor():
        for slug in ("neuron", "neuron5", "neurag", "gray-matter"):
            checks[f"deregistered_{entry['client']}_{slug}"] = \
                slug not in entry.get("servers", [])
    return {"ok": all(checks.values()), "checks": checks}


def cmd_uninstall(purge_data: bool = False, yes: bool = False,
                  dry_run: bool = False, list_only: bool = False,
                  as_json: bool = False) -> None:
    """Uninstall: reap, deregister, remove hooks/code; memory is INTERACTIVE
    (asks per data path) unless --purge-data (INSTALLER-UX §6). `--list` elenca le
    superfici; `--json` emette JSON (usato dal control center: esito + verifica)."""
    from gray_matter import executor
    if list_only:
        if as_json:
            print(json.dumps(_uninstall_targets()))
        else:
            t = _uninstall_targets()
            print("Removable surfaces:")
            for x in t["targets"] + t["data"]:
                print(f"  {'•' if x['exists'] else '·'} {x.get('label') or x.get('name')}"
                      f"  [{x['path']}]")
        return
    results = executor.execute_uninstall(
        purge_data=purge_data, assume_yes=(yes or as_json), dry_run=dry_run)
    if as_json:
        verification = {"ok": True, "checks": {}} if dry_run else _verify_uninstall()
        print(json.dumps({"ok": verification["ok"], "results": results,
                          "verification": verification}))
        return
    print(("[dry-run] " if dry_run else "") + "Uninstalling...")
    _print_results(results)
    print("Done.")


def cmd_repair(wipe: "list[str] | None" = None, dry_run: bool = False,
               as_json: bool = False, reinstall: bool = False) -> None:
    """Clean repair: wipe ONLY the chosen data surfaces, then remind to force a
    code reinstall. `list` prints what's present + its key; nothing is removed
    without an explicit key in `wipe` (INSTALLER-UX — keep vs remove is the user's).
    `--json` elenca le superfici (per la GUI); `--reinstall` lancia la suite -Force."""
    from gray_matter import executor
    from gray_matter import paths as _paths
    wipe = wipe or []
    if as_json:
        print(json.dumps({
            "scope": "gray-matter",
            "targets": executor.repair_targets("gray-matter"),
            "reinstall": "suite (installer -Force)",
            "installer": _paths.installer_script() is not None}))
        return
    if wipe == ["list"] or wipe == ["--list"]:
        print("Elementi presenti (chiave → percorso):")
        for t in executor.repair_targets():
            mark = "•" if t["exists"] else "·"
            print(f"  {mark} {t['key']:14} {t['label']}  [{t['path']}]"
                  f"{'' if t['exists'] else '  (assente)'}")
        print("\nUso: gray-matter repair <chiave> [<chiave> ...] [--dry-run]")
        print("Then force-reinstall the code:  install.ps1 -Force  (or install.sh --force)")
        return
    print(("[dry-run] " if dry_run else "") + "Repair — pulizia selettiva...")
    _print_results(executor.execute_repair(wipe, dry_run=dry_run))
    if reinstall and not dry_run:
        script = _paths.installer_script()
        if script is None:
            print("\n[!] installer not recorded: reinstall it by hand (install.ps1 -Force).")
            return
        argv = (["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Force"]
                if str(script).endswith(".ps1") else ["bash", str(script), "--force"])
        print(f"\nForce-reinstalling the suite: {' '.join(argv)}")
        import subprocess
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        sys.exit(subprocess.call(argv, creationflags=flags))
    print("\nNow reinstall the code (bypasses the version check):")
    print("  Windows:  powershell -ExecutionPolicy Bypass -File install.ps1 -Force")
    print("  mac/Linux: ./install.sh --force")


def cmd_record_env(root: str = "", gm: str = "", neurag: str = "", neuron: str = "") -> None:
    """GM registra la PROPRIA cartella sorgente (SoC: i peer registrano sé stessi
    con i loro `record-paths`). `--gm` esplicito, else `--root`, else auto."""
    from gray_matter import paths
    src = gm or (str(Path(root) / "gray_matter") if root else "")
    paths.record_self(source=src or None)
    print(f"GM source recorded in {paths.env_file()}: {paths.source_dir('gray-matter')}")
    disc = paths.discover_sources()
    if disc:
        print("Sorgenti scoperti:")
        for k, v in disc.items():
            print(f"  {k:12} {v}")


def cmd_cloud(subcmd: str, group: str, components: str, env_file: str,
              urls: "dict[str, str] | None" = None, token: str = "",
              no_cli_install: bool = False, assume_yes: bool = False) -> None:
    """Config del gruppo cloud Turso — CLI core, la GUI la invoca (DESIGN §5).
    `setup` = auto-provisioning (richiede turso CLI); `wire` = bring-your-own
    SENZA CLI (incolla URL/token dal dashboard)."""
    from gray_matter import cloud
    ef = Path(env_file) if env_file else None
    if subcmd == "setup":
        # Default: offriamo NOI l'install della turso CLI (opt-out: --no-cli-install
        # o GM_TURSO_CLI_INSTALL=0). Chi rifiuta riceve la guida — scelta loro.
        import shutil
        if shutil.which("turso") is None and not no_cli_install \
                and os.environ.get("GM_TURSO_CLI_INSTALL", "1") != "0":
            if cloud.cli_install_argv() is None:
                # Windows: la CLI cloud non ha installer nativo (WSL) → guida
                # subito, con `wire` come strada consigliata (zero CLI).
                for ln in cloud.CLI_GUIDE:
                    print(ln)
                sys.exit(1)
            consent = assume_yes
            if not consent and sys.stdin.isatty():
                ans = input("turso CLI non trovata. La installo ora (installer ufficiale, "
                            "consigliato)? [Y/n] ").strip().lower()
                consent = ans not in ("n", "no")
            if consent:
                if cloud.install_cli():
                    print("[ok] turso CLI installed - now run `turso auth login`, then re-run setup.")
                    return
                print("[!!] install CLI fallita — guida manuale:")
                for ln in cloud.CLI_GUIDE:
                    print(ln)
                sys.exit(1)
        comps = [c.strip() for c in components.split(",") if c.strip()] if components else None
        lines = cloud.setup(group=group, components=comps, env_file=ef)
    elif subcmd == "wire":
        urls = {k: v for k, v in (urls or {}).items() if v}
        # token mai obbligatorio su argv: fallback env/.env, poi prompt nascosto
        if not token and not os.environ.get("TURSO_AUTH_TOKEN", "").strip() \
                and not cloud.read_env_file(ef or cloud.default_env_file()).get("TURSO_AUTH_TOKEN") \
                and sys.stdin.isatty():
            import getpass
            token = getpass.getpass("Turso auth token (input nascosto, INVIO per saltare): ")
        lines = cloud.wire(urls, token=token, env_file=ef)
    elif subcmd == "status":
        lines = cloud.status(env_file=ef)
    else:
        lines = cloud.teardown(env_file=ef)
    for ln in lines:
        print(ln)
    if any(ln.startswith("[!!]") for ln in lines):
        sys.exit(1)


def cmd_logs(follow: bool = False, lines: int = 50) -> None:
    """G2 — coda del log del daemon; --follow resta in ascolto (Ctrl-C esce)."""
    from gray_matter.server import daemon_log_path
    p = daemon_log_path()
    if not p.exists():
        print(f"No logs yet ({p}). The file is created on the next `gray-matter start`.")
        return
    with open(p, encoding="utf-8", errors="replace") as f:
        tail = f.readlines()[-lines:]
        for ln in tail:
            print(ln.rstrip("\n"))
        if not follow:
            return
        print(f"--- following {p} (Ctrl-C to quit) ---")
        try:
            while True:
                line = f.readline()
                if line:
                    print(line.rstrip("\n"))
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass


def cmd_bridges() -> None:
    from gray_matter import bridges as _b
    bs = _b.all_bridges()
    print(f"Store: {_b.ENGINE_NAME}")          # stesso tier di Neuron/NeuRAG
    if not bs:
        print("No bridges yet.")
        return
    print(f"{len(bs)} cross-store bridge(s), strongest first:")
    for b in bs:
        rat = f" — {b['rationale']}" if b.get("rationale") else ""
        print(f"  [w={b.get('weight', 1)}] {b['neuron']} <-> {b['neurag']}{rat}")


def cmd_bridges_transfer(direction: str, dry_run: bool) -> None:
    """Sposta i bridge fra tier locale e cloud (additivo, mai distruttivo)."""
    from gray_matter.bridges import transfer
    try:
        r = transfer(direction, dry_run=dry_run)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
    what = "letti (dry-run, niente scritto)" if r["dry_run"] else "trasferiti"
    print(f"{r['direction']}: {r['read']} bridge {what}"
          + ("" if r["dry_run"] else f" — {r['written']} nuovi, {r['merged']} fusi"))


_KNOWLEDGE_TOOLS = {
    "status": "knowledge_status",
    "rebuild-links": "knowledge_rebuild_links",
    "link-graph": "knowledge_link_graph",
}


def cmd_knowledge(subcmd: str) -> None:
    tool = _KNOWLEDGE_TOOLS.get(subcmd)
    if not tool:
        print(f"Unknown knowledge subcommand: {subcmd}")
        print(f"Available: {', '.join(_KNOWLEDGE_TOOLS)}")
        sys.exit(1)
    r = _send_ipc({"action": "knowledge_cmd", "tool": tool, "args": {}})
    if "error" in r:
        print(f"Error: {r['error']}")
        sys.exit(1)
    if "text" in r:
        print(r["text"])
    elif "result" in r:
        print(r["result"])


def _ensure_daemon() -> bool:
    """Il daemon parte da solo se serve — un bottone della GUI deve funzionare,
    non rispondere 'connection refused'. Stessa logica di `start`."""
    from gray_matter.server import _spawn_gray_matter, _is_gray_matter_running
    if _is_gray_matter_running():
        return True
    print("[i] Gray-Matter is not running: starting it...")
    _spawn_gray_matter()
    for _ in range(30):          # ~3s: bind di :9876 a freddo
        time.sleep(0.1)
        if _is_gray_matter_running():
            print("[i] daemon started.")
            return True
    return False


def _cmd_gm_tool(action: str, tool: str, args_json: str) -> None:
    """gm-neuron / gm-neurag: chiama un tool passando dal gateway."""
    try:
        tool_args = json.loads(args_json) if args_json.strip() else {}
    except json.JSONDecodeError as e:
        print(f'[!] invalid arguments: they must be JSON, e.g. {{"topic": "coffee"}} - {e}')
        sys.exit(1)
    if not _ensure_daemon():
        print("[!] cannot start the daemon: try 'gray-matter start', then check 'logs'.")
        sys.exit(1)
    r = _send_ipc({"action": action, "tool": tool, "args": tool_args},
                  timeout=IPC_TOOL_TIMEOUT)
    if "error" in r:
        print(f"[{action}] {tool} -> error: {r['error']}")
        sys.exit(1)
    if "result" in r:
        result = r["result"].strip() if isinstance(r["result"], str) else str(r["result"])
        print(f"[{action}] {tool} -> {result}")


def cmd_gm_neuron(tool: str, args_json: str) -> None:
    _cmd_gm_tool("gm-neuron", tool, args_json)


def cmd_gm_neurag(tool: str, args_json: str) -> None:
    _cmd_gm_tool("gm-neurag", tool, args_json)


# Il parser sta in una funzione a sé: È l'elenco dei comandi (SSOT) e la GUI lo
# ispeziona invece di riscriverne una copia (gray_matter/catalog.py).
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gray-Matter control")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show Gray-Matter status and registered servers")
    sub.add_parser("start", help="Start Gray-Matter daemon")
    sub.add_parser("stop", help="Stop Gray-Matter daemon")
    sub.add_parser("ping", help="Check if Gray-Matter is running")
    reap_p = sub.add_parser("reap",
        help="Terminate suite processes left behind (orphans by default)")
    reap_p.add_argument("--all", dest="reap_all", action="store_true",
                        help="terminate every tracked process, not just orphans")
    reap_p.add_argument("--dry-run", action="store_true",
                        help="Show what would be terminated, kill nothing")

    iso = sub.add_parser("isolate", help="Exclude a server from the combined pulse (still callable directly)")
    iso.add_argument("name", help="Server name (neuron|neurag)")
    col = sub.add_parser("collaborate", help="Put a server back into the combined pulse")
    col.add_argument("name", help="Server name (neuron|neurag)")
    md = sub.add_parser("mode", help="Set ALL servers to collaborate or separate")
    md.add_argument("mode", choices=["collaborate", "separate"])

    gui_p = sub.add_parser("gui", help="Open the unified web control center")
    gui_p.add_argument("--classic", action="store_true", help=argparse.SUPPRESS)
    reg_p = sub.add_parser("register", help="Register installed trio servers in your MCP clients")
    reg_p.add_argument("--gateway", action="store_true",
                       help="Proxy model: register ONLY gray-matter, remove neuron/neurag from clients")
    der_p = sub.add_parser("deregister",
                           help="Take a tool off the gateway and register it directly in your clients (go-standalone)")
    der_p.add_argument("--tool", choices=["neuron", "neurag", "all"], default="all",
                       help="which tool to take off the gateway (default: all)")
    lnk_p = sub.add_parser("link",
                           help="Re-attach standalone tools to the gateway (the inverse of deregister)")
    lnk_p.add_argument("tools", nargs="*", default=[],
                       help="which tools to re-link (neuron, neurag) - empty = every standalone one")
    lnk_p.add_argument("--list", action="store_true", dest="list_only",
                       help="show each tool's gateway status, re-link nothing")
    lnk_p.add_argument("--json", action="store_true",
                       help="JSON output (used by the control center)")
    lnk_p.add_argument("--dry-run", action="store_true",
                       help="Show what would happen without changing anything")
    ins_p = sub.add_parser("install", help="Idempotent gateway install (reap, register GM, deploy hooks, manifest)")
    ins_p.add_argument("--dry-run", action="store_true", help="Show actions without doing them")
    uni_p = sub.add_parser("uninstall", help="Remove GM (interactive on the memory)")
    uni_p.add_argument("--purge-data", action="store_true", help="Also wipe memory WITHOUT asking")
    uni_p.add_argument("--yes", action="store_true", help="Answer yes to every prompt")
    uni_p.add_argument("--dry-run", action="store_true", help="Show actions without doing them")
    uni_p.add_argument("--list", action="store_true", dest="list_only",
                       help="List the removable surfaces (--json for the GUI), remove nothing")
    uni_p.add_argument("--json", action="store_true",
                       help="JSON output: surfaces (--list) or result+verification (used by the control center)")
    renv = sub.add_parser("record-env",
                          help="Record the source folders of all three tools (used by the installer)")
    renv.add_argument("--root", default="", help="Workspace to scan for the components")
    renv.add_argument("--gm", default="", help="gray_matter source folder")
    renv.add_argument("--neurag", default="", help="neurag source folder")
    renv.add_argument("--neuron", default="", help="neuron source folder")
    rep_p = sub.add_parser("repair",
                           help="Clean repair: choose what to delete, then force-reinstall")
    rep_p.add_argument("wipe", nargs="*", default=[],
                       help="keys to delete (neuron_graphs, neurag_db, gm_bridges, "
                            "gm_config, neurag_config, registrations) - or 'list'")
    rep_p.add_argument("--dry-run", action="store_true", help="Show what would be removed, change nothing")
    rep_p.add_argument("--reinstall", action="store_true",
                       help="after cleaning, run the suite installer right away with -Force")
    rep_p.add_argument("--json", action="store_true",
                       help="list the removable surfaces as JSON (used by the control center)")
    cld_p = sub.add_parser("cloud", help="Turso cloud: setup (auto, needs turso CLI), "
                                         "wire (paste URLs, NO CLI), status, teardown")
    cld_p.add_argument("subcmd", choices=["setup", "wire", "status", "teardown"])
    cld_p.add_argument("--group", default="graymatter", help="Turso group name (default: graymatter)")
    cld_p.add_argument("--components", default="",
                       help="setup: comma list among neuron,neurag,gm (default: all)")
    cld_p.add_argument("--neuron-url", default="", help="wire: Neuron DB URL (libsql://…)")
    cld_p.add_argument("--neurag-url", default="", help="wire: NeuRAG DB URL (SEPARATE DB)")
    cld_p.add_argument("--gm-url", default="", help="wire: GM bridges DB URL (SEPARATE DB)")
    cld_p.add_argument("--token", default="",
                       help="wire: auth token (better: TURSO_AUTH_TOKEN env, or hidden prompt)")
    cld_p.add_argument("--env-file", default="", help="Override the GM .env path")
    cld_p.add_argument("--no-cli-install", action="store_true",
                       help="setup: never offer to install the turso CLI (also GM_TURSO_CLI_INSTALL=0)")
    cld_p.add_argument("--yes", action="store_true",
                       help="setup: assume yes at the CLI-install prompt (headless)")

    log_p = sub.add_parser("logs", help="Show the daemon log (G2)")
    log_p.add_argument("--follow", "-f", action="store_true", help="Keep following (Ctrl-C to stop)")
    log_p.add_argument("--lines", "-n", type=int, default=50, help="Tail size (default 50)")

    sub.add_parser("bridges", help="List persisted cross-store bridges")

    brt_p = sub.add_parser("bridges-transfer",
                           help="Move bridges between the local and cloud tier (additive)")
    brt_p.add_argument("direction", choices=["to-cloud", "from-cloud"])
    brt_p.add_argument("--dry-run", action="store_true",
                       help="Count what would move, write nothing")
    sub.add_parser("stats", help="Orchestrator counters: cache hit rate, flashes, bridges, latency")
    sub.add_parser("doctor", help="Health snapshot: servers, workers, cache, bridges")

    br_p = sub.add_parser("bridge", help="Expose full suite over HTTP for remote LLM connectors")
    br_p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    br_p.add_argument("--bind", choices=["local", "all"], default="local",
                       help="Shorthand: 'local' → 127.0.0.1, 'all' → 0.0.0.0")
    br_p.add_argument("--port", type=int, default=8002, help="TCP port (default: 8002)")
    br_p.add_argument("--port-range", type=int, default=10,
                       help="How many ports to try if busy (default: 10)")
    br_p.add_argument("--tunnel", action="store_true", default=False,
                       help="Auto-launch a tunnel after bridge starts")
    br_p.add_argument("--proxy", default=None, help="Explicit mcp-proxy command")
    br_p.add_argument("--no-check", action="store_true", help="Skip preflight check")
    br_p.add_argument("--print-cmd", action="store_true", help="Print the command and exit")

    kn_p = sub.add_parser("knowledge", help="NeuRAG knowledge base management")
    kn_p.add_argument("subcmd", choices=["status", "rebuild-links", "link-graph"],
                       help="status=show nodes/chunks/links, rebuild-links= wipe+rebuild, link-graph= show graph")

    gm_nrn = sub.add_parser("gm-neuron", help="Call a Neuron tool via Gray Matter")
    gm_nrn.add_argument("tool", help="Neuron tool name: pre_turn, store_turn, get_context, status, ...")
    gm_nrn.add_argument("args", nargs="?", default="{}",
                        help='Optional JSON, e.g. {"topic": "coffee"} - empty = {}')

    gm_nrg = sub.add_parser("gm-neurag", help="Call a NeuRAG tool via Gray Matter")
    gm_nrg.add_argument("tool", help="NeuRAG tool name: knowledge_query, knowledge_status, knowledge_ingest, ...")
    gm_nrg.add_argument("args", nargs="?", default="{}",
                        help='Optional JSON, e.g. {"query": "spring boot"} - empty = {}')

    cfg_p = sub.add_parser("config", help="Get/set tunable knobs (flash rate, cache TTL, prewarm, ...)")
    cfg_p.add_argument("action", choices=["get", "set", "list"])
    cfg_p.add_argument("key", nargs="?", default="")
    cfg_p.add_argument("value", nargs="?", default=None)
    cfg_p.add_argument("--json", action="store_true",
                       help="Structured JSON output (used by the control center)")

    return parser


# GUI: gruppo di ogni comando, dal più grande al più piccolo.
COMMAND_GROUPS = {
    "install": "lifecycle", "uninstall": "lifecycle", "repair": "lifecycle",
    "start": "lifecycle", "stop": "lifecycle", "gui": "lifecycle", "register": "lifecycle",
    "deregister": "lifecycle", "link": "lifecycle", "bridge": "lifecycle",
    "bridges-transfer": "maintenance", "knowledge": "maintenance",
    "reap": "maintenance",
    "status": "inspect", "stats": "inspect", "doctor": "inspect",
    "bridges": "inspect", "logs": "inspect", "ping": "inspect",
    "gm-neuron": "inspect", "gm-neurag": "inspect",
    "config": "tuning", "cloud": "tuning", "mode": "tuning",
    "isolate": "tuning", "collaborate": "tuning", "record-env": "lifecycle",
}


def _console_safe() -> None:
    """Non far morire la CLI su un carattere che la console non sa scrivere.

    Su Windows stdout usa la code page locale (cp1252): il primo `→` che arriva
    dal grafo di Neuron faceva esplodere `gray-matter gm-neuron pre_turn` con
    UnicodeEncodeError a metà stampa. Il contenuto del grafo è testo utente
    arbitrario — emoji, CJK, frecce — e non è negoziabile con la code page:
    `errors="replace"` degrada quei caratteri a '?' invece di perdere il comando.
    """
    for stream in (sys.stdout, sys.stderr):
        # Sotto pytest, in una GUI o dietro una pipe, stdout è spesso un
        # wrapper senza `.reconfigure` (o con l'attributo a None): si salta.
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            pass


def main() -> None:
    import json
    _console_safe()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "ping":
        cmd_ping()
    elif args.command == "reap":
        cmd_reap(dry_run=args.dry_run, all_procs=args.reap_all)
    elif args.command == "isolate":
        cmd_isolate(args.name)
    elif args.command == "collaborate":
        cmd_collaborate(args.name)
    elif args.command == "mode":
        cmd_mode(args.mode)
    elif args.command == "gui":
        # La GUI è UNA: il control center web. La Tkinter "classic" è ritirata
        # (restava attiva in parallelo e confondeva — e non funzionava).
        if getattr(args, "classic", False):
            print("[!] --classic is retired: opening the single control center.")
        try:
            from gray_matter.shortcut import ensure_desktop_shortcut
            ensure_desktop_shortcut("gray-matter", "Gray Matter",
                                    ["-m", "gray_matter.cli", "gui"],
                                    "Gray Matter — control center")
        except Exception:  # noqa: BLE001 — un'icona non deve mai bloccare la GUI
            pass
        from gray_matter.webgui import main as gui_main
        gui_main()
    elif args.command == "register":
        cmd_register(args.gateway)
    elif args.command == "deregister":
        cmd_deregister(args.tool)
    elif args.command == "link":
        cmd_link(args.tools, args.list_only, args.json, args.dry_run)
    elif args.command == "install":
        cmd_install(args.dry_run)
    elif args.command == "uninstall":
        cmd_uninstall(args.purge_data, args.yes, args.dry_run,
                      args.list_only, args.json)
    elif args.command == "record-env":
        cmd_record_env(args.root, args.gm, args.neurag, args.neuron)
    elif args.command == "repair":
        cmd_repair(args.wipe, args.dry_run, args.json, args.reinstall)
    elif args.command == "cloud":
        cmd_cloud(args.subcmd, args.group, args.components, args.env_file,
                  urls={"neuron": args.neuron_url, "neurag": args.neurag_url,
                        "gm": args.gm_url},
                  token=args.token,
                  no_cli_install=args.no_cli_install, assume_yes=args.yes)
    elif args.command == "logs":
        cmd_logs(args.follow, args.lines)
    elif args.command == "bridges":
        cmd_bridges()
    elif args.command == "bridges-transfer":
        cmd_bridges_transfer(args.direction, args.dry_run)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "doctor":
        cmd_doctor()
    elif args.command == "bridge":
        from gray_matter.bridge import main as bridge_main
        # Pass through bridge-specific args; bridge_main handles its own parsing
        bridge_args = []
        if args.host and args.host != "127.0.0.1":
            bridge_args += ["--host", args.host]
        if args.bind == "all":
            bridge_args += ["--bind", "all"]
        if args.port and args.port != 8002:
            bridge_args += ["--port", str(args.port)]
        if args.port_range and args.port_range != 10:
            bridge_args += ["--port-range", str(args.port_range)]
        if args.tunnel:
            bridge_args.append("--tunnel")
        if args.proxy:
            bridge_args += ["--proxy", args.proxy]
        if args.no_check:
            bridge_args.append("--no-check")
        if args.print_cmd:
            bridge_args.append("--print-cmd")
        sys.exit(bridge_main(bridge_args))
    elif args.command == "config":
        cmd_config(args.action, args.key, args.value, args.json)
    elif args.command == "knowledge":
        cmd_knowledge(args.subcmd)
    elif args.command == "gm-neuron":
        cmd_gm_neuron(args.tool, args.args)
    elif args.command == "gm-neurag":
        cmd_gm_neurag(args.tool, args.args)


if __name__ == "__main__":
    main()
