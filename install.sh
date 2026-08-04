#!/usr/bin/env sh
# Gray-Matter TOTAL installer for macOS & Linux — one entry point for the whole
# environment. Installs Gray-Matter plus whichever peers (Neuron, NeuRAG) sit
# next to it into ONE shared venv, registers them in your MCP clients, and opens
# the control center.
#
# One venv (not pipx-isolated) on purpose: a single interpreter must import all
# three so the client entries can point at it. pyturso installs from the
# prebuilt wheels in Neuron/vendor (--find-links) so nothing compiles.
#
#   sh install.sh            # interactive
#   sh install.sh --yes      # non-interactive
#   sh install.sh --clear    # delete the venv and rebuild from scratch (implies --force)
#
# Opt out of a peer:  GM_NO_NEURON=1  /  GM_NO_NEURAG=1
set -eu

ASSUME_YES=0
FORCE=0
CLEAR=0
# --force: repair mode — bypass the version-skip and reinstall the code even at
# the same version (pip --force-reinstall --no-deps). Used by the GUI "Ripara".
# --clear: last resort — throw the venv away and rebuild, then install as usual.
# For the states no reinstall repairs: a half-written venv, a broken interpreter,
# a dependency pinned wrong. CODE only: graphs, knowledge.db, bridges and the GME
# registry are user data and live outside the venv (those are `repair`/`uninstall`).
for a in "$@"; do case "$a" in
    -y|--yes) ASSUME_YES=1 ;;
    -f|--force) FORCE=1 ;;
    -c|--clear) CLEAR=1; FORCE=1 ;;
esac; done
FORCE_ARGS=""
[ "$FORCE" = "1" ] && FORCE_ARGS="--force-reinstall --no-deps"
ask() {
    [ "$ASSUME_YES" = "1" ] && return 0
    [ -t 0 ] || return 1
    printf '%s [Y/n] ' "$1"; read -r ans
    case "$ans" in ""|y|Y|yes|YES|s|si) return 0 ;; *) return 1 ;; esac
}

find_python() {
    for c in python3.12 python3.11 python3.13 python3.10 python3.14 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            v=$("$c" -c 'import sys;print("%d%02d"%sys.version_info[:2])' 2>/dev/null || echo 0)
            [ "$v" -ge 310 ] 2>/dev/null && { command -v "$c"; return 0; }
        fi
    done
    return 1
}

PY=$(find_python || true)
# Click-and-go bootstrap: se Python manca, prova il package manager di sistema
# (con consenso), poi ricontrolla. Ultimo fallback: pointer a python.org.
if [ -z "${PY:-}" ]; then
    echo "Python 3.10+ not found."
    if command -v brew >/dev/null 2>&1 && ask "Install Python via Homebrew?"; then
        brew install python@3.12 || true
    elif command -v apt-get >/dev/null 2>&1 && ask "Install Python via apt (sudo)?"; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip || true
    elif command -v dnf >/dev/null 2>&1 && ask "Install Python via dnf (sudo)?"; then
        sudo dnf install -y python3 || true
    fi
    PY=$(find_python || true)
