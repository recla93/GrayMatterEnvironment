# Release Checklist — Gray Matter Environment (prima release unificata)

> Obiettivo: 2 file di install per OS, per ogni repo. GM sempre il cervello.
> Stato pre-release: gateway flip ✅ · installer unificati ✅ · wizard GUI ✅
> (Setup card: componenti + Preview/Install/Test + Prefs + Turso).

> **Audit locale 2026-07-20** (`~/Desktop/RELEASE-AUDIT-2026-07-20.md`):
> 337/338 verdi. I 3 bug emersi sono FIXATI (sandbox, da riverificare in suite):
> pollution `sys.modules` → conftest purge in gray_matter/tests e neurag/tests
> (fixture session autouse, scatta dopo i test Neuron); `_FixedEmbedder.name`
> aggiunto; **stack overflow cascade** → nuovo `db.delete_node()` con delete
> espliciti bottom-up (mai innescata la cascade FK di pyturso 0.6.1) + 2 test.
> Nota: la cascade FK resta nello schema ma NON va usata con DELETE raw su
> pyturso — usare sempre `delete_node()`.

## 1. Verifica locale (blocca tutto il resto)

- [ ] Suite: `pytest Neuron/tests gray_matter/tests neurag/tests -q` (attesi ~270+35+15)
- [ ] `test_vector_sql.py` col pyturso attivo (path SQL vero, non solo fallback)
- [ ] Wizard nel browser: `gray-matter gui` → Setup card → Preview → Install → Test → Prefs
- [ ] Install end-to-end da zero su una macchina/utente pulito: `.\install.ps1` → GUI → wizard
- [ ] Uninstall interattivo: memoria chiesta, `.bak` ripristinabili
- [ ] Commit dei 3 repo (accumulate: executor, trust/G2, installer, wizard, D3/D4, RAG-Turso)

## 2. Packaging per-OS

- [ ] **Windows**: `NeuronInstaller.exe` nel repo è STALE (build pre-unificazione,
      segnalato da Claudio) — RIMUOVERLO dal repo git (mai versionare il compilato),
      ricompilarlo al build di release dalla catena nuova (exe → install.ps1 →
      canonico GM) e allegarlo SOLO all'artifact
- [ ] **Flusso install SSOT** (fissato da Claudio 2026-07-20): scarichi Neuron
      o NeuRAG → 2 script (win / mac-linux) installano tool + Gray Matter →
      si apre la GUI → card Setup: wizard componenti, Install/Repair
      (idempotente), Test, Prefs, Turso, **Folders** (install dir, grafi
      Neuron, knowledge NeuRAG, config — con Open nel file manager). GUI
      aggiornata 2026-07-20: Folders… e Install/Repair implementati
- [x] **Click-and-go** (2026-07-20 sera): wrapper doppio-click `install.cmd`
      (Windows) e `install.command` (mac/linux) in radice, Neuron e neurag;
      bootstrap Python nei canonici — winget (build ufficiale python.org, lo
      stub Windows Store è già trattato come assente dal version-check) /
      brew / apt / dnf con consenso, fallback pointer a python.org. `.exe`
      binario già fuori dal repo (resta il sorgente .cs, build al release);
      `gray_matter/build/` ripulita; `.gitignore` di radice aggiunto; README
      radice+Neuron+neurag aggiornati al flusso doppio-click. **Da provare in
      locale: doppio-click reale su Win e mac/linux, incluso il ramo winget**
- [ ] Vendored wheels pyturso aggiornati (`Neuron/vendor`, py310–314 win_amd64)
- [ ] **Wheel d'emergenza di Gray Matter ricostruita** (fallback OFFLINE del
      bootstrap `neuron/neurag gui` quando GM manca — GM ha solo `mcp` come dep,
      già presente nei venv dei tool). A OGNI release di GM, dopo il bump:
      `python -m pip wheel ./gray_matter --no-deps -w <tmp>` poi copia la
      `gray_matter-<ver>-py3-none-any.whl` in **`neuron/src/neuron/_gm_vendor/`**
      e **`neurag/_gm_vendor/`** (rimuovendo la vecchia). È `package-data` in
      entrambi i pyproject → viaggia nel wheel dei tool. Se te la dimentichi, il
      bootstrap standalone offline installa una GM vecchia (o cade su rete/GitHub).
- [ ] `pip download pytest -d Neuron/vendor/dev` (pytest offline per sandbox/CI)
- [ ] **macOS/Linux**: `install.sh` eseguibile nel tarball (`chmod +x` preservato)
- [ ] **Modello di distribuzione (SSOT, fissato da Claudio 2026-07-20 sera):**
      la cartella "Gray Matter Enviroment" è SOLO workspace dev, mai
      distribuita — installer di radice RIMOSSI. L'unità di distribuzione è il
      singolo zip GitHub, autosufficiente:
      · **gray_matter zip** = GM + Neuron/ + neurag/ BUNDLED dentro (full suite)
      · **Neuron zip** = Neuron + gray_matter/ bundled
      · **neurag zip** = neurag + gray_matter/ bundled
      Canonici ed executor aggiornati: cercano i tool prima DENTRO il repo GM
      ($HERE/Neuron, $HERE/neurag), poi come sibling. Al build: copiare le dir
      bundled negli zip (git subtree o copia; MAI duplicare nei repo git).
