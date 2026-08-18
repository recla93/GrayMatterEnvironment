# Strumenti MCP — riferimento completo

> Ogni strumento MCP esposto da Neuron, Gray Matter e NeuRAG. Firme verificate
> contro il codice sorgente. Quando si usa il gateway Gray Matter, tutti gli
> strumenti dei sub-server registrati vengono ripubblicati con i nomi originali.

---

## Strumenti Gray Matter

Definiti in `gray_matter/server.py`.

### gray_matter_pulse

Chiamata principale dell'orchestrator. Chiama Neuron `get_context` e NeuRAG `knowledge_query` in parallelo, unisce i risultati, applica la cache, lancia il flash ai cambio di topic.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `topic` | string | si | — | Topic da cercare (max 200 caratteri) |
| `top_n` | integer | no | 5 | Numero di chunk NeuRAG (1-10) |

**Restituisce:** Testo unito da contesto Neuron + risultati NeuRAG + link bridge + flash + vicini proattivi.

### gray_matter_status

Mostra i server registrati, lo stato della cache e i contatori dell'orchestrator.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### gray_matter_bridge

Salva un bridge cross-store: un link tra un concetto Neuron e un nodo NeuRAG. Idempotente.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `neuron_concept` | string | si | — | Concetto/keyword Neuron |
| `neurag_node` | string | si | — | Nodo/topic NeuRAG |
| `rationale` | string | no | `""` | Perche sono collegati |

---

## Strumenti Neuron

Tutti definiti in `neuron/server.py`. Il loop fondamentale e composto da due passi per turno:
1. `pre_turn` (prima di rispondere) — carica il contesto
2. `store_turn` (dopo aver risposto) — persiste ci che e nuovo

### pre_turn

LOOP DI MEMORIA — PASSO 1. Carica il contesto rilevante in un colpo solo (status + get_context in forma compatta). Inseriscilo silenziosamente nella tua risposta.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `topic` | string | si | — | Topic o domanda corrente |
| `keywords` | string[] | no | `[]` | Keyword aggiuntive per ampliare la ricerca |
| `max_tokens` | integer | no | 200 | Dimensione massima output in token approssimativi |

### store_turn

LOOP DI MEMORIA — PASSO 2. Persiste ci che e nuovo nella memoria a lungo termine. Cura per un grafo pulito.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `topic` | string | si | — | Topic del turno (3-5 parole) |
| `keywords` | string[] | si | — | Keyword astratte (3-5, solo concetti) |
| `domain` | string | si | — | Label libera (es. `backend`, `AI`, `general`) |
| `intent` | string (enum) | si | — | Uno tra: `question`, `task`, `exploration`, `clarification`, `feedback` |
| `sentiment` | string (enum) | si | — | Uno tra: `neutral`, `positive`, `critical`, `urgent` |
| `context` | string | no | `""` | Percorso contesto (es. `java/spring`). Default: contesto attivo |
| `episode` | string | no | — | UNA frase compatta (max ~200 caratteri) |
| `entities` | string[] | no | `[]` | Entita esplicite (max 15) |
| `tags` | string[] | no | `[]` | Label libere (max 10) |
| `references` | object[] | no | `[]` | Riferimenti file/URL/commit (max 20) |
| `links` | object[] | no | `[]` | Edge tipati tra keyword |

**Schema links[]:** `{ source: string, target: string, link_type: string (cause-effect|analogy|evolution|contrast|deepening|instance-of), weight: string (strong|medium|tangential), rationale: string (max 200 caratteri) }`

### get_context

Recupera nodi e link correlati a un topic. Chiama prima di rispondere quando il contesto precedente potrebbe essere rilevante.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `topic` | string | si | — | Keyword principale da cercare |
| `keywords` | string[] | no | `[]` | Keyword aggiuntive per ampliare la ricerca |
| `depth` | integer | no | 1 | Profondita di ricerca (1-3) |
| `max_tokens` | integer | no | 400 | Dimensione massima output in token |
| `format` | string (enum) | no | `"full"` | `"full"` (multi-linea) o `"compact"` (singola riga per iniezione) |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### confirm

