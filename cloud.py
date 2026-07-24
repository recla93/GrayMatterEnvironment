"""`gray-matter cloud` — config del gruppo Turso, CLI core (DESIGN-CLOUD-MEMORY §5).

One logic, defined once: la GUI invoca questi stessi comandi e ne streamma
l'output. Tutto idempotente e re-eseguibile:

  setup     (1) verifica `turso` CLI + login; (2) crea/rileva il gruppo;
            (3) crea/rileva un DB per componente e ne prende l'URL;
            (4) riusa il token esistente nel `.env`, altrimenti ne minta uno
            di gruppo (decisione: UN SOLO group token);
            (5) scrive le env nel `.env` GM (backup `.bak`, mai clobber di
            righe non nostre, solo se cambiano);
            (6) report doctor-like dei tier. Nessuna credenziale a stdout.
  status    che tier è ogni componente (env file + env reale).
  teardown  de-cabla SOLO le env gestite (i DB cloud non si toccano).

Casi coperti: (a) full group, (b) bring-your-own (DB/token già esistenti →
niente creazione, solo cablaggio), (c) parziale via --components.
Stdlib only; `runner` iniettabile nei test (nessun turso reale richiesto).
"""
from __future__ import annotations

import os
import shutil
import subprocess

# Windows: niente flash di console per la turso CLI (output è già catturato).
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
from pathlib import Path

# componente -> (nome DB nel gruppo, env URL). Token: un solo group token in
# TURSO_AUTH_TOKEN (fallback naturale di NEURAG_/GM_TURSO_AUTH_TOKEN).
COMPONENTS = {
    "neuron": ("neuron", "TURSO_DATABASE_URL"),
    "neurag": ("neurag", "NEURAG_TURSO_DATABASE_URL"),
    "gm": ("gm-bridges", "GM_TURSO_DATABASE_URL"),
}
TOKEN_KEY = "TURSO_AUTH_TOKEN"
MANAGED_KEYS = tuple(url for _, url in COMPONENTS.values()) + (TOKEN_KEY,)
DEFAULT_GROUP = "graymatter"


def default_env_file() -> Path:
    from gray_matter.paths import gm_home
    return gm_home() / ".env"


# --- .env editing (mai clobber di righe non nostre, backup .bak) ------------

def read_env_file(path: Path) -> dict[str, str]:
    # utf-8-sig: PowerShell 5.1 `Set-Content -Encoding utf8` scrive il BOM, che
    # altrimenti corrompe la prima chiave (audit 2026-07-21, keep-in-sync _env.py).
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            out[k.strip()] = v
    except OSError:
        pass
    return out


def update_env_file(path: Path, updates: dict[str, str],
                    remove: tuple[str, ...] = ()) -> bool:
    """Set/replace only OUR keys, drop `remove`, keep every other line intact.
    Backup `.bak` before the first byte changes. Returns True if written."""
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    out, seen = [], set()
    for line in lines:
        s = line.strip()
        key = s.split("=", 1)[0].strip() if ("=" in s and not s.startswith("#")) else None
        if key in remove:
            continue
        if key in updates:
            seen.add(key)
            out.append(f"{key}={updates[key]}")
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    new = "\n".join(out) + ("\n" if out else "")
    old = "\n".join(lines) + ("\n" if lines else "")
    if new == old:
        return False
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True


# --- turso CLI --------------------------------------------------------------
# La CLI serve SOLO a `setup` (auto-provisioning). Default: la offriamo noi
# (opt-out GM_TURSO_CLI_INSTALL=0 / --no-cli-install); chi preferisce fa da sé
# con la guida. `wire` non la richiede mai.
#
# ATTENZIONE (B4, verificato 2026-07-21 su docs + repo): la CLI cloud è quella
# CLASSICA (docs.turso.tech/cli) — brew/script su mac/linux, WSL su Windows.
# Il pacchetto NUOVO `tursodatabase/turso` v0.7.x (installer nativo Windows) è
# il database engine locale: NIENTE `auth`/`group`/`db create` → inutile per il
# setup e sul PATH farebbe ombra col nome `turso`. Su Windows quindi: WSL,
# oppure — più semplice — `cloud wire` (zero CLI).


