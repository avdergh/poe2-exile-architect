"""Isolated schema-6 fixtures exercise source-claim migration and failure recovery."""

import json
import sqlite3

import pytest

from server.knowledge import (
    mature_learning,
    patch_reviews,
    research_claims,
    research_content,
    research_identity,
    research_memory,
    research_models,
    research_runtime,
)


def legacy_store(tmp_path):
    path = tmp_path / "legacy.sqlite"
    con = mature_learning.connect(path)
    con.executescript(mature_learning._SCHEMA_SQL)
    con.executescript(mature_learning._PHASE4_SCHEMA_SQL)
    mature_learning._migrate_phase4_additive_schema(con)
    mature_learning._migrate_research_memory_v5(con, apply_known_repairs=False)
    raw = {
        "research_group_id": "research:fixture-claim-migration",
        "record_kind": "skill_package",
        "title": "投射物覆盖的适用条件",
        "summary": "记录主技能和辅助的联动，同时保留单体表现复核任务。",
        "content": "覆盖能力来自技能和辅助的共同作用，单体环境需要独立验证。",
        "content_language": "zh-CN",
        "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
        "component_mentions": [
            {
                "candidate_name": "Lightning Arrow",
                "role": "primary_damage",
                "resolver_query": "Lightning Arrow",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:LightningArrowPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Scattershot",
                "role": "support_modifier",
                "resolver_query": "Scattershot",
                "expected_node_types": ["support_gem"],
                "scope": "any",
                "component_key": "support:Scattershot",
                "resolution_status": "resolved",
            },
        ],
        "source_case_refs": ["case:source-a", "case:source-b"],
        "safe_evidence_refs": ["safe:fixture:projection"],
        "conditions": ["投射物能够命中目标。"],
        "failure_conditions": ["单体重叠收益未经验证。"],
        "typed_payload": {
            "supportPackages": [
                {"skillKey": "skill:LightningArrowPlayer", "supportKeys": ["support:Scattershot"]}
            ]
        },
        "ascendancy_key": "ascendancy:monk:martial_artist",
        "extraction_method_version": "deep_research_mvp_v1",
        "record_schema_version": 2,
        "source_state_scope": "active_state",
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version_or_commit": "0.22.0",
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledge_scope": "global_seed",
    }
    proposal = research_models.DeepResearchRecordProposal.model_validate(raw)
    family = research_identity.infer_build_family([proposal])
    assert family is not None
    key = research_identity.knowledge_key(proposal, family)
    row = research_memory.ResearchMemoryService(initialize_store=False)._deep_record_values(
        proposal,
        record_id="drr-legacy-shared-record",
        build_family_key=family.key,
        knowledge_key=key,
        evidence_count=2,
        now="2026-09-06T00:00:00Z",
    )
    con.execute(
        f"INSERT INTO deep_research_records({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )
    evidence = {
        "knowledge_scope": row["knowledge_scope"],
        "knowledge_key": key,
        "source_case_ref": "case:source-a",
        "safe_evidence_refs": row["safe_evidence_refs"],
        "observed_component_keys": row["component_keys"],
        "observed_component_mentions": row["component_mentions"],
        "conditions": row["conditions"],
        "failure_conditions": row["failure_conditions"],
        "game_patch": row["game_patch"],
        "passive_tree_version": row["passive_tree_version"],
        "pob_version_or_commit": row["pob_version_or_commit"],
        "accepted_projection_hash": row["projection_hash"],
        "source_state_scope": row["source_state_scope"],
        "first_seen_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
    }
    for source in json.loads(row["source_case_refs"]):
        evidence["source_case_ref"] = source
        con.execute(
            f"INSERT INTO deep_research_record_evidence({','.join(evidence)}) "
            f"VALUES ({','.join('?' for _ in evidence)})",
            tuple(evidence.values()),
        )
    research_content.migrate(con, invalidate_receipts=False)
    con.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
    con.execute("UPDATE meta SET value='12' WHERE key='research_memory_revision'")
    con.commit()
    con.close()
    return path


def rows(con, table):
    return [dict(row) for row in con.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def test_shared_legacy_claims_keep_records_body_review_and_backup(tmp_path):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        before = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        before_evidence = rows(con, "deep_research_record_evidence")
        review = patch_reviews.submit(
            con,
            {
                "target_kind": "deep_research_record",
                "target_id": before["record_id"],
                "knowledge_scope": before["knowledge_scope"],
                "target_game_patch": "0.5.5",
                "source_fingerprint": patch_reviews.fingerprint(before),
                "outcome": "invalid",
                "rationale": "独立复核补丁差异，确认旧机制条件不再成立。",
                "correction_summary": "仅限制目标补丁采用，不重写旧知识正文。",
                "patch_evidence_refs": ["ggg:patch:0.5.5"],
                "review_evidence_refs": ["review:fixture-independent"],
                "author_ref": "agent:author",
                "reviewer_ref": "agent:reviewer",
            },
        )
        # Simulate a pre-claim-fingerprint review that still matches exactly.
        con.execute("UPDATE research_patch_reviews SET source_claim_fingerprint=NULL")
        revision = research_runtime.get_memory_revision(con)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert mature_learning.schema_version(con) == 7
        assert research_claims.installed(con)
        after = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        assert after == before
        assert research_runtime.get_memory_revision(con) == revision + 1
        evidence = rows(con, "deep_research_record_evidence")
        assert [
            {key: claim[key] for key in before_evidence[0]} for claim in evidence
        ] == before_evidence
        assert {claim["source_claim_key"] for claim in evidence} == {"default"}
        assert {claim["record_id"] for claim in evidence} == {before["record_id"]}
        assert {claim["binding_issue"] for claim in evidence} == {None}
        assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 1
        application = patch_reviews.applicability(con, after, "0.5.5")
        assert application["reviewRef"] == review["reviewRef"]
        assert application["adoptionAllowed"] is False
        research_claims.validate_storage(con)
    backup = path.with_name(path.name + ".pre-schema-6.sqlite")
    with mature_learning.connect(backup) as con:
        assert mature_learning.schema_version(con) == 6
        assert dict(con.execute("SELECT * FROM deep_research_records").fetchone()) == before
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert research_runtime.get_memory_revision(con) == revision + 1
        assert research_claims.migrate(con)["status"] == "already_applied"


@pytest.mark.parametrize(
    "sql,issue",
    [
        ("accepted_projection_hash=NULL", "missing_projection_hash"),
        ("accepted_projection_hash='unrecoverable-old-body'", "projection_unavailable"),
        ("source_case_ref='case:unsupported-source'", "source_reference_mismatch"),
        ("game_patch='0.5.3'", "source_version_mismatch"),
        ("source_state_scope='alternate_weapon_state'", "source_state_mismatch"),
    ],
)
def test_incomplete_source_is_a_gap_without_disabling_other_source(tmp_path, sql, issue):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        con.execute(
            f"UPDATE deep_research_record_evidence SET {sql} WHERE source_case_ref='case:source-b'"
        )
        old_evidence = rows(con, "deep_research_record_evidence")
        old_record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        evidence = rows(con, "deep_research_record_evidence")
        assert evidence[0]["record_id"] == old_record["record_id"]
        assert evidence[1]["record_id"] is None
        assert evidence[1]["binding_issue"] == issue
        assert [{key: claim[key] for key in old_evidence[0]} for claim in evidence] == old_evidence
        migrated = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        derived = {"source_case_refs", "safe_evidence_refs", "evidence_count"}
        assert {key: value for key, value in migrated.items() if key not in derived} == {
            key: value for key, value in old_record.items() if key not in derived
        }
        assert migrated["evidence_count"] == 1
        assert json.loads(migrated["source_case_refs"]) == ["case:source-a"]
        research_claims.validate_storage(con)
        with pytest.raises(ValueError, match="research_release_claim_unbound"):
            research_claims.validate_storage(con, release=True)


def test_tampered_body_is_not_repaired_by_recomputing_evidence(tmp_path):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        con.execute("UPDATE deep_research_records SET content='后写入但没有验收证据的内容。'")
        hashes = [
            row[0]
            for row in con.execute(
                "SELECT accepted_projection_hash FROM deep_research_record_evidence"
            )
        ]
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert {
            row[0] for row in con.execute("SELECT binding_issue FROM deep_research_record_evidence")
        } == {"record_projection_mismatch"}
        assert [
            row[0]
            for row in con.execute(
                "SELECT accepted_projection_hash FROM deep_research_record_evidence"
            )
        ] == hashes


def test_failure_rolls_back_every_schema_and_data_change(tmp_path, monkeypatch):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        before_records = [dict(row) for row in con.execute("SELECT * FROM deep_research_records")]
        before_evidence = rows(con, "deep_research_record_evidence")

    def fail_validation(*args, **kwargs):
        raise ValueError("fixture-final-validation-failed")

    with monkeypatch.context() as patch:
        patch.setattr(research_claims, "validate_storage", fail_validation)
        with pytest.raises(ValueError, match="fixture-final-validation-failed"):
            mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert mature_learning.schema_version(con) == 6
        assert not research_claims.installed(con)
        assert [
            dict(row) for row in con.execute("SELECT * FROM deep_research_records")
        ] == before_records
        assert rows(con, "deep_research_record_evidence") == before_evidence
        assert research_runtime.get_memory_revision(con) == 12
    mature_learning.initialize_store(path)
    assert len(list(tmp_path.glob("legacy.sqlite.pre-schema-6*.sqlite"))) == 2


def test_same_source_claims_and_legacy_versions_can_coexist(tmp_path):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        extra = {**record, "record_id": "drr-distinct-variant", "conditions": '["不同适用条件。"]'}
        extra["projection_hash"] = research_runtime.projection_hash(extra)
        con.execute(
            f"INSERT INTO deep_research_records({','.join(extra)}) VALUES ({','.join('?' for _ in extra)})",
            tuple(extra.values()),
        )
        assert research_claims.has_variants(con, "global_seed")
        assert not research_claims.has_variants(con, "local_user")
        claim = dict(con.execute("SELECT * FROM deep_research_record_evidence LIMIT 1").fetchone())
        insert = f"INSERT INTO deep_research_record_evidence({','.join(claim)}) VALUES ({','.join('?' for _ in claim)})"
        branch = {
            **claim,
            "source_claim_key": "boss-no-kills",
            "record_id": extra["record_id"],
            "accepted_projection_hash": extra["projection_hash"],
        }
        con.execute(insert, tuple(branch.values()))
        older = {
            **claim,
            "game_patch": "0.5.3",
            "record_id": None,
            "binding_issue": "source_version_mismatch",
        }
        con.execute(insert, tuple(older.values()))
        assert con.execute("SELECT count(*) FROM deep_research_record_evidence").fetchone()[0] == 4
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(insert, tuple(branch.values()))
        research_claims.validate_storage(con)


def test_binding_validation_rejects_wrong_record_and_mixed_issue(tmp_path):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        con.execute(
            "UPDATE deep_research_record_evidence SET binding_issue='projection_unavailable'"
        )
        with pytest.raises(ValueError, match="research_claim_bound_with_gap"):
            research_claims.validate_storage(con)
        con.execute(
            "UPDATE deep_research_record_evidence SET binding_issue=NULL,record_id='drr-missing'"
        )
        with pytest.raises(ValueError, match="research_claim_record_missing"):
            research_claims.validate_storage(con)


def test_ambiguous_legacy_targets_are_not_selected_by_row_order(tmp_path):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        record["record_id"] = "drr-legacy-ambiguous-copy"
        con.execute("DROP INDEX idx_deep_research_records_scope_knowledge")
        con.execute(
            f"INSERT INTO deep_research_records({','.join(record)}) VALUES ({','.join('?' for _ in record)})",
            tuple(record.values()),
        )
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 2
        assert {
            tuple(row)
            for row in con.execute(
                "SELECT record_id,binding_issue FROM deep_research_record_evidence"
            )
        } == {(None, "projection_ambiguous")}


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("record_schema_version", 1, "legacy_record_schema"),
        ("source_state_scope", "unknown", "source_state_unknown"),
    ],
)
def test_legacy_or_unknown_records_keep_gap_even_with_exact_hash(tmp_path, field, value, issue):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        con.execute(f"UPDATE deep_research_records SET {field}=?", (value,))
        record = con.execute("SELECT * FROM deep_research_records").fetchone()
        projection = research_runtime.projection_hash(record)
        con.execute("UPDATE deep_research_records SET projection_hash=?", (projection,))
        con.execute(
            "UPDATE deep_research_record_evidence SET accepted_projection_hash=?,source_state_scope=?",
            (projection, record["source_state_scope"]),
        )
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert {
            tuple(row)
            for row in con.execute(
                "SELECT record_id,binding_issue FROM deep_research_record_evidence"
            )
        } == {(None, issue)}


