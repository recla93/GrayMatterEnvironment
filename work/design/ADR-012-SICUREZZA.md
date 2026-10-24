# ADR-012: Sicurezza — modello di minaccia e identità interna

> Status: **Accepted** — 2026-10-24. Fase 1 implementata lo stesso giorno (sezione 7.1), fase 2 il
> 2026-10-25 (sezione 7.2).
> Relates to: ADR-011 (GM come container: permessi e risorse iniettati), docs/TEAM.md (store condiviso)

> [!abstract] In sintesi
> - **Cos'è.** Un modello di minaccia della suite e un sistema di **identità interna**: chi parla con
>   il daemon deve dimostrare chi è, con una chiave che vive solo nella RAM del daemon.
> - **Come funziona.** All'avvio il daemon genera una chiave di firma casuale. Un client si presenta su
>   un canale protetto dal sistema operativo, il daemon verifica il suo utente e gli rilascia un token
>   firmato e a scadenza breve. Alla chiusura la chiave muore col processo.
> - **A cosa serve.** Oggi tre ingressi accettano comandi da chi non dovrebbe darne (sezione 3). E la
>   stessa identità è la base del multi-utente concorrente: ogni chiamata sa a quale utente appartiene.

> [!note] I numeri di riga si riferiscono al commit `16a2c3a`.

---

## 1. Contesto

La suite va presentata a un'azienda. Il requisito è «impenetrabile».

Nessun sistema lo è. Il requisito si traduce in tre impegni verificabili:

1. Ogni ingresso è **autenticato**, tranne quelli che non espongono niente.
2. Ogni minaccia ha una **difesa con un test** che la dimostra.
3. Quello che la suite **non** difende è scritto, con il motivo (sezione 6).

## 2. Modello di minaccia

### 2.1 Cosa proteggiamo

| Bene | Dove sta | Perché conta |
|---|---|---|
| La memoria (grafi Neuron) | `%LOCALAPPDATA%\GrayMatterEnvironment\neuron\graphs` | decisioni, file, persone: il contesto di lavoro di un utente |
| La conoscenza (vault NeuRAG) | `...\neurag\knowledge.db` | documenti indicizzati, anche riservati |
| Le credenziali cloud | `...\graymatter\.env` (Turso, Cloudflare) | aprono lo store condiviso del team |
| La capacità di eseguire | daemon, GUI, bridge | `uninstall --purge-data`, ingest di file, scrittura in memoria |
| Il contesto che arriva all'IA | uscita di `pre_turn`, `pulse` | se è falso o ostile, l'IA agisce su dati falsi |

### 2.2 Da chi

| Attore | Come arriva | Esempio |
|---|---|---|
| **A1 — Sito web** nel browser dell'utente | richieste a `127.0.0.1`, DNS rebinding | una pagina qualunque aperta mentre la GUI è accesa |
| **A2 — Altro utente locale** | loopback, porte fisse | macchina condivisa, server di sviluppo |
| **A3 — Rete** (LAN o internet) | bridge HTTP con `--bind all` o `--tunnel` | chiunque abbia l'URL del tunnel |
| **A4 — Contenuto ostile** | prompt injection in un documento o in una pagina | l'IA legge un testo che le chiede di indicizzare `C:\Users\...\.aws` |
| **A5 — Catena di fornitura** | codice scaricato all'installazione | un commit malevolo sul branch `main` di un repo fratello |
| A6 — Malware con lo **stesso** utente | lettura diretta dei file | fuori portata del token (sezione 6) |

## 3. Superficie d'attacco oggi

Verificato il 2026-10-24, sulla macchina di sviluppo e sul codice di `16a2c3a`.

