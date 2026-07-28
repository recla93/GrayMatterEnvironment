#!/usr/bin/env python3
"""Neuron SessionStart hook for Claude Code.

Registered by scripts/configuration.ps1 (Install-ClaudeCodeSessionHook) in
~/.claude/settings.json under hooks.SessionStart, for the "startup", "resume",
"clear" and "compact" matchers. Claude Code runs this script and adds its
stdout directly to context at the start of the conversation (SessionStart is
one of the hook events where plain stdout, not just the hookSpecificOutput
JSON, is accepted as context -- see docs.claude.com/en/docs/claude-code/hooks).

Why this exists: the MCP `instructions` field (Neuron's dynamic SIGNPOST, see
server.py) is host-optional -- nothing in the MCP spec obligates a client to
surface it to the model. This hook is a second, independent delivery path for
the same handshake reminder, using a mechanism Claude Code documents and
guarantees (a registered hook's stdout at SessionStart). Kept as a static,
self-contained string (no import of neuron / no venv dependency) so it never
fails or slows down session start, even if the Neuron install is broken.

Tool names below use `mcp__gray-matter__<tool>`, NOT `mcp__gray-matter__<tool>`.
Under the gateway model (INSTALLER-UX §1) the client registers ONLY
"gray-matter"; Neuron and NeuRAG run as its workers and their tools are served
through it pass-through. This hook is deployed by GM's installer, i.e. always
in gateway mode. Naming mcp__gray-matter__* made every session open with a priority
instruction to call tools that do not exist in it.
"""

import sys

# Compact handshake: the minimal per-turn loop only; the full curation rules
# live on demand in skill(name='playbook') / 'curated'. Keep in sync with the
# other client hooks and server.py's SIGNPOST (funnel.py).
NEURON_HANDSHAKE = (
    "!IMPORTANT [NEURON]: persistent semantic memory is connected - priority "
    "for this session.\n"
    "Each substantive turn: call mcp__gray-matter__pre_turn(topic, keywords) BEFORE "
    "replying (fold the returned context in silently), then "
    "mcp__gray-matter__store_turn(topic, keywords, links) AFTER, to persist what is new.\n"
    "Keywords = 3-5 concept NOUNS (no verbs/paths); links typed, never a "
    "self-link; before minting a concept check mcp__gray-matter__find_candidates; "
    "never store secrets or tokens.\n"
    "Skip on procedural turns (ack/thanks/yes-no) or an empty graph. Once per "
    "session: mcp__gray-matter__help (commands), mcp__gray-matter__skill(name='playbook') "
    "(full workflow).\n"
    "If no mcp__gray-matter__* tools exist here, memory is not connected - ignore this silently."
)


def main() -> None:
    print(NEURON_HANDSHAKE)
    sys.exit(0)


if __name__ == "__main__":
    main()