def test_current_schema_rejects_corrupt_claim_index(tmp_path):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        con.execute("DROP INDEX idx_deep_research_record_evidence_record")
        con.execute(
            "CREATE INDEX idx_deep_research_record_evidence_record ON deep_research_record_evidence(source_case_ref)"
        )
    with pytest.raises(mature_learning.SchemaVersionError, match="claim schema is incomplete"):
        mature_learning.initialize_store(path)


def test_structural_migration_keeps_stale_review_untrusted(tmp_path):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        con.execute(
            "INSERT INTO research_patch_reviews(review_id,target_kind,target_id,knowledge_scope,source_game_patch,target_game_patch,source_fingerprint,outcome,rationale,correction_summary,verification_tasks,patch_evidence_refs,review_evidence_refs,author_ref,reviewer_ref,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "prv-fixture-stale",
                "deep_research_record",
                record["record_id"],
                record["knowledge_scope"],
                "0.5.4",
                "0.5.5",
                "0" * 64,
                "invalid",
                "原知识指纹不匹配，禁止重绑复核结论。",
                "保持历史复核。",
                "[]",
                '["ggg:patch:0.5.5"]',
                '["review:fixture-independent"]',
                "agent:author",
                "agent:reviewer",
                record["created_at"],
            ),
        )
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        review = con.execute("SELECT * FROM research_patch_reviews").fetchone()
        assert review["source_claim_fingerprint"] is None
        assert review["source_fingerprint"] == "0" * 64
        assert not patch_reviews.review_matches(review, record)