fi
[ -z "${PY:-}" ] && { echo "ERROR: need Python 3.10+ — install from https://www.python.org/downloads/ and re-run."; exit 1; }
echo "Using: $PY ($("$PY" --version 2>&1))"

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
# Il repo GM (zip GitHub) BUNDLE-A entrambi i tool come sottocartelle: cercali
# prima DENTRO il repo ($HERE), poi come sibling ($ROOT, checkout multi-repo).
# La cartella si IDENTIFICA dal pyproject, non dal nome. Confrontare il nome
# esatto rendeva INVISIBILE, in silenzio, ogni peer scaricato come zip: GitHub
# estrae in Neuron-master, neurag-main, gray-matter-main; uno zip di release in
# neurag-1.3.1. È così che una full-suite finiva con Neuron installato e NeuRAG
# no, senza un messaggio, perché "peer assente" è uno stato legittimo.
project_name() {  # $1 = dir → stampa il nome del pacchetto dichiarato
    [ -f "$1/pyproject.toml" ] || return 1
    sed -n 's/^[[:space:]]*name[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$1/pyproject.toml" 2>/dev/null | head -1 | tr 'A-Z_' 'a-z-'
}
find_peer_in() {  # $1 = nome pacchetto, $2 = parent
    [ -d "$2" ] || return 1
    for d in "$2/$1" "$2/$(printf '%s' "$1" | cut -c1 | tr 'a-z' 'A-Z')$(printf '%s' "$1" | cut -c2-)"; do
        if [ -f "$d/pyproject.toml" ] && [ "$(project_name "$d")" = "$1" ]; then
            echo "$d"; return 0
        fi
    done
    for d in "$2"/*/; do
        [ -d "$d" ] || continue
        if [ "$(project_name "${d%/}" 2>/dev/null || true)" = "$1" ]; then
            echo "${d%/}"; return 0
        fi
    done
    return 1
}
find_peer() {  # $1 = nome pacchetto → stampa il path se esiste
    find_peer_in "$1" "$HERE" || find_peer_in "$1" "$ROOT" || return 1
}


NEURON_DIR=$(find_peer neuron || true)
NEURAG_DIR=$(find_peer neurag || true)
# Wheel offline (pyturso non ha wheel win_amd64 su PyPI): si prendono da OGNI
# vendor presente, non da quella di Neuron. I tre tool sono standalone — dare per
# scontata neuron/vendor lasciava un install GM+NeuRAG senza wheel. pip accetta
# --find-links ripetuto: si passano tutte, vince chi ha la wheel giusta.
FINDLINKS=""
for _d in "$HERE" "$NEURON_DIR" "$NEURAG_DIR"; do
    [ -n "$_d" ] && [ -d "$_d/vendor" ] && FINDLINKS="$FINDLINKS --find-links $_d/vendor"
done

# Il venv sta sotto gm_home() (paths.py: <base>/graymatter) come tutto il resto di
# GM: era l'UNICA cosa in `<base>/gray-matter/`, due cartelle quasi omonime per lo
# stesso prodotto. GM_HOME è la BASE, come in paths.py — qui era letto come la
# cartella gray-matter stessa, quindi la stessa variabile spediva venv e config in
# posti scollegati; e XDG_DATA_HOME veniva ignorato solo qui.
# Un install ESISTENTE non viene migrato (un venv non è spostabile, e i client MCP
# registrati puntano al vecchio interprete): resta valido dov'è e converge al
# prossimo --clear.
OS_BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
# Radice UNICA della suite; GM_HOME resta l'override e vale gia' la radice suite.
GM_BASE="${GM_HOME:-$OS_BASE/GrayMatterEnvironment}"
VENV="$GM_BASE/graymatter/.venv"
# Le due posizioni precedenti: un venv non e' spostabile, se ce n'e' gia' uno lo
# si usa e converge alla nuova al primo --clear.
for _old in "$OS_BASE/graymatter/.venv" "$OS_BASE/gray-matter/.venv"; do
    if [ -d "$_old" ] && [ ! -d "$VENV" ]; then VENV="$_old"; break; fi
done
# INSTALLER-UX §5.3 — stop what runs from this venv before pip writes to it.
# POSIX unlinks mapped files happily, so this is not the Windows lock that makes
# pip fail there; the hazard here is a stale server writing to the same store
# mid-upgrade. Kept as a function called at the SAME three points as
# Stop-VenvProcesses in install.ps1: an MCP client respawns its stdio server
# while the user reads an interactive prompt, so one call at the top is not
# enough — and the two GM installers must stay readable as the same script.
stop_venv_procs() {
    command -v pkill >/dev/null 2>&1 || return 0
    pkill -f "$VENV" 2>/dev/null && sleep 1
    return 0
}
stop_venv_procs
if [ "$CLEAR" = "1" ] && [ -d "$VENV" ]; then
    echo "Clear: removing the venv and rebuilding from scratch ($VENV)"
    echo "  (user memory is NOT touched — graphs, knowledge.db and bridges live elsewhere)"
    rm -rf "$VENV"
    [ -d "$VENV" ] && { echo "ERROR: could not remove $VENV — stop any running Gray Matter/Neuron process and re-run."; exit 1; }
fi
# Un venv "c'e'" solo se il suo interprete PARTE. `[ -d ]` sulla cartella non e'
# quel test: una rimozione interrotta lascia lib/ e bin/ senza pyvenv.cfg, la
# creazione viene saltata e il primo pip muore con "failed to locate pyvenv.cfg".
# Stessa guardia di Test-VenvHealthy in install.ps1.
venv_healthy() {  # $1 = venv
    [ -f "$1/pyvenv.cfg" ] || return 1
    [ -x "$1/bin/python" ] || return 1
    "$1/bin/python" -c "import sys" >/dev/null 2>&1
}
if [ -d "$VENV" ] && ! venv_healthy "$VENV"; then
    echo "Damaged venv detected (pyvenv.cfg missing or interpreter dead) - rebuilding"
    rm -rf "$VENV"
fi
# venv: Plan A stdlib venv, Plan B virtualenv, else EXIT with guidance.
if [ ! -d "$VENV" ]; then
    "$PY" -m venv "$VENV" 2>/dev/null || "$PY" -m virtualenv "$VENV" 2>/dev/null || true
    venv_healthy "$VENV" || { echo "ERROR: could not create a working venv at $VENV - install python3-venv (or 'pip install virtualenv') and re-run."; exit 1; }
fi
VPY="$VENV/bin/python"
# pip self-upgrade is non-critical: never let it abort the install.
"$VPY" -m pip install --upgrade pip >/dev/null 2>&1 || echo "  (pip self-upgrade skipped — continuing)"

# Idempotenza VISIBILE (fix 2026-07-21): se la versione installata è già quella
# del sorgente, si SALTA il pip install (niente rebuild muto a ogni re-run).
src_ver() { sed -n 's/^version *= *"\(.*\)".*/\1/p' "$1/pyproject.toml" | head -1; }
already_installed() {  # $1 = pkg pip, $2 = dir sorgente
    v=$(src_ver "$2"); [ -n "$v" ] || return 1
    i=$("$VPY" -c "import importlib.metadata as m;print(m.version('$1'))" 2>/dev/null) || return 1
    [ "$i" = "$v" ]
}

if [ "$FORCE" != "1" ] && already_installed gray-matter "$HERE"; then
    echo "Gray-Matter $(src_ver "$HERE") already installed — skipping."
else
    [ "$FORCE" = "1" ] && echo "Repair: reinstalling Gray-Matter (forced)..." || echo "Installing Gray-Matter..."
    # Plan A: with vendored wheels. Plan B: retry without --find-links (a stale/absent
    # vendor wheel must not block a source install). Plan C: EXIT — GM is the required
    # gateway, nothing works without it.
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS $FORCE_ARGS "$HERE" \
        || "$VPY" -m pip install $FORCE_ARGS "$HERE" \
        || { echo "ERROR: gray-matter install failed (the required gateway). Check network/Python and re-run."; exit 1; }
fi

# GM_PEER_DIR set → coupled mode (called from Neuron/install.sh or NeuRAG):
# install GM + the calling peer, then detect and ask about other siblings.
install_peer() {  # $1 = dir sorgente, $2 = nome per i messaggi
    pkg=$(basename "$1" | tr '[:upper:]' '[:lower:]')
    if [ "$FORCE" != "1" ] && already_installed "$pkg" "$1"; then
        echo "$2 $(src_ver "$1") already installed — skipping."
        return 0
    fi
    [ "$FORCE" = "1" ] && echo "Repair: reinstalling $2 (forced)..." || echo "Installing $2 ($1)..."
    stop_venv_procs                 # same respawn window as install.ps1
    # Peers share GM's venv and install after it, so a peer with looser pins can
    # pull a shared dep past GM's cap (an old Neuron with an uncapped
    # `mcp>=1.28` dragged in mcp 2.x and broke GM's server import). pip only
    # warns and exits 0 — feed the peer's own caps, and see the pip check below.
    CONS=""; [ -f "$1/constraints.txt" ] && CONS="-c $1/constraints.txt"
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS $CONS $FORCE_ARGS "$1" \
        || "$VPY" -m pip install $CONS $FORCE_ARGS "$1" \
        || echo "  WARNING: $2 install failed — continuing."
}

if [ -n "${GM_PEER_DIR:-}" ] && [ -f "$GM_PEER_DIR/pyproject.toml" ]; then
    # Coupled mode: called from Neuron or NeuRAG installer.
    # Always install GM + the calling peer, then detect other siblings and ask.
    [ -d "$GM_PEER_DIR/vendor" ] && FINDLINKS="$FINDLINKS --find-links $GM_PEER_DIR/vendor"
    PEER_LABEL=$(basename "$GM_PEER_DIR")
    install_peer "$GM_PEER_DIR" "$PEER_LABEL"
    # Detect other peers as siblings of the calling peer's parent
    PEER_PARENT=$(dirname "$GM_PEER_DIR")
    OTHER_PEERS=""
    case "$PEER_LABEL" in
        neuron|Neuron)
            _d=$(find_peer_in neurag "$PEER_PARENT" 2>/dev/null || true)
            [ -n "$_d" ] && OTHER_PEERS="$_d:NeuRAG"
            ;;
        neurag|Neurag)
            _d=$(find_peer_in neuron "$PEER_PARENT" 2>/dev/null || true)
            [ -n "$_d" ] && OTHER_PEERS="$_d:Neuron"
            ;;
    esac
    for _entry in $OTHER_PEERS; do
        _dir="${_entry%%:*}"
        _label="${_entry##*:}"
        if already_installed "$_label" "$_dir" 2>/dev/null; then
            echo ""
            echo "  $_label $(src_ver "$_dir") detected alongside $PEER_LABEL."
        else
            echo ""
            echo "  $_label source found alongside $PEER_LABEL."
        fi
        printf "  [Y]es — add %s to the suite\n" "$_label"
        printf "  [N]o  — keep %s standalone\n" "$PEER_LABEL"
        printf "  Include %s? [Y] " "$_label"
        read -r _ans
        case "$_ans" in
            n|N|no|NO)
                echo "  Skipping $_label."
                ;;
            *)
                install_peer "$_dir" "$_label"
                ;;
        esac
    done
