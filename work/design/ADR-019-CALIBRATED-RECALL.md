# ADR-019: One calibrated score instead of five knobs

> Status: **Measured, not adopted** — 2026-11-16 (same day). Steps 1-2 were run
> and the stop condition of step 2 was met. See "Result" at the end. Do not
> redo this before the data changes (see "When to reopen").
> Depends on ADR-018.
> Scope: Neuron (`search._search_facts`, `server._fact_hits`), a fitting script.
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

The fact recall (`search._search_facts`) scores
`cosine + named_bonus + lex * lexical`, then applies an absolute floor, a window
from the best and a cap. Five hand-tuned values in `neuron/server.py`:
`FACT_MIN_SCORE` 0.40, `FACT_DELTA` 0.15, `FACT_RECALL_K` 2, `FACT_NAMED_BONUS`
0.20, `FACT_LEX_BONUS` 0.15. Each was tuned on 20-22 messages.

The score is not a probability, so the recall cannot say "I do not know": the
doubt measure (`neuron/bench/run.py`, `doubt`) predicts a miss with AUC 0.68-0.83
but, used as a filter, did worse than K=2.

## Mechanism

Logistic regression: the standard way to turn a few signals into a calibrated
probability. `P(useful) = sigmoid(b0 + b1*cos + b2*named + b3*lex + b4*age)`.
Five numbers, fitted offline, stored as constants. No model at run time.

## Decision

**D1. Labels from real use.** One row per fact shown in a real turn: features of
(message, fact), label = used or not by ADR-018's rule. Source: the Claude Code
transcripts (the injected `hook_additional_context` holds the message's recalled
facts) and a copy of the memory for the facts' texts and vectors.

**D2. The fitting script** lives in `neuron/bench/` and never touches the live
memory: it reads a backup copy (`<suite>/backups/gm-graph-backup_<date>/neuron/`).
It prints the coefficients, the calibration (predicted vs observed rate in 5
bins) and the AUC. Plain Python: gradient descent on 5 parameters needs no
dependency.

**D3. The bench has the last word.** Replace the floor/delta rule with
`P >= threshold`, keep K as a cap. Accept only if rule 1 of the index holds on
all three sets. If not, the hand weights stay and this ADR is closed as
"measured, not adopted".

**D4. Fewer knobs, not more.** If adopted, `FACT_MIN_SCORE`, `FACT_DELTA`,
`FACT_NAMED_BONUS` and `FACT_LEX_BONUS` become the fitted coefficients plus one
threshold. The env overrides for the removed ones are deleted, with a changelog
line.

## Steps

1. Build the dataset script; print its size and the label balance. Expect a few
   hundred rows (321 recalled facts on 2026-11-16, 17% used).
2. Fit; check calibration. Stop here if the AUC is under 0.65: the signals do
   not predict use and no threshold will help.
3. Try the fitted score in a scratch wrapper on the three bench sets (rule 2).
4. Only then edit `search._search_facts` and `server._fact_hits`.
5. Gate, install, commit.

## Traps

- **Selection bias.** Labels exist only for facts that were shown, i.e. already
  above the old floor. The fit says nothing about facts below it: do not lower
  the effective floor on the fit's word alone; the bench decides.
- **Few positives** (~55). Five parameters is the ceiling; no interaction terms.
- **`age`** must be in turns or days since the fact was written, capped, or a
  single old fact dominates.
- **Ties**: `PYTHONHASHSEED=0`.

## Acceptance

- The three bench sets: no fact lost, `full` not lower, `noise`/`off_topic` not
  higher than the 2026-11-16 baseline in the PLAN.
- A test with fixed vectors pins the rule (pattern:
  `neuron/tests/test_fact_newer.py`).
- The changelog states the numbers and names the removed knobs.

## Result (2026-11-16)

Dataset: 321 showings of 125 distinct facts in 17 real sessions, 55 used (17%),
features computed on a copy of the memory.

| Signal | AUC alone |
|---|---|
| cosine | 0.498 |
| named concept | 0.435 |
| shared wording | 0.492 |
| log age | 0.635 |
| logistic fit, in sample | 0.649 |
| logistic fit, **leave one session out** | **0.512** |

Use rate by cosine band: under 0.30 18%, 0.30-0.45 16%, 0.45-0.60 17%, over 0.60
20%. Flat. Among the facts the recall already shows, how much a fact resembles
the message says nothing about whether it will be used. The age effect does not
survive leaving a session out. No threshold on this score can help: the hand
weights stay, and so do the five knobs.

What does predict use is the fact's own history, which this ADR did not include:
see ADR-021, "Evidence".

Two side findings:
- Facts shown as a gist: 0 used of 14, against 18% for full texts. A defect of
  the measure, not of the gists: fixed in ADR-018 (the hook judges a gist on
  its full text).
- Facts brought in by the named-concept bonus are used less (12% against 20%).
  Not significant on its own; worth a look when the bench is larger.

## When to reopen

When the showings are at least three times as many, or when the bench has a
set large enough to fit on (rule 1 of the index stays the judge). The scratch
scripts are not in the repo; the method is the "Steps" above.
