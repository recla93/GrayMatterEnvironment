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

import subprocess
import sys

import pytest

CASES = [
    ("neuron", ["-m", "neuron", "--version"], "neuron"),
    ("neurag", ["-m", "neurag.cli", "--version"], "neurag"),
    ("gray-matter", ["-m", "gray_matter.cli", "--version"], "gray_matter"),
]


@pytest.mark.parametrize("label,argv,module", CASES)
def test_version_exits_zero_and_prints_something(label, argv, module):
    pytest.importorskip(module)

    # timeout is the point, not a nicety: the neuron bug was an infinite block
    # on stdin. stdin=DEVNULL is deliberately NOT used — that instant EOF is
    # what masked the hang everywhere it was checked by hand.
    proc = subprocess.run(
        [sys.executable, *argv],
        capture_output=True, text=True, timeout=60,
    )

    assert proc.returncode == 0, f"{label} --version exited {proc.returncode}: {proc.stderr[-400:]}"
    printed = proc.stdout.strip()
    assert printed, f"{label} --version printed nothing (banner would show a blank version)"
    assert printed.splitlines()[-1][0].isdigit(), (
        f"{label} --version should end with a version number, got: {printed[-120:]}")


@pytest.mark.parametrize("label,argv,module", CASES)
def test_version_matches_the_package_dunder(label, argv, module):
    mod = pytest.importorskip(module)
    proc = subprocess.run([sys.executable, *argv], capture_output=True, text=True, timeout=60)
    assert proc.stdout.strip().splitlines()[-1] == mod.__version__
