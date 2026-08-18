# DOCS-GUIDELINES — struttura e regole per la documentazione ufficiale

> Per opencode (o qualsiasi agente) che scriverà la documentazione completa
> dell'ecosistema Gray Matter. Queste sono le regole del progetto: seguile
> prima delle tue abitudini. Claudio è l'owner e decide le eccezioni.

## Principi (non negoziabili)

1. **Verità dal codice, non dai documenti vecchi.** Ogni claim (nome tool,
   parametro, default, path) va verificato nel sorgente PRIMA di scriverlo.
   L'errore classico è copiare da un MD stantio (è successo: audit con bug
   già risolti dati come aperti). Fonti canoniche: i sorgenti, poi
   `GRAY-MATTER-COMPENDIUM.md` (stato), `INSTALLER-UX.md` (install),
   `RELEASE-CHECKLIST.md` (distribuzione).
2. **Un fatto vive in UN posto.** Le liste tool, i path, le env var stanno nel
   reference; guide e tutorial LINKANO, non copiano. Ogni duplicazione è un
   futuro disallineamento.
3. **Progressione: perché → come → dettaglio.** Prima il concetto in una
   frase, poi il comando, poi (in fondo o collapsible) le opzioni complete.
4. **Ogni pagina è auto-sufficiente per il suo lettore.** Chi atterra da
   Google su "NeuRAG triggers" deve capire senza leggere altre 4 pagine:
   una riga di contesto + link alla panoramica bastano.
5. **Comandi copiabili e testati.** Ogni blocco di codice va ESEGUITO prima di
   essere documentato (o marcato `# non testato`). PowerShell per Windows,
   sh per unix — mai bash-ismi in blocchi marcati sh.
6. **Il degradato si documenta.** Ogni tier (turso→sqlite3, fastembed→TF-IDF)
   ha: come capire in che tier sei (doctor/status), cosa perdi, come salire.
7. **Lingue**: inglese primario, italiano come `*.it.md` affiancato (pattern
   INSTALL-AI già in uso). Stile: diretto, niente marketing nel reference;
   il tono "wow" vive solo nei README.

## Struttura target (per ogni repo, in `docs/`)

Neuron ha già `docs/DEVELOPER.md` e simili — estendere, non rifare. Per GM e
NeuRAG creare `docs/` con questa gerarchia (un file per riga, nomi esatti):

```
docs/
├── OVERVIEW.md        # cos'è, quando usarlo, come si incastra nella suite
│                      #   (diagramma fan-out per GM, gerarchia per NeuRAG)
├── INSTALL.md         # umani: click-and-go, per-OS, bootstrap Python,
│                      #   standalone vs gateway, upgrade, uninstall, troubleshooting
├── TOOLS.md           # REFERENCE MCP: ogni tool = firma, parametri con tipi e
│                      #   default, output, un esempio reale, errori tipici.
│                      #   Generare la lista dai sorgenti (list_tools), non a mano.
├── CLI.md             # reference della CLI (gray-matter/neuron/neurag):
│                      #   comando, flag, esempio, exit code
├── CONFIGURATION.md   # TUTTE le env var e i knob di settings.py in UNA tabella:
│                      #   nome, default, effetto, quando toccarla
│                      #   (NS_EMBED_MODEL, NEURAG_*, GM_*, TURSO_*, ...)
├── ARCHITECTURE.md    # per dev: moduli, flussi (pulse, store_turn, install),
│                      #   decisioni chiave con il PERCHÉ (gateway-only, refs
│                      #   table anti-clobber, tier a degradazione, trust)
├── DATA.md            # dove vivono i dati, formato, backup, migrazione,
│                      #   cosa tocca/non tocca l'uninstall, re-embed
└── TROUBLESHOOTING.md # sintomo → diagnosi → fix. Includere: tier degradato,
                       #   "open: NotFound" (L2), client che non vede i tool,
                       #   doppio daemon, Store-stub Python
```

Più, a livello suite (nel repo gray_matter, che è il download completo):
`docs/GETTING-STARTED.md` — il tutorial end-to-end: install → primo pulse →
primo store_turn → primo vault indicizzato → confirm/trust. Max 10 minuti di
lettura, ogni passo con l'output atteso.

## Ordine di scrittura consigliato

1. `CONFIGURATION.md` (obbliga a censire la verità dal codice — trova bug)
2. `TOOLS.md` + `CLI.md` (reference: tutto il resto ci linka)
3. `INSTALL.md` (esiste per Neuron, aggiornarlo; scriverlo per GM/NeuRAG)
4. `OVERVIEW.md` + `ARCHITECTURE.md`
5. `GETTING-STARTED.md` (per ultimo: quando tutto ciò che cita è stabile)
6. `DATA.md` + `TROUBLESHOOTING.md`

## Regole di stile

- Titoli frase, non Title Case. Tabelle per reference, prosa per concetti.
- Un esempio REALE vale tre esempi inventati: usare output veri dei comandi.
- Niente "semplicemente/basta/ovviamente". Se era ovvio non serviva scriverlo.
- Path Windows E unix dove differiscono (pattern già usato nei README).
- Versioni citate = quelle del pyproject al momento della scrittura; il
  CHANGELOG è la storia, i docs sono il presente.
