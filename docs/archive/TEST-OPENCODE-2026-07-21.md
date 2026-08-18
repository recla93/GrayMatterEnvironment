# Test plan for OpenCode — verifica locale intensa (2026-07-21)

> Verdetto autoritativo dei cambiamenti del 2026-07-21. Gira **in locale** (rete +
> pyturso + fastembed + mcp + Turso reali), come da `ENVIRONMENT.md`. PowerShell su
> Windows. `<...>` = da sostituire. Ogni blocco ha l'output atteso.
>
> Cosa si valida qui e NON si poteva nel sandbox: tier Turso locale/cloud, race L2
> multi-processo, build wheel, `doctor`, flow installer, versioni a runtime.

---

## 0. Prereq
- Python 3.10–3.13 (`py -0` per elencarli), Rust + MSVC Build Tools (per buildare pyturso), git.
- Radice: `cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment"`

## 1. Toolchain test offline (D1) — chiude il gap vendor/dev su 3.10
```powershell
cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment"
py -3.10 -m pip download exceptiongroup tomli -d Neuron\vendor\dev
# atteso: scarica exceptiongroup-*.whl e tomli-*.whl in Neuron\vendor\dev
```

## 2. Venv di test condiviso (modello gateway) + editable install
```powershell
cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment"
py -3.12 -m venv .venv-test
.\.venv-test\Scripts\Activate.ps1
python -m pip install --upgrade pip

# Neuron: pyturso dalle wheel vendored (niente compile), + dev + cloud
pip install -e ".\Neuron[dev,cloud]" --find-links .\Neuron\vendor
# NeuRAG: vendor PROPRIO per turso, + semantic (fastembed) + cloud + dev
pip install -e ".\Neurag[dev,turso,cloud,semantic]" --find-links .\Neurag\vendor --find-links .\Neuron\vendor
# Gray Matter
pip install -e ".\gray_matter[dev,gui]"
```
> Se `pip install -e ".\Neurag[...]"` lamenta le wheel: builda prima (sezione 8) o togli `turso` per il giro base.

## 3. Versioni a runtime (bug corretto: __init__ vs __version__.py)
```powershell
python -c "import neuron, neurag, gray_matter; print(neuron.__version__, neurag.__version__, gray_matter.__version__)"
# atteso ESATTO: 6.0.0 1.0.0 1.0.0
python -c "import neurag.__version__ as v; print(v.__version__)"   # re-export -> 1.0.0
```

## 4. Suite complete (deps reali) — una per repo (tier pulito)
```powershell
python -m pytest .\Neuron\tests -q
# atteso: 272 passed (i test a stub girano su sqlite; gli altri su deps reali)
python -m pytest .\Neurag\tests -q
# atteso: 36 passed (con pyturso: test_vector_sql NON skippa -> tier turso locale reale)
python -m pytest .\gray_matter\tests -q
# atteso: 38 passed (i 2 test mcp NON skippano piu: mcp installato)
```
> In sandbox erano 272 / 34(+2 skip) / 35(+3 skip): in locale gli skip diventano PASS
> perche pyturso/mcp ci sono. Se un "ex-skip" fallisce -> è un caso reale da guardare.

## 5. Test mirati ai cambiamenti di oggi
```powershell
python -m pytest .\Neuron\tests\test_l2_open_guard.py -q      # L2 guard (2)
python -m pytest .\Neurag\tests\test_node_links.py -q         # search_with_links enrich-only
python -m pytest .\Neurag\tests\test_cloud_turso.py -q        # facade cloud (4)
python -m pytest .\Neurag\tests\test_vector_sql.py -q         # tier turso locale REALE
```

## 6. doctor per tutti e 3
```powershell
neurag doctor
# atteso: NeuRAG v1.0.0 / engine: Turso (local) [se pyturso] / embedder: fastembed / vault: OK
neuron doctor                 # diagnosi registrazioni client
gray-matter doctor            # runtime gateway (serve il daemon su, vedi sez.7)
```

## 7. Gateway + registrazione + status live
```powershell
# installa il gateway (register + hooks + manifest) e avvia
python -m gray_matter.cli install
python -m gray_matter.cli status
# atteso: Gray-Matter v1.0.0 (NON piu v0.1.0), servers: neuron (+ neurag se attivo)
python -m gray_matter.cli doctor
```

## 8. Build wheel NeuRAG (decoupling) — serve Rust+MSVC
```powershell
cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment\Neurag\vendor"
python -m pip wheel "pyturso==0.6.1" --no-deps --find-links . -w .
# atteso: pyturso-0.6.1-cp3XX-cp3XX-win_amd64.whl creata qui (XX = tua minor)
Get-ChildItem *.whl
cd "$env:USERPROFILE\Desktop\Gray Matter Enviroment"
```

