# Cross-Linking Design — NeuRAG Knowledge Graph

## Problema

NeuRAG attualmente è un gerarchia di nodi con search vettoriale sui chunk.
Non ha link strutturali tra nodi — è un database gerarchico, non un grafo.

**Obiettivo**: collegare nodi che condividono concetti, rendendo la knowledge
graph effettivamente un grafo con relazioni esplicite.

---

## 1. Schema — tabella `node_links`

```sql
CREATE TABLE IF NOT EXISTS node_links (
    source_id   INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id   INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    link_type   TEXT NOT NULL CHECK(link_type IN ('tag_overlap', 'cross_ref', 'semantic')),
    weight      REAL DEFAULT 1.0,   -- 0.0-1.0, Jaccard o frequenza normalizzata
    evidence    TEXT DEFAULT '',     -- breve frase che giustifica il link
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source_id, target_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_links_source ON node_links(source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON node_links(target_id);
CREATE INDEX IF NOT EXISTS idx_links_type   ON node_links(link_type);
```

**Scelte**:
- Chiave primaria composta (source, target, type) → un solo link per tipo per coppia
- Bidirezionale: `link(A→B, tag_overlap)` + `link(B→A, tag_overlap)` — o lookup bidirezionale in query
- `evidence` per debugging trasparente
- `weight` 0-1 per ranking dei link

---

## 2. Tag-Based Linking

### Algoritmo

```python
def link_by_tags(kg, min_jaccard=0.15):
    """Collega nodi che condividono almeno min_jaccard dei tag."""
    nodes = kg.get_all_nodes_with_tags()
    links_created = 0
    
    for i, a in enumerate(nodes):
        tags_a = set(json.loads(a["tags"]))
        if not tags_a:
            continue
        for b in nodes[i+1:]:
            tags_b = set(json.loads(b["tags"]))
            if not tags_b:
                continue
            
            # Jaccard similarity
            intersection = tags_a & tags_b
            union = tags_a | tags_b
            jaccard = len(intersection) / len(union) if union else 0
            
            if jaccard >= min_jaccard:
                evidence = f"shared: {', '.join(sorted(intersection)[:3])}"
                kg.upsert_link(a["id"], b["id"], "tag_overlap", jaccard, evidence)
                links_created += 1
    
    return links_created
```

### Complessità

- **Tempo**: O(n² × t) dove n = nodi, t = tag medi per nodo
- **Spazio**: O(n × t) per caricare i tag
- **Scalabilità**: con1000 nodi e 10 tag → ~5M confronti (lento)
- **Ottimizzazione**: inverted index sui tag → O(n × t × k) dove k = nodi per tag

### Inverted Index (ottimizzazione)

```python
def link_by_tags_fast(kg, min_jaccard=0.15):
    """Versione ottimizzata con inverted index."""
    nodes = kg.get_all_nodes_with_tags()
    
    # Inverted index: tag → set di node_id
    tag_index = {}
    for n in nodes:
        for t in json.loads(n["tags"]):
            tag_index.setdefault(t, set()).add(n["id"])
    
    # Per ogni coppia di nodi, conta i tag in comune
    pair_counts = {}
    for tag, node_ids in tag_index.items():
        for nid in node_ids:
            for other_id in node_ids:
                if other_id > nid:  # evita duplicati
                    pair = (nid, other_id)
                    pair_counts[pair] = pair_counts.get(pair, 0) + 1
    
    # Calcola Jaccard e crea link
    nodes_map = {n["id"]: n for n in nodes}
    links_created = 0
    for (a_id, b_id), shared in pair_counts.items():
        tags_a = set(json.loads(nodes_map[a_id]["tags"]))
        tags_b = set(json.loads(nodes_map[b_id]["tags"]))
        union = len(tags_a | tags_b)
        jaccard = shared / union if union else 0
        
        if jaccard >= min_jaccard:
            evidence = f"{shared}/{union} tags shared"
            kg.upsert_link(a_id, b_id, "tag_overlap", jaccard, evidence)
            links_created += 1
    
    return links_created
```

### Test Cases

