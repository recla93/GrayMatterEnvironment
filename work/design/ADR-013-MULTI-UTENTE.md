# ADR-013: Multi-utente concorrente — daemon locale e hub

> Status: **Accepted** — 2026-10-25
> Relates to: ADR-011 (GM come container), ADR-012 (sicurezza: fase 2 è l'identità locale, questa è
> quella verso l'hub), `neuron/docs/TEAM.md` (il modello di squadra che questo ADR sostituisce)

> [!abstract] In sintesi
> - **Cos'è.** Più persone usano la suite nello stesso momento. Ognuno ha la sua memoria privata e
>   condivide solo quello che sceglie, con permessi per spazio e un registro di chi fa cosa.
> - **Come funziona.** Ogni persona tiene il suo daemon locale, come oggi: la memoria personale non
>   lascia mai il portatile. Le parti condivise vivono su un **hub**, l'unico che possiede le
>   credenziali del database condiviso e che decide chi legge e chi scrive.
> - **A cosa serve.** Il modello di oggi regge sei persone fidate, e chiunque abbia il token del
>   database legge e cancella tutto. Un'azienda ha bisogno di identità, permessi, isolamento e audit,
>   senza perdere la velocità del contesto locale a ogni turno.

> [!note] I riferimenti al codice si riferiscono al commit `0d2c452`.

---

## 1. Contesto

### 1.1 Il modello di oggi

`neuron/docs/TEAM.md` descrive la squadra così: ogni persona punta il suo Neuron allo stesso database
Turso Cloud. Verificato nel codice:

| Aspetto | Stato | Dove |
|---|---|---|
| Concorrenza di scrittura | **buona**: salienza per incremento atomico, pesi dei link solo in salita, nessuna cancellazione in blocco nei salvataggi normali | `TEAM.md`, `models.py` `_save_delta` |
| Dimensione | pensato per **sei persone fidate** al massimo | `TEAM.md` |
| Identità | **nessuna**: il token Turso dà accesso completo a tutto | `TEAM.md`, sezione Security |
| Separazione | i contesti sono una colonna, non un confine: chiunque legge e scrive ogni contesto | `models.py:1386` |
| Operazioni distruttive | un `merge` o un `reset` vale per tutti | `TEAM.md` |
| Chi ha scritto cosa | nodi, link ed episodi **non hanno autore**; solo `refs.by`, e solo se è impostata `NEURON_USER` | `models.py:1386`, `server.py:1439` |
| Credenziali | un token del database su ogni portatile, nel `.env` | `TEAM.md` |

### 1.2 Cosa serve a un'azienda

1. **Identità**: ogni chiamata sa a quale persona appartiene.
2. **Permessi**: chi legge, chi scrive, chi può distruggere, per ogni spazio.
3. **Isolamento**: la memoria personale di uno non è leggibile da un altro.
4. **Audit**: un registro di chi ha fatto cosa, dove e quando.
5. **Nessuna credenziale del database sui portatili**: un portatile perso non apre il patrimonio comune.

E non deve costare il punto di forza della suite: il contesto a ogni turno, veloce e gratis.

## 2. Decisioni

| # | Decisione | Perché |
|---|---|---|
| **D1** | **Architettura ibrida**: daemon locale per ogni persona, più un hub per le parti condivise | `pre_turn` gira a ogni turno: deve restare locale, in millisecondi e senza rete. Il patrimonio comune (documenti, decisioni di team) va indicizzato una volta per tutti: centrale |
| **D2** | **Memoria personale solo locale**: lo spazio personale non esiste sull'hub | È la storia più semplice da difendere con il GDPR e con chi valuta la sicurezza: un dato che non lascia il portatile non può trapelare dall'hub. La condivisione passa solo dalla promozione esplicita (3.6) |
| **D3** | **Chiavi per utente rilasciate dall'hub**; login aziendale (OIDC) in una fase successiva | Si dimostra subito, senza dipendere dall'IdP del cliente. Il login aziendale si aggiunge sopra senza cambiare il resto (3.4) |

## 3. Architettura

### 3.1 I pezzi

```
 portatile di Ada                         portatile di Bruno
 ┌─────────────────────────┐              ┌─────────────────────────┐
 │ client IA (Claude, …)   │              │ client IA               │
 │   │ MCP stdio           │              │   │                     │
 │ daemon GM locale        │              │ daemon GM locale        │
 │  · memoria personale    │              │  · memoria personale    │
 │  · identità locale      │              │                         │
 │    (ADR-012 fase 2)     │              │                         │
 └───────────┬─────────────┘              └───────────┬─────────────┘
             │ HTTPS + token d'accesso dell'hub        │
             └──────────────────┬──────────────────────┘
                     ┌──────────┴──────────┐
                     │ hub                 │
                     │  · identità e chiavi│
                     │  · permessi         │
                     │  · audit            │
                     │  · lease            │
                     └──────────┬──────────┘
                                │ unico detentore delle credenziali
                     ┌──────────┴──────────┐
                     │ store condiviso     │
                     │ (Turso / libSQL)    │
                     └─────────────────────┘
```

| Pezzo | Cosa fa | Cosa cambia rispetto a oggi |
|---|---|---|
| **Daemon locale** | tutto quello che fa oggi, sulla memoria personale | parla con l'hub per gli spazi condivisi; non ha più credenziali del database condiviso |
| **Hub** | servizio HTTP: autentica, autorizza, registra, serializza le operazioni distruttive | nuovo. È Gray Matter in modalità server, nel senso dell'ADR-011: ospita i servizi e possiede le loro risorse |
| **Store condiviso** | i dati degli spazi `team:*` e `azienda` | raggiungibile solo dall'hub |

### 3.2 Gli spazi

Lo **spazio** sostituisce il contesto come confine. Il contesto resta, come struttura **dentro** uno
spazio.

| Spazio | Dove vive | Chi lo vede |
|---|---|---|
| `personale:<utente>` | **solo** sul portatile | il proprietario |
| `team:<nome>` | hub | i membri del team, secondo il ruolo |
| `azienda` | hub | tutti gli utenti dell'hub, di solito in sola lettura |

### 3.3 Il flusso di una chiamata

**Lettura (`pre_turn`, `pulse`, `knowledge_query`).**
1. Il daemon locale interroga la memoria personale, come oggi.
2. In parallelo interroga l'hub per gli spazi condivisi che l'utente vede, con un **budget di tempo**
   (indicativo: 300 ms).
3. Se l'hub non risponde in tempo o non è raggiungibile, la risposta parte con la sola parte locale e
   lo dice in una riga. Il lavoro non si ferma per la rete.
4. Il contenuto condiviso arriva marcato come dato, con lo spazio di provenienza (ADR-012 F6).

**Scrittura (`store_turn`).** Va **sempre** nello spazio personale, in locale. Nessuna scrittura
implicita verso l'hub.

**Condivisione.** Solo con la promozione esplicita (3.6).

### 3.4 Identità verso l'hub

È un dominio di fiducia diverso dall'identità locale dell'ADR-012 fase 2: chiave diversa, emittente
diverso. Il JWT locale non lascia mai la macchina.

| Pezzo | Scelta | Perché |
|---|---|---|
| **Chiave d'utente** | rilasciata dall'amministratore dell'hub: `gmk_<id>_<segreto>`, 32 byte casuali | revocabile una per una; l'`id` permette di trovarla senza confrontare tutte |
| **Sull'hub** | conservata solo come hash SHA-256 del segreto | un segreto ad alta entropia non ha bisogno di un hash lento; un furto del database non dà chiavi valide |
| **Sul portatile** | nel portachiavi del sistema: Credential Manager (DPAPI) su Windows, Keychain su macOS, Secret Service su Linux | non in un `.env` leggibile in chiaro |
| **Token d'accesso** | la chiave si scambia con un token dell'hub a 15 minuti, con `sub`, gli spazi e i ruoli | la chiave viaggia una volta per sessione, non a ogni chiamata; i permessi letti dall'hub, non dal client |
| **Revoca** | chiave disattivata → nessun token nuovo; i token già emessi scadono entro 15 minuti | revoca effettiva in un tempo limitato e noto |
| **Login aziendale** (fase 4d) | l'hub accetta in alternativa un ID token OIDC (Entra ID, Okta), con device code flow per gli strumenti senza browser | l'hub emette lo stesso token d'accesso: daemon, permessi e audit non cambiano |

### 3.5 Permessi

Decisi e applicati **solo sull'hub**. Il client non è fidato: un daemon modificato non ottiene niente
che l'hub non gli conceda.

| Operazione | lettore | scrittore | manutentore | amministratore hub |
|---|---|---|---|---|
| leggere lo spazio (contesto, ricerca) | sì | sì | sì | sì |
| promuovere concetti nello spazio | | sì | sì | sì |
| confermare o smentire (`confirm`, `dismiss`) | | sì | sì | sì |
| indicizzare documenti nello spazio | | sì | sì | sì |
| `merge`, `consolidate`, potature | | | sì, con lease | sì |
| `reset` dello spazio | | | | sì |
| gestire membri e ruoli dello spazio | | | sì | sì |
| creare spazi, rilasciare e revocare chiavi | | | | sì |

### 3.6 Promozione

Il solo passaggio dal personale al condiviso.

1. L'utente chiede esplicitamente: `promote <concetti> --to team:<nome>`.
2. Il daemon mostra **cosa** partirà: nodi, link, episodi. L'utente conferma.
3. L'hub verifica il ruolo, scrive con `owner` = l'utente, e registra l'evento nell'audit.

È lo stesso schema del `promote` che oggi porta i concetti da Neuron a NeuRAG, con uno spazio come
destinazione.

### 3.7 Concorrenza

| Tipo di dato | Regola | Stato |
|---|---|---|
| salienza, conteggi | incremento atomico relativo | **c'è già** |
| peso dei link | solo in salita | **c'è già** |
| salvataggio normale | solo il proprio delta, nessuna cancellazione in blocco | **c'è già** |
| campi descrittivi (`topic`, `domain`) | vince l'ultimo che scrive, con `owner` e ora registrati | accettabile: il valore precedente resta nell'audit |
| episodi | uno per `(spazio, keyword, owner, turno)`: nessuno sovrascrive quelli degli altri | da aggiungere `owner` alla chiave |
| `merge`, `consolidate`, potature | **lease** per spazio: un solo manutentore alla volta, scadenza automatica | nuovo |
| ripetizione di una richiesta | ogni scrittura porta un id di richiesta: rifatta, non duplica | nuovo |

### 3.8 Audit

Una tabella in sola aggiunta sull'hub: ora, `sub`, spazio, azione, oggetto, id di richiesta, esito.

- Registra **il fatto**, non il contenuto. Il testo di un episodio non finisce nell'audit.
- Le letture si registrano in forma aggregata (chi, spazio, quante), per non far crescere il registro
  a ogni turno.
- La conservazione è una politica dell'azienda, configurabile.

### 3.9 Un solo modello di embedding per spazio

Vettori di modelli diversi non si confrontano (`neurag/settings.py`, `embed_model`). L'hub dichiara il
modello di ogni spazio. Un daemon con un modello diverso non manda vettori: manda il testo, e l'hub
calcola. Così il vault aziendale si indicizza **una volta**, con un modello, per tutti.

## 4. Modifiche ai dati

| Store | Modifica | Migrazione |
|---|---|---|
| Neuron (`nodes`, `links`, `episodes`, `refs`, `node_vectors`) | colonne `space` e `owner`; `owner` nella chiave degli episodi | ogni riga esistente diventa `personale:<identità locale>`, `owner` = identità locale (`ipcauth.own_identity()`) |
| NeuRAG (`nodes`, `chunks`) | `space` sul nodo; i chunk lo ereditano dal nodo | tutto `personale:<identità locale>` |
| Hub (nuovo) | `users`, `api_keys` (hash), `spaces`, `members`, `leases`, `audit` | nessuna: nasce vuoto |

`context` resta com'è, come struttura dentro lo spazio.

## 5. Piano

| Fase | Contenuto | Si dimostra con |
|---|---|---|
| **4a** | `space` e `owner` negli store locali, con migrazione | test di migrazione su una copia di un grafo reale; nessun cambiamento visibile per chi lavora da solo |
| **4b** | hub minimo: vault NeuRAG `azienda` servito dall'hub, chiavi per utente, token d'accesso, audit | due utenti interrogano lo stesso vault; un terzo senza chiave riceve 401; l'audit registra tutti e tre |
| **4c** | spazi Neuron `team:*`: permessi, promozione, lease | due scrittori concorrenti senza perdite; un lettore che tenta un `merge` riceve 403; due `merge` insieme: uno solo ottiene il lease |
| **4d** | login aziendale OIDC; chiavi nel portachiavi del sistema | login con un IdP di prova; nessun segreto nei file di configurazione |
| **4e** | limiti di carico, quote, monitoraggio, backup dello store condiviso | prove di carico con il numero di utenti dichiarato |

La **4b** è la più presentabile: i documenti aziendali indicizzati una volta, interrogabili da ogni IA
del team, con permessi e audit.

## 6. Cosa non copre

- **Il portatile compromesso**: un malware che gira come l'utente legge la memoria personale e usa la
  sua chiave dell'hub entro i suoi permessi. La revoca della chiave chiude l'accesso all'hub entro la
  scadenza dei token. La cifratura a riposo (ADR-012 fase 3) alza il costo per i dati locali.
- **L'amministratore dell'hub** vede gli spazi condivisi. È un ruolo di fiducia, e le sue azioni
  finiscono nell'audit come quelle degli altri.
- **La memoria personale di chi lascia l'azienda** resta sul suo portatile. Quello che aveva promosso
  resta negli spazi condivisi, con il suo `owner`.

## 7. Alternative scartate

| Alternativa | Perché no |
|---|---|
| **Tutto centrale** (ogni client MCP sul server) | un giro di rete a ogni turno, nessun lavoro senza rete, memoria personale sul server: contraddice D1 e D2 |
| **Token del database per persona** (il modello di oggi, esteso) | il database non conosce spazi né ruoli: ogni token apre tutto |
| **Permessi a livello di riga in Postgres** | un secondo motore da mantenere accanto a Turso, per ottenere quello che l'hub fa già sapendo chi chiama |
| **Sincronizzazione peer-to-peer** (CRDT fra portatili) | conflitti e revoche molto più difficili da garantire e da spiegare a chi valuta la sicurezza |

## 8. Domande aperte

- **Dove gira l'hub**: server dell'azienda o cloud. Il design non dipende dalla scelta; cambiano il
  rilascio e il monitoraggio.
- **Dimensioni**: il numero di utenti dichiarato decide i limiti della fase 4e.
- **Quale IdP** per la fase 4d.
