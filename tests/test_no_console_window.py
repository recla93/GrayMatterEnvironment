"""No background process may pop a visible CMD window.

Mirrors gray_matter/tests/test_no_console_window.py and neuron/tests's copy —
neurag.cli's `start` command had the identical CREATE_NO_WINDOW |
DETACHED_PROCESS bug (Windows ignores CREATE_NO_WINDOW when combined with
DETACHED_PROCESS -- the detached child allocates its own console), caught by
neither of those since they only scan their own package.
"""
import os
import re

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="flag solo Windows")


def _code_of(obj) -> str:
    """Source without comments, so a flag NAMED in a comment explaining its
    absence can't make this pass (or fail) for the wrong reason."""
    import inspect
    import io
    import tokenize

    src = inspect.getsource(obj)
    lines = src.splitlines()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col]
    return "\n".join(lines)


def test_cli_start_spawn_has_no_window():
    from neurag import cli as cli_mod

    for name in dir(cli_mod):
        fn = getattr(cli_mod, name)
        if not callable(fn) or not hasattr(fn, "__code__"):
            continue
        try:
            src = _code_of(fn)
        except (OSError, TypeError):
            continue
        for m in re.finditer(r"flags\s*=\s*(0x[0-9A-Fa-f]+(?:\s*\|\s*0x[0-9A-Fa-f]+)*)", src):
            expr = m.group(1)
            if expr == "0" or "|" not in expr:
                continue  # CREATE_NO_WINDOW alone (or no flags) is fine
            assert "0x00000008" not in expr, (
                f"DETACHED_PROCESS present alongside CREATE_NO_WINDOW: {expr!r} "
                f"in neurag.cli.{name}"
            )
