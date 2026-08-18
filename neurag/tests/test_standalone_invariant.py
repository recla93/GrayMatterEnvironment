"""I2 — NeuRAG alone must never need Neuron or Gray Matter.

DESIGN-EVOLUTION §7 states this is "enforced structurally too: no top-level
import of `neuron` or `gray_matter` anywhere in `neurag/` — assert on the
import graph, not on intent". It said so through P0-P3 without a test to say
it.

Asserted as the invariant, not as the convention: the peers are made
unimportable and NeuRAG's modules must still load. That is what "standalone"
means, and it also covers a dependency introduced three modules away, which
scanning for `^import` would miss.

It is deliberately NOT a ban on naming a peer at module level. `server.py`
imports `gray_matter.server` inside a `try/except ImportError` that sets
`_GM_AVAILABLE = False` — the peer is optional, and a guarded import is how a
module says so. What matters is that the absence is a branch, not a crash.
"""
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

MODULES = ["neurag.db", "neurag.cli", "neurag.chunker", "neurag.embedder",
           "neurag.reranker", "neurag.ingest", "neurag.paths", "neurag.settings",
           "neurag.clients", "neurag.server"]

_PROBE = '''
import sys

BLOCKED = ("neuron", "gray_matter")


class Blocker:
    """Make the peers unimportable, exactly as on a standalone install."""

    def find_module(self, name, path=None):
        return self.find_spec(name, path)

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ImportError(f"I2: {name} must not be needed by neurag")
        return None


sys.meta_path.insert(0, Blocker())
missing = []
for mod in %r:
    try:
        __import__(mod)
    except ImportError as e:
        if "I2:" in str(e):
            raise
        missing.append(f"{mod}: {e}")      # optional third-party dep, not a peer
print("MISSING " + "; ".join(missing) if missing else "ALL IMPORTED")
print("OK")
'''


def test_neurag_modules_import_with_both_peers_unavailable():
    r = subprocess.run([sys.executable, "-c", _PROBE % MODULES],
                       capture_output=True, text=True, timeout=300,
                       cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert "I2:" not in r.stderr, (
        f"NeuRAG needs a peer at module load time:\n{r.stderr[-1500:]}")
    assert r.returncode == 0, r.stderr[-1500:]
    assert "OK" in r.stdout


def test_the_probe_would_actually_catch_a_violation():
    """A blocker that blocks nothing would make the test above pass forever."""
    probe = _PROBE % ["gray_matter.server"]
    r = subprocess.run([sys.executable, "-c", probe],
                       capture_output=True, text=True, timeout=300,
                       cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r.returncode != 0 and "I2:" in r.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
