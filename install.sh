#!/usr/bin/env sh
# NeuRAG installer (macOS/Linux) — click-and-go, default: NeuRAG + Gray Matter
# (gateway). One shared venv, registers the gateway, opens GUI.
#
# Modes:
#   default           → install NeuRAG + GM (recommended, click-and-go)
#   --no-gm           → standalone (NeuRAG only, registers directly in clients)
#   -f / --force      → repair mode (pip --force-reinstall --no-deps)
#   -c / --clear      → last resort: delete the venv and rebuild (implies --force).
#                       CODE only — graphs/knowledge.db/bridges are never touched.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)

# 0) Parse flags. Default: install with GM (gateway mode). --no-gm = standalone.
WANT_GM=1; FORCE=0; CLEAR=0; MODE="gateway"; EMBED_MODEL=""; ASSUME_YES=0
_next_is_model=0
for a in "$@"; do
    if [ "$_next_is_model" = "1" ]; then EMBED_MODEL="$a"; _next_is_model=0; continue; fi
    case "$a" in
    --no-gm) WANT_GM=0; MODE="standalone" ;;
    -y|--yes) ASSUME_YES=1 ;;
    -f|--force) FORCE=1 ;;
    -c|--clear) CLEAR=1; FORCE=1 ;;   # clear is a stronger force
    --embed-model) _next_is_model=1 ;;
    --embed-model=*) EMBED_MODEL="${a#--embed-model=}" ;;
esac; done
[ "${GM_YES:-0}" = "1" ] && ASSUME_YES=1   # same contract as install.ps1
# --no-deps only safe once the shared deps are in the venv (see install.ps1).
has_mcp() { "$VPY" -c "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('mcp') else 1)" 2>/dev/null; }
repair_args() { if [ "$FORCE" = "1" ] && has_mcp; then echo "--force-reinstall --no-deps"; fi; }
[ "${GM_OPTIN:-1}" = "0" ] && WANT_GM=0 && MODE="standalone"

# Picking [N] is NOT the same question as "standalone forever": NeuRAG can run
# orchestrated by a GM that isn't on disk yet. So [N] asks a second question -
# stay alone, or fetch GM - instead of silently choosing the first for you.
read_neurag_only_mode() {
    echo ""
    echo "  NeuRAG only - which one?"
    echo "    [S] Full standalone - NeuRAG alone, own venv, registers itself in the clients"
    echo "    [G] Get Gray Matter - download GM next to NeuRAG, then install orchestrated"
    echo ""
    printf "  Choice [S]: "; read -r sub
    case "$sub" in g|G|gm|GM|get|gray|graymatter|gray-matter|orchestrated) return 0 ;; esac
    return 1
}
# Mode selector: click-and-go (Enter = full suite) or explicit --no-gm.
# Only shows in interactive terminals; non-interactive defaults to gateway.
if [ "$WANT_GM" = "1" ] && [ -t 0 ] && [ "$FORCE" != "1" ] && [ "$ASSUME_YES" != "1" ]; then
    echo ""
    echo "  Installation mode:"
    echo "    [F] Full suite — GM + Neuron + NeuRAG (recommended)"
    echo "    [N] NeuRAG only — standalone, or with GM fetched for you"
    echo "    [D] Details — what you lose without GM"
    echo ""
    printf "  Choice [F]: "; read -r ans
    case "$ans" in
        n|N|no|standalone)
            if read_neurag_only_mode; then MODE="gateway"    # [G]: keep WANT_GM
            else WANT_GM=0; MODE="standalone"; fi ;;
        d|D|details|DETAILS)
            echo ""
            echo "  Without GM you lose:"
            echo "    - Cross-store bridges (NeuRAG <-> Neuron)"
            echo "    - Neighbor auto-surface"
            echo "    - Unified GUI control center"
            echo "    - Auto-registration in MCP clients"
            echo ""
            printf "  Install Full suite? [Y/n] "; read -r ans2
            case "$ans2" in n|N|no|NO)
                if read_neurag_only_mode; then MODE="gateway"    # [G]: keep WANT_GM
                else WANT_GM=0; MODE="standalone"; fi ;;
            esac
            ;;
    esac
fi

