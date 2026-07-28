// neuron-handshake --- OpenCode plugin.
//
// Ensures Neuron's handshake priority text reaches the model's system prompt
// on every turn, independent of whether the host actually surfaces the MCP
// `instructions` field.
//
// IMPORTANT (why this is a NAMED export): OpenCode discovers plugins by their
// NAMED exports -- a `export default` is NOT picked up, so the hook below never
// registers and the handshake silently never fires. This was the bug. The
// plugin function must be exported by name (any name); OpenCode calls it with
// its context object and reads the hook map it returns.
//
// Caveat: `experimental.chat.system.transform` is an experimental hook, and on
// some OpenCode versions the runtime discards mutations to `output.system`
// (anomalyco/opencode#17100). So this plugin is a best-effort SECOND channel;
// the RELIABLE delivery path for OpenCode is the top-level `instructions` entry
// in opencode.json (see clients/opencode.example.json), which points at
// neuron-opener.md. Keep both.
//
// Deployed automatically by scripts/configuration.ps1's "Add Neuron to your
// AI" -> OpenCode flow, which copies this file to
// <opencode.json dir>\plugins\neuron-handshake.mjs and registers it in
// opencode.json's top-level "plugin" array. Safe to copy by hand too.
//
// Tool names use OpenCode's `<serverkey>_<tool>` convention for a server
// served by the gateway registered as "gray-matter" (Neuron/NeuRAG are its
// workers). Tools are named WITHOUT a hard prefix here on purpose: the
// Claude-side convention is mcp__gray-matter__<tool>, OpenCode's differs, and
// guessing it produced instructions pointing at tools that do not exist.

// Compact handshake: the minimal per-turn loop only; full curation rules live
// on demand in skill(name='playbook') / 'curated'. Keep in sync with the other
// client hooks and server.py's SIGNPOST (funnel.py).
const NEURON_HANDSHAKE = (
  "!IMPORTANT [NEURON]: persistent semantic memory is connected - priority " +
  "for this session.\n" +
  "Each substantive turn: call pre_turn(topic, keywords) BEFORE " +
  "replying (fold the returned context in silently), then " +
  "store_turn(topic, keywords, links) AFTER, to persist what is new.\n" +
  "Keywords = 3-5 concept NOUNS (no verbs/paths); links typed, never a " +
  "self-link; before minting a concept check find_candidates; never " +
  "store secrets or tokens.\n" +
  "Skip on procedural turns (ack/thanks/yes-no) or an empty graph. Once per " +
  "session: help (commands), skill(name='playbook') (full workflow).\n" +
  "If no gray-matter_* tools exist here, Neuron is not connected - ignore this silently."
);

export const NeuronHandshake = async () => {
  return {
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(NEURON_HANDSHAKE);
    },
  };
};
