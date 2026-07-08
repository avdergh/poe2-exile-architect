from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts import export_phase4_memory_graph


def test_build_memory_graph_uses_safe_relationships(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    _create_fixture_db(db_path)

    graph = export_phase4_memory_graph.build_memory_graph(db_path)

    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = graph["edges"]

    assert "pattern:bdp-1" in nodes
    assert "component:skill:SparkPlayer" in nodes
    assert "semantic_edge:rse-1" in nodes
    assert {
        "source": "pattern:bdp-1",
        "target": "component:skill:SparkPlayer",
        "type": "uses_component",
    } in [_edge_identity(edge) for edge in edges]
    assert {
        "source": "component:skill:SparkPlayer",
        "target": "component:skill:CometPlayer",
        "type": "semantic_source_to_target",
    } in [_edge_identity(edge) for edge in edges]

    serialized = json.dumps(graph, ensure_ascii=False)
    assert "rawXml" not in serialized
    assert "rawImportCode" not in serialized
    assert "PathOfBuilding" not in serialized


def test_export_memory_graph_html_is_self_contained_and_safe(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    html_path = tmp_path / "graph.html"
    _create_fixture_db(db_path)

    report = export_phase4_memory_graph.export_memory_graph_html(db_path, html_path)

    html = html_path.read_text(encoding="utf-8")
    assert report["status"] == "written"
    assert report["nodeCount"] >= 4
    assert report["edgeCount"] >= 3
    assert "<svg" in html
    assert "const GRAPH_DATA =" in html
    assert "skill:SparkPlayer" in html
    assert "rawXml" not in html
    assert "rawImportCode" not in html
    assert "PathOfBuilding" not in html


def test_export_memory_graph_html_uses_stable_layout_not_infinite_animation(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    html_path = tmp_path / "graph.html"
    _create_fixture_db(db_path)

    export_phase4_memory_graph.export_memory_graph_html(db_path, html_path)

    html = html_path.read_text(encoding="utf-8")
    assert "settleLayout();" in html
    assert "requestAnimationFrame(tick)" not in html
    assert "function tick()" not in html


def test_export_memory_graph_html_click_does_not_relayout_without_drag(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    html_path = tmp_path / "graph.html"
    _create_fixture_db(db_path)

    export_phase4_memory_graph.export_memory_graph_html(db_path, html_path)

    html = html_path.read_text(encoding="utf-8")
    assert "let hasDragged = false;" in html
    assert "hasDragged = movement > 4;" in html
    assert "if (!hasDragged) {" in html
    assert "if (hasDragged) {" in html
    assert "settleLayout(45);" in html


def _edge_identity(edge: dict) -> dict[str, str]:
    return {
        "source": edge["source"],
        "target": edge["target"],
        "type": edge["type"],
    }


def _create_fixture_db(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE research_build_patterns (
            pattern_id TEXT PRIMARY KEY,
            pattern_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            component_keys TEXT NOT NULL,
            component_roles TEXT NOT NULL,
            confidence_tier TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            family_count INTEGER NOT NULL,
            source_case_refs TEXT NOT NULL,
            planner_hint TEXT,
            verification_tasks TEXT NOT NULL,
            status TEXT NOT NULL,
            planner_visible INTEGER NOT NULL
        );
        CREATE TABLE research_semantic_edges (
            edge_id TEXT PRIMARY KEY,
            source_key TEXT NOT NULL,
            target_key TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            rationale TEXT NOT NULL,
            source_case_refs TEXT NOT NULL,
            confidence TEXT NOT NULL,
            status TEXT NOT NULL,
            planner_visible INTEGER NOT NULL
        );
        CREATE TABLE research_fragments (
            fragment_id TEXT PRIMARY KEY,
            fragment_type TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            reusable_principle TEXT NOT NULL,
            component_keys TEXT NOT NULL,
            source_case_refs TEXT NOT NULL,
            confidence TEXT NOT NULL,
            status TEXT NOT NULL
        );
        """
    )
    con.execute(
        """
        INSERT INTO research_build_patterns VALUES (
            'bdp-1',
            'cooccurrence',
            'Spark trigger package',
            'Spark and Comet are observed as a trigger package.',
            '["skill:SparkPlayer","skill:CometPlayer"]',
            '{"skill:SparkPlayer":"trigger_host","skill:CometPlayer":"payoff"}',
            'case_observation',
            1,
            1,
            '["case:fixture-001"]',
            'Treat as advisory.',
            '["Verify in Judge."]',
            'valid',
            1
        )
        """
    )
    con.execute(
        """
        INSERT INTO research_semantic_edges VALUES (
            'rse-1',
            'skill:SparkPlayer',
            'skill:CometPlayer',
            'synergizes_with',
            'Safe rationale only.',
            '["case:fixture-001"]',
            'medium',
            'valid',
            1
        )
        """
    )
    con.execute(
        """
        INSERT INTO research_fragments VALUES (
            'rf-1',
            'mechanism_pattern',
            'Spark principle',
            'Spark can act as a trigger surface.',
            'Use only after resolver checks.',
            '["skill:SparkPlayer"]',
            '["case:fixture-001"]',
            'medium',
            'valid'
        )
        """
    )
    con.commit()
    con.close()
