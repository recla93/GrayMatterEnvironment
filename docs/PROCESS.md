# Process

> How the Gray Matter Environment is built, and the lessons learned.
> A compendium of the working process — not a project management doc.

---

## Truth from code

Every document in this suite is verified against the source, not copied from
older docs. A claim that can be checked in the code is checked there; a doc that
disagrees with the code is the doc's bug.

---

## Where the project's state lives

| Question | Where the answer is |
|---|---|
| What shipped, and why | `CHANGELOG.md` of each project |
| What was decided, and what was rejected | the ADRs in `work/design/` |
| What is set aside for later | `work/design/IDEAS.md` |
| Everything else | `git log` |

A single hand-maintained compendium used to hold all of this. It went stale
within a month, because nothing forced an update: retired on 2026-10-26. The
sources above are written in the same commit as the change they describe, so
they cannot fall behind it.

---

## The Laguna audit lesson

At some point, the project underwent an external audit (Laguna). The result was humbling: many issues that the team thought were solid turned out to be fragile.

**What the audit found:**
- Version drift between files (RELEASE-CHECKLIST, README, pyproject all said different things)
- Assumptions in code that weren't validated (e.g., `_first_conchet` parsing dependent on Neuron output format)
- Missing edge cases (F3: reset without confirmation, F4: no dry-run on prune)

**What changed:** The team adopted a "verify everything against the code" discipline. The DOCS-GUIDELINES.md rules are a direct consequence: "Never trust a doc that isn't verified against the current source."

**Lesson:** External audits are not adversarial. They are the system checking itself. Audits are kept in `work/audit/` and `work/history/`.

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

## Local and CI, then the real server

A change is done when three things hold:

1. **The suites are green locally**, run as `ENVIRONMENT.md` §1 says.
2. **CI is green** on the pushed commit: `ci.yml` and `standalone.yml`.
3. **It works in the installed server.** Many bugs (L2, F19, F20) appeared only
   against the real daemon, the real DB and the real IPC, because they depend
   on runtime state that tests do not replicate.

**Rule:** green tests are necessary, not sufficient.

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

**When it's violated:** Hardware calibration (the PCA9685 example from the ponytail skill), input validation at trust boundaries, security measures, anything explicitly requested.

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

Neuron uses its own concept graph to track the project's knowledge. The docs reference Neuron tools. The project IS the thing it builds.

**Why this matters:** If Neuron can't track its own development, it can't track anyone else's. Every bug in Neuron is found first by the team using it.

**The feedback loop:** Neuron is used (via GM) while developing the suite → a problem shows up → Neuron gets fixed → the fix is committed → it is used again. The tool improves by being used.
