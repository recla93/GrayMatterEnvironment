"""Cosa c'e' gia' su questa macchina, e se e' allineato.

L'installer sovrascriveva e sperava. Non guardava se esistessero altre
installazioni, se i tre pacchetti fossero della stessa generazione, se i client
puntassero all'interprete che stiamo per usare o a uno morto. Il risultato lo
si scopriva molto dopo, come `spawn ... python.exe ENOENT` o come una GUI che
dice "nessun tool installato".

`scan()` e' PURO: guarda e riferisce, non tocca niente. Le azioni che ne
derivano sono separate (`fixes()`), perche' su un'installazione altrui la cosa
giusta e' quasi sempre dirlo, non deciderlo.

Le tre domande, nell'ordine in cui contano:

1. **Dove sono i venv?** Ce ne sono tre posizioni storiche. Piu' di uno vivo
   significa che qualcosa gira dal posto sbagliato.
2. **I pacchetti sono allineati?** gray-matter, neuron e neurag installati nello
   stesso venv ma da sorgenti diverse producono errori che sembrano casuali.
3. **I client puntano dove installiamo?** E' l'unico controllo che avrebbe preso
   l'ENOENT prima dell'utente.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from gray_matter import paths

TOOLS = ("gray-matter", "neuron", "neurag")


def venv_candidates() -> list[Path]:
    """Le posizioni in cui un venv della suite puo' trovarsi, nuova per prima."""
    base = paths._os_base()
    return [
        paths._user_base() / "graymatter" / ".venv",     # attuale (radice suite)
        base / "graymatter" / ".venv",                   # pre-suite
        base / "gray-matter" / ".venv",                  # ancora prima
        paths._user_base() / "neuron" / ".venv",         # standalone Neuron
        paths._user_base() / "neurag" / ".venv",         # standalone NeuRAG
        base / "neuron" / ".venv",
        base / "neurag" / ".venv",
    ]


