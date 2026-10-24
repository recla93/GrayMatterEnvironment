"""The seed is Neuron's own manual, not the user's memory.

`get()` used to warm-start every empty context from `base_knowledge.db`: 29
nodes about Neuron itself (`store_turn`, `dedup`, `consolidate`...). They then
answered searches in place of the user's concepts — reported 2026-10-24 on a
fresh install: "menu a tendina che perde il focus" returned only those nodes,
nothing about the PrimeNG note just stored.
"""

import sqlite3
import tempfile

from neuron.models import Graph, Link, Node
from neuron.registry import GraphRegistry


def test_a_new_context_starts_empty():
    reg = GraphRegistry(graphs_dir=tempfile.mkdtemp(prefix="seedfree_"))
    assert reg.get("default").nodes == []
    assert reg.get("backend").nodes == [], "nemmeno i nodi del seed con quel dominio"


def test_an_old_seed_copy_goes_and_the_users_work_stays():
    """A graph warm-started back then: the seed rows plus the user's turns.

    Only what is still exactly as shipped goes. A seed concept the user worked
    with stays — topic rewritten by store_turn, an episode, a link of theirs.
    """
    graphs_dir = tempfile.mkdtemp(prefix="seedclean_")
    seed_path = GraphRegistry(graphs_dir=graphs_dir)._seed_path
    c = sqlite3.connect(seed_path)
    seed_nodes = c.execute("SELECT keyword, topic, domain FROM nodes").fetchall()
    seed_links = c.execute(
        "SELECT source, target, link_type, weight FROM links").fetchall()
    c.close()

    g = Graph()
    for kw, topic, domain in seed_nodes:
        g.add_node(Node(keyword=kw, turn=0, topic=topic, domain=domain,
                        sentiment="neutral", salience=1))
    for s, t, lt, w in seed_links:
        g.add_link(Link(source=s, target=t, link_type=lt, weight=w, rationale="",
                        created_turn=0, last_active_turn=0))
    g.add_node(Node(keyword="pdf", turn=1, topic="estrazione testo",
                    domain="general", sentiment="neutral", salience=3))
    g.get_node("store_turn").topic = "salvare i turni a fine risposta"
    g.add_episode("dedup", "deciso di tenerlo acceso", 1)
    g.add_link(Link(source="flash", target="pdf", link_type="analogy",
                    weight="medium", rationale="", created_turn=2, last_active_turn=2))
    g.save_sqlite(f"{graphs_dir}/graph_default.db", context="default")

    for reg in (GraphRegistry(graphs_dir=graphs_dir),   # cleans and saves
                GraphRegistry(graphs_dir=graphs_dir)):  # reads it back from disk
        cg = reg.get("default")
        kws = {n.keyword for n in cg.nodes}
        assert kws == {"pdf", "store_turn", "dedup", "flash"}, kws
        assert all(lk.source in kws and lk.target in kws for lk in cg.links), \
            "un link del seed punta a un nodo rimosso"
        assert any((lk.source, lk.target) == ("flash", "pdf") for lk in cg.links)
        assert cg.recent_episodes("dedup", 1), "l'episodio dell'utente e' sparito"