def cli_install_argv() -> "list[str] | None":
    """Installer ufficiale della CLI cloud. None su Windows: lì non esiste un
    installer nativo (serve WSL) → il chiamante mostra la guida."""
    if os.name == "nt":
        return None
    return ["sh", "-c", "curl -sSfL https://get.tur.so/install.sh | bash"]


CLI_GUIDE = [
    "Installazione turso CLI (quella CLOUD — docs.turso.tech/cli):",
    "  macOS   : brew install tursodatabase/tap/turso",
    "  linux   : curl -sSfL https://get.tur.so/install.sh | bash",
    "  Windows : richiede WSL — dentro `wsl`: curl -sSfL https://get.tur.so/install.sh | bash",
    "  docs    : https://docs.turso.tech/cli/installation",
    "NB: il pacchetto `tursodatabase/turso` v0.7.x (installer nativo Windows) è il",
    "    database locale, NON la CLI cloud: non può creare gruppi/DB/token.",
    "Poi: `turso auth login` e ri-esegui `gray-matter cloud setup`.",
    "Niente CLI? `gray-matter cloud wire` cabla URL/token dal dashboard, zero requisiti.",
]


def install_cli(stream=None) -> bool:
    """Esegue l'installer ufficiale (consenso già raccolto dal chiamante).
    `stream(line)` opzionale per l'output. True = turso ora sul PATH.
    Su Windows non c'è installer nativo: guida e False."""
    argv = cli_install_argv()
    if argv is None:
        for ln in CLI_GUIDE:
            (stream or print)(ln)
        return False
    (stream or print)("$ " + " ".join(argv))
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300,
                           encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        for ln in ((r.stdout or "") + (r.stderr or "")).splitlines():
            (stream or print)(ln)
    except Exception as exc:  # noqa: BLE001
        (stream or print)(f"[!!] installer fallito: {exc}")
        return False
    return shutil.which("turso") is not None


