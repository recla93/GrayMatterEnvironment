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

# Comandi interattivi: fanno domande all'utente. La GUI li avverte e collega
# lo stdin del processo alla riga di risposta sotto la console. Prima li
# dirottava in una finestra `cmd` esterna — la finestra nera che spuntava
# dalla GUI; ora la console del pannello è a tutti gli effetti un terminale.
INTERACTIVE = {("gray-matter", "cloud"),
               ("neuron", "setup"), ("neuron", "manage"), ("neuron", "connect")}

# Spiegazioni per persone, non per CLI: la GUI mostra queste; il testo argparse
# resta il fallback per i comandi nuovi non ancora descritti qui.
#
# Ogni voce dice DUE cose, perché sapere cosa fa un comando non basta a sapere
# se è quello giusto adesso:
#     (cosa_it, quando_it, what_en, when_en)
# "cosa" = che effetto ha · "quando" = in quale situazione serve davvero.
# Le due lingue stanno QUI e non in due dizionari separati: tenerle accostate
# è l'unico modo perché una traduzione mancante si veda subito (vedi il
# self-check in demo(), che le conta).
DOCS: "dict[tuple[str, str], tuple[str, str, str, str]]" = {

    # ── Gray Matter — ciclo di vita ──────────────────────────────────────
    ("gray-matter", "install"): (
        "Installa/ripara il gateway: registra Gray Matter nei client AI e collega Neuron e NeuRAG.",
        "La prima volta, e ogni volta che un client AI non vede più i tool. È idempotente: rilanciarlo non rompe nulla.",
        "Install/repair the gateway: registers Gray Matter in your AI clients and wires up Neuron and NeuRAG.",
        "The first time, and any time an AI client stops seeing the tools. It is idempotent — re-running it breaks nothing.",
    ),
    ("gray-matter", "uninstall"): (
        "Rimuove Gray Matter dai client AI. Chiede cosa fare della memoria.",
        "Quando vuoi smettere di usare la suite. La memoria si conserva se non dici esplicitamente di cancellarla.",
        "Removes Gray Matter from your AI clients. Asks what to do with your memory.",
        "When you want to stop using the suite. Your memory is kept unless you explicitly ask to delete it.",
    ),
    ("gray-matter", "repair"): (
        "Reinstall pulito: scegli cosa cancellare (memoria, conoscenza, ponti, config, registrazioni) e cosa tenere, poi reinstalla forzando il bypass del check di versione.",
        "Quando 'install' non basta più: codice aggiornato ma stessa versione, o uno stato che non torna. Prima prova 'doctor'.",
        "Clean reinstall: pick what to delete (memory, knowledge, bridges, config, registrations) and what to keep, then force-reinstall bypassing the version check.",
        "When 'install' is no longer enough: code changed but the version did not, or state that no longer adds up. Try 'doctor' first.",
    ),
    ("gray-matter", "start"): (
        "Avvia il daemon Gray Matter in background.",
        "Raramente a mano: il client AI lo avvia da solo. Serve per test, o dopo uno 'stop'.",
        "Starts the Gray Matter daemon in the background.",
        "Rarely by hand — your AI client starts it for you. Useful for testing, or after a 'stop'.",
    ),
    ("gray-matter", "stop"): (
        "Ferma il daemon Gray Matter.",
        "Prima di un aggiornamento, o per liberare la porta se sospetti due daemon in esecuzione.",
        "Stops the Gray Matter daemon.",
        "Before an update, or to free the port if you suspect two daemons are running.",
    ),
    ("gray-matter", "register"): (
        "Registra il GATEWAY nei client AI (Claude, Cursor, ecc.). Neuron e NeuRAG restano gestiti dal proxy.",
        "Dopo aver installato un nuovo client AI, o per tornare al modello gateway dopo un 'go-standalone'.",
        "Registers the GATEWAY in your AI clients (Claude, Cursor, ...). Neuron and NeuRAG stay behind the proxy.",
        "After installing a new AI client, or to return to the gateway model after a 'go-standalone'.",
    ),
    ("gray-matter", "deregister"): (
        "Fa uscire un tool (o entrambi) dal gateway: lo toglie dalla gestione GM e lo registra come MCP diretto nei client.",
        "Quando vuoi usare Neuron o NeuRAG da solo, senza il gateway. Reversibile con 'link'.",
        "Takes a tool (or both) off the gateway: GM stops managing it and it registers directly in your clients.",
        "When you want to use Neuron or NeuRAG on its own, without the gateway. Undo it with 'link'.",
    ),
    ("gray-matter", "link"): (
        "Ri-aggancia al gateway i tool andati standalone: GM riprende a gestirli e la loro entry MCP diretta sparisce dai client.",
        "L'inverso di 'deregister', quando vuoi tornare a un solo connettore.",
        "Re-attaches standalone tools to the gateway: GM manages them again and their direct MCP entry disappears from your clients.",
        "The inverse of 'deregister', when you want a single connector again.",
    ),

    # ── Gray Matter — ispezione ──────────────────────────────────────────
    ("gray-matter", "status"): (
        "Stato del daemon e dei server registrati (Neuron, NeuRAG), con i loro tool.",
        "Prima domanda da farsi quando l'AI 'non ricorda': se qui i server non compaiono, il resto non può funzionare.",
        "Daemon status and the registered servers (Neuron, NeuRAG), with their tools.",
        "The first thing to check when your AI 'forgets': if the servers are missing here, nothing else can work.",
    ),
    ("gray-matter", "doctor"): (
        "Controllo di salute completo: server, worker, cache, ponti, tier di storage.",
        "Quando qualcosa non va e non sai da dove partire. È il comando diagnostico da lanciare per primo.",
        "Full health check: servers, workers, cache, bridges, storage tier.",
        "When something is wrong and you do not know where to start. This is the first diagnostic to run.",
    ),
    ("gray-matter", "ping"): (
        "Verifica veloce: il daemon risponde?",
        "Un sì/no immediato, più rapido di 'status', utile negli script.",
        "Quick check: is the daemon answering?",
        "An immediate yes/no, faster than 'status', handy in scripts.",
    ),
    ("gray-matter", "stats"): (
        "Contatori di sessione: cache hit, flash, ponti, latenza media.",
        "Per capire se la cache sta lavorando e quanto costa davvero un pulse.",
        "Session counters: cache hits, flashes, bridges, average latency.",
        "To see whether the cache is doing its job and what a pulse really costs.",
    ),
    ("gray-matter", "logs"): (
        "Mostra il log del daemon (le ultime righe).",
        "Dopo un crash o un avvio fallito: è lì che finiscono i traceback del daemon.",
        "Shows the daemon log (the last lines).",
        "After a crash or a failed start — daemon tracebacks land there.",
    ),
    ("gray-matter", "bridges"): (
        "Elenca i ponti salvati fra memoria (Neuron) e conoscenza (NeuRAG), con il loro peso.",
        "Per vedere cosa la suite ha imparato a collegare da sola con l'uso.",
        "Lists the saved bridges between memory (Neuron) and knowledge (NeuRAG), with their weight.",
        "To see what the suite has learned to connect on its own, through use.",
    ),
    ("gray-matter", "gm-neuron"): (
        "Chiama un tool di Neuron passando dal gateway.",
        "Per test e diagnosi: verifica che il percorso client → gateway → worker funzioni davvero.",
        "Calls a Neuron tool through the gateway.",
        "For testing and diagnosis: proves the client → gateway → worker path actually works.",
    ),
    ("gray-matter", "gm-neurag"): (
        "Chiama un tool di NeuRAG passando dal gateway.",
        "Come gm-neuron, ma per la base di conoscenza.",
        "Calls a NeuRAG tool through the gateway.",
        "Like gm-neuron, but for the knowledge base.",
    ),

    # ── Gray Matter — regolazione e rete ─────────────────────────────────
    ("gray-matter", "config"): (
        "Configurazione del gateway: cache, flash rate, TTL, prewarm.",
        "Per regolare il comportamento senza toccare il codice. Parti da action=list per vedere cosa esiste.",
        "Gateway configuration: cache, flash rate, TTL, prewarm.",
        "To tune behaviour without touching code. Start with action=list to see what exists.",
    ),
    ("gray-matter", "cloud"): (
        "Collega i database al cloud Turso (chiede URL e token).",
        "Quando vuoi la stessa memoria su più computer. In locale non serve: il file .db basta.",
        "Connects the databases to Turso cloud (asks for URL and token).",
        "When you want the same memory on more than one computer. Not needed locally — the .db file is enough.",
    ),
    ("gray-matter", "mode"): (
        "Tutti i server insieme (collaborate) o ognuno per sé (separate).",
        "'separate' isola i due store quando vuoi capire quale dei due risponde male.",
        "All servers together (collaborate) or each on its own (separate).",
        "'separate' isolates the two stores when you want to work out which one is answering badly.",
    ),
    ("gray-matter", "isolate"): (
        "Escludi un server (neuron|neurag) dal pulse combinato.",
        "Per provare la suite senza uno dei due, o mentre ne ripari uno.",
        "Excludes a server (neuron|neurag) from the combined pulse.",
        "To try the suite without one of them, or while you are repairing one.",
    ),
    ("gray-matter", "collaborate"): (
        "Rimetti un server (neuron|neurag) nel pulse combinato.",
        "L'inverso di 'isolate', quando hai finito.",
        "Puts a server (neuron|neurag) back into the combined pulse.",
        "The inverse of 'isolate', when you are done.",
    ),
    ("gray-matter", "bridge"): (
        "Espone l'intera suite (Neuron + NeuRAG + GM) su HTTP per connettori remoti.",
        "Per usare la memoria da client che non parlano stdio MCP (Perplexity, ChatGPT). Resta in esecuzione.",
        "Exposes the whole suite (Neuron + NeuRAG + GM) over HTTP for remote connectors.",
        "To use your memory from clients that do not speak stdio MCP (Perplexity, ChatGPT). Keeps running.",
    ),
    ("gray-matter", "bridges-transfer"): (
        "Sposta i ponti fra locale e cloud. È additivo: non cancella nulla.",
        "Quando passi al cloud e vuoi portarti dietro quello che la suite ha già imparato.",
        "Moves bridges between local and cloud. Additive — it never deletes anything.",
        "When you move to the cloud and want to bring along what the suite already learned.",
    ),
    ("gray-matter", "reap"): (
        "Termina i processi della suite rimasti indietro: quelli il cui genitore (il client AI) non esiste più.",
        "Quando 'doctor' segnala degli orfani. Non tocca i server che stanno servendo un client vivo — quelli servono.",
        "Terminates suite processes left behind: the ones whose parent (the AI client) is gone.",
        "When 'doctor' reports orphans. It leaves alone the servers still serving a live client — those are in use.",
    ),
    ("gray-matter", "knowledge"): (
        "Manutenzione della base di conoscenza NeuRAG (status, rebuild-links, link-graph).",
        "Scorciatoia per i comandi NeuRAG più usati, senza cambiare ambiente.",
        "NeuRAG knowledge base maintenance (status, rebuild-links, link-graph).",
        "A shortcut to the most-used NeuRAG commands without switching environment.",
    ),

    # ── Neuron ───────────────────────────────────────────────────────────
    ("neuron", "setup"): (
        "Installa, aggiorna o ripara Neuron. Fa domande.",
        "Per gestire Neuron da solo. Con la suite installata, 'gray-matter install' copre già tutto.",
        "Installs, updates or repairs Neuron. It asks questions.",
        "To manage Neuron on its own. With the suite installed, 'gray-matter install' already covers this.",
    ),
    ("neuron", "manage"): (
        "Gestione quotidiana del grafo di memoria. Fa domande.",
        "Per operazioni di manutenzione guidate sul grafo, una alla volta.",
        "Day-to-day management of the memory graph. It asks questions.",
        "For guided maintenance on the graph, one operation at a time.",
    ),
    ("neuron", "connect"): (
        "Collega un DB Turso Cloud a Neuron (chiede URL e token).",
        "Solo per la memoria di Neuron. Per tutta la suite usa 'gray-matter cloud'.",
        "Connects a Turso Cloud DB to Neuron (asks for URL and token).",
        "For Neuron's memory only. For the whole suite use 'gray-matter cloud'.",
    ),
    ("neuron", "register"): (
        "Registra Neuron come MCP DIRETTO nei client (standalone, senza gateway).",
        "Solo se non usi Gray Matter: con il gateway attivo crea una doppia registrazione.",
        "Registers Neuron as a DIRECT MCP server in your clients (standalone, no gateway).",
        "Only if you are not using Gray Matter: with the gateway active this creates a double registration.",
    ),
    ("neuron", "doctor"): (
        "Diagnostica e ripara le registrazioni di Neuron nei client AI.",
        "Quando un client vede Neuron e un altro no: confronta i config e li rimette a posto.",
        "Diagnoses and repairs Neuron's registrations in your AI clients.",
        "When one client sees Neuron and another does not: it compares the configs and fixes them.",
    ),
    ("neuron", "console"): (
        "Fotografia del grafo di memoria, in sola lettura.",
        "Per guardare cosa Neuron ha imparato senza rischiare di modificarlo.",
        "A read-only snapshot of the memory graph.",
        "To look at what Neuron has learned with no risk of changing it.",
    ),
    ("neuron", "consolidate"): (
        "Pulizia della memoria: fonde i quasi-duplicati e archivia gli orfani.",
        "Ogni tanto, quando il grafo si è riempito di varianti dello stesso concetto ('spring boot' / 'Spring Boot').",
        "Memory cleanup: merges near-duplicates and archives orphans.",
        "Every so often, when the graph has filled up with variants of the same concept ('spring boot' / 'Spring Boot').",
    ),
    ("neuron", "start"): (
        "Avvia il server Neuron in background (bridge HTTP per connettori remoti).",
        "Solo per i connettori remoti: il client AI non ha bisogno di questo.",
        "Starts the Neuron server in the background (HTTP bridge for remote connectors).",
        "For remote connectors only — your AI client does not need this.",
    ),
    ("neuron", "stop"): (
        "Ferma il server Neuron avviato con 'start'.",
        "Quando hai finito con i connettori remoti.",
        "Stops the Neuron server started with 'start'.",
        "When you are done with the remote connectors.",
    ),
    ("neuron", "bridge"): (
        "Espone Neuron su HTTP per i connettori remoti. Resta in esecuzione.",
        "Come 'gray-matter bridge', ma per la sola memoria.",
        "Exposes Neuron over HTTP for remote connectors. Keeps running.",
        "Like 'gray-matter bridge', but for memory alone.",
    ),
    ("neuron", "tunnel"): (
        "HTTPS pubblico via cloudflared, da usare insieme al bridge. Resta in esecuzione.",
        "Quando il connettore remoto è su internet e non può raggiungere il tuo localhost.",
        "Public HTTPS via cloudflared, to be used together with the bridge. Keeps running.",
        "When the remote connector lives on the internet and cannot reach your localhost.",
    ),
    ("neuron", "init"): (
        "Cablaggio dei client AI senza avviare il server.",
        "Quando vuoi solo scrivere la configurazione, senza caricare il modello.",
        "Wires up your AI clients without starting the server.",
        "When you only want to write the configuration, without loading the model.",
    ),
    ("neuron", "go-standalone"): (
        "Neuron esce dal gateway e si registra come MCP diretto nei client.",
        "Per usare solo la memoria, senza knowledge base. Reversibile con 'gray-matter link'.",
        "Neuron leaves the gateway and registers as a direct MCP server in your clients.",
        "To use memory alone, without the knowledge base. Undo with 'gray-matter link'.",
    ),
    ("neuron", "repair"): (
        "Reinstall pulito SOLO di Neuron: scegli cosa cancellare (memoria, config), poi reinstalla forzato.",
        "Quando è Neuron a essere rotto e non vuoi toccare NeuRAG né il gateway.",
        "Clean reinstall of Neuron ONLY: pick what to delete (memory, config), then force-reinstall.",
        "When Neuron is the broken one and you do not want to touch NeuRAG or the gateway.",
    ),
    ("neuron", "migrate"): (
        "Migra i grafi dalla vecchia slug (neuron5) alla nuova (neuron). Idempotente.",
        "Una volta sola, arrivando da un'installazione vecchia. Se non hai grafi vecchi non fa nulla.",
        "Migrates graphs from the old slug (neuron5) to the new one (neuron). Idempotent.",
        "Once only, coming from an old installation. With no old graphs it does nothing.",
    ),
    # Neuron non ha un comando `uninstall` a sé: la disinstallazione passa da
    # `neuron setup --uninstall` (è così che la invoca anche la card della GUI,
    # vedi webgui._detect_uninstall_tools). Documentarlo qui significava
    # descrivere un comando inesistente — lo `demo()` ora lo impedisce.

    # ── NeuRAG ───────────────────────────────────────────────────────────
    ("neurag", "status"): (
        "Stato della base di conoscenza: nodi, chunk, collegamenti, motore di storage.",
        "Per sapere se il vault è popolato e su quale tier gira (Turso o sqlite3).",
        "Knowledge base status: nodes, chunks, links, storage engine.",
        "To see whether the vault has content and which tier it runs on (Turso or sqlite3).",
    ),
    ("neurag", "query"): (
        "Cerca nella base di conoscenza. Scrivi la domanda nel campo query.",
        "Per provare cosa troverebbe l'AI prima di fidarti del vault.",
        "Searches the knowledge base. Type your question in the query field.",
        "To see what your AI would find, before you trust the vault.",
    ),
    ("neurag", "recall"): (
        "Cerca in TUTTI i layer, anche nei nodi parcheggiati (dormienti). "
        "Niente viene mai cancellato: viene solo messo da parte.",
        "Quando sai che una cosa c'era e 'query' non la trova più: probabilmente "
        "è stata parcheggiata perché nessuno la consultava da mesi.",
        "Searches EVERY layer, parked (dormant) nodes included. Nothing is ever "
        "deleted here — only set aside.",
        "When you know something was there and 'query' no longer finds it: it has "
        "most likely been parked after months without being consulted.",
    ),
    ("neurag", "park"): (
        "Elenca i nodi rimasti inattivi abbastanza a lungo da scendere a un layer "
        "dormiente. NON tocca niente finché non passi --apply.",
        "Su un vault grosso e vecchio, per togliere dalla scansione di default "
        "quello che non risponde più a nessuno. Un nodo parcheggiato resta "
        "raggiungibile con 'recall': lancialo prima senza --apply e leggi la lista.",
        "Lists nodes idle long enough to drop to a dormant layer. Changes NOTHING "
        "unless you pass --apply.",
        "On a large, old vault, to take what no longer answers anything out of the "
        "default scan. A parked node stays reachable through 'recall' — run it "
        "without --apply first and read the list.",
    ),
    ("neurag", "unpark"): (
        "Riporta un nodo dormiente nel vault attivo.",
        "Quando 'park' ha messo da parte qualcosa che ti serve ancora: torna nella "
        "ricerca normale, senza dover usare 'recall' ogni volta.",
        "Brings a dormant node back into the active vault.",
        "When 'park' set aside something you still need: it returns to ordinary "
        "search instead of needing 'recall' every time.",
    ),
    ("neurag", "decay"): (
        "Indebolisce il peso dei collegamenti e la salienza dei tag in base al "
        "tempo passato dall'ultima esecuzione. Non cancella nulla: le rotte "
        "sbiadiscono, non spariscono.",
        "Manutenzione periodica su un vault vivo: quello che usi si rinforza da "
        "solo a ogni ricerca, quello che non usi arretra. Lanciarlo due volte di "
        "fila non raddoppia l'effetto.",
        "Weakens link weights and tag salience by the time elapsed since the last "
        "run. Deletes nothing: routes get fainter, they never disappear.",
        "Periodic upkeep on a live vault: what you use reinforces itself on every "
        "search, what you don't recedes. Running it twice in a row does not "
        "double the effect.",
    ),
    ("neurag", "tree"): (
        "Mostra la gerarchia dei nodi di conoscenza.",
        "Per orientarti nel vault e capire dove finirà un nuovo documento.",
        "Shows the hierarchy of knowledge nodes.",
        "To get your bearings in the vault and see where a new document will land.",
    ),
    ("neurag", "health"): (
        "Controllo di integrità strutturale del vault: orfani, gerarchia rotta, chunk vuoti.",
        "Dopo un ingest grosso, o quando le risposte peggiorano senza motivo apparente.",
        "Structural integrity check of the vault: orphans, broken hierarchy, empty chunks.",
        "After a large ingest, or when answers get worse for no obvious reason.",
    ),
    ("neurag", "doctor"): (
        "Fotografia dell'ambiente: tier di storage, embedder, stato del gateway.",
        "Quando la ricerca sembra debole: spesso l'embedder è degradato al fallback lessicale.",
        "Environment snapshot: storage tier, embedder, gateway status.",
        "When search feels weak — often the embedder has degraded to the lexical fallback.",
    ),
    ("neurag", "ingest"): (
        "Grafizza una cartella in automatico: nodi dalla struttura, chunk, embedding e link. Dai solo il percorso.",
        "Il modo normale di riempire il vault. Preferiscilo ad add-node/add-chunks a mano.",
        "Graphs a folder automatically: nodes from its structure, chunks, embeddings and links. Just give it a path.",
        "The normal way to fill the vault. Prefer it over add-node/add-chunks by hand.",
    ),
    ("neurag", "reindex"): (
        "Ricalcola i vettori di TUTTI i chunk con il modello di embedding attivo. "
        "Testo, nodi e link non vengono toccati e i file sorgente non servono.",
        "Dopo aver cambiato embed_model: i vettori di due modelli non sono "
        "confrontabili, quindi finché non rifai l'indice la ricerca semantica "
        "restituisce rumore. Se invece hai cambiato la DIMENSIONE dei chunk, usa "
        "'ingest' (ri-spezzetta leggendo i file).",
        "Recomputes the vectors for EVERY chunk with the active embedding model. "
        "Text, nodes and links are untouched, and the source files are not needed.",
        "After changing embed_model: vectors from two models are not comparable, so "
        "semantic search returns noise until the vault is rebuilt. If you changed the "
        "chunk SIZE instead, use 'ingest' (it re-chunks from the files).",
    ),
    ("neurag", "chunk"): (
        "Prova di spezzettamento di un file o cartella. Non salva nulla.",
        "Prima di un ingest, per vedere come verrebbe tagliato un documento.",
        "Dry-run chunking of a file or folder. Saves nothing.",
        "Before an ingest, to see how a document would be split.",
    ),
    ("neurag", "add-node"): (
        "Aggiunge un nodo alla gerarchia di conoscenza.",
        "Per costruire la struttura a mano. Con 'ingest' i nodi nascono da soli.",
        "Adds a node to the knowledge hierarchy.",
        "To build the structure by hand. With 'ingest' the nodes appear on their own.",
    ),
    ("neurag", "add-chunks"): (
        "Aggancia chunk (JSON da file o stdin) a un nodo esistente.",
        "Per contenuto che non viene da un file su disco.",
        "Attaches chunks (JSON from a file or stdin) to an existing node.",
        "For content that does not come from a file on disk.",
    ),
    ("neurag", "import"): (
        "Importa una cartella intera secondo una mappa YAML.",
        "Quando vuoi decidere tu la gerarchia invece di lasciarla dedurre a 'ingest'.",
        "Imports a whole folder following a YAML mapping.",
        "When you want to decide the hierarchy yourself instead of letting 'ingest' infer it.",
    ),
    ("neurag", "rename-node"): (
        "Rinomina un nodo (i path dei figli si aggiornano da soli).",
        "Per correggere un nome senza dover reimportare il sottoalbero.",
        "Renames a node (children's paths update themselves).",
        "To fix a name without re-importing the subtree.",
    ),
    ("neurag", "remove-node"): (
        "Elimina un nodo e tutto il suo sottoalbero, chunk compresi.",
        "Distruttivo e senza annulla: controlla prima con 'tree'.",
        "Deletes a node and its whole subtree, chunks included.",
        "Destructive and cannot be undone: check with 'tree' first.",
    ),
    ("neurag", "config"): (
        "Configurazione NeuRAG: rerank on/off, pool, modello embedder.",
        "Il rerank migliora la precisione e costa tempo: accendilo se le risposte sono imprecise. Parti da action=list.",
        "NeuRAG configuration: rerank on/off, pool, embedder model.",
        "Rerank improves precision and costs time: turn it on if answers are imprecise. Start with action=list.",
    ),
    ("neurag", "register"): (
        "Registra NeuRAG come MCP DIRETTO nei client (standalone, senza gateway).",
        "Solo se non usi Gray Matter: con il gateway attivo crea una doppia registrazione.",
        "Registers NeuRAG as a DIRECT MCP server in your clients (standalone, no gateway).",
        "Only if you are not using Gray Matter: with the gateway active this creates a double registration.",
    ),
    ("neurag", "deregister"): (
        "Rimuove NeuRAG dai config dei client AI.",
        "Per togliere la sola knowledge base, lasciando il resto dov'è.",
        "Removes NeuRAG from your AI clients' configs.",
        "To remove the knowledge base alone, leaving everything else in place.",
    ),
    ("neurag", "go-standalone"): (
        "NeuRAG esce dal gateway e si registra come MCP diretto nei client.",
        "Per usare solo la knowledge base, senza memoria. Reversibile con 'gray-matter link'.",
        "NeuRAG leaves the gateway and registers as a direct MCP server in your clients.",
        "To use the knowledge base alone, without memory. Undo with 'gray-matter link'.",
    ),
    ("neurag", "start"): (
        "Avvia il server NeuRAG in background (MCP stdio).",
        "Raramente a mano: con il gateway ci pensa Gray Matter.",
        "Starts the NeuRAG server in the background (MCP stdio).",
        "Rarely by hand — with the gateway, Gray Matter handles it.",
    ),
    ("neurag", "stop"): (
        "Ferma il server NeuRAG.",
        "Prima di un aggiornamento, o per liberare il database.",
        "Stops the NeuRAG server.",
        "Before an update, or to release the database.",
    ),
    ("neurag", "repair"): (
        "Reinstall pulito SOLO di NeuRAG: scegli cosa cancellare (conoscenza, config), poi reinstalla forzato.",
        "Quando è NeuRAG a essere rotto e non vuoi toccare Neuron né il gateway.",
        "Clean reinstall of NeuRAG ONLY: pick what to delete (knowledge, config), then force-reinstall.",
        "When NeuRAG is the broken one and you do not want to touch Neuron or the gateway.",
    ),
    ("neurag", "uninstall"): (
        "Deregistra NeuRAG dai client AI e, se lo chiedi, cancella il database della conoscenza.",
        "Quando vuoi togliere solo NeuRAG. Il vault resta se non chiedi di cancellarlo.",
        "Deregisters NeuRAG from your AI clients and, if you ask, deletes the knowledge database.",
        "When you want to remove NeuRAG only. The vault stays unless you ask to delete it.",
    ),
}


