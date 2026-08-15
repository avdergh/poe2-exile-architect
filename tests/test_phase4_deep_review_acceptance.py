from __future__ import annotations

from datetime import UTC, datetime
import json

from scripts import run_phase4_deep_review_acceptance
from server.knowledge import graph_tools as gt
from server.knowledge import mature_learning
from server.knowledge import physical_graph as pg


def test_deep_review_acceptance_writes_only_resolved_case_observations(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 1
    assert isinstance(report["deferredCandidateCount"], int)
    observation = report["singleComponentObservations"][0]
    assert observation["confidenceTier"] == "case_observation"
    assert "common" not in observation["summaryZh"].casefold()
    assert observation["componentResolutions"][0]["resolutionSource"] == ("direct_resolver")

    serialized = json.dumps(report, ensure_ascii=False)
    assert "rawXml" not in serialized
    assert "rawImportCode" not in serialized
    assert "PathOfBuilding" not in serialized
    assert "eNrt" not in serialized
    assert "full support" not in serialized.casefold()

    con = mature_learning.connect(db_path)
    try:
        assert (
            con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0]
            == report["acceptedPatternCount"]
        )
        assert (
            con.execute("SELECT count(*) FROM research_build_design_observations").fetchone()[0]
            == 1
        )
    finally:
        con.close()

    json_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    md_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "单例：fixture pattern" in json_text
    assert "单例：fixture pattern" in md_text
    assert "Researcher conclusions were accepted only" in md_text


def test_deep_review_acceptance_persists_focused_records_with_patterns(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="deep-record-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "deep-record-report.json",
        md_output=tmp_path / "deep-record-report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedDeepRecordCount"] == 1
    assert report["createdDeepRecordCount"] == 1
    assert report["updatedDeepRecordCount"] == 0
    assert report["addedDeepRecordEvidenceCount"] in {0, 1}
    assert report["unresolvedDeepRecordComponentCount"] == 0
    assert report["deepRecordsWithUnresolvedComponents"] == []
    accepted_record = report["acceptedDeepRecords"][0]
    record_write = report["deepRecordWrite"]["recordWrites"][0]
    assert accepted_record["recordId"] == record_write["recordId"]
    assert record_write["title"] == accepted_record["titleZh"]
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT record_id, research_group_id, record_kind, content FROM deep_research_records"
        ).fetchone()
        assert row["record_id"] == accepted_record["recordId"]
        assert row["research_group_id"] == "research:fixture_sample_001"
        assert row["record_kind"] == "mechanic_chain"
        assert "一个主要机制问题" in row["content"]
    finally:
        con.close()


def test_deep_review_acceptance_persists_review_semantic_edges(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="semantic-edges-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["semanticEdges"] = [
        {
            "source_key": "skill:ResolvedOnlyPlayer",
            "target_key": "unique:FixtureIdentityItem",
            "source_resolution": _resolution_evidence("skill:ResolvedOnlyPlayer"),
            "target_resolution": _resolution_evidence("unique:FixtureIdentityItem"),
            "edge_type": "enables_mechanic",
            "rationale": "Fixture mechanism-level relationship from the reviewed sample.",
            "source_case_refs": ["case:fixture-sample-001"],
            "safe_evidence_refs": ["safe:fixture-sample-001"],
            "game_patch": "0.5.4",
            "passive_tree_version": "0_5",
            "pob_version_or_commit": "unknown",
            "status": "valid",
            "confidence": "low",
            "modelability": "partial",
            "copy_safety_state": "passed",
            "context_requirements": [
                {"context_type": "verification_gate_requirement", "task": "Fixture verify."}
            ],
            "affected_component_keys": [
                "skill:ResolvedOnlyPlayer",
                "unique:FixtureIdentityItem",
            ],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
            "directionality": "directional",
        }
    ]
    review_file.write_text(json.dumps(review, ensure_ascii=True, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "semantic-edges-report.json",
        md_output=tmp_path / "semantic-edges-report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedSemanticEdgeCount"] == 1
    assert report["durableWritePerformed"] is True
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT source_key, target_key, edge_type FROM research_semantic_edges"
        ).fetchone()
        assert row["source_key"] == "skill:ResolvedOnlyPlayer"
        assert row["target_key"] == "unique:FixtureIdentityItem"
        assert row["edge_type"] == "enables_mechanic"
    finally:
        con.close()


def test_deep_review_acceptance_rejects_invalid_semantic_edges(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    # Multi-component candidate so the pattern payload is non-empty: without the
    # preview_visible gate the rejected report would list acceptedPatterns (and
    # recordKindCounts) from candidates that were never persisted.
    review_file = _write_review(
        tmp_path,
        filename="semantic-edges-invalid-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Identity Item",
                "componentKey": "unique:FixtureIdentityItem",
                "role": "unique_enabler",
                "resolverQuery": "Fixture Identity Item",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["semanticEdges"] = [
        {
            "source_key": "skill:ResolvedOnlyPlayer",
            "target_key": "unique:FixtureIdentityItem",
            "edge_type": "synergizes_with",
            "rationale": "Fixture relationship.",
            "source_case_refs": ["case:fixture-sample-001"],
            "game_patch": "0.5.4",
            "passive_tree_version": "0_5",
            "pob_version_or_commit": "unknown",
            "status": "valid",
            "confidence": "low",
            "modelability": "partial",
            "copy_safety_state": "passed",
            "context_requirements": [
                {"context_type": "verification_gate_requirement", "task": "Fixture verify."}
            ],
            "affected_component_keys": [
                "skill:ResolvedOnlyPlayer",
                "unique:FixtureIdentityItem",
            ],
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledge_scope": "global_seed",
            "directionality": "associative",
        }
    ]
    review_file.write_text(json.dumps(review, ensure_ascii=True, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "semantic-edges-invalid-report.json",
        md_output=tmp_path / "semantic-edges-invalid-report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    assert report["acceptedSemanticEdgeCount"] == 0
    assert report["semanticEdgeWrite"]["status"] != "accepted"
    assert report["durableWritePerformed"] is False
    assert report["acceptedDeepRecordCount"] == 0
    assert report["acceptedDeepRecords"] == []
    assert report["acceptedBuildFamilyKeys"] == []
    assert report["recordKindCounts"] == {}
    assert report["acceptedPatternCount"] == 0
    assert report["acceptedPatterns"] == []
    assert report["acceptedTransferCandidateCount"] == 0
    assert report["promotedTransferPatternCount"] == 0
    assert report["promotedTransferPatternIds"] == []
    assert report["siblingFamilyHints"] == []
    # Pin that the zeroed previews come from the gate, not an empty payload: the
    # pattern candidate validated and produced exactly one candidate id.
    assert len(report["patternWrite"].get("candidatePatternIds") or []) == 1
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_semantic_edges").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0] == 0
        assert (
            con.execute("SELECT count(*) FROM research_build_design_observations").fetchone()[0]
            == 0
        )
    finally:
        con.close()


def _resolution_evidence(key: str) -> dict[str, object]:
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": key,
        "snapshot_id": "snapshot:deep-review-fixture",
        "evidence_path_nodes": [key],
        "source_refs": ["fixture:deep_review"],
    }


def test_deep_review_acceptance_persists_revision_pinned_mechanic_evidence(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="mechanic-audit-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    source_ref = "poe2wiki:page:855:rev:130794"
    review["mechanicAudit"] = [
        {
            "claim": "该案例使用的转换机制需要按当前转换顺序解释。",
            "claimType": "conversion_or_transform",
            "affectedRecords": ["聚焦机制链"],
            "affectedCandidates": ["单例：fixture pattern"],
            "wiki": {
                "status": "supports",
                "pageTitle": "Damage conversion",
                "sourceRef": source_ref,
            },
            "corroboration": ["source_artifact", "pinned_pob_static"],
            "decision": "keep",
        }
    ]
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "mechanic-audit-report.json",
        md_output=tmp_path / "mechanic-audit-report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["mechanicAuditEntryCount"] == 1
    assert report["mechanicAuditPinnedRevisionCount"] == 1
    assert report["mechanicAuditSchemaIssueCount"] == 0
    assert report["mechanicAuditLiveEvidenceStatus"] == "complete"
    assert report["mechanicAuditUnauditedHighRiskRecordCount"] == 0
    assert report["mechanicAuditAdvisories"] == []
    con = mature_learning.connect(db_path)
    try:
        record_refs = json.loads(
            con.execute("SELECT safe_evidence_refs FROM deep_research_records").fetchone()[0]
        )
        observation_refs = json.loads(
            con.execute(
                "SELECT safe_evidence_refs FROM research_build_design_observations"
            ).fetchone()[0]
        )
        assert source_ref in record_refs
        assert source_ref in observation_refs
    finally:
        con.close()


def test_acceptance_uses_gear_base_for_non_weapon_item_bases(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    item_key = "item_base:Metadata/Items/Armours/BodyArmours/Fixture"
    review_file = _write_review(
        tmp_path,
        filename="gear-base-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Body Armour",
                "componentKey": item_key,
                "role": "gear_base",
                "resolverQuery": "Fixture Body Armour",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["recordKind"] = "gear_synergy"
    record["title"] = "非武器装备基底职责"
    record["summary"] = "护甲基底使用通用装备角色，不冒充武器基底。"
    record["typedPayload"] = {
        "gearResponsibilities": [
            {
                "componentKey": item_key,
                "responsibilityType": "defense",
                "responsibility": "提供护甲部位的防御基底。",
            }
        ]
    }
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["unresolvedDeepRecordMentionCount"] == 0
    con = mature_learning.connect(db_path)
    try:
        mentions = json.loads(
            con.execute("SELECT component_mentions FROM deep_research_records").fetchone()[0]
        )
    finally:
        con.close()
    assert next(item for item in mentions if item["component_key"] == item_key)["role"] == (
        "gear_base"
    )


def test_deep_review_acceptance_marks_single_case_transfer_candidate_with_origin_family(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="transfer-candidate-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Support",
                "componentKey": "support:FixtureSupport",
                "role": "support_modifier",
                "resolverQuery": "Fixture Support",
            },
        ],
        include_deep_record=True,
        candidate_overrides={
            "transferScope": "component",
            "transferRationale": "The package depends on skill/support compatibility, not ascendancy.",
            "applicabilityRequirements": ["The active skill can use this support behavior."],
            "exclusionConditions": ["Do not use when support legality fails."],
        },
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["ascendancyKey"] = "ascendancy:ranger:deadeye"
    review["deepResearchRecords"].append(
        {
            "sampleId": "fixture_sample_001",
            "researchGroupId": "research:fixture_sample_001",
            "caseRef": "case:fixture-sample-001",
            "safeEvidenceRef": "safe:fixture-sample-001",
            "recordKind": "gear_synergy",
            "title": "身份装备职责",
            "summary": "明确记录身份装备职责后才允许跨 Family 迁移。",
            "content": "Fixture Identity Item 提供该技能包的身份机制。",
            "contentLanguage": "zh-CN",
            "lengthExceptionReason": None,
            "components": [
                {
                    "candidateName": "Fixture Identity Item",
                    "componentKey": "unique:FixtureIdentityItem",
                    "role": "unique_enabler",
                    "resolverQuery": "Fixture Identity Item",
                }
            ],
            "conditions": [],
            "failureConditions": [],
            "typedPayload": {
                "gearResponsibilities": [
                    {
                        "componentKey": "unique:FixtureIdentityItem",
                        "responsibilityType": "identity_enabler",
                        "responsibility": "Enables the transferred skill package identity.",
                    }
                ]
            },
            "ascendancyKey": "ascendancy:ranger:deadeye",
            "extractionMethodVersion": "deep_research_mvp_v1",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobVersionOrCommit": "unknown",
        }
    )
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedTransferCandidateCount"] == 1
    assert report["promotedTransferPatternCount"] == 0
    assert report["createdBuildFamilyCount"] == 1
    assert report["addedBuildFamilyEvidenceCount"] == 1
    con = mature_learning.connect(db_path)
    try:
        row = con.execute("SELECT * FROM research_build_patterns").fetchone()
        assert row["transfer_scope"] == "component"
        assert row["confidence_tier"] == "case_observation"
        assert len(json.loads(row["origin_family_keys"])) == 1
    finally:
        con.close()


def test_acceptance_defers_family_record_without_canonical_knowledge_identity(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="unkeyed-resource-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["ascendancyKey"] = "ascendancy:ranger:deadeye"
    resource_record = json.loads(json.dumps(review["deepResearchRecords"][0]))
    resource_record.update(
        {
            "recordKind": "resource_engine",
            "title": "普通法力偷取与法力瓶续航",
            "summary": "通过普通词缀与药剂维持续航。",
            "content": "物理攻击法力偷取负责持续回复，法力瓶处理无目标阶段。",
            "typedPayload": {},
        }
    )
    review["deepResearchRecords"].append(resource_record)
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        validation_only=True,
    )

    assert report["status"] == "accepted"
    assert report["acceptedDeepRecordCount"] == 1
    assert report["unkeyedDeepRecordCount"] == 1
    assert report["deferredReasonCounts"] == {"missing_knowledge_identity": 1}
    assert report["deepRecordsWithoutKnowledgeIdentity"][0]["recordKind"] == "resource_engine"


def test_acceptance_keys_resource_record_with_structured_mechanisms(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="keyed-resource-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record.update(
        {
            "ascendancyKey": "ascendancy:ranger:deadeye",
            "recordKind": "resource_engine",
            "title": "普通法力偷取与法力瓶续航",
            "summary": "通过普通词缀与药剂维持续航。",
            "content": "物理攻击法力偷取负责持续回复，法力瓶处理无目标阶段。",
            "typedPayload": {"resourceMechanisms": ["mana_leech", "mana_flask"]},
        }
    )
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedDeepRecordCount"] == 1
    assert report["unkeyedDeepRecordCount"] == 0
    assert report["addedDeepRecordEvidenceCount"] == 1


def test_acceptance_is_idempotent_for_the_same_safe_review(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="idempotent-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )

    for suffix in ("first", "second"):
        report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
            db_path=db_path,
            json_output=tmp_path / f"{suffix}.json",
            md_output=tmp_path / f"{suffix}.md",
            review_file=review_file,
            graph_service=_graph_service(),
        )
        assert report["acceptedDeepRecordCount"] == 1

    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
        assert (
            con.execute("SELECT count(*) FROM research_build_design_observations").fetchone()[0]
            == 1
        )
    finally:
        con.close()


def test_case_depth_rejection_writes_nothing(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="depth-rejected-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=False,
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "rejected.json",
        md_output=tmp_path / "rejected.md",
        review_file=review_file,
        graph_service=_graph_service(),
        require_deep_records=True,
    )

    assert report["status"] == "rejected"
    assert report["deferredReasonCounts"]["missing_deep_research_records"] == 1
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
        assert (
            con.execute("SELECT count(*) FROM research_build_design_observations").fetchone()[0]
            == 0
        )
        assert con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0] == 0
    finally:
        con.close()


def test_queue_rejects_case_when_all_submitted_deep_records_are_deferred(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="all-records-deferred-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Support",
                "componentKey": "support:FixtureSupport",
                "role": "support_modifier",
                "resolverQuery": "Fixture Support",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["caseCoverage"] = {
        "supports": "evidence_missing",
        "rotation": "evidence_missing",
        "passiveAscendancy": "not_applicable",
        "gearRoles": "evidence_missing",
        "resourceDefense": "evidence_missing",
    }
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        require_deep_records=True,
    )

    assert report["status"] == "rejected"
    assert report["acceptanceMode"] == "blocked"
    assert report["deferredReasonCounts"]["missing_deep_research_records"] == 1
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
    finally:
        con.close()


def test_validation_only_uses_acceptance_logic_without_writing_memory_or_reports(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    json_output = tmp_path / "validation.json"
    md_output = tmp_path / "validation.md"
    review_file = _write_review(
        tmp_path,
        filename="validation-only-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["ascendancyKey"] = "ascendancy:ranger:deadeye"
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=json_output,
        md_output=md_output,
        review_file=review_file,
        graph_service=_graph_service(),
        require_deep_records=True,
        validation_only=True,
    )

    assert report["status"] == "accepted"
    assert report["validationOnly"] is True
    assert report["durableWritePerformed"] is False
    assert report["acceptedDeepRecordCount"] == 1
    assert not db_path.exists()
    assert not json_output.exists()
    assert not md_output.exists()


def test_validation_only_reports_custom_role_with_canonical_values(tmp_path):
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "validation.json",
        md_output=tmp_path / "validation.md",
        review_file=_write_review(
            tmp_path,
            filename="invalid-role-review.json",
            components=[
                {
                    "candidateName": "Resolved Only",
                    "componentKey": "skill:ResolvedOnlyPlayer",
                    "role": "burst_window",
                    "resolverQuery": "Resolved Only",
                }
            ],
            include_deep_record=True,
        ),
        graph_service=_graph_service(),
        require_deep_records=True,
        validation_only=True,
    )

    invalid = [
        item
        for item in report["deferredCandidates"]
        if item.get("reason") == "invalid_schema" and item.get("validationIssues")
    ]
    assert invalid
    issue = invalid[0]["validationIssues"][0]
    assert issue["submittedValue"] == "burst_window"
    assert "payoff" in issue["allowedValues"]
    assert "burst_window" not in issue["allowedValues"]
    assert not (tmp_path / "memory.sqlite").exists()


def test_acceptance_prevalidates_all_payloads_before_any_durable_write(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        filename="mixed-validity-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["components"][0]["role"] = "burst_window"
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        require_deep_records=True,
    )

    assert report["status"] == "rejected"
    assert report["durableWritePerformed"] is False
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
        assert (
            con.execute("SELECT count(*) FROM research_build_design_observations").fetchone()[0]
            == 0
        )
        assert con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0] == 0
    finally:
        con.close()


def test_deep_review_acceptance_accepts_plural_safe_evidence_refs(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="plural-evidence-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    for item in [*review["deepResearchRecords"], *review["candidateReviews"]]:
        evidence = item.pop("safeEvidenceRef")
        item["safeEvidenceRefs"] = [evidence, "safe:secondary-evidence"]
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedDeepRecordCount"] == 1
    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        refs = json.loads(
            con.execute("SELECT safe_evidence_refs FROM deep_research_records").fetchone()[0]
        )
        assert refs == ["safe:fixture-sample-001", "safe:secondary-evidence"]
    finally:
        con.close()


def test_deep_review_acceptance_audits_declared_case_coverage(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="coverage-review.json",
        components=[
            {
                "candidateName": "Fixture Support",
                "componentKey": "support:FixtureSupport",
                "role": "support_modifier",
                "resolverQuery": "Fixture Support",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["caseCoverage"] = {
        "supports": "covered",
        "rotation": "covered",
        "passiveAscendancy": "not_applicable",
        "gearRoles": "evidence_missing",
        "resourceDefense": "evidence_missing",
    }
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["caseCoverage"]["supports"] == "evidence_missing"
    assert report["caseCoverage"]["rotation"] == "evidence_missing"
    assert report["caseCoverage"]["passiveAscendancy"] == "not_applicable"
    assert report["caseCoverageGapCount"] == 4
    assert any("caseCoverage.rotation" in item for item in report["caseCoverageAdvisories"])
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "## Case Coverage" in markdown
    assert "rotation: `evidence_missing`" in markdown


def test_deep_review_acceptance_infers_legacy_coverage_with_advisory(tmp_path):
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="legacy-coverage-review.json",
            components=[
                {
                    "candidateName": "Fixture Support",
                    "componentKey": "support:FixtureSupport",
                    "role": "support_modifier",
                    "resolverQuery": "Fixture Support",
                }
            ],
            include_deep_record=True,
        ),
        graph_service=_graph_service(),
    )

    assert report["caseCoverage"]["supports"] == "evidence_missing"
    assert any("omitted caseCoverage" in item for item in report["caseCoverageAdvisories"])


def test_ordinary_notable_does_not_satisfy_passive_ascendancy_coverage():
    coverage, _ = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"passiveAscendancy": "covered"}},
        accepted_records=[
            {
                "recordKind": "passive_package",
                "componentRoles": ["passive_anchor"],
                "components": [{"componentKey": "notable:Fixture", "role": "passive_anchor"}],
                "typedPayload": {},
            }
        ],
    )

    assert coverage["passiveAscendancy"] == "evidence_missing"


def test_explicit_ascendancy_responsibility_satisfies_coverage():
    source = pg.GraphSource(
        source_id="fixture:ascendancy-coverage",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:ascendancy-coverage",
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(
                    "ascendancy:ranger:deadeye",
                    "ascendancy",
                    "Deadeye",
                    (source.source_id,),
                ),
                pg.GraphNode("notable:Fixture", "notable", "Fixture", (source.source_id,)),
            ),
            edges=(
                pg.GraphEdge(
                    "belongs_to",
                    "notable:Fixture",
                    "ascendancy:ranger:deadeye",
                    (source.source_id,),
                ),
            ),
        )
    )
    coverage, _ = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"passiveAscendancy": "covered"}},
        accepted_records=[
            {
                "recordKind": "passive_package",
                "componentRoles": ["ascendancy_shell", "passive_anchor"],
                "components": [
                    {
                        "componentKey": "ascendancy:ranger:deadeye",
                        "role": "ascendancy_shell",
                    },
                    {"componentKey": "notable:Fixture", "role": "passive_anchor"},
                ],
                "typedPayload": {
                    "ascendancyResponsibilities": [
                        {
                            "componentKey": "notable:Fixture",
                            "responsibility": "Provides the build's projectile duplication layer.",
                        }
                    ]
                },
            }
        ],
        graph_service=graph_service,
    )

    assert coverage["passiveAscendancy"] == "covered"