```python
def test_tag_overlap_basic():
    """Due nodi con tag in comune → link creato."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("Java", "fundamental", parent_id=0, tags=["backend", "jvm", "oop"])
    b = kg.add_node("Kotlin", "fundamental", parent_id=0, tags=["backend", "jvm", "conciseness"])
    # Jaccard = 2/4 = 0.5 → sopra soglia
    count = link_by_tags(kg, min_jaccard=0.15)
    assert count == 1
    links = kg.get_links(a)
    assert len(links) == 1
    assert links[0]["target_id"] == b
    assert links[0]["link_type"] == "tag_overlap"
    assert 0.4 < links[0]["weight"] < 0.6  # ~0.5

def test_tag_overlap_no_common_tags():
    """Due nodi senza tag in comune → nessun link."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("Python", "fundamental", parent_id=0, tags=["scripting", "dynamic"])
    b = kg.add_node("SQL", "fundamental", parent_id=0, tags=["query", "declarative"])
    count = link_by_tags(kg, min_jaccard=0.15)
    assert count == 0

def test_tag_overlap_below_threshold():
    """Jaccard sotto soglia → nessun link."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["x", "y", "z"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["x", "w"])
    # Jaccard = 1/4 = 0.25 → sopra 0.15
    count = link_by_tags(kg, min_jaccard=0.3)
    assert count == 0  # sotto 0.3

def test_tag_overlap_idempotent():
    """Rieseguire non duplica i link."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["x", "y"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["y", "z"])
    link_by_tags(kg)
    link_by_tags(kg)  # secondo giro
    links = kg.get_links(a)
    assert len(links) == 1  # upsert, non insert

def test_tag_overlap_inverted_index():
    """Versione ottimizzata produce stessi risultati."""
    kg = KnowledgeGraph(":memory:")
    # 10 nodi, tag casuali
    nodes = []
    for i in range(10):
        tags = [f"tag_{j}" for j in range(5) if (i + j) % 3 == 0]
        nodes.append(kg.add_node(f"N{i}", "fundamental", parent_id=0, tags=tags))
    
    count_basic = link_by_tags(kg, min_jaccard=0.1)
    # Reset links
    kg._conn.execute("DELETE FROM node_links")
    kg._conn.commit()
    count_fast = link_by_tags_fast(kg, min_jaccard=0.1)
    assert count_basic == count_fast
```

---

## 3. Cross-References (menzioni nei chunk)

### Algoritmo

```python
def link_by_cross_refs(kg, min_mentions=2):
    """Collega nodi quando i chunk di uno menzionano il nome/triggers di un altro."""
    nodes = kg.get_all_nodes_with_triggers()
    node_map = {n["id"]: n for n in nodes}
    
    # Build trigger → node_id index
    trigger_index = {}
    for n in nodes:
        for t in json.loads(n.get("triggers", "[]")):
            trigger_index.setdefault(t.lower(), set()).add(n["id"])
        # Also index the node name
        trigger_index.setdefault(n["name"].lower(), set()).add(n["id"])
    
    # Scan all chunks for mentions
    mention_counts = {}  # (source_node_id, target_node_id) → count
    chunks = kg._conn.execute(
        "SELECT c.id, c.node_id, c.text FROM chunks c"
    ).fetchall()
    
    for chunk_id, node_id, text in chunks:
        text_lower = text.lower()
        for trigger, target_ids in trigger_index.items():
            if trigger in text_lower:
                for target_id in target_ids:
                    if target_id != node_id:
                        pair = (node_id, target_id)
                        mention_counts[pair] = mention_counts.get(pair, 0) + 1
    
    # Create links for pairs with enough mentions
    links_created = 0
    for (source, target), count in mention_counts.items():
        if count >= min_mentions:
            # Weight: normalized by chunk count of source node
            source_chunks = kg._conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE node_id = ?", (source,)
            ).fetchone()[0]
            weight = min(1.0, count / max(source_chunks, 1))
            evidence = f"mentioned {count}x in chunks"
            kg.upsert_link(source, target, "cross_ref", weight, evidence)
            links_created += 1
    
    return links_created
```

### Complessità

- **Tempo**: O(C × T) dove C = chunk totali, T = trigger unici
- **Spazio**: O(T × N) per l'inverted index
- **Scalabilità**: con10k chunk e 500 trigger → ~5M confronti (accettabile)
- **Ottimizzazione**: embedding similarity tra node (media chunk) per ridurre i confronti

### Test Cases

```python
def test_cross_ref_basic():
    """Chunk di Java menziona 'Spring' → link Java→Spring."""
    kg = KnowledgeGraph(":memory:")
    java = kg.add_node("Java", "fundamental", parent_id=0, triggers=["java", "jvm"])
    spring = kg.add_node("Spring", "fundamental", parent_id=0, triggers=["spring", "di", "ioc"])
    kg.add_chunk(java, "Java works well with Spring framework for enterprise apps")
    kg.add_chunk(java, "Spring Boot simplifies Java deployment")
    kg.add_chunk(spring, "Spring provides dependency injection for Java")
    
    count = link_by_cross_refs(kg, min_mentions=1)
    assert count >= 1
    links = kg.get_links(java)
    assert any(l["target_id"] == spring for l in links)

def test_cross_ref_no_mentions():
    """Chunk senza menzioni → nessun link."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("A", "fundamental", parent_id=0, triggers=["a"])
    b = kg.add_node("B", "fundamental", parent_id=0, triggers=["b"])
    kg.add_chunk(a, "This text mentions nothing about B at all")
    count = link_by_cross_refs(kg, min_mentions=1)
    assert count == 0

def test_cross_ref_min_mentions():
    """Soglia minima menzioni."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("A", "fundamental", parent_id=0, triggers=["a"])
    b = kg.add_node("B", "fundamental", parent_id=0, triggers=["b"])
    kg.add_chunk(a, "B is mentioned once here")
    count = link_by_cross_refs(kg, min_mentions=3)
    assert count == 0  # sotto soglia
```

