# Handoff: degradazione SQLite — NeuRAG + GM

## Problema

pyturso 0.6.1 su Windows **non rilascia il lock OS** dopo `conn.close()`. Questo è stato confermato con test cross-process: una volta che il processo A apre un DB Turso, il processo B non riesce ad aprirlo (errore "unable to open database file") anche dopo che A ha chiuso la connessione.

**Impatto**: Gray Matter (GM) apre il DB di NeuRAG via pyturso durante l'avvio dei worker MCP. Quando l'utente poi usa `neurag` da CLI, il processo neurag non riesce ad aprire lo stesso DB perché è già locked da GM.

## Soluzione attuale

Il `release_lock` pattern (rimuovere e riaprire la connessione) è stato **completamente eliminato** — non funziona su Windows. In suo luogo:

1. **`_turso_conn_cache`** tiene la connessione aperta per tutta la vita del processo (cache permanente).
2. **`_turso_locked`** flag: quando neurag CLI rileva che il DB è già aperto da un altro processo, **degrada a sqlite3** (fallback Python puro).
3. Nessun tentativo di rilasciare o riaprire il lock.

**Risultato**: GM worker usano Turso (SQL vector search). Neurag CLI usa sqlite3 (cosine Python-side). Stessi dati, stessa funzionalità, differenza irrilevante su poche centinaia di chunks.

## Limiti della soluzione attuale

- **Nessuna scrittura concorrente**: se GM sta scrivendo e neurag CLI prova a scrivere, la scrittura CLI fallisce (sqlite3 non supporta scritture concorrenti senza WAL).
- **Cosine Python vs SQL**: la cosine distance SQL di Turso è più veloce ma su 5-100 chunks la differenza è ms vs µs — irrilevante.
- **Indice vector search perduto**: su sqlite3, la ricerca vettoriale usa scan lineare Python. Su Turso, usa indice SQL. A 10k+ chunks diventa evidente.

## Possibili soluzioni future (quando DB cresce)

### Opzione A: Turso remoto (consigliata)
Usare un DB Turso hosted (libsql) invece di locale. Il lock OS non si applica — il lock è lato server, non lato client. Ogni processo apre la propria connessione TCP. Zero conflitti.
- Pro: zero modifica al codice, performances migliori, backup automatici
- Con: richiede account Turso (free tier sufficiente), latenza di rete (~10ms)

### Opzione B: Multi-process sqlite3 con WAL
Usare sqlite3 in modalità WAL (Write-Ahead Logging) che permette letture concorrenti while writing. Richiede che entrambi i processi usino sqlite3.
- Pro: nessuna dipendenza esterna
- Con: scritture concorrenti ancora serialized, WAL può crescere su workload pesante

### Opzione C: Server dedicato per vector search
Un mini-server FastAPI che espone `/search` e `/store` via HTTP. GM e neurag chiamano l'API invece di accedere direttamente al DB.
- Pro: zero conflitti file, versioning API, caching
- Con: un altro processo da gestire, over-engineering per 5 chunks

### Opzione D: Migrazione completa a sqlite3
Abbandonare pyturso per DB locali. Usare sqlite3 direttamente con indici vettoriali custom.
- Pro: nessun problema di lock, zero dipendenze esterne
- Con: perdita della cosine search SQL, re-implementazione di indici

## Raccomandazione

Per ora la soluzione attuale è sufficiente. Quando i chunks superano ~1000:
1. **Migrare a Turso remoto** (Opzione A) — la soluzione più pulita
2. Come fallback, **sqlite3 con WAL** (Opzione B) se non si vuole account esterno
3. Evitare Opzione C e D (over-engineering per il caso d'uso)