def test_functional_ascendancy_roles_validate_and_satisfy_coverage(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:functional-ascendancy-responsibility",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    shell_key = "ascendancy:fixture:shell"
    generator_key = "notable:FixtureGenerator"
    resource_key = "notable:FixtureResourceEngine"
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:functional-ascendancy-responsibility",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(shell_key, "ascendancy", "Fixture Shell", (source.source_id,)),
                pg.GraphNode(generator_key, "notable", "Fixture Generator", (source.source_id,)),
                pg.GraphNode(
                    resource_key, "notable", "Fixture Resource Engine", (source.source_id,)
                ),
            ),
            edges=(
                pg.GraphEdge("belongs_to", generator_key, shell_key, (source.source_id,)),
                pg.GraphEdge("belongs_to", resource_key, shell_key, (source.source_id,)),
            ),
        )
    )
    review_file = _write_review(tmp_path, components=[])
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["caseCoverage"] = {"passiveAscendancy": "covered"}
    review["deepResearchRecords"] = [
        {
            "sampleId": "fixture_sample_001",
            "researchGroupId": "research:fixture_sample_001",
            "caseRef": "case:fixture-sample-001",
            "safeEvidenceRef": "safe:fixture-sample-001",
            "recordKind": "passive_package",
            "title": "功能型升华职责",
            "summary": "升华节点分别提供生成与资源职责。",
            "content": "两个升华节点各自承担生成与资源引擎职责。",
            "contentLanguage": "zh-CN",
            "lengthExceptionReason": None,
            "components": [
                {
                    "candidateName": "Fixture Shell",
                    "componentKey": shell_key,
                    "role": "ascendancy_shell",
                    "resolverQuery": shell_key,
                },
                {
                    "candidateName": "Fixture Generator",
                    "componentKey": generator_key,
                    "role": "generator",
                    "resolverQuery": generator_key,
                },
                {
                    "candidateName": "Fixture Resource Engine",
                    "componentKey": resource_key,
                    "role": "resource_engine",
                    "resolverQuery": resource_key,
                },
            ],
            "conditions": ["节点属于当前升华。"],
            "failureConditions": ["节点未分配。"],
            "typedPayload": {
                "ascendancyResponsibilities": [
                    {"componentKey": generator_key, "responsibility": "生成机制状态。"},
                    {"componentKey": resource_key, "responsibility": "维持资源循环。"},
                ]
            },
            "extractionMethodVersion": "deep_research_mvp_v1",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobVersionOrCommit": "unknown",
        }
    ]
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=graph_service,
        validation_only=True,
    )

    assert report["acceptedDeepRecordCount"] == 1
    assert report["caseCoverage"]["passiveAscendancy"] == "covered"


def test_wrong_ascendancy_relationship_does_not_satisfy_coverage():
    source = pg.GraphSource(
        source_id="fixture:wrong-ascendancy",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:wrong-ascendancy",
            created_at=datetime(2026, 7, 16, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(
                    "ascendancy:druid:oracle", "ascendancy", "Oracle", (source.source_id,)
                ),
                pg.GraphNode(
                    "ascendancy:ranger:deadeye", "ascendancy", "Deadeye", (source.source_id,)
                ),
                pg.GraphNode("notable:Fixture", "notable", "Fixture", (source.source_id,)),
            ),
            edges=(
                pg.GraphEdge(
                    "belongs_to",
                    "notable:Fixture",
                    "ascendancy:druid:oracle",
                    (source.source_id,),
                ),
            ),
        )
    )

    coverage, _ = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"passiveAscendancy": "covered"}},
        accepted_records=[
            {
                "recordKind": "passive_package",
                "componentRoles": ["ascendancy_shell", "passive_anchor"],
                "components": [
                    {"componentKey": "ascendancy:ranger:deadeye", "role": "ascendancy_shell"},
                    {"componentKey": "notable:Fixture", "role": "passive_anchor"},
                ],
                "typedPayload": {
                    "ascendancyResponsibilities": [
                        {"componentKey": "notable:Fixture", "responsibility": "Wrong shell."}
                    ]
                },
            }
        ],
        graph_service=graph_service,
    )

    assert coverage["passiveAscendancy"] == "evidence_missing"


def test_duplicate_record_titles_are_deferred_as_invalid_schema():
    records = [
        {
            "research_group_id": "research:fixture",
            "record_kind": "skill_package",
            "title": "重复标题",
            "component_mentions": [
                {
                    "role": "primary_damage",
                    "component_key": "skill:SparkPlayer",
                    "resolution_status": "resolved",
                }
            ],
            "typed_payload": {},
        },
        {
            "research_group_id": "research:fixture",
            "record_kind": "skill_package",
            "title": " 重复标题 ",
            "component_mentions": [
                {
                    "role": "clear_skill",
                    "component_key": "skill:ArcPlayer",
                    "resolution_status": "resolved",
                }
            ],
            "typed_payload": {},
        },
    ]
    accepted = [
        {
            "titleZh": "重复标题",
            "recordKind": "skill_package",
            "sampleId": "case:fixture",
            "componentKeys": ["skill:SparkPlayer"],
        },
        {
            "titleZh": "重复标题",
            "recordKind": "skill_package",
            "sampleId": "case:fixture",
            "componentKeys": ["skill:ArcPlayer"],
        },
    ]

    kept, kept_summaries, deferred = (
        run_phase4_deep_review_acceptance._filter_deep_records_with_identity(
            records=records,
            accepted=accepted,
        )
    )

    assert kept == []
    assert kept_summaries == []
    assert len(deferred) == 2
    assert {item["reason"] for item in deferred} == {"invalid_schema"}
    assert "duplicate" in deferred[0]["validationIssues"][0]["msg"].lower()


def test_support_coverage_checks_triggered_payload_and_declared_host_across_group():
    records = [
        {
            "researchGroupId": "research:fixture",
            "recordKind": "skill_package",
            "components": [
                {"componentKey": "skill:SparkPlayer", "role": "primary_damage"},
            ],
            "typedPayload": {
                "supportPackages": [
                    {
                        "skillKey": "skill:SparkPlayer",
                        "supportKeys": ["support:A", "support:B"],
                    }
                ]
            },
        },
        {
            "researchGroupId": "research:fixture",
            "recordKind": "mechanic_chain",
            "components": [
                {"componentKey": "skill:MetaCastOnCritPlayer", "role": "trigger_host"},
                {"componentKey": "skill:CometPlayer", "role": "triggered_payload"},
            ],
            "typedPayload": {},
        },
    ]

    # The automatic core is SparkPlayer + the triggered payload CometPlayer; the trigger host
    # is NOT automatic identity anymore.
    assert not run_phase4_deep_review_acceptance._support_packages_cover_core_skill_groups(records)

    records[1]["typedPayload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:CometPlayer",
                "supportKeys": ["support:C", "support:D"],
            }
        ],
    }

    assert run_phase4_deep_review_acceptance._support_packages_cover_core_skill_groups(records)

    # A trigger host declared as Family identity must be packaged (or excepted) like any core skill.
    records[0]["typedPayload"]["familyCoreSkillKeys"] = ["skill:MetaCastOnCritPlayer"]

    assert not run_phase4_deep_review_acceptance._support_packages_cover_core_skill_groups(records)

    records[1]["typedPayload"]["supportCoverageExceptions"] = [
        {
            "skillKey": "skill:MetaCastOnCritPlayer",
            "reason": "not_applicable",
            "detail": "The meta host does not use ordinary supports in this source group.",
        }
    ]

    assert run_phase4_deep_review_acceptance._support_packages_cover_core_skill_groups(records)


def test_group_ascendancy_scope_is_propagated_from_resolved_shell():
    payload = {
        "schema_version": 5,
        "deep_research_records": [
            {
                "research_group_id": "research:fixture",
                "ascendancy_key": None,
                "component_mentions": [
                    {
                        "component_key": "skill:SparkPlayer",
                        "role": "primary_damage",
                    }
                ],
            },
            {
                "research_group_id": "research:fixture",
                "ascendancy_key": None,
                "component_mentions": [
                    {
                        "component_key": "ascendancy:mercenary:gemling_legionnaire",
                        "role": "ascendancy_shell",
                    }
                ],
            },
        ],
    }

    run_phase4_deep_review_acceptance._propagate_group_ascendancy_scope(payload)

    assert {record["ascendancy_key"] for record in payload["deep_research_records"]} == {
        "ascendancy:mercenary:gemling_legionnaire"
    }


