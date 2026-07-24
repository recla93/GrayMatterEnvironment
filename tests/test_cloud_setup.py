"""`gray-matter cloud` — setup idempotente, .env mai clobberato, teardown soft."""
from pathlib import Path

from gray_matter import cloud


class FakeTurso:
    """Runner finto: simula gruppi/DB esistenti e registra le chiamate."""

    def __init__(self, groups=(), dbs=(), logged_in=True):
        self.groups, self.dbs = list(groups), list(dbs)
        self.logged_in = logged_in
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        cmd = " ".join(args[:3])
        if args[:2] == ["auth", "whoami"]:
            return (0, "utente@example.com") if self.logged_in else (1, "not logged in")
        if args[:2] == ["group", "list"]:
            return 0, "NAME\n" + "\n".join(self.groups)
        if args[:2] == ["group", "create"]:
            self.groups.append(args[2]); return 0, "created"
        if args[:2] == ["db", "list"]:
            return 0, "NAME\n" + "\n".join(self.dbs)
        if args[:2] == ["db", "create"]:
            self.dbs.append(args[2]); return 0, "created"
        if args[:2] == ["db", "show"]:
            return 0, f"libsql://{args[2]}-org.turso.io"
        if cmd == "group tokens create":     # B4: la sottocomando reale (docs)
            return 0, "tok_secret_abc"
        return 1, f"unknown: {args}"


def test_full_setup_writes_env_idempotent(tmp_path, monkeypatch):
    for k in cloud.MANAGED_KEYS:
        monkeypatch.delenv(k, raising=False)
    envf = tmp_path / ".env"
    envf.write_text("ALTRA_RIGA=intatta\n", encoding="utf-8")
    fake = FakeTurso()
    lines = cloud.setup(env_file=envf, runner=fake)
    assert not any(ln.startswith("[!!]") for ln in lines)
    saved = cloud.read_env_file(envf)
    assert saved["ALTRA_RIGA"] == "intatta"                       # mai clobber
    assert saved["TURSO_DATABASE_URL"] == "libsql://neuron-org.turso.io"
    assert saved["NEURAG_TURSO_DATABASE_URL"] == "libsql://neurag-org.turso.io"
    assert saved["GM_TURSO_DATABASE_URL"] == "libsql://gm-bridges-org.turso.io"
    assert saved["TURSO_AUTH_TOKEN"] == "tok_secret_abc"
    assert not any("tok_secret_abc" in ln for ln in lines)        # mai a stdout
    # re-run: rileva tutto, non ricrea, non ri-minta, .env invariato
    fake2 = FakeTurso(groups=fake.groups, dbs=fake.dbs)
    before = envf.read_text(encoding="utf-8")
    lines2 = cloud.setup(env_file=envf, runner=fake2)
    assert not any(ln.startswith("[!!]") for ln in lines2)
    assert envf.read_text(encoding="utf-8") == before
    assert not any(c[:2] in (["group", "create"], ["db", "create"]) for c in fake2.calls)
    assert not any(c[:2] == ["group", "tokens"] for c in fake2.calls)


def test_partial_components_and_not_logged_in(tmp_path, monkeypatch):
    for k in cloud.MANAGED_KEYS:
        monkeypatch.delenv(k, raising=False)
    envf = tmp_path / ".env"
    lines = cloud.setup(components=["neurag"], env_file=envf, runner=FakeTurso())
    saved = cloud.read_env_file(envf)
    assert "NEURAG_TURSO_DATABASE_URL" in saved
    assert "TURSO_DATABASE_URL" not in saved                      # parziale (c)
    out = cloud.setup(env_file=envf, runner=FakeTurso(logged_in=False))
    assert out[0].startswith("[!!]") and "auth login" in out[0]


def test_cli_install_argv_and_guide():
    argv = cloud.cli_install_argv()
    if __import__("os").name == "nt":
        assert argv is None            # niente installer nativo della CLI cloud
    else:
        assert argv[0] == "sh" and "get.tur.so" in argv[-1]
    guide = "\n".join(cloud.CLI_GUIDE)
    # tutte le strade: brew, script, WSL, il warning v0.7, e wire senza CLI
    for frag in ("brew", "get.tur.so", "WSL", "v0.7", "wire"):
        assert frag in guide


def test_setup_detects_wrong_turso_on_path(tmp_path):
    """`turso` v0.7 (database locale) sul PATH: comandi cloud sconosciuti → guida."""
    lines = cloud.setup(env_file=tmp_path / ".env",
                        runner=lambda a: (2, "error: unrecognized subcommand 'auth'"))
    assert lines[0].startswith("[!!]") and "database locale" in lines[0]
    assert any("wire" in ln for ln in lines)


