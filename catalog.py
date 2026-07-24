"""Catalogo degli ambienti e dei loro comandi — la sorgente che alimenta la GUI.

SSOT: qui NON c'è nessun elenco di comandi. Ogni tool dichiara i propri e questo
modulo li **legge**:

  * Gray Matter e NeuRAG espongono ``build_parser()`` (argparse) → i subcomandi
    e i loro argomenti si ricavano per introspezione;
  * Neuron espone ``COMMANDS`` (dict) perché il suo dispatch non è argparse.

Conseguenza voluta: un subcomando aggiunto a una CLI compare nel control center
da solo, senza toccare la GUI. Un tool non installato semplicemente non compare.

SoC: questo modulo *descrive* soltanto. Non esegue nulla — l'esecuzione è di
``webgui`` (un solo runner generico), il rendering della pagina è dell'HTML.
"""
from __future__ import annotations

import importlib
import importlib.util   # esplicito: `import importlib` NON garantisce .util

# Ordine di rendering: dal più grande al più piccolo.
GROUPS = (
    ("lifecycle",   "Ciclo di vita"),
    ("maintenance", "Manutenzione"),
    ("inspect",     "Ispezione"),
    ("tuning",      "Regolazione"),
    ("other",       "Altro"),
)
_DEFAULT_GROUP = "other"   # un comando nuovo è VISIBILE anche prima di avere un gruppo

# Comandi che nella GUI non hanno senso (aprirebbero un'altra GUI).
GUI_HIDDEN = {("gray-matter", "gui"), ("neuron", "gui"), ("neurag", "gui"),
              ("gray-matter", "record-env"),
              ("neuron", "record-paths"), ("neurag", "record-paths")}

# Comandi interattivi: fanno domande all'utente, quindi NON si possono
# streamare in un pannello con stdin chiuso (restavano appesi: "non parte
# nulla"). La GUI li apre in una finestra di terminale vera.
INTERACTIVE = {("gray-matter", "cloud"),
               ("neuron", "setup"), ("neuron", "manage"), ("neuron", "connect")}