@pytest.mark.parametrize(
    "field,value,issue",
    [
        ("record_schema_version", 1, "legacy_record_schema"),
        ("source_state_scope", "unknown", "source_state_unknown"),
    ],
)
def test_exact_new_diagnostic_bindings_remain_non_release(tmp_path, field, value, issue):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        con.execute(f"UPDATE deep_research_records SET {field}=?", (value,))
        record = con.execute("SELECT * FROM deep_research_records").fetchone()
        projection = research_runtime.projection_hash(record)
        con.execute("UPDATE deep_research_records SET projection_hash=?", (projection,))
        con.execute(
            "UPDATE deep_research_record_evidence SET accepted_projection_hash=?,source_state_scope=?,binding_issue=?",
            (projection, record["source_state_scope"], issue),
        )
        research_claims.validate_storage(con)
        assert (
            con.execute(
                "SELECT count(*) FROM deep_research_record_evidence WHERE record_id IS NOT NULL AND binding_issue IS NULL"
            ).fetchone()[0]
            == 0
        )
        with pytest.raises(ValueError, match="research_release_claim_diagnostic_only"):
            research_claims.validate_storage(con, release=True)


@pytest.mark.parametrize(
    "corruption,error",
    [
        ("game_patch='0.5.3'", "source_version_mismatch"),
        ("passive_tree_version='wrong-tree'", "source_version_mismatch"),
        ("pob_version_or_commit='wrong-pob'", "source_version_mismatch"),
        ("source_case_ref='case:wrong-source'", "source_reference_mismatch"),
        ("source_state_scope='alternate_weapon_state'", "source_state_mismatch"),
        ("accepted_projection_hash='wrong-hash'", "binding_mismatch"),
        ("knowledge_scope='local_user'", "binding_mismatch"),
    ],
)
def test_diagnostic_issue_never_excuses_broken_structure(tmp_path, corruption, error):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        con.execute("UPDATE deep_research_records SET record_schema_version=1")
        record = con.execute("SELECT * FROM deep_research_records").fetchone()
        projection = research_runtime.projection_hash(record)
        con.execute("UPDATE deep_research_records SET projection_hash=?", (projection,))
        con.execute(
            "UPDATE deep_research_record_evidence SET accepted_projection_hash=?,binding_issue='legacy_record_schema'",
            (projection,),
        )
        research_claims.validate_storage(con)
        con.execute(
            f"UPDATE deep_research_record_evidence SET {corruption} WHERE source_case_ref='case:source-a'"
        )
        with pytest.raises(ValueError, match="research_claim_" + error):
            research_claims.validate_storage(con)


