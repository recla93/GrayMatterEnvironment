# ADR-023: Gray Matter consolidation (towards 2.0)

> Status: **Proposed** — 2026-11-16. Independent; can run beside 019-022.
> Scope: Gray Matter (`tools/smoke.py`, the daemon, the hooks).
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

From what surfaced on 2026-11-16. Not a full audit: step 0 below is one.

- On 2026-11-14 an install without `GM_HOME` re-pointed the clients' hooks at a
  stale suite in `%LOCALAPPDATA%\GrayMatterEnvironment`. Nothing caught it.
- The live venv ran unreleased code under a released version label for a day.
- The daemon log (`<suite>/graymatter/logs/daemon.log`) repeats
  `Tool 'forgotten' not listed, no validation will be performed` on every flash
  (23 lines in a day) and holds a `Task exception was never retrieved` traceback
  from a shutdown on 2026-11-15.
- KB pointers: 77 shown in real sessions, 22 followed by a `knowledge_query`,
  and the follow rate does not grow with cosine (0.55: 8/28, 0.60: 2/17,
  0.65: 9/24, 0.70: 3/8). `KB_VECTOR_MIN_COS` was tuned on five messages.
- The use signal (ADR-018) exists only where the hook can read a transcript.

## Decision

**D0. Audit first.** Before any change, list what Gray Matter does that no number
defends, with `tools/deps.py <name>` for who depends on each. Removing beats
fixing.

**D1. Extended cohesion in the smoke** (`tools/smoke.py`, group `cohesion`):
- the versions in `<suite>/registry/*.json` equal the ones installed in the venv;
- every hook command registered in a client points at a Python that exists and
  at the suite's venv;
- a suite folder under `%LOCALAPPDATA%` is reported as a warning, with its path.

**D2. Debug on a FAIL.** When a smoke check fails, collect into one folder: the
last 200 lines of the daemon log, the last install log, the workers' state.

**D3. A quiet log.** Find why the worker call of `forgotten` is "not listed"
(`gray_matter/server.py`, the flash and warm-up calls) and fix the cause, not
the message. Await or cancel the daemon's task at shutdown.

**D4. The KB pointer gets a better signal or shows less.** Cosine does not
predict a follow. Try the wording signal used for facts (`search._lexical`'s
idea, on the section title and the message); measure on the real pointers
(shown, followed). If nothing predicts, show the pointer only when the message
names a document or a section.

**D5. The use signal for hosts without a transcript.** Kimi hands the hook
nothing; Codex hands the last answer (`last_assistant_message`). For Codex,
apply ADR-018's rule to that answer, with the facts the daemon showed that
session (`_HOOK_SEEN`). Kimi stays without.

**D6. Gray Matter 2.0 has one criterion**: the hooks work and are verified by a
real turn inside every client, with the use signal where D5 allows.

## Steps

D0, then D1, D3, D2, D4, D5. Each its own commit.

## Traps

- D1 must read, never repair: a check that fixes hides the cause.
- D5: `_HOOK_SEEN` is per daemon life and cleared when full; a restart loses it.
  Count nothing rather than guess.
- D4 changes what the model sees on every turn: measure on the recorded
  pointers before installing, and say how many it would have dropped.

## Acceptance

- D1 fails on a venv with a registry version edited by hand, and on a hook
  pointed at a missing Python (tests with temp folders).
- A day of use leaves no repeated line in the daemon log.
- D4: follow rate of the pointers shown goes up, on real sessions.
