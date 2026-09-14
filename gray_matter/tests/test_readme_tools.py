"""Ogni tool MCP che i server annunciano compare nel README del suo progetto.

Le tabelle erano scritte a mano: Neuron documentava `neuron_pre_turn` — un
prefisso mai esistito — e NeuRAG ometteva otto tool su diciannove. Il test
legge i nomi dal sorgente (`name="..."` nelle Tool()) e li cerca nel README.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CASES = [
    ("neuron", ROOT / "neuron" / "src" / "neuron" / "server.py", ROOT / "neuron" / "README.md"),
    ("neurag", ROOT / "neurag" / "server.py", ROOT / "neurag" / "README.md"),
    ("gray_matter", ROOT / "gray_matter" / "server.py", ROOT / "gray_matter" / "README.md"),
]


@pytest.mark.parametrize("proj,src,readme", CASES, ids=[c[0] for c in CASES])
def test_every_served_tool_is_in_the_readme(proj, src, readme):
    if not src.exists():
        pytest.skip(f"{proj} non e' in questo albero (standalone)")
    served = set(re.findall(r'\bname="([a-z_]+)"', src.read_text(encoding="utf-8")))
    served = {t for t in served if proj != "gray_matter" or t.startswith("gray_matter_")}
    assert served, f"{src}: nessun Tool(name=...) trovato"
    doc = readme.read_text(encoding="utf-8")
    missing = sorted(t for t in served if f"`{t}" not in doc and f"_{t}" not in doc)
    assert not missing, f"{proj}/README.md non documenta: {missing}"
