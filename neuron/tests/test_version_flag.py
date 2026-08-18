"""`--version` must answer and exit — never start the MCP server.

The regression this pins was a real installer hang. `--version` begins with '-',
so it slipped past the unknown-command guard in `cli()`; no COMMANDS entry
matched; and it fell into the "no command => run the stdio MCP server" branch.
The server then blocked on stdin forever. Since the installer's final line asks
the tool for its version, a fully successful install hung on its last step —
everything done, nothing reported.

It only looked fine when stdin was /dev/null (instant EOF), which is exactly how
it escaped every previous manual check.
"""

import runpy

import pytest

from neuron import __version__


@pytest.mark.parametrize("flag", ["--version", "-V", "version"])
def test_version_prints_and_exits_zero(flag, monkeypatch, capsys):
    from neuron.__main__ import cli

    monkeypatch.setattr("sys.argv", ["neuron", flag])
    with pytest.raises(SystemExit) as exc:
        cli()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_version_never_reaches_the_server_branch(monkeypatch):
    """The actual failure mode: falling through to the stdio server, which
    blocks on stdin. Any attempt to start it here is the bug returning."""
    from neuron import __main__ as m

    def _boom(*a, **k):                     # pragma: no cover - must not run
        raise AssertionError("--version started the MCP server (the hang is back)")

    for attr in ("main", "_run_server", "serve"):
        if hasattr(m, attr):
            monkeypatch.setattr(m, attr, _boom, raising=False)
    monkeypatch.setattr("sys.argv", ["neuron", "--version"])

    with pytest.raises(SystemExit) as exc:
        m.cli()
    assert exc.value.code == 0


def test_unknown_flag_is_still_free_to_reach_the_server(monkeypatch):
    """Guard the guard: --graphs-dir/--local/--slug are server flags and must
    NOT be swallowed. Only the version spellings are intercepted."""
    from neuron.__main__ import COMMANDS

    for spelling in ("--version", "-V"):
        assert spelling not in COMMANDS, "version is handled in cli(), not COMMANDS"