def test_group_ascendancy_scope_is_not_guessed_when_shells_conflict():
    payload = {
        "schema_version": 5,
        "deep_research_records": [
            {
                "research_group_id": "research:fixture",
                "ascendancy_key": None,
                "component_mentions": [
                    {
                        "component_key": "ascendancy:mercenary:gemling_legionnaire",
                        "role": "ascendancy_shell",
                    }
                ],
            },
            {
                "research_group_id": "research:fixture",
                "ascendancy_key": None,
                "component_mentions": [
                    {
                        "component_key": "ascendancy:ranger:deadeye",
                        "role": "ascendancy_shell",
                    }
                ],
            },
        ],
    }

    run_phase4_deep_review_acceptance._propagate_group_ascendancy_scope(payload)

    assert [record["ascendancy_key"] for record in payload["deep_research_records"]] == [
        None,
        None,
    ]


def test_name_based_typed_references_canonicalize_only_exact_resolved_components():
    typed_payload, issues = (
        run_phase4_deep_review_acceptance._canonicalize_typed_payload_references(
            typed_payload={
                "supportPackages": [
                    {
                        "skillName": "Arc",
                        "supportNames": ["Dominus' Grasp", "Urgent Totems III"],
                    }
                ],
                "supportCoverageExceptions": [
                    {
                        "skillName": "Spell Totem",
                        "reason": "not_applicable",
                        "detail": "The host does not own ordinary payload supports.",
                    }
                ],
                "ascendancyResponsibilities": [
                    {
                        "componentName": "Advanced Thaumaturgy",
                        "responsibility": "放大技能品质收益。",
                    }
                ],
                "gearResponsibilities": [
                    {
                        "componentName": "Darkness Enthroned",
                        "responsibilityType": "resource_or_spirit",
                        "responsibility": "提供 Spirit 与保留效率。",
                    }
                ],
            },
            component_mentions=[
                {
                    "candidate_name": "Arc",
                    "role": "primary_damage",
                    "component_key": "skill:ArcPlayer",
                    "resolution_status": "resolved",
                },
                {
                    "candidate_name": "Dominus' Grasp",
                    "role": "support_modifier",
                    "component_key": "support:DominusGrasp",
                    "resolution_status": "resolved",
                },
                {
                    "candidate_name": "Spell Totem",
                    "role": "trigger_host",
                    "component_key": "skill:SpellTotemPlayer",
                    "resolution_status": "resolved",
                },
                {
                    "candidate_name": "Urgent Totems III",
                    "role": "support_modifier",
                    "component_key": "support:UrgentTotemsThree",
                    "resolution_status": "resolved",
                },
                {
                    "candidate_name": "Advanced Thaumaturgy",
                    "role": "passive_anchor",
                    "component_key": "notable:AdvancedThaumaturgy",
                    "resolution_status": "resolved",
                },
                {
                    "candidate_name": "Darkness Enthroned",
                    "role": "unique_enabler",
                    "component_key": "unique:DarknessEnthroned",
                    "resolution_status": "resolved",
                },
            ],
        )
    )

    assert issues == []
    assert typed_payload["supportPackages"] == [
        {
            "skillKey": "skill:ArcPlayer",
            "supportKeys": ["support:DominusGrasp", "support:UrgentTotemsThree"],
        }
    ]
    assert typed_payload["supportCoverageExceptions"] == [
        {
            "skillKey": "skill:SpellTotemPlayer",
            "reason": "not_applicable",
            "detail": "The host does not own ordinary payload supports.",
        }
    ]
    assert typed_payload["ascendancyResponsibilities"][0]["componentKey"] == (
        "notable:AdvancedThaumaturgy"
    )
    assert typed_payload["gearResponsibilities"][0]["componentKey"] == ("unique:DarknessEnthroned")


def test_name_based_typed_reference_does_not_guess_ambiguous_component():
    _, issues = run_phase4_deep_review_acceptance._canonicalize_typed_payload_references(
        typed_payload={
            "supportPackages": [
                {
                    "skillName": "Arc",
                    "supportNames": ["Shared Name"],
                }
            ]
        },
        component_mentions=[
            {
                "candidate_name": "Arc",
                "role": "primary_damage",
                "component_key": "skill:ArcPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Shared Name",
                "role": "support_modifier",
                "component_key": "support:First",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Shared Name",
                "role": "support_modifier",
                "component_key": "support:Second",
                "resolution_status": "resolved",
            },
        ],
    )

    assert any("exactly one resolved component" in issue["msg"] for issue in issues)


def test_acceptance_resolves_name_based_support_ownership_before_schema_validation(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="name-based-support-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": None,
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Support",
                "componentKey": None,
                "role": "support_modifier",
                "resolverQuery": "Fixture Support",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["recordKind"] = "skill_package"
    record["typedPayload"] = {
        "supportPackages": [
            {
                "skillName": "Resolved Only",
                "supportNames": ["Fixture Support"],
            }
        ]
    }
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        validation_only=True,
    )

    assert report["acceptedDeepRecordCount"] == 1
    assert report["acceptedDeepRecords"][0]["typedPayload"]["supportPackages"] == [
        {
            "skillKey": "skill:ResolvedOnlyPlayer",
            "supportKeys": ["support:FixtureSupport"],
        }
    ]


def test_source_skill_named_in_rotation_requires_structured_review_before_supports_covered(
    tmp_path,
):
    review_file = _write_review(
        tmp_path,
        filename="source-skill-diagnostic-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["recordKind"] = "rotation"
    record["content"] = "先用 Spark 持续命中，再进入主要输出循环。"
    record["typedPayload"] = {"knowledgeShape": "player_action_sequence"}
    diagnostics = run_phase4_deep_review_acceptance._source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:2",
                    "activeSkills": [{"name": "Spark", "skillId": "SparkPlayer"}],
                    "supports": [
                        {"name": "Pierce", "gemId": "SupportGemPierce"},
                        {"name": "Arcane Tempo", "gemId": "SupportGemArcaneTempo"},
                    ],
                }
            ]
        },
    )
    accepted_records = [
        {
            "researchGroupId": "research:fixture",
            "recordKind": "skill_package",
            "components": [{"componentKey": "skill:ResolvedOnlyPlayer", "role": "primary_damage"}],
            "typedPayload": {
                "supportPackages": [
                    {
                        "skillKey": "skill:ResolvedOnlyPlayer",
                        "supportKeys": ["support:A", "support:B"],
                    }
                ]
            },
        }
    ]

    coverage, advisories = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"supports": "covered"}},
        accepted_records=accepted_records,
        source_evidence_diagnostics=diagnostics,
    )

    assert diagnostics["supportCoverageBlockedByStructuredOmission"] is False
    assert diagnostics["unstructuredSourceSkillMentions"][0]["name"] == "Spark"
    assert coverage["supports"] == "covered"
    assert any("Spark" in item for item in advisories)


def test_source_support_diagnostics_block_evidence_group_with_unpackaged_supports(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="evidence-unpackaged-supports-review.json",
        components=[
            {
                "candidateName": "Flash Grenade",
                "componentKey": "skill:FlashGrenadePlayer",
                "role": "clear_skill",
                "resolverQuery": "Flash Grenade",
            },
            {
                "candidateName": "Explosive Grenade",
                "componentKey": "skill:ExplosiveGrenadePlayer",
                "role": "primary_damage",
                "resolverQuery": "Explosive Grenade",
            },
            {
                "candidateName": "Defy II",
                "componentKey": "support:Metadata/Items/Gem/SupportGemDefyTwo",
                "role": "support_modifier",
                "resolverQuery": "Defy II",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["recordKind"] = "rotation"
    record["content"] = "先投 Flash Grenade 控制，再以 Explosive Grenade 输出。"
    record["typedPayload"] = {"knowledgeShape": "player_action_sequence"}
    review["deepResearchRecords"].append(
        {
            "sampleId": record["sampleId"],
            "researchGroupId": record["researchGroupId"],
            "caseRef": record["caseRef"],
            "safeEvidenceRef": record.get("safeEvidenceRef") or "evidence:test",
            "recordKind": "skill_package",
            "title": "身份包",
            "summary": "身份记录",
            "content": "主技能与清图技能。",
            "components": record["components"],
            "conditions": [],
            "failureConditions": [],
            "typedPayload": {"knowledgeShape": "state_causal_chain"},
        }
    )
    diagnostics = run_phase4_deep_review_acceptance._source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:4",
                    "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                    "supports": [
                        {"name": "Freeze", "gemId": "SupportGemGlaciation"},
                        {"name": "Frost Nexus", "gemId": "SupportGemFrostNexus"},
                        {"name": "Defy II", "gemId": "SupportGemDefyTwo"},
                        {"name": "Cooldown Recovery II", "gemId": "SupportGemIngenuityTwo"},
                        {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"},
                    ],
                }
            ]
        },
    )

    assert diagnostics["supportCoverageBlockedByStructuredOmission"] is True
    assert diagnostics["unstructuredSourceSupportMentionCount"] == 0


def test_source_support_diagnostics_non_core_group_does_not_block(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="evidence-noncore-unpackaged-supports-review.json",
        components=[
            {
                "candidateName": "Flash Grenade",
                "componentKey": "skill:FlashGrenadePlayer",
                "role": "control_skill",
                "resolverQuery": "Flash Grenade",
            },
            {
                "candidateName": "Explosive Grenade",
                "componentKey": "skill:ExplosiveGrenadePlayer",
                "role": "primary_damage",
                "resolverQuery": "Explosive Grenade",
            },
            {
                "candidateName": "Defy II",
                "componentKey": "support:Metadata/Items/Gem/SupportGemDefyTwo",
                "role": "support_modifier",
                "resolverQuery": "Defy II",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["recordKind"] = "rotation"
    record["content"] = "先投 Flash Grenade 控制，再以 Explosive Grenade 输出。"
    record["typedPayload"] = {"knowledgeShape": "player_action_sequence"}
    review["deepResearchRecords"].append(
        {
            "sampleId": record["sampleId"],
            "researchGroupId": record["researchGroupId"],
            "caseRef": record["caseRef"],
            "safeEvidenceRef": record.get("safeEvidenceRef") or "evidence:test",
            "recordKind": "skill_package",
            "title": "身份包",
            "summary": "身份记录",
            "content": "主技能与清图技能。",
            "components": record["components"],
            "conditions": [],
            "failureConditions": [],
            "typedPayload": {"knowledgeShape": "state_causal_chain"},
        }
    )
    diagnostics = run_phase4_deep_review_acceptance._source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:4",
                    "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                    "supports": [
                        {"name": "Freeze", "gemId": "SupportGemGlaciation"},
                        {"name": "Frost Nexus", "gemId": "SupportGemFrostNexus"},
                        {"name": "Defy II", "gemId": "SupportGemDefyTwo"},
                        {"name": "Cooldown Recovery II", "gemId": "SupportGemIngenuityTwo"},
                        {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"},
                    ],
                }
            ]
        },
    )

    assert diagnostics["supportCoverageBlockedByStructuredOmission"] is False
    assert diagnostics["unrepresentedActiveSkillGroupCount"] == 0


def test_source_support_diagnostics_allow_shared_support_in_evidence_group(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="evidence-shared-support-review.json",
        components=[
            {
                "candidateName": "Cluster Grenade",
                "componentKey": "skill:ClusterGrenadePlayer",
                "role": "clear_skill",
                "resolverQuery": "Cluster Grenade",
            },
            {
                "candidateName": "Defy II",
                "componentKey": "support:Metadata/Items/Gem/SupportGemDefyTwo",
                "role": "support_modifier",
                "resolverQuery": "Defy II",
            },
            {
                "candidateName": "Short Fuse I",
                "componentKey": "support:Metadata/Items/Gem/SupportGemExpedite",
                "role": "support_modifier",
                "resolverQuery": "Short Fuse I",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["recordKind"] = "skill_package"
    record["typedPayload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:ClusterGrenadePlayer",
                "supportKeys": [
                    "support:Metadata/Items/Gem/SupportGemDefyTwo",
                    "support:Metadata/Items/Gem/SupportGemExpedite",
                    "support:Metadata/Items/Gems/SupportGemFirePenetrationTwo",
                    "support:Metadata/Items/Gems/SupportGemPrimalArmamentTwo",
                ],
            }
        ]
    }
    diagnostics = run_phase4_deep_review_acceptance._source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:2",
                    "activeSkills": [
                        {"name": "Cluster Grenade", "skillId": "ClusterGrenadePlayer"}
                    ],
                    "supports": [
                        {"name": "Short Fuse I", "gemId": "SupportGemExpedite"},
                        {"name": "Defy II", "gemId": "SupportGemDefyTwo"},
                        {"name": "Fire Penetration II", "gemId": "SupportGemFirePenetrationTwo"},
                        {"name": "Elemental Armament II", "gemId": "SupportGemPrimalArmamentTwo"},
                    ],
                }
            ]
        },
    )

    assert diagnostics["supportCoverageBlockedByStructuredOmission"] is False
    assert diagnostics["unstructuredSourceSupportMentionCount"] == 0


def test_unresolved_jewel_sockets_deferral_requires_explicit_review_declaration():
    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-001"},
        "deepResearchRecords": [
            {
                "title": "Main skill package",
                "recordKind": "skill_package",
                "summary": "no sockets discussed",
                "content": "main skill only",
                "components": [],
            }
        ],
    }
    counts = {
        "allocatedJewelSocketCount": 2,
        "socketedJewelCount": 0,
        "status": "ok",
    }
    deferred = run_phase4_deep_review_acceptance._unresolved_jewel_sockets_deferred(review, counts)

    assert len(deferred) == 1
    assert deferred[0]["reason"] == "unresolved_jewel_sockets"
    assert deferred[0]["candidateKind"] == "research_case"
    assert deferred[0]["sampleId"] == "case:fix-001"


def test_unresolved_jewel_sockets_deferral_skips_declared_or_filled_or_unknown():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    base_review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-002"},
        "deepResearchRecords": [],
    }
    declared = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-003"},
        "deepResearchRecords": [
            {
                "title": "Jewel state",
                "recordKind": "open_question",
                "summary": "socketed Jewel evaluation",
                "content": "jewel sockets are empty by design",
                "components": [],
            }
        ],
    }
    counts = {"allocatedJewelSocketCount": 2, "socketedJewelCount": 0, "status": "ok"}

    assert acceptance._unresolved_jewel_sockets_deferred(declared, counts) == []
    assert (
        acceptance._unresolved_jewel_sockets_deferred(
            base_review, {**counts, "socketedJewelCount": 2}
        )
        == []
    )
    assert (
        acceptance._unresolved_jewel_sockets_deferred(
            base_review, {**counts, "allocatedJewelSocketCount": 0}
        )
        == []
    )
    assert (
        acceptance._unresolved_jewel_sockets_deferred(
            base_review, {**counts, "status": "tree_data_missing"}
        )
        == []
    )
    assert (
        acceptance._unresolved_jewel_sockets_deferred(
            base_review, {**counts, "status": "sockets_absent"}
        )
        == []
    )
    assert acceptance._unresolved_jewel_sockets_deferred(base_review, None) == []


