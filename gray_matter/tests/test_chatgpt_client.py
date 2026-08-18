"""ChatGPT non gira su questa macchina: si raggiunge via bridge + tunnel.

Il punto delicato non e' accendere il tunnel, e' il tier senza account: il quick
tunnel (`*.trycloudflare.com`) parte senza credenziali ma ha un TIMER e scade da
solo, portandosi dietro la connessione di ChatGPT senza un errore visibile.
Segnare verde quell'installazione significa lasciare l'utente a scoprire da solo
perche' ha smesso di funzionare — quindi non e' verde, ed e' accompagnata dal
link per registrarsi e dai comandi esatti.
"""
from __future__ import annotations

import importlib

import pytest

from gray_matter import chatgpt


@pytest.fixture
def cf(monkeypatch, tmp_path):
    """Controlla presenza di cloudflared e delle credenziali."""
    def setup(has_binary: bool, has_creds: bool):
        monkeypatch.setattr(chatgpt.shutil, "which",
                            lambda n: "/usr/bin/cloudflared" if has_binary else None)
        cert = tmp_path / ".cloudflared" / "cert.pem"
        if has_creds:
            cert.parent.mkdir(parents=True, exist_ok=True)
            cert.write_text("cert", encoding="utf-8")
        monkeypatch.setattr(chatgpt, "_cloudflared_cert", lambda: cert)
        return chatgpt.state()
    return setup


@pytest.fixture
def home(tmp_path, monkeypatch):
    """I test che chiamano clients.register() devono isolare i path REALI:
    senza mockare USERPROFILE/APPDATA i registri toccano i config della
    macchina (verificato: 7 config corrotti con '/fake/python'). Stesso
    fixture di test_client_register_is_a_merge.py."""
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "Local"))
    return tmp_path


def test_registered_account_is_the_only_persistent_setup(cf):
    st = cf(True, True)
    assert st["mode"] == "named"
    assert st["persistent"] is True
    assert chatgpt.instructions(st) == [], "con le credenziali non c'e' nulla da spiegare"
    assert chatgpt.register()["ok"] is True


def test_a_quick_tunnel_is_not_reported_as_success(cf):
    """Parte, ma scade: verde sarebbe una bugia."""
    st = cf(True, False)
    assert st["can_start"] is True
    assert st["persistent"] is False
    res = chatgpt.register()
    assert res["ok"] is False
    assert "scade" in res["detail"]


def test_the_user_gets_the_signup_link_and_the_exact_commands(cf):
    st = cf(True, False)
    text = "\n".join(chatgpt.instructions(st))
    assert chatgpt.SIGNUP_URL in text
    assert "cloudflared tunnel login" in text
    assert "cloudflared tunnel create" in text
    assert "scade" in text.lower(), "non dice che il quick tunnel muore da solo"


def test_missing_cloudflared_says_how_to_install_it(cf):
    st = cf(False, False)
    assert st["mode"] == "none" and st["can_start"] is False
    text = "\n".join(chatgpt.instructions(st))
    assert "winget install" in text and "brew install" in text
    assert chatgpt.register()["action"] == "manual"


def test_it_is_a_known_client_but_never_automatic(monkeypatch, home):
    """Accendere un tunnel PUBBLICO non e' una cosa da fare da sola dentro un
    "registra nei client rilevati": va chiesto per nome."""
    from gray_matter import clients as C
    importlib.reload(C)
    assert "chatgpt" in C.CLIENTS
    assert C.CLIENTS["chatgpt"].get("remote") is True

    seen = []
    monkeypatch.setattr(C, "installed_servers", lambda: ["gray-matter"])
    # senza `only`: non deve nemmeno essere considerato
    res = C.register(gateway=True, py="/fake/python")
    assert not any(r.get("client") == "ChatGPT" for r in res), \
        "ha acceso un tunnel pubblico senza che nessuno lo chiedesse"
    assert seen == []


def test_asked_by_name_it_answers(monkeypatch, home):
    from gray_matter import clients as C
    importlib.reload(C)
    res = C.register(only=["chatgpt"], gateway=True, py="/fake/python")
    assert any(r.get("client") == "ChatGPT" for r in res)