# Spiegazioni per persone, non per CLI: la GUI mostra queste; il testo argparse
# resta il fallback per i comandi nuovi non ancora descritti qui.
HELP_IT = {
    ("gray-matter", "install"):   "Installa/ripara il gateway: registra Gray Matter nei client AI e collega Neuron e NeuRAG. Sicuro da rilanciare.",
    ("gray-matter", "uninstall"): "Rimuove Gray Matter dai client. Chiede cosa fare della memoria (si apre in un terminale).",
    ("gray-matter", "repair"):    "Reinstall pulito: scegli cosa cancellare (memoria, knowledge, bridges, config, registrazioni) e cosa tenere, poi reinstalla forzato bypassando il check di versione.",
    ("gray-matter", "start"):     "Avvia il daemon Gray Matter in background.",
    ("neuron", "uninstall"):      "Deregistra Neuron dai client AI e opzionalmente cancella il database dei ricordi.",
    ("neurag", "uninstall"):      "Deregistra NeuRAG dai client AI e opzionalmente cancella il database della conoscenza.",
    ("gray-matter", "stop"):      "Ferma il daemon Gray Matter.",
    ("gray-matter", "status"):    "Stato del daemon e dei server registrati (Neuron, NeuRAG).",
    ("gray-matter", "ping"):      "Verifica veloce: il daemon risponde?",
    ("gray-matter", "register"):  "Registra il GATEWAY nei client AI (Claude, Cursor, ecc.). Neuron e NeuRAG vengono gestiti tramite il proxy.",
    ("gray-matter", "deregister"): "Fa uscire un tool (o entrambi) dal gateway: lo toglie dalla gestione GM e lo registra come MCP diretto nei client. Reversibile con 'link' (o register --gateway).",
    ("gray-matter", "link"): "Ri-aggancia al gateway i tool andati standalone (l'inverso di deregister): scegli quali far tornare sotto Gray Matter. GM riprende a gestirli e l'entry MCP diretta del tool sparisce dai client.",
    ("gray-matter", "logs"):      "Mostra il log del daemon (le ultime righe).",
    ("gray-matter", "doctor"):    "Controllo di salute completo: server, worker, cache, ponti.",
    ("gray-matter", "stats"):     "Contatori: cache, flash, ponti, latenza.",
    ("gray-matter", "bridges"):   "Elenca i ponti salvati tra memoria (Neuron) e conoscenza (NeuRAG).",
    ("gray-matter", "bridges-transfer"): "Sposta i ponti tra locale e cloud (non cancella nulla).",
    ("gray-matter", "knowledge"): "Manutenzione della base di conoscenza NeuRAG (status, rebuild-links, link-graph).",
    ("gray-matter", "gm-neuron"): "Chiama un tool di Neuron passando dal gateway (per test).",
    ("gray-matter", "gm-neurag"): "Chiama un tool di NeuRAG passando dal gateway (per test).",
    ("gray-matter", "config"):    "Configurazione del gateway: cache, flash rate, TTL, ponti. Prova: action=list.",
    ("gray-matter", "cloud"):     "Collega i database al cloud Turso (si apre in un terminale: chiede URL/token).",
    ("gray-matter", "mode"):      "Tutti i server insieme (collaborate) o ognuno per sé (separate).",
    ("gray-matter", "isolate"):   "Escludi un server (neuron|neurag) dal pulse combinato.",
    ("gray-matter", "collaborate"): "Rimetti un server (neuron|neurag) nel pulse combinato.",
    ("neuron", "setup"):          "Installa, aggiorna o ripara Neuron (si apre in un terminale: fa domande).",
    ("neuron", "manage"):         "Gestione quotidiana del grafo di memoria (si apre in un terminale).",
    ("neuron", "connect"):        "Collega un DB Turso Cloud a Neuron (si apre in un terminale: chiede URL/token).",
    ("neuron", "register"):       "Registra Neuron come MCP DIRETTO nei client (standalone, senza gateway).",
    ("neuron", "doctor"):         "Diagnostica e ripara le registrazioni di Neuron nei client.",
    ("neuron", "console"):        "Fotografia del grafo di memoria, sola lettura.",
    ("neuron", "consolidate"):    "Pulizia della memoria: fonde i quasi-duplicati e archivia gli orfani.",
    ("neuron", "start"):          "Avvia il server Neuron in background (bridge HTTP per connettori remoti).",
    ("neuron", "stop"):           "Ferma il server Neuron.",
    ("neuron", "bridge"):         "Espone Neuron su HTTP per i connettori remoti (resta in esecuzione).",
    ("neuron", "tunnel"):         "HTTPS pubblico via cloudflared, da usare col bridge (resta in esecuzione).",
    ("neuron", "init"):           "Cablaggio dei client AI senza avviare il server.",
    ("neuron", "go-standalone"):  "Neuron esce dal gateway: si registra come MCP diretto nei client. Reversibile con gray-matter register --gateway.",
    ("neuron", "repair"):         "Reinstall pulito SOLO di Neuron: scegli cosa cancellare (memoria, config), poi reinstalla forzato.",
    ("neuron", "migrate"):        "Migra i grafi dalla vecchia slug (neuron5) alla nuova (neuron). Idempotente.",
    ("neurag", "register"):       "Registra NeuRAG come MCP DIRETTO nei client (standalone, senza gateway).",
    ("neurag", "deregister"):     "Rimuove NeuRAG dai config dei client AI.",
    ("neurag", "go-standalone"):  "NeuRAG esce dal gateway: si registra come MCP diretto nei client. Reversibile con gray-matter register --gateway.",
    ("neurag", "start"):          "Avvia il server NeuRAG in background (MCP stdio).",
    ("neurag", "stop"):           "Ferma il server NeuRAG.",
    ("neurag", "status"):         "Stato della base di conoscenza: nodi, chunk, collegamenti.",
    ("neurag", "query"):          "Cerca nella base di conoscenza. Scrivi la domanda nel campo query.",
    ("neurag", "tree"):           "Mostra la gerarchia dei nodi di conoscenza.",
    ("neurag", "health"):         "Controllo di integrità strutturale del vault.",
    ("neurag", "doctor"):         "Fotografia dell'ambiente: tier, embedder, gateway.",
    ("neurag", "chunk"):          "Prova di spezzettamento di un file o cartella (non salva nulla).",
    ("neurag", "add-node"):       "Aggiunge un nodo alla gerarchia di conoscenza.",
    ("neurag", "add-chunks"):     "Aggancia chunk (JSON da file o stdin) a un nodo esistente.",
    ("neurag", "import"):         "Importa una cartella intera secondo una mappa YAML.",
    ("neurag", "ingest"):         "Grafizza una cartella in automatico: nodi dalla struttura, chunk, embedding e link. Dai solo il percorso.",
    ("neurag", "rename-node"):    "Rinomina un nodo della conoscenza (i path dei figli si aggiornano da soli).",
    ("neurag", "remove-node"):    "Elimina un nodo e tutto il suo sottoalbero (chunk compresi).",
    ("neurag", "config"):         "Configurazione NeuRAG: rerank on/off, pool, modello embedder. Prova: action=list.",
    ("neurag", "repair"):         "Reinstall pulito SOLO di NeuRAG: scegli cosa cancellare (knowledge, config), poi reinstalla forzato.",
}

# I tre ambienti. `module` è ciò che si importa per sapere se il tool c'è.
ENVIRONMENTS = (
    {"key": "gray-matter", "label": "Gray Matter", "subtitle": "orchestratore",
     "module": "gray_matter", "cli": "gray_matter.cli", "kind": "parser"},
    {"key": "neuron", "label": "Neuron", "subtitle": "memoria semantica",
     "module": "neuron", "cli": "neuron.__main__", "kind": "commands"},
    {"key": "neurag", "label": "NeuRAG", "subtitle": "knowledge vault",
     "module": "neurag", "cli": "neurag.cli", "kind": "parser"},
)


