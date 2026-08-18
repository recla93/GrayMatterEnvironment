# Installazione

> Come installare il Gray Matter Environment (Gray Matter + Neuron + NeuRAG).
> Il download `gray_matter` include tutti e tre: un solo installer configura
> l'intera suite dietro un unico connettore MCP. Per il dettaglio per-progetto
> vedi [`Neuron/INSTALL.md`](../Neuron/INSTALL.md).

## Prerequisiti

- **Python 3.10+** (consigliato 3.12). L'installer può installarlo per te su
  macOS (Homebrew), Debian/Ubuntu (apt) e Fedora (dnf) col tuo consenso.
- Un client MCP: Claude Desktop, Cursor, VS Code o OpenCode.
- Nessun compilatore: `pyturso` si installa dalle wheel prebuildate in
  `Neuron/vendor/` (`--find-links`), quindi non compila nulla da sorgente.

## 1. Click-and-go (consigliato)

L'installer dell'intera suite sta nella cartella `gray_matter` e installa Gray
Matter più i peer presenti accanto (Neuron, NeuRAG) in **un unico venv
condiviso**, li registra nei client MCP e apre il control center.

**Windows** — doppio clic su `gray_matter\install.cmd` (o eseguilo):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\gray_matter\install.ps1
```

**macOS / Linux** — doppio clic su `gray_matter/install.command`, oppure:

```sh
sh gray_matter/install.sh
```

Non interattivo (CI / script):

```sh
sh gray_matter/install.sh --yes
```

Per escludere un peer: `GM_NO_NEURON=1` oppure `GM_NO_NEURAG=1` prima del comando.

## 2. Verifica

```sh
gray-matter doctor
```

Poi, dal client AI, chiama `gray_matter_pulse(topic="ciao")`. Un solo elemento
MCP (Gray Matter) espone tutti i tool di Neuron + NeuRAG.

## 3. Standalone (un singolo componente)

Gray Matter è **raccomandato, non obbligatorio**. `Neuron/install.sh` o
`Neurag/install.sh` (e i gemelli `.ps1`) mostrano un **selettore di modalità**:

```
  Installation mode:
    [F] Full suite — GM + Neuron + NeuRAG (consigliato)
    [N] Solo Neuron — standalone (si registra direttamente nei client)
    [D] Dettagli — cosa perdi senza GM

  Scelta [F]:
```

Premi **Invio** per il default (Full suite). Scegli **N** per la modalità
standalone — il tool si installa nel proprio venv e si registra direttamente
nei client MCP. Senza GM perdi solo i collegamenti cross-store (bridge) e
l'auto-surface dei vicini; mantieni memoria, knowledge e tutti gli stimoli nativi.

Headless / CI: passa `--no-gm` o imposta `GM_OPTIN=0` per saltare il selettore
e installare standalone. Se GM non è ottenibile (offline), l'installer degrada
a standalone invece di uscire. Ri-esegui in qualsiasi momento: GM riprende il
comando (gateway + bridge).

Ogni tool gira anche da solo da PyPI, senza gateway:

```sh
# Solo Neuron — memoria semantica
pip install neuron
neuron register

# Solo NeuRAG — knowledge base
pip install neurag
neurag-mcp
```

## 4. Installazione manuale (qualsiasi OS, da wheel)

```sh
# 1. Crea e attiva un venv
python -m venv .venv
# Windows:     .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate

# 2a. Linux/macOS — le wheel di pyturso sono su PyPI, funziona diretto:
pip install neuron neurag gray-matter

# 2b. Windows — punta pip alle wheel vendored di pyturso così non compila:
pip install --find-links Neuron/vendor neuron neurag gray-matter

# 3. Registra il gateway
gray-matter register --gateway
```

`register --gateway` registra solo Gray Matter ed espelle eventuali voci
standalone di Neuron/NeuRAG dai config dei client (backup salvati come `.bak`).

## 5. Aggiornamento

Ri-esegui l'installer click-and-go (passo 1). Riusa il venv condiviso e
ri-registra i client in modo idempotente.

## 6. Disinstallazione

```sh
gray-matter uninstall            # solo app: venv, dipendenze, de-registrazione client
gray-matter uninstall --dry-run  # anteprima di un wipe completo, non cambia nulla
gray-matter uninstall --purge-data --yes   # anche grafo memoria + vault NeuRAG + segreti .env
```

La memoria (grafo, vault, bridge) non viene mai cancellata senza `--purge-data`.

## 7. Risoluzione problemi

- **`pip` prova a compilare pyturso / "Microsoft Visual C++ required" (Windows):**
  hai saltato le wheel vendored. Ri-esegui con `--find-links Neuron/vendor`.
- **La wheel `pyturso` non combacia col mio Python:** le wheel vendored coprono
  cp310–cp314 su `win_amd64`. Usa Python 3.10–3.14, oppure installa su
  Linux/macOS dove PyPI serve le wheel giuste.
- **`ModuleNotFoundError: fastembed` / `mcp`:** il venv è incompleto — ri-esegui
  l'installer, o `pip install -e .` in ogni repo.
- **Il client non vede i tool:** verifica che il daemon sia su
  (`gray-matter status`) e che il client sia stato riavviato dopo la registrazione.

Per la matrice per-componente completa (memoria cloud/Turso, seed DB,
registrazione sui sei client) vedi [`Neuron/INSTALL.md`](../Neuron/INSTALL.md).

---

## Prossimi passi

- [Getting started](GETTING-STARTED.it.md) — tutorial end-to-end (10 min)
- [Configurazione](CONFIGURATION.it.md) — variabili d'ambiente e tier
- [Risoluzione problemi](TROUBLESHOOTING.it.md) — sintomo → diagnosi → fix