---

## 4. Semantic Linking (embedding similarity tra node)

### Algoritmo

```python
def link_by_semantic(kg, min_cosine=0.6):
    """Collega nodi con embedding media simili."""
    nodes = kg.get_all_nodes_with_embeddings()
    if len(nodes) < 2:
        return 0
    
    # Compute mean embedding per node
    node_embeddings = {}
    for n in nodes:
        chunks = kg.get_chunks(n["id"])
        embedded = [kg._unpack_vec(c["embedding"]) for c in chunks if c.get("embedding")]
        if embedded:
            dim = len(embedded[0])
            mean = [sum(v[i] for v in embedded) / len(embedded) for i in range(dim)]
            node_embeddings[n["id"]] = mean
    
    # Pairwise cosine similarity
    links_created = 0
    node_ids = list(node_embeddings.keys())
    for i, a_id in enumerate(node_ids):
        for b_id in node_ids[i+1:]:
            sim = kg._cosine_sim(node_embeddings[a_id], node_embeddings[b_id])
            if sim >= min_cosine:
                evidence = f"semantic similarity: {sim:.2f}"
                kg.upsert_link(a_id, b_id, "semantic", sim, evidence)
                links_created += 1
    
    return links_created
```

### Complessità

- **Tempo**: O(n² × d) dove n = nodi embedded, d = dimensione embedding (384)
- **Spazio**: O(n × d) per le medie
- **Scalabilità**: con1000 nodi → ~500k confronti × 384 dim = ~192M operazioni (lento)
- **Ottimizzazione**: LSH (Locality-Sensitive Hashing) per ridurre a O(n × d)

### Test Cases

```python
def test_semantic_similar_nodes():
    """Nodi con chunk semanticamente simili → link."""
    kg = KnowledgeGraph(":memory:")
    # Importa documenti simili
    a = kg.add_node("Java", "fundamental", parent_id=0)
    b = kg.add_node("Kotlin", "fundamental", parent_id=0)
    kg.add_chunk(a, "Object-oriented programming with classes and inheritance")
    kg.add_chunk(b, "Object-oriented programming with classes and data classes")
    # Embeddings dovrebbero essere simili
    count = link_by_semantic(kg, min_cosine=0.5)
    # Il test dipende dall'embedder — potrebbe non collegare se i testi sono troppo diversi

def test_semantic_different_nodes():
    """Nodi con chunk diversi → nessun link."""
    kg = KnowledgeGraph(":memory:")
    a = kg.add_node("Python", "fundamental", parent_id=0)
    b = kg.add_node("SQL", "fundamental", parent_id=0)
    kg.add_chunk(a, "Dynamic scripting language with indentation syntax")
    kg.add_chunk(b, "Structured query language for relational databases")
    count = link_by_semantic(kg, min_cosine=0.8)
    assert count == 0
```

---

## 5. API Estesa

### Nuovi metodi su KnowledgeGraph

