#!/usr/bin/env sh
# NeuRAG installer for macOS & Linux. Installs NeuRAG plus the Gray-Matter
# orchestrator (bundled by default) into ONE shared venv and registers them in
# your MCP clients via `gray-matter register`. pyturso installs from the
# prebuilt wheels in ../Neuron/vendor when present (--find-links) so nothing
# compiles. Symmetric to Neuron's installer: whichever tool you install pulls
# Gray-Matter in, and from GM you can add the missing peer later.
#
#   sh install.sh          # interactive
#   sh install.sh --yes    # non-interactive
#
# Opt out of the orchestrator:  NEURAG_NO_GM=1
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
[ -z "${PY:-}" ] && { echo "ERROR: need Python 3.10+ (https://python.org) and re-run."; exit 1; }
echo "Using: $PY ($("$PY" --version 2>&1))"

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
FINDLINKS=""
[ -d "$ROOT/Neuron/vendor" ] && FINDLINKS="--find-links $ROOT/Neuron/vendor"

VENV="${NEURAG_HOME:-$HOME/.local/share/neurag}/.venv"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip >/dev/null

echo "Installing NeuRAG..."
# shellcheck disable=SC2086
"$VPY" -m pip install $FINDLINKS "$HERE"

GM_BUNDLED=0
if [ -z "${NEURAG_NO_GM:-}" ] && [ -d "$ROOT/gray_matter" ]; then
    echo "Bundling Gray-Matter orchestrator..."
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FINDLINKS "$ROOT/gray_matter" && GM_BUNDLED=1
fi

if [ "$GM_BUNDLED" = "1" ]; then
    echo "Registering installed servers in your MCP clients..."
    "$VPY" -m gray_matter.cli register || true
else
    echo "Add NeuRAG to your MCP client by hand — command: $VPY  args: -m neurag.server"
fi

if [ -x "$VENV/bin/neurag" ] && [ -d "$HOME/.local/bin" ]; then
    ln -sf "$VENV/bin/neurag" "$HOME/.local/bin/neurag" 2>/dev/null || true
fi

echo "Done. Restart your AI apps to load NeuRAG."
echo "  index docs:  $VENV/bin/neurag index ~/notes"
echo "  query:       $VENV/bin/neurag query 'java streams'"