def _python_of(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _is_standalone_python(python: str) -> bool:
    """True se l'interprete appartiene a un venv standalone di Neuron/NeuRAG
    (layout attuale o storico): registrazioni volutamente dirette."""
    s = python.replace("\\", "/").lower()
    return any(seg in s for seg in (
        "/neuron/.venv/", "/neurag/.venv/",
        "/programs/neuron/.venv/", "/programs/neurag/.venv/",
    ))


def _versions(python: Path) -> dict:
    """Versioni dei tre pacchetti in QUEL venv. {} se l'interprete non parte."""
    code = (
        "import json\n"
        "from importlib.metadata import version, PackageNotFoundError\n"
        "out = {}\n"
        "for n in ('gray-matter', 'neuron', 'neurag'):\n"
        "    try: out[n] = version(n)\n"
        "    except PackageNotFoundError: pass\n"
        "print(json.dumps(out))\n"
    )
    try:
        r = subprocess.run([str(python), "-c", code], capture_output=True,
                           text=True, timeout=60)
        if r.returncode != 0:
            return {}
        return json.loads((r.stdout or "{}").strip().splitlines()[-1])
    except Exception:  # noqa: BLE001 — interprete rotto = nessuna versione
        return {}


def source_versions() -> dict:
    """Versioni dichiarate nei sorgenti accanto a noi (quello che installeremmo)."""
    import re
    here = Path(__file__).resolve().parent
    out: dict[str, str] = {}
    for root in (here, here.parent):
        for d in (root, *(p for p in root.iterdir() if p.is_dir())) if root.is_dir() else ():
            toml = d / "pyproject.toml"
            if not toml.exists():
                continue
            try:
                text = toml.read_text(encoding="utf-8")
            except OSError:
                continue
            name = re.search(r'^\s*name\s*=\s*"(.+?)"', text, re.M)
            ver = re.search(r'^\s*version\s*=\s*"(.+?)"', text, re.M)
            if name and ver and name.group(1).replace("_", "-") in TOOLS:
                out.setdefault(name.group(1).replace("_", "-"), ver.group(1))
    return out


def client_interpreters() -> list[dict]:
    """Interprete registrato in ogni client, e se esiste ancora."""
    try:
        from gray_matter import clients as C
    except Exception:  # noqa: BLE001
        return []
    out = []
    for key, spec in C.CLIENTS.items():
        try:
            files = [p for p in spec["paths"]() if os.path.exists(p)]
        except Exception:  # noqa: BLE001
            continue
        for p in files:
            try:
                raw = Path(p).read_text(encoding="utf-8-sig")
            except OSError:
                continue
            if "gray-matter" not in raw:
                continue
            found = None
            for tok in raw.replace("\\\\", "\\").split('"'):
                low = tok.lower()
                if low.endswith("python.exe") or low.endswith("/bin/python"):
                    found = tok
                    break
            out.append({"client": key, "path": p, "python": found,
                        "alive": bool(found) and os.path.exists(found)})
    return out


def _venv_kind(v: Path) -> str:
    """"suite" = il venv condiviso del gateway; "standalone" = i venv propri di
    Neuron/NeuRAG installati con --no-gm. Sono legittimi in parallelo: contarli
    come 'multiple_venvs' era un falso allarme."""
    s = str(v).replace("\\", "/").lower()
    tail = s.rsplit("/", 2)[-2] if "/" in s else ""
    return "standalone" if tail in ("neuron", "neurag") else "suite"


def scan() -> dict:
    """Fotografia PURA della macchina. Non scrive niente, non decide niente."""
    venvs = []
    for v in venv_candidates():
        py = _python_of(v)
        if not py.exists():
            continue
        vers = _versions(py)
        venvs.append({"venv": str(v), "python": str(py), "versions": vers,
                      "usable": bool(vers), "kind": _venv_kind(v)})

    src = source_versions()
    clients = client_interpreters()
    # Il target è il venv che QUESTO install userà davvero. L'install.ps1 può
    # ADOTTARE un venv storico (un venv non si sposta): senza l'override qui
    # sotto il report prometteva riscritture verso il path canonico che la
    # registrazione non avrebbe mai scritto (visto in produzione, 2026-08-26).
    env_target = os.environ.get("GM_TARGET_PYTHON", "").strip()
    target = env_target or str(_python_of(paths._user_base() / "graymatter" / ".venv"))

    problems = []
    suite_live = [v for v in venvs if v["usable"] and v["kind"] == "suite"]
    if len(suite_live) > 1:
        problems.append({
            "kind": "multiple_venvs",
            "detail": f"{len(suite_live)} venv della suite vivi: " +
                      ", ".join(v["venv"] for v in suite_live),
            "fix": "usa -Clear per rifare quello corrente, poi rimuovi gli altri",
        })
    for v in (v for v in venvs if v["usable"] and v["kind"] == "suite"):
        skew = {n: (v["versions"].get(n), src.get(n))
                for n in TOOLS
                if n in v["versions"] and n in src and v["versions"][n] != src[n]}
        if skew:
            problems.append({
                "kind": "version_skew",
                "detail": f"{v['venv']}: " + ", ".join(
                    f"{n} installato {a} != sorgente {b}" for n, (a, b) in skew.items()),
                "fix": "reinstalla con -Force",
            })
        missing = [n for n in TOOLS if n in src and n not in v["versions"]]
        if missing and "gray-matter" in v["versions"]:
            problems.append({
                "kind": "incomplete_suite",
                "detail": f"{v['venv']}: manca " + ", ".join(missing),
                "fix": "rilancia l'installer: i peer mancanti vengono scaricati",
            })
    for c in clients:
        if c["python"] and not c["alive"]:
            problems.append({
                "kind": "dead_client_interpreter",
                "detail": f"{c['client']} punta a un interprete che non esiste: {c['python']}",
                "fix": "verra' riscritto dalla registrazione di questo install",
            })
        elif c["alive"] and c["python"] and target and \
                os.path.normcase(os.path.normpath(c["python"])) != \
                os.path.normcase(os.path.normpath(target)) and \
                not _is_standalone_python(c["python"]):
            # Un interprete standalone (venv proprio di Neuron/NeuRAG) e' una
            # scelta, non un disallineamento: segnalarlo come "punta altrove"
            # generava il falso allarme permanente visto col venv adottato.
            problems.append({
                "kind": "client_points_elsewhere",
                "detail": f"{c['client']} punta a {c['python']}, non a {target}",
                "fix": "verra' riscritto dalla registrazione di questo install",
            })

    return {"venvs": venvs, "source_versions": src, "clients": clients,
            "target_python": target, "problems": problems,
            "ok": not problems}


def report(state: dict | None = None) -> str:
    """Il testo che l'installer stampa. Silenzioso quando non c'e' niente da dire."""
    st = state or scan()
    if st["ok"]:
        n = len([v for v in st["venvs"] if v["usable"]])
        return "" if not n else "  [OK] installazione esistente allineata."
    lines = ["", "  Controllo dell'esistente:"]
    for p in st["problems"]:
        lines.append(f"    [!] {p['detail']}")
        lines.append(f"        -> {p['fix']}")
    return "\n".join(lines)


def main() -> int:
    st = scan()
    if "--json" in sys.argv:
        print(json.dumps(st, indent=2, ensure_ascii=False))
    else:
        out = report(st)
        if out:
            print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
