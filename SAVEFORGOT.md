# SAVEFORGOT — il salvataggio che non scatta

**Osservato:** 4 settembre 2026, sessione Claude Code (corso Bash, contesto `studio/bash`).
**Stato:** diagnosi chiusa, rimedio **implementato e registrato** il 4 settembre 2026.
Resta fuori: il wiring nell'installer (`deploy_hooks.py`) e la verifica sul campo.

Handoff breve. Serve a riprendere il lavoro, non a documentare Gray Matter.

---

## Il fatto

In una sessione di ~15 turni, densa e piena di concetti nuovi, ho chiamato `store_turn`
**una volta sola** — al primo turno.

| | Previsto dal protocollo | Fatto |
|---|---|---|
| Salvataggi a fine lezione | 2 | 1 |
| Salvataggi a fine digressione | 5 | 0 |

Tutto il resto — un'intera lezione più cinque digressioni — è finito solo in un file markdown.
Nel grafo non è mai arrivato, finché l'utente non ha chiesto esplicitamente di controllare.

Recuperato a posteriori con due `store_turn`: +8 nodi, +8 link. Ma il recupero è avvenuto perché
**l'utente ha chiesto**, non perché il sistema abbia segnalato qualcosa.

---

## Il promemoria c'era già

Questo è il punto che rende il problema interessante: **non mancava l'avviso.**

Output reale di `pre_turn`, primo turno della sessione:

```
[neuron] ctx=studio/bash turn=8 nodes=35 links=27(active 27) db=turso-local
links:export-[s]->ambiente-processo | nodes:ambiente-processo(1),export(0)
🧠 export ⇢ ambiente-processo (recall)
→ then store_turn(topic, keywords, links).
→ useful? confirm(keywords=["ambiente-processo", "export"])
```

Penultima riga: `→ then store_turn(...)`.

E simmetricamente, ogni `store_turn` risponde con `→ next: pre_turn`.

Il ciclo è già cablato in entrambe le direzioni. È stato letto. È stato ignorato lo stesso.

---

## La diagnosi: un ciclo che non sa riavviarsi

```
pre_turn ──> "then store_turn" ──> store_turn ──> "next: pre_turn" ──> pre_turn ──> ...
```

Ogni promemoria vive **dentro la risposta dell'anello precedente**.

Conseguenza: se salti un anello, non ricevi il promemoria dell'anello successivo — perché quel
promemoria stava dentro la chiamata che hai saltato.

**Il ciclo non ha un innesco esterno. Una volta rotto, resta rotto per il resto della sessione.**

È esattamente ciò che è successo. Dal turno 2 in poi nessuna delle due estremità ha più parlato,
perché nessuna delle due è più stata chiamata.

### Perché la rottura è probabile proprio quando serve

Il ciclo si rompe quando la sessione si fa densa — molte digressioni, molti tool esterni, molto
contenuto. Cioè **quando ci sarebbe più da salvare**.

Nella sessione osservata, fra il primo `pre_turn` e la fine ci sono stati ~16 tool call di Bash
(esecuzioni in WSL per verificare gli esempi). Il ciclo Neuron è stato scavalcato da un altro
flusso di lavoro, non abbandonato per disinteresse.

---

## Cosa NON risolve

### Aggiungere `then save` alla coda di `pre_turn`

C'è già. Ed è nell'anello che viene saltato. Rafforzare il testo di un messaggio che non viene
consegnato non cambia niente.

Vale per qualunque aggancio alla risposta di un tool Neuron: **se il fallimento è la mancata
chiamata, nessuna modifica all'output di quella chiamata può ripararlo.**

### Scrivere la regola in un file di istruzioni

Già fatto in due punti: la skill `/lezione` (sezione *Quando salvare*) e l'handoff della sessione
precedente. Entrambi letti a inizio sessione, entrambi scivolati via.

Un file si legge una volta; il fallimento avviene 12 turni dopo.

### `auto()`

Va comunque invocato. Stesso problema, più il fatto che il playbook stesso lo sconsiglia
(«imprecisi, preferisci store_turn»).

---

## Il vincolo che decide il design

**Un hook di Claude Code non può chiamare un tool MCP.**

Gli hook sono comandi shell: ricevono JSON su stdin, stampano su stdout, e su alcuni eventi
(`SessionStart`, `UserPromptSubmit`) quello stdout entra nel contesto del modello.

Quindi un hook può **dire di salvare**. Non può salvare.

> Alternativa scartata: scrivere direttamente nel DB Turso locale bypassando l'MCP. Richiederebbe
> di generare gli embedding a 384 dimensioni e di scegliere keyword e link fuori dal modello.
> Sarebbe un secondo Neuron, non un hook.

---

## La proposta

Hook su **`UserPromptSubmit`**, con contatore su file.

| | |
|---|---|
| Trigger | ogni messaggio dell'utente — **indipendente dall'arbitrio del modello** |
| Azione | conta; ogni N (proposto: 8) inietta una riga sola |
| Testo | «N turni dall'ultimo `store_turn` — salva se c'è qualcosa di nuovo» |
| Reset | quando il salvataggio avviene |
| Stato | un file contatore. Nessun accesso al DB di Neuron |