else
    # Full suite mode — tools bundled INSIDE the GM repo zip, or siblings.
    #
    # GM è l'ORCHESTRATORE: se un peer manca se lo scarica, non si limita a dire
    # all'utente di clonarselo. Prima era il contrario e non aveva senso — un
    # peer (neuron/install.sh) sa tirarsi dentro GM con tre fallback, mentre GM,
    # l'unico che dichiara di installare la full suite, stampava un messaggio e
    # proseguiva a metà. Nessun tag fisso: il branch di default è quello che la
    # CI dei peer testa, e una costante da allineare a mano è la deriva che il
    # guard su GM_VERSION ha appena chiuso. Ogni passo degrada: git → zip → avviso.
    peer_repo() { case "$1" in neuron) echo "recla93/Neuron" ;; neurag) echo "recla93/neurag" ;; esac; }

    report_missing_peer() {  # $1 = label, $2 = dir repo, $3 = url
        echo ""
        echo "  [i] $1 not found next to Gray Matter — it will NOT be installed."
        echo "      Gray Matter works on its own, with that half of the memory missing."
        echo "      To add it: clone $3 into a '$2' folder next to this one,"
        echo "      then run this installer again."
    }

    fetch_peer() {  # $1 = pacchetto, $2 = label → stampa il path, o niente
        _repo=$(peer_repo "$1"); _target="$ROOT/$1"
        echo "" >&2
        echo "  $2 non è accanto a Gray Matter: lo scarico ($_repo)." >&2
        if command -v git >/dev/null 2>&1; then
            if git clone --depth 1 "https://github.com/$_repo.git" "$_target" >&2 2>&1; then
                _d=$(find_peer_in "$1" "$ROOT" || true)
                [ -n "$_d" ] && { echo "      [OK] $2 in $_d" >&2; echo "$_d"; return 0; }
            fi
            rm -rf "$_target"
            echo "      git clone non utilizzabile - provo lo zip." >&2
        fi
        # zip del branch di default: main e master entrambi, invece di incollare
        # qui il branch di ogni repo (si sposta senza avvisare). Lo zip estrae in
        # <repo>-<branch> e find_peer lo riconosce dal pyproject, quindi il
        # rename è un di più, non un requisito.
        for _b in main master; do
            _tmp=$(mktemp -d); _zip="$_tmp/$1.zip"
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL -o "$_zip" "https://github.com/$_repo/archive/refs/heads/$_b.zip" 2>/dev/null || true
            elif command -v wget >/dev/null 2>&1; then
                wget -qO "$_zip" "https://github.com/$_repo/archive/refs/heads/$_b.zip" 2>/dev/null || true
            fi
            if [ -s "$_zip" ] && command -v unzip >/dev/null 2>&1 && unzip -q "$_zip" -d "$_tmp" 2>/dev/null; then
                _ex=$(find "$_tmp" -maxdepth 2 -name pyproject.toml -exec dirname {} \; 2>/dev/null | head -1)
                if [ -n "$_ex" ]; then
                    # rename best-effort: se fallisce si usa dov'è, invece di
                    # buttare via il download
                    if mv "$_ex" "$_target" 2>/dev/null; then _dest="$_target"; else _dest="$_ex"; fi
                    if [ "$(project_name "$_dest" 2>/dev/null || true)" = "$1" ]; then
                        echo "      [OK] $2 in $_dest" >&2; echo "$_dest"; return 0
                    fi
                fi
            fi
            rm -rf "$_tmp"
        done
        return 1
    }

    resolve_peer() {  # $1 = pacchetto, $2 = label, $3 = dir gia' trovata
        [ -n "$3" ] && { echo "$3"; return 0; }
        _f=$(fetch_peer "$1" "$2" || true)
        [ -n "$_f" ] && { echo "$_f"; return 0; }
        echo "      download non riuscito (rete/git assenti?)." >&2
        report_missing_peer "$2" "$1" "https://github.com/$(peer_repo "$1")" >&2
        return 1
    }

    if [ -z "${GM_NO_NEURON:-}" ]; then
        NEURON_DIR=$(resolve_peer neuron "Neuron (semantic memory)" "$NEURON_DIR" || true)
        if [ -n "$NEURON_DIR" ]; then
            [ -d "$NEURON_DIR/vendor" ] && FINDLINKS="$FINDLINKS --find-links $NEURON_DIR/vendor"
            install_peer "$NEURON_DIR" "Neuron"
        fi
    fi
    if [ -z "${GM_NO_NEURAG:-}" ]; then
        NEURAG_DIR=$(resolve_peer neurag "NeuRAG (knowledge base)" "$NEURAG_DIR" || true)
        if [ -n "$NEURAG_DIR" ]; then
            [ -d "$NEURAG_DIR/vendor" ] && FINDLINKS="$FINDLINKS --find-links $NEURAG_DIR/vendor"
            install_peer "$NEURAG_DIR" "NeuRAG"
        fi
    fi