- Chiudere ogni guida con "Next steps" (2-3 link, non di più).

## Sezione storica e di ricerca (docs "sapienziali")

Oltre al reference, tre documenti raccontano il progetto. Vivono in
`Neuron/docs/` (o suite-level in gray_matter/docs se cross-tool). I FILE
SORGENTE li indica Claudio — qui c'è solo il COME scriverli.

### TECHNOLOGY.md — gli studi sulle tecnologie

Ogni tecnologia adottata = una scheda con QUATTRO campi fissi:
**problema** (cosa doveva risolvere) → **alternative considerate** (con il
motivo dello scarto, una riga ciascuna) → **scelta e perché** → **limiti
accettati** (i ponytail: ceiling noti e upgrade path). Esempi da coprire:
Turso/libSQL vs ChromaDB (migrazione fatta: F8), fastembed/ONNX vs
sentence-transformers, modello multilingue vs monolingua, MCP come protocollo,
worker persistenti vs cold-import, flat vs src layout.
Regola: si scrive la scheda ANCHE per le scelte poi ribaltate — lo scarto
motivato vale quanto l'adozione.

### EVOLUTION.md — il progresso dalla V1

Non un changelog (quello esiste già): una NARRAZIONE per ere, dove ogni era
risponde a: *qual era il limite della versione precedente che ha forzato il
salto?* Formato per era: nome+versione → il muro incontrato → l'idea che lo
supera → cosa si è rotto nel passaggio (migrazioni, compat) → cosa resta di
quell'era nel codice di oggi. Le ere le definisce Claudio coi file che
passerà; indicativamente: V1-V3 (le origini), V4 (slug `neuron`, installer
monolitico), V5 "Synapse" (grafo semantico maturo, cloud Turso, curation),
V6 "gateway era" (trust, refs, GM-only, click-and-go).
Regole: mai riscrivere la storia col senno di poi — se una scelta era
sbagliata si dice cosa si sapeva ALLORA; citare i numeri quando esistono
(253→340 test, latenze pulse); ogni era chiude con un link ai commit/tag.

### PROCESS.md — il processo di studio e sviluppo di Neuron

Questo è il documento più difficile: racconta il METODO, non il prodotto.
Indicazioni da chi ci ha lavorato dentro (integrale ciò che manca con
Claudio, che è la memoria storica):

1. **Il compendium come cervello condiviso.** Un unico file
   (GRAY-MATTER-COMPENDIUM.md) fa da SSOT di bug, decisioni e roadmap; ogni
   sessione — umana o AI — inizia leggendolo e finisce aggiornandolo.
   Documentare il pattern: handoff espliciti, TODO ordinati per dipendenze,
   stati ✅/◐/⬜ verificati dal codice e non dalla memoria.
2. **Multi-AI con ruoli.** Fable (architettura+implementazione), opencode
   (esecuzione locale, test reali, commit), audit esterni (Laguna, Minimax)
   trattati come input DA VERIFICARE: l'audit del 20/07 aveva il 60% di
   claim stantii — la regola "verità dal codice" nasce lì. Raccontare anche
   il caso L2: bug intermittente cacciato in 3 sessioni con strumentazione
   progressiva (trappola del traceback al livello giusto), non a tentativi.
3. **Sandbox → locale, sempre.** Nessun fix è "verde" finché la suite non
   gira sulla macchina reale (regola ENVIRONMENT.md). Smoke test in sandbox
   come primo filtro, pytest locale come verdetto.
4. **Ponytail / YAGNI come disciplina.** La soluzione più corta che funziona,
   i ceiling marcati con commenti `ponytail:`, il debito tracciato invece di
   negato. Citare esempi veri: refute senza tool nuovo (confidence negativa),
   dry_run con helper condiviso, thin launcher da 16 righe.
5. **Il design si àncora allo schema.** Le decisioni grosse (refs table
   anti-clobber, trust nel ranking, tier a degradazione) nascono sempre da
   un'analisi del modello dati esistente, mai da feature-wish. Mostrare il
   caso §6.10 del compendium (path+provenienza) come esempio di design doc.
6. **Neuron sviluppato USANDO Neuron.** Il loop pre_turn/store_turn ha
   registrato lo sviluppo di sé stesso — dogfooding estremo: i bug di
   store_turn sono emersi salvando le decisioni su store_turn. È l'angolo
   narrativo più forte del documento: usarlo.

Se su un punto mancano dettagli, chiedere a Claudio invece di inventare:
è lui la fonte primaria del processo.

## Definition of done (per ogni file)

- [ ] Ogni comando eseguito con successo (o marcato non testato)
- [ ] Ogni nome tool/flag/env var grep-ato nei sorgenti
- [ ] Link relativi verificati DENTRO il repo (lo zip è autosufficiente:
      mai link a `../` fuori dal repo)
- [ ] Letto ad alta voce il primo paragrafo: spiega perché esisto in 2 frasi?
- [ ] Passato su un ambiente pulito almeno GETTING-STARTED e INSTALL
