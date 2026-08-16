"""Tests for the family re-consolidation script (set-based identity merges)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.knowledge import mature_learning, research_memory  # noqa: E402
from server.knowledge import physical_graph as pg  # noqa: E402
from server.knowledge import graph_tools as gt  # noqa: E402

SCRIPT = REPO_ROOT / "scripts" / "merge_build_families.py"


def _graph_service() -> gt.GraphQueryService:
    source = pg.GraphSource(
        source_id="fixture:merge",
        kind="test_fixture",
        source_file="tests/test_merge_build_families.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    nodes = (
        pg.GraphNode("skill:A", "active_skill", "A", (source.source_id,)),
        pg.GraphNode("skill:B", "active_skill", "B", (source.source_id,)),
        pg.GraphNode("support:Scattershot", "support_gem", "Scattershot", (source.source_id,)),
        pg.GraphNode(
            "ascendancy:monk:martial_artist",
            "ascendancy",
            "Martial Artist",
            (source.source_id,),
        ),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:merge",
        created_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        sources=(source,),
        nodes=nodes,
        aliases=(),
        edges=(),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)


def _record(primary: str, group: str, title: str) -> dict:
    return {
        "record_kind": "skill_package",
        "title": title,
        "summary": title,
        "content": title,
        "content_language": "zh-CN",
        "length_exception_reason": None,
        "extraction_method_version": "deep_research_mvp_v1",
        "record_schema_version": 1,
        "research_group_id": group,
        "class_key": None,
        "ascendancy_key": "ascendancy:monk:martial_artist",
        "source_case_refs": [f"source-hash:{group}"],
        "safe_evidence_refs": [f"evidence:{group}"],
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledge_scope": "global_seed",
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version_or_commit": "0.22.0",
        "component_mentions": [
            {
                "role": "primary_damage",
                "component_key": primary,
                "candidate_name": primary,
                "resolver_query": primary,
                "resolution_status": "resolved",
                "scope": "player",
            },
            {
                "role": "support_modifier",
                "component_key": "support:Scattershot",
                "candidate_name": "Scattershot",
                "resolver_query": "Scattershot",
                "resolution_status": "resolved",
                "scope": "any",
            },
        ],
        "component_keys": [primary, "support:Scattershot"],
        "conditions": [],
        "failure_conditions": [],
        "typed_payload": {
            "availability": "standard",
            "knowledgeShape": "state_causal_chain",
            "supportPackages": [{"skillKey": primary, "supportKeys": ["support:Scattershot"]}],
        },
    }


def _insert_family_and_record(
    db_path: Path,
    *,
    family_key: str,
    primary_keys: list[str],
    record_id: str,
    group: str,
    title: str,
) -> None:
    """Insert one family row plus one record pointing at it (simulates historical data
    created before the set-based identity rule, which the merge script must consolidate)."""
    con = mature_learning.connect(db_path)
    try:
        con.execute(
            """
            INSERT INTO research_build_families(
                build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys,
                secondary_skill_keys, evidence_count, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, '[]', 1, ?, ?)
            """,
            (
                family_key,
                "ascendancy:monk:martial_artist",
                primary_keys[0],
                json.dumps(primary_keys),
                "2026-08-10T00:00:00+00:00",
                "2026-08-10T00:00:00+00:00",
            ),
        )
        con.execute(
            """
            INSERT INTO deep_research_records(
                record_id, research_group_id, build_family_key, knowledge_key,
                evidence_count, record_kind, title, summary, content, content_language,
                length_exception_reason, component_keys, component_mentions,
                source_case_refs, safe_evidence_refs, conditions, failure_conditions,
                typed_payload, class_key, ascendancy_key, extraction_method_version,
                record_schema_version, game_patch, passive_tree_version,
                pob_version_or_commit, visibility, split, knowledge_scope, status,
                copy_safety_state, current_version_context, created_at, last_seen_at,
                last_validated_at, superseded_by_id
            ) VALUES (?, ?, ?, ?, 1, 'skill_package', ?, ?, ?, 'zh-CN', NULL,
                ?, ?, ?, ?, '[]', '[]', ?, NULL, 'ascendancy:monk:martial_artist',
                'deep_research_mvp_v1', 1, '0.5.4', '0_5', '0.22.0', 'creator_visible',
                'train_context', 'global_seed', 'valid', 'passed', ?, ?, ?, ?, NULL)
            """,
            (
                record_id,
                group,
                family_key,
                f"ku-{record_id}",
                title,
                title,
                title,
                json.dumps(primary_keys),
                json.dumps(
                    [
                        {
                            "role": "primary_damage",
                            "component_key": primary_keys[0],
                            "candidate_name": primary_keys[0],
                            "resolver_query": primary_keys[0],
                            "resolution_status": "resolved",
                            "scope": "player",
                        }
                    ]
                ),
                json.dumps([f"source-hash:{group}"]),
                json.dumps([f"evidence:{group}"]),
                json.dumps({"availability": "standard"}),
                json.dumps(
                    {
                        "game_patch": "0.5.4",
                        "passive_tree_version": "0_5",
                        "pob_version_or_commit": "0.22.0",
                    }
                ),
                "2026-08-10T00:00:00+00:00",
                "2026-08-10T00:00:00+00:00",
                "2026-08-10T00:00:00+00:00",
            ),
        )
        con.execute(
            """
            INSERT INTO research_build_family_evidence(
                build_family_key, source_case_ref, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                family_key,
                f"source-hash:{group}",
                "2026-08-10T00:00:00+00:00",
                "2026-08-10T00:00:00+00:00",
            ),
        )
        con.commit()
    finally:
        con.close()


