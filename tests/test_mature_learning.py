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


def test_schema_rejects_evaluator_evidence_marked_creator_visible(tmp_path):
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
                'supports', 'evaluator_only', 'eval_holdout', 'global_seed',
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
        "diversityBucket": "stormweaver-lightning-spell",
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


def test_sanitize_rejects_snake_case_forbidden_fields_inside_manifest():
    raw = _raw_case(
        fixtureManifest={
            "eligibility_basis": "manual_stand_in_for_hot_sample",
            "popularity_signal": {"kind": "rank", "rank": 1, "source": "fixture_manifest"},
            "currentness_basis": {
                "league": "Dawn of the Hunt",
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "snapshot_date": "2026-06-27",
            },
            "diversity_policy": "Popularity filtered before diversity cap.",
            "passive_tree": {"nodes": [1, 2, 3]},
        }
    )

    result = mature_learning.sanitize_mature_case(raw)

    assert result["ok"] is False
    assert result["error"] == "forbidden_copyable_fields"
    assert "fixtureManifest.passive_tree" in result["redactedFieldsPresent"]


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


def test_sanitize_rejects_invalid_lifecycle_stage_and_evidence_type_before_insert():
    invalid_stage = mature_learning.sanitize_mature_case(_raw_case(lifecycleStage="copied_final"))
    invalid_evidence = mature_learning.sanitize_mature_case(_raw_case(evidenceType="random_blog"))

    assert invalid_stage["ok"] is False
    assert invalid_stage["error"] == "invalid_lifecycle_stage"
    assert invalid_evidence["ok"] is False
    assert invalid_evidence["error"] == "invalid_evidence_type"


def test_sanitize_preserves_snake_case_knowledge_scope():
    result = mature_learning.sanitize_mature_case(
        _raw_case(knowledgeScope=None, knowledge_scope="global_seed")
    )

    assert result["ok"] is True
    assert result["knowledge_scope"] == "global_seed"


def test_sanitize_rejects_bad_sample_weight_without_raising():
    result = mature_learning.sanitize_mature_case(_raw_case(sampleWeight="heavy"))

    assert result["ok"] is False
    assert result["error"] == "invalid_sample_weight"


def test_sanitize_rejects_invalid_numeric_n_and_percentiles():
    bad_n = mature_learning.sanitize_mature_case(
        _raw_case(
            numericRangesOrMetrics={
                "TotalDPS": {"min": 100000, "median": 150000, "max": 200000, "n": 0},
            }
        )
    )
    bad_percentile = mature_learning.sanitize_mature_case(
        _raw_case(
            numericRangesOrMetrics={
                "TotalDPS": {"min": 100000, "p90": 250000, "max": 200000, "n": 3},
            }
        )
    )

    assert bad_n["ok"] is False
    assert bad_n["error"] == "invalid_numeric_ranges_or_metrics"
    assert bad_percentile["ok"] is False
    assert bad_percentile["error"] == "invalid_numeric_ranges_or_metrics"


def test_fixture_manifest_requires_structured_popularity_currentness_and_diversity():
    raw = _raw_case(fixtureManifest={"eligibility_basis": "manual_stand_in_for_hot_sample"})

    result = mature_learning.validate_fixture_manifest(raw)

    assert result["ok"] is False
    assert "fixture_manifest_incomplete" in result["error"]
    assert "popularity_signal" in result["missing"]
    assert "currentness_basis" in result["missing"]
    assert "diversity_policy" in result["missing"]


def test_fixture_manifest_requires_rank_signal_and_snapshot_date():
    raw = _raw_case(
        fixtureManifest={
            "eligibility_basis": "manual_stand_in_for_hot_sample",
            "popularity_signal": {"kind": "rank"},
            "currentness_basis": {
                "league": "Dawn of the Hunt",
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
            },
            "diversity_policy": "Popularity filtered before diversity cap.",
        }
    )

    result = mature_learning.validate_fixture_manifest(raw)

    assert result["ok"] is False
    assert "popularity_signal.rank" in result["missing"]
    assert "currentness_basis.snapshot_date" in result["missing"]