# STANDALONE: only NeuRAG, its own venv. Reversible: re-run without --no-gm
# and GM takes over (gateway + bridges). Also the safety net when GM cannot
# be obtained (§6: degrade, don't exit).
# Un venv "c'e'" solo se il suo interprete PARTE. `[ -d ]` sulla cartella non e'
# quel test: una rimozione interrotta lascia lib/ e bin/ senza pyvenv.cfg, la
# creazione viene saltata e il primo pip muore con "failed to locate pyvenv.cfg".
# Stessa guardia di Test-VenvHealthy in install.ps1.
venv_healthy() {  # $1 = venv
    [ -f "$1/pyvenv.cfg" ] || return 1
    [ -x "$1/bin/python" ] || return 1
    "$1/bin/python" -c "import sys" >/dev/null 2>&1
}

# Python bootstrap. No silent-install story on macOS/Linux the way there is on
# Windows (python.org ships no unattended package here, and installing one
# system-wide behind the user's back is not ours to do) — so: accept anything
# cp310..cp314, and when nothing fits print the exact command for THIS machine
# instead of a bare link.
py_ok() {  # $1 = candidate interpreter
    [ -n "$1" ] || return 1
    "$1" -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,14) else 1)' >/dev/null 2>&1
}
find_python() {
    for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
        _p=$(command -v "$c" 2>/dev/null) || continue
        py_ok "$_p" && { echo "$_p"; return; }
    done
}
ensure_python() {
    _p=$(find_python)
    [ -n "$_p" ] && { echo "$_p"; return; }
    echo "ERROR: NeuRAG needs Python 3.10-3.14 and none was found." >&2
    if command -v brew >/dev/null 2>&1; then       echo "  Install it with:  brew install python@3.14" >&2
    elif command -v apt-get >/dev/null 2>&1; then  echo "  Install it with:  sudo apt-get install -y python3 python3-venv" >&2
    elif command -v dnf >/dev/null 2>&1; then      echo "  Install it with:  sudo dnf install -y python3" >&2
    elif command -v pacman >/dev/null 2>&1; then   echo "  Install it with:  sudo pacman -S python" >&2
    else                                            echo "  Download it from: https://www.python.org/downloads/" >&2
    fi
    echo "  Then re-run this installer." >&2
    exit 1
}

