from server.knowledge import graph_tools as gt, physical_graph as pg


def test_existing_evidence_tool_returns_only_linked_static_stat_text():
    source = pg.GraphSource(
        source_id="pob:fixture", kind="pinned_pob_passive_tree", source_file="fixture.json"
    )
    text_source = pg.GraphSource(
        source_id="pob:fixture_text", kind="pinned_pob_passive_tree", source_file="text.json"
    )
    nodes = (
        pg.GraphNode("notable:fixture:a", "notable", "Fixture A", (source.source_id,)),
        pg.GraphNode("notable:fixture:b", "notable", "Fixture B", (source.source_id,)),
        pg.GraphNode("stat:fixture:a", "passive_stat_text", "Grants Fixture Buff", (text_source.source_id,)),
        pg.GraphNode("stat:fixture:b", "passive_stat_text", "Other node text", (source.source_id,)),
    )
    snapshot = pg.build_snapshot(
        sources=(source, text_source), nodes=nodes,
        edges=(
            pg.GraphEdge("has_stat_text", "notable:fixture:a", "stat:fixture:a", (source.source_id,)),
            pg.GraphEdge("has_stat_text", "notable:fixture:b", "stat:fixture:b", (source.source_id,)),
        ),
    )
    result = gt.GraphQueryService(snapshot).run_tool(
        "explain_graph_evidence", {"node_key": "notable:fixture:a"}
    )
    assert result["status"] == "known"
    assert result["facts"]["statTexts"] == [{
        "stableKey": "stat:fixture:a", "text": "Grants Fixture Buff", "sourceRefs": [text_source.source_id]
    }]
    assert result["facts"]["statTextScope"] == "static_snapshot_not_allocation_or_application"
    assert result["evidencePath"]["snapshotId"] == snapshot.snapshot_id
    assert result["evidencePath"]["nodes"] == ["notable:fixture:a", "stat:fixture:a"]
    assert len(result["evidencePath"]["edges"]) == 1
    assert result["sourceRefs"] == [source.source_id, text_source.source_id]
