"""Internal identity for the IPC — ADR-012, phase 2. Standard library only.

The daemon's IPC used to trust a token kept forever in a file, sent to whoever
answered on the port: another local account that took the port first collected
it (F4). Now:

* **Key** — 32 random bytes, made when the daemon opens its IPC, kept only in
  RAM, zeroed at exit. Never written, never sent. Every restart is a rotation:
  a token issued before is dead after.
* **Channel** — a per-user rendezvous the OS guards. Windows: the named pipe
  ``\\\\.\\pipe\\gray-matter-<SID>``, whose DACL admits only the user's SID,
  created with FILE_FLAG_FIRST_PIPE_INSTANCE so nobody can hold the name
  first. POSIX: a Unix socket in a 0700 folder owned by the user.
* **Both ends check each other** before anything flows: the client checks that
  the pipe's server process runs as itself (or that the socket folder is its
  own), the server checks the client's user.
* **Token** — a JWT HS256 (``sub`` user, ``sid`` session, ``aud``, ``iat``,
  ``exp`` 15 minutes), issued over the channel and carried by every TCP IPC
  message. Verification accepts our exact header only: ``alg: none`` and
  algorithm swaps are refusals, not options.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

AUDIENCE = "gm-ipc"
TTL = 15 * 60
_HEADER = {"alg": "HS256", "typ": "JWT"}
_WIN = os.name == "nt"


# --- JWT HS256 ---------------------------------------------------------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(key: bytes, signing_input: str) -> str:
    return _b64e(hmac.new(bytes(key), signing_input.encode("ascii"), hashlib.sha256).digest())


def issue(key: bytes, sub: str, *, ttl: int = TTL, now: "float | None" = None) -> "tuple[str, int]":
    """A signed token for `sub`, and its expiry (epoch seconds)."""
    iat = int(time.time() if now is None else now)
    claims = {"sub": sub, "sid": uuid.uuid4().hex, "aud": AUDIENCE,
              "iat": iat, "exp": iat + ttl, "scope": "ipc"}
    head = _b64e(json.dumps(_HEADER, separators=(",", ":")).encode())
    body = _b64e(json.dumps(claims, separators=(",", ":")).encode())
    return f"{head}.{body}.{_sign(key, head + '.' + body)}", claims["exp"]


def verify(key: "bytes | None", token: str, *, sub: str,
           now: "float | None" = None) -> "dict | None":
    """The claims if `token` is ours, unexpired, for `sub` and our audience."""
    if not key or not isinstance(token, str) or token.count(".") != 2:
        return None
    head, body, sig = token.split(".")
    try:
        if json.loads(_b64d(head)) != _HEADER:     # alg is fixed: no "none", no swaps
            return None
        if not hmac.compare_digest(sig, _sign(key, head + "." + body)):
            return None
        claims = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return None
    t = time.time() if now is None else now
    if (claims.get("aud") != AUDIENCE or claims.get("sub") != sub
            or not isinstance(claims.get("exp"), int) or claims["exp"] <= t):
        return None
    return claims


# --- the ephemeral key (daemon side) -----------------------------------------

_key: "bytearray | None" = None


def new_key() -> None:
    """Mint this process's signing key. In RAM only; zeroed at exit."""
    global _key
    drop_key()
    _key = bytearray(secrets.token_bytes(32))
    atexit.register(drop_key)


def drop_key() -> None:
    """Overwrite and forget the key (best effort: Python may hold copies of
    bytes passed to hmac; the bytearray itself is zeroed)."""
    global _key
    if _key is not None:
        for i in range(len(_key)):
            _key[i] = 0
    _key = None


def verify_request(token: str) -> "dict | None":
    """Server side: is this IPC message's token one we issued, for our user?"""
    return verify(_key, token, sub=own_identity())


# --- who am I ----------------------------------------------------------------