def test_diagnostic_binding_requires_the_actual_qualification_issue(tmp_path):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        con.execute("UPDATE deep_research_record_evidence SET binding_issue='legacy_record_schema'")
        with pytest.raises(ValueError, match="research_claim_diagnostic_issue_mismatch"):
            research_claims.validate_storage(con)
        con.execute("UPDATE deep_research_record_evidence SET binding_issue='source_state_unknown'")
        with pytest.raises(ValueError, match="research_claim_diagnostic_issue_mismatch"):
            research_claims.validate_storage(con)


def test_schema7_legacy_policy_downgrade_detaches_only_affected_claims(tmp_path):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        current = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        current["record_id"] = "drr-current-unaffected"
        current["knowledge_key"] = "ku-current-unaffected"
        con.execute(
            f"INSERT INTO deep_research_records({','.join(current)}) VALUES ({','.join('?' for _ in current)})",
            tuple(current.values()),
        )
        claim = dict(con.execute("SELECT * FROM deep_research_record_evidence LIMIT 1").fetchone())
        claim.update(record_id=current["record_id"], knowledge_key=current["knowledge_key"])
        con.execute(
            f"INSERT INTO deep_research_record_evidence({','.join(claim)}) VALUES ({','.join('?' for _ in claim)})",
            tuple(claim.values()),
        )
        con.execute(
            "UPDATE deep_research_records SET record_schema_version=1 WHERE record_id='drr-legacy-shared-record'"
        )
        legacy = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id='drr-legacy-shared-record'"
        ).fetchone()
        projection = research_runtime.projection_hash(legacy)
        con.execute(
            "UPDATE deep_research_records SET projection_hash=? WHERE record_id=?",
            (projection, legacy["record_id"]),
        )
        con.execute(
            "UPDATE deep_research_record_evidence SET accepted_projection_hash=?,binding_issue='legacy_record_schema' WHERE record_id=?",
            (projection, legacy["record_id"]),
        )
        revision = research_runtime.get_memory_revision(con)
        research_claims.validate_storage(con)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        legacy = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id='drr-legacy-shared-record'"
        ).fetchone()
        assert legacy["status"] == "needs_revalidation"
        assert legacy["projection_hash"] == projection
        assert {
            tuple(row)
            for row in con.execute(
                "SELECT record_id,binding_issue,accepted_projection_hash FROM deep_research_record_evidence WHERE knowledge_key=?",
                (legacy["knowledge_key"],),
            )
        } == {(None, "record_projection_mismatch", projection)}
        assert (
            dict(
                con.execute(
                    "SELECT * FROM deep_research_record_evidence WHERE record_id=?",
                    (current["record_id"],),
                ).fetchone()
            )
            == claim
        )
        assert research_runtime.get_memory_revision(con) == revision + 1
        research_claims.validate_storage(con)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert research_runtime.get_memory_revision(con) == revision + 1