**Perché `UserPromptSubmit` e non la coda di `pre_turn`:** è l'unico canale che scatta *a
prescindere* da cosa il modello decide di chiamare. Rompe la circolarità.

**Perché iniettato e non scritto in un file di regole:** arriva in mezzo al lavoro, non a inizio
sessione. La sessione osservata dimostra che il secondo canale non regge.

### Seconda rete: `PreCompact`

Hook aggiuntivo sull'evento di compattazione del contesto. Raro, tardivo, ma è il momento in cui la
perdita è reale e imminente.

Da solo non basta: in una sessione che finisce prima della compattazione non scatta mai.

---

## Il reset del contatore: risolto togliendo il contatore

Le tre strade proposte partivano tutte dal presupposto che servisse un file contatore da azzerare.
Non serve: **il transcript e' gia' il contatore.**

Claude Code passa all'hook `transcript_path` sullo stdin. E' il JSONL della sessione, e contiene
sia i prompt dell'utente sia le chiamate a tool. Basta contare i prompt veri dopo l'ultimo
`store_turn`.

| | |
|---|---|
| Stato su disco | nessuno |
| Da sincronizzare | niente |
| Reset | il salvataggio stesso, che e' gia' scritto nel log |

L'hook non vede le chiamate MCP mentre avvengono, ma **ne legge il registro**. Era il punto cieco
apparente, e non c'era.

### Cosa NON conta come turno dell'utente

Tre righe hanno `role: user` senza essere un prompt. In una sessione densa sono la maggioranza:

- **tool result** — la risposta di un tool torna come messaggio utente;
- **sidechain** — il prompt di un subagente;
- **meta** — l'output di un hook reiniettato in contesto, incluso quello di questo hook.

### Parsing strutturale, non substring

Prima stesura: match testuale su `"type":"user"` e `"name":"...store_turn"`. Funzionava sul
transcript vero (JSONL compatto) e falliva su ogni fixture, perche' gli spazi dopo i due punti non
sono parte di nessun contratto.

Difetto peggiore: un `store_turn` cercato come sottostringa viene azzerato **dall'utente che scrive
la parola**. Le sessioni che parlano del loop di memoria sono esattamente quelle che non devono
zittirlo. `json.loads` riga per riga costa millisecondi su migliaia di righe.

## Infrastruttura già presente

```
~/.claude/hooks/neuron_sessionstart_hook.py     hook SessionStart, di Gray Matter
~/.claude/settings.json                          registra solo SessionStart
```

L'hook esistente usa già il pattern giusto (stdout → contesto) e gestisce la deduplica fra canali
multipli con un claim atomico su marker di sessione. Il nuovo hook può riusarne la struttura.

---

## Fatto

- [x] Hook `UserPromptSubmit` — `neuron/src/neuron/clients/claude-code-hook/neuron_reminder_hook.py`,
      deployato in `~/.claude/hooks/`. Riusa `installed_slugs()` / `owner()` del SessionStart, cosi'
      il prefisso nel messaggio e' quello che esiste davvero in quella sessione.
- [x] Reset senza contatore: il transcript e' la fonte unica (vedi sopra).
- [x] Registrato in `settings.json` su `UserPromptSubmit` **e** `PreCompact`, con lo stesso
      interprete di `SessionStart`.
- [x] `gray_matter/tests/test_reminder.py` — 11 test: cosa conta, cosa azzera, cosa non azzera.
      Suite intera verde (567 passed).

### Verifica eseguita

Pipe-test con l'interprete registrato, payload sintetico:

| evento | prompt non salvati | stdout |
|---|---|---|
| `UserPromptSubmit` | 8 | il promemoria |
| `PreCompact` | 8 | il promemoria |
| `UserPromptSubmit` | 7 | vuoto |

Replay sui transcript reali gia' su disco:

| sessione | prompt | `store_turn` | promemoria che sarebbero scattati |
|---|---|---|---|
| `d24e3174` | 61 | 5 | 5 |
| `78673d0c` | 46 | 7 | 3 |
| `7756c7d1` | 13 | 0 | 1 |
| `ee122493` | 9 | 2 | **0** |

L'ultima riga e' la controprova che conta: quando il loop gira, l'hook tace.

## Resta da fare

- [ ] Wiring nell'installer. `deploy_hooks.py` deploya *un* file su *un* evento: registrare anche
      questo richiede di generalizzarlo, e vanno allineate le quattro copie byte-identiche
      (`neuron/src/neuron/clients/`, `neurag/clients/`, piu' le copie Cowork). Finche' non e' fatto,
      l'hook vive solo su questa macchina.
- [ ] Verifica sul campo: una sessione lunga vera, e contare i `store_turn` effettivi contro quelli
      attesi.

---

## Nota sulla misura

Lo `status` di Neuron riporta un contatore di sessione:

```
Loop (this session): pre_turn 0 | store_turn 0 | other tools 1
```

Nella sessione osservata mostrava `0 | 0` **pur essendo stati fatti** un `pre_turn` e uno
`store_turn`: il server MCP si era disconnesso e riconnesso a metà sessione, e il contatore era
ripartito.

Da tenere presente se lo si usa come metrica: **non sopravvive a un riavvio del server.**