if _WIN:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.LocalFree.argtypes = [ctypes.c_void_p]
    _k32.CreateNamedPipeW.restype = wintypes.HANDLE
    _k32.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.DWORD, ctypes.c_void_p]
    _k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _k32.GetNamedPipeClientProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    _k32.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
    _adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]

    class _SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    def _token_sid(process: int) -> "str | None":
        tok = wintypes.HANDLE()
        if not _adv.OpenProcessToken(process, 0x0008, ctypes.byref(tok)):   # TOKEN_QUERY
            return None
        try:
            need = wintypes.DWORD()
            _adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(need))   # TokenUser
            buf = ctypes.create_string_buffer(need.value)
            if not _adv.GetTokenInformation(tok, 1, buf, need, ctypes.byref(need)):
                return None
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]     # TOKEN_USER.User.Sid
            text = wintypes.LPWSTR()
            if not _adv.ConvertSidToStringSidW(psid, ctypes.byref(text)):
                return None
            try:
                return text.value
            finally:
                _k32.LocalFree(text)
        finally:
            _k32.CloseHandle(tok)

    def _pid_identity(pid: int) -> "str | None":
        h = _k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            return _token_sid(h)
        finally:
            _k32.CloseHandle(h)


_own: "str | None" = None


def own_identity() -> str:
    """This process's user: the SID on Windows, the uid elsewhere."""
    global _own
    if _own is None:
        _own = (_token_sid(_k32.GetCurrentProcess()) or "") if _WIN else str(os.getuid())
    return _own


def channel_address() -> str:
    """Where this user's daemon hands out tokens. One per user, by construction."""
    if _WIN:
        return r"\\.\pipe\gray-matter-" + own_identity()
    from gray_matter import paths
    return str(paths.gm_home() / "run" / "ipc.sock")


# --- framing (same as the TCP IPC: 4-byte length + JSON) ---------------------

def _write(f, obj: dict) -> None:
    data = json.dumps(obj).encode("utf-8")
    f.write(struct.pack("!I", len(data)) + data)


def _read(f) -> "dict | None":
    def exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = f.read(n - len(buf))
            if not chunk:
                return b""
            buf += chunk
        return buf
    hdr = exact(4)
    if not hdr:
        return None
    (n,) = struct.unpack("!I", hdr)
    if not 0 < n <= 65536:
        return None
    body = exact(n)
    return json.loads(body.decode("utf-8")) if body else None


def _answer(f, port: int) -> None:
    """One handshake: a fresh token for the (already verified) caller."""
    req = _read(f)
    if not req or req.get("action") != "handshake" or _key is None:
        _write(f, {"error": "bad request"})
        return
    token, exp = issue(_key, own_identity())
    _write(f, {"token": token, "exp": exp, "port": port})


# --- server ------------------------------------------------------------------

def serve(port: int) -> "threading.Thread | None":
    """Hand out tokens on this user's channel, in a background thread.

    Returns None when the channel cannot be held — on Windows that means
    someone else already owns the pipe name, which is exactly the attack the
    first-instance flag is there to expose: say so, and serve nothing."""
    if _key is None:
        new_key()
    try:
        listener = _win_listener() if _WIN else _posix_listener()
    except OSError as exc:
        print(f"gray-matter: IPC identity channel unavailable ({exc}); "
              f"clients cannot authenticate", file=sys.stderr)
        return None
    t = threading.Thread(target=listener, args=(port,), name="gm-ipcauth", daemon=True)
    t.start()
    return t


def _win_listener():
    sid = own_identity()
    psd = ctypes.c_void_p()
    # Protected DACL, one ACE: GENERIC_ALL for this user. Nobody else connects.
    if not _adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"D:P(A;;GA;;;{sid})", 1, ctypes.byref(psd), None):
        raise OSError(ctypes.get_last_error(), "security descriptor")
    sa = _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), psd, False)
    name = channel_address()

    def create(first: bool):
        # PIPE_ACCESS_DUPLEX | (FILE_FLAG_FIRST_PIPE_INSTANCE); byte mode, blocking,
        # PIPE_REJECT_REMOTE_CLIENTS: never reachable over SMB.
        h = _k32.CreateNamedPipeW(name, 0x3 | (0x00080000 if first else 0), 0x8,
                                  255, 65536, 65536, 0, ctypes.byref(sa))
        if h is None or h == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), f"cannot create {name}")
        return h

    first = create(True)   # raises here if the name is already held

    def loop(port: int, h=first) -> None:
        import msvcrt
        while True:
            ok = _k32.ConnectNamedPipe(h, None)
            if not ok and ctypes.get_last_error() != 535:     # ERROR_PIPE_CONNECTED
                _k32.CloseHandle(h)
                h = create(False)
                continue
            nxt = create(False)                                # next caller never waits
            threading.Thread(target=_serve_pipe_client, args=(h, port, msvcrt),
                             daemon=True).start()
            h = nxt

    return loop