def test_migration_removes_unproven_support_from_create_lane_and_preserves_review(
    tmp_path, monkeypatch
):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        con.execute(
            "UPDATE deep_research_records SET safe_evidence_refs=?",
            ('["safe:source-a","safe:source-b"]',),
        )
        con.execute(
            "UPDATE deep_research_record_evidence SET safe_evidence_refs='[\"safe:source-a\"]' WHERE source_case_ref='case:source-a'"
        )
        con.execute(
            "UPDATE deep_research_record_evidence SET safe_evidence_refs='[\"safe:source-b\"]',accepted_projection_hash='missing-older-body' WHERE source_case_ref='case:source-b'"
        )
        record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        family = record["build_family_key"]
        con.execute(
            "INSERT INTO research_build_families(knowledge_scope,build_family_key,ascendancy_key,primary_skill_key,primary_skill_keys,secondary_skill_keys,evidence_count,created_at,last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record["knowledge_scope"],
                family,
                record["ascendancy_key"],
                "skill:LightningArrowPlayer",
                '["skill:LightningArrowPlayer"]',
                "[]",
                2,
                record["created_at"],
                record["last_seen_at"],
            ),
        )
        for source in ("case:source-a", "case:source-b"):
            con.execute(
                "INSERT INTO research_build_family_evidence VALUES (?,?,?,?,?)",
                (
                    record["knowledge_scope"],
                    family,
                    source,
                    record["created_at"],
                    record["last_seen_at"],
                ),
            )
            con.execute(
                "INSERT INTO research_source_provenance VALUES (?,?,?,?,?)",
                (
                    source,
                    record["knowledge_scope"],
                    "fixture:explicit",
                    record["created_at"],
                    record["last_seen_at"],
                ),
            )
        review = patch_reviews.submit(
            con,
            {
                "target_kind": "deep_research_record",
                "target_id": record["record_id"],
                "knowledge_scope": record["knowledge_scope"],
                "target_game_patch": "0.5.5",
                "source_fingerprint": patch_reviews.fingerprint(record),
                "outcome": "invalid",
                "rationale": "独立补丁复核确认旧机制前提不再成立。",
                "correction_summary": "仅限制目标补丁的采用权限。",
                "patch_evidence_refs": ["ggg:patch:0.5.5"],
                "review_evidence_refs": ["review:independent-fixture"],
                "author_ref": "agent:author",
                "reviewer_ref": "agent:reviewer",
            },
        )
        con.execute("UPDATE research_patch_reviews SET source_claim_fingerprint=NULL")
    reports = []
    migrate = research_claims.migrate

    def capture_report(con, **kwargs):
        report = migrate(con, **kwargs)
        reports.append(report)
        return report

    monkeypatch.setattr(research_claims, "migrate", capture_report)
    service = research_memory.ResearchMemoryService(db_path=path)
    result = service.query_research_memory(
        "",
        build_family_keys=[family],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        response_profile="create_compact",
        detail_level="record",
        knowledge_scope="global_seed",
        source_case_ref="case:source-a",
    )
    assert result["status"] == "known", result
    assert result["selectedSourceCaseRef"] == "case:source-a"
    assert len(result["deepResearchRecords"]) == 1
    recalled = result["deepResearchRecords"][0]
    assert recalled["recordId"] == record["record_id"]
    assert recalled["evidenceCount"] == 1
    assert recalled["sourceCaseRefs"] == ["case:source-a"]
    assert recalled["safeEvidenceRefs"] == ["safe:source-a"]
    assert recalled["content"] == record["content"]
    assert reports[0]["derivedMetadataCorrectedCount"] == 1
    assert reports[0]["boundClaims"] == reports[0]["gapClaims"] == 1
    with mature_learning.connect(path) as con:
        migrated = con.execute("SELECT * FROM deep_research_records").fetchone()
        immutable = set(record) - {"source_case_refs", "safe_evidence_refs", "evidence_count"}
        assert {key: migrated[key] for key in immutable} == {key: record[key] for key in immutable}
        actual_review = con.execute("SELECT * FROM research_patch_reviews").fetchone()
        assert patch_reviews.review_matches(actual_review, migrated)
        assert actual_review["source_fingerprint"] == patch_reviews.fingerprint(record)
        application = patch_reviews.applicability(con, migrated, "0.5.5")
        assert application["reviewRef"] == review["reviewRef"]
        assert application["adoptionAllowed"] is False
        gap = con.execute(
            "SELECT * FROM deep_research_record_evidence WHERE source_case_ref='case:source-b'"
        ).fetchone()
        assert gap["record_id"] is None
        assert gap["accepted_projection_hash"] == "missing-older-body"
        assert gap["safe_evidence_refs"] == '["safe:source-b"]'