def _seed_store(db_path: Path) -> None:
    """Seed three historical split families: two A-only and one A+B superset."""
    mature_learning.initialize_store(db_path)
    _insert_family_and_record(
        db_path,
        family_key="bf-" + "a" * 20,
        primary_keys=["skill:A"],
        record_id="drr-aaa1",
        group="g1",
        title="A pack 1",
    )
    _insert_family_and_record(
        db_path,
        family_key="bf-" + "b" * 20,
        primary_keys=["skill:A"],
        record_id="drr-aaa2",
        group="g2",
        title="A pack 2",
    )
    _insert_family_and_record(
        db_path,
        family_key="bf-" + "c" * 20,
        primary_keys=["skill:A", "skill:B"],
        record_id="drr-aaa3",
        group="g3",
        title="AB pack",
    )


def _run_script(db_path: Path, *extra: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db_path), *extra],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_merge_script_dry_run_reports_plan(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    _seed_store(db_path)
    report = _run_script(db_path, "--dry-run")
    assert report["status"] == "ok"
    assert report["familyCount"] == 3
    assert report["mergePlanCount"] >= 2


def test_merge_script_apply_converges_to_single_family(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    _seed_store(db_path)
    report = _run_script(db_path, "--apply", "--backup-dir", str(tmp_path))
    assert report["status"] == "applied"
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_build_families").fetchone()[0] == 1
        families = con.execute(
            "SELECT build_family_key, primary_skill_keys FROM research_build_families"
        ).fetchall()
        keys = json.loads(families[0]["primary_skill_keys"])
        assert set(keys) == {"skill:A", "skill:B"}
        orphans = con.execute(
            """
            SELECT count(*) FROM deep_research_records r
            WHERE r.build_family_key IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM research_build_families f
                  WHERE f.build_family_key = r.build_family_key
              )
            """
        ).fetchone()[0]
        assert orphans == 0
        log_rows = con.execute("SELECT count(*) FROM family_merge_log").fetchone()[0]
        assert log_rows >= 2
    finally:
        con.close()


def test_merge_script_disjoint_families_stay_separate(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    service.propose_deep_research_records(
        {"schema_version": 5, "deep_research_records": [_record("skill:A", "g1", "A pack")]}
    )
    service.propose_deep_research_records(
        {"schema_version": 5, "deep_research_records": [_record("skill:B", "g2", "B pack")]}
    )
    report = _run_script(db_path, "--apply", "--backup-dir", str(tmp_path))
    assert report["status"] == "applied"
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_build_families").fetchone()[0] == 2
    finally:
        con.close()
