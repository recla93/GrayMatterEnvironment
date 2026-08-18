# Processo

> Come il Gray Matter Environment viene costruito, da chi, e le lezioni imparate.
> Un compendio del processo di lavoro — non un documento di project management.

---

## Il team: Claudio + Fable (multi-AI)

Il progetto è costruito da un umano (Claudio) che lavora con sessioni AI multiple (Fable e altre). Questa non è una metafora — è il processo di sviluppo reale.

**Ruoli:**
- **Claudio:** Decisioni prodotto, revisione architettura, testing, bug report, conoscenza del dominio. "L'umano nel loop."
- **Fable (e altre AI):** Implementazione codice, debugging, documentazione, refactoring. "Le mani."

**Come funziona:** Claudio descrive un problema o una feature. Fable la implementa. Claudio revisiona, testa localmente, riporta cosa si è rotto. Fable fixa. Il ciclo si ripete. Le decisioni si fanno in conversazione, non in ticket.

**Perché conta per le doc:** Ogni documento in questa suite è stato verificato contro il codice sorgente, non copiato da vecchie doc. La regola DOCS-GUIDELINES.md "verità dal codice" esiste perché le sessioni AI possono hallucinare — controllare il codice è l'unico modo per restare onesti.

---

## Il compendium come cervello condiviso

`GRAY-MATTER-COMPENDIUM.md` è la singola fonte di verità per lo stato del progetto. Unisce e deduplica quello che prima era sparsato tra `GMFixAndIdeas`, `HANDOFF-07-16/17/18`, `STATO-E-PIANO`, e `PIANO-EVOLUZIONE`.

**Perché esiste:** Sessioni AI multiple devono sapere le stesse cose. Senza compendium, ogni sessione parte fredda e ripete investigazioni. Il compendium è il "cervello condiviso" — persiste tra le sessioni.

**Come viene mantenuto:** Dopo ogni sessione di lavoro, il compendium viene aggiornato con cosa è stato fatto, cosa si è rotto, cosa è stato fixato, e cosa c'è dopo. È pesante in append (nuove sezioni per nuovo lavoro) e pesante in dedup (merging entry sovrapposte).

**Regola:** Il compendium non è mai stale di più di una sessione. Se lo è, qualcuno non lo ha aggiornato.

---

## La lezione dell'audit Laguna

A un certo punto, il progetto ha subito un'audit esterno (Laguna). Il risultato è stato umiliante: molte cose che il team pensava solide si sono rivelate fragili.

**Cosa ha trovato l'audit:**
- Drift versione tra file (RELEASE-CHECKLIST, README, pyproject dicevano tutte cose diverse)
- Assunzioni nel codice non validate (es. parsing `_first_conchet` dipendente dal formato output di Neuron)
- Edge case mancanti (F3: reset senza conferma, F4: nessun dry-run su prune)

**Cosa è cambiato:** Il team ha adottato la disciplina "verifica tutto contro il codice". Le regole DOCS-GUIDELINES.md sono una diretta conseguenza: "Non fidarti mai di un doc non verificato contro il sorgente corrente."

**Lezione:** Gli audit esterni non sono avversari. Sono il sistema che se stesso controlla. Il compendium ora include un audit trail.

---

## Il debugging L2: la race del daemon

Il bug più istruttivo del progetto è stato L2: `store_turn → open: NotFound`.

**Sintomo:** `store_turn` falliva intermittente con `NotFound`. `pre_turn` funzionava sempre. Test one-shot passavano sempre. Falliva solo nel daemon vivo.

**Timeline:**
1. Primo osservato: 2026-07-19. Intermittente. Mai riproducibile in test isolati.
2. Ipotesi 1: env/cwd del daemon senza .env/token Turso. → Scartata: pre_turn funziona.
3. Ipotesi 2: re-import per call (F0). → Fixato da F0 ma L2 persisteva.
4. Ipotesi 3: `_graphs.clear()` nel worker + accesso concorrente allo stesso file WAL. → Confermato reproducing nel daemon vivo, mai nei test.
5. Causa radice: processi GM multipli (Desktop chat + host, Cowork) spawna worker pyturso multipli sullo stesso `graph_*.db`. Il worker fa `_graphs.clear()` + reload a ogni call → race tra open e checkpoint WAL.
6. Fix in corso: respawn worker on failure, o rimozione `_graphs.clear()`.

**Lezione:** Le race condition in SQLite/WAL sono invisibili nei test single-process. Il bug appare solo quando processi multipli condividono lo stesso file DB. Il singleton daemon (Era 2) mitiga ma non elimina — Claude Desktop spawn 2 client MCP da 1 entry.

---

## Il rito sandbox → locale

Prima che ogni cambio venga commesso, deve passare attraverso due ambienti:

1. **Sandbox (cloud):** L'AI scrive codice, lancia `pytest` nella sandbox cloud. Test verdi → codice plausibile.
2. **Locale (Claude Desktop):** Claudio lancia gli stessi test localmente. Test verdi → codice reale.

**Perché entrambi:** I test sandbox sono isolati. I test locali girano contro il daemon reale, il DB reale, l'IPC reale. Molti bug (L2, F19, F20) sono apparsi solo localmente perché dipendono da stato runtime che la sandbox non replica.

**Regola:** Sandbox verde ≠ fatto. Locale verde = fatto. Entrambi rossi → investiga localmente.

---

## La disciplina ponytail

Il progetto segue ponytail: "il percorso più corto verso il done è il percorso giusto."

**Cosa significa nella pratica:**
- Nessuna interfaccia con una implementazione
- Nessuna factory per un prodotto
- Nessuna config per valori che non cambiano mai
- Nessun boilerplate "per dopo"
- Una riga prima di cinquanta
- Eliminazione sopra aggiunta

**Quando viene violata:** Calibrazione hardware (l'esempio del PCA9685 dalla skill ponytail), validazione input ai confini di sicurezza, misure di sicurezza, qualsiasi cosa esplicitamente richiesta da Claudio.

**La convenzione commento:** `ponytail: this exists` marca semplificazioni deliberate. Esempio: `# ponytail: global lock, per-account locks if throughput matters`.

---

## Design anchored allo schema

Ogni feature importante parte dal database schema, non dal codice. Lo schema è il contratto.

**Come funziona:**
1. Progettare le tabelle in `models.py` (o `db.py` per NeuRAG)
2. Scrivere DDL con `CREATE TABLE IF NOT EXISTS`
3. Scrivere migration `ALTER TABLE` per tabelle esistenti
4. Poi scrivere il codice che usa lo schema

**Perché:** Lo schema è verificabile. Puoi fare `SELECT` e vedere cosa c'è. Il codice può essere sbagliato in modi sottili; i dati o ci sono o non ci sono.

**Esempio:** La colonna `Node.trust` è stata progettata come `trust REAL DEFAULT 0` con delta atomico `MAX(0, trust + ?)` prima che qualsiasi logica trust fosse scritta. Lo schema ha forzato l'implementazione ad essere corretta.

---

## Neuron che si mangia da solo

Neuron usa il suo stesso concept graph per tracciare la conoscenza del progetto. Il compendium referenzia nodi Neuron. Le doc referenziano tool Neuron. Il progetto È la cosa che costruisce.

**Perché conta:** Se Neuron non riesce a tracciare il suo stesso sviluppo, non riesce a tracciare quello di nessun altro. Ogni bug in Neuron viene trovato prima dal team che lo usa.

**Il feedback loop:** Claudio usa Neuron (via GM) durante lo sviluppo → trova problemi → fixa Neuron → commette → lo usa di nuovo. Lo strumento migliora siendo usato.