## 9. Turso CLOUD (CORE-1) — il pezzo non testabile in sandbox
> **Architettura:** Neuron e NeuRAG hanno DB **separati** (Neuron `graph_*.db`,
> NeuRAG `knowledge.db`) — anche su cloud sono due database distinti. È **GM** che
> li connette via bridge. Qui si verifica solo che **ciascuno** salga sul suo cloud.
> **DUE DB distinti = DUE URL.** Neuron legge `TURSO_DATABASE_URL`; NeuRAG legge
> `NEURAG_TURSO_DATABASE_URL` (mai lo stesso: entrambi hanno una tabella `nodes` con
> schema diverso). Il token può essere condiviso (org/group): NeuRAG usa
> `NEURAG_TURSO_AUTH_TOKEN` se presente, altrimenti fallback a `TURSO_AUTH_TOKEN`.
```powershell
# Neuron -> DB "neuron"
$env:TURSO_DATABASE_URL        = "libsql://<db-neuron>.turso.io"
$env:TURSO_AUTH_TOKEN          = "<token>"
# NeuRAG -> DB SEPARATO "neurag"
$env:NEURAG_TURSO_DATABASE_URL = "libsql://<db-neurag>.turso.io"
# (NEURAG_TURSO_AUTH_TOKEN opzionale; senza, riusa TURSO_AUTH_TOKEN)

# Neuron sale sul suo cloud
python -c "import neuron.db as d; print(d.ENGINE_NAME, d.REMOTE_TURSO)"
# atteso: Turso (cloud) True

# NeuRAG sale sul SUO cloud (DB diverso)
python -c "from neurag.db import KnowledgeGraph as K; print(K().status()['engine'])"
# atteso: Turso (cloud)
neurag doctor      # -> turso: cloud configured (NEURAG_TURSO_DATABASE_URL)

# scrittura+lettura reale su NeuRAG cloud (facade libsql-client)
python -c "from neurag.db import KnowledgeGraph as K; kg=K(); n=kg.add_node('CloudTest','godnode',parent_id=0); kg.add_chunk(n,'hello cloud',source='t.md'); print(kg.search('hello',3))"
# atteso: 1 risultato, nessuna eccezione

# pulizia env quando finito
Remove-Item Env:TURSO_DATABASE_URL, Env:TURSO_AUTH_TOKEN, Env:NEURAG_TURSO_DATABASE_URL -ErrorAction SilentlyContinue
```

## 10. L2 sotto concorrenza REALE (il residuo da chiudere)
Riproduci il pattern del bug: piu worker/daemon sullo STESSO `graph_*.db` locale, uno
`store_turn` che fa switch di contesto. Con pyturso installato e TURSO_* NON settate:
```powershell
$env:NS_GRAPHS_DIR = "$env:TEMP\l2test"; Remove-Item $env:NS_GRAPHS_DIR -Recurse -Force -ErrorAction SilentlyContinue
# 2+ processi in parallelo che scrivono sullo stesso store, con switch di contesto
1..3 | ForEach-Object {
  Start-Process -NoNewWindow python -ArgumentList @(
    "-c", "import os,neuron.server as s; [s._g.switch(f'dom{i}') or s._g.get().add_node.__self__ for i in range(20)]"
  )
}
# Meglio: guidalo via i tool MCP reali (pre_turn/store_turn) da 2 client Desktop+Cowork
# aperti insieme, alternando domini per forzare lo switch (dom signal 2/2).
# atteso: nessun 'open: NotFound'. Se compare -> la guardia _open_local_engine ha
# loggato 'degrading to sqlite3' (grep stderr): in quel caso la scrittura è passata
# comunque -> mitigazione OK; se invece crasha -> serve il file-lock cross-processo.
Remove-Item Env:NS_GRAPHS_DIR
```
> Il modo piu fedele resta: Claude Desktop (chat+host) + Cowork aperti insieme sullo
> stesso store, alternando argomenti di domini diversi per far scattare lo switch.

## 11. Flow installer — fallback e recovery
```powershell
# path locale (GM presente come sibling): il launcher deve delegare a GM
.\Neurag\install.ps1 -WhatIf 2>$null; .\Neuron\install.ps1   # osserva "Installing ..."
# fallback: nascondi GM e verifica il messaggio di bootstrap/recovery (no crash muto)
Rename-Item .\gray_matter .\gray_matter_hidden
.\Neurag\install.ps1        # atteso: prova locale->GitHub->PyPI, poi messaggio guida (pre-publish)
Rename-Item .\gray_matter_hidden .\gray_matter
```

## 12. Verifiche statiche installer (sintassi)
```powershell
# PowerShell: parse senza eseguire
foreach ($f in ".\gray_matter\install.ps1", ".\Neuron\install.ps1", ".\Neurag\install.ps1") {
  [System.Management.Automation.PSParser]::Tokenize((Get-Content $f -Raw), [ref]$null) | Out-Null
  "OK  $f"
}
```

## 13. Solo dopo TUTTO verde — git (rimandato per tua scelta)
```powershell
# per ogni repo: commit + tag della release
foreach ($r in "Neuron","Neurag","gray_matter") {
  Push-Location $r
  git add -A
  git commit -m "release: v<...> — polish, decoupling NeuRAG cloud, L2 guard, doctor, installer flow"
  Pop-Location
}
git -C Neuron      tag v6.0.0
git -C Neurag      tag v1.0.0
git -C gray_matter tag v1.0.0
# push (attiva i workflow release.yml -> build wheel + Release):
#   git -C <repo> push origin <branch> --tags
```

---

### Checklist di accettazione
- [ ] `6.0.0 1.0.0 1.0.0` a runtime (sez.3)
- [ ] 3 suite verdi con deps reali; ex-skip ora PASS (sez.4)
- [ ] `test_vector_sql` gira sul tier turso locale, non skip (sez.5)
- [ ] `neurag/neuron/gray-matter doctor` ok; status GM dice v1.0.0 (sez.6-7)
- [ ] wheel NeuRAG buildata (sez.8)
- [ ] NeuRAG **e** Neuron salgono su `Turso (cloud)` — ognuno sul PROPRIO DB (sez.9)
- [ ] nessun `open: NotFound` sotto concorrenza, o degrade loggato (sez.10)
- [ ] installer: delega locale ok + fallback non muto (sez.11)
