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
for a in "$@"; do case "$a" in -y|--yes) ASSUME_YES=1 ;; esac; done
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
[ -z "${PY:-}" ] && { echo "ERROR: need Python 3.10+ (install from https://python.org) and re-run."; exit 1; }
echo "Using: $PY ($("$PY" --version 2>&1))"

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
FINDLINKS=""
[ -d "$ROOT/Neuron/vendor" ] && FINDLINKS="--find-links $ROOT/Neuron/vendor"

VENV="${GM_HOME:-$HOME/.local/share/gray-matter}/.venv"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip >/dev/null

echo "Installing Gray-Matter..."
# shellcheck disable=SC2086
"$VPY" -m pip install $FINDLINKS "$HERE"
if [ -z "${GM_NO_NEURON:-}" ] && [ -d "$ROOT/Neuron" ]; then
    echo "Installing Neuron..."
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS "$ROOT/Neuron"
fi
if [ -z "${GM_NO_NEURAG:-}" ] && [ -d "$ROOT/neurag" ]; then
    echo "Installing NeuRAG..."
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS "$ROOT/neurag"
fi
# Launched from a standalone tool repo (Neuron-only / NeuRAG-only download):
# the thin per-repo installer points GM_PEER_DIR at itself — install it too.
if [ -n "${GM_PEER_DIR:-}" ] && [ -f "$GM_PEER_DIR/pyproject.toml" ]; then
    echo "Installing $(basename "$GM_PEER_DIR")..."
    [ -d "$GM_PEER_DIR/Neuron/vendor" ] && FINDLINKS="--find-links $GM_PEER_DIR/Neuron/vendor"
    [ -d "$GM_PEER_DIR/vendor" ] && FINDLINKS="--find-links $GM_PEER_DIR/vendor"
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS "$GM_PEER_DIR"
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

# Gateway model (INSTALLER-UX): register ONLY gray-matter, deploy hooks, manifest.
echo "Installing the gateway (register + hooks + manifest)..."
"$VPY" -m gray_matter.cli install || "$VPY" -m gray_matter.cli register || true

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
