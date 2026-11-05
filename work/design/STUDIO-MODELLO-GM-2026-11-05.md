---
title: Un modello che diventa Gray Matter — studio di fattibilità (mock)
tags: [gray-matter, modello, api, strati, fattibilita, progetto]
created: 2026-11-05
status: mock — niente è implementato, nessuna fase è in calendario
---

# Un modello che diventa Gray Matter — studio di fattibilità

> [!abstract] In sintesi
> - **Cos'è.** Lo studio di quattro strade per offrire Gray Matter come **modello**: un endpoint che
>   un client chiama come chiamerebbe Claude, e che risponde con la memoria già dentro.
> - **Come funziona.** Nella strada che regge, GM è un proxy davanti al modello. A ogni richiesta fa
>   lui il richiamo (lo stesso dell'ADR-014), lo inietta, inoltra la richiesta e registra il turno.
>   Il client non chiama strumenti di memoria: ha solo cambiato indirizzo.
> - **A cosa serve.** Oggi la memoria funziona dove ci sono un client MCP e un modello che si
>   ricorda il loop. Un proxy la porta in **ogni** client che accetta un `base_url`, senza hook e
>   senza strumenti.

> [!info] Le quattro strade, in una riga
> | Strada | Verdetto |
> |---|---|
> | A. Proxy davanti a un modello esistente | **fattibile**, è il prolungamento naturale di ADR-014 e ADR-013 |
> | B. Piccoli modelli dentro GM (estrazione, ranking) | **fattibile e conveniente**, il primo passo da fare |
> | C. Modello aperto rifinito (LoRA) che usa la memoria da solo | possibile, costoso da mantenere, da rimandare |
> | D. Modello addestrato da zero | **non fattibile** a questa scala |

---

## Mappa

| Capitolo | Domanda |
|---|---|
| 1. Gli strati | come si legge l'evoluzione di GM, dal disco al prodotto |
| 2. Strada A — il proxy | come diventa "un modello" senza addestrare niente |
| 3. Strada B — i piccoli modelli | dove un modello piccolo vale più di un'euristica |
| 4. Strada C — il modello rifinito | cosa costerebbe un modello che usa la memoria da sé |
| 5. Strada D — da zero | perché no |
| 6. Economia | quanto costa un turno, e cosa non sappiamo ancora |
| 7. Vincoli | termini d'uso, privacy, cache, ragionamento conservato |
| 8. Piano | le fasi, ognuna con la sua prova |

Ogni capitolo regge da solo.

---

## 1. Gli strati

Due assi, e vanno tenuti separati.

### 1.1 Strati della memoria (dentro il cervello)

Sono i cinque di [CINQUE-STRATI](CINQUE-STRATI-2026-11-03.md): working, episodic, semantic,
procedural, meta. Dicono **cosa** GM ricorda. Questo studio non li cambia.

### 1.2 Strati del prodotto (dal disco al cliente)

Dicono **dove** GM vive e chi lo vede.

| Strato | Cosa contiene | Oggi |
|---|---|---|
| **P0 Modello** | il modello che genera il testo | Claude o un altro, scelto dal client |
| **P1 Memoria** | Neuron (grafo, episodi) e NeuRAG (vault) | c'è, locale |
| **P2 Orchestrazione** | GM: richiamo, flash, bridge, budget | c'è, come server MCP e daemon |
| **P3 Ingresso** | come la memoria entra nel turno | MCP + hook (ADR-014) |
| **P4 Superficie** | cosa vede chi usa la suite | strumenti MCP, GUI, CLI |

L'evoluzione di questo studio è **P3 e P4**: l'ingresso diventa un endpoint, la superficie diventa
un nome di modello. P1 e P2 restano quelli di oggi.

---

## 2. Strada A — il proxy

### 2.1 Cos'è

Un endpoint compatibile con la Messages API. Il client cambia solo `base_url`. Il nome del modello
che chiede è, per esempio, `gray-matter-1`. Il proxy sa a quale modello vero inoltrare.

### 2.2 Come funziona

```
client (Claude Code, SDK, app)            base_url = http://localhost:<porta>  oppure  https://<hub>
   │  POST /v1/messages  {model: "gray-matter-1", messages: [...]}
   ▼
proxy GM
   1. chi chiama (token) → quale memoria (spazio personale o di team, ADR-013)
   2. ultimo messaggio dell'utente → _hook_recall (lo stesso dell'ADR-014): contesto, KB, flash
   3. il richiamo entra come messaggio di sistema IN CODA, dopo l'ultimo punto di cache
   4. inoltro al modello vero (P0), in streaming
   5. a risposta finita, in background: registrazione del turno (D4 dell'ADR-014)
   ▼
client: riceve la risposta in streaming, come da Claude
```

### 2.3 Due varianti

| | **A1 — proxy locale** | **A2 — proxy ospitato (hub)** |
|---|---|---|
| Dove gira | sul portatile, dentro il daemon | su un server, è l'hub dell'ADR-013 fase 4b |
| La memoria esce dal portatile | no | sì, per gli spazi condivisi |
| Chi paga il modello | l'utente, con la sua chiave | noi, a consumo, e lo rivendiamo |
| Cosa serve | un listener HTTP nel daemon | hub, identità, quote, audit, fatturazione |
| Fattibilità | **alta**: un mese di lavoro, tutto il resto esiste | media: è la 4b più un prodotto commerciale |

**A1 è l'hook universale.** L'ADR-014 vale solo per Claude Code, perché solo Claude Code ha gli hook.
Un proxy locale funziona con ogni client che accetta un indirizzo: SDK, script, altri agenti.

### 2.4 Perché è "un modello che diventa GM"

Dal lato del client non c'è più differenza fra "un modello" e "un modello con memoria". Il client
non sa che esiste un loop. La memoria non è più uno strumento che il modello deve ricordarsi di
chiamare: è una proprietà dell'endpoint.

È lo stesso principio dell'ADR-014, portato al livello più basso possibile: un meccanismo
involontario non può dipendere da un atto volontario.

---

## 3. Strada B — i piccoli modelli dentro GM

### 3.1 Il problema che risolvono

L'estrazione di oggi è euristica, e sul vivo conia parole vuote (ADR-014, D4):

```
extract("Il flash era gestito da GM in prima battuta: se parliamo di qualcosa…")
→ pulse, parliamo, qualcosa, flash, chiamare, battuta
```

Per questo il salvataggio automatico è fermo in dry-run. Un modello piccolo che estrae concetti e
relazioni tipizzate sblocca la fase 3 dell'ADR-014: il loop di scrittura senza il modello grande.

### 3.2 Due modi

| | Modello piccolo via API | Modello piccolo locale |
|---|---|---|
| Esempio | Claude Haiku 5.5 | un modello aperto quantizzato (GGUF) servito da Ollama |
| Costo | a consumo, vedi §6 | zero per chiamata, una GPU o CPU occupata |
| Latenza | rete + generazione | dipende dall'hardware |
| Privacy | il testo del turno esce | resta sul portatile |
| Esperienza già fatta | — | sì: deploy MoE, template, `num_gpu` (memoria del grafo `ai`) |

Il lavoro gira **dopo** la risposta, nell'hook `Stop` o nel proxy. La latenza non pesa sull'utente.

### 3.3 Altri due posti dove un modello piccolo serve

- **Rerank del richiamo**: NeuRAG ha già un cross-encoder opzionale. Lo stesso vale per i nodi di
  Neuron prima del budget.
- **Il giudice di `confirm`**: oggi `confirm`/`dismiss` dipendono dal modello grande. Un modello
  piccolo può dire, a fine turno, quali ricordi iniettati sono stati usati nella risposta. È l'oblio
  per **valore** che manca allo strato meta.

---

## 4. Strada C — il modello rifinito

### 4.1 Cos'è

Un modello aperto, rifinito con LoRA su tracce di uso di GM, così che usi la memoria da sé: chiede il
richiamo quando serve, salva quando c'è qualcosa di nuovo, tipizza i link.

### 4.2 Cosa servirebbe

| Pezzo | Stato |
|---|---|
| Dati: turni con le chiamate di memoria giuste | pochi: 14 sessioni in questo progetto, e le chiamate sono quelle che il modello **salta** |
| Una misura (recall@k, costo per turno) | non esiste ancora: è il passo 2 di CINQUE-STRATI |
| Hosting | una GPU dedicata o un servizio a consumo |
| Manutenzione | a ogni modello base nuovo, si rifà |

### 4.3 Perché rimandarla

La strada A ottiene il comportamento senza addestrare: il proxy **fa** il loop, quindi il modello non
deve impararlo. La C torna utile solo se serve un modello che gira **senza** proxy, per esempio
offline su un dispositivo. Non è un bisogno misurato oggi.

---

## 5. Strada D — da zero

Addestrare un modello di base richiede dati, calcolo e persone a una scala che non è la nostra.
E non servirebbe: GM vale per la memoria intorno al modello, non per il modello. Scartata.

---

## 6. Economia

### 6.1 Listino usato (Anthropic, prezzi per milione di token, aggiornati al 2026-10-06)

| Modello | Input | Output | Lettura dalla cache |
|---|---|---|---|
| Claude Opus 5.5 | $4.00 | $20.00 | $0.20 |
| Claude Sonnet 5.5 | $2.00 | $10.00 | $0.20 |
| Claude Haiku 5.5 | $0.10 | $0.50 | — |

La scrittura in cache costa circa 1,25 volte l'input; la lettura circa 0,1 volte. **Da riverificare
sul listino prima di qualunque offerta.**

### 6.2 Cosa aggiunge GM a un turno

| Voce | Quantità | Costo per turno su Sonnet 5.5 |
|---|---|---|
| Richiamo iniettato | ≤ 1200 caratteri, ~300 token di input | 300 × $2 / 1M = **$0.0006** |
| Estrazione con Haiku 5.5 (strada B) | ~600 input + ~100 output | 600 × $0.10/1M + 100 × $0.50/1M ≈ **$0.0001** |
| Totale aggiunto | | **≈ $0.0007**, cioè ~$0.70 ogni mille turni |

Il richiamo va **dopo** l'ultimo punto di cache, quindi non invalida il prefisso. Ma non si mette in
cache a sua volta, perché cambia a ogni turno.

### 6.3 Cosa non sappiamo, ed è la domanda vera

Il costo aggiunto è piccolo e misurabile. Il **beneficio** no: quanti token si risparmiano perché
l'utente non rispiega, quante risposte migliorano perché il ricordo c'era. Nessuno l'ha misurato.

Senza quella misura:

- A1 si giustifica lo stesso, perché è gratis per noi e migliora l'uso;
- A2 non si può vendere con un numero in mano.

La misura è il passo 2 di CINQUE-STRATI, e diventa il prerequisito di A2.

---

## 7. Vincoli

### 7.1 Termini d'uso e nome

- Il modello si chiama `gray-matter-1`, non con il nome del modello sotto. La documentazione dice
  quale modello lo alimenta.
- La strada A2 rivende l'accesso a un modello di terzi: vanno rispettati i termini commerciali del
  fornitore. Da verificare prima della fase A2, non dopo.

### 7.2 Privacy

- **A1** non sposta niente: la memoria resta sul portatile, come oggi (ADR-013, D1).
- **A2** porta sul server almeno gli spazi condivisi. Con identità, permessi e audit dell'ADR-013,
  e con la cifratura a riposo dell'ADR-012 fase 3. La memoria personale può restare locale, con il
  proxy locale che parla con l'hub solo per gli spazi di team.

### 7.3 Cache e ragionamento conservato

Due regole tecniche del modello sotto, che il proxy deve rispettare:

- **La cache è un confronto di prefisso.** Qualunque byte cambiato prima dell'ultimo punto di cache
  la invalida. Quindi il richiamo non si scrive nel `system` iniziale: si **aggiunge in coda**.
- **I modelli recenti legano i blocchi di ragionamento alla conversazione.** Modificare un turno
  passato li invalida. Quindi il proxy deve essere **append-only**: aggiunge messaggi di sistema a
  metà conversazione, non riscrive quelli vecchi. Il richiamo di un turno resta nella storia; quello
  del turno dopo si aggiunge.

Sono vincoli, non ostacoli: un proxy che aggiunge soltanto li rispetta per costruzione.

### 7.4 Latenza

Il richiamo misurato per l'ADR-014 costa 100–275 ms lato daemon. Dentro un proxy il costo
dell'avvio di Python sparisce, perché il proxy è già un processo vivo. Davanti a una generazione che
dura secondi, è sotto la soglia di percezione.

---

## 8. Piano

| Fase | Contenuto | Si dimostra con |
|---|---|---|
| **B1** | estrazione con un modello piccolo, dietro un flag, confrontata con l'euristica sul log del dry-run dell'ADR-014 | su 100 turni reali: meno parole vuote, più concetti già esistenti riconosciuti |
| **M** | la misura: recall@k e costo per turno, con e senza richiamo | un numero di token risparmiati, o la prova che non ce ne sono |
| **A1** | proxy locale nel daemon: `/v1/messages`, streaming, richiamo in coda, registrazione in background | Claude Code con `ANTHROPIC_BASE_URL` sul proxy: memoria in ogni turno, zero chiamate di loop |
| **A2** | proxy sull'hub (ADR-013 4b), con quote e fatturazione | due utenti, due memorie, un conto a consumo coerente con il listino |
| **C** | solo se serve un modello offline senza proxy | — |

**L'ordine conta.** B1 e M non dipendono da niente e rendono possibili le altre. A1 riusa tutto quello
che c'è. A2 aspetta la misura, perché senza numero non c'è prodotto.

## 9. Verdetto

- **Si può fare**, e non serve addestrare un modello. GM "diventa un modello" diventando l'endpoint.
- La parte nuova vera è piccola: un listener HTTP compatibile con la Messages API, append-only.
- La parte che manca davvero è **la misura del beneficio**. È lei che decide se A2 è un prodotto.