def test_import_seed_fixtures_persists_sanitized_cases(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    fixture_path.write_text(
        """
{
  "schemaVersion": 1,
  "fixtureSet": "phase3n1-test",
  "cases": [
    {
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
      "defenseTags": ["energy_shield"],
      "mechanicTags": ["crit", "shock"],
      "lifecycleStage": "endgame_final",
      "budgetBand": "expensive",
      "popularityRank": 1,
      "sampleWeight": 1.0,
      "pobModelability": "partial",
      "keypoints": ["Endgame lightning caster scaling fixture."],
      "numericRangesOrMetrics": {},
      "visibility": "creator_visible",
      "split": "train_context",
      "knowledgeScope": "global_seed",
      "evidenceType": "poe_ninja_hot",
      "freshnessStatus": "verified_current",
      "compatibilityStatus": "current",
      "diversityBucket": "stormweaver-lightning-spell",
      "fixtureManifest": {
        "eligibility_basis": "manual_stand_in_for_hot_sample",
        "popularity_signal": {"kind": "rank", "rank": 1, "source": "fixture_manifest"},
        "currentness_basis": {
          "league": "Dawn of the Hunt",
          "game_patch": "0.5.4",
          "passive_tree_version": "0_5",
          "snapshot_date": "2026-06-27"
        },
        "diversity_policy": "Popularity filtered before diversity balancing."
      }
    },
    {
      "sourceType": "manual_fixture",
      "sourceRef": "fixture://deadeye-projectile",
      "league": "Dawn of the Hunt",
      "gamePatch": "0.5.4",
      "passiveTreeVersion": "0_5",
      "class": "Ranger",
      "ascendancy": "Deadeye",
      "mainSkill": "Lightning Arrow",
      "damageTypes": ["lightning", "physical"],
      "deliveryTags": ["attack", "projectile"],
      "defenseTags": ["evasion"],
      "mechanicTags": ["projectile"],
      "lifecycleStage": "endgame_budget",
      "budgetBand": "moderate",
      "popularityRank": 2,
      "sampleWeight": 1.0,
      "pobModelability": "partial",
      "keypoints": ["Projectile attack fixture with starter-risk caveat."],
      "numericRangesOrMetrics": {},
      "visibility": "evaluator_only",
      "split": "eval_holdout",
      "knowledgeScope": "global_seed",
      "evidenceType": "poe_ninja_hot",
      "freshnessStatus": "verified_current",
      "compatibilityStatus": "current",
      "diversityBucket": "deadeye-projectile-attack",
      "fixtureManifest": {
        "eligibility_basis": "manual_stand_in_for_hot_sample",
        "popularity_signal": {"kind": "rank", "rank": 2, "source": "fixture_manifest"},
        "currentness_basis": {
          "league": "Dawn of the Hunt",
          "game_patch": "0.5.4",
          "passive_tree_version": "0_5",
          "snapshot_date": "2026-06-27"
        },
        "diversity_policy": "Held out for later evaluator tests after popularity filter."
      }
    }
  ]
}
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    mature_learning.initialize_store(db_path)

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    assert result["importedCases"] == 2
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM source_groups").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM source_snapshots").fetchone()[0] == 2
    assert con.execute("SELECT count(*) FROM mature_build_cases").fetchone()[0] == 2
    rows = con.execute(
        "SELECT visibility, split FROM mature_build_cases ORDER BY case_id"
    ).fetchall()
    assert {tuple(row) for row in rows} == {
        ("creator_visible", "train_context"),
        ("evaluator_only", "eval_holdout"),
    }
    versions = con.execute("SELECT DISTINCT sanitizer_version FROM source_snapshots").fetchall()
    assert {row[0] for row in versions} == {mature_learning.SANITIZER_VERSION}


def test_import_fixture_file_is_idempotent(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(sourceRef="fixture://idempotent-case")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "idempotent", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    first = mature_learning.import_fixture_file(fixture_path, db_path=db_path)
    second = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert first["ok"] is True
    assert second["ok"] is True
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM source_groups").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM source_snapshots").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM mature_build_cases").fetchone()[0] == 1


def test_import_fixture_file_closes_connection_after_import(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(sourceRef="fixture://close-test")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "close-test", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    db_path.unlink()
    assert not db_path.exists()


def test_seed_fixture_import_rejects_user_feedback_even_when_local_scope(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(evidenceType="user_feedback_local", knowledgeScope="local_user")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "feedback", "cases": [raw]}),
        encoding="utf-8",
    )

    result = mature_learning.import_fixture_file(fixture_path, db_path=tmp_path / "mature.sqlite")

    assert result["ok"] is False
    assert result["importedCases"] == 0
    assert result["rejected"][0]["error"] == "seed_fixture_cannot_use_user_feedback"


def test_import_fixture_file_is_all_or_nothing_for_mixed_seed(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    valid = _raw_case(sourceRef="fixture://valid-case")
    invalid = _raw_case(sourceRef="fixture://invalid-case", pobCode="eNrtSecret")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "mixed", "cases": [valid, invalid]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is False
    assert result["importedCases"] == 0
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM mature_build_cases").fetchone()[0] == 0


def test_import_bundled_seed_fixture_file(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(db_path=db_path)

    assert result["ok"] is True
    assert result["importedCases"] == 4
    con = sqlite3.connect(db_path)
    classes = {row[0] for row in con.execute("SELECT class FROM mature_build_cases").fetchall()}
    assert len(classes) >= 4


def test_invalid_visibility_split_is_rejected_by_sanitizer():
    result = mature_learning.sanitize_mature_case(
        _raw_case(visibility="creator_visible", split="eval_holdout")
    )

    assert result["ok"] is False
    assert result["error"] == "invalid_visibility_split"


def test_user_feedback_local_cannot_enter_global_seed():
    result = mature_learning.sanitize_mature_case(
        _raw_case(evidenceType="user_feedback_local", knowledgeScope="global_seed")
    )

    assert result["ok"] is False
    assert result["error"] == "local_feedback_must_stay_local"


def test_persisted_fixture_rows_do_not_contain_raw_copyable_content(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(
        sourceRef="fixture://safe-case",
        keypoints=["Broad coarse keypoint about an endgame-only scaling lane."],
    )
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "copy-safety", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    raw_db_bytes = db_path.read_bytes()
    assert b"pobCode" not in raw_db_bytes
    assert b"passiveTree" not in raw_db_bytes
    assert b"Ring 1" not in raw_db_bytes
    assert b"fullGemLinks" not in raw_db_bytes


def test_expiration_metadata_is_inert_in_phase_3n1(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    raw = _raw_case(freshnessStatus="stale", compatibilityStatus="stale")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "stale-inert", "cases": [raw]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"

    result = mature_learning.import_fixture_file(fixture_path, db_path=db_path)

    assert result["ok"] is True
    con = sqlite3.connect(db_path)
    row = con.execute(
        "SELECT freshness_status, compatibility_status FROM mature_build_cases"
    ).fetchone()
    assert tuple(row) == ("stale", "stale")


def _extract_rows(con: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    con.row_factory = sqlite3.Row
    return con.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_extract_technique_candidates_creates_candidates_and_evidence(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    result = mature_learning.import_fixture_file(db_path=db_path)
    assert result["ok"] is True

    extract = mature_learning.extract_technique_candidates(db_path=db_path)

    assert extract["ok"] is True
    assert extract["casesScanned"] == 4
    assert extract["candidatesUpserted"] == 4
    assert extract["evidenceUpserted"] == 4
    con = mature_learning.connect(db_path)
    candidates = _extract_rows(con, "technique_candidates")
    evidence = _extract_rows(con, "candidate_evidence")
    assert len(candidates) == 4
    assert len(evidence) == 4
    assert {row["support_count"] for row in candidates} == {1}
    assert {row["contradiction_count"] for row in candidates} == {0}
    assert {row["source_count"] for row in candidates} == {1}
    assert all(row["promotion_status"] in {"candidate", "quarantined"} for row in candidates)


def test_extract_technique_candidates_is_idempotent_and_deterministic(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    first = mature_learning.extract_technique_candidates(db_path=db_path)
    second = mature_learning.extract_technique_candidates(db_path=db_path)

    assert first["ok"] is True
    assert second["ok"] is True
    con = mature_learning.connect(db_path)
    candidate_ids = [
        row[0]
        for row in con.execute(
            "SELECT candidate_id FROM technique_candidates ORDER BY candidate_id"
        )
    ]
    evidence_ids = [
        row[0]
        for row in con.execute("SELECT evidence_id FROM candidate_evidence ORDER BY evidence_id")
    ]
    assert len(candidate_ids) == len(set(candidate_ids)) == 4
    assert len(evidence_ids) == len(set(evidence_ids)) == 4
    assert con.execute("SELECT count(*) FROM technique_candidates").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM candidate_evidence").fetchone()[0] == 4


def test_extract_technique_candidates_preserves_creator_visibility_boundaries(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    rows = con.execute(
        """
        SELECT visibility, split, creator_visible
        FROM candidate_evidence
        ORDER BY visibility, split
        """
    ).fetchall()
    assert ("creator_visible", "train_context", 1) in [tuple(row) for row in rows]
    assert ("evaluator_only", "eval_holdout", 0) in [tuple(row) for row in rows]
    assert ("quarantined", "quarantine", 0) in [tuple(row) for row in rows]


def test_extract_technique_candidates_derives_counts_from_evidence_rows(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    first = _raw_case(sourceRef="fixture://spark-a")
    second = _raw_case(
        sourceRef="fixture://spark-b",
        damageTypes=["LIGHTNING"],
        deliveryTags=["projectile", "spell"],
        defenseTags=["RECHARGE", "energy_shield"],
        mechanicTags=["shock", "crit"],
        keypoints=["Another coarse Spark mature-case summary from a separate source."],
    )
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "counting", "cases": [first, second]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(fixture_path, db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    candidates = con.execute("SELECT * FROM technique_candidates").fetchall()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["support_count"] == 2
    assert candidate["source_count"] == 2
    assert candidate["contradiction_count"] == 0


def test_extract_technique_candidates_records_lifecycle_risk_fields(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    row = con.execute(
        """
        SELECT required_prerequisites, starter_risk_reason, transition_gate_summary,
               unsafe_before_stage
        FROM technique_candidates
        WHERE lifecycle_stage = 'endgame_final'
        LIMIT 1
        """
    ).fetchone()
    assert json.loads(row["required_prerequisites"])
    assert "starter" in row["starter_risk_reason"].lower()
    assert "transition" in row["transition_gate_summary"].lower()
    assert row["unsafe_before_stage"] in {"maps_entry", "endgame_budget", "endgame_final"}


def test_extract_technique_candidates_keeps_same_semantic_holdout_in_separate_bucket(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    creator = _raw_case(sourceRef="fixture://same-semantic-creator")
    evaluator = _raw_case(
        sourceRef="fixture://same-semantic-evaluator",
        visibility="evaluator_only",
        split="eval_holdout",
    )
    quarantined = _raw_case(
        sourceRef="fixture://same-semantic-quarantine",
        visibility="quarantined",
        split="quarantine",
    )
    fixture_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "fixtureSet": "same-semantic-boundary",
                "cases": [creator, evaluator, quarantined],
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(fixture_path, db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    rows = con.execute(
        """
        SELECT tc.candidate_id, tc.knowledge_scope, tc.promotion_status, tc.source_count,
               ce.visibility, ce.split, ce.creator_visible
        FROM technique_candidates tc
        JOIN candidate_evidence ce ON ce.candidate_id = tc.candidate_id
        ORDER BY ce.visibility, ce.split
        """
    ).fetchall()
    assert len({row["candidate_id"] for row in rows}) == 3
    assert all(row["source_count"] == 1 for row in rows)
    by_visibility = {row["visibility"]: row for row in rows}
    assert by_visibility["creator_visible"]["knowledge_scope"] == "global_seed"
    assert by_visibility["creator_visible"]["creator_visible"] == 1
    assert by_visibility["evaluator_only"]["knowledge_scope"] == "eval_ephemeral"
    assert by_visibility["evaluator_only"]["creator_visible"] == 0
    assert by_visibility["quarantined"]["knowledge_scope"] == "eval_ephemeral"
    assert by_visibility["quarantined"]["promotion_status"] == "quarantined"
    assert by_visibility["quarantined"]["creator_visible"] == 0


def test_evaluator_only_candidates_do_not_become_global_creator_context(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    evaluator_candidate_ids = [
        row["candidate_id"]
        for row in con.execute(
            """
            SELECT DISTINCT candidate_id
            FROM candidate_evidence
            WHERE visibility = 'evaluator_only'
            """
        )
    ]
    assert evaluator_candidate_ids
    scopes = {
        row["knowledge_scope"]
        for row in con.execute(
            "SELECT knowledge_scope FROM technique_candidates WHERE candidate_id IN ({})".format(
                ",".join("?" for _ in evaluator_candidate_ids)
            ),
            evaluator_candidate_ids,
        )
    }
    assert scopes == {"eval_ephemeral"}


def test_extract_technique_candidates_recomputes_counts_from_evidence(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True
    assert mature_learning.extract_technique_candidates(db_path=db_path)["ok"] is True
    con = mature_learning.connect(db_path)
    con.execute(
        "UPDATE technique_candidates SET source_count = 99, support_count = 99, contradiction_count = 99"
    )
    con.commit()
    con.close()

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    counts = con.execute(
        "SELECT DISTINCT source_count, support_count, contradiction_count FROM technique_candidates"
    ).fetchall()
    assert {tuple(row) for row in counts} == {(1, 1, 0)}


def test_extract_technique_candidates_moves_evidence_when_case_visibility_changes(tmp_path):
    fixture_path = tmp_path / "fixtures.json"
    creator = _raw_case(sourceRef="fixture://mutable-visibility")
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "mutable", "cases": [creator]}),
        encoding="utf-8",
    )
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(fixture_path, db_path=db_path)["ok"] is True
    assert mature_learning.extract_technique_candidates(db_path=db_path)["ok"] is True

    evaluator = _raw_case(
        sourceRef="fixture://mutable-visibility",
        visibility="evaluator_only",
        split="eval_holdout",
    )
    fixture_path.write_text(
        json.dumps({"schemaVersion": 1, "fixtureSet": "mutable", "cases": [evaluator]}),
        encoding="utf-8",
    )
    assert mature_learning.import_fixture_file(fixture_path, db_path=db_path)["ok"] is True

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    evidence_rows = con.execute(
        """
        SELECT visibility, split, creator_visible
        FROM candidate_evidence
        ORDER BY evidence_id
        """
    ).fetchall()
    assert [tuple(row) for row in evidence_rows] == [("evaluator_only", "eval_holdout", 0)]
    positive_counts = con.execute(
        """
        SELECT knowledge_scope, support_count
        FROM technique_candidates
        WHERE support_count > 0
        """
    ).fetchall()
    assert [tuple(row) for row in positive_counts] == [("eval_ephemeral", 1)]


def test_extract_technique_candidates_preserves_manual_promotion_status(tmp_path):
    db_path = tmp_path / "mature.sqlite"
    assert mature_learning.import_fixture_file(db_path=db_path)["ok"] is True
    assert mature_learning.extract_technique_candidates(db_path=db_path)["ok"] is True
    con = mature_learning.connect(db_path)
    candidate_id = con.execute(
        """
        SELECT candidate_id
        FROM technique_candidates
        WHERE promotion_status = 'candidate'
        LIMIT 1
        """
    ).fetchone()["candidate_id"]
    con.execute(
        "UPDATE technique_candidates SET promotion_status = 'rejected' WHERE candidate_id = ?",
        (candidate_id,),
    )
    con.commit()
    con.close()

    mature_learning.extract_technique_candidates(db_path=db_path)

    con = mature_learning.connect(db_path)
    assert (
        con.execute(
            "SELECT promotion_status FROM technique_candidates WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()["promotion_status"]
        == "rejected"
    )
