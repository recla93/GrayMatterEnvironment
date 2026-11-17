# ADR-022: Procedure facts (Neuron 7)

> Status: **Proposed** — 2026-11-16. Best after ADR-021. This is the release
> named Neuron 7. Scope: Neuron (`store_turn`, `pre_turn`), the bench.
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

The procedural layer of the five-layer map
([CINQUE-STRATI](CINQUE-STRATI-2026-11-03.md)) is missing. Two observations on
2026-11-16:

- To run the installer outside the MSIX container the assistant needed the exact
  procedure (environment variables, flags, what happens without `GM_HOME`). It
  was in the client's own memory file, not in Neuron.
- The procedures Neuron does hold are `habit` facts, in the profile: shown at
  every session start, needed or not.

A warning from 2026-11-10: a test wrote a false habit into the profile. A
procedure learned without proof teaches the mistake.

## Mechanisms

- **Procedural memory** is retrieved by the task at hand, not by resemblance to
  a sentence, and is strengthened by outcomes.
- **Evidence-gated writing**: a procedure exists because something measurable
  succeeded.

## Decision

**D1. A fact kind `procedure`.** Added to `FACT_KINDS` (`neuron/models.py`) and
to the `kind` enum of `store_turn` in `neuron/server.py` (a literal there: a
test reads the schema from source). Text: the steps, in order, one sentence
each, with the command when there is one. Concepts: the **task type**
(`install`, `release`, `bench diagnosis`), 1-3 nouns.

**D2. Recalled by task, outside the profile.** A `procedure` is never in the
profile. In `pre_turn` it competes in the normal recall, with the named-concept
match as its main signal (the message names the task).

**D3. Born from an outcome.** `store_turn` accepts a `procedure` only with an
`evidence` field naming the outcome: a passed gate, a passed smoke, a user
correction, a commit. Without it the fact is stored as kind `fact`, with a note
in the result. No model judges the evidence: its presence and form are checked.

**D4. Retired by failure.** A note that disputes a procedure (a fact citing its
`#id`) is shown beside it (already so, since `17ca169`). With ADR-021 a
procedure shown and never used falls by itself. No separate lifecycle states.

**D5. Existing `habit` facts that are procedures are migrated by hand**, once,
with `supersedes`: a list for the user to approve, not a job.

## Not in this ADR

- Procedures the model writes and runs by itself.
- Idle reflection that mines old facts for procedures.
- A registry with versions: `supersedes` already is the version chain.

## Steps

1. A bench set by task: `neuron/bench/recall_proc.json`, real task messages and
   the procedure each expects. Baseline with the procedures stored as `habit`.
2. D1 + D2 in code; rerun.
3. D3; tests for the accepted and refused forms.
4. D5 with the user.

## Baseline (2026-11-17, step 1)

`neuron/bench/recall_proc.json` v1: the 34 facts of `recall_en_all.json` plus
seven procedures (`q1`-`q7`: reinstall, release, gate, commit, bench, isolated
instance, deps), stored as `habit`; 14 real task messages from the transcripts,
the 5 off-topic messages of the other sets.

| Mode | recall | full | noise | off_topic | chars |
|---|---|---|---|---|---|
| message, procedures as `habit` | 45% (9/20) | 6/14 | 1.0/msg | 0 | 758/msg |

Where it fails: the push messages (m6, m7, m8) lose the gate procedure to the
`progress` and `habit` facts that share the concept `push`; the release-state
messages (m5, m14) get old release `progress` instead of gate and release
steps; the rename message (m12) gets ADR facts on `neuron`. In the bench
`pre_turn` shows no profile, so `habit` competes in the normal recall; the
session-start cost of habits is measured separately.

```
python neuron/bench/run.py --mode message --set neuron/bench/recall_proc.json -v
```

## Traps

- The profile shrinks when habits leave it: check `PROFILE_MAX_CHARS` still fits
  what remains, and that no test counts profile facts.
- `evidence` must not hold secrets or tokens (the rule of every fact).
- Do not add `procedure` to the flash kinds (`FLASH_KINDS`) without measuring.

## Acceptance

- The task set has its own recall number, and it beats the `habit` baseline.
- Characters of the session-start injection go down.
- The three recall sets do not regress.
