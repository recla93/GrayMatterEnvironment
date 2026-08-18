# INSTALL-AI — Gray Matter (suite completa: GM + Neuron + NeuRAG bundled)

> Istruzioni per un agente AI. Esegui in ordine, fermati al primo errore.
> Questo repo BUNDLE-A entrambi i tool come sottocartelle (`neuron/`,
> `neurag/`) — lo zip è autosufficiente. Modello: i client MCP parlano SOLO
> con `gray-matter` (gateway); i tool girano come worker gestiti.
> English version: `INSTALL-AI.md`.

## 1. Install (un passo — l'installer unificato fa tutto)

```bash
sh install.sh          # macOS/Linux   (Windows: install.cmd / install.ps1)
```

Cosa fa: trova/bootstrappa Python 3.10+ → un venv condiviso → installa GM +
Neuron + NeuRAG bundled (wheel pyturso da `neuron/vendor`, fastembed
best-effort) → `gray-matter install` (registra SOLO il gateway nei client MCP
con backup `.bak`, deploya gli hook di sessione, scrive il manifest) →
shortcut GUI sul Desktop → apre il control center.

## 2. Verifica

```bash
gray-matter doctor    # solo gray-matter nei client; warning se tier degradato
gray-matter ping
python -m pytest neuron/tests gray_matter/tests neurag/tests -q
```

Riavvia le app AI per caricare il gateway.

## 3. Rollback / rimozione

```bash
gray-matter uninstall --dry-run
gray-matter uninstall            # interattivo: chiede PRIMA di toccare la memoria
```

La memoria utente (grafi, knowledge.db, bridges) non viene MAI cancellata
senza consenso esplicito.