def test_migration_zero_support_retains_body_but_clears_only_current_support_cache(tmp_path):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        con.execute(
            "UPDATE deep_research_record_evidence SET accepted_projection_hash='missing-older-body'"
        )
        before = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        report = research_claims.migrate(con)
        after = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        assert report["derivedMetadataCorrectedCount"] == 1
        assert report["boundClaims"] == 0
        assert report["gapClaims"] == 2
        assert after == {
            **before,
            "evidence_count": 0,
            "source_case_refs": "[]",
            "safe_evidence_refs": "[]",
        }
        research_claims.validate_storage(con)


def test_migration_preserves_schema1_diagnostic_metadata_and_reports_clean_cache(tmp_path):
    path = legacy_store(tmp_path)
    with mature_learning.connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        clean = research_claims.migrate(con)
        assert clean["derivedMetadataCorrectedCount"] == 0
        con.rollback()
        con.execute("UPDATE deep_research_records SET record_schema_version=1")
        before = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        report = research_claims.migrate(con)
        assert report["derivedMetadataCorrectedCount"] == 0
        assert dict(con.execute("SELECT * FROM deep_research_records").fetchone()) == before


def test_migration_audit_preserves_safe_removed_ids_and_digests_untrusted_refs(tmp_path):
    path = legacy_store(tmp_path)
    safe_source = "source-hash:0123456789abcdef"
    unsafe_source = "https://example.invalid/character/private-account-name"
    unsafe_safe_ref = "accountName=private-account-name"
    with mature_learning.connect(path) as con:
        con.execute(
            "UPDATE deep_research_records SET record_id=?,source_case_refs=?,safe_evidence_refs=?,evidence_count=4",
            (
                "drr-0123456789abcdef",
                json.dumps(["case:source-a", "case:source-b", safe_source, unsafe_source]),
                json.dumps(["safe:fixture:projection", unsafe_safe_ref]),
            ),
        )
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        audit_text = con.execute(
            "SELECT value FROM meta WHERE key=?", (research_claims.MIGRATION_REPORT_META_KEY,)
        ).fetchone()[0]
        audit = json.loads(audit_text)
        assert audit["schemaVersion"] == 1
        assert audit["targetDatabaseSchemaVersion"] == 7
        assert (
            audit["derivedMetadataCorrectedCount"] == len(audit["derivedMetadataCorrections"]) == 1
        )
        correction = audit["derivedMetadataCorrections"][0]
        assert correction["recordId"] == "drr-0123456789abcdef"
        assert safe_source in correction["removedSourceCaseRefs"]
        assert len(correction["removedSourceCaseRefs"]) == 2
        assert any(
            ref.startswith("audit-ref:sha256:") for ref in correction["removedSourceCaseRefs"]
        )
        assert len(correction["removedSafeEvidenceRefs"]) == 1
        assert correction["removedSafeEvidenceRefs"][0].startswith("audit-ref:sha256:")
        assert correction["previousEvidenceCount"] == 4
        assert correction["currentEvidenceCount"] == 2
        assert unsafe_source not in audit_text
        assert unsafe_safe_ref not in audit_text
        assert "private-account-name" not in audit_text
        assert "https://" not in audit_text
        assert (
            con.execute("SELECT content FROM deep_research_records").fetchone()[0] not in audit_text
        )
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert (
            con.execute(
                "SELECT value FROM meta WHERE key=?", (research_claims.MIGRATION_REPORT_META_KEY,)
            ).fetchone()[0]
            == audit_text
        )


