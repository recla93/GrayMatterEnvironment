"""Env model — loader .env a livello GM (daemon→worker via eredità)."""
import os


def _fresh(monkeypatch):
    from gray_matter import _env
    monkeypatch.setattr(_env, "_loaded", False)
    monkeypatch.setattr(_env, "_is_test_run", lambda: False)  # il test PUÒ caricare
    return _env


def test_loads_gm_env_real_env_wins(monkeypatch, tmp_path):
    envf = tmp_path / ".env"
    envf.write_text('GM_TURSO_DATABASE_URL="libsql://gm.example"\n'
                    "TURSO_DATABASE_URL=libsql://neuron.example\n"
                    "# commento\nMALFORMED\n", encoding="utf-8")
    monkeypatch.delenv("GM_TURSO_DATABASE_URL", raising=False)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://gia-presente")
    _env = _fresh(monkeypatch)
    assert _env.load_dotenv_once(str(envf)) is True
    assert os.environ["GM_TURSO_DATABASE_URL"] == "libsql://gm.example"   # unquoted
    assert os.environ["TURSO_DATABASE_URL"] == "libsql://gia-presente"    # env reale vince


def test_runs_once_and_respects_optout(monkeypatch, tmp_path):
    envf = tmp_path / ".env"
    envf.write_text("GM_X=1\n", encoding="utf-8")
    _env = _fresh(monkeypatch)
    monkeypatch.setenv("GM_NO_DOTENV", "1")
    monkeypatch.delenv("GM_X", raising=False)
    assert _env.load_dotenv_once(str(envf)) is False       # opt-out
    assert "GM_X" not in os.environ
    monkeypatch.delenv("GM_NO_DOTENV", raising=False)
    assert _env.load_dotenv_once(str(envf)) is False       # già "loaded" → once


def test_missing_file_is_noop(monkeypatch, tmp_path):
    _env = _fresh(monkeypatch)
    assert _env.load_dotenv_once(str(tmp_path / "nope.env")) is False


def test_bom_from_powershell_is_stripped(monkeypatch, tmp_path):
    """PS 5.1 `Set-Content -Encoding utf8` scrive il BOM: la chiave deve restare pulita."""
    envf = tmp_path / ".env"
    envf.write_bytes(b"\xef\xbb\xbfGM_BOM_VAR=ok\n")
    monkeypatch.delenv("GM_BOM_VAR", raising=False)
    _env = _fresh(monkeypatch)
    assert _env.load_dotenv_once(str(envf)) is True
    assert os.environ["GM_BOM_VAR"] == "ok"
    assert "﻿GM_BOM_VAR" not in os.environ


def test_disabled_under_pytest(monkeypatch, tmp_path):
    from gray_matter import _env
    monkeypatch.setattr(_env, "_loaded", False)
    envf = tmp_path / ".env"
    envf.write_text("GM_Y=1\n", encoding="utf-8")
    monkeypatch.delenv("GM_Y", raising=False)
    assert _env.load_dotenv_once(str(envf)) is False       # siamo sotto pytest
    assert "GM_Y" not in os.environ
