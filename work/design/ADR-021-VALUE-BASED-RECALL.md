# ADR-021: Recall as a value decision

> Status: **Proposed** — 2026-11-16. Depends on ADR-018 (the signal) and ADR-019
> (the calibrated prior). Scope: Neuron, the ledger, the control center.
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

The recall answers "which fact resembles the message?". The question that saves
tokens is "is showing this fact worth it?". A shown fact has a certain cost (its
tokens, read again on every later request of the session) and an uncertain gain
(the exploration it avoids, if used). Numbers on 2026-11-16: memory is 1.1-1.2%
of consumption, 21% of the facts shown are used, a turn makes 14.4 exploring
tool calls. The cost side is done; the value is in showing the fact that removes
an exploration, and in staying silent otherwise.

Since ADR-018 the suite knows, turn by turn, whether a shown fact was used.

## Mechanisms

- **Beta-Bernoulli estimate per fact.** Shown `n` times, used `k` times:
  `P(useful) ~ Beta(a0 + k, b0 + n - k)`. Two integers per fact.
- **Hierarchical prior.** A fact is shown about once per session, so alone it
  learns slowly: `a0, b0` come from its group (ADR-019's probability for this
  message, or the rate of its kind and age) with a fixed weight.
- **Expected-value rule.** Show when `P(useful) * saving > cost`.
- **Thompson sampling.** Draw `P` from the posterior instead of taking its mean:
  uncertain facts are sometimes shown, so a fact never tried is not buried.
  This is reward-prediction-error learning, with the reply as the reward.

## Decision

**D1. A `shown` counter beside `confirmed`.** Same plumbing as `confirmed` and
`gist` in `neuron/models.py`: the `ALTER TABLE facts ADD COLUMN` block, the
INSERT statement, the save and the load paths. Incremented in `pre_turn` for the
facts in the `facts:` segment (not the profile, not `latest:`).

**D2. The posterior replaces the threshold of ADR-019.** Prior strength: start
with the weight of 4 observations; measure 2 and 8.

**D3. `saving` and `cost` are measured, not guessed.** Cost: the fact's shown
length in tokens times the session's remaining requests (the ledger's weights).
Saving: from the ledger, the difference in exploring calls between turns where a
recalled fact was used and turns where none was, in the same sessions. Until
that number exists, use the ratio that reproduces today's behaviour and say so.

**D4. Exploration is bounded**: at most one explored fact per turn, never on an
off-topic message (the calibrated `P` under a floor), and it can be switched
off (`NEURON_FACT_EXPLORE=0`) for the bench, which must be deterministic.

**D5. A savings line in the control center**: explorations and tokens avoided in
the last 7 days, labelled as an estimate, with the count of turns behind it.

## Steps

1. D1 alone: counter, migration, test. Gate, install, commit. Let it collect.
2. The saving estimate in `gray_matter/bench/ledger.py`; print it with its
   sample size. If the difference is not distinguishable from zero, stop: the
   rule has no basis yet, keep ADR-019's threshold.
3. D2 + D3 in a scratch wrapper on the three sets, exploration off.
4. D4 behind its switch; verify on an isolated instance that an explored fact
   is shown and counted.
5. D5 last.

## Traps

- **The estimate is observational.** Turns where a fact is used differ from the
  others (easier, more familiar). Confirm with the mini A/B
  (`gray_matter/bench/ab.py`, 5 tasks, outside the repo) before quoting it.
- **Closing on the strong facts.** Without D4 the memory shows what it already
  showed. Notes that dispute a fact (`#id ↳#id`) stay visible whatever its score.
- **`confirmed` carried by `supersedes`**: a new version inherits the old one's
  count (`models.add_fact`). Carry `shown` the same way or its rate is inflated.
- **Random draws and tests**: seed them; the bench runs with exploration off.

## Acceptance

- Same share of used facts with fewer facts shown, on real sessions after two
  weeks (ledger before/after).
- Bench: rule 1 of the index, exploration off.
- The savings line shows its sample size and the word "estimate".

## Evidence (2026-11-16, before any code)

On the 321 real showings, with "elsewhere" meaning other sessions:

| The fact, elsewhere | Showings | Used here |
|---|---|---|
| was used at least once | 122 | 36 (30%) |
| was shown and never used | 151 | 17 (11%) |

AUC of the smoothed per-fact rate (prior 17%, weight 4): **0.66**, out of session
by construction. Similarity to the message: 0.50 (ADR-019). The per-fact history
is the only signal found that predicts use.

