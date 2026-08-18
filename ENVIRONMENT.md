# ENVIRONMENT — come lavorare nel Gray Matter Environment

> Doc canonico d'ambiente. Fissa una volta le regole che ogni sessione/handoff
> ri‑scopriva. Aggiornato: 2026‑07‑29.

> ⚠️ **Le §1–§2 descrivono il vecchio setup Cowork** (file‑tool su Windows +
> sandbox Linux senza rete, pytest vendorato). **Non è più così.** Si lavora in
> locale sui file veri, con i venv veri e la rete: `pytest` gira direttamente e
> i suoi risultati valgono. Restano lì perché il vincolo torna se qualcuno
> riapre il progetto in un sandbox — non perché descrivano oggi.
>
> Comandi correnti (Windows, dalla root del workspace):
>
> ```
> neuron\.venv\Scripts\python.exe -m pytest neuron/tests    -q
> neuron\.venv\Scripts\python.exe -m pytest neurag/tests    -q
> neuron\.venv\Scripts\python.exe -m pytest gray_matter/tests -q
> ```
>
> Le tre suite si lanciano **separatamente**: i tre repo hanno file di test con
> lo stesso nome (`test_no_console_window.py`), e in un'unica invocazione pytest
> fallisce la collection con "import file mismatch".
>
> Per provare un install senza toccare le proprie config MCP:
> `GM_NO_CLIENT_REGISTER=1`. Isolare `LOCALAPPDATA` **non basta** — i config dei
> client stanno in `%APPDATA%`, `~/.claude.json` e `~/.codex`.

Vale per i tre progetti (Neuron, NeuRAG, Gray‑Matter). Il contesto è una sessione
Cowork: file‑tool sui file reali su Windows + un sandbox Linux (`bash`) con mount
dei file. I due non sono lo stesso filesystem.

---

## 1. Due viste dei file — quale è la verità

- **File‑tool (Read/Write/Edit) = fonte di verità.** Colpiscono i file reali su
  Windows in modo affidabile.
- **Il mount `bash` è una copia in ritardo e a volte troncata a metà edit.** Non
  riflette in modo affidabile un file appena editato via file‑tool.

**Regola:** dopo un edit via file‑tool, **non** validare quel file con `bash`
(niente `cat`, `sh -n`, `py_compile`, `pytest` sul file appena toccato): puoi
leggere contenuto stale o troncato. Sintomi visti: `install.sh` fermo a una
versione vecchia con "errore riga 119" fantasma; `py_compile` che falliva su
`InitializationOptions` mentre il file vero si chiude regolarmente.

**Cosa fare invece:**
- Validare la sintassi di uno *snippet* isolato: scrivilo in `/tmp` e controlla lì
  (es. `dash -n /tmp/chk.sh`). Il contenuto lo controlli tu, non il mount.
- Per il resto, fidati del file‑tool e verifica il comportamento **in locale**
  (sotto).

`git status`/`git diff` dal sandbox sono anch'essi inaffidabili (index stale,
HEAD detached): **git si usa solo in locale.**

---

## 2. Test — niente PyPI nel sandbox, quindi pytest offline

Il sandbox non raggiunge PyPI (proxy 403): non si installano `mcp`/`fastembed`/
`pytest`. Ma la suite è progettata con stub — `tests/test_core.py` mocka
fastembed/mcp/turso all'import, gli altri file usano `pytest.importorskip`.
Manca solo `pytest`, che è pure‑python → si vendora una volta e gira offline.

**Setup (una volta, IN LOCALE dove c'è rete):**
```bash
# scarica pytest + le sue dip pure-python dentro il repo
pip download pytest -d Neuron/vendor/dev
```
Questo popola `Neuron/vendor/dev/` con `pytest`, `pluggy`, `iniconfig`,
`packaging` (+ `exceptiongroup`, `tomli` su Python 3.10). Committali: da lì è
offline per sempre.

> ⚠️ **Gap noto (2026-07-21):** il `vendor/dev/` attuale è stato catturato su
> Python ≥3.11 e **manca `exceptiongroup` e `tomli`**, richiesti da pytest su
> 3.10 → `pip install --no-index` fallisce lì. Fix (in locale, con rete):
> `pip download exceptiongroup tomli -d Neuron/vendor/dev` su un interprete 3.10,
> poi commit. `gray_matter` e `Neurag` non hanno un proprio `vendor/dev` e usano
> quello di Neuron (`--find-links ../Neuron/vendor/dev`).
>
> ⚠️ **NeuRAG su CI Linux:** la cartella è `Neurag` ma il pacchetto è `neurag`.
> Su filesystem case-sensitive la collection dei test fallisce con
> `No module named 'neurag'` se si usa il raw `sys.path`. Girare i test dopo
> `pip install -e .` (l'egg `neurag` risolve a prescindere dal case della cartella).

**Uso (anche nel sandbox, senza rete):**
```bash
cd Neuron
pip install --no-index --find-links vendor/dev pytest --break-system-packages
python -m pytest tests/test_core.py -q      # suite a stub, gira senza fastembed/mcp reali
```
I test che richiedono `mcp`/`fastembed` reali si auto‑skippano (`importorskip`):
quelli girano **in locale/CI** con `pip install -e .[dev] && pytest`.

> Finché `vendor/dev/` non è popolato, la verifica in‑sandbox resta: check statico
> + snippet isolati in `/tmp`. È il motivo per cui i fix di codice qui vanno
> sempre ri‑lanciati in locale prima di considerarli "verdi".

---

## 3. `.env` col Turso cloud — non farti dirottare

Se `.env` contiene `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`, qualunque
`import neuron` ad‑hoc va sul **DB cloud condiviso** e ignora i path locali
(`NS_GRAPHS_DIR`) — su quel tier lo scoping è per colonna `context`, non per file.
`pytest` salta già il caricamento `.env`; gli script no.

**Regola:** per ogni verifica locale/manuale forza il locale:
```bash
NEURON_NO_DOTENV=1 NS_GRAPHS_DIR=/tmp/neuron-test  python -c "..."
```
Protocollo completo di store isolato + server gemello `neurontest`:
`Neuron/handoff/HANDOFF-test-env-setup.md` (+ `TEST-PROTOCOL-opencode.md`).

---

## 4. Cosa gira dove — riassunto

| Operazione | Sandbox (qui) | Locale / CI |
|---|---|---|
| Leggere/editare file | ✅ file‑tool | ✅ |
| Sintassi di snippet isolati | ✅ `/tmp` | ✅ |
| Suite a stub (`test_core`) | ✅ *dopo* vendor/dev | ✅ |
| Suite completa (mcp/fastembed reali) | ❌ (auto‑skip) | ✅ `pip install -e .[dev] && pytest` |
| `git` commit/tag/push, release | ❌ | ✅ solo qui |
| Verifica su Turso cloud | ❌ | ✅ con credenziali |

Regola d'oro: **un fix di codice fatto nel sandbox non è "verde" finché non gira
in locale.** Il sandbox serve a scrivere e a fare check statici, non a garantire.