def _default_runner(args: list[str]) -> tuple[int, str]:
    try:
        r = subprocess.run(["turso", *args], capture_output=True, text=True,
                           timeout=120, encoding="utf-8", errors="replace",
                           creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, "turso CLI not found"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _first_word_column(out: str) -> list[str]:
    """Names from a turso table listing (first column, header skipped)."""
    names = []
    for i, line in enumerate(out.splitlines()):
        parts = line.split()
        if not parts or (i == 0 and parts[0].upper() == "NAME"):
            continue
        names.append(parts[0])
    return names


def _db_url(name: str, run) -> str:
    rc, out = run(["db", "show", name, "--url"])
    if rc == 0:
        for tok in out.split():
            if tok.startswith("libsql://") or tok.startswith("https://"):
                return tok.strip()
    return ""


def _mint_group_token(group: str, run) -> str:
    """Un solo group token — `turso group tokens create <group>` (B4: confermato
    dalle docs ufficiali; `mint` non esiste)."""
    rc, out = run(["group", "tokens", "create", group])
    if rc == 0 and out.strip():
        return out.split()[-1].strip()
    return ""


# --- comandi ----------------------------------------------------------------

def setup(group: str = DEFAULT_GROUP, components: list[str] | None = None,
          env_file: Path | None = None, runner=None) -> list[str]:
    """Idempotent setup. Returns report lines (no credentials)."""
    run = runner or _default_runner
    env_file = env_file or default_env_file()
    comps = [c for c in (components or list(COMPONENTS)) if c in COMPONENTS]
    lines: list[str] = []
    if not comps:
        return [f"[!!] nessun componente valido (scegli tra: {', '.join(COMPONENTS)})"]

    # (1) CLI + login
    rc, out = run(["auth", "whoami"])
    if rc == 127:
        return ["[!!] turso CLI non trovata.", *CLI_GUIDE]
    if rc != 0:
        low = out.lower()
        if any(k in low for k in ("unrecognized", "unknown", "unexpected", "invalid")):
            # `turso` sul PATH ma senza comandi cloud = è il database locale v0.7.x
            return ["[!!] il `turso` sul PATH è il database locale (tursodatabase/turso "
                    "v0.7.x), NON la CLI cloud — non può creare gruppi/DB/token.",
                    *CLI_GUIDE]
        return ["[!!] non autenticato su Turso — esegui `turso auth login` e riprova."]
    lines.append(f"[ok] turso CLI: login come {out.strip().splitlines()[-1] if out.strip() else '?'}")

    # (2) gruppo: rileva, non ricreare
    rc, out = run(["group", "list"])
    groups = _first_word_column(out) if rc == 0 else []
    if group in groups:
        lines.append(f"[ok] gruppo '{group}' esistente (riusato)")
    else:
        rc, out = run(["group", "create", group])
        if rc != 0:
            return lines + [f"[!!] creazione gruppo '{group}' fallita: {out.strip()}"]
        lines.append(f"[ok] gruppo '{group}' creato")

    # (3) DB per componente: rileva/crea + URL
    rc, out = run(["db", "list"])
    existing = _first_word_column(out) if rc == 0 else []
    updates: dict[str, str] = {}
    saved = read_env_file(env_file)
    for comp in comps:
        db, url_key = COMPONENTS[comp]
        if db in existing:
            lines.append(f"[ok] db '{db}' ({comp}) esistente (riusato)")
        else:
            rc, out = run(["db", "create", db, "--group", group])
            if rc != 0:
                lines.append(f"[!!] creazione db '{db}' ({comp}) fallita: {out.strip()}")
                continue
            lines.append(f"[ok] db '{db}' ({comp}) creato nel gruppo '{group}'")
        url = _db_url(db, run)
        if not url:
            lines.append(f"[!!] URL di '{db}' non ottenuto (turso db show {db} --url)")
            continue
        if saved.get(url_key) != url:
            updates[url_key] = url

    # (4) token: riusa quello già cablato (idempotenza), altrimenti minta
    if not (saved.get(TOKEN_KEY) or os.environ.get(TOKEN_KEY, "").strip()):
        token = _mint_group_token(group, run)
        if token:
            updates[TOKEN_KEY] = token
            lines.append(f"[ok] group token mintato per '{group}' (scritto solo nel .env)")
        else:
            lines.append("[!!] mint del group token fallito — cabla TURSO_AUTH_TOKEN a mano nel .env")
    else:
        lines.append("[ok] token esistente riusato (nessun nuovo mint)")

    # (5) scrivi solo se cambia qualcosa
    if updates:
        changed = update_env_file(env_file, updates)
        lines.append(f"[ok] {env_file}: {'aggiornate ' + ', '.join(sorted(updates)) if changed else 'invariato'}")
    else:
        lines.append(f"[ok] {env_file}: già cablato, nessuna modifica")

    # (6) report tier
    lines.append("")
    lines.extend(status(env_file=env_file))
    lines.append("Riavvia Gray-Matter (`gray-matter stop && gray-matter start`) per applicare.")
    return lines


def wire(urls: dict[str, str], token: str = "",
         env_file: Path | None = None, probe=None) -> list[str]:
    """Bring-your-own SENZA turso CLI: l'utente incolla URL (e token) dal
    dashboard Turso e qui si cablano solo le env — nessuna creazione, nessun
    requisito di CLI/login. Parziale per natura: cabla solo i componenti passati.
    `probe(url, token) -> (ok, scheme, detail)` opzionale (best-effort: si prova
    quello di Neuron se installato). Nessuna credenziale in output."""
    env_file = env_file or default_env_file()
    updates: dict[str, str] = {}
    lines: list[str] = []
    for comp, url in urls.items():
        if comp not in COMPONENTS or not url.strip():
            continue
        url = url.strip()
        if not (url.startswith("libsql://") or url.startswith("https://")):
            lines.append(f"[!!] {comp}: URL non valida ({url[:40]}…) — attesa libsql://… o https://…")
            continue
        updates[COMPONENTS[comp][1]] = url
        lines.append(f"[ok] {comp}: URL cablata")
    token = (token or "").strip()
    saved = read_env_file(env_file)
    # Token scritto SOLO se ancorato a una URL: nuova (updates) o già cablata nel
    # .env (rotazione token). Mai orfano (fix audit OpenCode, invariante conservato).
    if token:
        if updates:
            updates[TOKEN_KEY] = token
            lines.append("[ok] token cablato (scritto solo nel .env)")
        elif any(saved.get(k) for _, k in COMPONENTS.values()):
            updates[TOKEN_KEY] = token
            lines.append("[ok] token ruotato (URL già cablate nel .env)")
    if not updates:
        return lines or ["[!!] niente da cablare: passa almeno una URL (neuron/neurag/gm)"]

    # probe best-effort: verifica una URL col token effettivo prima di salvare
    if probe is None:
        try:
            from neuron.connect import probe_connection as probe  # type: ignore
        except Exception:  # noqa: BLE001 — Neuron assente: si salva senza probe
            probe = None
    eff_token = token or os.environ.get(TOKEN_KEY, "").strip() \
        or read_env_file(env_file).get(TOKEN_KEY, "")
    if probe is not None and eff_token:
        test_url = next((u for k, u in updates.items() if k != TOKEN_KEY), "") \
            or next((saved[k] for _, k in COMPONENTS.values() if saved.get(k)), "")
        if test_url:
            try:
                ok, scheme, detail = probe(test_url, eff_token)
                lines.append(f"[{'ok' if ok else '!!'}] probe: "
                             f"{'verified via ' + scheme if ok else detail or 'failed'}")
                if not ok:
                    lines.append("[!!] niente scritto — correggi URL/token e riprova.")
                    return lines
            except Exception as exc:  # noqa: BLE001
                lines.append(f"[??] probe non riuscito ({exc}) — salvo comunque.")
    elif not eff_token:
        lines.append("[??] nessun token (né passato, né in env/.env): le URL da sole "
                     "non bastano per il tier cloud.")

    changed = update_env_file(env_file, updates)
    lines.append(f"[ok] {env_file}: {'aggiornato' if changed else 'invariato'}")
    lines.append("")
    lines.extend(status(env_file=env_file))
    lines.append("Riavvia Gray-Matter (`gray-matter stop && gray-matter start`) per applicare.")
    return lines


def status(env_file: Path | None = None) -> list[str]:
    """Tier per componente: env reale > .env GM. Nessuna credenziale in output."""
    env_file = env_file or default_env_file()
    saved = read_env_file(env_file)

    def _get(key: str) -> str:
        return os.environ.get(key, "").strip() or saved.get(key, "")

    lines = [f"Cloud status (.env: {env_file}{'' if env_file.exists() else ' — assente'})"]
    token = _get(TOKEN_KEY)
    for comp, (db, url_key) in COMPONENTS.items():
        url = _get(url_key)
        comp_token = token or _get({"neurag": "NEURAG_TURSO_AUTH_TOKEN",
                                    "gm": "GM_TURSO_AUTH_TOKEN"}.get(comp, TOKEN_KEY))
        if url and comp_token:
            lines.append(f"  [cloud] {comp:6} -> {url_key} impostata (db '{db}')")
        elif url:
            lines.append(f"  [!!]    {comp:6} -> URL impostata ma token mancante ({TOKEN_KEY})")
        else:
            lines.append(f"  [local] {comp:6} -> nessuna env cloud (tier locale)")
    return lines


def teardown(env_file: Path | None = None) -> list[str]:
    """De-cabla SOLO le env gestite dal setup. I DB cloud restano intatti."""
    env_file = env_file or default_env_file()
    saved = read_env_file(env_file)
    present = tuple(k for k in MANAGED_KEYS if k in saved)
    if not present:
        return [f"[ok] {env_file}: nessuna env cloud gestita da rimuovere"]
    update_env_file(env_file, {}, remove=present)
    return [f"[ok] {env_file}: rimosse {', '.join(present)} (backup .bak; i DB cloud NON sono stati toccati)",
            "Riavvia Gray-Matter per tornare al tier locale."]
