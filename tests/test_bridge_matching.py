"""Come un bridge viene trovato: token interi e identità di tag, non sottostringhe.

`bridges_for` matchava con `endpoint in topic or topic in endpoint`. È lo stesso
difetto che il cue scan di NeuRAG aveva prima di P0, sulla stessa classe di
parole tecniche corte: un endpoint chiamato `ast` matchava "fastembed install",
`cache` matchava "cached", e un bridge che salta fuori in una pulse viene anche
RINFORZATO — quindi il rumore si consolidava da solo.

La seconda metà è il join che DESIGN-EVOLUTION §4 chiede: NeuRAG risolve il topic
nei nomi canonici dei suoi tag e GM matcha su quelli. Raggiunge un bridge il cui
nodo si chiama in un modo che non dice niente del topic, mentre i suoi tag sì.
"""
import pytest


@pytest.fixture
def B(tmp_path, monkeypatch):
    import importlib

    from gray_matter import bridges
    monkeypatch.setenv("GRAY_MATTER_BRIDGES", str(tmp_path / "bridges.db"))
    importlib.reload(bridges)
    return bridges


# ---------- il contratto che c'era già (selfcheck.check_bridges) ----------

def test_an_endpoint_is_found_inside_a_longer_topic(B):
    B.add_bridge("JVM bytecode", "Java/Compilation", "class loading")
    assert B.bridges_for("tell me about jvm bytecode internals")
    assert B.bridges_for("java/compilation")
    assert not B.bridges_for("garbage collection")


def test_a_topic_shorter_than_the_endpoint_still_matches(B):
    """L'altra direzione: chiedere "bytecode" deve trovare "JVM bytecode"."""
    B.add_bridge("JVM bytecode", "Java/Compilation")
    assert B.bridges_for("bytecode")


# ---------- il bug ----------

@pytest.mark.parametrize("endpoint,topic", [
    ("ast", "fastembed install"),        # ast dentro fastembed
    ("cache", "the request was cached"),  # cache dentro cached
    ("int", "print the value"),           # int dentro print
    ("io", "the audio file"),             # io dentro audio
])
def test_an_endpoint_no_longer_matches_inside_a_longer_word(B, endpoint, topic):
    B.add_bridge(endpoint, f"Node_{endpoint}")
    assert B.bridges_for(topic) == [], (
        f"'{endpoint}' ha matchato '{topic}' come sottostringa")


@pytest.mark.parametrize("endpoint,topic", [
    ("ast", "walking the ast here"),
    ("cache", "cache invalidation"),
    ("int", "an int overflow"),
])
def test_but_it_does_match_the_whole_word(B, endpoint, topic):
    B.add_bridge(endpoint, f"Node_{endpoint}")
    assert B.bridges_for(topic), f"'{endpoint}' non ha matchato '{topic}'"


def test_a_multi_word_endpoint_needs_its_words_adjacent(B):
    B.add_bridge("vector search", "Retrieval")
    assert B.bridges_for("how does vector search work")
    assert B.bridges_for("vector based search of documents") == [], (
        "le due parole non sono contigue: non è quell'endpoint")


def test_noise_no_longer_reinforces_itself(B):
    """Una pulse che fa emergere un bridge lo rinforza. Con il match a
    sottostringa un bridge rumoroso si consolidava da solo a ogni pulse."""
    B.add_bridge("ast", "Parser")
    for _ in range(6):
        B.bridges_for("fastembed installation")
    assert B.all_bridges()[0]["weight"] == 1, "il peso è salito su un falso match"
    assert B.all_bridges()[0]["promoted"] == 0


# ---------- il join per identità di tag (§4) ----------

def test_a_bridge_is_reachable_through_the_tags_of_its_node(B):
    """Il nome del nodo non contiene niente del topic; i suoi tag sì."""
    B.add_bridge("coordinatore", "Appunti_Sparsi")
    topic = "quali strumenti abbiamo per il consenso distribuito"
    assert B.bridges_for(topic) == []
    assert B.bridges_for(topic, tags={"appunti_sparsi"}), (
        "l'identità di tag deve raggiungere ciò che il nome non raggiunge")


def test_the_neuron_endpoint_joins_on_tags_too(B):
    B.add_bridge("quorum", "Spec")
    assert B.bridges_for("un topic senza quelle parole", tags={"quorum"})


def test_tag_matching_is_identity_not_containment(B):
    """Un tag è una chiave, non un frammento: `quorum` non è `quorumless`."""
    B.add_bridge("quorum", "Spec")
    assert B.bridges_for("topic muto", tags={"quorumless"}) == []
    assert B.bridges_for("topic muto", tags={"QUORUM "}), "normalizzato, non case-sensitive"


def test_tags_are_optional_and_empty_changes_nothing(B):
    B.add_bridge("JVM bytecode", "Java/Compilation")
    with_none = len(B.bridges_for("jvm bytecode"))
    assert len(B.bridges_for("jvm bytecode", tags=None)) == with_none
    assert len(B.bridges_for("jvm bytecode", tags=set())) == with_none
    assert len(B.bridges_for("jvm bytecode", tags={"", "  "})) == with_none


def test_an_empty_topic_still_matches_nothing(B):
    B.add_bridge("quorum", "Spec")
    assert B.bridges_for("") == []
    assert B.bridges_for("   ") == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
