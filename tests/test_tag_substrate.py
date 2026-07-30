"""P1 — the tag substrate (DESIGN-EVOLUTION §4).

Gates for the phase: the migration is idempotent, and the link count stays
within 2x of what the legacy JSON path produced. Both are asserted below, plus
the two things that only exist because tags became rows: normalization as a
join key, and IDF suppression of a tag that predicts everything.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from neurag.db import KnowledgeGraph


def _kg(path=":memory:"):
    return KnowledgeGraph(pathlib.Path(path))


def _tags_of(kg, node_id):
    return {r["name"] for r in kg._conn.execute(
        "SELECT t.name AS name FROM node_tags nt JOIN tags t ON t.id = nt.tag_id "
        "WHERE nt.node_id = ?", (node_id,)).fetchall()}


# ---------- schema ----------

def test_schema_creates_tag_tables():
    kg = _kg()
    tables = {r[0] for r in kg._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"tags", "node_tags", "chunk_tags"} <= tables
    assert not kg._corrupt, kg._corrupt_err
    kg.close()


def test_a_semicolon_in_a_comment_does_not_truncate_the_schema():
    """There is no executescript on either backend, so the script is cut on
    ';' by hand. A ';' inside a `--` comment used to truncate the statement
    around it, and the table simply never appeared: the schema is applied
    inside a try/except that only sets `_corrupt`, so the failure was silent
    until a query hit the missing table. SCHEMA_SQL still contains such a
    comment on purpose -- it is the fixture."""
    from neurag.db import SCHEMA_SQL, _split_sql
    assert ";" in re.search(r"salience.*", SCHEMA_SQL).group(0)
    created = [s for s in _split_sql(SCHEMA_SQL) if "CREATE TABLE IF NOT EXISTS tags" in s]
    assert len(created) == 1
    assert "last_used" in created[0]          # the whole body, not the head of it
    assert created[0].count("(") == created[0].count(")")
    assert _split_sql("CREATE TABLE a (x INT);  -- one; two\nSELECT 1;") == [
        "CREATE TABLE a (x INT)", "SELECT 1"]


# ---------- normalization is the join key ----------

def test_tag_names_are_normalized_and_shared():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["Cache", " API "])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["cache", "api"])
    assert _tags_of(kg, a) == {"cache", "api"} == _tags_of(kg, b)
    # one row per atom, not one per spelling
    assert kg._conn.execute(
        "SELECT COUNT(*) FROM tags WHERE name IN ('cache','api')").fetchone()[0] == 2
    kg.close()


def test_uses_counts_nodes_carrying_the_tag():
    kg = _kg()
    for name in ("A", "B", "C"):
        kg.add_node(name, "fundamental", parent_id=0, tags=["shared"])
    kg.add_node("D", "fundamental", parent_id=0, tags=["lonely"])
    uses = dict(kg._conn.execute("SELECT name, uses FROM tags").fetchall())
    assert uses["shared"] == 3
    assert uses["lonely"] == 1
    kg.close()


def test_add_tags_syncs_both_sides():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0)
    kg.add_tags(a, ["Alpha", "beta"])
    # legacy column keeps the original spelling (still a read path)
    assert json.loads(kg.get_node(a)["tags"]) == ["Alpha", "beta"]
    assert _tags_of(kg, a) == {"alpha", "beta"}
    kg.close()


def test_delete_node_releases_its_tag_rows():
    kg = _kg()
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["x"])
    kg.add_node("B", "fundamental", parent_id=0, tags=["x"])
    kg.delete_node(a)
    assert kg._conn.execute(
        "SELECT COUNT(*) FROM node_tags WHERE node_id = ?", (a,)).fetchone()[0] == 0
    # I5: the tag row survives its last node; only the count moves
    assert kg._conn.execute(
        "SELECT uses FROM tags WHERE name = 'x'").fetchone()[0] == 1
    kg.close()


# ---------- migration ----------

def test_migration_backfills_legacy_json_and_is_idempotent(tmp_path):
    db = tmp_path / "legacy.db"
    kg = _kg(db)
    a = kg.add_node("A", "fundamental", parent_id=0, tags=["one", "two"])
    b = kg.add_node("B", "fundamental", parent_id=0, tags=["two"])
    # rewind to a pre-P1 vault: legacy column populated, substrate empty
    kg._conn.execute("DELETE FROM node_tags")
    kg._conn.execute("DELETE FROM tags")
    kg._conn.execute("DELETE FROM meta WHERE key = 'tags_migrated'")
    kg._conn.commit()
    kg.close()

    kg = _kg(db)
    assert _tags_of(kg, a) == {"one", "two"}
    assert _tags_of(kg, b) == {"two"}
    before = [tuple(r) for r in kg._conn.execute(
        "SELECT node_id, tag_id FROM node_tags ORDER BY node_id, tag_id").fetchall()]
    uses_before = dict(kg._conn.execute("SELECT name, uses FROM tags").fetchall())
    kg.close()

    # second open: flag set, nothing moves
    kg = _kg(db)
    after = [tuple(r) for r in kg._conn.execute(
        "SELECT node_id, tag_id FROM node_tags ORDER BY node_id, tag_id").fetchall()]
    assert after == before
    assert dict(kg._conn.execute("SELECT name, uses FROM tags").fetchall()) == uses_before
    kg.close()


# ---------- IDF suppression ----------

def _fan(kg, n, common="common"):
    for i in range(n):
        kg.add_node(f"N{i}", "fundamental", parent_id=0, tags=[common, f"uniq{i}"])


def test_small_vault_suppresses_nothing():
    """Below MIN_TAG_NODE_FLOOR a ratio is meaningless — every real cue counts."""
    kg = _kg()
    _fan(kg, 10)
    assert kg.build_tag_links() == 10 * 9 // 2
    kg.close()


def test_a_tag_on_half_the_vault_stops_generating_pairs():
    kg = _kg()
    n = kg.MIN_TAG_NODE_FLOOR + 10
    _fan(kg, n)
    # every pair shares `common` (jaccard 1/3, above the floor), so the
    # unsuppressed build would write n*(n-1)/2 links
    assert kg.build_tag_links() == 0
    kg.close()


def test_suppression_does_not_touch_the_similarity_measure():
    """A pair that shares an informative tag still links, and with the SAME
    weight — the common tag stays in the Jaccard denominator."""
    kg = _kg()
    n = kg.MIN_TAG_NODE_FLOOR + 10
    _fan(kg, n)
    x = kg.add_node("X", "fundamental", parent_id=0, tags=["common", "rare"])
    y = kg.add_node("Y", "fundamental", parent_id=0, tags=["common", "rare"])
    kg.build_tag_links()
    links = [l for l in kg.get_links(x) if l["other_name"] == "Y"]
    assert len(links) == 1
    assert links[0]["weight"] == 1.0          # {common,rare} identical on both
    assert links[0]["evidence"] == "common,rare"
    kg.close()


# ---------- chunk_tags ----------

def test_chunk_tags_written_and_replaced_on_reingest(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n",
                   encoding="utf-8")
    kg = _kg()
    node = kg.add_node("Code", "fundamental", parent_id=0)
    kg.index_into_node(src, node)
    rows = kg._conn.execute("SELECT COUNT(*) FROM chunk_tags").fetchone()[0]
    assert rows > 0

    kg.index_into_node(src, node)             # idempotent re-ingest
    assert kg._conn.execute("SELECT COUNT(*) FROM chunk_tags").fetchone()[0] == rows
    # no join row survives its chunk
    assert kg._conn.execute(
        "SELECT COUNT(*) FROM chunk_tags WHERE chunk_id NOT IN "
        "(SELECT id FROM chunks)").fetchone()[0] == 0
    kg.close()


# ---------- the phase gate: link count within 2x of the legacy path ----------

def test_link_count_matches_the_legacy_json_computation():
    """Same fixture, same links. The substrate changed WHERE tags are read
    from, not what a tag_overlap means."""
    kg = _kg()
    fixture = {
        "A": ["web", "api", "rest"],
        "B": ["api", "rest", "http"],
        "C": ["db", "sql"],
        "D": ["sql", "db", "index"],
        "E": ["web", "css"],
    }
    for name, tags in fixture.items():
        kg.add_node(name, "fundamental", parent_id=0, tags=tags)

    expected = 0
    names = sorted(fixture)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = set(fixture[names[i]]), set(fixture[names[j]])
            if len(a & b) / len(a | b) >= kg.MIN_TAG_JACCARD:
                expected += 1

    assert kg.build_tag_links() == expected > 0
    kg.close()
