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
WANT_GM=1; FORCE=0; CLEAR=0; MODE="gateway"
for a in "$@"; do case "$a" in
    --no-gm) WANT_GM=0; MODE="standalone" ;;
    -f|--force) FORCE=1 ;;
    -c|--clear) CLEAR=1; FORCE=1 ;;   # clear is a stronger force
esac; done
FORCE_ARGS=""
[ "$FORCE" = "1" ] && FORCE_ARGS="--force-reinstall --no-deps"
[ "${GM_OPTIN:-1}" = "0" ] && WANT_GM=0 && MODE="standalone"

# Mode selector: click-and-go (Enter = full suite) or explicit --no-gm.
# Only shows in interactive terminals; non-interactive defaults to gateway.
if [ "$WANT_GM" = "1" ] && [ -t 0 ] && [ "$FORCE" != "1" ]; then
    echo ""
    echo "  Installation mode:"
    echo "    [F] Full suite — GM + Neuron + NeuRAG (recommended)"
    echo "    [N] Solo NeuRAG — standalone (registers directly in clients)"
    echo "    [D] Details — what you lose without GM"
    echo ""
    printf "  Choice [F]: "; read -r ans
    case "$ans" in
        n|N|no|standalone) WANT_GM=0; MODE="standalone" ;;
        d|D|details|DETAILS)
            echo ""
            echo "  Without GM you lose:"
            echo "    - Cross-store bridges (NeuRAG <-> Neuron)"
            echo "    - Neighbor auto-surface"
            echo "    - Unified GUI control center"
            echo "    - Auto-registration in MCP clients"
            echo ""
            printf "  Install Full suite? [Y/n] "; read -r ans2
            case "$ans2" in n|N|no|NO) WANT_GM=0; MODE="standalone" ;; esac
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

standalone_install() {
    echo "Installing NeuRAG STANDALONE (no Gray Matter — add it any time by re-running)."
    PY=$(command -v python3 || command -v python || true)
    [ -z "$PY" ] && { echo "ERROR: need Python 3.10+ — https://www.python.org/downloads/"; exit 1; }
    VENV="${NEURAG_HOME:-$HOME/.local/share/neurag}/.venv"
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
    "$VPY" -m pip install --upgrade pip >/dev/null 2>&1 || true
    [ "$FORCE" = "1" ] && echo "Repair: reinstalling NeuRAG (forced)..."
    FL=""; [ -d "$HERE/vendor" ] && FL="--find-links $HERE/vendor"
    # shellcheck disable=SC2086
    "$VPY" -m pip install $FL $FORCE_ARGS "$HERE" || "$VPY" -m pip install $FORCE_ARGS "$HERE" \
        || { echo "ERROR: NeuRAG install failed — check network, or try: pip install --upgrade pip"; exit 1; }
    "$VENV/bin/neurag" register --client all || true
    "$VENV/bin/neurag" doctor 2>/dev/null || true
    
    # --- GME Registry ---
    # One line instead of ~35 of hand-written JSON: gray_matter/gme.py is the
    # single writer (and the reader). Six shell copies in two languages is what
    # let the PowerShell BOM and the macOS path divergence ship unnoticed.
    # Best-effort — standalone means Gray Matter may be absent.
    "$VPY" -m gray_matter.gme register "$HERE" 2>/dev/null || true
    
    # Desktop icon "NeuRAG" → apre il control center (bootstrappa GM al 1° click).
    "$VPY" -m neurag.cli gui --shortcut-only 2>/dev/null || true
    NEURAG_VER=$("$VENV/bin/neurag" --version 2>/dev/null || echo "?")
    echo ""
    echo "  NeuRAG $NEURAG_VER — standalone"
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
GM_VERSION="${GM_VERSION:-1.1.2}"
GM_REPO="${GM_REPO:-recla93/gray-matter}"
GM_SHA256="${GM_SHA256:-}"          # optional: pin the release tarball checksum
CACHE="${GM_CACHE:-$HERE/.gm-bootstrap}"
PY=$(command -v python3 || command -v python || true)
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
