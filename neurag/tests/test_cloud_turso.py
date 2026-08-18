"""Cloud Turso facade (decoupled port) — unit tests with a fake libsql client.

The real cloud path needs libsql-client + a live Turso DB (verify locally); these
lock in the facade contract: name-accessible rows, no-op pragmas, batch writes,
scheme normalisation, and the L2 local-open degrade.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from neurag import db  # noqa: E402


class _FakeResult:
    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows


class _FakeClient:
    def __init__(self):
        self.batches = []

    def execute(self, sql, params=None):
        return _FakeResult(["id", "name"], [(1, "spring")])

    def batch(self, stmts):
        self.batches.append(stmts)

    def close(self):
        pass


class _FakeLibsql:
    @staticmethod
    def create_client_sync(url, auth_token):
        return _FakeClient()

    class Statement:
        def __init__(self, sql, params):
            self.sql, self.params = sql, params


def test_remote_rows_are_name_accessible(monkeypatch):
    monkeypatch.setattr(db, "_libsql", _FakeLibsql)
    conn = db.RemoteTursoConnection("libsql://x", "tok")
    row = conn.execute("SELECT id, name FROM nodes").fetchone()
    assert row["name"] == "spring"   # dict-like (NeuRAG uses row['col'])
    assert row[0] == 1               # index-like too
    conn.close()


def test_remote_pragma_is_noop(monkeypatch):
    monkeypatch.setattr(db, "_libsql", _FakeLibsql)
    conn = db.RemoteTursoConnection("libsql://x", "tok")
    # WAL/foreign_keys pragmas are meaningless remote — must not hit the client
    assert conn.execute("PRAGMA journal_mode=WAL").fetchall() == []
    conn.executemany("INSERT INTO t(x) VALUES (?)", [(1,), (2,)])
    assert conn._client.batches, "executemany should batch"
    conn.close()


def test_url_candidates_normalisation():
    # _url_candidates returns a list: user's URL first, then https fallback
    assert db._url_candidates("libsql://db.turso.io") == [
        "libsql://db.turso.io", "https://db.turso.io"]
    assert db._url_candidates("https://db.turso.io") == ["https://db.turso.io"]
    assert db._url_candidates("wss://db.turso.io") == [
        "wss://db.turso.io", "https://db.turso.io"]


def test_local_open_degrades_to_none(monkeypatch):
    def _boom(_path):
        raise OSError("open: NotFound")
    monkeypatch.setattr(db, "turso_connect", _boom, raising=False)
    assert db._open_local_turso("/tmp/does/not/matter.db") is None  # caller logs error
