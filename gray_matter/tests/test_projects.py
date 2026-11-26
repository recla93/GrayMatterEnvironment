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
    monkeypatch.setattr(S, "_project_scope", lambda cwd: "backend")
    assert S._session_scoped("pre_turn", {"topic": "x"}) == {"topic": "x", "_scope": "backend"}
    out = S._session_scoped("switch_context", {"context": "LLM/"})
    assert out["_scope"] == "llm" and S._SESSION_CTX == ["llm"]
    assert S._session_scoped("store_turn", {})["_scope"] == "llm"


def test_gateway_without_project_keeps_the_shared_pointer(monkeypatch):
    from gray_matter import server as S
    monkeypatch.setattr(S, "_SESSION_CTX", [None])
    monkeypatch.setattr(S, "_project_scope", lambda cwd: "")
    assert S._session_scoped("switch_context", {"context": "llm"}) == {"context": "llm"}
    assert S._session_scoped("pre_turn", {"topic": "x"}) == {"topic": "x"}


def test_memhook_scope_from_payload_cwd(monkeypatch):
    from gray_matter import memhook as M
    monkeypatch.setattr(P, "resolve", lambda cwd, file=None: "backend" if cwd == "D:/gm" else "")
    assert M._scope({"cwd": "D:/gm"}) == {"_scope": "backend"}
    assert M._scope({"cwd": "C:/Windows/System32"}) == {}
    assert M._scope({}) == {}