def test_unresolved_jewel_sockets_deferral_uses_tree_socket_count():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-020"},
        "deepResearchRecords": [],
    }
    # Embedded item-socket jewels must not suppress the empty tree-socket declaration.
    counts = {
        "allocatedJewelSocketCount": 2,
        "treeSocketedJewelCount": 0,
        "embeddedJewelCount": 1,
        "socketedJewelCount": 1,
        "status": "ok",
    }
    deferred = acceptance._unresolved_jewel_sockets_deferred(review, counts)
    assert len(deferred) == 1
    assert deferred[0]["reason"] == "unresolved_jewel_sockets"

    filled = {**counts, "treeSocketedJewelCount": 1}
    assert acceptance._unresolved_jewel_sockets_deferred(review, filled) == []


def test_unresolved_jewel_sockets_deferral_ignores_jewel_in_identity_fields():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:jewel-samples-001"},
        "deepResearchRecords": [
            {
                "sampleId": "case:jewel-samples-001",
                "researchGroupId": "research:case:jewel-samples-001",
                "caseRef": "source-hash:jewel-samples-001",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Main skill package",
                "recordKind": "skill_package",
                "summary": "no sockets discussed",
                "content": "main skill only",
                "components": [],
            }
        ],
    }
    counts = {"allocatedJewelSocketCount": 2, "socketedJewelCount": 0, "status": "ok"}
    deferred = acceptance._unresolved_jewel_sockets_deferred(review, counts)

    assert len(deferred) == 1
    assert deferred[0]["reason"] == "unresolved_jewel_sockets"

    declared = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:jewel-samples-001"},
        "deepResearchRecords": [
            {
                "sampleId": "case:jewel-samples-001",
                "researchGroupId": "research:case:jewel-samples-001",
                "caseRef": "source-hash:jewel-samples-001",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Jewel state",
                "recordKind": "open_question",
                "summary": "jewel sockets are empty by design",
                "content": "declared",
                "components": [],
            }
        ],
    }
    assert acceptance._unresolved_jewel_sockets_deferred(declared, counts) == []


def test_unique_gem_diagnostics_labels_lineage_support_identity():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:4",
                "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                "supports": [
                    {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"},
                    {"name": "Freeze", "gemId": "SupportGemGlaciation"},
                ],
            }
        ]
    }
    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-010"},
        "deepResearchRecords": [
            {
                "sampleId": "case:fix-010",
                "researchGroupId": "research:case:fix-010",
                "caseRef": "source-hash:fix-010",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Flash CC rotation",
                "recordKind": "rotation",
                "summary": "Bhatair's Vengeance support pair",
                "content": "Flash Grenade controls with Freeze",
                "components": [
                    {
                        "candidateName": "Flash Grenade",
                        "componentKey": "skill:FlashGrenadePlayer",
                        "role": "control_skill",
                    }
                ],
            }
        ],
    }
    diagnostics = acceptance._unique_gem_diagnostics(review, manifest)

    assert diagnostics["available"] is True
    assert "Bhatair's Vengeance" in diagnostics["uniqueGemCandidates"]
    assert "Bhatair's Vengeance" in diagnostics["unlabeledUniqueGemNames"]


def test_unique_gem_diagnostics_exempts_open_question_but_not_enabler_role():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:4",
                "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                "supports": [
                    {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"}
                ],
            }
        ]
    }
    open_question = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-011"},
        "deepResearchRecords": [
            {
                "sampleId": "case:fix-011",
                "researchGroupId": "research:case:fix-011",
                "caseRef": "source-hash:fix-011",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Bhatair lineage open",
                "recordKind": "open_question",
                "summary": "Bhatair's Vengeance lineage support mechanism unverified",
                "content": "mechanism details pending",
                "components": [],
            }
        ],
    }
    diagnostics = acceptance._unique_gem_diagnostics(open_question, manifest)
    assert "Bhatair's Vengeance" in diagnostics["uniqueGemCandidates"]
    assert diagnostics["unlabeledUniqueGemNames"] == []

    enabler_review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-012"},
        "deepResearchRecords": [
            {
                "sampleId": "case:fix-012",
                "researchGroupId": "research:case:fix-012",
                "caseRef": "source-hash:fix-012",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Unique support labeled",
                "recordKind": "skill_package",
                "summary": "labeled",
                "content": "pair",
                "components": [
                    {
                        "candidateName": "Bhatair's Vengeance",
                        "componentKey": "support:Metadata/Items/Gems/SupportGemBhatairsVengeance",
                        "role": "unique_enabler",
                    }
                ],
            }
        ],
    }
    diagnostics = acceptance._unique_gem_diagnostics(enabler_review, manifest)
    assert diagnostics["unlabeledUniqueGemNames"] == ["Bhatair's Vengeance"]


def test_unique_gem_diagnostics_handles_missing_manifest():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    diagnostics = acceptance._unique_gem_diagnostics({"safeArtifactOnly": True}, None)
    assert diagnostics["available"] is False
    assert diagnostics["uniqueGemCandidates"] == []
    assert diagnostics["unlabeledUniqueGemNames"] == []


def test_unique_gem_diagnostics_accepts_prose_lineage_label_with_support_role():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:4",
                "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                "supports": [
                    {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"}
                ],
            }
        ]
    }
    prose_labeled = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-013"},
        "deepResearchRecords": [
            {
                "sampleId": "case:fix-013",
                "researchGroupId": "research:case:fix-013",
                "caseRef": "source-hash:fix-013",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Flash CC package",
                "recordKind": "skill_package",
                "summary": "Bhatair's Vengeance is a lineage support gem with fixed affixes",
                "content": "pair with Flash Grenade",
                "components": [
                    {
                        "candidateName": "Flash Grenade",
                        "componentKey": "skill:FlashGrenadePlayer",
                        "role": "control_skill",
                    },
                    {
                        "candidateName": "Bhatair's Vengeance",
                        "componentKey": "support:Metadata/Items/Gems/SupportGemBhatairsVengeance",
                        "role": "support_modifier",
                    },
                ],
            }
        ],
    }
    diagnostics = acceptance._unique_gem_diagnostics(prose_labeled, manifest)
    assert "Bhatair's Vengeance" in diagnostics["uniqueGemCandidates"]
    assert diagnostics["unlabeledUniqueGemNames"] == []


def test_unique_gem_diagnostics_gem_name_with_unique_word_does_not_self_label():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    assert (
        acceptance._mentions_unique_identity(
            "Bhatair's Vengeance is a lineage support gem with fixed affixes",
            "Bhatair's Vengeance",
        )
        is True
    )
    assert (
        acceptance._mentions_unique_identity(
            "uses Unique Breach Lightning Bolt as the main skill", "Unique Breach Lightning Bolt"
        )
        is False
    )
    assert (
        acceptance._mentions_unique_identity("pair with Flash Grenade", "Bhatair's Vengeance")
        is False
    )
    assert acceptance._mentions_unique_identity("", "Bhatair's Vengeance") is False


def test_source_support_diagnostics_use_resolved_physical_type_not_functional_role(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="physical-support-diagnostic-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Support",
                "componentKey": "support:FixtureSupport",
                "role": "generator",
                "resolverQuery": "Fixture Support",
            },
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    diagnostics = run_phase4_deep_review_acceptance._source_skill_evidence_diagnostics(
        review=review,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:1",
                    "activeSkills": [{"name": "Resolved Only", "skillId": "ResolvedOnlyPlayer"}],
                    "supports": [{"name": "Fixture Support", "gemId": "FixtureSupport"}],
                }
            ]
        },
    )

    assert diagnostics["unstructuredSourceSupportMentionCount"] == 0
    assert diagnostics["unstructuredSourceSkillMentionCount"] == 0


def test_single_active_source_group_defers_static_unsupported_support_claim(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:source-support-compatibility",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    skill_key = "skill:IceStrikePlayer"
    support_key = "support:Metadata/Items/Gems/SupportGemProfusionTwo"
    support_contract_key = "skill:SupportChargeProfusionPlayerTwo"
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:source-support-compatibility",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(skill_key, "active_skill", "Ice Strike", (source.source_id,)),
                pg.GraphNode(
                    support_key,
                    "support_gem",
                    "Charge Profusion II",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    support_contract_key,
                    "active_skill",
                    "Charge Profusion II contract",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    "skill_type:attack",
                    "skill_type",
                    "Attack",
                    (source.source_id,),
                ),
            ),
            edges=(
                pg.GraphEdge(
                    "grants_skill",
                    support_key,
                    support_contract_key,
                    (source.source_id,),
                ),
                pg.GraphEdge(
                    "has_type",
                    skill_key,
                    "skill_type:attack",
                    (source.source_id,),
                ),
            ),
            aliases=(
                pg.GraphAlias("Ice Strike", skill_key, (source.source_id,)),
                pg.GraphAlias("Charge Profusion II", support_key, (source.source_id,)),
            ),
            requirement_facts=(
                pg.RequirementFact(
                    component_key=support_contract_key,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["GeneratesCharges"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                    },
                    source_refs=(source.source_id,),
                ),
            ),
        )
    )
    review_file = _write_review(
        tmp_path,
        filename="unsupported-source-support-review.json",
        components=[
            {
                "candidateName": "Ice Strike",
                "componentKey": skill_key,
                "role": "generator",
                "resolverQuery": "Ice Strike",
            },
            {
                "candidateName": "Charge Profusion II",
                "componentKey": support_key,
                "role": "support_modifier",
                "resolverQuery": "Charge Profusion II",
            },
        ],
        include_deep_record=True,
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=graph_service,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:1",
                    "activeSkills": [{"name": "Ice Strike", "skillId": "IceStrikePlayer"}],
                    "supports": [
                        {
                            "name": "Charge Profusion II",
                            "gemId": "Metadata/Items/Gems/SupportGemProfusionTwo",
                        }
                    ],
                }
            ]
        },
        validation_only=True,
    )

    assert report["acceptedDeepRecordCount"] == 0
    assert report["deferredReasonCounts"]["unsupported_source_skill_support_pair"] == 1
    diagnostics = report["sourceEvidenceDiagnostics"]
    assert diagnostics["sourceSupportCompatibilityCheckedPairCount"] == 1
    assert diagnostics["unsupportedSourceSupportPairCount"] == 1
    pair = diagnostics["unsupportedSourceSupportPairs"][0]
    assert pair["skillKey"] == skill_key
    assert pair["supportKey"] == support_key
    assert pair["excludedReason"] == "required_types_not_matched"


def test_single_active_source_group_uses_support_type_fixed_point_and_contract_grant():
    source = pg.GraphSource(
        source_id="fixture:source-support-group-fixed-point",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    skill_key = "skill:FixtureAttackPlayer"
    type_grant_key = "support:FixtureTypeGrant"
    dependent_key = "support:FixtureDependent"
    payload_support_key = "support:FixturePayloadSupport"
    type_grant_contract = "skill:FixtureTypeGrantContract"
    dependent_contract = "skill:FixtureDependentContract"
    payload_support_contract = "skill:FixturePayloadSupportContract"
    payload_skill_key = "skill:FixtureTriggeredPayload"
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:source-support-group-fixed-point",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(skill_key, "active_skill", "Fixture Attack", (source.source_id,)),
                pg.GraphNode(
                    type_grant_key, "support_gem", "Fixture Type Grant", (source.source_id,)
                ),
                pg.GraphNode(
                    dependent_key, "support_gem", "Fixture Dependent", (source.source_id,)
                ),
                pg.GraphNode(
                    payload_support_key,
                    "support_gem",
                    "Fixture Payload Support",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    type_grant_contract,
                    "active_skill",
                    "Fixture Type Grant contract",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    dependent_contract,
                    "active_skill",
                    "Fixture Dependent contract",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    payload_support_contract,
                    "active_skill",
                    "Fixture Payload Support contract",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    payload_skill_key,
                    "active_skill",
                    "Fixture Triggered Payload",
                    (source.source_id,),
                ),
                pg.GraphNode("skill_type:attack", "skill_type", "Attack", (source.source_id,)),
                pg.GraphNode("skill_type:damage", "skill_type", "Damage", (source.source_id,)),
            ),
            edges=(
                pg.GraphEdge("has_type", skill_key, "skill_type:attack", (source.source_id,)),
                pg.GraphEdge("has_type", skill_key, "skill_type:damage", (source.source_id,)),
                pg.GraphEdge(
                    "grants_skill", type_grant_key, type_grant_contract, (source.source_id,)
                ),
                pg.GraphEdge(
                    "grants_skill", dependent_key, dependent_contract, (source.source_id,)
                ),
                pg.GraphEdge(
                    "grants_skill",
                    payload_support_key,
                    payload_support_contract,
                    (source.source_id,),
                ),
                pg.GraphEdge(
                    "grants_skill", payload_support_key, payload_skill_key, (source.source_id,)
                ),
            ),
            aliases=(
                pg.GraphAlias("Fixture Attack", skill_key, (source.source_id,)),
                pg.GraphAlias("Fixture Type Grant", type_grant_key, (source.source_id,)),
                pg.GraphAlias("Fixture Dependent", dependent_key, (source.source_id,)),
                pg.GraphAlias("Fixture Payload Support", payload_support_key, (source.source_id,)),
            ),
            requirement_facts=(
                pg.RequirementFact(
                    component_key=type_grant_contract,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["Attack"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                        "added_types": ["GeneratesCharges"],
                    },
                    source_refs=(source.source_id,),
                ),
                pg.RequirementFact(
                    component_key=dependent_contract,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["GeneratesCharges"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                        "added_types": [],
                    },
                    source_refs=(source.source_id,),
                ),
                pg.RequirementFact(
                    component_key=payload_support_contract,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["Attack", "Damage", "AND"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                        "added_types": ["Triggered"],
                    },
                    source_refs=(source.source_id,),
                ),
            ),
        )
    )
    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:1",
                "activeSkills": [{"name": "Fixture Attack", "skillId": "FixtureAttackPlayer"}],
                "supports": [
                    {"name": "Fixture Dependent"},
                    {"name": "Fixture Payload Support"},
                    {"name": "Fixture Type Grant"},
                ],
            }
        ]
    }

    resolutions = run_phase4_deep_review_acceptance._source_skill_id_resolutions(
        graph_service=graph_service,
        source_skill_manifest=manifest,
    )
    diagnostics = run_phase4_deep_review_acceptance._source_support_compatibility_diagnostics(
        graph_service=graph_service,
        source_skill_manifest=manifest,
        source_skill_resolutions=resolutions,
    )

    assert diagnostics["sourceSupportCompatibilityCheckedPairCount"] == 3
    assert diagnostics["unsupportedSourceSupportPairCount"] == 0
    assert diagnostics["unverifiedSourceSupportPairCount"] == 0
    assert diagnostics["sourceSupportCompatibilityBlocked"] is False


