#!/bin/sh
# Gray Matter (full suite) — click-and-go installer (macOS/Linux). Double-click me.
# The GM repo bundles Neuron + NeuRAG: this installs everything.
#
#   ./install.command            normal install
#   ./install.command --force    repair: reinstall the code at the same version
#   ./install.command --clear    last resort: wipe the venv and rebuild (implies --force)
#                                CODE only — graphs, knowledge.db and bridges are kept
#
# "$@" forwarded so the flags work from a terminal; a double-click passes none.
cd "$(dirname "$0")" || exit 1
sh install.sh "$@"
RC=$?
echo; printf "Done. Press Enter to close."; read -r _
# Propagate the installer's exit code — parity with the Windows .cmd. `read`
# alone returned its own status, so a failed install looked successful.
exit $RC