# Embedding model choice. Embedding is MANDATORY, exactly as in Neuron:
# fastembed and pyturso are hard dependencies of the package, so this install
# fails rather than proceeding without them. There used to be a "none - lexical
# only" answer here, from when fastembed was an optional extra. It outlived that
# and had to go: it contradicted the dependency (recall@5 is 67% vector-only vs
# 94% hybrid, §6b - that menu entry shipped the degraded half of the tool), and
# it did not do what it said either. It wrote embed_model = '' , and '' means
# "follow Neuron / the multilingual default", so it configured the very model it
# promised not to download. `lexical_only_requested()` looks for the literal
# string "none", which nothing ever wrote.
# Lexical-only stays reachable where an expert knob belongs:
# `neurag config set embed_model none`. Removed from the menu, not the runtime.
# The vault is EMPTY at install time, the only moment this is free: vectors of
# different models/widths are not comparable, so changing it later means
# re-indexing.
# Persisted via neurag/settings.py (the tool's own config surface), NOT an env
# var: the MCP client respawns the server from an arbitrary cwd.
# Keep in sync with $EmbedModels in install.ps1.
EM_1="|0|0 MB|Follow Neuron / default multilingual - one shared vector space (recommended)"
EM_2="sentence-transformers/all-MiniLM-L6-v2|384|90 MB|English only - smallest and fastest"
EM_3="sentence-transformers/paraphrase-multilingual-mpnet-base-v2|768|1.0 GB|multilingual, stronger - 2x storage per vector"
EM_4="intfloat/multilingual-e5-large|1024|2.2 GB|multilingual, best quality - heavy (RAM + disk)"
CHOSEN_MODEL=""; CHOSEN_DIM=""; CHOSEN_SIZE=""
_set_chosen() {
    CHOSEN_MODEL="${1%%|*}"; _r="${1#*|}"
    CHOSEN_DIM="${_r%%|*}"; _r="${_r#*|}"; CHOSEN_SIZE="${_r%%|*}"
}
select_embed_model() {
    if [ -n "$EMBED_MODEL" ]; then
        for e in "$EM_1" "$EM_2" "$EM_3" "$EM_4"; do
            [ "${e%%|*}" = "$EMBED_MODEL" ] && { _set_chosen "$e"; return; }
        done
        CHOSEN_MODEL="$EMBED_MODEL"; CHOSEN_DIM=0; CHOSEN_SIZE="?"; return
    fi
    if [ ! -t 0 ] || [ "$FORCE" = "1" ] || [ "$ASSUME_YES" = "1" ]; then _set_chosen "$EM_1"; return; fi
    echo ""
    echo "  Embedding model for the vault (downloaded once):"
    i=1
    for e in "$EM_1" "$EM_2" "$EM_3" "$EM_4"; do
        _rest="${e#*|}"; _dim="${_rest%%|*}"
        _rest="${_rest#*|}"; _size="${_rest%%|*}"; _note="${_rest#*|}"
        echo "    [$i] $_note"
        _nm="${e%%|*}"
        [ -n "$_nm" ] && echo "        $_nm  (${_dim}-dim, ${_size})"
        i=$((i + 1))
    done
    echo ""
    echo "  Changing this later requires re-indexing the whole vault."
    printf "  Choice [1]: "; read -r mc
    case "$mc" in
        2) _set_chosen "$EM_2" ;;
        3) _set_chosen "$EM_3" ;;
        4) _set_chosen "$EM_4" ;;
        *) _set_chosen "$EM_1" ;;
    esac
}
save_embed_model() {  # $1 = venv python
    _vpy="$1"
    if [ -z "$CHOSEN_MODEL" ]; then
        echo "  Embedding model: following Neuron / the multilingual default."
        return 0
    fi
    _dim="$CHOSEN_DIM"
    if [ "$_dim" = "0" ]; then
        _dim=$("$_vpy" -c "from fastembed import TextEmbedding
print(next((m['dim'] for m in TextEmbedding.list_supported_models() if m['model']=='$CHOSEN_MODEL'), 384))" 2>/dev/null || echo 384)
    fi
    NS_EMBED_NAME_SAVE="$CHOSEN_MODEL" "$_vpy" -c "import os
from neurag import settings
settings.set('embed_model', os.environ['NS_EMBED_NAME_SAVE'])
settings.set('embed_dim', $_dim)" || {
        echo "  WARNING: could not save the model choice - the default stays active."; return 0; }
    echo ""
    echo "  Downloading the embedding model ($CHOSEN_SIZE, one-time)."
    echo "  Large models take several minutes - this is NOT frozen."
    # Never fatal (set -e is on): NeuRAG degrades to lexical search rather than
    # breaking. Progress bar off - HF's tqdm redraws with a carriage return and
    # emits no newline, so a logged install looks softlocked.
    if HF_HUB_DISABLE_PROGRESS_BARS=1 "$_vpy" -W ignore -c "from neurag.embedder import get_embedder
get_embedder()
print('EMBED_MODEL_READY')" 2>&1 | sed 's/^/    /'; then
        echo "  [OK] $CHOSEN_MODEL cached."
    else
        echo "  [!] download failed - NeuRAG stays lexical until it succeeds (install continues)."
    fi
}

