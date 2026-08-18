# Wow, I've got a brain: now what?

You installed three things and got one connector. This is the guide for the
half hour after that, written for the person who just wants to know what to
actually *do*.

---

## What you actually have

Three tools that go together, and one of them is the front door.

| | what it is | what it answers |
|---|---|---|
| **Neuron** | memory | *what did we say, decide, learn?* |
| **NeuRAG** | knowledge | *what do my documents say?* |
| **Gray Matter** | the gateway | routes both, and joins them |

If Gray Matter is installed, your AI app talks to **it**, and it spawns the
other two. One connector in your client, three capabilities behind it. If you
installed only one, it works alone — that is a design rule, not a courtesy, and
it is tested.

**The distinction that matters, and the only one you need:** memory is what
*happened*, knowledge is what you *have*. "What did we decide about the
database?" is memory. "What does the contract say about termination?" is
knowledge. Ask for the wrong one and you get a confident answer built from the
wrong place.

---

## The first five minutes

**1. Check it is alive.**

```bash
gray-matter doctor
```

Read the `engine` line. `Turso (local)` is the good tier. `SQLite (read-only:
owned by another process)` is also fine — it means something else has the vault
open, usually the server, and you are reading a borrowed copy. `corrupt` is the
only word that means trouble, and it will tell you what to do about it.

**2. Give it something to read.**

```bash
neurag ingest ~/Documents/my-project
```

A folder becomes a graph: folders become topics, files become chunks, and the
links between them are built for you. A single document works too — you do not
have to invent a folder for one PDF:

```bash
neurag ingest ~/Downloads/contract.pdf
```

Re-running it on the same file **replaces** that file's chunks. Updating a
document is just ingesting it again; nothing duplicates.

**3. Ask it something you know the answer to.**

Do this first, deliberately, with a question you can check. It is the only way
to calibrate what it is good at before you start trusting it.

```bash
neurag query "the thing you already know"
```

---

## Now use it from the chat

You will mostly not type commands. The point is that your AI app can reach all
of this by itself. What changes is what you can ask for:

- *"What did we decide about X last month?"* → memory
- *"What does my documentation say about Y?"* → knowledge
- *"Remember that we chose Postgres because of the JSONB support."* → stored,
  and it will come back later without you asking

**The one habit worth forming:** when the assistant answers about *your*
material, ask it which source it used. It has that information. An answer with
a source is checkable; an answer without one is indistinguishable from a
confident guess about somebody else's version of your subject.

---

## Teaching it, which is the part people skip

The graph starts out knowing only what it could infer — which files mention
which, which topics share vocabulary. It learns the rest from you, and it only
learns from **confirmation**, never from having been shown something:

```bash
neurag confirm "Deploy" "Rollback"
```

That says these two belong together. The link between them gets stronger, and
strong links survive re-ingests. Retrieval is cheap and often wrong, so being
retrieved together proves nothing — that is why confirming is a separate verb.

To see what a topic reaches:

```bash
neurag related "Deploy"
```

---

## Keeping it honest

```bash
neurag health      # structural audit — flags, never deletes
neurag park        # report what has gone quiet (DRY RUN unless --apply)
neurag recall "…"  # search EVERYTHING, including what was parked
```

**Nothing is ever deleted.** Not chunks, not topics, not concepts. Things get
*parked*: dropped from the default search, kept on disk, reachable by `recall`.
What decays is the route, never the trace. If you cannot find something, you
have not lost it — try `recall`.

---

## The control center

```bash
gray-matter gui
```

Everything above, with buttons, plus the panels that are genuinely easier to
look at than to type: which MCP clients are registered, the settings for each
tool, the health of the vault, and a console you can answer prompts in.

Two honest notes about it:

- **Repair closes it.** The installer stops every process running from Gray
  Matter's environment so it can replace the files they hold — and the control
  center is one of those processes. The repair keeps running without it. Reopen
  the panel and it will show you how it went.
- **A running server keeps its code.** Reinstalling updates the files; the
  processes already running still hold what they loaded at startup. Restart
  them, or you will be checking a fix against the one process that does not
  have it.

---

## What it will not do, on purpose

- **It will not invent connections.** The graph can spread activation from one
  topic to its neighbours, but that stays out of ranking: a knowledge base that
  free-associates is one you stop trusting. It was built, measured, and it made
  results worse — so it is not there.
- **It will not answer from your documents unless it looks.** If the vault is
  empty, the tools say so rather than searching nothing forever.
- **It will not keep secrets safe.** The vault is plain text on disk and gets
  surfaced verbatim into future conversations. Do not paste tokens, passwords
  or credentials into it.

---

## When something looks wrong

| symptom | what it usually is |
|---|---|
| "vault is corrupt" | often it is **locked**, not damaged — another process has it. The message tells you which case it is; only one of them wants `--wipe-knowledge`. |
| searches find nothing | check `neurag status`: an empty vault has nothing to find. Ingest first. |
| the assistant ignores the tools | it decides from the tool list; if the vault is empty that list says so, correctly. |
| a document is missing | `neurag recall` before anything else — parked is not deleted. |
| results feel shallow | `neurag health` after a bulk ingest. That is when structure breaks quietly. |

`gray-matter doctor` is the single command worth remembering. It prints the
tier, the embedder, the vault, and whether the gateway sees its peers.

---

## The one-paragraph version

Feed it your documents with `ingest`. Ask it things and make it cite. Confirm
the connections that turn out to be real, because that is the only way it
learns. Run `health` after big imports, and remember that `recall` reaches
things that ordinary search has stopped offering. Everything else is detail you
can pick up when you need it.