def _serve_pipe_client(h, port: int, msvcrt) -> None:
    pid = wintypes.ULONG()
    caller = (_pid_identity(pid.value)
              if _k32.GetNamedPipeClientProcessId(h, ctypes.byref(pid)) else None)
    fd = msvcrt.open_osfhandle(h, os.O_RDWR)
    with os.fdopen(fd, "r+b", buffering=0) as f:
        try:
            if caller != own_identity():                       # the DACL already says so;
                _write(f, {"error": "unauthorized"})           # this is the second lock
                return
            _answer(f, port)
        except (OSError, ValueError):
            pass


def _posix_listener():
    path = Path(channel_address())
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.parent.stat().st_uid != os.getuid():
        raise OSError(f"{path.parent} is not owned by this user")
    if path.exists():
        path.unlink()                                          # ours: stale from a crash
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    os.chmod(path, 0o600)
    srv.listen(8)

    def loop(port: int) -> None:
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=_serve_unix_client, args=(conn, port), daemon=True).start()

    return loop


def _peer_uid(conn) -> "int | None":
    if hasattr(socket, "SO_PEERCRED"):                         # Linux
        cred = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", cred)[1]
    return os.getuid()          # macOS & co.: the 0700 folder is the lock


def _serve_unix_client(conn, port: int) -> None:
    with conn, conn.makefile("rwb", buffering=0) as f:
        try:
            if _peer_uid(conn) != os.getuid():
                _write(f, {"error": "unauthorized"})
                return
            _answer(f, port)
        except (OSError, ValueError):
            pass


# --- client ------------------------------------------------------------------

_cache: dict = {}


def fetch_token(timeout: float = 3.0) -> "dict | None":
    """Ask this user's daemon for a token, after checking it IS this user's."""
    try:
        return _win_fetch(timeout) if _WIN else _posix_fetch(timeout)
    except (OSError, ValueError):
        return None


def _win_fetch(timeout: float) -> "dict | None":
    import msvcrt
    deadline = time.monotonic() + timeout
    while True:
        try:
            f = open(channel_address(), "r+b", buffering=0)
            break
        except OSError as exc:
            # 231 ERROR_PIPE_BUSY: every instance taken for an instant; retry.
            if getattr(exc, "winerror", None) != 231 or time.monotonic() > deadline:
                return None
            time.sleep(0.02)
    with f:
        pid = wintypes.ULONG()
        if not _k32.GetNamedPipeServerProcessId(msvcrt.get_osfhandle(f.fileno()),
                                                ctypes.byref(pid)):
            return None
        if _pid_identity(pid.value) != own_identity():
            return None            # someone else's pipe under our name: send nothing
        _write(f, {"action": "handshake"})
        return _read(f)


def _posix_fetch(timeout: float) -> "dict | None":
    path = Path(channel_address())
    st_dir, st_sock = path.parent.stat(), path.stat()
    if (st_dir.st_uid != os.getuid() or st_sock.st_uid != os.getuid()
            or st_dir.st_mode & 0o077):
        return None                # not a folder only we can write into
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(path))
        with s.makefile("rwb", buffering=0) as f:
            _write(f, {"action": "handshake"})
            return _read(f)


def client_token(*, refresh: bool = False) -> str:
    """A valid token for this process's IPC calls, cached until near expiry."""
    if not refresh and _cache.get("exp", 0) - time.time() > 60:
        return _cache["token"]
    got = fetch_token()
    if not got or "token" not in got:
        _cache.clear()
        return ""
    _cache.update(token=got["token"], exp=int(got.get("exp", 0)))
    return _cache["token"]


def drop_legacy_token() -> None:
    """The old shared secret on disk (`<GM_HOME>/ipc-token`) authenticates
    nothing any more; leaving it would leave a key lying around."""
    from gray_matter import paths
    try:
        (paths.gm_home() / "ipc-token").unlink()
    except OSError:
        pass