**The signal is positive only.** A rule "never used in N other showings: stop
showing it" loses uses at the base rate:

| N | Showings dropped | Uses lost | Use rate of what stays |
|---|---|---|---|
| 1 | 151 (47%) | 17 | 22% |
| 2 | 102 (32%) | 14 | 19% |
| 3 | 55 (17%) | 9 | 17% |
| 4 | 39 (12%) | 5 | 18% |

So: **no demotion rule**. What the data supports is a bonus for a fact that
proved useful, not a penalty for one that did not yet.

Caveats: the measure is lexical, so a fact rich in distinctive words is easier
to "use" in every session (part of the 30% is the fact's wording, not its
value); and topics persist across sessions of one project.

## Changes to the decision after the evidence

- **D1 is implemented** (2026-11-16), differently from the text above: `shown`
  is not incremented in `pre_turn` (a write on every recall, on the hook's hot
  path) but reported by the Stop hook together with the used facts,
  `confirm(facts=used, shown=shown)` → `Graph.note_shown`. One write per turn.
  A superseding fact carries its predecessor's showings, as it carries its uses.
- **D2's prior cannot come from ADR-019** (not adopted). Use the flat base rate.
- **The rule to try first is a bonus**: `score += w * (rate - base)` clipped at
  zero from below, for facts with at least 2 showings.
- **It cannot be measured on the bench** (bench facts have no history) and not
  offline (use is known only for facts that were shown). Acceptance is an
  online split: Gray Matter passes the session id's parity to `pre_turn`, the
  bonus applies on one half, and the ledger compares the use rate of the two
  halves after two weeks. No model, no tokens. Until that split exists, no
  ranking change is installed.
- `confirmed` before 2026-11-16 holds legacy counts (50 facts by concept
  overlap). Rates are meaningful only for showings counted from D1 on: use
  `shown > 0` as the gate, never `confirmed` alone.

## Parked by the user (2026-11-17)

D2 (the per-fact posterior) and D4 (Thompson exploration) are set aside: 385
showings are too few for per-fact estimates, so a group-level rate (kind, age)
would decide almost everything anyway. What goes on is the bonus experiment
below and D5. Reopen D2 and D4 when most recalled facts have several showings.

## The user's rule (2026-11-16): a fact that is not used is not less useful

Stated by the user after reading the evidence, and binding for everything above:

- **No fact dies and none is made unreachable for lack of use.** A fact stays
  stored and comes back when it serves, as a memory does. This forbids any
  pruning, archiving or exclusion by non-use, and it agrees with the data: a
  drop rule gains nothing.
- **Lack of use can lower a fact's reliability, never its availability.** If a
  reliability is ever shown or used, it is a tie-breaker between facts that
  already answer the message, not a filter.
- **Standing is measured from the last recall**: what counts is when the fact
  last came back and served, not how many times it was passed over. In ACT-R
  terms, the base-level activation refreshed by each retrieval; a single recent
  use outweighs many old showings.
- **Weights come from real data, with confirmations and criticism.** A number
  that only the bench of 22 messages supports is a hypothesis.

Consequences for this ADR: D2's posterior may only ADD to a score, the
expected-value rule of D3 may decide between candidates but may not hide a fact
whose similarity alone would show it, and D4's exploration stays (it is what
brings an old fact back).

## The experiment switch (implemented 2026-11-16, off)

- `memhook.arm(session)`: half of the sessions, from a hash of the session id.
  `_hook_recall` passes it to `pre_turn` as `arm`; the ledger computes the same
  value from the transcript's name and reports `any_use_rate_by_arm`.
- `search._use_rate(f)`: `confirmed / shown`, capped at 1, and 0 until the fact
  has been shown twice. `_search_facts(use=w)` adds `w * rate`: it can only
  raise a fact.
- `NEURON_FACT_USE_BONUS` is 0: nothing changes for anyone. Baseline before any
  experiment: the two halves read 20.9% and 20.8% (191 and 216 facts shown).

To run it: wait until most recalled facts have `shown >= 2` (weeks of use), set
`NEURON_FACT_USE_BONUS=0.10` in the suite's environment, let two weeks pass, run
`python gray_matter/bench/ledger.py --json` and compare the halves. Adopt only
on a clear difference with at least 150 facts shown per half; otherwise set it
back to 0 and record the result here. Mind that `confirmed` holds counts from
before 2026-11-16 for some facts: a rate above its real value, capped at 1.
