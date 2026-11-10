"""The memory ledger (gray_matter/bench/ledger.py) on a synthetic transcript."""
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "ledger", Path(__file__).resolve().parents[1] / "bench" / "ledger.py")
ledger = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ledger)

RECALL = ('[neuron] ctx=x\n<recalled-memory>\n[fix] the installer writes to deploy_hooks.py '
          'under claude_pzs8sxrjxfjjc (installer) #aaaaaaaa\n'
          '[idea] unrelated idea about something_else_entirely (x) #bbbbbbbb\n</recalled-memory>')


def _assistant(mid, blocks, out=10):
    return {"type": "assistant", "message": {"id": mid, "content": blocks, "usage": {
        "input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": out,
        "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}}}}


def _write(tmp_path, entries):
    p = tmp_path / "proj" / "s1234567.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return p


def test_costs_uses_and_work_on_one_session(tmp_path):
    p = _write(tmp_path, [
        {"type": "attachment", "attachment": {"type": "hook_additional_context",
                                              "hookEvent": "UserPromptSubmit", "content": [RECALL]}},
        {"type": "user", "message": {"role": "user", "content": "where does it write?"}},
        # two entries of ONE request: counted once
        _assistant("m1", [{"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x"}}]),
        _assistant("m1", [{"type": "text", "text": "thinking"}]),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        _assistant("m2", [{"type": "text", "text": "It writes deploy_hooks.py in claude_pzs8sxrjxfjjc."},
                          {"type": "tool_use", "id": "t2", "name": "mcp__gray-matter__store_turn",
                           "input": {"facts": [{"kind": "fix", "text": "y", "supersedes": "#cccccccc"}]}}]),
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2",
                                                   "content": "facts: 1 saved — #dddddddd fix"}]}},
        _assistant("m3", [{"type": "text", "text": "done"}]),
    ])
    r = ledger.analyze(p)
    assert r["turns"] == 1 and r["requests"] == 3
    assert r["explore_calls"] == 1 and r["mem_calls"] == 1
    assert r["facts_shown"] == 2                     # its own write #dddddddd is not "shown"
    assert r["facts_used"] == 0 and r["facts_silent"] == 1    # #aaaaaaaa reused, #bbbbbbbb not
    assert r["any_use_rate"] == 0.5
    # the recall is written once and read by the 3 later requests
    tok = len(RECALL) / ledger.CHARS_PER_TOKEN
    assert r["mem_overhead_iet"] >= round(tok * (ledger.W_CW1H + 3 * ledger.W_CR))
    assert 0 < r["mem_share"] < 1


def test_a_word_from_the_users_own_message_proves_nothing():
    words = ledger.distinctive("the installer writes deploy_hooks.py on 10/11")
    assert "10/11" not in words                      # dates prove nothing
    assert ledger.silently_used(words, "deploy_hooks.py and installer")
    assert not ledger.silently_used(words, "deploy_hooks.py and installer",
                                    prompt="why does deploy_hooks.py touch the installer?")