def test_source_group_accepts_support_known_on_sibling_endpoint_of_same_active_gem():
    source = pg.GraphSource(
        source_id="fixture:source-support-sibling-endpoint",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    gem_key = "gem:FixtureCompositeSkill"
    setup_skill_key = "skill:FixtureCompositeSetup"
    payload_skill_key = "skill:FixtureCompositePayload"
    support_key = "support:FixturePayloadSupport"
    support_contract_key = "skill:FixturePayloadSupportContract"
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:source-support-sibling-endpoint",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(gem_key, "skill_gem", "Fixture Composite", (source.source_id,)),
                pg.GraphNode(
                    setup_skill_key,
                    "active_skill",
                    "Fixture Composite Setup",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    payload_skill_key,
                    "active_skill",
                    "Fixture Composite Payload",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    support_key,
                    "support_gem",
                    "Fixture Payload Support",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    support_contract_key,
                    "active_skill",
                    "Fixture Payload Support contract",
                    (source.source_id,),
                ),
                pg.GraphNode("skill_type:buff", "skill_type", "Buff", (source.source_id,)),
                pg.GraphNode("skill_type:attack", "skill_type", "Attack", (source.source_id,)),
            ),
            edges=(
                pg.GraphEdge("grants_skill", gem_key, setup_skill_key, (source.source_id,)),
                pg.GraphEdge("grants_skill", gem_key, payload_skill_key, (source.source_id,)),
                pg.GraphEdge("granted_by", setup_skill_key, gem_key, (source.source_id,)),
                pg.GraphEdge("granted_by", payload_skill_key, gem_key, (source.source_id,)),
                pg.GraphEdge("has_type", setup_skill_key, "skill_type:buff", (source.source_id,)),
                pg.GraphEdge(
                    "has_type", payload_skill_key, "skill_type:attack", (source.source_id,)
                ),
                pg.GraphEdge(
                    "grants_skill", support_key, support_contract_key, (source.source_id,)
                ),
            ),
            aliases=(
                pg.GraphAlias("Fixture Composite", setup_skill_key, (source.source_id,)),
                pg.GraphAlias("Fixture Payload Support", support_key, (source.source_id,)),
            ),
            requirement_facts=(
                pg.RequirementFact(
                    component_key=support_contract_key,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["Attack"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                    },
                    source_refs=(source.source_id,),
                ),
            ),
        )
    )
    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:1",
                "activeSkills": [{"name": "Fixture Composite", "skillId": "FixtureCompositeSetup"}],
                "supports": [{"name": "Fixture Payload Support"}],
            }
        ]
    }

    resolutions = run_phase4_deep_review_acceptance._source_skill_id_resolutions(
        graph_service=graph_service,
        source_skill_manifest=manifest,
    )
    diagnostics = run_phase4_deep_review_acceptance._source_support_compatibility_diagnostics(
        graph_service=graph_service,
        source_skill_manifest=manifest,
        source_skill_resolutions=resolutions,
    )

    assert diagnostics["sourceSupportCompatibilityCheckedPairCount"] == 1
    assert diagnostics["unsupportedSourceSupportPairCount"] == 0
    assert diagnostics["unverifiedSourceSupportPairCount"] == 0
    assert diagnostics["sourceSupportCompatibilityBlocked"] is False


def test_unrelated_unsupported_source_pair_does_not_erase_confirmed_support_coverage():
    coverage, advisories = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"supports": "covered"}},
        accepted_records=[
            {
                "researchGroupId": "research:fixture",
                "recordKind": "skill_package",
                "components": [
                    {"componentKey": "skill:StormWavePlayer", "role": "primary_damage"},
                    {
                        "componentKey": "support:Metadata/Items/Gems/SupportGemLightningInfusion",
                        "role": "support_modifier",
                    },
                    {
                        "componentKey": "support:Metadata/Items/Gems/SupportGemRageThree",
                        "role": "support_modifier",
                    },
                ],
                "typedPayload": {
                    "supportPackages": [
                        {
                            "skillKey": "skill:StormWavePlayer",
                            "supportKeys": [
                                "support:Metadata/Items/Gems/SupportGemLightningInfusion",
                                "support:Metadata/Items/Gems/SupportGemRageThree",
                            ],
                        }
                    ]
                },
            }
        ],
        source_evidence_diagnostics={
            "sourceSupportCompatibilityBlocked": True,
            "unsupportedSourceSupportPairs": [{"skillName": "Wind Dancer", "supportName": "Maim"}],
        },
    )

    assert coverage["supports"] == "covered"
    assert not any("caseCoverage.supports declared covered" in item for item in advisories)


def test_structured_support_packages_reject_cross_assigned_multi_active_supports():
    source = pg.GraphSource(
        source_id="fixture:structured-support-ownership",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    spell_skill = "skill:FixtureSpellPlayer"
    totem_skill = "skill:FixtureTotemPlayer"
    spell_support = "support:FixtureSpellSupport"
    totem_support = "support:FixtureTotemSupport"
    spell_contract = "skill:FixtureSpellSupportContract"
    totem_contract = "skill:FixtureTotemSupportContract"
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:structured-support-ownership",
            created_at=datetime(2026, 7, 18, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(spell_skill, "active_skill", "Fixture Spell", (source.source_id,)),
                pg.GraphNode(totem_skill, "active_skill", "Fixture Totem", (source.source_id,)),
                pg.GraphNode(
                    spell_support, "support_gem", "Fixture Spell Support", (source.source_id,)
                ),
                pg.GraphNode(
                    totem_support, "support_gem", "Fixture Totem Support", (source.source_id,)
                ),
                pg.GraphNode(
                    spell_contract,
                    "active_skill",
                    "Fixture Spell Support contract",
                    (source.source_id,),
                ),
                pg.GraphNode(
                    totem_contract,
                    "active_skill",
                    "Fixture Totem Support contract",
                    (source.source_id,),
                ),
                pg.GraphNode("skill_type:spell", "skill_type", "Spell", (source.source_id,)),
                pg.GraphNode("skill_type:totem", "skill_type", "Totem", (source.source_id,)),
            ),
            edges=(
                pg.GraphEdge("has_type", spell_skill, "skill_type:spell", (source.source_id,)),
                pg.GraphEdge("has_type", totem_skill, "skill_type:totem", (source.source_id,)),
                pg.GraphEdge("grants_skill", spell_support, spell_contract, (source.source_id,)),
                pg.GraphEdge("grants_skill", totem_support, totem_contract, (source.source_id,)),
            ),
            aliases=(),
            requirement_facts=(
                pg.RequirementFact(
                    component_key=spell_contract,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["Spell"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                    },
                    source_refs=(source.source_id,),
                ),
                pg.RequirementFact(
                    component_key=totem_contract,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["Totem"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                    },
                    source_refs=(source.source_id,),
                ),
            ),
        )
    )
    record = {
        "component_keys": [spell_skill, totem_skill, spell_support, totem_support],
        "component_mentions": [],
        "typed_payload": {
            "supportPackages": [
                {"skillKey": spell_skill, "supportKeys": [spell_support, totem_support]},
                {"skillKey": totem_skill, "supportKeys": [spell_support, totem_support]},
            ]
        },
    }
    summary = {
        "titleZh": "复合技能辅助归属",
        "recordKind": "skill_package",
        "sampleId": "fixture_sample_001",
        "componentKeys": record["component_keys"],
    }

    kept_payload, kept_summaries, deferred = (
        run_phase4_deep_review_acceptance._filter_records_with_unsupported_structured_support_packages(
            graph_service=graph_service,
            deep_payload={"schema_version": 5, "deep_research_records": [record]},
            accepted_records=[summary],
        )
    )

    assert kept_payload["deep_research_records"] == []
    assert kept_summaries == []
    assert deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert {(item["skillKey"], item["supportKey"]) for item in deferred[0]["unsupportedPairs"]} == {
        (spell_skill, totem_support),
        (totem_skill, spell_support),
    }

    record["typed_payload"]["supportPackages"] = [
        {"skillKey": spell_skill, "supportKeys": [spell_support]},
        {"skillKey": totem_skill, "supportKeys": [totem_support]},
    ]
    corrected_payload, corrected_summaries, corrected_deferred = (
        run_phase4_deep_review_acceptance._filter_records_with_unsupported_structured_support_packages(
            graph_service=graph_service,
            deep_payload={"schema_version": 5, "deep_research_records": [record]},
            accepted_records=[summary],
        )
    )

    assert corrected_payload["deep_research_records"] == [record]
    assert corrected_summaries == [summary]
    assert corrected_deferred == []


def test_source_support_name_match_does_not_collapse_distinct_stable_skill_keys():
    canonical_skill = "skill:GlacialBoltPlayer"
    source_implementation = "skill:GlacialBoltAmmoPlayer"
    support_key = "support:FixtureColdMastery"
    record = {
        "title": "Glacial Bolt package",
        "summary": "Glacial Bolt uses Cold Mastery.",
        "content": "Glacial Bolt uses Cold Mastery for its cold package.",
        "conditions": [],
        "failure_conditions": [],
        "component_keys": [canonical_skill, support_key],
        "component_mentions": [
            {
                "candidate_name": "Glacial Bolt",
                "component_key": canonical_skill,
                "role": "primary_damage",
            }
        ],
    }
    summary = {
        "titleZh": "Glacial Bolt package",
        "recordKind": "skill_package",
        "sampleId": "fixture_sample_001",
        "componentKeys": record["component_keys"],
    }

    kept_payload, kept_summaries, deferred = (
        run_phase4_deep_review_acceptance._filter_records_with_unsupported_source_supports(
            deep_payload={"schema_version": 5, "deep_research_records": [record]},
            accepted_records=[summary],
            diagnostics={
                "unsupportedSourceSupportPairs": [
                    {
                        "skillName": "Glacial Bolt",
                        "skillKey": source_implementation,
                        "supportName": "Cold Mastery",
                        "supportKey": support_key,
                    }
                ]
            },
        )
    )

    assert kept_payload["deep_research_records"] == [record]
    assert kept_summaries == [summary]
    assert deferred == []
    _, advisories = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {}},
        accepted_records=[],
        source_evidence_diagnostics={
            "unsupportedSourceSupportPairs": [
                {
                    "skillName": "Glacial Bolt",
                    "skillKey": source_implementation,
                    "supportName": "Cold Mastery",
                    "supportKey": support_key,
                }
            ]
        },
    )
    support_advisory = next(item for item in advisories if "Static support contracts" in item)
    assert canonical_skill not in support_advisory
    assert source_implementation in support_advisory
    assert support_key in support_advisory


def test_bounded_diagnostic_caveats_never_trip_copy_safety_long_prose():
    pairs = [
        {
            "skillName": f"Skill {index}",
            "skillKey": f"skill:Metadata/Items/Gems/ActiveSkill{index}",
            "supportName": f"Support {index}",
            "supportKey": f"support:Metadata/Items/Gems/SupportGem{index}",
        }
        for index in range(60)
    ]
    _, advisories = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {}},
        accepted_records=[],
        source_evidence_diagnostics={"unsupportedSourceSupportPairs": pairs},
    )
    support_advisory = next(item for item in advisories if "Static support contracts" in item)
    assert len(support_advisory) <= 1200
    assert "+60 entries total" in support_advisory


def test_origin_family_requires_confirmed_identity_record():
    rotation = {
        "record_kind": "rotation",
        "research_group_id": "research:fixture",
        "ascendancy_key": "ascendancy:monk:martial_artist",
        "source_case_refs": ["source-hash:fixture"],
        "component_mentions": [
            {"role": "primary_damage", "component_key": "skill:WyvernDevourPlayer"}
        ],
    }

    without_identity = run_phase4_deep_review_acceptance._origin_family_by_case_ref(
        {"deep_research_records": [rotation]}
    )
    with_identity = run_phase4_deep_review_acceptance._origin_family_by_case_ref(
        {
            "deep_research_records": [
                rotation,
                {**rotation, "record_kind": "skill_package"},
            ]
        }
    )

    assert without_identity == {}
    assert with_identity == {"source-hash:fixture": "bf-9bad44ec97043db69f4d"}


def test_single_active_source_group_defers_exact_unstructured_unsupported_claim(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:unstructured-source-support-compatibility",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    skill_key = "skill:IceStrikePlayer"
    support_key = "support:Metadata/Items/Gems/SupportGemProfusionTwo"
    support_contract_key = "skill:SupportChargeProfusionPlayerTwo"
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:unstructured-source-support-compatibility",
            created_at=datetime(2026, 7, 17, tzinfo=UTC),
            sources=(source,),
            nodes=(
                pg.GraphNode(skill_key, "active_skill", "Ice Strike", (source.source_id,)),
                pg.GraphNode(
                    support_key, "support_gem", "Charge Profusion II", (source.source_id,)
                ),
                pg.GraphNode(
                    support_contract_key,
                    "active_skill",
                    "Charge Profusion II contract",
                    (source.source_id,),
                ),
                pg.GraphNode("skill_type:attack", "skill_type", "Attack", (source.source_id,)),
            ),
            edges=(
                pg.GraphEdge(
                    "grants_skill", support_key, support_contract_key, (source.source_id,)
                ),
                pg.GraphEdge("has_type", skill_key, "skill_type:attack", (source.source_id,)),
            ),
            aliases=(
                pg.GraphAlias("Ice Strike", skill_key, (source.source_id,)),
                pg.GraphAlias("Charge Profusion II", support_key, (source.source_id,)),
            ),
            requirement_facts=(
                pg.RequirementFact(
                    component_key=support_contract_key,
                    level_or_stage="support_contract",
                    requirements={
                        "allowed_types_expr": ["GeneratesCharges"],
                        "excluded_types_expr": [],
                        "supports_gems_only": False,
                    },
                    source_refs=(source.source_id,),
                ),
            ),
        )
    )
    review_file = _write_review(
        tmp_path,
        filename="unstructured-unsupported-source-support-review.json",
        components=[
            {
                "candidateName": "Ice Strike",
                "componentKey": skill_key,
                "role": "generator",
                "resolverQuery": "Ice Strike",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    record = review["deepResearchRecords"][0]
    record["summary"] = "Ice Strike 携带 Charge Profusion II 生成充能。"
    record["content"] = "Ice Strike + Charge Profusion II 提供主要充能来源。"
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=graph_service,
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:1",
                    "activeSkills": [{"name": "Ice Strike", "skillId": "IceStrikePlayer"}],
                    "supports": [
                        {
                            "name": "Charge Profusion II",
                            "gemId": "Metadata/Items/Gems/SupportGemProfusionTwo",
                        }
                    ],
                }
            ]
        },
        validation_only=True,
    )

    assert report["acceptedDeepRecordCount"] == 0
    deferred = report["deferredCandidates"][0]
    assert deferred["reason"] == "unsupported_source_skill_support_pair"
    assert deferred["unsupportedPairs"][0]["matchedBy"] == "exact_same_statement"


def test_deep_record_id_attachment_uses_ordered_write_mapping():
    accepted = [
        {"titleZh": "先写入的记录", "researchGroupId": "research:fixture"},
        {"titleZh": "后写入的记录", "researchGroupId": "research:fixture"},
    ]
    deep_result = {
        "recordIds": ["drr-a", "drr-z"],
        "recordWrites": [
            {
                "recordId": "drr-z",
                "title": "先写入的记录",
                "researchGroupId": "research:fixture",
            },
            {
                "recordId": "drr-a",
                "title": "后写入的记录",
                "researchGroupId": "research:fixture",
            },
        ],
    }

    attached = run_phase4_deep_review_acceptance._attach_deep_record_ids(accepted, deep_result)

    assert [item["recordId"] for item in attached] == ["drr-z", "drr-a"]