standalone_install() {
    echo "Installing NeuRAG STANDALONE (no Gray Matter — add it any time by re-running)."
    # Ask before the long pip phase, write after it (needs the venv's python).
    select_embed_model
    # `exit 1` inside $( ) only kills the subshell - propagate it explicitly.
    PY=$(ensure_python) || exit 1
    # Radice UNICA della suite anche in standalone — vedi la nota in install.ps1.
    _rbase="${XDG_DATA_HOME:-$HOME/.local/share}"
    NEURAG_DIR_HOME="${NEURAG_HOME:-$_rbase/GrayMatterEnvironment/neurag}"
    if [ -d "$_rbase/neurag/.venv" ] && [ ! -d "$NEURAG_DIR_HOME/.venv" ]; then
        NEURAG_DIR_HOME="$_rbase/neurag"
    fi
    VENV="$NEURAG_DIR_HOME/.venv"
    # INSTALLER-UX §5.3 — stop what runs from this venv before pip writes to it.
    # POSIX unlinks mapped files happily, so this is not the Windows lock, but a
    # stale server writing to the same store during an upgrade is its own hazard.
    if command -v pkill >/dev/null 2>&1; then
        pkill -f "$VENV" 2>/dev/null || true
        sleep 1
    fi
    if [ "$CLEAR" = "1" ] && [ -d "$VENV" ]; then
        echo "Clear: removing the venv and rebuilding from scratch ($VENV)"
        echo "  (user memory is NOT touched — it lives outside the venv)"
        rm -rf "$VENV"
        [ -d "$VENV" ] && { echo "ERROR: could not remove $VENV — stop any running NeuRAG process and re-run."; exit 1; }
    fi
    if [ -d "$VENV" ] && ! venv_healthy "$VENV"; then
        echo "Damaged venv detected (pyvenv.cfg missing or interpreter dead) - rebuilding"
        rm -rf "$VENV"
    fi
    [ -d "$VENV" ] || "$PY" -m venv "$VENV" 2>/dev/null || true
    venv_healthy "$VENV" || { echo "ERROR: could not create a working venv at $VENV - check disk space and permissions"; exit 1; }
    VPY="$VENV/bin/python"
    # Console-script fallback: a pip install that missed the entry point would
    # otherwise fail right here. Degrade to `python -m`, same as Invoke-Tool in
    # install.ps1.
    invoke_tool() {  # $1=exe, $2=module, rest=args
        _exe="$1"; _mod="$2"; shift 2
        if [ -x "$VENV/bin/$_exe" ]; then "$VENV/bin/$_exe" "$@"
        else echo "  ($_exe not found in the venv - using python -m $_mod)"
             "$VPY" -m "$_mod" "$@"; fi
    }
    "$VPY" -m pip install --upgrade pip >/dev/null 2>&1 || true
    # Senza repair_args pip risponde "already satisfied" a parita' di versione e
    # non copia niente: un fix spedito senza bump non arriva a chi reinstalla.
    # E la versione e' un'ETICHETTA che puo' mentire (dist-info nuovo sui file
    # vecchi: visto dal vivo, 72 file diversi a versione identica). Si chiede al
    # CODICE. Il confronto vero lo fa gray_matter quando c'e'; standalone si
    # ripiega su etichetta-contro-codice, che e' la parte che morde.
    code_matches() {  # $1 = modulo, $2 = dir sorgente
        "$VPY" - "$1" "$2" <<'PY' 2>/dev/null
import sys
mod, src = sys.argv[1], sys.argv[2]
try:
    from gray_matter.executor import install_drift
    sys.exit(0 if install_drift(mod, src)["state"] == "same" else 1)
except ImportError:
    pass
try:
    import importlib, importlib.metadata as md
    label = md.version(mod.replace("_", "-"))
    body = getattr(importlib.import_module(mod), "__version__", "")
    sys.exit(0 if (not label or not body or label == body) else 1)
except Exception:
    sys.exit(0)
PY
    }
    if [ "$FORCE" != "1" ] && ! code_matches neurag "$HERE"; then
        echo "NeuRAG: il codice installato NON e' questo sorgente — refresh forzato."
        FORCE=1
    fi
    [ "$FORCE" = "1" ] && echo "Repair: reinstalling NeuRAG (forced)..."
    FL=""; [ -d "$HERE/vendor" ] && FL="--find-links $HERE/vendor"
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FL $(repair_args) "$HERE" || "$VPY" -m pip install $(repair_args) "$HERE" \
        || { echo "ERROR: NeuRAG install failed — check network, or try: pip install --upgrade pip"; exit 1; }
    save_embed_model "$VPY"
    # Handshake assets (standalone has no GM to deploy them). Idempotent.
    _hooks=$("$VPY" -c "import neurag,os;print(os.path.join(os.path.dirname(neurag.__file__),'clients','deploy_hooks.py'))" 2>/dev/null || true)
    [ -n "$_hooks" ] && [ -f "$_hooks" ] && "$VPY" "$_hooks" || true
    # Let the user choose WHERE this registers (see install.ps1).
    # Not a tty => "detected", which never touches an absent client.
    if [ -t 0 ] && [ "$ASSUME_YES" != "1" ]; then CLIENT_SEL="ask"; else CLIENT_SEL="detected"; fi
    invoke_tool neurag neurag register --client "$CLIENT_SEL" || true
    invoke_tool neurag neurag doctor 2>/dev/null || true
    
    # --- GME Registry ---
    # One line instead of ~35 of hand-written JSON: gray_matter/gme.py is the
    # single writer (and the reader). Six shell copies in two languages is what
    # let the PowerShell BOM and the macOS path divergence ship unnoticed.
    # Best-effort — standalone means Gray Matter may be absent.
    "$VPY" -m gray_matter.gme register "$HERE" 2>/dev/null || true
    
    # Desktop icon "NeuRAG" → apre il control center (bootstrappa GM al 1° click).
    "$VPY" -m neurag.cli gui --shortcut-only 2>/dev/null || true
    NEURAG_VER=$(invoke_tool neurag neurag --version 2>/dev/null || echo "?")
    # An explicit, affirmative terminator: without it callers could not tell
    # "finished successfully" from "still working" or "died quietly".
    echo ""
    echo "  ============================================================"
    echo "  [OK] INSTALL COMPLETE - NeuRAG $NEURAG_VER (standalone)"
    echo "  ============================================================"
    echo "  Embedding model: ${CHOSEN_MODEL:-default (follows Neuron)}"
    echo "  Restart your AI apps to load the server."
    echo "  Desktop icon 'NeuRAG' opens the control center (installs Gray Matter on first click)."
    exit 0
}
[ "$WANT_GM" = "0" ] && standalone_install

