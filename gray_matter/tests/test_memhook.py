"""ADR-014: l'hook porta il contesto da solo, e non rompe mai il messaggio."""
import json

from gray_matter import memhook as mh


def test_acks_commands_and_short_text_are_not_recalled():
    for p in ("ok", "Sì.", "grazie!", "/ponytail lite", "   ", "corto"):
        assert not mh.worth_recalling(p), p
    assert mh.worth_recalling("Come mai GM non è partito?")


def test_flash_takes_the_first_dormant_concept():
    out = ("Dormant & mid-band related to 'x':\n"
           "  episodi-append-only  last_turn=189  (6 turns ago)  salience=4\nTotal: 1 concepts")
    assert mh.flash_concept(out) == "episodi-append-only"
    assert mh.flash_concept("") == ""


def test_kb_pointer_only_above_threshold():
    hit = "Top 1 results:\n  [1] docs/A.md :: Titolo (2/5)  (cos 0.61)\n"
    low = "Top 1 results:\n  [1] docs/A.md :: Titolo (2/5)  (cos 0.40)\n"
    assert "docs/A.md" in mh.kb_pointer(hit)
    assert mh.kb_pointer(low) == ""


def test_compose_skips_a_flash_already_in_context_and_respects_budget():
    assert "⚡" not in mh.compose("nodes: flash(1)", "flash", "")
    assert "⚡ Ne avevate già parlato: around" in mh.compose("ctx", "around", "")
    assert len(mh.compose("x" * 5000, "around", "")) == mh.BUDGET


def test_no_daemon_no_output(monkeypatch):
    import gray_matter.cli as cli
    monkeypatch.setattr(cli, "gm_answers", lambda *a, **k: False)
    assert mh.recall({"prompt": "una domanda abbastanza lunga"}) == ""


def test_a_flash_is_shown_once_per_session(monkeypatch, tmp_path):
    monkeypatch.setattr(mh.tempfile, "gettempdir", lambda: str(tmp_path))
    assert mh._take_new("s1", "around")
    assert not mh._take_new("s1", "around")
    assert mh._take_new("s2", "around")


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