def test_defensive_unique_alone_does_not_satisfy_gear_coverage():
    coverage, _ = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"gearRoles": "covered"}},
        accepted_records=[
            {
                "researchGroupId": "research:fixture",
                "recordKind": "defense_engine",
                "components": [
                    {"componentKey": "unique:pob:defensive_boots", "role": "unique_enabler"}
                ],
                "typedPayload": {},
            }
        ],
    )

    assert coverage["gearRoles"] == "evidence_missing"


def test_identity_gear_responsibility_satisfies_gear_coverage():
    coverage, _ = run_phase4_deep_review_acceptance._evaluate_case_coverage(
        review={"caseCoverage": {"gearRoles": "covered"}},
        accepted_records=[
            {
                "researchGroupId": "research:fixture",
                "recordKind": "gear_synergy",
                "components": [
                    {"componentKey": "unique:pob:identity_item", "role": "unique_enabler"}
                ],
                "typedPayload": {
                    "gearResponsibilities": [
                        {
                            "componentKey": "unique:pob:identity_item",
                            "responsibilityType": "identity_enabler",
                            "responsibility": "Changes how the build converts its curse count.",
                        }
                    ]
                },
            }
        ],
    )

    assert coverage["gearRoles"] == "covered"


def test_declared_missing_gear_context_defers_mechanic_chain_only():
    deep_payload = {
        "schema_version": 5,
        "deep_research_records": [
            {"record_kind": "skill_package"},
            {"record_kind": "mechanic_chain"},
            {"record_kind": "resource_engine"},
        ],
    }
    summaries = [
        {
            "titleZh": "Skill",
            "recordKind": "skill_package",
            "sampleId": "fixture",
            "componentKeys": ["skill:Fixture"],
        },
        {
            "titleZh": "Mechanic",
            "recordKind": "mechanic_chain",
            "sampleId": "fixture",
            "componentKeys": ["skill:Fixture", "unique:Fixture"],
        },
        {
            "titleZh": "Resource",
            "recordKind": "resource_engine",
            "sampleId": "fixture",
            "componentKeys": ["skill:Fixture"],
        },
    ]

    filtered, kept, deferred = (
        run_phase4_deep_review_acceptance._filter_mechanic_records_without_gear_context(
            review={"caseCoverage": {"gearRoles": "evidence_missing"}},
            deep_payload=deep_payload,
            accepted_records=summaries,
            case_coverage={"gearRoles": "evidence_missing"},
        )
    )

    assert [row["record_kind"] for row in filtered["deep_research_records"]] == [
        "skill_package",
        "resource_engine",
    ]
    assert [row["recordKind"] for row in kept] == ["skill_package", "resource_engine"]
    assert deferred[0]["reason"] == "insufficient_gear_context"


def test_pattern_cannot_bypass_a_deferred_mechanic_record(tmp_path):
    components = [
        {
            "candidateName": "Resolved Only",
            "componentKey": "skill:ResolvedOnlyPlayer",
            "role": "primary_damage",
            "resolverQuery": "Resolved Only",
        },
        {
            "candidateName": "Fixture Support",
            "componentKey": "support:FixtureSupport",
            "role": "support_modifier",
            "resolverQuery": "Fixture Support",
        },
    ]
    review_file = _write_review(
        tmp_path,
        filename="deferred-mechanic-pattern-review.json",
        components=components,
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["caseCoverage"] = {
        "supports": "evidence_missing",
        "rotation": "evidence_missing",
        "passiveAscendancy": "not_applicable",
        "gearRoles": "evidence_missing",
        "resourceDefense": "evidence_missing",
    }
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedDeepRecordCount"] == 0
    assert report["acceptedPatternCount"] == 0
    assert report["deferredReasonCounts"] == {
        "insufficient_gear_context": 1,
        "supporting_record_deferred": 1,
    }
    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        assert con.execute("SELECT count(*) FROM research_build_patterns").fetchone()[0] == 0
    finally:
        con.close()


def test_deep_review_acceptance_advises_rotation_shape_mismatch(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="rotation-shape-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["recordKind"] = "rotation"
    review["deepResearchRecords"][0]["typedPayload"] = {"knowledgeShape": "state_causal_chain"}
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["recordKindCounts"] == {"rotation": 1}
    assert len(report["recordKindAdvisories"]) == 1
    assert "player_action_sequence" in report["recordKindAdvisories"][0]


def test_deep_review_acceptance_rejects_malformed_candidate(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="missing-candidate-text-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["candidateReviews"][0].pop("title")
    review["candidateReviews"][0].pop("summary")
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    # A schema-violating candidate must fail the whole case closed (mirroring
    # the validate-only gate) instead of being silently dropped into a partial
    # payload.
    assert report["status"] == "rejected"
    assert report["acceptanceMode"] == "blocked"
    assert report["acceptedDeepRecordCount"] == 0
    assert report["acceptedPatternCount"] == 0
    assert report["deferredReasonCounts"] == {"invalid_schema": 1}
    assert report["durableWritePerformed"] is False


def test_deep_review_acceptance_structural_issues_return_issues_not_crash(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="empty-verification-tasks-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["candidateReviews"][0]["verificationTasks"] = []
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    assert report["acceptedPatternCount"] == 0
    assert report["deferredReasonCounts"] == {"invalid_schema": 1}
    issues = (report["deferredCandidates"][0] or {}).get("validationIssues") or []
    assert any(
        issue.get("loc") == ["candidateReviews", 0, "verificationTasks"]
        and "non-empty list" in str(issue.get("msg") or "")
        for issue in issues
    )


def test_deep_review_acceptance_structural_issues_validate_only_path(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="missing-pattern-type-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["candidateReviews"][0].pop("patternType")
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        validation_only=True,
    )

    assert report["status"] == "rejected"
    issues = (report["deferredCandidates"][0] or {}).get("validationIssues") or []
    assert any(
        issue.get("loc") == ["candidateReviews", 0, "patternType"]
        and "missing required field" in str(issue.get("msg") or "")
        for issue in issues
    )


def test_deep_review_acceptance_structural_issues_container_type_errors(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="container-type-errors-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["candidateReviews"] = {"not": "a list"}
    review["mechanicAudit"] = {"not": "a list"}
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    all_issues = [
        issue
        for deferred in report["deferredCandidates"]
        for issue in (deferred.get("validationIssues") or [])
    ]
    assert any(issue.get("loc") == ["candidateReviews"] for issue in all_issues)
    assert any(issue.get("loc") == ["mechanicAudit"] for issue in all_issues)


def test_deep_review_acceptance_structural_issues_record_missing_content(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="record-missing-content-review.json",
        components=[],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0].pop("content")
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    issues = (report["deferredCandidates"][0] or {}).get("validationIssues") or []
    assert any(
        issue.get("loc") == ["deepResearchRecords", 0, "content"]
        and "missing required field" in str(issue.get("msg") or "")
        for issue in issues
    )


def test_deep_review_acceptance_structural_issues_record_bad_safe_evidence_type(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="record-bad-safe-evidence-review.json",
        components=[],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["safeEvidenceRefs"] = "evidence:fix"
    review_file.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    issues = (report["deferredCandidates"][0] or {}).get("validationIssues") or []
    assert any(
        issue.get("loc") == ["deepResearchRecords", 0, "safeEvidenceRefs"]
        and "must be a list" in str(issue.get("msg") or "")
        for issue in issues
    )


def test_structural_preflight_field_rules_match_normalizer_required_fields():
    acceptance = run_phase4_deep_review_acceptance
    assert set(acceptance._STRUCTURAL_CANDIDATE_REQUIRED) == {
        "sampleId",
        "caseRef",
        "patternType",
        "plannerHint",
        "verificationGate",
    }
    assert set(acceptance._STRUCTURAL_CANDIDATE_NONEMPTY_LISTS) == {
        "axes",
        "verificationTasks",
    }
    assert set(acceptance._STRUCTURAL_RECORD_REQUIRED) == {
        "sampleId",
        "researchGroupId",
        "caseRef",
        "recordKind",
        "title",
        "summary",
        "content",
    }


def test_kind_identity_roles_fallback_matches_record_kind_superset():
    from server.knowledge import research_identity, research_models

    roles = research_identity.kind_identity_roles()
    assert set(roles["fallback"]["kindsWithoutExplicitRoles"]) == (
        research_models.DEEP_RESEARCH_RECORD_KINDS - set(research_identity._KIND_IDENTITY_ROLES)
    )
    assert set(roles["explicitRoles"]) == set(research_identity._KIND_IDENTITY_ROLES)


def test_deep_review_acceptance_resolves_component_when_worker_omits_stable_key(tmp_path):
    component = {
        "candidateName": "Resolved Only",
        "role": "primary_damage",
        "resolverQuery": "Resolved Only",
    }
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="resolver-fallback-review.json",
            components=[component],
            include_deep_record=True,
        ),
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedDeepRecords"][0]["componentKeys"] == ["skill:ResolvedOnlyPlayer"]
    assert report["singleComponentObservations"][0]["componentKeys"] == ["skill:ResolvedOnlyPlayer"]


def test_acceptance_uses_source_skill_id_to_disambiguate_named_player_skill(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="source-skill-id-review.json",
        components=[
            {
                "candidateName": "Ember Fusillade",
                "role": "primary_damage",
                "resolverQuery": "Ember Fusillade",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    review["deepResearchRecords"][0]["ascendancyKey"] = "ascendancy:ranger:deadeye"
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "activeSkills": [
                        {
                            "name": "Ember Fusillade",
                            "skillId": "EmberFusilladePlayer",
                        }
                    ]
                }
            ]
        },
        require_deep_records=True,
        validation_only=True,
    )

    assert report["status"] == "accepted"
    assert report["acceptedDeepRecords"][0]["componentKeys"] == ["skill:EmberFusilladePlayer"]
    assert "missing_build_family_identity" not in report["deferredReasonCounts"]
    assert report["unresolvedDeepRecordMentionCount"] == 0
    assert report["sourceSkillIdResolvedNames"] == ["Ember Fusillade"]


def test_source_skill_id_disambiguates_same_explicit_key_across_deep_records(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="repeated-source-skill-id-review.json",
        components=[
            {
                "candidateName": "Ember Fusillade",
                "componentKey": "skill:EmberFusilladePlayer",
                "role": "primary_damage",
                "resolverQuery": "Ember Fusillade",
            }
        ],
        include_deep_record=True,
    )
    review = json.loads(review_file.read_text(encoding="utf-8"))
    first = review["deepResearchRecords"][0]
    first["ascendancyKey"] = "ascendancy:ranger:deadeye"
    rotation = json.loads(json.dumps(first))
    rotation.update(
        recordKind="rotation",
        title="重复端点轮转记录",
        summary="同一来源技能端点在另一条记录中继续承担输出职责。",
        content="先建立触发条件，再使用 Ember Fusillade 完成输出。",
        typedPayload={"knowledgeShape": "player_action_sequence"},
    )
    rotation["components"][0]["role"] = "payoff"
    review["deepResearchRecords"].append(rotation)
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "activeSkills": [
                        {
                            "name": "Ember Fusillade",
                            "skillId": "EmberFusilladePlayer",
                        }
                    ]
                }
            ]
        },
        require_deep_records=True,
        validation_only=True,
    )

    assert report["status"] == "accepted"
    assert report["acceptedDeepRecordCount"] == 2
    assert report["unresolvedDeepRecordMentionCount"] == 0
    assert all(
        item["componentKeys"] == ["skill:EmberFusilladePlayer"]
        for item in report["acceptedDeepRecords"]
    )


def test_acceptance_keeps_canonical_name_resolution_before_source_implementation_id(tmp_path):
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="canonical-before-source-id-review.json",
            components=[
                {
                    "candidateName": "Glacial Bolt",
                    "role": "primary_damage",
                    "resolverQuery": "Glacial Bolt",
                }
            ],
            include_deep_record=True,
        ),
        graph_service=_graph_service(),
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "activeSkills": [
                        {
                            "name": "Glacial Bolt",
                            "skillId": "GlacialBoltAmmoPlayer",
                        }
                    ]
                }
            ]
        },
        validation_only=True,
    )

    assert report["acceptedDeepRecords"][0]["componentKeys"] == ["skill:GlacialBoltPlayer"]


def test_queue_acceptance_blocks_unattributed_records_but_generic_validation_remains_flexible(
    tmp_path,
):
    review_file = _write_review(
        tmp_path,
        filename="missing-family-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "secondary_skill",
                "resolverQuery": "Resolved Only",
            }
        ],
        include_deep_record=True,
    )

    strict_report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "strict-memory.sqlite",
        json_output=tmp_path / "strict-report.json",
        md_output=tmp_path / "strict-report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        require_deep_records=True,
    )
    flexible_report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "flexible-memory.sqlite",
        json_output=tmp_path / "flexible-report.json",
        md_output=tmp_path / "flexible-report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        validation_only=True,
    )

    assert strict_report["status"] == "rejected"
    assert strict_report["acceptanceMode"] == "blocked"
    assert strict_report["deferredReasonCounts"]["missing_build_family_identity"] == 1
    con = mature_learning.connect(tmp_path / "strict-memory.sqlite")
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
    finally:
        con.close()
    assert flexible_report["status"] == "accepted"
    assert flexible_report["acceptedDeepRecordCount"] == 1


def test_deep_review_acceptance_persists_unresolved_component_mentions(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="unresolved-mention-review.json",
            components=[
                {
                    "candidateName": "Missing Skill",
                    "role": "secondary_skill",
                    "resolverQuery": "Missing Skill active spell skill",
                }
            ],
            include_deep_record=True,
        ),
        graph_service=_graph_service(),
    )

    assert report["acceptedDeepRecordCount"] == 1
    assert report["acceptedPatternCount"] == 0
    assert report["unresolvedDeepRecordComponentCount"] == 1
    assert report["unresolvedDeepRecordMentionCount"] == 1
    assert report["unresolvedUniqueComponentCount"] == 1
    unresolved = report["deepRecordsWithUnresolvedComponents"][0]
    assert unresolved["titleZh"] == "聚焦机制链"
    assert unresolved["recordKind"] == "mechanic_chain"
    assert unresolved["unresolvedComponentCount"] == 1
    assert unresolved["unresolvedComponents"] == [
        {
            "candidateName": "Missing Skill",
            "role": "secondary_skill",
            "resolverQuery": "Missing Skill active spell skill",
            "reason": "source_coverage_gap",
            "actualNodeTypes": [],
            "suggestedRoles": [],
        }
    ]
    assert "insufficient_case_research_depth" not in report["deferredReasonCounts"]
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT component_keys, component_mentions FROM deep_research_records"
        ).fetchone()
        assert json.loads(row["component_keys"]) == []
        mentions = json.loads(row["component_mentions"])
        assert mentions[0]["candidate_name"] == "Missing Skill"
        assert mentions[0]["role"] == "secondary_skill"
        assert mentions[0]["resolution_status"] == "missing"
    finally:
        con.close()


