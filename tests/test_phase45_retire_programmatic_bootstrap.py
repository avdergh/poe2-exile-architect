from __future__ import annotations

import json
import sqlite3

from scripts import retire_phase45_programmatic_bootstrap
from server.knowledge import mature_learning


def test_retire_programmatic_bootstrap_marks_legacy_deep_rows_not_planner_visible(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    mature_learning.initialize_store(db_path)
    con = mature_learning.connect(db_path)
    try:
        _insert_pattern(
            con,
            pattern_id="bdp-legacy",
            title="Case observation case:phase45-deep-001: Hollow Focus",
            safe_refs=["safe:phase45-deep:abc123"],
            status="valid",
            planner_visible=1,
        )
        _insert_pattern(
            con,
            pattern_id="bdp-real",
            title="Deep researcher Hollow Focus gate",
            safe_refs=["safe:phase45-real:abc123"],
            source_refs=["case:phase4-deep-researcher-001"],
            status="valid",
            planner_visible=1,
        )
        con.commit()
    finally:
        con.close()

    report = retire_phase45_programmatic_bootstrap.retire_programmatic_bootstrap_rows(
        db_path=db_path,
        dry_run=False,
    )

    assert report["status"] == "accepted"
    assert report["matchedPatternCount"] == 1
    assert report["updatedPatternCount"] == 1
    assert report["retirementStatus"] == "needs_revalidation"
    assert report["noRawMatureBuildMaterial"] is True

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        legacy = con.execute(
            "SELECT status, planner_visible FROM research_build_patterns WHERE pattern_id = ?",
            ("bdp-legacy",),
        ).fetchone()
        real = con.execute(
            "SELECT status, planner_visible FROM research_build_patterns WHERE pattern_id = ?",
            ("bdp-real",),
        ).fetchone()
    finally:
        con.close()

    assert dict(legacy) == {"status": "needs_revalidation", "planner_visible": 0}
    assert dict(real) == {"status": "valid", "planner_visible": 1}


def test_retire_programmatic_bootstrap_dry_run_does_not_mutate(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    mature_learning.initialize_store(db_path)
    con = mature_learning.connect(db_path)
    try:
        _insert_pattern(
            con,
            pattern_id="bdp-legacy",
            title="Case observation case:phase45-deep-001: Hollow Focus",
            safe_refs=["safe:phase45-deep:abc123"],
            status="valid",
            planner_visible=1,
        )
        con.commit()
    finally:
        con.close()

    report = retire_phase45_programmatic_bootstrap.retire_programmatic_bootstrap_rows(
        db_path=db_path,
        dry_run=True,
    )

    assert report["status"] == "dry_run"
    assert report["matchedPatternCount"] == 1
    assert report["updatedPatternCount"] == 0

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT status, planner_visible FROM research_build_patterns WHERE pattern_id = ?",
            ("bdp-legacy",),
        ).fetchone()
    finally:
        con.close()

    assert dict(row) == {"status": "valid", "planner_visible": 1}


def test_retire_programmatic_bootstrap_does_not_retire_deep_researcher_with_legacy_ref(
    tmp_path,
):
    db_path = tmp_path / "memory.sqlite"
    mature_learning.initialize_store(db_path)
    con = mature_learning.connect(db_path)
    try:
        _insert_pattern(
            con,
            pattern_id="bdp-researcher",
            title="Deep researcher charge cadence finding",
            summary=(
                "Researcher analysis found a charge cadence transition gate with resource and "
                "defense caveats."
            ),
            planner_hint="Use only after endpoint resolution and Judge verification.",
            safe_refs=["safe:phase45-deep:abc123"],
            source_refs=["case:phase45-deep-001"],
            status="valid",
            planner_visible=1,
        )
        con.commit()
    finally:
        con.close()

    report = retire_phase45_programmatic_bootstrap.retire_programmatic_bootstrap_rows(
        db_path=db_path,
        dry_run=False,
    )

    assert report["matchedPatternCount"] == 0
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT status, planner_visible FROM research_build_patterns WHERE pattern_id = ?",
            ("bdp-researcher",),
        ).fetchone()
    finally:
        con.close()

    assert dict(row) == {"status": "valid", "planner_visible": 1}


def _insert_pattern(
    con: sqlite3.Connection,
    *,
    pattern_id: str,
    title: str,
    safe_refs: list[str],
    source_refs: list[str] | None = None,
    summary: str = "One mature sample contains resolver-backed components with roles: primary_damage. Treat as a safe case observation, not a reusable trend.",
    planner_hint: str = "Use this case observation only as a candidate component set for Phase 5 search; verify roles primary_damage before generation.",
    status: str,
    planner_visible: int,
) -> None:
    source_refs = source_refs or ["case:phase45-deep-001"]
    con.execute(
        """
        INSERT INTO research_build_patterns(
            pattern_id, pattern_type, title, summary, component_keys, component_roles,
            confidence_tier, sample_count, family_count, source_diversity_count, denominator,
            source_case_refs, safe_evidence_refs, context_requirements, planner_hint,
            verification_tasks, game_patch, passive_tree_version, pob_version_or_commit,
            visibility, split, knowledge_scope, status, copy_safety_state,
            current_version_context, planner_visible, created_at, last_seen_at,
            last_validated_at, superseded_by_id
        ) VALUES (?, 'build_archetype', ?, ?, ?, ?, 'case_observation',
            1, 1, 1, 1, ?, ?, ?, ?, ?, '0.5.x', '0_5', 'unknown',
            'creator_visible', 'train_context', 'global_seed', ?, 'passed',
            ?, ?, '2026-07-07T00:00:00+00:00', '2026-07-07T00:00:00+00:00', NULL, NULL)
        """,
        (
            pattern_id,
            title,
            summary,
            json.dumps(["skill:HollowFocusPlayer"]),
            json.dumps({"skill:HollowFocusPlayer": "primary_damage"}),
            json.dumps(source_refs),
            json.dumps(safe_refs),
            json.dumps(
                [
                    {
                        "context_type": "verification_gate_requirement",
                        "task": "Verify before planner use.",
                    }
                ]
            ),
            planner_hint,
            json.dumps(["Verify before planner use."]),
            status,
            json.dumps({"game_patch": "0.5.x", "passive_tree_version": "0_5"}),
            planner_visible,
        ),
    )