```python
def upsert_link(self, source_id: int, target_id: int, 
                link_type: str, weight: float, evidence: str = "") -> None:
    """Inserisce o aggiorna un link tra due nodi."""
    if source_id == target_id:
        return  # mai self-link
    self._conn.execute("""
        INSERT INTO node_links (source_id, target_id, link_type, weight, evidence, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(source_id, target_id, link_type) DO UPDATE SET
            weight = excluded.weight,
            evidence = excluded.evidence,
            updated_at = datetime('now')
    """, (source_id, target_id, link_type, weight, evidence))
    self._conn.commit()

def get_links(self, node_id: int, link_type: Optional[str] = None) -> list[dict]:
    """Restituisce tutti i link di un nodo (outgoing + incoming)."""
    sql = """
        SELECT nl.*, n.name as target_name, n.node_type as target_type
        FROM node_links nl
        JOIN nodes n ON n.id = nl.target_id
        WHERE nl.source_id = ?
    """
    params = [node_id]
    if link_type:
        sql += " AND nl.link_type = ?"
        params.append(link_type)
    
    # Bidirectional: anche incoming
    sql += """
        UNION
        SELECT nl.*, n.name as target_name, n.node_type as target_type
        FROM node_links nl
        JOIN nodes n ON n.id = nl.source_id
        WHERE nl.target_id = ?
    """
    params.append(node_id)
    if link_type:
        sql += " AND nl.link_type = ?"
        params.append(link_type)
    
    return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

def get_link_graph(self) -> list[dict]:
    """Restituisce tutti i link per visualizzazione grafo."""
    rows = self._conn.execute("""
        SELECT nl.*, 
               s.name as source_name, s.node_type as source_type,
               t.name as target_name, t.node_type as target_type
        FROM node_links nl
        JOIN nodes s ON s.id = nl.source_id
        JOIN nodes t ON t.id = nl.target_id
    """).fetchall()
    return [dict(r) for r in rows]

def rebuild_links(self, tag_weight=0.5, cross_ref_weight=0.3, semantic_weight=0.2):
    """Ricostruisce tutti i link da zero."""
    self._conn.execute("DELETE FROM node_links")
    self._conn.commit()
    
    tag_count = link_by_tags(self)
    cross_count = link_by_cross_refs(self)
    semantic_count = link_by_semantic(self)
    
    return {
        "tag_overlap": tag_count,
        "cross_ref": cross_count,
        "semantic": semantic_count,
        "total": tag_count + cross_count + semantic_count
    }
```

---

## 6. Integrazione con Search

> **Stato in v1.0.0 (2026-07-21):** spedita la versione **enrich-only**. Firma
> reale `search_with_links(query, top_k=5)`: fa la `search` normale e annota ogni
> risultato con un campo `links` verso gli altri nodi-risultato — **non** espande
> i risultati con chunk dai nodi collegati. Lo schema qui sotto (`include_linked`
> + espansione + budget `top_n*2`) è il design completo, tenuto come **tech-debt**
> post-v1. Nota: `search_with_links` **non è esposto come tool MCP** (usato solo dai
> test); `knowledge_query` usa la `search` semplice e `knowledge_neighbors` copre
> l'espansione via grafo.

### Search arricchita con link (design completo — non ancora spedito)

```python
def search_with_links(self, query: str, top_n: int = 5, include_linked: bool = True) -> list[dict]:
    """Search cheinclude chunk dai nodi collegati."""
    # Prima: search normale
    results = self.search(query, top_n=top_n)
    
    if not include_linked:
        return results
    
    # Seconda: per ogni risultato, aggiungi chunk dai nodi collegati
    seen_chunk_ids = {r["id"] for r in results}
    extra = []
    
    for r in results:
        node_id = r["node_id"]
        links = self.get_links(node_id)
        for link in links:
            linked_node_id = link["target_id"]
            linked_chunks = self.get_chunks(linked_node_id)
            for lc in linked_chunks:
                if lc["id"] not in seen_chunk_ids and lc.get("embedding"):
                    # Score: media tra score originale e similarità del link
                    linked_score = self._cosine_sim(
                        self._get_embedding(query),
                        self._unpack_vec(lc["embedding"])
                    )
                    blended = linked_score * link["weight"]  # weight-based blending
                    extra.append((blended, lc))
                    seen_chunk_ids.add(lc["id"])
    
    # Merge e rank
    extra.sort(key=lambda x: x[0], reverse=True)
    for score, chunk in extra[:top_n]:
        chunk["linked_score"] = score
        chunk["linked_from"] = True
        results.append(chunk)
    
    return results[:top_n * 2]  # espandi budget
```

---

## 7. Piano di Implementazione

### Fase1: Schema + upsert_link + get_links (base)
- Nuova tabella `node_links`
- Metodi CRUD base
- Test: upsert, get, bidirectional

### Fase2: tag-based linking (più semplice, alto valore)
- `link_by_tags()` con inverted index
- Test: Jaccard, threshold, idempotenza

### Fase3: cross-references (medio valore)
- `link_by_cross_refs()` con trigger index
- Test: menzioni, soglia, nessun self-link

### Fase4: semantic linking (opzionale, bassa priorità)
- `link_by_semantic()` con media embedding
- Test: similarità, diversità

### Fase5: search arricchita + CLI
- `search_with_links()`
- CLI: `neurag links` per visualizzare il grafo
- Test: search con link, budget espanso

---

## 8. Metriche di Successo

| Metrica | Target | Misura |
|---------|--------|--------|
| Link creati | >5 per10 nodi | `rebuild_links()` |
| Latenza search | <2x search normale | benchmark |
| Copertura link | >30% nodi collegati | `get_link_graph()` |
| False positive | <10% link errati | test manuali |
