# Audit — Gray-Matter (Neuron + NeuRAG) — DB corruption dopo ingest concorrente

**Data:** 2026-07-22
**Versione:** Gray-Matter v1.0.7
**Severità:** Alta — knowledge base NeuRAG corrotta, dati potenzialmente irrecuperabili senza backup

## Sintomo riportato

Dopo aver usato Neuron e/o lanciato un ingest NeuRAG, le chiamate successive all'LLM (via OpenCode) iniziano a fallire con "Internal Server Error".

## Stato attuale confermato

```
knowledge_status  → "database disk image is malformed"
knowledge_health  → "database disk image is malformed"
knowledge_ingest_status(job_id=f98c908b) → "No such job: f98c908b"
```

Il DB SQLite di NeuRAG (`C:\Users\recla\.local\share\neurag\knowledge.db`) è fisicamente corrotto. Il job di ingest che stava girando al momento della corruzione non è più tracciato — il registro dei job sembra essere in-memory e non è sopravvissuto a un riavvio/crash del processo.

`gray_matter_status` continua a riportare entrambi i server come `alive` con `pid=0`, il che indica che non sono processi OS separati ma girano in-process (probabilmente il layer gray-matter li invoca come moduli embedded, non subprocess). Questo è rilevante per la causa radice.

## Ricostruzione dell'incidente (dalla trace OpenCode)

1. `knowledge_ingest(path=C:\Users\recla\.config\opencode, godnode=OpenCode_Config)` → job `f98c908b` avviato in background (ingest di un'intera directory multi-plugin, centinaia di file).
2. Mentre il job risultava ancora `running` (confermato da polling ripetuto di `knowledge_ingest_status`), sono state lanciate **in parallelo, sullo stesso processo/DB**:
   - `gray_matter_status` (lettura)
   - `store_turn` (SCRITTURA su Neuron/Turso — turn 14 salvato)
   - `knowledge_query` x2 (lettura, ma innesca embedding on-the-fly)
   - `vector_search` (lettura + embedding on-the-fly)
   - `consolidate` (SCRITTURA — ha effettivamente droppato 5 concetti: "Neuron", "neurag", "knowledge-base", "encoding", "semantic-memory", mentre l'ingest stava ancora scrivendo chunk)
   - `pre_turn` (lettura)
   - `knowledge_tree` (lettura, ma dump completo e pesante dell'intero grafo, decine di nodi annidati, come ultima chiamata)
3. Al controllo successivo: DB malformato, job scomparso dal registro.

## Causa radice (ipotesi supportata dalle evidenze)

**Scrittura concorrente non serializzata sullo stesso file SQLite/Turso-locale.**

- SQLite ammette un solo writer alla volta. L'ingest scrive chunk + embeddings di continuo su `knowledge.db`. `consolidate` è anch'essa un'operazione di scrittura (merge/drop di nodi) ed è stata eseguita **durante** l'ingest attivo — esattamente l'anti-pattern che la guida interna di Neuron segnala ("non lanciare consolidate ad-hoc mentre altre operazioni sono in corso, coordinare prima").
- `store_turn` ha scritto un turn (44° nodo Neuron) nello stesso momento.
- Se il layer non usa WAL mode con `busy_timeout` adeguato, o se le connessioni non sono correttamente serializzate con un lock applicativo, due write concorrenti su SQLite possono lasciare pagine a metà scritte → `disk image malformed`. Questo è il sintomo SQLite classico per corruzione da I/O concorrente non protetto (non è corruzione "casuale", è quasi sempre lock/write mancante).
- Il fatto che `pid=0` per entrambi i server suggerisce che girano nello stesso processo/thread pool del gateway gray-matter: se le chiamate tool arrivano in parallelo (come nella trace) senza un mutex globale attorno alle operazioni di scrittura DB, la race è strutturale, non occasionale.
- Il job registry perso (`No such job: f98c908b`) indica inoltre che lo stato dei job di ingest è tenuto solo in memoria di processo: se il processo NeuRAG è crashato/si è riavviato a causa della corruzione, ha perso anche il tracking del job, oltre ai dati.

L'"Internal Server Error" visto lato LLM è quasi certamente il sintomo a valle: una chiamata tool che va in eccezione non gestita (SQLite corruption error) o in timeout durante il lock contention, che il gateway propaga come errore generico invece di un errore tool strutturato.

## Cosa serve fixare

1. **Serializzazione delle scritture**: un mutex/lock applicativo attorno a ogni operazione di scrittura su knowledge.db e sul DB Neuron (store_turn, consolidate, dedup, merge, knowledge_add_node, knowledge_add_chunks, e le fasi di scrittura interne di knowledge_ingest). Nessuna scrittura concorrente deve poter partire mentre un ingest è `running`.
2. **SQLite in WAL mode** con `busy_timeout` configurato, così letture concorrenti non bloccano lo scrittore e gli scrittori si accodano invece di corrompersi a vicenda.
3. **Job registry persistente**: lo stato dei job di ingest (non solo l'ultimo risultato ma anche checkpoint di avanzamento) va salvato su disco/DB separato dal knowledge.db target, così un crash a metà ingest non lo fa sparire e permette resume o almeno diagnosi post-mortem.
4. **Error handling esplicito**: le eccezioni SQLite (corruption, lock timeout) vanno intercettate e restituite come errore tool strutturato con messaggio chiaro, non lasciate propagare fino a generare un "Internal Server Error" generico lato client.
5. **Guardrail applicativo**: se possibile, il tool layer dovrebbe rifiutare/accodare chiamate a store_turn/consolidate/dedup/merge/knowledge_add_* quando esiste un ingest job con stato `running`, invece di eseguirle e basta.
6. **Recovery immediato**: il knowledge.db attuale è corrotto. Serve `PRAGMA integrity_check` per capire l'estensione del danno, poi probabilmente ricostruzione da un backup (se esiste) o re-ingest completo da zero delle fonti originali (i file su disco non sono stati toccati, solo il DB derivato).

## Non toccato / non causa

- Neuron (Turso locale) risulta ancora leggibile (`status`, `vector_search` hanno risposto normalmente prima della verifica finale) — il danno sembra circoscritto al DB SQLite di NeuRAG, coerente con il fatto che l'ingest pesante scriveva lì.
- Le dimensioni dei payload di ritorno (vector_search, knowledge_query) sono risultate compatte nei test — non è un problema di contesto/token, è un problema di integrità DB lato server.