def test_same_schema_family_repair_invalidates_revision_once(tmp_path):
    path = legacy_store(tmp_path)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        con.execute("PRAGMA foreign_keys=OFF")
        record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        con.execute("DROP TABLE research_build_family_evidence")
        con.execute("DROP TABLE research_build_families")
        con.execute(
            "CREATE TABLE research_build_families (build_family_key TEXT PRIMARY KEY,ascendancy_key TEXT,primary_skill_key TEXT,primary_skill_keys TEXT,secondary_skill_keys TEXT,evidence_count INTEGER,created_at TEXT,last_seen_at TEXT)"
        )
        con.execute(
            "CREATE TABLE research_build_family_evidence (build_family_key TEXT,source_case_ref TEXT,first_seen_at TEXT,last_seen_at TEXT,PRIMARY KEY(build_family_key,source_case_ref))"
        )
        con.execute(
            "INSERT INTO research_build_families VALUES (?,?,?,?,?,?,?,?)",
            (
                record["build_family_key"],
                record["ascendancy_key"],
                "skill:CometPlayer",
                '["skill:CometPlayer"]',
                "[]",
                2,
                record["created_at"],
                record["last_seen_at"],
            ),
        )
        revision = research_runtime.get_memory_revision(con)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert research_runtime.get_memory_revision(con) == revision + 1
        assert (
            con.execute("SELECT status FROM deep_research_records").fetchone()[0]
            == "needs_revalidation"
        )
        assert {
            tuple(row)
            for row in con.execute(
                "SELECT record_id,binding_issue,accepted_projection_hash FROM deep_research_record_evidence"
            )
        } == {(None, "record_projection_mismatch", record["projection_hash"])}
        research_claims.validate_storage(con)
    mature_learning.initialize_store(path)
    with mature_learning.connect(path) as con:
        assert research_runtime.get_memory_revision(con) == revision + 1