def _version(module: str) -> str:
    try:
        import importlib.metadata as md
        return md.version(module.replace("_", "-"))
    except Exception:  # noqa: BLE001 — non installato (es. checkout sorgente)
        try:
            return getattr(importlib.import_module(module), "__version__", "") or ""
        except Exception:  # noqa: BLE001
            return ""


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except BaseException:  # noqa: BLE001 — un pacchetto rotto = non installato
        return False


def _args_of(action_container) -> list[dict]:
    """Argomenti di un subparser, normalizzati per la GUI."""
    out = []
    for a in getattr(action_container, "_actions", []):
        if a.dest in ("help", "==SUPPRESS=="):
            continue
        out.append({
            "dest": a.dest,
            "flag": a.option_strings[0] if a.option_strings else "",
            "required": bool(getattr(a, "required", False)) and not a.option_strings,
            "choices": [str(c) for c in (a.choices or [])] if a.choices else [],
            "help": a.help or "",
            "is_flag": a.nargs == 0,
        })
    return out


def _from_parser(cli_module: str) -> list[dict]:
    mod = importlib.import_module(cli_module)
    parser = mod.build_parser()
    groups = getattr(mod, "COMMAND_GROUPS", {})
    subparsers = next((a for a in parser._actions
                       if hasattr(a, "choices") and isinstance(a.choices, dict)), None)
    if subparsers is None:
        return []
    cmds = []
    for name, sub in subparsers.choices.items():
        cmds.append({
            "name": name,
            "help": (sub.description or "").strip() or _help_of(subparsers, name),
            "group": groups.get(name, _DEFAULT_GROUP),
            "args": _args_of(sub),
        })
    return cmds


def _help_of(subparsers_action, name: str) -> str:
    for ch in subparsers_action._choices_actions:
        if ch.dest == name:
            return ch.help or ""
    return ""


def _from_commands(cli_module: str) -> list[dict]:
    """Neuron: dict `COMMANDS` = nome -> (modulo, funzione, gruppo, help, flag)."""
    mod = importlib.import_module(cli_module)
    return [{"name": name, "help": spec[3], "group": spec[2], "args": []}
            for name, spec in getattr(mod, "COMMANDS", {}).items()]


def environments() -> list[dict]:
    """Gli ambienti con lo stato reale della macchina. Mai solleva: un tool rotto
    compare come non-installato invece di far fallire tutta la GUI."""
    out = []
    for env in ENVIRONMENTS:
        present = _installed(env["module"])
        commands: list[dict] = []
        error = ""
        if present:
            try:
                commands = (_from_parser(env["cli"]) if env["kind"] == "parser"
                            else _from_commands(env["cli"]))
            except BaseException as exc:  # noqa: BLE001 — anche SystemExit:
                # un tool la cui CLI chiama sys.exit() all'import non deve
                # uccidere la GUI, deve solo comparire con l'errore scritto.
                error = f"{type(exc).__name__}: {exc}"
        commands = [c for c in commands
                    if (env["key"], c["name"]) not in GUI_HIDDEN]
        for c in commands:
            key = (env["key"], c["name"])
            c["help"] = HELP_IT.get(key, c["help"])
            c["interactive"] = key in INTERACTIVE
        out.append({
            "key": env["key"], "label": env["label"], "subtitle": env["subtitle"],
            "installed": present, "version": _version(env["module"]) if present else "",
            "commands": sorted(commands, key=lambda c: (
                [g[0] for g in GROUPS].index(c["group"])
                if c["group"] in [g[0] for g in GROUPS] else 99, c["name"])),
            "error": error,
        })
    return out


def grouped(env: dict) -> list[dict]:
    """I comandi di un ambiente raccolti per gruppo, nell'ordine di GROUPS."""
    out = []
    for key, label in GROUPS:
        items = [c for c in env["commands"] if c["group"] == key]
        if items:
            out.append({"key": key, "label": label, "commands": items})
    return out


def demo() -> None:
    """Self-check: il catalogo deve descrivere la macchina, non un elenco fisso."""
    envs = environments()
    assert len(envs) == 3, envs
    gm = next(e for e in envs if e["key"] == "gray-matter")
    assert gm["installed"], "gray_matter deve essere importabile da qui"
    assert not gm["error"], gm["error"]
    names = [c["name"] for c in gm["commands"]]
    assert "status" in names and "install" in names, names
    # ogni comando finisce in un gruppo noto: nessuno sparisce dalla GUI
    valid = {g[0] for g in GROUPS}
    for e in envs:
        for c in e["commands"]:
            assert c["group"] in valid, (e["key"], c)
        assert sum(len(g["commands"]) for g in grouped(e)) == len(e["commands"]), e["key"]
    print(f"catalog OK — " + ", ".join(
        f"{e['label']}: {len(e['commands'])} comandi" if e["installed"]
        else f"{e['label']}: non installato" for e in envs))


if __name__ == "__main__":
    demo()