fi

# Last stop before the dependency phase (pyturso / fastembed write into
# site-packages). Mirrors install.ps1.
stop_venv_procs

# Best-effort turso tier: prova le wheel vendored (Neuron/vendor o vendor del
# peer), poi PyPI (mac/linux le ha). Se fallisce NON è un errore: NeuRAG e
# Neuron degradano al tier sqlite3 e funzionano comunque.
if ! "$VPY" -c "import turso" >/dev/null 2>&1; then
    echo "Enabling the Turso vector tier (best-effort)..."
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS "pyturso==0.6.1" \
        || echo "  pyturso not available here — running on the sqlite3 tier (still fully functional)."
fi

# Best-effort semantic tier: fastembed = retrieval preciso sul vault
# multi-disciplinare (meno chunk, meno token). Come pyturso: mai bloccante,
# senza si degrada al lessicale TF-IDF.
if ! "$VPY" -c "import fastembed" >/dev/null 2>&1; then
    echo "Enabling the semantic embedding tier (best-effort)..."
    "$VPY" -m pip install "fastembed>=0.5.0,<1.0" \
        || echo "  fastembed not available — lexical ranking only (still functional)."
fi

# Gateway model (INSTALLER-UX): register ONLY gray-matter, deploy hooks, manifest.
echo "Installing the gateway (register + hooks + manifest)..."
# Embedding model — asked HERE because the full-suite path installs Neuron
# without ever running Neuron's own installer, so these users were never given
# the choice. Keep in sync with $EmbedModels in install.ps1 and with
# neuron/install.sh.
GM_EM_1="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2|384|220 MB|multilingual (EN+IT) - default"
GM_EM_2="sentence-transformers/all-MiniLM-L6-v2|384|90 MB|English only - smallest and fastest"
GM_EM_3="sentence-transformers/paraphrase-multilingual-mpnet-base-v2|768|1.0 GB|multilingual, stronger"
GM_EM_4="intfloat/multilingual-e5-large|1024|2.2 GB|multilingual, best quality - heavy"
GM_MODEL=""; GM_DIM=""; GM_SIZE=""
_gm_set() { GM_MODEL="${1%%|*}"; _r="${1#*|}"; GM_DIM="${_r%%|*}"; _r="${_r#*|}"; GM_SIZE="${_r%%|*}"; }
gm_select_embed_model() {
    if [ -n "${GM_EMBED_MODEL:-}" ]; then
        for e in "$GM_EM_1" "$GM_EM_2" "$GM_EM_3" "$GM_EM_4"; do
            [ "${e%%|*}" = "$GM_EMBED_MODEL" ] && { _gm_set "$e"; return; }
        done
        GM_MODEL="$GM_EMBED_MODEL"; GM_DIM=0; GM_SIZE="?"; return
    fi
    if [ ! -t 0 ]; then _gm_set "$GM_EM_1"; return; fi
    echo ""
    echo "  Embedding model (downloaded once, defines the memory's vector space):"
    i=1
    for e in "$GM_EM_1" "$GM_EM_2" "$GM_EM_3" "$GM_EM_4"; do
        _rest="${e#*|}"; _d="${_rest%%|*}"; _rest="${_rest#*|}"; _sz="${_rest%%|*}"; _n="${_rest#*|}"
        echo "    [$i] $_n"
        echo "        ${e%%|*}  (${_d}-dim, ${_sz})"
        i=$((i + 1))
    done
    echo ""
    echo "  Changing this later requires re-embedding the whole store."
    printf "  Choice [1]: "; read -r mc || mc=""
    case "$mc" in
        2) _gm_set "$GM_EM_2" ;; 3) _gm_set "$GM_EM_3" ;; 4) _gm_set "$GM_EM_4" ;;
        *) _gm_set "$GM_EM_1" ;;
    esac
}
gm_save_embed_model() {   # $1 = venv python
    # Never fatal (set -e is on): the model is refetched lazily on first use.
    # Via environment, non interpolato nel sorgente: un nome modello con un
    # apostrofo chiudeva la stringa Python e la scelta spariva dietro il
    # generico "not saved" (stessa correzione in install.ps1).
    GM_EMBED_NAME="$GM_MODEL" GM_EMBED_DIM="$GM_DIM" "$1" -c "import os
from neuron.config import set_user_env
print(set_user_env(NS_EMBED_MODEL=os.environ['GM_EMBED_NAME'], NS_EMBED_DIM=os.environ['GM_EMBED_DIM']))" >/dev/null 2>&1 || {
        echo "  (embedding model choice not saved - default stays active)"; return 0; }
    echo ""
    echo "  Downloading the embedding model ($GM_SIZE, one-time)."
    echo "  Large models take several minutes - this is NOT frozen."
    if HF_HUB_DISABLE_PROGRESS_BARS=1 "$1" -W ignore -c "from neuron.server import _get_embedder
