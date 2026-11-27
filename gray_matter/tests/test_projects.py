"""projects.resolve: the session's context from its folder, by identity, never a guess."""
import json

from gray_matter import projects as P

GM = "https://github.com/recla93/GrayMatterEnvironment.git"


def _repo(d, url=GM):
    (d / ".git").mkdir(parents=True)
    (d / ".git" / "config").write_text(
        f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*\n',
        encoding="utf-8")
    return d


def _conf(tmp_path, remotes=None, paths=None):
    f = tmp_path / "projects.json"
    f.write_text(json.dumps({"remotes": remotes or {}, "paths": paths or {}}), encoding="utf-8")
    return f


def test_remote_identity_survives_moves_and_spellings(tmp_path):
    conf = _conf(tmp_path, remotes={"github.com/recla93/GrayMatterEnvironment": "backend"})
    for name, url in (("a", GM), ("Gray Matter Enviroment", "git@github.com:recla93/GrayMatterEnvironment"),
                      ("c", "https://user@GitHub.com/recla93/graymatterenvironment/")):
        root = _repo(tmp_path / name, url)
        (root / "neuron" / "src").mkdir(parents=True)
        assert P.resolve(str(root / "neuron" / "src"), conf) == "backend"


def test_worktree_reads_the_main_repo_config(tmp_path):
    conf = _conf(tmp_path, remotes={"github.com/recla93/graymatterenvironment": "backend"})
    main = _repo(tmp_path / "main")
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}", encoding="utf-8")
    assert P.resolve(str(wt), conf) == "backend"


def test_no_root_means_no_project(tmp_path):
    conf = _conf(tmp_path, remotes={"github.com/recla93/graymatterenvironment": "backend"})
    desk = tmp_path / "Desktop"
    _repo(desk / "repo1")                         # repos BELOW do not count
    assert P.resolve(str(desk), conf) == ""
    assert P.resolve(str(tmp_path / "missing"), conf) == ""
    assert P.resolve("", conf) == ""


def test_nearest_root_wins_and_unknown_repo_is_no_project(tmp_path):
    conf = _conf(tmp_path, remotes={"github.com/recla93/graymatterenvironment": "backend"})
    outer = _repo(tmp_path / "outer")
    inner = _repo(outer / "vendor" / "other", "https://github.com/someone/else.git")
    assert P.resolve(str(inner), conf) == ""      # unmapped: not silently the outer project
    assert P.resolve(str(outer / "vendor"), conf) == "backend"


def test_marker_and_known_path(tmp_path):
    conf = _conf(tmp_path, paths={str(tmp_path / "notes"): "studio/bash"})
    (tmp_path / "notes" / "sub").mkdir(parents=True)
    assert P.resolve(str(tmp_path / "notes" / "sub"), conf) == "studio/bash"
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / P.MARKER).write_text("Qwen\n", encoding="utf-8")
    assert P.resolve(str(tmp_path / "proj"), conf) == "qwen"


def test_bad_config_is_no_project(tmp_path):
    f = tmp_path / "projects.json"
    f.write_text("{not json", encoding="utf-8")
    assert P.resolve(str(_repo(tmp_path / "r")), f) == ""


def test_gateway_scopes_neuron_calls_and_switches_its_session_only(monkeypatch):
    from gray_matter import server as S
    monkeypatch.setattr(S, "_SESSION_CTX", [None])
    monkeypatch.setattr(S, "_SESSION_PINNED", [False])
    monkeypatch.setattr(S, "_project_scope", lambda cwd: "backend")
    assert S._session_scoped("pre_turn", {"topic": "x"}) == {"topic": "x", "_scope": "backend"}
    out = S._session_scoped("switch_context", {"context": "LLM/"})
    assert out["_scope"] == "llm" and S._SESSION_CTX == ["llm"]
    assert S._session_scoped("store_turn", {})["_scope"] == "llm"


