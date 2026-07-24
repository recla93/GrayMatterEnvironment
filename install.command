#!/bin/sh
# Gray Matter (full suite) — click-and-go installer (macOS/Linux). Double-click me.
# The GM repo bundles Neuron + NeuRAG: this installs everything.
cd "$(dirname "$0")" && sh install.sh
echo; printf "Done. Press Enter to close."; read -r _