_get_embedder()
print('EMBED_MODEL_READY')" 2>&1 | sed 's/^/    /'; then
        echo "  [OK] $GM_MODEL cached."
    else
        echo "  [!] download failed - Neuron retries on first use (install continues)."
    fi
}

# Embedding model for Neuron (full-suite users never see neuron/install.sh).
if [ -n "$NEURON_DIR" ]; then
    gm_select_embed_model
    gm_save_embed_model "$VPY"
fi

# Where to register: GM_CLIENT wins, else ask on a tty, else "detected" (never
# touches a client the user does not have).
if [ -n "${GM_CLIENT:-}" ]; then CLIENT_SEL="$GM_CLIENT"
elif [ -t 0 ]; then CLIENT_SEL="ask"
else CLIENT_SEL="detected"; fi
# Dice a `cli install` che il padrone dell'ultima parola è questo script: il suo
# "Done. Restart your AI apps." finiva in MEZZO all'output (peer, modello, icona)
# e un log in cui un passo dopo falliva si leggeva come "finito, poi esploso".
# Trasloco sotto la radice unica PRIMA di registrare: se i dati si spostano
# dopo, manifest e registro puntano gia' ai path vecchi.
"$VPY" -c "from gray_matter.paths import migrate_to_suite_root
for r in migrate_to_suite_root():
    print(('  [OK] ' if r['ok'] else '  [!] ') + r['from'] + ' -> ' + r['to'] + '  ' + r['detail'])" || true

