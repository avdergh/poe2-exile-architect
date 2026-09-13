from pipeline import build_corpus
from server.knowledge import physical_graph as graph


RAW = """Versioned Ward
Iron Ring
Version: Legacy
Version: Current
{version:1}+10 to maximum Life
{version:2}+20 to maximum Mana
"""


def test_corpus_and_graph_keep_version_conditions_in_readable_mods(tmp_path, monkeypatch):
    source = tmp_path / "ring.lua"
    source.write_text("return {[[" + RAW + "]]}", encoding="utf-8")
    monkeypatch.setattr(build_corpus, "UNIQUES_DIR", tmp_path)
    monkeypatch.setattr(build_corpus, "GENERATED_UNIQUES_FILE", tmp_path / "absent.lua")
    unique = build_corpus.parse_uniques()[0]
    expected = {
        "[Version: Legacy] +10 to maximum Life",
        "[Version: Current] +20 to maximum Mana",
    }
    assert unique["base"] == "Iron Ring"
    assert set(unique["text"].splitlines()[2:]) == expected
    assert unique["raw"] == RAW.strip()
    ingested = graph.ingest_uniques(
        source, source=graph.GraphSource("pob:test", "pinned_pob_unique_text", "ring.lua")
    )
    assert {node.display_name for node in ingested.nodes if node.node_type == "unique_mod_text"} == expected
