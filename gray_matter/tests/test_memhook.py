"""ADR-014: the hook brings the context on its own, and never breaks the message."""
import json

from gray_matter import memhook as mh


def test_acks_commands_and_short_text_are_not_recalled():
    for p in ("ok", "Sì.", "grazie!", "/ponytail lite", "   ", "corto"):
        assert not mh.worth_recalling(p), p
    assert mh.worth_recalling("Come mai GM non è partito?")







# --- Stop (ADR-015 phase 3): the model writes the fact, the hook checks ------

USER = {"type": "user", "message": {"role": "user", "content": "sistema il test che fallisce"}}
RESULT = {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def _assistant(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def _stop(tmp_path, *entries, **payload):
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8", newline="\n")
    return mh.save({"transcript_path": str(t), **payload})


def test_a_working_turn_without_a_fact_is_sent_back_once(tmp_path):
    turn = (USER, _assistant(_tool("Edit", file_path="x.py")), RESULT,
            _assistant({"type": "text", "text": "fatto"}))
    assert _stop(tmp_path, *turn) == mh.REMIND
    assert _stop(tmp_path, *turn, stop_hook_active=True) == "", "the second Stop must pass: no loop"


def test_a_fact_saved_after_the_prompt_lets_the_turn_end(tmp_path):
    fact = _tool("mcp__gray-matter__store_turn",
                 facts=[{"kind": "fix", "text": "x", "concepts": ["test"]}])
    assert _stop(tmp_path, USER, _assistant(_tool("Bash", command="pytest")), RESULT,
                 _assistant(fact), RESULT) == ""
    legacy = _tool("mcp__neuron__store_turn", topic="t", keywords=["k"], episode="un fatto")
    assert _stop(tmp_path, USER, _assistant(_tool("Bash")), RESULT, _assistant(legacy)) == ""


def test_keywords_alone_are_not_a_fact(tmp_path):
    words = _tool("mcp__gray-matter__store_turn", topic="t", keywords=["k"])
    assert _stop(tmp_path, USER, _assistant(_tool("Edit")), RESULT,
                 _assistant(words), RESULT) == mh.REMIND


def test_a_fact_of_an_earlier_turn_does_not_count(tmp_path):
    fact = _tool("mcp__gray-matter__store_turn", facts=[{"kind": "fact", "text": "x", "concepts": ["a"]}])
    assert _stop(tmp_path, USER, _assistant(fact), RESULT,
                 USER, _assistant(_tool("Edit")), RESULT) == mh.REMIND


def test_chatter_and_acks_are_let_through(tmp_path):
    short = _assistant({"type": "text", "text": "Si', e' cosi'."})
    assert _stop(tmp_path, USER, short) == "", "a short answer with no work is not a turn of substance"
    memory_only = _assistant(_tool("mcp__gray-matter__pre_turn", topic="x"),
                             {"type": "text", "text": "ok"})
    assert _stop(tmp_path, USER, memory_only, RESULT) == "", "memory tools are not work"
    ack = {"type": "user", "message": {"content": "grazie"}}
    assert _stop(tmp_path, ack, _assistant(_tool("Edit")), RESULT) == ""
    long = _assistant({"type": "text", "text": "x" * mh.SUBSTANTIVE_CHARS})
    assert _stop(tmp_path, USER, long) == mh.REMIND, "a long answer is a turn of substance"


def test_no_transcript_no_block(tmp_path):
    assert mh.save({"transcript_path": str(tmp_path / "missing.jsonl")}) == ""


def test_the_stop_output_is_the_block_shape(monkeypatch):
    import io
    import sys
    monkeypatch.setattr(mh, "save", lambda p: "torna al lavoro")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{}')))
    buf = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buf, encoding="utf-8"))
    mh.main(["memhook", "save"])
    sys.stdout.flush()
    assert json.loads(buf.getvalue().decode("utf-8")) == {"decision": "block",
                                                           "reason": "torna al lavoro"}


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


def test_a_down_daemon_costs_the_hook_half_a_second_not_two(monkeypatch):
    """On Windows a refused connection to localhost is retried for ~2 s.
    The hook runs on every message: with the daemon down it must fail fast."""
    import socket
    import time
    import gray_matter.cli as cli
    with socket.socket() as s:                   # a free port, then closed
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(cli, "resolve_port", lambda: port)
    t = time.perf_counter()
    out = mh.recall({"prompt": "una domanda abbastanza lunga"})
    assert out == ""
    assert time.perf_counter() - t < 1.5
