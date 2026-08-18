# HANDOFF — Gray Matter / Neuron — 2026-07-18

> Per: Fable (in code). Stato + TODO + il problema runtime aperto.
> SSOT: `GRAY-MATTER-COMPENDIUM.md` (§0 = handoff/TODO), `INSTALLER-UX.md`,
> `ARCHITETTURA.md`, `ENVIRONMENT.md`.

## Stack
Tre server MCP: **Neuron** (memoria semantica a grafo, Turso), **NeuRAG** (knowledge
base), **Gray-Matter/GM** (orchestratore + proxy). Repo root:
`C:\Users\recla\Desktop\Gray Matter Enviroment` — 3 repo git separati
(`Neuron`, `gray_matter`, `neurag`).
Regole ambiente: git solo in locale; un fix in sandbox NON è "verde" finché non
gira in locale. Neuron è installato **editable** sia in `C:\Python314` sia in
`...\Programs\neuron5\.venv`.

## Fatto oggi (codice — compila + test isolati verdi; da confermare con pytest locale + commit)
- **GM**: A4 (`stats`/`doctor` + fix `ContextCache` singleton), D2 (worker prewarm),
  F4 (ingest-validation bridge), cache multi-topic + invalidazione post `store_turn`
  + validazione topic in `pulse`, **F12** (schemi reali pass-through via worker
  `list_tools` — **verificato locale**: `store_turn 11 args`, ecc.), `settings.py`
  + `gray-matter config get|set|list` + `server.py` legge 5 knob da config,
  `paths.py`/`Manifest`, `installer.py`/`uninstaller.py` (cervelli puri),
  **gateway self-bootstrap** (registry `managed` + `_bootstrap_subservers`),
  fix worker `CREATE_NO_WINDOW` (Windows).
- **Neuron**: G3 `project.py` (marker `.neuron/project.json`, path relativi POSIX,
  provenance `by`), G1 (refs canonicalizzati in `store_turn` + riga `files:` in
  `pre_turn`). ~38 test verdi sui nuovi moduli.

## TODO codice (ordine)
1. **Verifica locale (bloccante)**: `pytest gray_matter/tests`, `pytest Neuron/tests`
   (+ `tests/test_project.py`); poi **commit** repo `Neuron` e `gray_matter`.
2. **Flip gateway**: client → **solo GM**; Neuron con `NEURON_NO_GM=1`; GM tiene i
   worker (self-bootstrap già codato). Manca la CLI `gray-matter register --gateway`
   (registra SOLO `gray_matter` + **deregistra** neuron/neurag dai client).
3. **Singleton su `_spawn_gray_matter`** (evita GM daemon duplicati in race).
4. Neuron **G2** (tabella `refs` strutturata anti-clobber) + **trust B1–B3**
   (`confirm(confidence)`, `Node.trust`, trust nel ranking) — dipendono da **L1**
   (UPDATE atomici, concorrenza Fase 2).
5. Deploy hook/plugin dentro l'installer GM; GM serve le `instructions`.

## PROBLEMA RUNTIME APERTO (motivo dell'handoff)
**Sintomo:** all'avvio di Claude Desktop compaiono **2 finestre CMD** e
`neuron doctor` dice *"claude.exe spawned 2 Neuron servers — duplicate keys"*.

**Cosa NON è (escluso):**
- NON è duplicazione di config. Il config MSIX che Claude usa davvero
  (`...\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json`)
  ha **una sola** voce `neuron5`. Anche il config APPDATA = solo `neuron5`.
- NON sono i worker di GM (`NEURON_NO_GM=1` attivo → GM non parte; nessun
  `gray_matter._worker` nei processi).
- Il child-spawn per-server (`neuron → neuron`, i pid figli) è **by design**:
  `neuron doctor` marca i figli **[ok]**. Ipotesi: `bridge.py` / cloud Turso.

**Cosa È (ipotesi da verificare):** una **singola** app Claude spawna **2** server
Neuron da **1 sola** entry di config. Probabile causa: Claude Desktop istanzia il
server MCP due volte — un contesto per la **chat** e uno per **Cowork/local-agent
mode** (la sessione gira in Cowork). Il messaggio "duplicate keys" del doctor è
un'euristica **fuorviante** in questo caso (fa quel warning ogni volta che vede 2
server da 1 app).

**Residuo innocuo:** Codex CLI `neuron5` → `C:\Python314` (config TOML, `doctor
--fix` non lo riscrive; ma `C:\Python314` ha lo **stesso** editable del repo →
funzionalmente identico).

**Albero processi tipico:**
```
claude.exe → neuron(A) → neuron(A')   [A' = figlio by-design, [ok]]
claude.exe → neuron(B) → neuron(B')
```
Le 2 CMD visibili = i figli neuron (stdio in attesa di stdin, "nessun output").
Nasconderli è lato Neuron (aggiungere `CREATE_NO_WINDOW` allo spawn in `bridge.py`),
NON lato GM.

## Domande per Fable
1. Il **flip gateway** (client → solo GM, Neuron come worker gestito) risolve alla
   radice sia i doppi server sia le finestre? (GM = 1 processo, niente spawn
   multipli client-side.) È il fix strutturale proposto.
2. Vale la pena, come mitigazione **cosmetica** subito, aggiungere `CREATE_NO_WINDOW`
   allo spawn `-m neuron` in `Neuron/src/neuron/bridge.py`?
3. Perché Claude istanzia 2 volte il server da 1 entry? (verificare: chat vs
   cowork/CCD come due client MCP distinti nella stessa app.)

## Verifiche rapide utili
```
python -m neuron doctor
Get-CimInstance Win32_Process | ? { $_.CommandLine -match '-m neuron' } | Select ProcessId, ParentProcessId, CommandLine
```