# Cosa c'era gia' e se e' allineato — vedi la nota in install.ps1.
"$VPY" -m gray_matter.preflight || true

export GM_INSTALLER=1
"$VPY" -m gray_matter.cli install --client "$CLIENT_SEL" \
    || "$VPY" -m gray_matter.cli register --gateway --client "$CLIENT_SEL" || true

# Registro path sorgente (SoC): ogni componente registra il PROPRIO sorgente nel
# proprio registro; GM li scopre chiedendo ai peer. Riscritto a ogni install.
"$VPY" -m gray_matter.cli record-env --gm "$HERE" >/dev/null 2>&1 || true
[ -n "$NEURON_DIR" ] && "$VPY" -m neuron record-paths --source "$NEURON_DIR" >/dev/null 2>&1 || true
[ -n "$NEURAG_DIR" ] && "$VPY" -m neurag.cli record-paths --source "$NEURAG_DIR" >/dev/null 2>&1 || true

# --- GME Registry ---
# `cli install` above already registers every tool (installer.plan emits
# register_gme). Repeated here as the safety net for its `|| cli register`
# fallback path, which writes no manifest and no registry: one line, same single
# writer, so the two can never drift the way six shell copies did.
"$VPY" -m gray_matter.gme register "$HERE" || true

# Convenience: put `gray-matter` on PATH if ~/.local/bin exists.
if [ -x "$VENV/bin/gray-matter" ] && [ -d "$HOME/.local/bin" ]; then
    ln -sf "$VENV/bin/gray-matter" "$HOME/.local/bin/gray-matter" 2>/dev/null || true
