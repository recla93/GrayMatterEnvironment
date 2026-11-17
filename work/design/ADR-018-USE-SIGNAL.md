# ADR-018: A fact is used when the reply used it

> Status: **Implemented** — 2026-11-16, commit `26c41cf`. Refines ADR-015 D8.
> Scope: Gray Matter (the Stop hook), Neuron (`store_turn`, `confirm`).
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

ADR-015 D8 counted a shown fact as used when the next `store_turn` shared a
concept with it. Measured on the live memory (213 active facts, 81 with
`confirmed >= 1`): 31 confirmed by superseding an older fact, 1 by an `#id`
citation, **50 by concept overlap alone**. Writing on the same topic is not use.
Nothing ranks on `confirmed` yet; ADR-019 and ADR-021 will, and a memory that
ranks on topic overlap confirms itself.

Explicit signals cannot stand alone: models cite an id about 1% of the time.

## Decision

**D1. The reply is the evidence.** The Stop hook reads the turn and reports the
recalled facts the turn used: `memhook.used_facts(entries)` → IPC
`{"action": "call", "server": "neuron", "tool": "confirm", "args": {"facts": [...]}}`.
No new daemon action.

**D2. The rule** (`memhook.distinctive`, `memhook.silently_used`): a fact is used
when the turn's text and tool inputs reuse two of its distinctive words (8+
characters, or holding a digit, dot, slash or underscore), or all of them when it
has fewer than two.

**D3. What does not count.**
- Words in the user's message, or anywhere in the session before the recall:
  the model had them without the memory.
- Inputs of memory tools: a `store_turn` restating a fact is the
  self-confirmation this replaces.
- The profile (`user`, `habit`): always shown.
- The Stop that follows the hook's own reminder (`stop_hook_active`).

**D4. `store_turn` keeps the explicit signals only**: an `#id` citation, a
`supersedes`. The concept-overlap rule and `_facts_served` are gone.

**D5. One rule, one place.** `gray_matter/bench/ledger.py` loads the same two
functions from `memhook.py` by path.

**D6. A gist is judged on its full text** (added 2026-11-16, same day). A fact
shown in its short form has too few distinctive words to match: 0 of 14 gists
counted as used on the real sessions, against 18% of the full texts. The hook
asks Neuron for the text (`pre_turn(topic="#id ...")`) before applying D2.

**D7. The hook also reports what was shown** (`confirm(shown=[...])`), for the
per-fact rate of ADR-021.

## Evidence

| Rule, on 135 real turns with 321 recalled facts | Reported as used |
|---|---|
| D2 without the "before the recall" filter | 38% |
| D2 + D3 (installed) | 17% |
| Ledger, offline, with its corpus-wide common-word filter | 21% |

The installed rule is the conservative one. End to end on an isolated instance:
the installed hook raised a fact's `confirmed` from 1 to 2.

## Limits

- Lexical: a paraphrase is missed.
- Only hosts with a readable transcript (Claude Code). Kimi and Codex: ADR-023.
- One window: the turn the fact was shown in. A fact used two turns later is
  not counted.

## Check

`pytest gray_matter/tests/test_memhook.py neuron/tests/test_search_recall.py`:
`test_the_stop_hook_reports_the_recalled_facts_the_turn_used`,
`test_a_fact_cited_or_confirmed_counts_one_use_a_shared_concept_does_not`.
