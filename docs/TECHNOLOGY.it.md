# Scelte tecnologiche

> Ogni decisione tecnologica significativa nel Gray Matter Environment.
> Formato: problema → alternative scartate → scelta → perché → limiti accettati.

---

## 1. Storage engine: libSQL / Turso

**Problema:** Serve persistenza del grafo per nodi/link di Neuron e chunk/nodi di NeuRAG, con vettoriale opzionale e accesso multi-processo.

**Alternative scartate:**
- **SQLite (stdlib):** Nessun vettoriale, nessuna sicurezza multi-processo via protocollo di rete. Va per single-process ma fallisce su accesso condiviso.
- **PostgreSQL:** Eccessivo per uno strumento local-first. Dipendenza pesante, tradisce l'etica "installa e vai".
- **ChromaDB:** Usato nel NeuRAG v0.1.0. Abbandonato: daemon separato, interni opachi, nessun percorso fallback SQL.

**Scelta:** libSQL (fork Turso) con fallback a 3 livelli: Turso remoto → pyturso locale → SQLite.

**Perché:** libSQL legge file SQLite (zero migrazione da locale). Il fallback a 3 livelli funziona offline, in LAN o cloud. pyturso==0.6.1 è pinnato per compatibilità wheel su Python 3.10-3.14.

**Limiti accettati:** Le wheel pyturso sono specifiche per piattaforma (win_amd64, macosx, manylinux). L'indice vettoriale (`libsql_vector_idx`) non è ancora usato — il cosine full-scan va bene per vault sotto ~50K chunk.

---

## 2. Embeddings: ONNX + fastembed

**Problema:** Serve embedding vettoriali semantici per similarità keyword di Neuron e ricerca chunk di NeuRAG.

**Alternative scartate:**
- **API embeddings OpenAI:** Richiede chiave API, rete, costo. Tradisce il local-first.
- **Sentence-transformers (PyTorch):** ~2GB di dipendenza. Pesante per vettori 384-dim.
- **Solo TF-IDF:** Nessuna comprensione semantica. "Spring Boot" e "spring framework" sono estranei.

**Scelta:** ONNX Runtime + fastembed (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384-dim). Lazy-load al primo uso. Sia Neuron che NeuRAG usano di default questo stesso modello (NeuRAG legge `NS_EMBED_MODEL`), così i due store condividono un unico spazio vettoriale.

**Perché:** ONNX gira su CPU senza PyTorch. Modello ~130MB, scaricato una volta. fastembed lo wrappa pulitamente. TF-IDF resta fallback trasparente se ONNX non disponibile.

**Limiti accettati:** Modello multilingue (cambiato 2026-07-20 dal precedente `all-MiniLM-L6-v2` solo-inglese, così memoria IT + EN vivono in uno spazio confrontabile). Modello piccolo scambia accuratezza per velocità (accettabile per retrieval-augmented). Override via `NS_EMBED_MODEL` — cambiarlo invalida i vettori salvati (deve combaciare in lettura).

---

## 3. IPC: TCP length-prefixed

**Problema:** L'orchestrator Gray Matter deve chiamare gli strumenti di Neuron e NeuRAG senza bloccare il loop event principale.

**Alternative scartate:**
- **Import in-process:** `_call_server_async` re-importava il server a ogni chiamata (F0). Cold start 2-5s a chiamata.
- **HTTP/REST:** Eccessivo per stessa macchina. Aggiunge dipendenza framework.
- **Pipe subprocess:** Fragile su Windows, nessun multiplexing.

**Scelta:** Worker persistenti con TCP length-prefixed su localhost (porta 0 = auto-assegnazione).

**Perché:** I worker restano caldi (costo import pagato una volta). Il framing length-prefixed è banale da implementare. `_worker_for` fa spawn lazy + respawn alla morte.

**Limiti accettati:** Bug F1 (IPC leggeva assumeva un solo `recv` per la lunghezza) è stato fixato ma il pattern è fragile se messaggio > 64KB. Non è un problema per risposte tool.

---

## 4. Registrazione client: JSON filesystem

