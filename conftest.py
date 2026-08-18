"""Workspace-root pytest config — makes `pytest` work from here without
PYTHONPATH gymnastics (PIANO-AZIONE FASE 0).

Two entries, and the ORDER matters:

1. ``neuron/src`` first. Neuron uses a src layout, so the real package is
   ``neuron/src/neuron``. The workspace also contains a directory literally
   named ``neuron/`` — with the root on sys.path first, ``import neuron``
   resolves to that directory as an empty *namespace* package and every
   ``neuron.paths`` / ``neuron.clients`` import fails (this is what made
   gray_matter/tests/test_cross_project.py fail with 4 errors: GM's tests
   collect before neuron/tests/conftest.py has a chance to fix the path).
2. the workspace root, so flat-layout ``gray_matter`` and ``neurag`` import
   without being pip-installed.

ONE SUITE PER PROCESS
---------------------
This file used to end with "run everything with a bare ``pytest`` from this
folder", which contradicted ``pytest.ini`` two lines away and did not work:
``neuron/tests/_mockdeps.py`` injects fake ``mcp``/``fastembed`` and
``turso = None`` into ``sys.modules`` at import time, while ``neurag.db``
captures ``TURSO_AVAILABLE`` at ITS import time, so one shared process leaks the
fakes across repos and invents ~25 failures.

What a bare ``pytest`` actually produced was neither the leak nor a useful
message: collection died first on two basenames that exist in two suites
(``test_no_console_window.py``, ``test_version_consistency.py``) with an "import
file mismatch" hint about ``__pycache__``. Renaming them would have been the
worse repair -- it turns a loud stop into a quiet, wrong run.

So the constraint is enforced here instead of documented and hoped for.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_TOOLS = ("neuron", "gray_matter", "neurag")

for _p in (_ROOT, os.path.join(_ROOT, "neuron", "src")):
    # inserted in this order so neuron/src ends up at index 0 and wins
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)


def _tool_of(arg: str) -> "str | None":
    """Which tool's tree an invocation argument points into, if any."""
    path = arg.split("::", 1)[0]                  # drop a ::test_name selector
    try:
        rel = os.path.relpath(os.path.abspath(path), _ROOT)
    except ValueError:                            # different drive on Windows
        return None
    head = rel.replace(os.altsep or os.sep, os.sep).split(os.sep)[0]
    return head if head in _TOOLS else None


def pytest_configure(config):
    """Stop a cross-suite run before collection, and say what to type instead."""
    targeted = {t for a in config.args if (t := _tool_of(a))}
    if len(targeted) == 1:
        return
    import pytest
    raise pytest.UsageError(
        # plain ASCII: this message is read on a cp1252 console, where an
        # em-dash arrives as a replacement character.
        "run one suite per process - the three leak fake modules into each "
        "other (see pytest.ini).\n"
        "    pytest neuron/tests\n"
        "    pytest gray_matter/tests\n"
        "    pytest neurag/tests\n"
        + (f"  got: {', '.join(sorted(targeted))}" if targeted else
           "  got: no suite selected"))