Segnale di feedback: rinforza la salience delle keyword utili per farle emergere piu prominentemente nel future retrieval.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `keywords` | string[] | si | — | Keyword che sono state effettivamente utili |
| `boost` | integer | no | 2 | Boost salience (max 5) |
| `confidence` | number | no | 1.0 | Quanto era utile il contesto (-1 a 1). NEGATIVO = refute: riduce la fiducia |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### find_candidates

Screening: trova keyword simili esistenti via ricerca vettoriale. Chiama prima di store_turn per evitare duplicati.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `keywords` | string[] | si | — | Keyword per cui trovare candidati simili |
| `top_n` | integer | no | 8 | Numero di candidati |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### vector_search

Ricerca vettoriale semantica via Turso `vector_distance_cos` o fallback cosine Python.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `keywords` | string[] | si | — | Keyword di query |
| `top_n` | integer | no | 8 | Numero di risultati |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### summary

Riassunto testuale del grafo: keyword principali, link recenti, salute, concetti dimenticati.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### introspect

Autocoscienza Neuron (C3): concetti forti, crescita recente, dominio debole, conformita al loop. Restituisce JSON.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### forgotten

Trova keyword non toccate da N turni (salience in decadimento). Con `near`, ordina i concetti dormienti per similarita a fascia media con un topic.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `threshold` | integer | no | 5 | Soglia turni di inattivita |
| `top_n` | integer | no | 10 | Quanti mostrare |
| `near` | string | no | — | Topic contro cui ordinare i concetti dormienti (fascia media 0.30-0.75) |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### prune

Elimina forzatamente i link tangential inattivi.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |
| `dry_run` | boolean | no | false | Anteprima: elenca cosa verrebbe eliminato senza cancellare |

### consolidate

Fondi concetti quasi-duplicati (coseno) e archivia orfani a bassa salience nel `_graveyard`. Sicuro da eseguire periodicamente.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |
| `merge` | boolean | no | true | Fondi nodi quasi-duplicati |
| `drop_orphans` | boolean | no | true | Archivia nodi orfani a bassa salience |
| `sim_threshold` | number | no | 0.85 | Soglia coseno per il merge |

### dedup

Attiva/disattiva la deduplicazione delle keyword. L'output riporta lo stato ON/OFF risultante.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `enable` | boolean | no | (toggle) | Imposta esplicitamente. Ometti per invertire |

### flash

Attiva/disattiva i flashback semantici.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### reset

Resetta il grafo e ricomincia. DESTRUTTIVO e irreversibile.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `confirm` | boolean | si | — | Deve essere true per cancellare il grafo |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### extract

Estrazione semantica automatica dal testo: keyword, topic, dominio, intent, sentiment, entita. Euristica (0 costo in token).

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `text` | string | si | — | Testo da analizzare |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### auto

Fallback POST (0 token): extract + cambio topic + auto-link + save. Preferire store_turn curato quando possibile.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `text` | string | si | — | Messaggio utente da analizzare e archiviare |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### export

Esporta l'intero grafo come JSON.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### merge

Fondi nodi duplicati o quasi-duplicati. Sposta tutti i link dagli alias al canonicale, somma la salience, poi elimina gli alias.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `canonical` | string | si | — | La keyword da mantenere come nodo unico autorevole |
| `aliases` | string[] | si | — | Keyword da assorbire nel canonicale ed eliminare |
| `context` | string | no | `""` | Percorso contesto. Default: contesto attivo |

### switch_context

Cambia il contesto attivo (crea se nuovo). Es. `java/spring`, `python/django`.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `context` | string | si | — | Percorso contesto a cui passare |

### list_contexts

