"""No background process may pop a visible CMD window.

Mirrors gray_matter/tests/test_no_console_window.py, which caught the same
bug in gray_matter/server.py's daemon spawn but only scans that one module.
`neuron.__main__._start_cli` had the identical CREATE_NO_WINDOW |
DETACHED_PROCESS bug (Windows ignores CREATE_NO_WINDOW when combined with
DETACHED_PROCESS -- the detached child allocates its own console) and nothing
here would have caught it. This scans neuron's own spawn points directly.
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


def test_start_cli_spawn_has_no_window():
    from tests._mockdeps import install_mock_deps, unpoison_turso
    install_mock_deps()
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
    from neuron import __main__ as main_mod
    unpoison_turso()

    src = _code_of(main_mod._start_cli)
    for m in re.finditer(r"flags\s*=\s*(0x[0-9A-Fa-f]+(?:\s*\|\s*0x[0-9A-Fa-f]+)*)", src):
        expr = m.group(1)
        if expr == "0" or "|" not in expr:
            continue  # CREATE_NO_WINDOW alone (or no flags) is fine
        # CREATE_NO_WINDOW=0x08000000 paired with DETACHED_PROCESS=0x00000008:
        # Windows ignores CREATE_NO_WINDOW in that combination, the detached
        # child allocates its own (visible) console.
        assert "0x00000008" not in expr, (
            f"DETACHED_PROCESS present alongside CREATE_NO_WINDOW: {expr!r} "
            "in neuron.__main__._start_cli"
        )
