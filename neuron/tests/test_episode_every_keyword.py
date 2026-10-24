"""A turn's fact is reachable from any of its keywords, and shown once.

It was attached to the first keyword only. Reported twice on 2026-10-24: the
proxy bug filed under `turso` was missed by a search on `firewall`, and the
Safari dropdown fact on `primeng` by a question that landed on `focus`.
"""

import asyncio

from neuron import server as S
from neuron.registry import GraphRegistry

FACT = "Su Safari il p-dropdown in una p-dialog perde il focus: appendTo body."


def test_the_fact_comes_back_from_any_keyword_once(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_g", GraphRegistry(graphs_dir=str(tmp_path)))
    call = lambda tool, args: asyncio.run(S.call_tool(tool, args))[0].text
    call("store_turn", {"topic": "bug p-dropdown in modale Safari",
                        "keywords": ["primeng", "dropdown", "safari", "focus"],
                        "episode": FACT})

    only_top = call("pre_turn", {"topic": "focus", "keywords": ["focus"],
                                 "fact_nodes": 1})
    assert FACT in only_top, f"il fatto non arriva dal nodo trovato: {only_top}"

    wide = call("pre_turn", {"topic": "focus", "keywords": ["focus"],
                             "fact_nodes": 4, "max_tokens": 2000})
    assert wide.count(FACT) == 1, f"lo stesso fatto ripetuto: {wide}"