| # | Gravità | Problema | Dove | Attore | Verifica |
|---|---|---|---|---|---|
| **F1** | **critica** | Il bridge di GM è un `mcp-proxy` **senza autenticazione**. Con `--bind all` è in rete, con `--tunnel` su internet, con tutti i tool, anche distruttivi | `gray_matter/bridge.py:171`, `:186` | A3 | lettura del codice: nessun controllo, nessun rifiuto. Neuron e NeuRAG invece chiedono il Bearer e rifiutano il bind aperto senza (`neuron/src/neuron/http_transport.py`) |
| **F2** | **alta** | La GUI consegna il token a **qualunque Host**: un sito che fa DNS rebinding legge la pagina, prende il token e comanda `POST /api/run` | `gray_matter/webgui.py:1182` | A1 | `curl -H "Host: attacker.example:<porta>"` → la pagina torna **con il token** |
| **F3** | **alta** | `knowledge_ingest` e `knowledge_index` accettano **qualunque percorso**; `knowledge_index` restituisce il testo intero dei file | `neurag/server.py:485`, `:507` | A3, A4 | lettura del codice: solo `path.exists()` |
| **F4** | media | IPC del daemon: porta fissa 9876, e il client manda il token a **chiunque ascolti** lì. Il token è permanente su disco | `gray_matter/server.py:1501`, `:1560`; `gray_matter/cli.py:77-110` | A2 | un altro utente che occupa la 9876 prima del daemon raccoglie il token e può servire contesto falso |
| **F5** | media | L'installer scarica i pacchetti fratelli dalla **punta di `main`**, senza tag né hash | `gray_matter/install.ps1:772`, `:789` | A5 | lettura del codice |
| **F6** | media | **Prompt injection persistente**: un testo ostile salvato in memoria torna in ogni sessione dentro il contesto, con la stessa autorità del resto | `neuron/src/neuron/server.py:2291` (`facts:`) | A4 | per costruzione: nessuna marcatura di provenienza |
| F7 | bassa | Dati a riposo in chiaro (SQLite) | store sotto `%LOCALAPPDATA%` | A6 | solo l'ACL del sistema operativo |

**Cosa è già fatto bene**, verificato:

- nessun segreto nel repo: niente `.env` tracciati, nessun token nel codice;
- il file `ipc-token` è leggibile solo dall'utente (più SYSTEM e Administrators);
- la GUI respinge una `POST` senza token (**403**) e confronta a tempo costante;
- il runner della GUI esegue solo comandi del catalogo, con argomenti in lista, senza shell;
- i bridge HTTP di Neuron e NeuRAG: Bearer obbligatorio fuori da loopback, rifiuto all'avvio.

## 4. Decisione: identità interna con chiave effimera

### 4.1 La proposta di partenza

> Un sistema di JWT interno che si crea all'avvio e scambia internamente la chiave all'handshake, e la
> scarica alla chiusura del processo cancellandola. Le ENV non si committano. Ogni chiave per utente è
> univoca, per restare fedeli alla scelta del multi-uso.

**Cosa regge, e resta nel design:**

- chiave **generata all'avvio**, mai su disco, distrutta alla chiusura;
- **una chiave per utente**: niente segreto condiviso fra persone;
- token in **formato JWT**: standard, leggibile dagli strumenti di audit di un'azienda;
- le variabili d'ambiente fuori dal repo.

**Due punti da correggere:**

1. **La chiave di firma non si scambia mai.** Se viaggia sul canale, chi intercetta il canale firma
   token validi. Il daemon la tiene per sé e scambia solo **token firmati** con quella chiave.
2. **Serve un primo contatto fidato.** «Dammi un token» deve arrivare da qualcuno che ha diritto di
   chiederlo. Su una macchina, l'unica identità che non si falsifica è l'**utente del sistema
   operativo**. Senza questo, il JWT sposta il problema: il primo che chiede riceve un token.

### 4.2 Il design

