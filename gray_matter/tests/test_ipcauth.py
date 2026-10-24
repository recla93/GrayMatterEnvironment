"""The IPC's internal identity: ephemeral key, per-user channel, JWT HS256.

ADR-012 phase 2. The old scheme kept one secret forever in a file and sent it
to whoever answered on the port (F4).
"""
import json
import os
import time
import uuid

import pytest

from gray_matter import ipcauth as A

KEY = b"k" * 32
ME = "S-1-5-21-me"


def _claims(token):
    return json.loads(A._b64d(token.split(".")[1]))


# --- the token ---------------------------------------------------------------

def test_a_token_carries_who_and_until_when():
    token, exp = A.issue(KEY, ME, now=1000)
    c = A.verify(KEY, token, sub=ME, now=1001)
    assert c and c["sub"] == ME and c["aud"] == A.AUDIENCE and c["exp"] == exp == 1000 + A.TTL
    assert A.TTL <= 15 * 60, "scadenza breve: un token rubato vale poco"


def test_every_token_is_its_own_session():
    a, _ = A.issue(KEY, ME)
    b, _ = A.issue(KEY, ME)
    assert _claims(a)["sid"] != _claims(b)["sid"]


@pytest.mark.parametrize("header", [{"alg": "none", "typ": "JWT"},
                                    {"alg": "HS512", "typ": "JWT"},
                                    {"alg": "HS256"}])
def test_only_our_exact_header_is_accepted(header):
    """`alg: none` and algorithm swaps are the classic JWT traps."""
    token, _ = A.issue(KEY, ME)
    _, body, sig = token.split(".")
    forged = A._b64e(json.dumps(header).encode())
    assert A.verify(KEY, f"{forged}.{body}.{sig}", sub=ME) is None
    assert A.verify(KEY, f"{forged}.{body}.", sub=ME) is None


def test_tampering_expiry_audience_user_and_key_all_fail():
    token, exp = A.issue(KEY, ME, now=1000)
    head, _, sig = token.split(".")
    c = _claims(token)
    for change in ({"sub": "S-1-5-21-other"}, {"exp": exp + 9999}, {"aud": "elsewhere"}):
        body = A._b64e(json.dumps({**c, **change}).encode())
        assert A.verify(KEY, f"{head}.{body}.{sig}", sub=ME, now=1001) is None, change
    assert A.verify(KEY, token, sub=ME, now=exp) is None, "scaduto"
    assert A.verify(KEY, token, sub="S-1-5-21-other", now=1001) is None, "di un altro utente"
    assert A.verify(b"x" * 32, token, sub=ME, now=1001) is None, "altra chiave"
    for junk in ("", "a.b", "a.b.c.d", None, 42):
        assert A.verify(KEY, junk, sub=ME) is None


# --- the key -----------------------------------------------------------------

def test_the_key_lives_in_ram_and_is_zeroed():
    A.new_key()
    held = A._key
    assert isinstance(held, bytearray) and len(held) == 32 and any(held)
    A.drop_key()
    assert A._key is None and not any(held), "i byte vanno sovrascritti, non solo dimenticati"


def test_a_restart_kills_every_token_issued_before():
    A.new_key()
    token, _ = A.issue(A._key, A.own_identity())
    assert A.verify_request(token)
    A.new_key()
    assert A.verify_request(token) is None
    A.drop_key()


def test_the_legacy_secret_file_is_removed(tmp_path, monkeypatch):
    from gray_matter import paths
    monkeypatch.setattr(paths, "gm_home", lambda: tmp_path)
    (tmp_path / "ipc-token").write_text("old-shared-secret")
    A.drop_legacy_token()
    assert not (tmp_path / "ipc-token").exists()


# --- the channel, end to end -------------------------------------------------

@pytest.fixture
def channel(tmp_path, monkeypatch):
    """A private channel name, so the live daemon's pipe is never touched."""
    if os.name == "nt":
        name = r"\\.\pipe\gm-test-" + uuid.uuid4().hex
    else:
        d = tmp_path / "run"
        name = str(d / "ipc.sock")
    monkeypatch.setattr(A, "channel_address", lambda: name)
    A.new_key()
    yield name
    A.drop_key()


def test_a_handshake_on_the_channel_returns_a_valid_token(channel):
    assert A.serve(4321)
    time.sleep(0.1)
    got = A.fetch_token()
    assert got and got["port"] == 4321
    assert A.verify_request(got["token"])["sub"] == A.own_identity()


def test_the_channel_cannot_be_taken_twice(channel):
    """First-instance flag (Windows) / owned socket (POSIX): a second holder of
    the same name is refused, so it cannot be pre-empted by someone else."""
    assert A.serve(1)
    if os.name == "nt":
        assert A.serve(1) is None


@pytest.mark.skipif(os.name != "nt", reason="pipe server identity is a Windows check")
def test_the_client_sends_nothing_to_a_server_of_another_user(channel, monkeypatch):
    assert A.serve(1)
    time.sleep(0.1)
    monkeypatch.setattr(A, "_pid_identity", lambda pid: "S-1-5-21-someone-else")
    assert A.fetch_token() is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX folder ownership")
def test_the_client_refuses_a_folder_others_can_write(channel):
    assert A.serve(1)
    time.sleep(0.1)
    os.chmod(os.path.dirname(channel), 0o777)
    assert A.fetch_token() is None


def test_client_token_is_cached_and_renewable(channel, monkeypatch):
    assert A.serve(1)
    time.sleep(0.1)
    A._cache.clear()
    first = A.client_token()
    assert first and A.client_token() == first, "in cache fino a vicino alla scadenza"
    assert A.client_token(refresh=True) != first
    A._cache.clear()
