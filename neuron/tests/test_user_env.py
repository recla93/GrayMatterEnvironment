"""Per-user .env: the file the installer writes so the embedding-model choice
survives an MCP client spawning the server from an arbitrary cwd."""

import os

import pytest

from neuron import _env, config


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point user_data_dir() at a temp dir (it reads LOCALAPPDATA/XDG_DATA_HOME)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("NEURON_SLUG", raising=False)
    return tmp_path / "neuron"


def test_user_env_file_sits_beside_graphs(home):
    # Same parent as the graph store — one Neuron home, not two.
    assert os.path.dirname(config.user_env_file()) == os.path.dirname(config.default_graphs_dir())


def test_set_user_env_creates_and_reads_back(home):
    path = config.set_user_env(NS_EMBED_MODEL="intfloat/multilingual-e5-large", NS_EMBED_DIM="1024")
    assert os.path.isfile(path)
    body = open(path, encoding="utf-8").read()
    assert "NS_EMBED_MODEL=intfloat/multilingual-e5-large" in body
    assert "NS_EMBED_DIM=1024" in body


def test_set_user_env_preserves_other_keys(home):
    # The Turso credentials live in the same file — a model change must not eat
    # them, which a naive "write the two keys" installer would have done.
    config.set_user_env(TURSO_DATABASE_URL="libsql://x", TURSO_AUTH_TOKEN="tok")
    config.set_user_env(NS_EMBED_MODEL="sentence-transformers/all-MiniLM-L6-v2", NS_EMBED_DIM="384")
    body = open(config.user_env_file(), encoding="utf-8").read()
    assert "TURSO_DATABASE_URL=libsql://x" in body
    assert "TURSO_AUTH_TOKEN=tok" in body
    assert "NS_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2" in body


def test_set_user_env_overwrites_same_key_once(home):
    config.set_user_env(NS_EMBED_DIM="384")
    config.set_user_env(NS_EMBED_DIM="768")
    body = open(config.user_env_file(), encoding="utf-8").read()
    assert body.count("NS_EMBED_DIM=") == 1
    assert "NS_EMBED_DIM=768" in body


def test_load_reads_user_env_from_any_cwd(home, tmp_path, monkeypatch):
    """The whole point: no project .env anywhere up the tree, yet the choice loads."""
    config.set_user_env(NS_EMBED_MODEL="sentence-transformers/all-MiniLM-L6-v2")
    elsewhere = tmp_path / "some" / "unrelated" / "cwd"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("NS_EMBED_MODEL", raising=False)
    monkeypatch.setattr(_env, "_loaded", False)
    monkeypatch.setattr(_env, "_is_test_run", lambda: False)   # the loader no-ops under pytest

    assert _env.load_dotenv_once() is True
    assert os.environ["NS_EMBED_MODEL"] == "sentence-transformers/all-MiniLM-L6-v2"


def test_project_env_wins_over_user_env(home, tmp_path, monkeypatch):
    """Precedence: real env > project .env > user .env (setdefault, project first)."""
    config.set_user_env(NS_EMBED_MODEL="from-user")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("NS_EMBED_MODEL=from-project\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    monkeypatch.delenv("NS_EMBED_MODEL", raising=False)
    monkeypatch.setattr(_env, "_loaded", False)
    monkeypatch.setattr(_env, "_is_test_run", lambda: False)

    _env.load_dotenv_once()
    assert os.environ["NS_EMBED_MODEL"] == "from-project"


def test_real_env_still_wins(home, monkeypatch):
    config.set_user_env(NS_EMBED_MODEL="from-user")
    monkeypatch.setenv("NS_EMBED_MODEL", "from-real-env")
    monkeypatch.setattr(_env, "_loaded", False)
    monkeypatch.setattr(_env, "_is_test_run", lambda: False)

    _env.load_dotenv_once()
    assert os.environ["NS_EMBED_MODEL"] == "from-real-env"