**Problema:** I client MCP (Claude Desktop, VS Code, Cursor, ecc.) devono sapere come raggiungere il gateway Gray Matter.

**Alternative scartate:**
- **Singolo path config:** Ogni client ha la sua posizione config (APPDATA, MSIX Packages, XDG, ecc.).
- **Symlink:** Rompono tra drive, problemi permessi su Windows.

**Scelta:** `clients.py` scansiona tutti i path config noti, scrive/aggiorna entry JSON, crea backup `.bak`. `register --gateway` espelle le entry vecchie neuron/neurag.

**Perché:** Funziona su tutte le piattaforme. `.bak` permette rollback. La scansione dei path noti copre Claude Desktop (APPDATA + MSIX), VS Code (settings.json), Cursor, OpenCode.

**Limiti accettati:** Nuovo client = nuovo path in `clients.py`. La scoperta del path MSIX è fragile (dipende dalla convenzione naming del package).

---

## 5. Pattern gateway: singolo server MCP che ripubblica tool

**Problema:** Gli assistenti AI si aspettano un singolo server MCP. Tre server separati significano tre connessioni, tre config, potenziali conflitti.

**Alternative scartate:**
- **Montare tutti e tre come sub-server nel config MCP:** Ogni client monta neuron, neurag, gray_matter separatamente. Verboso, fragile.
- **Proxy via HTTP:** Hop extra, perde il trasporto stdio.

**Scelta:** Gray Matter si lega una volta (stdio o TCP :9876), ripubblica tutti i 33 tool da Neuron + NeuRAG con i nomi originali.

**Perché:** Una sola connessione da gestire. I tool mantengono i nomi (nessuna confusione di aliasing). I processi worker gestiscono le sotto-chiamate internamente.

**Limiti accettati:** GM è un singolo punto di fallimento. Se GM muore, muoiono tutti i tool. Mitigato da singleton daemon + respawn.

---

## 6. Daemon: singleton via bind esclusivo

**Problema:** Lanci multipli (Claude Desktop chat + host, VS Code, Cowork) ognuno prova a avviare un daemon. Daemon duplicati causano lock file e race condition.

**Alternative scartate:**
- **File PID:** Può diventare stale. Non gestisce zombie.
- **Mutex (Windows):** Specifico per piattaforma, non aiuta su Linux/macOS.

**Scelta:** `SO_EXCLUSIVEADDRUSE` (Windows) / `SO_REUSEADDR` (POSIX) sulla porta 9876. Bind fallito = daemon esistente vivo, nuova istanza muore. Fallback a modalita stdio se bind fallito.

**Perché:** Singleton enforceato dal kernel. Nessuna gestione PID necessaria. Il daemon perdente muore immediatamente.

**Limiti accettati:** La porta 9876 potrebbe collidere con un altro servizio. La variabile d'ambiente `GM_PORT` è disponibile ma raramente necessaria.

---

## 7. Bridge hebbiani: apprendimento cross-store

**Problema:** NeuRAG conosce fatti, Neuron conosce contesto episodico. Nessun collegamento tra loro. "Questo chunk è correlato a quel concetto" non viene mai persistito.

**Alternative scartate:**
- **Comandi espliciti utente:** L'utente deve chiamare `bridge` manualmente ogni volta. Non scala.
- **Prossimità embedding:** Confronto cross-store cosine inaffidabile.

**Scelta:** Auto-learning bridge: quando `pulse` trova sia un hit contesto Neuron sia un hit knowledge NeuRAG sullo stesso topic, GM crea un link bridge con peso iniziale 1.0. Co-occorrenza ripetuta alza il peso (Hebbiano: "insieme fanno fuoco, insieme si connettono"). Bridge inattivi 7+ turn decadono.

**Perché:** Crescita organica del grafo conoscitivo senza intervento dell'utente. Il peso è una proxy per la rilevanza.

**Limiti accettati:** Qualità bridge dipende dall'overlap topic tra store. Bridge falsi possibili se il topic è troppo generico. Decay è basato su turn, non tempo.