- [ ] Artifact per repo: zip con il bundling di cui sopra + wheels per NeuRAG-only
- [ ] **Wheels pyturso negli artifact standalone** (nota Claudio 2026-07-20):
      `pyturso==0.6.1` è dipendenza HARD anche di NeuRAG → l'artifact
      NeuRAG-only per Windows DEVE includere una copia di `vendor/` (presa da
      `Neuron/vendor` al build, NON duplicata nel repo git — fonte unica).
      L'installer canonico cerca già `$GM_PEER_DIR/vendor`: zero code change.
      macOS/Linux non servono (wheel su PyPI). Idem per un eventuale artifact
      GM-only: GM non dipende da pyturso, nessuna wheel necessaria.
- [x] **Checkout NeuRAG+GM senza Neuron** (follow-up Claudio): risolto alla
      radice — pyturso NON è più dipendenza hard di neurag ma extra `[turso]`
      (il pyproject ora rispecchia il design a 3 tier di db.py). L'install
      base funziona ovunque sul tier sqlite3; l'installer canonico tenta il
      tier turso best-effort (`pip install pyturso==0.6.1` con `--find-links`
      dal vendor disponibile, poi PyPI) e se fallisce lo dice senza bloccare.
      Il pin resta uno solo, nell'extra, da bumpare col pin di Neuron.
- [x] **Degradato mai silenzioso** (nota Claudio): il tier sqlite3 è solo
      l'ultima rete (checkout parziale Windows senza wheel) — tutti i percorsi
      di release hanno il tier Turso pieno. FATTO: `_build_doctor` (async)
      interroga `knowledge_status` e il doctor stampa
      `[!!] NeuRAG vector tier DEGRADED … pip install neurag[turso]` quando
      l'engine è sqlite. Il Test del wizard usa il doctor → warning incluso.
      Da vedere dal vivo alla verifica locale.

## 3. Versioni e metadata

- [ ] Bump coerente: **Neuron 6.0.0** (major approvato da Claudio 2026-07-20:
      schema DB nuovo trust+refs con migrazioni, confirm±/refute, introspect,
      ranking a 4 pesi, paradigma install gateway) · NeuRAG 0.3.0 · GM 0.2.0
- [ ] Badge versione nei 3 README allineati ai pyproject
- [ ] CHANGELOG per repo (dal compendium §0 — le sessioni 07-18/19/20 sono il grosso)
- [ ] `release.yml` aggiornato a Python 3.14 (housekeeping noto)

## 4. Documentazione finale

- [ ] README ✅ · INSTALL-AI ✅/it ✅ · INSTALL.md Neuron ✅ — ripasso finale link/versioni
- [ ] Compendium: spostare §0 handoff in CHANGELOG, tenere solo TODO vivi

## 5. Smoke post-release (su download reale)

- [ ] Windows pulito: exe → wizard → `pre_turn`/`store_turn` da Claude Desktop
- [ ] Linux/mac: `sh install.sh` → idem
- [ ] Standalone: repo singolo Neuron-only e NeuRAG-only (GM_PEER_DIR path)

### Tier semantico di default (decisione Claudio 2026-07-20)

Il vault è multi-disciplinare e deve essere preciso: fastembed diventa parte
dell'install standard — l'installer canonico lo tenta best-effort (come
pyturso), mai bloccante, fallback lessicale TF-IDF. Chiarito il modello: gli
embedding NON riducono i token di per sé (l'LLM riceve sempre testo) — li
riducono indirettamente via precisione del retrieval (meno chunk, più giusti).
Nota: fastembed scarica il modello ONNX (~80MB) al primo uso → il primo
`knowledge_query`/pulse dopo l'install è lento una tantum; il pre-warm D2 lo
assorbe all'avvio del daemon. Doctor: valutare di esporre anche il tier
embedding accanto a `neurag_engine` (post-1.0).
**Modello allineato 2026-07-20** (domanda Claudio su multilingua): NeuRAG
defaultava ad `all-MiniLM-L6-v2` (solo EN) mentre Neuron è già su
`paraphrase-multilingual-MiniLM-L12-v2` (IT/EN, 384-dim) — spazi vettoriali
diversi, bridge e appunti italiani penalizzati. Fix: NeuRAG ora segue
`NEURAG_EMBED_MODEL` → `NS_EMBED_MODEL` → default multilingue di Neuron (una
env governa la suite, stessa dimensione = zero migrazioni schema).
- [ ] **Re-embed vault esistenti** creati col modello vecchio (vettori non
      confrontabili col nuovo): serve un `neurag reembed` o nota di rilascio
      "reindicizza il vault". NeuRAG non ha il write-guard P5 di Neuron →
      valutarlo post-1.0 (meta `embed_model` nel knowledge.db).

## Rischi aperti (non bloccanti, monitorare)

- **L2** `open: NotFound` — intermittente, trappola col traceback armata; se ricompare
  in release, il messaggio d'errore ora contiene lo stack completo
- Costo doppio GM stdio per-app (worker duplicati) — thin-shim stdio→daemon solo se la RAM morde
- `libsql_vector_idx` + scoping sottoalbero quando il vault supera ~10k chunk
