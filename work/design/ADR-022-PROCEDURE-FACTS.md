# ADR-022: Procedure facts (Neuron 7)

> Status: **D1-D3 implemented** — 2026-11-17 (proposed 2026-11-16); D5, the
> migration of live habits, waits for the user. Best after ADR-021. This is the release
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

## D1 + D2 (2026-11-17, step 2)

`procedure` is a kind (`FACT_KINDS`, the `store_turn` enum, the hook's and the
ledger's fact patterns), never in the profile (`_profile_facts` takes only
`user` and `habit`). D2 is one term in `search._search_facts`: `proc` is added
to a procedure when the message names one of its concepts
(`NEURON_FACT_PROC_BONUS`, 0.20). Explored outside the repo from 0 to 0.30:

| bonus | found | full | noise |
|---|---|---|---|
| 0 (kind alone) | 9/20 | 6/14 | 1.0 |
| 0.10 | 11/20 | 7/14 | 0.71 |
| 0.15 | 11/20 | 7/14 | 0.57 |
| **0.20** | **12/20** | **7/14** | **0.5** |
| 0.30 | 12/20 | 7/14 | 0.5 |

Set v2 (the procedures as `procedure`), real code: 12/20, full 7/14, noise
0.5, off-topic 0, 735 chars per message. The three recall sets are unchanged
(18/33 noise 0.59; 19/33 noise 0.64 on both English sets): they hold no
procedure.

Still missed: the gate procedure when the message says "push" and a second
procedure takes the other slot (m6), or says "release" without naming the gate
(m5, m14); "slug" does not name `rename` (m12); "aggiorniamo" does not name
`reinstall` (m11). These need the concepts a procedure is stored with, not a
bigger bonus.

## Traps

- The profile shrinks when habits leave it: check `PROFILE_MAX_CHARS` still fits
  what remains, and that no test counts profile facts.
- `evidence` must not hold secrets or tokens (the rule of every fact).
- Do not add `procedure` to the flash kinds (`FLASH_KINDS`) without measuring.

## Acceptance

- The task set has its own recall number, and it beats the `habit` baseline.
- Characters of the session-start injection go down.
- The three recall sets do not regress.

## D3 (2026-11-17, step 3)

`store_turn` takes `evidence` on a fact. A `procedure` with at least a few
characters of it is stored as one, and the evidence is kept at the end of its
text (`Proven by: ...`, at most 160 characters); without it the fact is stored
as `fact` with a note. Test: `test_a_procedure_needs_the_outcome_that_proved_it`.

Checked and dropped: linking procedures by `#id` notes so that the release
procedure brings the gate one. A note shows only the citing fact's id
(`↳#id`), not its text, so the model would see a pointer, not the steps.

## Checked on real data (2026-11-17)

A read-only copy of the real memory (225 active facts, 13 `habit`), with the
repo's code, and the 209 distinct user messages of the project transcripts.
Seven live habits are procedures (profiling a slow suite, smoke after a hook
change, NeuRAG bench diagnosis, release order, a mocoder live run, VS Code UI
testing, the OpenCode websearch fallback). Run A: as stored. Run B: those seven
as `procedure`, D2 as first written.

- B changed the facts of 26 messages; read one by one, about 7 were better and
  17 worse. The profiling procedure (`test suite`) came in on 11 turns, because
  "test" named the concept; `computer-use` was named by "user". On "Install
  prima, test a runtime e poi commit" it pushed out the right habit (no commit
  before a usage test).
- The bonus now needs **every word** of a concept (`search._names_whole`);
  the plain named bonus is unchanged. Run C, same data: 9 messages change, 6
  better (gate, smoke, three release questions, automation of the smoke) and
  3 worse, all the websearch procedure on messages that only say "OpenCode":
  its concept `opencode` is the client, not the task. That is the D5 lesson:
  a migrated procedure gets task concepts (`websearch`), not the tool's name.
- The profile on the first call: 1222 -> 1182 characters, and the slots the
  two newest procedures held go to `user` facts (the profile cap keeps about
  six facts, newest first).
- Bench v3 (each procedure with its evidence, as D3 requires): 12/20, full
  7/14, noise 0.5, off-topic 0, as before the rule; the three recall sets
  unchanged.

The bench alone said "better"; real data said "better only with whole
concepts". Every recall change goes through a replay on the real messages too.

### Why it got worse, read fact by fact

Run C's three worse messages: two lost nothing (the websearch procedure came as
a third fact, ~390 characters), one lost a relevant fix (OpenCode plugin
loading, on a question about installing a plugin). All three: the concept
`opencode`, carried by 12 of 252 active facts, names the client, not the task.
Run D, the same procedure indexed by `websearch`, `webfetch`, `duckduckgo`
only: 6 messages change, all better, none worse. The rule goes into the
playbook: a procedure's concepts name the task, never the tool alone.

The six better ones lost: mocoder facts on Gray Matter messages (two), a Kimi
shell fix on "smoke scrittura", two old push `progress` facts on "committa e
pusha", the 11-16 gate result on "Prima il gate unico" (state, mildly useful).

Better/worse is the author's reading, not a blind label. The bench now stops
when a set fact is stored under another kind (D3 had silently turned the
procedures into `fact`).

### Blind check (2026-11-17)

The 26 distinct comparisons of runs B, C, D, sides shuffled with a fixed seed,
judged by a cheap model told only "which list helps answer this message", with
no hint of which list is new:

| Run | new better | old better | tie | the author's reading |
|---|---|---|---|---|
| B (any word of a concept) | 6 | 18 | 2 | ~7 / ~17 |
| C (whole concept) | 5 | 3 | 1 | 6 / 3 |
| D (whole concept, task concepts) | 5 | 1 | 0 | 6 / 0 |

The blind judge agrees with the author's reading except on one message: "Prima
il gate unico", where it prefers the two gate results (state) to the smoke
procedure plus one result. That was the one the author had marked as arguable.

## Not adopted: a reply-language clause in the memory frame (2026-11-17)

Memory is English by rule; in this session the assistant drifted into English
replies. Tried: `note="stored in English; reply in the user's language. ..."`
on `<recalled-memory>` and "in the user's language" in the `→ next` line. Six
real Italian messages with their real recalled facts, old frame against new,
one fresh Haiku per case: short context 6/6 and 6/6 in Italian; with ~12k
characters of English tool output and an English ADR before the message, 6/6
and 6/6 again. No difference to measure, so the clause is not installed. The
drift seen here came from a long session of the assistant's own English work,
not from the memory frame.