fi

# Desktop shortcut to the control center (double-clickable on macOS & most Linux).
if [ -d "$HOME/Desktop" ]; then
    SC="$HOME/Desktop/Gray-Matter-GUI.command"
    printf '#!/bin/sh\nexec "%s" -m gray_matter.cli gui\n' "$VPY" > "$SC" && chmod +x "$SC" || true
fi

echo ""
# A peer install can leave the shared venv internally inconsistent (pip prints
# "dependency resolver ... conflicts" and still exits 0), and the banner below
# then declares success over a venv whose servers crash on import.
if ! PIP_CHECK=$("$VPY" -m pip check 2>&1); then
    echo ""
    echo "  [!] The venv has conflicting dependencies - servers may fail to start:"
    echo "$PIP_CHECK" | sed 's/^/      /'
    echo "      Fix: update the offending source to a version with matching pins and re-run."
fi

# An explicit, affirmative terminator: callers could not tell "finished
# successfully" from "still working" or "died quietly".
GM_VER=$("$VPY" -m gray_matter.cli --version 2>/dev/null | tail -1)
[ -n "$GM_VER" ] || GM_VER="?"
echo ""
echo "  ============================================================"
echo "  [OK] INSTALL COMPLETE - Gray Matter $GM_VER"
echo "  ============================================================"
[ -n "$NEURON_DIR" ] && echo "  Neuron:  installed"
[ -n "$NEURAG_DIR" ] && echo "  NeuRAG:  installed"
echo "Done. Restart your AI apps to load the servers."
echo "Control center: the 'Gray-Matter-GUI' icon on your Desktop"
echo "                (or run: gray-matter gui)"
# L'installer NON apre piu' il control center da solo — keep-in-sync con
# install.ps1. Aprirlo qui significava aprirlo nel momento peggiore: subito
# dopo aver scritto venv, registrazioni e shortcut, col daemon non ancora a
# regime. Il lanciatore sul Desktop c'e': lo si apre quando si vuole.
