"""ADR-014: l'hook porta il contesto da solo, e non rompe mai il messaggio."""
import json

from gray_matter import memhook as mh


def test_acks_commands_and_short_text_are_not_recalled():
    for p in ("ok", "Sì.", "grazie!", "/ponytail lite", "   ", "corto"):
        assert not mh.worth_recalling(p), p
    assert mh.worth_recalling("Come mai GM non è partito?")







def test_save_sees_a_store_turn_after_the_last_prompt(tmp_path):
    user = {"type": "user", "message": {"role": "user", "content": "una domanda vera"}}
    call = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "mcp__gray-matter__store_turn", "input": {}}]}}
    result = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
    assert mh.last_turn([user, call, result]) == ("una domanda vera", True)
    assert mh.last_turn([call, user]) == ("una domanda vera", False)


def test_save_keeps_only_words_that_are_already_nodes(monkeypatch):
    fc = ("Candidates for [...]:\n"
          "  flash                 sim=0.55  links: ...\n"
          "  pulse                 sim=0.56  links: ...\n")
    monkeypatch.setattr(mh, "_call", lambda *a: fc)
    assert mh.existing(["pulse", "parliamo", "flash", "qualcosa"]) == ["pulse", "flash"]


def test_main_never_raises_on_garbage(monkeypatch, capsys):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"non json")))
    mh.main(["memhook", "recall"])
    assert capsys.readouterr().out == ""


def test_output_is_the_userpromptsubmit_shape(monkeypatch, capsys):
    import io
    import sys
    monkeypatch.setattr(mh, "recall", lambda p: "contesto")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"prompt": "x"}')))
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="utf-8"))
    mh.main(["memhook", "recall"])
    sys.stdout.flush()
    out = json.loads(buf.getvalue().decode("utf-8"))
    assert out["hookSpecificOutput"]["additionalContext"] == "contesto"


def test_recall_is_one_request_with_the_session(monkeypatch):
    sent = []
    monkeypatch.setattr(mh, "_ipc", lambda msg: sent.append(msg) or "x" * 5000)
    out = mh.recall({"prompt": "una domanda abbastanza lunga", "session_id": "s1"})
    assert [m["action"] for m in sent] == ["recall"] and sent[0]["session"] == "s1"
    assert len(out) == mh.BUDGET


def test_no_daemon_no_output(monkeypatch):
    import gray_matter.cli as cli
    monkeypatch.setattr(cli, "_send_ipc", lambda *a, **k: {"error": "connection refused"})
    assert mh.recall({"prompt": "una domanda abbastanza lunga"}) == ""