| Pezzo | Scelta | Perché |
|---|---|---|
| **Chiave** | 32 byte da `secrets.token_bytes`, generati all'avvio del daemon, solo in RAM | un crash non lascia niente; ogni avvio è una rotazione |
| **Canale di primo contatto** | Windows: named pipe per utente, con DACL che ammette solo il SID dell'utente e `FILE_FLAG_FIRST_PIPE_INSTANCE`. POSIX: socket Unix in una cartella `0700`, identità con `SO_PEERCRED` | l'identità la garantisce il kernel, non un file o una porta |
| **Anti-sostituzione** | il client verifica che il **server** della pipe giri con il suo stesso SID (`GetNamedPipeServerProcessId` → token del processo) prima di mandare qualsiasi cosa | chiude F4: un altro utente non può fingersi il daemon |
| **Token** | JWT HS256: `sub` (SID o uid), `sid` (sessione), `aud` = `gm`, `scope`, `iat`, `exp` = 15 minuti, rinnovo prima della scadenza | l'identità viaggia con ogni chiamata: base del multi-utente |
| **Verifica** | algoritmo fisso HS256 (un header diverso è un rifiuto), firma a tempo costante, `exp`, `aud`, `sub` uguale all'identità del canale | chiude le trappole note dei JWT: `alg: none`, confusione di algoritmo |
| **Chiusura** | chiave sovrascritta (`bytearray`) e rilasciata; `ipc-token` su disco eliminato alla migrazione | nessun segreto sopravvive al processo |
| **Remoto** (bridge HTTP) | Bearer **sempre obbligatorio**, anche per GM. Token per utente creati con `gray-matter token create --user <nome>`, salvati solo come hash, revocabili | chiude F1; un token rubato si revoca senza toccare gli altri |

**Implementazione.** HS256 con `hmac` della libreria standard: poche decine di righe, nessuna
dipendenza nuova, formato JWT standard. Se l'azienda richiede una libreria certificata, PyJWT con
`algorithms=["HS256"]` fisso è un rimpiazzo diretto.

## 5. Correzioni indipendenti dal token

Non aspettano il design della sezione 4. Ognuna ha il suo test.

