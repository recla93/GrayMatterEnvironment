"""The workers' model cache never falls back to %TEMP%: a daemon without the
user's FASTEMBED_CACHE_PATH re-downloaded mpnet on every call (2026-11-28)."""
from gray_matter import _worker


def test_existing_installer_cache_wins(tmp_path, monkeypatch):
    legacy = tmp_path / "gray-matter" / "fastembed_cache"
    legacy.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _worker.model_cache() == str(legacy)


def test_else_the_suite_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("GM_HOME", str(tmp_path / "suite"))
    assert _worker.model_cache() == str(tmp_path / "suite" / "fastembed_cache")
