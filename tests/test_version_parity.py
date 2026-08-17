"""All three CLIs must answer `--version` the same way.

Each installer's final line asks its tool for the version to print the
completion banner. All three got that wrong in a different way:

* `neuron --version`      fell through to the stdio MCP server and HUNG;
* `neurag --version`      died with an argparse "required: command" usage error;
* `gray-matter --version` did the same (exit 2).

So the last thing every install did was run a broken command — which is what
"it finished but never said so" looked like from the outside. One test, because
one of the three passing proves nothing about the others.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

CASES = [
    ("neuron", ["-m", "neuron", "--version"], "neuron"),
    ("neurag", ["-m", "neurag.cli", "--version"], "neurag"),
    ("gray-matter", ["-m", "gray_matter.cli", "--version"], "gray_matter"),
]


def _ask_version(argv, mod):
    """Run the CLI, with the child pinned to the package the PARENT imported.

    The child gets a fresh interpreter and therefore no root conftest, which is
    what puts each tool's real package first on sys.path. Without the pin,
    `import neuron` in the child resolved whatever was installed elsewhere on
    the machine -- measured 2026-08-17: a 5.4.1 checkout in PycharmProjects,
    against a working tree at 6.4.0. Both tests below failed for neuron on code
    nobody had touched, and the dunder comparison was quietly meaningless: it
    read `__version__` from one install and `--version` from another. Deriving
    the path from `mod.__file__` keeps the two halves the same package by
    construction, whichever tool the case is for and wherever it lives.

    timeout is the point, not a nicety: the neuron bug was an infinite block on
    stdin. stdin=DEVNULL is deliberately NOT used -- that instant EOF is what
    masked the hang everywhere it was checked by hand.
    """
    root = str(Path(mod.__file__).resolve().parents[1])
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join(
               p for p in (root, os.environ.get("PYTHONPATH", "")) if p)}
    return subprocess.run([sys.executable, *argv], capture_output=True,
                          text=True, timeout=60, env=env)


@pytest.mark.parametrize("label,argv,module", CASES)
def test_version_exits_zero_and_prints_something(label, argv, module):
    mod = pytest.importorskip(module)
    proc = _ask_version(argv, mod)

    assert proc.returncode == 0, f"{label} --version exited {proc.returncode}: {proc.stderr[-400:]}"
    printed = proc.stdout.strip()
    assert printed, f"{label} --version printed nothing (banner would show a blank version)"
    assert printed.splitlines()[-1][0].isdigit(), (
        f"{label} --version should end with a version number, got: {printed[-120:]}")


@pytest.mark.parametrize("label,argv,module", CASES)
def test_version_matches_the_package_dunder(label, argv, module):
    mod = pytest.importorskip(module)
    proc = _ask_version(argv, mod)
    assert proc.stdout.strip().splitlines()[-1] == mod.__version__