| # | Correzione | Test che la dimostra |
|---|---|---|
| F1 | il bridge di GM rifiuta di partire senza token, con lo stesso schema di Neuron, e passa il Bearer a `mcp-proxy` | avvio senza token → rifiuto; richiesta senza Bearer → 401 |
| F2 | la GUI accetta solo `Host: 127.0.0.1:<porta>` o `localhost:<porta>`, su GET e POST | `Host: attacker.example` → 403, niente token nella risposta |
| F3 | ingest e index solo dentro **radici dichiarate** (cartelle scelte dall'utente) e mai su percorsi sensibili (`.ssh`, `.aws`, `.env`, chiavi, credenziali) | percorso fuori radice → rifiuto con messaggio |
| F5 | l'installer scarica un **tag** di release e ne verifica lo SHA-256 | hash diverso → installazione interrotta |
| F6 | il contesto restituito all'IA è marcato come **dato, non istruzione**, con la provenienza di ogni fatto | test sul formato di `pre_turn` |

## 6. Cosa la suite non difende

Scritto perché un'azienda lo chiederà, ed è meglio che lo legga qui.

- **Amministratore o SYSTEM** della macchina: legge la RAM e i file. Nessun software in spazio utente
  si difende da lì.
- **Malware che gira con lo stesso utente**: legge i database direttamente, senza passare dal daemon.
  Il token protegge gli ingressi, non i file. La difesa è la **cifratura a riposo** con una chiave
  protetta da DPAPI (Windows) o dal keyring (Linux, macOS): fase 3.
- **L'IA stessa**: un modello che esegue istruzioni ostili lette altrove può usare i tool che gli sono
  dati. F3 e F6 restringono cosa può fare, non lo rendono impossibile.

## 7. Piano

| Fase | Contenuto | Chiude |
|---|---|---|
| **1** | bridge GM autenticato, Host check della GUI, radici dell'ingest | F1, F2, F3 |
| **2** | chiave effimera, pipe per utente, token JWT, verifica del server | F4 |
| **3** | release firmate con hash, cifratura a riposo, registro di audit delle chiamate | F5, F7 |
| **4** | multi-utente concorrente: ADR a parte, sopra l'identità della fase 2 | — |

F6 si affianca alla fase 1: è una modifica di formato, non di architettura.

### 7.1 Fase 1: cosa è stato fatto

| # | Come | Test |
|---|---|---|
| F1 | `gray-matter bridge` usa il trasporto MCP di Neuron (`serve(app, prefix="GM")`). Il Bearer vale su **qualunque** host: token da `<PREFIX>_BRIDGE_TOKEN`, oppure uno nuovo per esecuzione, stampato e mai salvato; aperto solo con `<PREFIX>_BRIDGE_ALLOW_OPEN=1` | `neuron/tests/test_bridge_auth.py`, gemello in `neurag/`; `test_cross_project` vieta `mcp-proxy` anche nel bridge di GM |
| F2 | `_foreign_host()` nella GUI: solo `127.0.0.1:<porta>` e `localhost:<porta>` | `gray_matter/tests/test_webgui_token.py` |
| F3 | `ai_ingest_refusal()` prima di ogni ingest o index chiesto dall'IA; `scan_directory` salta segreti, cartelle nascoste e link che escono dalla radice | `neurag/tests/test_ingest_guard.py` |
| F6 | `<recalled-memory>` in Neuron, `<vault-excerpts>` in NeuRAG, tag neutralizzato nel contenuto | `neuron/tests/test_data_marking.py`, `neurag/tests/test_data_marking.py` |

### 7.2 Fase 2: cosa è stato fatto

Tutto in `gray_matter/ipcauth.py`, solo libreria standard (`ctypes` per le API Windows). Due punti di
innesto: `_send_ipc` in `cli.py`, unico mittente dell'IPC, e `_ipc_listener` in `server.py`, unico
ricevente.

| Pezzo | Come | Test |
|---|---|---|
| Chiave | `new_key()` all'apertura dell'IPC, `bytearray` in RAM, `drop_key()` la sovrascrive all'uscita | `test_the_key_lives_in_ram_and_is_zeroed`, `test_a_restart_kills_every_token_issued_before` |
| Canale | pipe `gray-matter-<SID>` con DACL `D:P(A;;GA;;;<SID>)`, prima istanza, niente client remoti; socket Unix `0600` in cartella `0700` | `test_the_channel_cannot_be_taken_twice` |
| Verifica del server | il client confronta il SID del processo server della pipe col proprio, o la proprietà e i permessi della cartella | `test_the_client_sends_nothing_to_a_server_of_another_user`, `test_the_client_refuses_a_folder_others_can_write` |
| Verifica del client | il server confronta il SID del client (Windows) o l'uid via `SO_PEERCRED` (Linux) | dentro il DACL: secondo lucchetto |
| Token | JWT HS256, `exp` 15 minuti, header fisso | `test_only_our_exact_header_is_accepted`, `test_tampering_expiry_audience_user_and_key_all_fail` |
| Ordine | chiave e canale prima di pubblicare la porta | `test_the_key_and_channel_exist_before_the_port_is_published` |
| Migrazione | `ipc-token` cancellato all'avvio del daemon | `test_the_legacy_secret_file_is_removed` |

Il canale POSIX è provato su Linux in WSL. Su macOS manca `SO_PEERCRED`: lì il lucchetto è solo la
cartella `0700`.

**Trovato durante il lavoro.** F1 non era solo di GM. Anche i bridge di Neuron e NeuRAG esentavano
il loopback, ma `--tunnel` lega `127.0.0.1` e cloudflared arriva da lì: un URL pubblico serviva tutti
i tool senza chiave. La stessa correzione li copre tutti e tre.

## 8. Alternative scartate

| Alternativa | Perché no |
|---|---|
| Tenere il token condiviso su file, ruotandolo | resta la porta fissa (F4) e nessuna identità per utente |
| mTLS su loopback | certificati da distribuire e ruotare per un canale che il kernel protegge già meglio |
| Solo JWT, senza canale protetto | il primo contatto resta anonimo: chiunque chieda un token lo riceve |
