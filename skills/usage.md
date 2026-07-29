# NeuRAG — retrieval workflow

The knowledge base is a hierarchical graph of **nodes** (topics) holding
**chunks** (the text). Retrieval is hybrid: vector similarity when an embedding
model is available, lexical otherwise. Both paths return the same shape, so the
workflow below does not change with the tier.

## The loop

1. **Search before answering** when the question touches indexed material:
   `knowledge_query(query)`. Prefer it over answering from memory — the vault is
   the user's own material and outranks anything you recall.
2. **Cite what you used.** Name the node/chunk you drew from. An uncited answer
   is indistinguishable from a guess, and the user cannot check it.
3. **Widen only if empty.** No hits → try `knowledge_neighbors(query)` to see
   what the graph actually holds near that topic, then re-query with the
   vocabulary the vault uses. Re-running the same words never helps.

## When NOT to search

Searching a vault that cannot answer costs a round-trip and buries the reply in
irrelevant chunks. Skip it for:

- procedural turns (ack, thanks, yes/no);
- general knowledge that is not in the user's material;
- anything you can answer from the current conversation.

`knowledge_status` tells you whether the vault is even populated. An empty vault
means every query is a wasted call — say so once, do not keep searching.

## Writing to the vault

- `knowledge_add_node(name, parent, triggers)` — a topic. `triggers` are the
  phrases that should surface it; pick words the user would actually type, not
  synonyms you invented.
- `knowledge_add_chunks(node, chunks)` — the text under a topic. Chunks want to
  be self-contained: a chunk that only makes sense next to its neighbour will be
  retrieved alone and read alone.
- `knowledge_ingest(path)` — bulk import; `knowledge_ingest_status` to follow it.

Do not paste secrets, tokens or credentials into a chunk. The vault is plain
text on disk and is surfaced verbatim into future conversations.

## Keeping it honest

`knowledge_health` is a read-only audit: broken hierarchy, duplicate names,
tiny/empty chunks, orphan nodes, chunks with no source. It flags, never deletes.
Run it after a bulk ingest — that is when structure breaks quietly.

## Paired with Neuron

When Gray Matter is the gateway, memory (Neuron) and knowledge (NeuRAG) are both
behind one connector. They answer different questions:

- **memory** — what was said, decided, learned in past turns (`pre_turn`/`store_turn`);
- **knowledge** — what the user's documents say (`knowledge_query`).

A question about a past decision is memory. A question about indexed material is
knowledge. When both apply, `gray_matter_pulse(topic)` merges them in one call.
