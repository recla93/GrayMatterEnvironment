# ADR-020: State questions and elliptical messages

> Status: **Measured, not adopted** (2026-11-16): D1 and D3 both failed their
> measure, see the two "Result" sections. Independent of ADR-019.
> Scope: Neuron (`pre_turn`), the bench. Gray Matter only passes `profile`, as today.
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

Of the 15 facts missed on bench v2 (K=2, lexical 0.15), 7 rank 11th or worse.
Two kinds of message cause most of them, and no ranking tweak reaches either:

- **State questions.** "Let's check the state", "can we release?" want the
  newest `progress` facts, which do not resemble the message (m01: p1 27th, p2
  19th; m17: p2 15th). Live, 2026-11-16: a session opened with "check the state"
  and the hook brought two decisions from 10-12/11, not the release of 15/11.
- **Elliptical messages.** "Can we release?" does not hold its subject: the
  subject is in the previous turn.

## Mechanisms

- **Retrieval by time**, not by meaning, for the session's opening.
- **Context reinstatement**: a memory comes back better in the context it was
  formed in; here, the concepts of the turn just stored.

## Decision

**D1. The newest `progress` facts ride with the profile.** On the first call of a
session (`pre_turn` with `profile=true`; Gray Matter already sets it once per
session, `_hook_recall`), Neuron adds a `latest:` segment: the N newest active
`progress` facts, shown through `fact_shown` (the gist when there is one). Model
it on `_profile_facts` in `neuron/server.py`. Their ids join `_seen_ids`, so the
recall does not repeat them.

**D2. N is measured, starting at 3.** The bench set holds four `progress` facts
(p1, p2, p3, s2): with N=2 the bench gains one fact, so 2 is known to be too few.

**D3. The previous turn enriches a short message.** When the message has few
content words (start with: under 8 words of 3+ letters), the fact query in
`pre_turn` is the message plus the concepts of the facts stored in the graph's
last turn. Do it inside Neuron, which holds those facts (`fact["turn"]`,
`g.turn_count`): Gray Matter keeps no per-session record of what a turn stored
(`_FACT_AT` in `gray_matter/server.py` is one global timestamp), and adding one
is more code for the same effect. Only when that last turn is recent: start with
"stored within the last 30 minutes" (`created_at`), so another session's old
turn is not taken for context.

**D4. A sequence set for the bench.** D3 cannot be measured on single messages.
Add `neuron/bench/recall_seq.json`: pairs (previous turn's concepts, short
message, expected facts) taken from real transcripts, with the same rules as
`recall.json`. Mark session openers in `recall.json` (`"first": true`) for D1
and raise `version`.

## Steps

1. Bench first: the `first` flag and `recall_seq.json`, with `run.py` passing
   `profile` for openers. Record the baseline before any code.
2. D1 in a scratch wrapper, N in {2, 3, 4}; then in `pre_turn`.
3. D3 in a scratch wrapper on the sequence set; then in `pre_turn`, where
   `_fact_q` is built.
4. Each one: gate, install, commit, separately.

## Traps

- D1's facts are shown whatever the message says. On an opener that is not a
  state question they are noise by the bench's definition (m02 expects k2, x1).
  Report both numbers; the cost is paid once per session.
- `latest:` prints `#id`s: they become "seen" for the session (index, traps).
- D3 must not fire on a long message: appended concepts would dilute it.
- Do not merge D1 into the profile's own cap (`PROFILE_MAX_CHARS`): give it its
  own, or a long profile starves it.

## Acceptance

- D1: on the opener messages, recall up with N chosen; characters added per
  session stated in the changelog.
- D3: the sequence set improves and the three single-message sets do not move.

## Result for D1 (2026-11-16, computed on the bench rows, no code)

The four `progress` facts of the set, newest first: s2, p3, p2, p1. Adding the
newest N to the messages that open a session or ask for the state (m01, m02,
m17, m21, judged by reading them), on top of the K=2 + lexical 0.15 result
(18 of 33 found, 0.59 unexpected facts per message):

| Trigger | N | Expected facts gained | Unexpected facts added | Recall | Noise per message |
|---|---|---|---|---|---|
| openers (m01, m02, m21) | 3 | 2 (m01: p2, p3) | 6 | 0.606 | 0.86 |
| the word "stato" (m01, m02, m17) | 3 | 3 (m01: p2, p3; m17: p2) | 6 | 0.636 | 0.86 |
| the word "stato" | 2 | 1 | 5 | 0.576 | 0.82 |

Rule 1 of the index fails on noise in every variant: two or three facts gained
for six unexpected ones. m02 ("read the state of the work... we must fix the
suite") expects a fix and a fact, not the progress. **D1 is not adopted as
designed.**

A variant that keeps the cost at a few tokens and leaves the choice to the model:
at session start, one line naming the newest progress facts by id and date only
(no text), opened with `pre_turn(topic="#id")` when the message asks for the
state. It adds no fact text, so no noise by the bench's definition, but it
works only if the model opens it: explicit pulls are rare in this suite (KB
pointers followed 22 times of 77, explicit confirms 1%). It needs a live
measure, not the bench, and the ids must be printed so that they are not taken
as "seen" (index, traps). Not started.

D3 and D4 are untouched: they still need the sequence set first.

## Result for D3 (2026-11-16, on real turns, no code)

The premise holds: in the real sessions 57 of 162 turns are short (under 8 words
of 3+ letters: "yes, start from A+B", "first the hash"), only 47% of them get
any recalled fact against 73-97% of the longer ones, and when they do the facts
are used more (27%).

The remedy does not. Measured on a relevance set built from the same turns (a
fact is relevant when it existed before the turn and the reply reuses two of
its distinctive words that neither the message nor the session before held;
154 turns, 99 with a relevant fact), with the installed scoring:

| Query for a short message | Short turns that recall something | Facts shown | Relevant among them |
|---|---|---|---|
| the message alone (today) | 34 of 57 | 56 | 3 |
| + last 200 characters of the previous reply | 57 | 107 | 3 |
| + last 400 characters | 57 | 108 | 3 |
| + first 200 characters | 57 | 105 | 3 |

Twice the facts shown, not one more relevant. Adding the previous reply to every
message makes the long ones worse (24 → 21 relevant). **D3 is not adopted**: the
previous reply is not the context that finds the fact. The variant in the text
above (concepts of the last STORED turn) was not measured; it has less text to
go on than the reply itself, so do not expect more from it.

About the relevance set: it marks 12 facts per turn as relevant on average,
because a long agentic turn writes thousands of words and two distinctive words
match by chance. Good enough to compare two queries on the same turns, not to
quote as a recall figure. A tighter label (IDF-weighted, three words) is the
first thing to do before using it for anything else.
