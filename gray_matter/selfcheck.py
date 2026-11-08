"""Runnable self-check for Gray-Matter's pure logic (no MCP/registry needed).

    python selfcheck.py      (run from inside the gray_matter/ folder)

Uses a temp bridge store (GRAY_MATTER_BRIDGES) so it never touches the real one.
Raises AssertionError on regression, else prints ALL OK.
"""
import os
import sys
import tempfile
from pathlib import Path

# Isolate the bridge store to a temp file BEFORE importing bridges.
os.environ["GRAY_MATTER_BRIDGES"] = str(Path(tempfile.mkdtemp()) / "bridges.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gray_matter.bridges import add_bridge, bridges_for, all_bridges


def check_bridges() -> None:
    assert add_bridge("JVM bytecode", "Java/Compilation", "both about class loading") is True
    assert add_bridge("JVM bytecode", "Java/Compilation") is False   # idempotent
    assert len(all_bridges()) == 1
    assert bridges_for("tell me about jvm bytecode internals"), "recall on Neuron endpoint failed"
    assert bridges_for("java/compilation"), "recall on NeuRAG endpoint failed"
    assert not bridges_for("garbage collection"), "unrelated topic must not match"
    print("OK bridges: add (idempotent) + recall on either endpoint")


if __name__ == "__main__":
    check_bridges()
    print("ALL OK")
