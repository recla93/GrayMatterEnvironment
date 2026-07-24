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
#
# Opt out of a peer:  GM_NO_NEURON=1  /  GM_NO_NEURAG=1
set -eu

ASSUME_YES=0
FORCE=0
# --force: repair mode — bypass the version-skip and reinstall the code even at
# the same version (pip --force-reinstall --no-deps). Used by the GUI "Ripara".
for a in "$@"; do case "$a" in -y|--yes) ASSUME_YES=1 ;; -f|--force) FORCE=1 ;; esac; done
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
find_peer() {  # $1 = nome dir del tool → stampa il path se esiste
    for d in "$HERE/$1" "$ROOT/$1"; do
        [ -f "$d/pyproject.toml" ] && { echo "$d"; return 0; }
    done
    return 1
}
NEURON_DIR=$(find_peer neuron || find_peer Neuron || true)
NEURAG_DIR=$(find_peer neurag || find_peer Neurag || true)
# Wheel offline (pyturso non ha wheel win_amd64 su PyPI): si prendono da OGNI
# vendor presente, non da quella di Neuron. I tre tool sono standalone — dare per
# scontata neuron/vendor lasciava un install GM+NeuRAG senza wheel. pip accetta
# --find-links ripetuto: si passano tutte, vince chi ha la wheel giusta.
FINDLINKS=""
for _d in "$HERE" "$NEURON_DIR" "$NEURAG_DIR"; do
    [ -n "$_d" ] && [ -d "$_d/vendor" ] && FINDLINKS="$FINDLINKS --find-links $_d/vendor"
done

VENV="${GM_HOME:-$HOME/.local/share/gray-matter}/.venv"
# venv: Plan A stdlib venv, Plan B virtualenv, else EXIT with guidance.
if [ ! -d "$VENV" ]; then
    "$PY" -m venv "$VENV" 2>/dev/null \
        || "$PY" -m virtualenv "$VENV" 2>/dev/null \
        || { echo "ERROR: could not create a venv at $VENV — install python3-venv (or 'pip install virtualenv') and re-run."; exit 1; }
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

# GM_PEER_DIR set → standalone mode (called from Neuron/install.sh or NeuRAG):
# install ONLY GM + the specified peer, skip sibling detection entirely.
install_peer() {  # $1 = dir sorgente, $2 = nome per i messaggi
    pkg=$(basename "$1" | tr '[:upper:]' '[:lower:]')
    if [ "$FORCE" != "1" ] && already_installed "$pkg" "$1"; then
        echo "$2 $(src_ver "$1") already installed — skipping."
        return 0
    fi
    [ "$FORCE" = "1" ] && echo "Repair: reinstalling $2 (forced)..." || echo "Installing $2 ($1)..."
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS $FORCE_ARGS "$1" \
        || "$VPY" -m pip install $FORCE_ARGS "$1" \
        || echo "  WARNING: $2 install failed — continuing."
}

if [ -n "${GM_PEER_DIR:-}" ] && [ -f "$GM_PEER_DIR/pyproject.toml" ]; then
    # Standalone: le wheel del peer si aggiungono a quelle già trovate.
    [ -d "$GM_PEER_DIR/vendor" ] && FINDLINKS="$FINDLINKS --find-links $GM_PEER_DIR/vendor"
    install_peer "$GM_PEER_DIR" "$(basename "$GM_PEER_DIR")"
else
    # Full suite mode — tools bundled INSIDE the GM repo zip, or siblings.
    [ -z "${GM_NO_NEURON:-}" ] && [ -n "$NEURON_DIR" ] && install_peer "$NEURON_DIR" "Neuron"
    [ -z "${GM_NO_NEURAG:-}" ] && [ -n "$NEURAG_DIR" ] && install_peer "$NEURAG_DIR" "NeuRAG"
fi

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
"$VPY" -m gray_matter.cli install || "$VPY" -m gray_matter.cli register || true

# Registro path sorgente (SoC): ogni componente registra il PROPRIO sorgente nel
# proprio registro; GM li scopre chiedendo ai peer. Riscritto a ogni install.
"$VPY" -m gray_matter.cli record-env --gm "$HERE" >/dev/null 2>&1 || true
[ -n "$NEURON_DIR" ] && "$VPY" -m neuron record-paths --source "$NEURON_DIR" >/dev/null 2>&1 || true
[ -n "$NEURAG_DIR" ] && "$VPY" -m neurag.cli record-paths --source "$NEURAG_DIR" >/dev/null 2>&1 || true

# Convenience: put `gray-matter` on PATH if ~/.local/bin exists.
if [ -x "$VENV/bin/gray-matter" ] && [ -d "$HOME/.local/bin" ]; then
    ln -sf "$VENV/bin/gray-matter" "$HOME/.local/bin/gray-matter" 2>/dev/null || true
fi

# Desktop shortcut to the control center (double-clickable on macOS & most Linux).
if [ -d "$HOME/Desktop" ]; then
    SC="$HOME/Desktop/Gray-Matter-GUI.command"
    printf '#!/bin/sh\nexec "%s" -m gray_matter.cli gui\n' "$VPY" > "$SC" && chmod +x "$SC" || true
fi

echo "Done. Restart your AI apps to load the servers."
echo "Control center any time:  $VENV/bin/gray-matter gui   (or: gray-matter gui)"
if ask "Open the Gray-Matter control center now?"; then
    nohup "$VPY" -m gray_matter.cli gui >/dev/null 2>&1 &
fi