# 1) Local GM (bundled or sibling) — zero-network, always the safest path.
for gm in "$HERE/gray_matter" "$HERE/../gray_matter"; do
    [ -f "$gm/install.sh" ] && { GM_PEER_DIR="$HERE" sh "$gm/install.sh" "$@"; gm_exit=$?; [ $gm_exit -eq 0 ] && exit 0; echo "WARNING: GM installer failed (exit $gm_exit), continuing standalone."; }
done

# GM is the required gateway: if missing, fetch it. Safest source first. These
# remote paths activate once Gray Matter is published (GitHub release / PyPI);
# until then they fail cleanly and we print guidance below.
# Da bumpare a ogni release di GM — vedi la nota in install.ps1.
GM_VERSION="${GM_VERSION:-1.4.1}"
GM_REPO="${GM_REPO:-recla93/gray-matter}"
GM_SHA256="${GM_SHA256:-}"          # optional: pin the release tarball checksum
CACHE="${GM_CACHE:-$HERE/.gm-bootstrap}"
PY=$(find_python)
echo "Gray Matter not found locally — bootstrapping it (GM is the required gateway)."
mkdir -p "$CACHE"

# 2) Primary remote: pinned GitHub release of the GM repo (immutable tag, TLS,
#    optional SHA256). Reuses the exact same tested install.sh pipeline.
URL="https://github.com/$GM_REPO/archive/refs/tags/v$GM_VERSION.tar.gz"
TGZ="$CACHE/gm-$GM_VERSION.tgz"
if command -v curl >/dev/null 2>&1; then curl -fsSL "$URL" -o "$TGZ" || rm -f "$TGZ"
elif command -v wget >/dev/null 2>&1; then wget -qO "$TGZ" "$URL" || rm -f "$TGZ"
fi
if [ -f "$TGZ" ]; then
    if [ -n "$GM_SHA256" ] && command -v sha256sum >/dev/null 2>&1; then
        echo "$GM_SHA256  $TGZ" | sha256sum -c - || { echo "ERROR: GM checksum mismatch — re-download or set GM_SHA256 to skip"; exit 1; }
    fi
    tar -xzf "$TGZ" -C "$CACHE"
    gm=$(find "$CACHE" -maxdepth 1 -type d -name 'gray-matter*' | head -1)
    [ -n "$gm" ] && [ -f "$gm/install.sh" ] && { GM_PEER_DIR="$HERE" sh "$gm/install.sh" "$@"; gm_exit=$?; [ $gm_exit -eq 0 ] && exit 0; echo "WARNING: GM installer failed (exit $gm_exit), continuing standalone."; }
fi

# 3) Fallback: PyPI. Install GM into the venv, then drive the gateway install.
if [ -n "$PY" ] && "$PY" -m pip install "gray-matter==$GM_VERSION" >/dev/null 2>&1; then
    "$PY" -m pip install --find-links "$HERE/vendor" "$HERE" >/dev/null 2>&1 || true
    # no exec: a failed gateway install must fall through to the standalone
    # degrade below (§6), not strand the user (keep-in-sync with .ps1 audit fix).
    if command -v gray-matter >/dev/null 2>&1; then
        gray-matter install "$@" && exit 0
    fi
fi

# GM unobtainable → degrade to standalone (§6), don't strand the user.
echo "WARNING: could not obtain Gray Matter (offline, or not yet published)."
echo "Falling back to a STANDALONE NeuRAG install — re-run this script later to add GM."
standalone_install
