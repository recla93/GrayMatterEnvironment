# ADR-008: Architettura Memoria a 4 Livelli

**Stato:** Accepted (2026-07-26)
**Data:** 2026-07-26
**Deciders:** recla93 (owner)
**Fase roadmap:** 5 — ottimizzazione memoria

## Contesto

Prima di questo ADR, Neuron gestiva la memoria su due livelli impliciti:
- **Grafo attivo** (SQLite): nodi, link, salienza, consolidamento
- **Graveyard** (tabella separata): nodi droppati dal consolidamento, accessibili solo tramite `load_graveyard`

Mancavano: una working memory per sessione, un modo per riattivare conoscenza archiviata,
e meccanismi per evitare ridondanza semantica e favorire diversità nei risultati.

Il modello LLM ha un budget token fisso. Ogni token speso per contesto ridotto è un token
risparmiato per il ragionamento. L'obiettivo è: **massima rilevanza, minimo dispendio**.

## Decisione

Implementare un'architettura a 4 livelli ispirata alla memoria umana:

```
L1  Session Cache     Working memory (in-memory + persistita)
    ↓ TTL expiry (10 turni) + cap (8 entries)
L2  Active Graph      Grafo SQLite (nodi, link, salienza, trust)
    ↓ consolidamento orfanotrofio → graveyard
L3  Graveyard         Memoria a lungo termine archiviata
    ↓ decay periodico → L4
L4  Forgotten         Nodi con salience=0 nel graveyard (irrecuperabili)
```

### L1 — Session Cache (Working Memory)

**Dove:** `Graph._session_cache: dict` in memoria + serializzato in `meta` table JSON.

**Come funziona:**
- Ogni keyword confermata (`confirm`), salvata (`store_turn` con salience≥3) o recallata
  entra in cache con score `min(1.0, salience / 10.0)`
- Il cache ha TTL di 10 turni e cap di 8 entries (FIFO eviction)
- Al `pre_turn`, le entry scadute vengono espulse
- Al riavvio del server, il cache viene ricaricato dalla tabella `meta`
- Il `dismiss` rimuove la keyword dalla cache

**Perché:** Quando un modello chiama `pre_turn`, le keyword più rilevanti per il turno
corrente dovrebbero essere già "calde" nella working memory. Il cache evita di dover
ricalcolare la rilevanza da zero.

**Costo:** 8 entry × ~20 byte = ~160 byte in memoria. Trascurabile.

### L2 — Active Graph

**Dove:** SQLite WAL, nodi + link + episodes.

**Come funziona:**
- Ogni `store_turn` aggiunge/aggiorna nodi e link
- Ogni `confirm` boosta salienza e trust
- Il consolidamento periodico (ogni 8 turni) fonde nodi simili e droppa orfani
- Il `prune_tangential` rimuove link tangential inattivi dopo 6 turni
- I nodi droppati dal consolidamento vanno in L3 (graveyard)

**Novità FASE 5:**
- **Semantic dedup** (FASE 5.5): prima di creare un nuovo nodo, viene verificata la
  similarità coseno con i nodi multi-parola esistenti. Se cosine > 0.90, il nuovo keyword
  viene fuso nel nodo esistente invece di crearne uno nuovo.
- **MMR diversification** (FASE 5.6): a depth≥2, i top_nodes vengono re-rankati con
  Maximal Marginal Relevance (λ=0.7) per evitare nodi quasi-identici.

### L3 — Graveyard (Long-Term Memory)

**Dove:** Tabella `graveyard` nello stesso SQLite, keyword + metadata + decay counter.

**Come funziona:**
- I nodi droppati dal consolidamento entrano nel graveyard
- Ogni 8 turni, il decay riduce la salienza di 1 punto
- I nodi con salienza raggiungono 0 passano a L4
- **Memory recall** (FASE 5.3): il motore di stimolo cerca nel graveyard nodi semanticamente
  simili al turno corrente. Se trovati, vengono proposti come "💡 Memory recall" con
  penalità leggera (×0.9) rispetto ai nodi attivi.
- **Tool `recall`** (FASE 5.3): riporta esplicitamente un nodo dal graveyard al grafo attivo
  con salienza base di 3.

**Perché:** Il graveyard trasforma i nodi droppati da " morti" a "memoria a lungo termine".
Un concetto che non è stato toccato da 20 turni può ancora riemergere se semanticamente
rilevante — come la memoria umana che recupera informazioni "dimenticate" quando diventano
rilevanti.

### L4 — Forgotten

**Dove:** Nel graveyard con salienza = 0.

**Come funziona:**
- Raggiunto quando il decay in L3 porta la salienza a 0
- Non viene più cercato dal memory recall
- Può essere recuperato solo con `recall` esplicito

**Perché:** Un limite必须 per evitare che il graveyard cresca indefinitamente. I nodi
dimenticati restano nel DB (non vengono cancellati) ma non consumano compute.

## Tool associati

| Tool | Livello | Scopo |
|------|---------|-------|
| `dismiss` | L1+L2 | Abbassa salienza e trust, rimuove dalla session cache |
| `recall` | L3→L2 | Riporta un nodo dal graveyard al grafo attivo |
| `confirm` | L1+L2 | Boosta salienza/trust, entra in session cache |
| `store_turn` | L1+L2 | Aggiunge nodi con semantic dedup |
| `pre_turn` | L1+L2+L3 | Carica cache, propone memory recall |
| `get_context` | L2 | Ricerca con MMR a depth≥2 |

## Costi e trade-off

| Componente | Costo | Benefit |
|-----------|-------|---------|
| Session cache | ~160 byte RAM, ~0.1ms/turn | Evita ricalcolo rilevanza |
| Semantic dedup | 2 embedding calls per keyword multi-word | Riduce nodi duplicati ~15-30% |
| MMR | 2-10 embedding calls extra a depth≥2 | Diversifica risultati, riduce ridondanza |
| Memory recall | 1-3 embedding calls nel graveyard | Riporta conoscenza archiviata |
| Graveyard decay | 1 UPDATE SQL ogni 8 turni | Previene crescita indefinita |

**Budget embedding totale:** worst case ~15 calls/turn (3 keyword × 2 dedup + 3 recall + 5 MMR).
A ~0.5ms/call su CPU = ~7.5ms extra. Accettabile.

## Cross-references

- [[03-stimulus-engine]] — Il motore di stimolo che genera i memory recall
- [[02-vectors-consolidation]] — Il consolidamento che droppa nodi in L3
- [[04-drift-sleep]] — Il meccanismo di sleep che integra il decay del graveyard