def test_deep_review_acceptance_reports_unique_component_type_mismatch(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:type-mismatch",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    support = pg.GraphNode(
        "support:Metadata/Items/Gem/SupportGemRagingCry",
        "support_gem",
        "Raging Cry",
        (source.source_id,),
    )
    item_base = pg.GraphNode(
        "item_base:Metadata/Items/Gem/SupportGemRagingCry",
        "item_base",
        "Raging Cry",
        (source.source_id,),
    )
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:type-mismatch",
            created_at=datetime(2026, 7, 14, tzinfo=UTC),
            sources=(source,),
            nodes=(support, item_base),
            edges=(),
            aliases=(
                pg.GraphAlias("Raging Cry", support.stable_key, (source.source_id,)),
                pg.GraphAlias("Raging Cry", item_base.stable_key, (source.source_id,)),
            ),
        )
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="type-mismatch-review.json",
            components=[
                {
                    "candidateName": "Raging Cry",
                    "role": "secondary_skill",
                    "resolverQuery": "Raging Cry active skill",
                }
            ],
            include_deep_record=True,
        ),
        graph_service=graph_service,
    )

    assert report["acceptedDeepRecordCount"] == 1
    assert report["acceptedPatternCount"] == 0
    deferred = report["deferredCandidates"][0]
    assert deferred["reason"] == "component_type_mismatch"
    component_reason = deferred["componentReasons"][0]
    assert component_reason["actualNodeTypes"] == ["support_gem"]
    assert component_reason["suggestedRoles"] == ["support_modifier"]
    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        mention = json.loads(
            con.execute("SELECT component_mentions FROM deep_research_records").fetchone()[0]
        )[0]
        assert mention["resolution_status"] == "type_mismatch"
    finally:
        con.close()


def test_triggered_payload_requires_the_granted_active_skill_endpoint(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:support-granted-payload",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    support = pg.GraphNode(
        "support:FixturePayloadSupport",
        "support_gem",
        "Fixture Payload Support",
        (source.source_id,),
    )
    payload = pg.GraphNode(
        "skill:FixturePayloadPlayer",
        "active_skill",
        "Fixture Payload",
        (source.source_id,),
    )
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:support-granted-payload",
            created_at=datetime(2026, 7, 18, tzinfo=UTC),
            sources=(source,),
            nodes=(support, payload),
            edges=(
                pg.GraphEdge(
                    "grants_skill",
                    support.stable_key,
                    payload.stable_key,
                    (source.source_id,),
                ),
            ),
            aliases=(
                pg.GraphAlias(support.display_name, support.stable_key, (source.source_id,)),
                pg.GraphAlias(payload.display_name, payload.stable_key, (source.source_id,)),
            ),
        )
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="support-as-payload-review.json",
            components=[
                {
                    "candidateName": support.display_name,
                    "componentKey": support.stable_key,
                    "role": "triggered_payload",
                    "resolverQuery": support.stable_key,
                }
            ],
            include_deep_record=True,
        ),
        graph_service=graph_service,
    )

    assert report["acceptedPatternCount"] == 0
    deferred = report["deferredCandidates"][0]
    assert deferred["reason"] == "component_type_mismatch"
    component_reason = deferred["componentReasons"][0]
    assert component_reason["actualNodeTypes"] == ["support_gem"]
    assert component_reason["suggestedRoles"] == ["support_modifier"]


def test_functional_roles_resolve_across_compatible_physical_node_types(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:functional-roles",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    nodes = (
        pg.GraphNode("unique:pob:skysliver", "unique", "Skysliver", (source.source_id,)),
        pg.GraphNode("notable:pob:0_5:9294", "notable", "Critical Strike", (source.source_id,)),
        pg.GraphNode("notable:pob:0_5:35187", "notable", "In for the Kill", (source.source_id,)),
    )
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:functional-roles",
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
            sources=(source,),
            nodes=nodes,
            edges=(),
            aliases=tuple(
                pg.GraphAlias(node.display_name, node.stable_key, (source.source_id,))
                for node in nodes
            ),
        )
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="functional-role-review.json",
            components=[
                {
                    "candidateName": "Skysliver",
                    "role": "weapon_base",
                    "resolverQuery": "unique:pob:skysliver",
                },
                {
                    "candidateName": "Critical Strike",
                    "role": "keystone_transformer",
                    "resolverQuery": "notable:pob:0_5:9294",
                },
                {
                    "candidateName": "In for the Kill",
                    "role": "payoff",
                    "resolverQuery": "notable:pob:0_5:35187",
                },
            ],
            include_deep_record=True,
        ),
        graph_service=graph_service,
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 1
    assert report["unresolvedDeepRecordMentionCount"] == 0
    assert report["unresolvedUniqueComponentCount"] == 0
    assert report["deferredCandidateCount"] == 0


def test_type_mismatch_diagnostic_prefers_exact_name_over_related_candidates(tmp_path):
    source = pg.GraphSource(
        source_id="fixture:exact-type-mismatch",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    nodes = (
        pg.GraphNode("notable:pob:0_5:9294", "notable", "Critical Strike", (source.source_id,)),
        pg.GraphNode(
            "passive:pob:0_5:31112",
            "passive",
            "Ballista Critical Strike",
            (source.source_id,),
        ),
        pg.GraphNode(
            "passive:pob:0_5:63828",
            "passive",
            "Ballista Critical Strike and Damage",
            (source.source_id,),
        ),
    )
    graph_service = gt.GraphQueryService.from_snapshot(
        pg.GraphSnapshot(
            snapshot_id="snapshot:exact-type-mismatch",
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
            sources=(source,),
            nodes=nodes,
            edges=(),
            aliases=tuple(
                pg.GraphAlias(node.display_name, node.stable_key, (source.source_id,))
                for node in nodes
            ),
        )
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="exact-type-mismatch-review.json",
            components=[
                {
                    "candidateName": "Critical Strike",
                    "role": "secondary_skill",
                    "resolverQuery": "Critical Strike active skill",
                }
            ],
            include_deep_record=True,
        ),
        graph_service=graph_service,
    )

    deferred = report["deferredCandidates"][0]["componentReasons"][0]
    assert deferred["reason"] == "component_type_mismatch"
    assert deferred["actualNodeTypes"] == ["notable"]
    assert deferred["discoveredCandidates"] == ["notable:pob:0_5:9294"]
    assert deferred["suggestedRoles"] == ["passive_anchor"]


def test_deep_review_acceptance_rejects_shallow_case_without_persisting_records(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=_write_review(
            tmp_path,
            filename="shallow-review.json",
            components=[],
            include_deep_record=True,
        ),
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    assert report["acceptedDeepRecordCount"] == 0
    assert report["deferredReasonCounts"]["insufficient_case_research_depth"] == 1
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
    finally:
        con.close()


def test_deep_review_acceptance_normalizes_worker_enum_canonical_variants(tmp_path):
    variants = [
        ("BuildArchetypePattern", "build_archetype"),
        ("build-archetype observation", "build_archetype"),
        ("CoOccurrence Pattern", "cooccurrence"),
        ("plannerHintCandidate", "planner_hint"),
        ("TransitionGatePattern", "transition_gate"),
        ("failure-pattern candidate", "failure_pattern"),
    ]
    for index, (pattern_type, expected) in enumerate(variants):
        db_path = tmp_path / f"memory-{index}.sqlite"
        review_file = _write_review(
            tmp_path,
            filename=f"review-{index}.json",
            components=[
                {
                    "candidateName": "Resolved Only",
                    "componentKey": "skill:ResolvedOnlyPlayer",
                    "role": "primary_damage",
                    "resolverQuery": "Resolved Only",
                },
                {
                    "candidateName": "Fixture Support",
                    "componentKey": "support:FixtureSupport",
                    "role": "support_modifier",
                    "resolverQuery": "Fixture Support",
                },
            ],
            candidate_overrides={
                "patternType": pattern_type,
                "axes": ["primary_skill_package", "variant_relation", "modelability_caveat"],
            },
        )
        report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
            db_path=db_path,
            json_output=tmp_path / f"report-{index}.json",
            md_output=tmp_path / f"report-{index}.md",
            review_file=review_file,
            graph_service=_graph_service(),
        )

        assert report["status"] == "accepted"
        assert report["acceptedPatternCount"] == 1
        con = mature_learning.connect(db_path)
        try:
            observation = con.execute(
                "SELECT observation_type, axes FROM research_build_design_observations"
            ).fetchone()
            pattern = con.execute("SELECT pattern_type FROM research_build_patterns").fetchone()
            assert observation["observation_type"] == expected
            assert pattern["pattern_type"] == expected
            axes = json.loads(observation["axes"])
            assert "variant_relations" in axes
            assert "modelability_caveats" in axes
        finally:
            con.close()


def test_deep_review_acceptance_rejects_invalid_pattern_type(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        candidate_overrides={
            "patternType": "mechanic_engine",
            "axes": ["mechanic_engine", "itemization"],
        },
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "rejected"
    assert report["acceptanceMode"] == "blocked"
    assert report["acceptedPatternCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == "invalid_schema"


def test_deep_review_acceptance_uses_reviewed_mapping_for_ambiguous_endpoint(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )
    primary_mapping = _write_mapping(
        tmp_path,
        accepted_stable_key="skill:SparkPlayer",
        candidate_name="Spark",
        candidates=[
            {
                "stableKey": "gem:Spark",
                "nodeType": "skill_gem",
                "sourceRefs": ["fixture:mapping_report_only"],
            },
            {
                "stableKey": "skill:SparkPlayer",
                "nodeType": "active_skill",
                "sourceRefs": ["fixture:mapping_report_only"],
            },
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        primary_mapping_report=primary_mapping,
        graph_service=_graph_service(),
    )

    assert report["safeArtifactOnly"] is True
    assert report["patternWrite"]["status"] == "accepted"
    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 1
    assert report["deferredCandidateCount"] == 0
    assert report["singleComponentObservations"][0]["componentResolutions"][0][
        "resolutionSource"
    ] == ("direct_resolver")
    observations = report["patternWrite"]["observationIds"]
    con = mature_learning.connect(tmp_path / "memory.sqlite")
    try:
        row = con.execute(
            "SELECT components FROM research_build_design_observations WHERE observation_id = ?",
            (observations[0],),
        ).fetchone()
        components = json.loads(row["components"])
        assert components[0]["resolution"]["source_refs"] == ["fixture:deep_review"]
    finally:
        con.close()
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()


def test_deep_review_acceptance_uses_role_type_to_resolve_ambiguous_name(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 1
    assert report["deferredCandidateCount"] == 0
    assert report["singleComponentObservations"][0]["componentKeys"] == ["skill:SparkPlayer"]


def test_deep_review_acceptance_prefers_explicit_resolver_query(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "skill:SparkPlayer",
            }
        ],
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 1
    assert report["deferredCandidateCount"] == 0
    assert (
        report["singleComponentObservations"][0]["componentResolutions"][0]["resolutionSource"]
        == "direct_resolver"
    )


def test_deep_review_acceptance_reuses_same_review_stable_key_confirmation(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "secondary_skill",
                "resolverQuery": "skill:SparkPlayer",
            },
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "generator",
                "resolverQuery": "Spark",
            },
        ],
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        validation_only=True,
    )

    assert report["deferredCandidateCount"] == 0
    resolutions = report["singleComponentObservations"][0]["componentResolutions"]
    assert [item["resolutionSource"] for item in resolutions] == [
        "direct_resolver",
        "intra_review_stable_confirmation",
    ]


def test_deep_review_acceptance_defers_stale_ambiguous_mapping_not_in_resolver(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )
    stale_mapping = _write_mapping(
        tmp_path,
        accepted_stable_key="skill:ResolvedOnlyPlayer",
        candidate_name="Spark",
        candidates=[
            {
                "stableKey": "skill:ResolvedOnlyPlayer",
                "nodeType": "active_skill",
                "sourceRefs": ["fixture:stale_mapping_only"],
            }
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        primary_mapping_report=stale_mapping,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == "resolver_key_mismatch"


def test_deep_review_acceptance_does_not_need_mapping_after_role_type_resolution(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Spark",
                "componentKey": "skill:SparkPlayer",
                "role": "primary_damage",
                "resolverQuery": "Spark",
            }
        ],
    )
    stale_mapping = _write_mapping(
        tmp_path,
        accepted_stable_key="skill:SparkPlayer",
        candidate_name="Spark",
        candidates=[
            {
                "stableKey": "gem:Spark",
                "nodeType": "skill_gem",
                "sourceRefs": ["fixture:deep_review"],
            }
        ],
    )
    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        primary_mapping_report=stale_mapping,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 1
    assert report["deferredCandidateCount"] == 0


def test_deep_review_acceptance_defers_missing_endpoint_and_empty_review(tmp_path):
    missing_review = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Missing Skill",
                "componentKey": "skill:MissingSkillPlayer",
                "role": "primary_damage",
                "resolverQuery": "Missing Skill",
            }
        ],
    )
    missing = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "missing.sqlite",
        json_output=tmp_path / "missing.json",
        md_output=tmp_path / "missing.md",
        review_file=missing_review,
        graph_service=_graph_service(),
    )
    empty_review = _write_review(tmp_path, components=[], filename="empty-review.json")
    empty = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "empty.sqlite",
        json_output=tmp_path / "empty.json",
        md_output=tmp_path / "empty.md",
        review_file=empty_review,
        graph_service=_graph_service(),
    )

    assert missing["acceptedPatternCount"] == 0
    assert missing["deferredCandidates"][0]["reason"] == "source_coverage_gap"
    assert empty["acceptedPatternCount"] == 0
    assert empty["deferredCandidateCount"] == 0


def test_deep_review_acceptance_defers_pattern_with_unstructured_source_component(tmp_path):
    review_file = _write_review(
        tmp_path,
        filename="unstructured-source-component-review.json",
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        candidate_overrides={
            "summary": ("单样本观察：Resolved Only 搭配 Prolonged Duration II 延长持续时间。")
        },
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
        source_skill_manifest={
            "activeSkillGroups": [
                {
                    "groupRef": "skill-set:1:group:1",
                    "activeSkills": [{"name": "Resolved Only", "skillId": "ResolvedOnlyPlayer"}],
                    "supports": [
                        {
                            "name": "Prolonged Duration II",
                            "gemId": "Metadata/Items/Gems/SupportGemProlongedDurationTwo",
                        }
                    ],
                }
            ]
        },
        validation_only=True,
    )

    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == ("unstructured_source_component_mention")
    assert "Prolonged Duration II" in report["deferredCandidates"][0]["caveats"][0]


