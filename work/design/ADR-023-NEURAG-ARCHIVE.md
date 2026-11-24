# ADR-023: NeuRAG is the archive of project documentation

> Status: **decided and implemented** — 2026-11-23. Supersedes the knowledge
> role of ADR-017 (memory and knowledge as two equal stores) and parks its
> bridges and copy-promotion. Scope: NeuRAG, Gray Matter's KB pointer.
> Rules and traps: [index](ADR-INDEX-2026-11-16.md).

## Context

ADR-017 gave NeuRAG the knowledge and bridges to tie it to Neuron's episodes.
On 2026-11-23 every part of that was measured on real data, and most of it did
not hold:

| Measure (real messages, blind judge where marked) | Result |
|---|---|
| bridges in the live suite | 0; never more than 2. No automatic birth exists since ADR-016 D4; the provenance bridge of `promote` decayed after 7 idle days, so a second `promote` re-added the same facts (fixed: `promoted=1` bridges never decay) |
| `promote` candidates read one by one | 56: ~29 durable, 11 stale (none marked superseded, so no rule can filter them), 16 dated snapshots; a promoted copy diverges from the fact it copies |
| KB content | 99% this repo, already on disk: the KB pointer was followed 0 times in 17 here |
| KB pointer on 146 messages, KB = 30 neuroscience articles (judge) | 1 relevant in 11 |
| a model asking the KB on its own (OpenCode, isolated, 2 models) | 1 call in 12 questions; that answer was judged worse than the one without |
| keyword routing (Neuron's "named" rule on titles/headings, judge) | 15-25% precise |
| the vector pointer on the user's project design docs (ARBOR, judge) | **10 relevant in 11** |
| the user's own Java/Spring course notes | 1 of 7 on-topic messages, 5 noise in 141 |
| context-scoped search, distinctive-keyword boost (judge, 15 relevant) | no clear gain over the plain pointer |

What decides is the content, not the routing: documents specific to a project
(designs, decisions, specs) that the model does not know and that are not on
disk where it works. General knowledge, even in the user's own words, is
something the model already has.

## Decision

**D1. NeuRAG's role is the archive of project documentation.** What goes in is
chosen by the user (ADR-017 D2): designs, specs, decisions of projects. Not the
repository being worked on, not general knowledge.

**D2. It reaches the model through the KB pointer only.** One line per message
when a section is close enough (cos >= 0.55, kept: on 33 judged pairs a higher
threshold did not raise precision consistently), content on demand with
`knowledge_query`. Neuron stays the long-term memory; nothing is copied into
NeuRAG.

**D3. The pointer skips the current project.** The memory hook passes the
client's working directory; the first hit outside it is the pointer, same
threshold. Clients that send no directory (OpenCode, whose plugin serves
several locations from one process) keep the first hit.

**D4. Word documents are part of the archive.** `python-docx` is a dependency
of NeuRAG (the installers never add extras, so `ingest` stopped on every
.docx). PDF stays optional: PyMuPDF is ~20 MB and AGPL.

**D5. Parked, not removed:** GM bridges, `promote`, keyword routing, the idea
of KB attachments on Neuron facts. They stay in the code; nothing new is built
on them until a measure says otherwise.

## Consequences

- The live KB holds `X:\ARBOR` and the mocoder documents; this repo and the
  old promoted memory are archived (reversible; backup
  `backups/before-kb-content-2026-11-23`).
- NeuRAG is optional at install: Neuron + Gray Matter is the core.
- On ARBOR messages the pointer names the right section (ciclo notte ->
  `NOTTE_LORA`, 0.73); commit/push/github messages get no pointer.