Elenca tutti i contesti disponibili con metadati.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `parent` | string | no | — | Filtro padre opzionale |

### help

Mostra ogni comando Neuron (uno per riga) plus come usare Neuron bene.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### skill

Restituisce il testo completo di un playbook/skill Neuron su richiesta.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `name` | string (enum) | no | `"playbook"` | `playbook` (workflow PRE/POST completo) o `curated` (pattern grafo pulito) |

### status

Stato corrente del grafo: conteggio nodi/link, salute e configurazione attiva (tier DB, contesto attivo). Read-only — la prima chiamata sicura per ispezionare il grafo di memoria.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

---

## Strumenti NeuRAG

Tutti definiti in `neurag/server.py`. La knowledge base usa un albero gerarchico di nodi (godnode/fundamental/specialization) con contenuto suddiviso in chunk.

### knowledge_index

Dividi un file o directory in chunk senza salvare. Restituisce JSON lista di chunk. L'LLM poi chiama `knowledge_add_node` + `knowledge_add_chunks` per organizzarli.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `path` | string | si | — | Percorso assoluto a un file o directory da suddividere |

### knowledge_add_node

Crea un nodo nella gerarchia.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `name` | string | si | — | Nome nodo (es. `Java`, `Spring_Boot`) |
| `node_type` | string (enum) | si | — | `godnode` (topic radice), `fundamental` (area), `specialization` (approfondimento) |
| `parent_name` | string | no | — | Nome nodo padre. Ometti per godnode. Obbligatorio per fundamental e specialization |
| `triggers` | string[] | no | `[]` | Parole chiave che attivano questo nodo su knowledge_query |

### knowledge_add_chunks

Allega chunk precedentemente indicizzati a un nodo.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `node_name` | string | si | — | Nome nodo target |
| `chunks` | object[] | si | — | Chunk dall'output di knowledge_index |

**Schema chunks[]:** `{ text: string, source: string, section: string, chunk_index: integer }`

### knowledge_query

Cerca nella knowledge base chunk rilevanti per un topic. Fallback a tre livelli: match trigger → vector SQL → cosine Python / TF-IDF.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `query` | string | si | — | Topic o domanda |
| `top_n` | integer | no | 5 | Numero di risultati (1-10) |

### knowledge_status

Mostra lo stato della knowledge base: engine, conteggio nodi, conteggio chunk.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### knowledge_tree

Mostra l'albero gerarchico dei nodi dalla radice.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### knowledge_health

Audit strutturale: gerarchia rotta, chunk vuoti, nomi duplicati (serio) + nodi orfani, chunk senza sorgente, nodi senza trigger (avvisi). Read-only.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### knowledge_link_graph

Mostra tutti i link dei nodi (tag_overlap, cross_ref) con pesi ed evidenze.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### knowledge_rebuild_links

Cancella tutti i link e ricostruisci da tag (Jaccard) + cross-ref (file sorgente condivisi). Restituisce il conteggio dei link creati.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| (nessuno) | | | | |

### knowledge_neighbors

Vicinato strutturato di un nodo. BFS su padre/figli/link fino a `depth` hop. Solo SQL, nessun embedding.

| Parametro | Tipo | Obbligatorio | Default | Descrizione |
|---|---|---|---|---|
| `query` | string | si | — | Topic/keyword da risolvere in un nodo (match trigger prima, nome esatto dopo) |
| `depth` | integer | no | 2 | Hop (1-3) |
| `limit` | integer | no | 5 | Max vicini (1-20) |

**Restituisce:** JSON `{ node: {name, path}, neighbors: [{name, path, node_type, relation, distance}] }`. Nodo vuoto = nessun match.

---

## Prossimi passi

- [Riferimento CLI](CLI.it.md) — tutti i comandi a riga di comando
- [Configurazione](CONFIGURATION.it.md) — env var e knob
- [Architettura](ARCHITECTURE.it.md) — come gli strumenti si collegano