def doc_for(key: "tuple[str, str]", lang: str = "it") -> "tuple[str, str]":
    """(cosa fa, quando serve) per un comando, nella lingua chiesta.

    ("", "") se il comando non è ancora documentato: chi chiama ricade sul
    testo argparse, così un subcomando nuovo compare comunque nella GUI.
    """
    entry = DOCS.get(key)
    if not entry:
        return "", ""
    what_it, when_it, what_en, when_en = entry
    return (what_en, when_en) if lang == "en" else (what_it, when_it)



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


def _python() -> str:
    """Return the current Python executable path."""
    import sys
    return sys.executable or "python"


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


def environments(lang: str = "it") -> list[dict]:
    """Gli ambienti con lo stato reale della macchina. Mai solleva: un tool rotto
    compare come non-installato invece di far fallire tutta la GUI.

    lang: lingua delle descrizioni ("it" | "en") — la sceglie chi chiama, cioè
    la GUI, che sa quale lingua ha selezionato l'utente.

    Discovery order:
    1. GME folder (centralized registry)
    2. find_spec() fallback (existing behavior)
    """
    try:
        from gray_matter.gme import list_tools as gme_list_tools
        gme_tools = {t["key"]: t for t in gme_list_tools()}
    except ImportError:
        gme_tools = {}  # gme.py not available, fallback to find_spec
    
    out = []
    for env in ENVIRONMENTS:
        gme = gme_tools.get(env["key"])
        
        # Determine if installed
        if gme and gme.get("status") == "installed":
            present = True
            python_path = gme.get("python") or _python()
        else:
            present = _installed(env["module"])
            python_path = _python()
        
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
            what, when = doc_for(key, lang)
            # il testo argparse resta il fallback: un subcomando nuovo compare
            # nella GUI anche prima che qualcuno lo abbia descritto qui.
            c["help"] = what or c["help"]
            c["when"] = when
            c["interactive"] = key in INTERACTIVE
        
        # Version: prefer GME, fallback to _version()
        if gme and gme.get("version"):
            version = gme["version"]
        elif present:
            version = _version(env["module"])
        else:
            version = ""
        
        out.append({
            "key": env["key"], "label": env["label"], "subtitle": env["subtitle"],
            "installed": present, "version": version,
            "venv": gme.get("venv") if gme else None,
            "python": python_path,
            "linked_to": gme.get("linked_to") if gme else None,
            "commands": sorted(commands, key=lambda c: (
                [g[0] for g in GROUPS].index(c["group"])
                if c["group"] in [g[0] for g in GROUPS] else 99, c["name"])),
            "error": error or (gme.get("error") if gme else None),
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

    # Ogni voce di DOCS deve avere tutte e quattro le parti piene: una lingua a
    # metà è peggio di una assente, perché la GUI la mostra comunque.
    for key, entry in DOCS.items():
        assert len(entry) == 4, key
        for part in entry:
            assert part and part.strip(), f"{key}: pezzo vuoto in DOCS"

    # Nessun comando visibile deve restare senza guida scritta, in NESSUNA
    # delle due lingue: è il controllo che tiene onesto "tutti i comandi
    # documentati" quando qualcuno ne aggiunge uno nuovo alla CLI.
    for lang in ("it", "en"):
        for e in environments(lang):
            for c in e["commands"]:
                key = (e["key"], c["name"])
                assert key in DOCS, f"comando senza guida [{lang}]: {key}"
                assert c["when"], f"manca il 'quando serve' [{lang}]: {key}"

    # DOCS non deve descrivere comandi che non esistono più.
    real = {(e["key"], c["name"]) for e in envs for c in e["commands"]}
    stale = {k for k in DOCS if k[0] in {e["key"] for e in envs if e["installed"]}} - real
    assert not stale, f"DOCS descrive comandi inesistenti: {sorted(stale)}"
    print(f"catalog OK — " + ", ".join(
        f"{e['label']}: {len(e['commands'])} comandi" if e["installed"]
        else f"{e['label']}: non installato" for e in envs))


if __name__ == "__main__":
    demo()