def test_deep_review_acceptance_defers_invalid_candidate_but_accepts_valid_one(tmp_path):
    bad_candidate = {
        "sampleId": "fixture_sample_001",
        "caseRef": "case:fixture-sample-001",
        "safeEvidenceRef": "safe:fixture-sample-001",
        "patternType": "cooccurrence",
        "title": "过强候选",
        "summary": "这是常见组合。",
        "axes": ["primary_skill_package"],
        "components": [
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        "plannerHint": "Treat as advisory only.",
        "verificationGate": "Verify before planner use.",
        "verificationTasks": ["Verify before planner use."],
    }
    good_candidate = {
        **bad_candidate,
        "title": "安全候选",
        "summary": "这是单样本观察。",
    }
    review = {
        "reportId": "phase4-deep-researcher-candidate-review-v1",
        "safeArtifactOnly": True,
        "candidateReviews": [bad_candidate, good_candidate],
    }
    review_file = tmp_path / "mixed-review.json"
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 0
    assert report["singleComponentObservationCount"] == 1
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == "overclaimed_pattern_confidence"
    assert report["singleComponentObservations"][0]["titleZh"] == "安全候选"


def test_deep_review_acceptance_rejects_mojibake_or_surrogate_text(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            }
        ],
        candidate_overrides={
            "title": "Oracle \u6fb6\u6c2d\u59a7\u9473\udcaf damaged text",
        },
    )

    try:
        run_phase4_deep_review_acceptance.accept_deep_review_candidates(
            db_path=tmp_path / "memory.sqlite",
            json_output=tmp_path / "acceptance.json",
            md_output=tmp_path / "acceptance.md",
            review_file=review_file,
            graph_service=_graph_service(),
        )
    except ValueError as exc:
        assert "invalid unicode" in str(exc)
    else:  # pragma: no cover - assertion clarity.
        raise AssertionError("mojibake/surrogate safe review was accepted")


def test_source_specific_candidate_indexes_only_the_named_source_component(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Resolved Only",
                "componentKey": "skill:ResolvedOnlyPlayer",
                "role": "primary_damage",
                "resolverQuery": "Resolved Only",
            },
            {
                "candidateName": "Fixture Identity Item",
                "componentKey": "unique:FixtureIdentityItem",
                "role": "unique_enabler",
                "resolverQuery": "Fixture Identity Item",
            },
        ],
        candidate_overrides={
            "availability": "source_specific_random",
            "sourceSpecificComponentNames": ["Fixture Identity Item"],
        },
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["acceptedPatternCount"] == 0
    assert report["caseOnlyObservationCount"] == 1
    assert report["caseOnlyObservations"][0]["componentKeys"] == ["unique:FixtureIdentityItem"]
    assert (
        report["caseOnlyObservations"][0]["componentIndexing"]
        == "resolved_source_specific_components"
    )
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT component_keys FROM research_build_design_observations"
        ).fetchone()
    finally:
        con.close()
    assert json.loads(row["component_keys"]) == ["unique:FixtureIdentityItem"]


def test_source_specific_candidate_without_a_stable_node_becomes_unindexed_note(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Unmapped Mutated Rare",
                "componentKey": "",
                "role": "unique_enabler",
                "resolverQuery": "Unmapped Mutated Rare",
            }
        ],
        candidate_overrides={
            "availability": "source_specific_random",
            "sourceSpecificComponentNames": ["Unmapped Mutated Rare"],
            "transferScope": "component",
        },
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=db_path,
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["status"] == "accepted"
    assert report["deferredCandidateCount"] == 0
    assert report["acceptedPatternCount"] == 0
    assert report["caseOnlyObservationCount"] == 1
    assert report["caseOnlyObservations"][0]["componentKeys"] == []
    assert (
        report["caseOnlyObservations"][0]["componentIndexing"]
        == "omitted_unresolved_source_specific_components"
    )
    con = mature_learning.connect(db_path)
    try:
        row = con.execute(
            "SELECT component_keys FROM research_build_design_observations"
        ).fetchone()
    finally:
        con.close()
    assert json.loads(row["component_keys"]) == []


def test_source_specific_candidate_requires_explicit_source_component(tmp_path):
    review_file = _write_review(
        tmp_path,
        components=[
            {
                "candidateName": "Fixture Identity Item",
                "componentKey": "unique:FixtureIdentityItem",
                "role": "unique_enabler",
                "resolverQuery": "Fixture Identity Item",
            }
        ],
        candidate_overrides={"availability": "source_specific_random"},
    )

    report = run_phase4_deep_review_acceptance.accept_deep_review_candidates(
        db_path=tmp_path / "memory.sqlite",
        json_output=tmp_path / "report.json",
        md_output=tmp_path / "report.md",
        review_file=review_file,
        graph_service=_graph_service(),
    )

    assert report["acceptedPatternCount"] == 0
    assert report["caseOnlyObservationCount"] == 0
    assert report["deferredCandidateCount"] == 1
    assert report["deferredCandidates"][0]["reason"] == "missing_source_specific_component"


def _write_review(
    tmp_path,
    *,
    components: list[dict[str, str]],
    filename: str = "review.json",
    candidate_overrides: dict[str, object] | None = None,
    include_deep_record: bool = False,
):
    candidate = {
        "sampleId": "fixture_sample_001",
        "caseRef": "case:fixture-sample-001",
        "safeEvidenceRef": "safe:fixture-sample-001",
        "patternType": "cooccurrence",
        "title": "单例：fixture pattern",
        "summary": "单样本 fixture observation for acceptance gate.",
        "axes": ["primary_skill_package", "modelability_caveats"],
        "components": components,
        "plannerHint": "Treat fixture pattern as advisory only.",
        "verificationGate": "Verify fixture selected skill before planner use.",
        "verificationTasks": ["Verify fixture selected skill before planner use."],
    }
    if candidate_overrides:
        candidate.update(candidate_overrides)
    review = {
        "reportId": "phase4-deep-researcher-candidate-review-v1",
        "safeArtifactOnly": True,
        "candidateReviews": [] if not components else [candidate],
        "deepResearchRecords": (
            [
                {
                    "sampleId": "fixture_sample_001",
                    "researchGroupId": "research:fixture_sample_001",
                    "caseRef": "case:fixture-sample-001",
                    "safeEvidenceRef": "safe:fixture-sample-001",
                    "recordKind": "mechanic_chain",
                    "title": "聚焦机制链",
                    "summary": "只记录一个机制问题。",
                    "content": "这条记录只解释一个主要机制问题及其成立条件。",
                    "contentLanguage": "zh-CN",
                    "lengthExceptionReason": None,
                    "components": components,
                    "conditions": ["组件已解析"],
                    "failureConditions": ["组件失效"],
                    "typedPayload": {},
                    "extractionMethodVersion": "deep_research_mvp_v1",
                    "gamePatch": "0.5.4",
                    "passiveTreeVersion": "0_5",
                    "pobVersionOrCommit": "unknown",
                }
            ]
            if include_deep_record
            else []
        ),
    }
    path = tmp_path / filename
    path.write_text(json.dumps(review, ensure_ascii=True, indent=2), encoding="utf-8")
    return path


def _write_mapping(
    tmp_path,
    *,
    accepted_stable_key: str,
    candidate_name: str,
    candidates: list[dict[str, str]] | None = None,
):
    mapping = {
        "reportId": "phase4-reviewed-endpoint-mapping-v1",
        "safeArtifactOnly": True,
        "snapshotId": "snapshot:deep-review-fixture",
        "reviewItems": [
            {
                "sampleId": "fixture_sample_001",
                "candidateName": candidate_name,
                "acceptedStableKey": accepted_stable_key,
                "reviewStatus": "accepted",
                "resolverStatus": "ambiguous",
                "candidates": candidates
                or [
                    {
                        "stableKey": "gem:Spark",
                        "nodeType": "skill_gem",
                        "sourceRefs": ["fixture:deep_review"],
                    },
                    {
                        "stableKey": "skill:SparkPlayer",
                        "nodeType": "active_skill",
                        "sourceRefs": ["fixture:deep_review"],
                    },
                ],
            }
        ],
    }
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _graph_service() -> gt.GraphQueryService:
    source = pg.GraphSource(
        source_id="fixture:deep_review",
        kind="test_fixture",
        source_file="tests/test_phase4_deep_review_acceptance.py",
    )
    nodes = (
        pg.GraphNode(
            "skill:ResolvedOnlyPlayer", "active_skill", "Resolved Only", (source.source_id,)
        ),
        pg.GraphNode("gem:Spark", "skill_gem", "Spark", (source.source_id,)),
        pg.GraphNode("skill:SparkPlayer", "active_skill", "Spark", (source.source_id,)),
        pg.GraphNode("notable:Spark", "notable", "Spark", (source.source_id,)),
        pg.GraphNode(
            "skill:EmberFusilladePlayer",
            "active_skill",
            "Ember Fusillade",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:EmberFusilladeAltPlayer",
            "active_skill",
            "Ember Fusillade",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:GlacialBoltPlayer",
            "active_skill",
            "Glacial Bolt",
            (source.source_id,),
        ),
        pg.GraphNode(
            "skill:GlacialBoltAmmoPlayer",
            "active_skill",
            "Glacial Bolt Ammo",
            (source.source_id,),
        ),
        pg.GraphNode("ascendancy:ranger:deadeye", "ascendancy", "Deadeye", (source.source_id,)),
        pg.GraphNode(
            "unique:FixtureIdentityItem",
            "unique",
            "Fixture Identity Item",
            (source.source_id,),
        ),
        pg.GraphNode(
            "support:FixtureSupport",
            "support_gem",
            "Fixture Support",
            (source.source_id,),
        ),
        pg.GraphNode(
            "item_base:Metadata/Items/Armours/BodyArmours/Fixture",
            "item_base",
            "Fixture Body Armour",
            (source.source_id,),
        ),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:deep-review-fixture",
        created_at=datetime(2026, 7, 6, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        edges=(),
        aliases=(
            pg.GraphAlias("Resolved Only", "skill:ResolvedOnlyPlayer", (source.source_id,)),
            pg.GraphAlias("Spark", "gem:Spark", (source.source_id,)),
            pg.GraphAlias("Spark", "skill:SparkPlayer", (source.source_id,)),
            pg.GraphAlias("Spark", "notable:Spark", (source.source_id,)),
            pg.GraphAlias(
                "Ember Fusillade",
                "skill:EmberFusilladePlayer",
                (source.source_id,),
            ),
            pg.GraphAlias(
                "Ember Fusillade",
                "skill:EmberFusilladeAltPlayer",
                (source.source_id,),
            ),
            pg.GraphAlias(
                "Glacial Bolt",
                "skill:GlacialBoltPlayer",
                (source.source_id,),
            ),
            pg.GraphAlias("Deadeye", "ascendancy:ranger:deadeye", (source.source_id,)),
            pg.GraphAlias(
                "Fixture Identity Item", "unique:FixtureIdentityItem", (source.source_id,)
            ),
            pg.GraphAlias("Fixture Support", "support:FixtureSupport", (source.source_id,)),
            pg.GraphAlias(
                "Fixture Body Armour",
                "item_base:Metadata/Items/Armours/BodyArmours/Fixture",
                (source.source_id,),
            ),
        ),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)


def test_unique_gem_diagnostics_splits_non_gem_names_and_corpus_missing():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:10",
                "activeSkills": [
                    {
                        "name": "ThornsPlayer",
                        "skillId": "ThornsPlayer",
                        "nameSource": "internal_id",
                    },
                    {
                        "name": "EnemyExplode",
                        "skillId": "EnemyExplode",
                        "nameSource": "internal_id",
                    },
                    {"name": "Bonestorm", "skillId": "BonestormPlayer", "nameSource": "gem_name"},
                ],
                "supports": [
                    {
                        "name": "Oisin's Oath",
                        "gemId": "SupportGemOisinsOath",
                        "nameSource": "gem_name",
                    }
                ],
            }
        ]
    }
    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-020"},
        "deepResearchRecords": [],
    }
    diagnostics = acceptance._unique_gem_diagnostics(review, manifest)

    assert diagnostics["available"] is True
    assert "ThornsPlayer" in diagnostics["nonGemSkillNames"]
    assert "EnemyExplode" in diagnostics["nonGemSkillNames"]
    assert "Bonestorm" not in diagnostics["nonGemSkillNames"]
    assert "Oisin's Oath" in diagnostics["corpusMissingGemNames"]
    assert diagnostics["uniqueGemCandidates"] == []
    assert diagnostics["proseMentionedWithoutComponentNames"] == []


def test_unique_gem_diagnostics_reports_prose_mention_without_component():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:4",
                "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                "supports": [
                    {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"}
                ],
            }
        ]
    }
    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-021"},
        "deepResearchRecords": [
            {
                "sampleId": "case:fix-021",
                "researchGroupId": "research:case:fix-021",
                "caseRef": "source-hash:fix-021",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Rotation",
                "recordKind": "rotation",
                "summary": "Bhatair's Vengeance mentioned in prose only",
                "content": "Flash Grenade controls; Bhatair's Vengeance adds stun buildup",
                "components": [
                    {
                        "candidateName": "Flash Grenade",
                        "componentKey": "skill:FlashGrenadePlayer",
                        "role": "control_skill",
                    }
                ],
            }
        ],
    }
    diagnostics = acceptance._unique_gem_diagnostics(review, manifest)

    assert "Bhatair's Vengeance" in diagnostics["proseMentionedWithoutComponentNames"]
    assert diagnostics["unlabeledUniqueGemNames"] == ["Bhatair's Vengeance"]


def test_unique_gem_diagnostics_component_declaration_clears_prose_only():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:4",
                "activeSkills": [{"name": "Flash Grenade", "skillId": "FlashGrenadePlayer"}],
                "supports": [
                    {"name": "Bhatair's Vengeance", "gemId": "SupportGemBhatairsVengeance"}
                ],
            }
        ]
    }
    review = {
        "safeArtifactOnly": True,
        "artifactIdentity": {"sampleId": "case:fix-022"},
        "deepResearchRecords": [
            {
                "sampleId": "case:fix-022",
                "researchGroupId": "research:case:fix-022",
                "caseRef": "source-hash:fix-022",
                "safeEvidenceRefs": ["evidence:fix"],
                "title": "Rotation",
                "recordKind": "rotation",
                "summary": "declared component",
                "content": "Flash Grenade controls with Freeze",
                "components": [
                    {
                        "candidateName": "Flash Grenade",
                        "componentKey": "skill:FlashGrenadePlayer",
                        "role": "control_skill",
                    },
                    {
                        "candidateName": "Bhatair's Vengeance",
                        "componentKey": "support:SupportGemBhatairsVengeance",
                        "role": "support_modifier",
                    },
                ],
            }
        ],
    }
    diagnostics = acceptance._unique_gem_diagnostics(review, manifest)

    assert diagnostics["proseMentionedWithoutComponentNames"] == []


def test_source_skill_id_resolutions_skips_internal_id_skills():
    from scripts import run_phase4_deep_review_acceptance as acceptance

    calls: list[tuple[str, dict]] = []

    class FakeGraph:
        def run_tool(self, name, payload):
            calls.append((name, payload))
            return {"status": "resolved", "resolvedSubject": {"stableKey": payload["query"]}}

    manifest = {
        "activeSkillGroups": [
            {
                "groupRef": "skill-set:1:group:1",
                "activeSkills": [
                    {
                        "name": "ThornsPlayer",
                        "skillId": "ThornsPlayer",
                        "nameSource": "internal_id",
                    },
                    {
                        "name": "Bonestorm",
                        "skillId": "BonestormPlayer",
                        "nameSource": "gem_name",
                    },
                ],
                "supports": [],
            }
        ]
    }

    resolutions = acceptance._source_skill_id_resolutions(
        graph_service=FakeGraph(),
        source_skill_manifest=manifest,
    )

    assert set(resolutions) == {"bonestorm"}
    assert len(calls) == 1
    assert calls[0][1]["query"] == "skill:BonestormPlayer"
