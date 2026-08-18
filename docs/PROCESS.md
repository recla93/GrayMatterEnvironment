# Process

> How the Gray Matter Environment is built, by whom, and the lessons learned.
> A compendium of the working process — not a project management doc.

---

## The team: Claudio + Fable (multi-AI)

The project is built by one human (Claudio) working with multiple AI sessions (Fable, and others). This is not a metaphor — it is the actual development process.

**Roles:**
- **Claudio:** Product decisions, architecture review, testing, bug reports, domain knowledge. "The human in the loop."
- **Fable (and other AIs):** Code implementation, debugging, documentation, refactoring. "The hands."

**How it works:** Claudio describes a problem or a feature. Fable implements it. Claudio reviews, tests locally, reports what broke. Fable fixes. The cycle repeats. Decisions are made in conversation, not in tickets.

**Why this matters for the docs:** Every document in this suite was verified against source code, not copied from old docs. The DOCS-GUIDELINES.md rule "truth from code" exists because AI sessions can hallucinate — checking the code is the only way to stay honest.

---

## The compendium as shared brain

`GRAY-MATTER-COMPENDIUM.md` is the single source of truth for the project's state. It merges and deduplicates what used to be scattered across `GMFixAndIdeas`, `HANDOFF-07-16/17/18`, `STATO-E-PIANO`, and `PIANO-EVOLUZIONE`.

**Why it exists:** Multiple AI sessions need to know the same things. Without a compendium, each session starts cold and repeats investigations. The compendium is the "shared brain" — it persists between sessions.

**How it's maintained:** After each working session, the compendium is updated with what was done, what broke, what was fixed, and what's next. It's append-heavy (new sections for new work) and dedup-heavy (merging overlapping entries).

**Rule:** The compendium is never stale by more than one session. If it is, someone didn't update it.

---

## The Laguna audit lesson

At some point, the project underwent an external audit (Laguna). The result was humbling: many issues that the team thought were solid turned out to be fragile.

**What the audit found:**
- Version drift between files (RELEASE-CHECKLIST, README, pyproject all said different things)
- Assumptions in code that weren't validated (e.g., `_first_conchet` parsing dependent on Neuron output format)
- Missing edge cases (F3: reset without confirmation, F4: no dry-run on prune)

**What changed:** The team adopted a "verify everything against the code" discipline. The DOCS-GUIDELINES.md rules are a direct consequence: "Never trust a doc that isn't verified against the current source."

**Lesson:** External audits are not adversarial. They are the system checking itself. The compendium now includes an audit trail.

---

## L2 debugging: the daemon race

The most instructive bug in the project was L2: `store_turn → open: NotFound`.

**Symptom:** `store_turn` intermittently failed with `NotFound`. `pre_turn` always worked. One-shot tests always passed. Only failed in the live daemon.

**Timeline:**
1. First observed: 2026-07-19. Intermittent. Never reproducible in isolated tests.
2. Hypothesis 1: env/cwd of daemon missing .env/Turso token. → Rejected: pre_turn works.
3. Hypothesis 2: worker re-import per call (F0). → Fixed by F0 but L2 persisted.
4. Hypothesis 3: `_graphs.clear()` in worker + concurrent access to same WAL file. → Confirmed by reproducing in live daemon, never in tests.
5. Root cause: multiple GM processes (Desktop chat + host, Cowork) spawn multiple pyturso workers on the same `graph_*.db`. Worker does `_graphs.clear()` + reload on every call → race between open and WAL checkpoint.
6. Fix in progress: respawn worker on failure, or remove `_graphs.clear()`.

**Lesson:** Race conditions in SQLite/WAL are invisible in single-process tests. The bug only appears when multiple processes share the same DB file. The daemon singleton (Era 2) mitigates but doesn't eliminate this — Claude Desktop spawns 2 MCP clients from 1 entry.

---

## The sandbox → locale rite

Before any change is committed, it must pass through two environments:

1. **Sandbox (cloud):** AI writes code, runs `pytest` in the cloud sandbox. Tests pass → code is plausible.
2. **Locale (Claude Desktop):** Claudio runs the same tests locally. Tests pass → code is real.

**Why both:** Sandbox tests are isolated. Local tests run against the real daemon, real DB, real IPC. Many bugs (L2, F19, F20) only appeared locally because they depend on runtime state that sandbox doesn't replicate.

**Rule:** Sandbox green ≠ done. Locale green = done. Both red = investigate locally.

---

## Ponytail discipline

The project follows ponytail: "the shortest path to done is the right path."

**What this means in practice:**
- No interfaces with one implementation
- No factories for one product
- No config for values that never change
- No boilerplate "for later"
- One line before fifty
- Deletion over addition

**When it's violated:** Hardware calibration (the PCA9685 example from the ponytail skill), input validation at trust boundaries, security measures, anything explicitly requested by Claudio.

**The comment convention:** `ponytail: this exists` marks deliberate simplifications. Example: `# ponytail: global lock, per-account locks if throughput matters`.

---

## Schema-anchored design

Every major feature starts with the database schema, not the code. The schema is the contract.

**How it works:**
1. Design the table(s) in `models.py` (or `db.py` for NeuRAG)
2. Write the DDL with `CREATE TABLE IF NOT EXISTS`
3. Write migration `ALTER TABLE` for existing tables
4. Then write the code that uses the schema

**Why:** The schema is verifiable. You can `SELECT` and see what's there. Code can be wrong in subtle ways; data is either there or it isn't.

**Example:** The `Node.trust` column was designed as `trust REAL DEFAULT 0` with atomic delta `MAX(0, trust + ?)` before any trust logic was written. The schema forced the implementation to be correct.

---

## Neuron dogfooding itself

Neuron uses its own concept graph to track the project's knowledge. The compendium references Neuron nodes. The docs reference Neuron tools. The project IS the thing it builds.

**Why this matters:** If Neuron can't track its own development, it can't track anyone else's. Every bug in Neuron is found first by the team using it.

**The feedback loop:** Claudio uses Neuron (via GM) during development →发现问题 → fixes Neuron → commits → uses it again. The tool improves by being used.
