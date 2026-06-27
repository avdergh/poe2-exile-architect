"""Phase 3N mature-build learning store tests.

The mature-learning store must keep popular mature build knowledge useful but non-copyable.
Phase 3N.1 creates schema and safety guards only; it must not affect route synthesis.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from server import paths
from server.knowledge import mature_learning


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def test_mature_learning_path_lives_in_user_data(tmp_path, monkeypatch):
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path))

    path = paths.mature_learning_path()

    assert path == tmp_path / "mature_build_learning.sqlite"
    assert path.parent == tmp_path


def test_initialize_store_creates_phase_3n1_schema(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    mature_learning.initialize_store(db_path)
    con = sqlite3.connect(db_path)

    assert mature_learning.schema_version(con) == mature_learning.SCHEMA_VERSION
    assert {
        "meta",
        "source_groups",
        "source_snapshots",
        "mature_build_cases",
        "technique_candidates",
        "candidate_evidence",
        "technique_edges",
    } <= _tables(con)
    assert {
        "source_group_id",
        "dedupe_hash",
        "canonical_source_type",
        "canonical_source_ref",
        "league",
        "game_patch",
        "passive_tree_version",
        "created_at",
        "last_seen_at",
    } <= _columns(con, "source_groups")
    assert {
        "case_id",
        "source_snapshot_id",
        "external_id_hash",
        "visibility",
        "split",
        "knowledge_scope",
        "class",
        "ascendancy",
        "main_skill",
        "sanitized_keypoints",
        "redacted_fields_present",
        "source_group_id",
    } <= _columns(con, "mature_build_cases")
    assert "evidence_id" in _columns(con, "candidate_evidence")
    assert "edge_id" in _columns(con, "technique_edges")


def test_initialize_store_is_idempotent_for_schema_v1(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    mature_learning.initialize_store(db_path)
    mature_learning.initialize_store(db_path)
    con = sqlite3.connect(db_path)

    assert mature_learning.schema_version(con) == mature_learning.SCHEMA_VERSION
    assert con.execute("SELECT count(*) FROM meta WHERE key = 'schema_version'").fetchone()[0] == 1


def test_initialize_store_refuses_future_schema_without_downgrading(tmp_path):
    db_path = tmp_path / "future.sqlite"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '999')")
    con.commit()
    con.close()

    with pytest.raises(mature_learning.SchemaVersionError):
        mature_learning.initialize_store(db_path)

    con = sqlite3.connect(db_path)
    assert con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "999"


def test_schema_rejects_invalid_candidate_evidence_visibility_split(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    mature_learning.initialize_store(db_path)
    con = sqlite3.connect(db_path)

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            """
            INSERT INTO candidate_evidence(
                evidence_id, candidate_id, case_id, source_snapshot_id, source_group_id,
                relation, visibility, split, knowledge_scope, extraction_method,
                extractor_version, confidence, creator_visible, created_at, last_seen_at
            ) VALUES (
                'ev-1', 'cand-missing', 'case-missing', 'ss-missing', 'sg-missing',
                'supports', 'creator_visible', 'eval_holdout', 'global_seed',
                'test', 'test', 1.0, 1, 'now', 'now'
            )
            """
        )


def _raw_case(**overrides):
    base = {
        "sourceType": "manual_fixture",
        "sourceRef": "fixture://spark-stormweaver",
        "league": "Dawn of the Hunt",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "class": "Sorceress",
        "ascendancy": "Stormweaver",
        "mainSkill": "Spark",
        "damageTypes": ["lightning"],
        "deliveryTags": ["spell", "projectile"],
        "defenseTags": ["energy_shield", "recharge"],
        "mechanicTags": ["crit", "shock"],
        "lifecycleStage": "endgame_final",
        "budgetBand": "expensive",
        "popularityRank": 1,
        "sampleWeight": 1.0,
        "pobModelability": "partial",
        "keypoints": [
            "Scales lightning spell damage through broad +level and crit investment.",
            "Uses an endgame-only defensive identity; not a direct campaign starter.",
        ],
        "numericRangesOrMetrics": {
            "TotalDPS": {"min": 100000, "median": 500000, "max": 1200000, "n": 8}
        },
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledgeScope": "global_seed",
        "evidenceType": "poe_ninja_hot",
        "freshnessStatus": "verified_current",
        "compatibilityStatus": "current",
        "fixtureManifest": {
            "eligibility_basis": "manual_stand_in_for_hot_sample",
            "popularity_signal": {"kind": "rank", "rank": 1, "source": "fixture_manifest"},
            "currentness_basis": {
                "league": "Dawn of the Hunt",
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "snapshot_date": "2026-06-27",
            },
            "diversity_policy": "Popularity filtered before diversity cap.",
        },
    }
    base.update(overrides)
    return base


def test_sanitize_mature_case_keeps_allowed_coarse_fields():
    sanitized = mature_learning.sanitize_mature_case(_raw_case())

    assert sanitized["class"] == "Sorceress"
    assert sanitized["ascendancy"] == "Stormweaver"
    assert sanitized["main_skill"] == "Spark"
    assert sanitized["damage_types"] == ["lightning"]
    assert sanitized["delivery_tags"] == ["spell", "projectile"]
    assert sanitized["redacted_fields_present"] == []
    assert sanitized["sanitized_keypoints"]
    assert "pobCode" not in sanitized
    assert "passiveTree" not in sanitized


def test_sanitize_rejects_explicit_raw_copyable_fields():
    raw = _raw_case(
        pobCode="eNrtVerySecret",
        passiveTree={"nodes": [1, 2, 3]},
        gear={"Ring 1": {"name": "Exact Item"}},
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert "forbidden_copyable_fields" in result["error"]
    assert {"pobCode", "passiveTree", "gear"} <= set(result["redactedFieldsPresent"])


def test_copyability_guard_rejects_reconstructable_keypoints():
    raw = _raw_case(
        keypoints=[
            "Unique: Exact Ring",
            "Unique: Exact Helmet",
            "Unique: Exact Body Armour",
            "Passive path: node 1 -> node 2 -> node 3 -> node 4",
            "Supports: A, B, C, D, E",
        ]
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "too_many_named_uniques" in result["copyabilityFlags"]
    assert "ordered_passive_path" in result["copyabilityFlags"]
    assert "full_support_link_like" in result["copyabilityFlags"]


def test_sanitize_rejects_nested_forbidden_copyable_fields():
    raw = _raw_case(
        numericRangesOrMetrics={
            "TotalDPS": {"min": 100000, "max": 200000, "n": 3},
            "gear": {"Ring 1": "Exact copied item"},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "forbidden_copyable_fields"
    assert "numericRangesOrMetrics.gear" in result["redactedFieldsPresent"]


def test_sanitize_rejects_pob_code_like_text_anywhere():
    raw = _raw_case(
        keypoints=[
            "Broad summary.",
            "eNrt" + ("A" * 180),
        ]
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "pob_code_like_blob" in result["copyabilityFlags"]


def test_sanitize_rejects_non_aggregate_numeric_metrics():
    raw = _raw_case(
        numericRangesOrMetrics={
            "TotalDPS": {"value": 123456},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "invalid_numeric_ranges_or_metrics"


def test_sanitize_rejects_non_finite_numeric_metrics():
    raw = _raw_case(
        numericRangesOrMetrics={
            "TotalDPS": {"min": 100000, "median": float("inf"), "max": 200000, "n": 3},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "invalid_numeric_ranges_or_metrics"


def test_sanitize_rejects_current_claim_with_unknown_patch_tree_or_league():
    result = mature_learning.sanitize_mature_case(
        _raw_case(league="unknown", freshnessStatus="verified_current")
    )

    assert result["ok"] is False
    assert result["error"] == "current_claim_missing_version_metadata"