def test_gateway_without_project_keeps_the_shared_pointer(monkeypatch):
    from gray_matter import server as S
    monkeypatch.setattr(S, "_SESSION_CTX", [None])
    monkeypatch.setattr(S, "_SESSION_PINNED", [False])
    monkeypatch.setattr(S, "_project_scope", lambda cwd: "")
    assert S._session_scoped("pre_turn", {"topic": "x"}) == {"topic": "x"}
    assert S._session_scoped("switch_context", {"context": "llm"}) == {"context": "llm", "_scope_pin": True}


def test_the_daemon_gives_a_gateway_call_the_turn_project(monkeypatch):
    """Claude Desktop shares one gateway among its sessions: its own choice was
    another session's folder (qwen) while the hook of the message said
    graymatter (live 2026-11-27). The hook's project wins, a switch pins."""
    import asyncio
    from gray_matter import server as S
    monkeypatch.setattr(S, "_LAST_HOOK_SCOPE", ["graymatter"])
    assert S._turn_scoped("neuron", {"x": 1, "_scope": "qwen"}, False) == {"x": 1, "_scope": "graymatter"}
    assert S._turn_scoped("neuron", {"_scope": "llm"}, True) == {"_scope": "llm"}
    assert S._turn_scoped("neurag", {"q": 1}, False) == {"q": 1}
    S._LAST_HOOK_SCOPE[0] = ""
    assert S._turn_scoped("neuron", {"_scope": "qwen"}, False) == {"_scope": "qwen"}
    sent = []

    async def via(payload, timeout=0):
        sent.append(payload)
        return "ok"
    monkeypatch.setattr(S, "_via_daemon", via)
    asyncio.run(S._call_server_async("neuron", "store_turn", {"facts": [], "_scope_pin": True}))
    assert sent[0]["pin"] is True and "_scope_pin" not in sent[0]["args"]


def test_memhook_scope_from_payload_cwd(monkeypatch):
    from gray_matter import memhook as M
    monkeypatch.setattr(P, "session_context", lambda cwd, file=None: "backend" if cwd == "D:/gm" else "")
    assert M._scope({"cwd": "D:/gm"}) == {"_scope": "backend"}
    assert M._scope({"cwd": "C:/Windows/System32"}) == {}
    assert M._scope({}) == {}


def test_no_project_means_the_inbox_once_projects_json_exists(tmp_path):
    conf = _conf(tmp_path, remotes={"github.com/recla93/graymatterenvironment": "graymatter"})
    repo = _repo(tmp_path / "gm")
    assert P.session_context(str(repo), conf) == "graymatter"
    assert P.session_context(str(tmp_path / "gm" / ".."), conf) == "inbox"
    assert P.session_context("", conf) == "inbox"
    conf.write_text(json.dumps({"remotes": {}, "no_project": "Generale"}), encoding="utf-8")
    assert P.session_context(str(tmp_path), conf) == "generale"
    assert P.session_context(str(repo), tmp_path / "missing.json") == ""      # not opted in: as before


def test_gateway_takes_the_project_from_the_client_roots(monkeypatch):
    import asyncio
    import types
    from gray_matter import server as S
    monkeypatch.setattr(S, "_SESSION_CTX", [None])
    seen = {}
    monkeypatch.setattr(S, "_project_scope", lambda folder: seen.setdefault("folder", folder) and "graymatter")

    class Sess:
        client_params = types.SimpleNamespace(capabilities=types.SimpleNamespace(roots=object()))

        async def list_roots(self):
            return types.SimpleNamespace(roots=[types.SimpleNamespace(uri="file:///D:/Desktop/Gray%20Matter")])
    monkeypatch.setattr(S, "app", types.SimpleNamespace(request_context=types.SimpleNamespace(session=Sess())))
    asyncio.run(S._resolve_session_ctx())
    assert seen["folder"] == "D:/Desktop/Gray Matter" and S._SESSION_CTX == ["graymatter"]
    assert S._root_path("file:///home/u/proj") == "/home/u/proj" and S._root_path("https://x") == ""