def test_mint_uses_group_tokens_create(tmp_path):
    calls = []
    def run(args):
        calls.append(args)
        return (0, "tok_zzz") if args[:3] == ["group", "tokens", "create"] else (0, "NAME\nx")
    assert cloud._mint_group_token("g", run) == "tok_zzz"
    assert ["group", "tokens", "create", "g"] in calls
    assert not any("mint" in c for c in calls for c in c)   # mai `mint` (B4)


def test_setup_without_cli_points_to_guide(tmp_path):
    lines = cloud.setup(env_file=tmp_path / ".env", runner=lambda a: (127, ""))
    assert lines[0].startswith("[!!]")
    assert any("wire" in ln for ln in lines)          # l'alternativa senza CLI c'è sempre


def test_wire_no_cli(tmp_path, monkeypatch):
    """BYO senza turso CLI: cabla URL/token incollati, parziale, probe gating."""
    for k in cloud.MANAGED_KEYS:
        monkeypatch.delenv(k, raising=False)
    envf = tmp_path / ".env"
    # parziale: solo neurag + token, nessuna CLI coinvolta
    lines = cloud.wire({"neurag": "libsql://nrg.turso.io"}, token="tok_x",
                       env_file=envf, probe=lambda u, t: (True, "wss", ""))
    assert not any(ln.startswith("[!!]") for ln in lines)
    saved = cloud.read_env_file(envf)
    assert saved == {"NEURAG_TURSO_DATABASE_URL": "libsql://nrg.turso.io",
                     "TURSO_AUTH_TOKEN": "tok_x"}
    assert not any("tok_x" in ln for ln in lines)              # token mai in output
    # URL non valida → [!!] e non scritta
    out = cloud.wire({"neuron": "ftp://nope"}, token="t", env_file=envf,
                     probe=lambda u, t: (True, "wss", ""))
    assert any(ln.startswith("[!!]") for ln in out)
    assert "TURSO_DATABASE_URL" not in cloud.read_env_file(envf)
    # probe fallito → niente scritto
    out = cloud.wire({"neuron": "libsql://n.turso.io"}, token="bad",
                     env_file=envf, probe=lambda u, t: (False, "", "401"))
    assert any("niente scritto" in ln for ln in out)
    assert "TURSO_DATABASE_URL" not in cloud.read_env_file(envf)
    # niente input → messaggio chiaro
    assert cloud.wire({}, env_file=envf)[0].startswith("[!!]")
    # token orfano (nessuna URL, .env vuoto) → NON scritto (invariante audit)
    empty = tmp_path / "empty.env"
    out = cloud.wire({}, token="tok_orphan", env_file=empty)
    assert out[0].startswith("[!!]") and not cloud.read_env_file(empty)
    # rotazione: token nuovo con URL già cablate nel .env → ok
    out = cloud.wire({}, token="tok_new", env_file=envf,
                     probe=lambda u, t: (True, "wss", ""))
    assert any("ruotato" in ln for ln in out)
    assert cloud.read_env_file(envf)["TURSO_AUTH_TOKEN"] == "tok_new"


def test_env_file_with_bom(tmp_path):
    """BOM di PowerShell 5.1: read non corrompe la prima chiave, update la preserva."""
    envf = tmp_path / ".env"
    envf.write_bytes(b"\xef\xbb\xbfTURSO_DATABASE_URL=libsql://x\n")
    assert cloud.read_env_file(envf) == {"TURSO_DATABASE_URL": "libsql://x"}
    cloud.update_env_file(envf, {"TURSO_DATABASE_URL": "libsql://y"})
    assert cloud.read_env_file(envf) == {"TURSO_DATABASE_URL": "libsql://y"}
    assert "﻿" not in envf.read_text(encoding="utf-8")   # riscritto senza BOM


def test_status_and_teardown(tmp_path, monkeypatch):
    for k in cloud.MANAGED_KEYS + ("NEURAG_TURSO_AUTH_TOKEN", "GM_TURSO_AUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    envf = tmp_path / ".env"
    envf.write_text("MIA=1\nTURSO_DATABASE_URL=libsql://x\nTURSO_AUTH_TOKEN=t\n",
                    encoding="utf-8")
    st = "\n".join(cloud.status(env_file=envf))
    assert "[cloud] neuron" in st and "[local] neurag" in st and "[local] gm" in st
    out = cloud.teardown(env_file=envf)
    assert out[0].startswith("[ok]")
    saved = cloud.read_env_file(envf)
    assert saved == {"MIA": "1"}                                  # solo le nostre rimosse
    assert envf.with_suffix(".env.bak").exists() or Path(str(envf) + ".bak").exists()
    assert cloud.teardown(env_file=envf)[0].endswith("da rimuovere")
