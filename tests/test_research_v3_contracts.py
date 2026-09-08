from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import json
import sqlite3

import pytest

from server.knowledge import research_identity, research_models
from server.knowledge import research_intake_ledger, research_memory, research_runtime
from server.knowledge import graph_tools, physical_graph
from server import main
from server.generation import progression_provenance
from scripts import research_mature_builds


def _graph_service() -> graph_tools.GraphQueryService:
    source = physical_graph.GraphSource(
        source_id="fixture:v3",
        kind="test_fixture",
        source_file=__file__,
    )
    return graph_tools.GraphQueryService.from_snapshot(
        physical_graph.GraphSnapshot(
            snapshot_id="snapshot:v3",
            created_at=datetime(2026, 8, 23, tzinfo=UTC),
            sources=(source,),
            nodes=(
                physical_graph.GraphNode(
                    "skill:CometPlayer", "active_skill", "Comet", (source.source_id,)
                ),
                physical_graph.GraphNode(
                    "support:ArcaneTempo",
                    "support_gem",
                    "Arcane Tempo",
                    (source.source_id,),
                ),
                physical_graph.GraphNode(
                    "skill:MetaCastOnCritPlayer",
                    "active_skill",
                    "Cast on Critical",
                    (source.source_id,),
                ),
                physical_graph.GraphNode(
                    "ascendancy:witch:blood_mage",
                    "ascendancy",
                    "Blood Mage",
                    (source.source_id,),
                ),
            ),
            edges=(),
            aliases=(),
        )
    )


def _record(*, schema: int = 2) -> dict:
    return {
        "research_group_id": "research:case:v3",
        "record_kind": "gear_synergy",
        "title": "装备预算",
        "summary": "装备预算摘要",
        "content": "头胸手鞋承担抗性与资源预算。",
        "content_language": "zh-CN",
        "component_keys": ["skill:CometPlayer"],
        "component_mentions": [
            {
                "candidate_name": "Comet",
                "role": "primary_damage",
                "resolver_query": "skill:CometPlayer",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:CometPlayer",
                "resolution_status": "resolved",
            }
        ],
        "source_case_refs": ["case:v3"],
        "safe_evidence_refs": ["safe:v3"],
        "conditions": [],
        "failure_conditions": [],
        "typed_payload": {"gearResponsibilities": [], "gearSubjects": ["helmet"]},
        "ascendancy_key": "ascendancy:witch:blood_mage",
        "extraction_method_version": "test-v3",
        "record_schema_version": schema,
        "game_patch": "0.5.4",
        "passive_tree_version": "tree-test",
        "pob_version_or_commit": "unknown",
        "visibility": "creator_visible",
        "split": "train_context",
        "knowledge_scope": "local_user",
        "status": "valid",
        "copy_safety_state": "passed",
        "source_state_scope": "state_agnostic",
    }


def _with_raw_compact_dq(
    service: research_memory.ResearchMemoryService,
    payload: dict,
) -> dict:
    """Attach the real raw DQ prerequisite used by start_retrieval_session."""

    value = deepcopy(payload)
    dedupe_ref = "dq-" + research_runtime.stable_hash(value)[:16]
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        revision = research_runtime.get_memory_revision(con)
        now = datetime.now(tz=UTC).isoformat()
        service._record_dedupe_query(
            con,
            dedupe_ref=dedupe_ref,
            query="fixture compact query",
            component_keys=[],
            request_contract={"responseProfile": "create_compact"},
            result_contract={
                "queryContractVersion": 2,
                "deepRecordEligibilityVersion": research_memory.DEEP_RECORD_ELIGIBILITY_VERSION,
                "responseProfile": "create_compact",
                "memoryRevision": revision,
                "selectedKnowledgeScope": value.get("selectedKnowledgeScope"),
                "selectedSourceCaseRef": value.get("selectedSourceCaseRef"),
                "createAuthorizing": False,
            },
            now=now,
        )
        con.commit()
    finally:
        con.close()
    value["dedupeQueryRef"] = dedupe_ref
    return value


def _make_family_tables_unscoped(
    db_path,
    *,
    knowledge_scope: str,
    family_key: str,
) -> None:
    """Convert one scoped Family row into the legacy unscoped v5 fixture shape."""

    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("DROP TABLE research_build_family_evidence")
        con.execute("ALTER TABLE research_build_families RENAME TO scoped_families_fixture")
        con.execute(
            """
            CREATE TABLE research_build_families (
                build_family_key TEXT PRIMARY KEY,
                ascendancy_key TEXT NOT NULL,
                primary_skill_key TEXT NOT NULL,
                primary_skill_keys TEXT NOT NULL DEFAULT '[]',
                secondary_skill_keys TEXT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO research_build_families
            SELECT build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys,
                   secondary_skill_keys, evidence_count, created_at, last_seen_at
            FROM scoped_families_fixture
            WHERE knowledge_scope = ? AND build_family_key = ?
            """,
            (knowledge_scope, family_key),
        )
        con.execute("DROP TABLE scoped_families_fixture")
        con.execute(
            """
            CREATE TABLE research_build_family_evidence (
                build_family_key TEXT NOT NULL,
                source_case_ref TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (build_family_key, source_case_ref)
            )
            """
        )
        con.commit()
    finally:
        con.close()


def test_schema6_requires_record_schema2_and_gear_subjects() -> None:
    record = _record()
    assert (
        research_models.validate_researcher_output(
            {"schema_version": 6, "deep_research_records": [record]}
        )["status"]
        == "accepted"
    )

    missing = deepcopy(record)
    missing["typed_payload"].pop("gearSubjects")
    result = research_models.validate_researcher_output(
        {"schema_version": 6, "deep_research_records": [missing]}
    )
    assert result["status"] == "error"

    legacy = deepcopy(record)
    legacy["record_schema_version"] = 1
    legacy["typed_payload"].pop("gearSubjects")
    assert (
        research_models.validate_researcher_output(
            {"schema_version": 5, "deep_research_records": [legacy]}
        )["status"]
        == "accepted"
    )


def test_gear_subjects_separate_content_based_gear_identity() -> None:
    helmet = research_models.DeepResearchRecordProposal.model_validate(_record())
    jewel_payload = _record()
    jewel_payload["typed_payload"]["gearSubjects"] = ["passive_tree_jewel"]
    jewel = research_models.DeepResearchRecordProposal.model_validate(jewel_payload)
    family = research_identity.BuildFamilyIdentity(
        ascendancy_key="ascendancy:witch:blood_mage",
        primary_skill_keys=("skill:CometPlayer",),
    )
    assert research_identity.knowledge_key(helmet, family) != research_identity.knowledge_key(
        jewel, family
    )


def test_support_topology_separates_schema2_identity_without_changing_legacy() -> None:
    base = _record()
    base["record_kind"] = "skill_package"
    base["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:CometPlayer",
                "supportKeys": ["support:ArcaneTempo"],
                "deliveryRole": "direct",
            }
        ]
    }
    base["component_keys"].append("support:ArcaneTempo")
    base["component_mentions"].append(
        {
            "candidate_name": "Arcane Tempo",
            "role": "support_modifier",
            "resolver_query": "support:ArcaneTempo",
            "expected_node_types": ["support_gem"],
            "scope": "player",
            "component_key": "support:ArcaneTempo",
            "resolution_status": "resolved",
        }
    )
    direct = research_models.DeepResearchRecordProposal.model_validate(base)
    payload = deepcopy(base)
    payload["component_keys"].append("skill:MetaCastOnCritPlayer")
    payload["component_mentions"].append(
        {
            "candidate_name": "Cast on Critical",
            "role": "trigger_host",
            "resolver_query": "skill:MetaCastOnCritPlayer",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:MetaCastOnCritPlayer",
            "resolution_status": "resolved",
        }
    )
    payload["typed_payload"]["supportPackages"][0].update(
        {
            "deliveryRole": "triggered_payload",
            "hostSkillKey": "skill:MetaCastOnCritPlayer",
        }
    )
    triggered = research_models.DeepResearchRecordProposal.model_validate(payload)
    family = research_identity.BuildFamilyIdentity(
        ascendancy_key="ascendancy:witch:blood_mage",
        primary_skill_keys=("skill:CometPlayer",),
    )
    assert research_identity.knowledge_key(direct, family) != research_identity.knowledge_key(
        triggered, family
    )


def test_schema2_non_skill_record_requires_complete_unique_support_ownership() -> None:
    payload = _record()
    payload["record_kind"] = "defense_engine"
    payload["typed_payload"] = {}
    payload["component_keys"].append("support:ArcaneTempo")
    payload["component_mentions"].append(
        {
            "candidate_name": "Arcane Tempo",
            "role": "support_modifier",
            "resolver_query": "support:ArcaneTempo",
            "expected_node_types": ["support_gem"],
            "scope": "player",
            "component_key": "support:ArcaneTempo",
            "resolution_status": "resolved",
        }
    )
    assert research_models.validate_researcher_output(
        {"schema_version": 6, "deep_research_records": [payload]}
    )["status"] == "error"

    payload["typed_payload"]["supportPackages"] = [
        {
            "skillKey": "skill:CometPlayer",
            "supportKeys": ["support:ArcaneTempo"],
            "deliveryRole": "direct",
        }
    ]
    first = research_models.DeepResearchRecordProposal.model_validate(payload)
    second_payload = deepcopy(payload)
    second_payload["component_keys"][-1] = "support:SecondSupport"
    second_payload["component_mentions"][-1].update(
        {
            "candidate_name": "Second Support",
            "resolver_query": "support:SecondSupport",
            "component_key": "support:SecondSupport",
        }
    )
    second_payload["typed_payload"]["supportPackages"][0]["supportKeys"] = [
        "support:SecondSupport"
    ]
    second = research_models.DeepResearchRecordProposal.model_validate(second_payload)
    family = research_identity.BuildFamilyIdentity(
        ascendancy_key="ascendancy:witch:blood_mage",
        primary_skill_keys=("skill:CometPlayer",),
    )
    assert research_identity.knowledge_key(first, family) != research_identity.knowledge_key(
        second, family
    )


def test_schema2_durable_topology_allows_same_support_type_under_distinct_roots() -> None:
    payload = _record()
    payload["record_kind"] = "skill_package"
    payload["typed_payload"] = {
        "supportPackages": [
            {
                "skillKey": "skill:CometPlayer",
                "supportKeys": ["support:ArcaneTempo"],
                "deliveryRole": "direct",
            },
            {
                "skillKey": "skill:FrostWallPlayer",
                "supportKeys": ["support:ArcaneTempo"],
                "deliveryRole": "direct",
            },
        ]
    }
    payload["component_keys"].extend(
        ["skill:FrostWallPlayer", "support:ArcaneTempo"]
    )
    payload["component_mentions"].extend(
        [
            {
                "candidate_name": "Frost Wall",
                "role": "secondary_skill",
                "resolver_query": "skill:FrostWallPlayer",
                "expected_node_types": ["active_skill"],
                "scope": "player",
                "component_key": "skill:FrostWallPlayer",
                "resolution_status": "resolved",
            },
            {
                "candidate_name": "Arcane Tempo",
                "role": "support_modifier",
                "resolver_query": "support:ArcaneTempo",
                "expected_node_types": ["support_gem"],
                "scope": "player",
                "component_key": "support:ArcaneTempo",
                "resolution_status": "resolved",
            },
        ]
    )

    record = research_models.DeepResearchRecordProposal.model_validate(payload)

    assert record.typed_payload["supportPackages"] == payload["typed_payload"][
        "supportPackages"
    ]


def test_acceptance_unit_commits_records_receipt_and_revision_once(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    deep = {"schema_version": 6, "deep_research_records": [_record()]}
    result = service.accept_research_unit(
        run_ref="research-run:test",
        sample_id="case:v3",
        accept_attempt_key="raa-test",
        packet_safe_hash="packet-safe-hash",
        canonical_review_hash="review-hash",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload=deep,
        edge_payload={"schema_version": 4},
    )
    assert result["status"] == "accepted"
    assert result["memoryRevision"] == 1
    receipt = service.get_research_write_receipt(result["writeReceiptRef"])
    assert receipt is not None
    assert receipt["createAuthorizing"] is False
    assert receipt["writtenMapping"][0]["recordId"] == result["deepRecordWrite"]["recordIds"][0]

    replay = service.accept_research_unit(
        run_ref="research-run:test",
        sample_id="case:v3",
        accept_attempt_key="raa-test",
        packet_safe_hash="packet-safe-hash",
        canonical_review_hash="review-hash",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload=deep,
        edge_payload={"schema_version": 4},
    )
    assert replay["idempotentReplay"] is True
    con = service.db_path and research_memory.mature_learning.connect(service.db_path)
    assert con is not None
    try:
        assert research_runtime.get_memory_revision(con) == 1
    finally:
        con.close()


def test_legacy_backfill_fails_closed_when_v3_or_local_lanes_exist(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    service.accept_research_unit(
        run_ref="research-run:backfill-guard",
        sample_id="case:v3",
        accept_attempt_key="raa-backfill-guard",
        packet_safe_hash="packet-backfill-guard",
        canonical_review_hash="review-backfill-guard",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [_record()]},
        edge_payload={"schema_version": 4},
    )

    result = service.backfill_deep_research_knowledge(force=True)
    assert result["status"] == "blocked_scope_unsafe"
    assert result["recordCount"] == 1


@pytest.mark.parametrize(
    "fault_step", ["begin", "pattern", "deep_record", "semantic_edge", "receipt"]
)
def test_acceptance_fault_before_commit_rolls_back_the_whole_unit(tmp_path, fault_step) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    with pytest.raises(RuntimeError, match="injected_research_acceptance_fault"):
        service.accept_research_unit(
            run_ref="research-run:fault",
            sample_id="case:fault",
            accept_attempt_key="raa-fault",
            packet_safe_hash="packet-fault",
            canonical_review_hash="review-fault",
            contract_version="phase4-safe-review-v3",
            expected_origin_state="claimed",
            pattern_payload={"schema_version": 4},
            deep_payload={"schema_version": 6, "deep_research_records": [_record()]},
            edge_payload={"schema_version": 4},
            _fault_after_step=fault_step,
        )
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_record_write_receipts").fetchone()[0] == 0
        assert research_runtime.get_memory_revision(con) == 0
    finally:
        con.close()


def test_acceptance_fault_after_commit_replays_one_receipt_and_one_revision(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    kwargs = {
        "run_ref": "research-run:commit-fault",
        "sample_id": "case:commit-fault",
        "accept_attempt_key": "raa-commit-fault",
        "packet_safe_hash": "packet-commit-fault",
        "canonical_review_hash": "review-commit-fault",
        "contract_version": "phase4-safe-review-v3",
        "expected_origin_state": "claimed",
        "pattern_payload": {"schema_version": 4},
        "deep_payload": {"schema_version": 6, "deep_research_records": [_record()]},
        "edge_payload": {"schema_version": 4},
    }
    with pytest.raises(RuntimeError, match="injected_research_acceptance_fault:commit"):
        service.accept_research_unit(**kwargs, _fault_after_step="commit")
    replay = service.accept_research_unit(**kwargs)
    assert replay["idempotentReplay"] is True
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM research_record_write_receipts").fetchone()[0] == 1
        assert research_runtime.get_memory_revision(con) == 1
    finally:
        con.close()


def test_ledger_finalizer_can_recreate_exact_missing_row_idempotently(tmp_path) -> None:
    ledger = tmp_path / "intake.sqlite"
    first = research_intake_ledger.finalize_accepted(
        ledger,
        league="test-league",
        character_ref="character-hash:0123456789abcdef",
        source_hash="source-hash:test",
        sample_id="case:test",
    )
    second = research_intake_ledger.finalize_accepted(
        ledger,
        league="test-league",
        character_ref="character-hash:0123456789abcdef",
        source_hash="source-hash:test",
        sample_id="case:test",
    )
    assert first == "recreated"
    assert second == "already_accepted"


def test_same_knowledge_key_is_canonicalized_independently_per_scope(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    local = _record()
    local["source_case_refs"] = ["source-hash:shared"]
    global_record = deepcopy(local)
    global_record["knowledge_scope"] = "global_seed"
    global_record["safe_evidence_refs"] = ["safe:global"]
    local_result = service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [local]}
    )
    global_result = service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [global_record]}
    )
    assert local_result["knowledgeKeys"] == global_result["knowledgeKeys"]
    assert local_result["recordIds"] != global_result["recordIds"]
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        rows = con.execute(
            "SELECT knowledge_scope, knowledge_key, projection_hash "
            "FROM deep_research_records ORDER BY knowledge_scope"
        ).fetchall()
        assert [row["knowledge_scope"] for row in rows] == ["global_seed", "local_user"]
        assert len({row["knowledge_key"] for row in rows}) == 1
        assert all(row["projection_hash"] for row in rows)
        assert con.execute(
            "SELECT count(*) FROM research_source_provenance "
            "WHERE source_case_ref = 'source-hash:shared'"
        ).fetchone()[0] == 2
    finally:
        con.close()


def test_local_source_hash_does_not_mark_public_source_as_studied(tmp_path, monkeypatch) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    local = _record()
    local["source_case_refs"] = ["source-hash:sharedpublic"]
    service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [local]}
    )
    monkeypatch.setattr(
        research_memory.mature_learning,
        "mature_learning_path",
        lambda: service.db_path,
    )
    assert "sharedpublic" not in research_mature_builds._studied_source_hashes()

    public = deepcopy(local)
    public["knowledge_scope"] = "global_seed"
    public["safe_evidence_refs"] = ["safe:public"]
    service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [public]}
    )
    assert "sharedpublic" in research_mature_builds._studied_source_hashes()


def test_local_family_expansion_never_relocates_global_records(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    global_record = _record()
    global_record["knowledge_scope"] = "global_seed"
    global_record["source_case_refs"] = ["case:global"]
    global_record["safe_evidence_refs"] = ["safe:global"]
    global_write = service.accept_research_unit(
        run_ref="research-run:global",
        sample_id="case:global",
        accept_attempt_key="raa-global",
        packet_safe_hash="packet-global",
        canonical_review_hash="review-global",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [global_record]},
        edge_payload={"schema_version": 4},
    )
    local_record = deepcopy(_record())
    local_record["knowledge_scope"] = "local_user"
    local_record["source_case_refs"] = ["case:local"]
    local_record["safe_evidence_refs"] = ["safe:local"]
    local_record["component_keys"].append("skill:MetaCastOnCritPlayer")
    local_record["component_mentions"].append(
        {
            "candidate_name": "Cast on Critical",
            "role": "primary_damage",
            "resolver_query": "skill:MetaCastOnCritPlayer",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:MetaCastOnCritPlayer",
            "resolution_status": "resolved",
        }
    )
    local_write = service.accept_research_unit(
        run_ref="research-run:local",
        sample_id="case:local",
        accept_attempt_key="raa-local",
        packet_safe_hash="packet-local",
        canonical_review_hash="review-local",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [local_record]},
        edge_payload={"schema_version": 4},
    )
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        rows = con.execute(
            "SELECT knowledge_scope, build_family_key FROM deep_research_records "
            "ORDER BY knowledge_scope"
        ).fetchall()
        assert [(row["knowledge_scope"], row["build_family_key"]) for row in rows] == [
            ("global_seed", global_write["deepRecordWrite"]["buildFamilyKeys"][0]),
            ("local_user", local_write["deepRecordWrite"]["buildFamilyKeys"][0]),
        ]
        assert rows[0]["build_family_key"] != rows[1]["build_family_key"]
    finally:
        con.close()


def test_schema5_family_scope_repair_fails_closed_on_legacy_cross_scope_mount(tmp_path) -> None:
    db_path = tmp_path / "memory.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path, graph_service=_graph_service()
    )
    global_record = _record()
    global_record["knowledge_scope"] = "global_seed"
    global_record["source_case_refs"] = ["case:global"]
    global_record["safe_evidence_refs"] = ["safe:global"]
    service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [global_record]}
    )
    local_record = deepcopy(_record())
    local_record["knowledge_scope"] = "local_user"
    local_record["source_case_refs"] = ["case:local"]
    local_record["safe_evidence_refs"] = ["safe:local"]
    local_record["component_keys"].append("skill:MetaCastOnCritPlayer")
    local_record["component_mentions"].append(
        {
            "candidate_name": "Cast on Critical",
            "role": "primary_damage",
            "resolver_query": "skill:MetaCastOnCritPlayer",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:MetaCastOnCritPlayer",
            "resolution_status": "resolved",
        }
    )
    local = service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [local_record]}
    )
    polluted_family_key = local["buildFamilyKeys"][0]

    con = sqlite3.connect(db_path)
    try:
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("DROP TABLE research_build_family_evidence")
        con.execute("ALTER TABLE research_build_families RENAME TO scoped_families_fixture")
        con.execute(
            """
            CREATE TABLE research_build_families (
                build_family_key TEXT PRIMARY KEY,
                ascendancy_key TEXT NOT NULL,
                primary_skill_key TEXT NOT NULL,
                primary_skill_keys TEXT NOT NULL DEFAULT '[]',
                secondary_skill_keys TEXT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO research_build_families
            SELECT build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys,
                   secondary_skill_keys, evidence_count, created_at, last_seen_at
            FROM scoped_families_fixture
            WHERE knowledge_scope = 'local_user' AND build_family_key = ?
            """,
            (polluted_family_key,),
        )
        con.execute("DROP TABLE scoped_families_fixture")
        con.execute(
            """
            CREATE TABLE research_build_family_evidence (
                build_family_key TEXT NOT NULL,
                source_case_ref TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (build_family_key, source_case_ref)
            )
            """
        )
        con.execute(
            "UPDATE deep_research_records SET build_family_key = ?",
            (polluted_family_key,),
        )
        con.commit()
    finally:
        con.close()

    research_memory.mature_learning.initialize_store(db_path)
    con = research_memory.mature_learning.connect(db_path)
    try:
        assert con.execute(
            "SELECT 1 FROM research_build_families "
            "WHERE knowledge_scope = 'global_seed' AND build_family_key = ?",
            (polluted_family_key,),
        ).fetchone() is None
        assert con.execute(
            "SELECT status FROM deep_research_records WHERE knowledge_scope = 'global_seed'"
        ).fetchone()[0] == "needs_revalidation"
        assert con.execute(
            "SELECT 1 FROM research_build_families "
            "WHERE knowledge_scope = 'local_user' AND build_family_key = ?",
            (polluted_family_key,),
        ).fetchone() is not None
    finally:
        con.close()


def test_schema5_single_scope_family_requires_one_exact_identity_witness(tmp_path) -> None:
    db_path = tmp_path / "single-scope-residual.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path, graph_service=_graph_service()
    )
    written = service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [_record()]}
    )
    family_key = written["buildFamilyKeys"][0]
    con = research_memory.mature_learning.connect(db_path)
    try:
        con.execute(
            "UPDATE research_build_families SET primary_skill_keys = ? "
            "WHERE knowledge_scope = 'local_user' AND build_family_key = ?",
            (json.dumps(["skill:CometPlayer", "skill:MetaCastOnCritPlayer"]), family_key),
        )
        con.commit()
    finally:
        con.close()
    _make_family_tables_unscoped(
        db_path,
        knowledge_scope="local_user",
        family_key=family_key,
    )

    research_memory.mature_learning.initialize_store(db_path)
    con = research_memory.mature_learning.connect(db_path)
    try:
        assert con.execute(
            "SELECT 1 FROM research_build_families "
            "WHERE knowledge_scope = 'local_user' AND build_family_key = ?",
            (family_key,),
        ).fetchone() is None
        assert con.execute(
            "SELECT status FROM deep_research_records WHERE knowledge_scope = 'local_user'"
        ).fetchone()[0] == "needs_revalidation"
    finally:
        con.close()


def test_schema5_family_keeps_contained_case_when_exact_witness_exists(tmp_path) -> None:
    db_path = tmp_path / "single-scope-exact-witness.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path, graph_service=_graph_service()
    )
    subset = _record()
    subset["research_group_id"] = "research:case:subset"
    subset["source_case_refs"] = ["case:subset"]
    subset["safe_evidence_refs"] = ["safe:subset"]
    service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [subset]}
    )

    exact = deepcopy(_record())
    exact["research_group_id"] = "research:case:exact"
    exact["source_case_refs"] = ["case:exact"]
    exact["safe_evidence_refs"] = ["safe:exact"]
    exact["typed_payload"]["gearSubjects"] = ["body_armour"]
    exact["component_keys"].append("skill:MetaCastOnCritPlayer")
    exact["component_mentions"].append(
        {
            "candidate_name": "Cast on Critical",
            "role": "primary_damage",
            "resolver_query": "skill:MetaCastOnCritPlayer",
            "expected_node_types": ["active_skill"],
            "scope": "player",
            "component_key": "skill:MetaCastOnCritPlayer",
            "resolution_status": "resolved",
        }
    )
    expanded = service.propose_deep_research_records(
        {"schema_version": 6, "deep_research_records": [exact]}
    )
    family_key = expanded["buildFamilyKeys"][0]
    _make_family_tables_unscoped(
        db_path,
        knowledge_scope="local_user",
        family_key=family_key,
    )

    research_memory.mature_learning.initialize_store(db_path)
    con = research_memory.mature_learning.connect(db_path)
    try:
        assert con.execute(
            "SELECT 1 FROM research_build_families "
            "WHERE knowledge_scope = 'local_user' AND build_family_key = ?",
            (family_key,),
        ).fetchone() is not None
        assert {
            row[0]
            for row in con.execute(
                "SELECT status FROM deep_research_records WHERE knowledge_scope = 'local_user'"
            ).fetchall()
        } == {"valid"}
    finally:
        con.close()

def test_missing_source_provenance_disables_create_and_receipt_lane(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    accepted = service.accept_research_unit(
        run_ref="research-run:provenance",
        sample_id="case:v3",
        accept_attempt_key="raa-provenance",
        packet_safe_hash="packet-provenance",
        canonical_review_hash="review-provenance",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [_record()]},
        edge_payload={"schema_version": 4},
    )
    family_key = accepted["deepRecordWrite"]["buildFamilyKeys"][0]
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        con.execute("DELETE FROM research_source_provenance")
        con.commit()
    finally:
        con.close()
    queried = service.query_research_memory(
        "",
        response_profile="create_compact",
        build_family_keys=[family_key],
        knowledge_scope="local_user",
        source_case_ref="case:v3",
    )
    assert queried["selectedSourceCaseRef"] is None
    assert queried["deepResearchRecords"] == []
    receipt = service.get_research_write_receipt(accepted["writeReceiptRef"])
    assert receipt is not None
    assert receipt["currentProjection"][0]["currentEligibility"] is False
    assert receipt["currentProjection"][0]["currentExclusionReasons"] == [
        "source_provenance"
    ]


def test_identical_supplement_is_no_gain_without_revision_or_receipt(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    common = {
        "sample_id": "case:v3",
        "packet_safe_hash": "packet-no-gain",
        "canonical_review_hash": "review-no-gain",
        "contract_version": "phase4-safe-review-v3",
        "expected_origin_state": "claimed",
        "pattern_payload": {"schema_version": 4},
        "deep_payload": {"schema_version": 6, "deep_research_records": [_record()]},
        "edge_payload": {"schema_version": 4},
    }
    first = service.accept_research_unit(
        run_ref="research-run:first", accept_attempt_key="raa-first", **common
    )
    second = service.accept_research_unit(
        run_ref="research-run:supplement",
        accept_attempt_key="raa-supplement",
        supplement=True,
        **common,
    )
    assert first["memoryRevision"] == 1
    assert second["errorCode"] == "supplement_no_gain"
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert research_runtime.get_memory_revision(con) == 1
        assert con.execute("SELECT count(*) FROM research_record_write_receipts").fetchone()[0] == 1
    finally:
        con.close()


def test_projection_hash_and_state_gate_create_lane_records(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    records = []
    for subject, state in (
        ("helmet", "state_agnostic"),
        ("gloves", "active_state"),
        ("boots", "alternate_weapon_state"),
        ("ring", "unknown"),
    ):
        record = deepcopy(_record())
        record["title"] = f"{subject} budget"
        record["summary"] = f"{subject} summary"
        record["content"] = f"{subject} 承担当前案例的装备职责。"
        record["typed_payload"]["gearSubjects"] = [subject]
        record["source_state_scope"] = state
        records.append(record)
    accepted = service.accept_research_unit(
        run_ref="research-run:states",
        sample_id="case:v3",
        accept_attempt_key="raa-states",
        packet_safe_hash="packet-states",
        canonical_review_hash="review-states",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": records},
        edge_payload={"schema_version": 4},
    )
    family_key = accepted["deepRecordWrite"]["buildFamilyKeys"][0]
    result = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        detail_level="record",
        response_profile="create_compact",
        knowledge_scope="local_user",
        source_case_ref="case:v3",
    )
    assert {item["title"] for item in result["deepResearchRecords"]} == {
        "helmet budget",
        "gloves budget",
    }
    coverage = result["familyRecordCoverage"][0]
    assert coverage["storedRecordCount"] == 4
    assert coverage["eligibleRecordCount"] == 2
    assert coverage["excludedRecordCount"] == 2
    assert coverage["exclusionReasonCounts"] == {"source_state": 2}
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        mismatches = con.execute(
            """
            SELECT count(*)
            FROM deep_research_record_evidence AS evidence
            JOIN deep_research_records AS record
              ON record.knowledge_scope = evidence.knowledge_scope
             AND record.knowledge_key = evidence.knowledge_key
            WHERE evidence.accepted_projection_hash <> record.projection_hash
               OR evidence.accepted_projection_hash IS NULL
            """
        ).fetchone()[0]
        assert mismatches == 0
    finally:
        con.close()


def test_create_query_uses_one_source_lane_and_bounded_session(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    accepted = service.accept_research_unit(
        run_ref="research-run:lane",
        sample_id="case:v3",
        accept_attempt_key="raa-lane",
        packet_safe_hash="packet-lane",
        canonical_review_hash="review-lane",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [_record()]},
        edge_payload={"schema_version": 4},
    )
    family_key = accepted["deepRecordWrite"]["buildFamilyKeys"][0]
    raw = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        detail_level="record",
        response_profile="create_compact",
        source_case_ref="case:v3",
        knowledge_scope="local_user",
        run_ref="generation-run:lane",
    )
    compact = main._compact_create_research_response(raw)
    first = service.start_retrieval_session(
        compact,
        response_profile="create_compact",
        run_ref="generation-run:lane",
        claim_ref=None,
    )
    assert first["selectedKnowledgeScope"] == "local_user"
    assert first["selectedSourceCaseRef"] == "case:v3"
    assert first["deepResearchRecords"]
    assert len(str(first).encode("utf-8")) < 65_536
    receipt = service.read_query_receipt(first["dedupeQueryRef"])
    assert receipt is not None
    usage = {
        "retrievalOutcome": "matched",
        "dedupeQueryRefs": [first["dedupeQueryRef"]],
        "buildFamilyKeys": [family_key],
        "deepRecordIds": [first["deepResearchRecords"][0]["recordId"]],
        "selectedKnowledgeScope": "local_user",
        "selectedSourceCaseRef": "case:v3",
        "insightDecisions": [
            {
                "sourceRefs": [first["deepResearchRecords"][0]["recordId"]],
                "decision": "adopted",
                "summary": "Verified single-lane knowledge.",
                "application": "Use the verified case lane.",
            }
        ],
    }
    error, summary, _ = progression_provenance.validate_research_use_receipts(
        research_memory_use=usage,
        receipt_reader=service.read_query_receipt,
    )
    assert error is None
    assert summary is not None


def test_create_lane_scoring_applies_version_filters_before_ranking(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    old_records = []
    for subject, title in (("helmet", "old helmet"), ("gloves", "old gloves")):
        record = deepcopy(_record())
        record["title"] = title
        record["summary"] = title
        record["content"] = title
        record["source_case_refs"] = ["case:old"]
        record["safe_evidence_refs"] = [f"safe:{subject}"]
        record["game_patch"] = "0.4.0"
        record["typed_payload"] = {
            "gearResponsibilities": [],
            "gearSubjects": [subject],
        }
        old_records.append(record)
    old = service.accept_research_unit(
        run_ref="research-run:old-lane",
        sample_id="case:old",
        accept_attempt_key="raa-old-lane",
        packet_safe_hash="packet-old-lane",
        canonical_review_hash="review-old-lane",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": old_records},
        edge_payload={"schema_version": 4},
    )
    current_record = deepcopy(_record())
    current_record["title"] = "current boots"
    current_record["summary"] = "current boots"
    current_record["content"] = "current boots"
    current_record["source_case_refs"] = ["case:current"]
    current_record["safe_evidence_refs"] = ["safe:current"]
    current_record["typed_payload"] = {
        "gearResponsibilities": [],
        "gearSubjects": ["boots"],
    }
    current = service.accept_research_unit(
        run_ref="research-run:current-lane",
        sample_id="case:current",
        accept_attempt_key="raa-current-lane",
        packet_safe_hash="packet-current-lane",
        canonical_review_hash="review-current-lane",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [current_record]},
        edge_payload={"schema_version": 4},
    )
    family_key = old["deepRecordWrite"]["buildFamilyKeys"][0]
    assert current["deepRecordWrite"]["buildFamilyKeys"] == [family_key]

    result = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        record_kinds=["gear_synergy", "rotation"],
        game_patch="0.5.4",
        passive_tree_version="tree-test",
        response_profile="create_compact",
        knowledge_scope="local_user",
    )

    assert result["selectedSourceCaseRef"] == "case:current"
    assert [item["title"] for item in result["deepResearchRecords"]] == ["current boots"]

    exact_result = service.query_research_memory(
        "",
        build_family_keys=[family_key],
        record_ids=[
            current["deepRecordWrite"]["recordIds"][0],
            "drr-missing-filter-fixture",
        ],
        response_profile="create_compact",
        knowledge_scope="local_user",
    )
    assert exact_result["selectedSourceCaseRef"] == "case:current"
    assert [item["title"] for item in exact_result["deepResearchRecords"]] == ["current boots"]


def test_selected_lane_does_not_authorize_another_case_family(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    first_record = _record()
    first_record["source_case_refs"] = ["case:a"]
    first_record["safe_evidence_refs"] = ["safe:a"]
    first = service.accept_research_unit(
        run_ref="research-run:lane-a",
        sample_id="case:a",
        accept_attempt_key="raa-lane-a",
        packet_safe_hash="packet-a",
        canonical_review_hash="review-a",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [first_record]},
        edge_payload={"schema_version": 4},
    )

    second_record = deepcopy(_record())
    second_record["research_group_id"] = "research:case:lane-b"
    second_record["source_case_refs"] = ["case:b"]
    second_record["safe_evidence_refs"] = ["safe:b"]
    second_record["component_keys"] = ["skill:MetaCastOnCritPlayer"]
    second_record["component_mentions"][0].update(
        {
            "candidate_name": "Cast on Critical",
            "resolver_query": "skill:MetaCastOnCritPlayer",
            "component_key": "skill:MetaCastOnCritPlayer",
        }
    )
    second = service.accept_research_unit(
        run_ref="research-run:lane-b",
        sample_id="case:b",
        accept_attempt_key="raa-lane-b",
        packet_safe_hash="packet-b",
        canonical_review_hash="review-b",
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [second_record]},
        edge_payload={"schema_version": 4},
    )
    first_family = first["deepRecordWrite"]["buildFamilyKeys"][0]
    second_family = second["deepRecordWrite"]["buildFamilyKeys"][0]

    raw = service.query_research_memory(
        "lane isolation",
        build_family_keys=[first_family, second_family],
        knowledge_scope="local_user",
        response_profile="create_compact",
    )
    assert raw["selectedSourceCaseRef"] == "case:a"
    assert [item["buildFamilyKey"] for item in raw["buildFamilies"]] == [first_family]
    page = service.start_retrieval_session(
        main._compact_create_research_response(raw),
        response_profile="create_compact",
        run_ref="generation-run:lane-isolation",
        claim_ref=None,
    )
    error, _, _ = progression_provenance.validate_research_use_receipts(
        research_memory_use={
            "retrievalOutcome": "matched",
            "dedupeQueryRefs": [page["dedupeQueryRef"]],
            "buildFamilyKeys": [second_family],
            "selectedKnowledgeScope": "local_user",
            "selectedSourceCaseRef": "case:a",
            "insightDecisions": [
                {
                    "sourceRefs": [second_family],
                    "decision": "rejected",
                    "summary": "Cross-case family must not be authorized.",
                    "application": "Ignore the unrelated family.",
                }
            ],
        },
        receipt_reader=service.read_query_receipt,
    )
    assert error == "progression_research_case_comparison_incomplete"


def test_compact_failure_premise_includes_minimal_decision_template() -> None:
    premise_id = "rp-0123456789abcdef"
    compact = main._compact_create_research_response(
        {
            "familyPremiseCatalog": [
                {
                    "premiseId": premise_id,
                    "premiseType": "failure_condition",
                    "buildFamilyKey": "bf-test",
                }
            ]
        }
    )

    assert compact["familyPremiseCatalog"][0]["decisionTemplate"] == {
        "premiseId": premise_id,
        "decision": "caveated",
        "resolutionRefs": [],
        "application": "",
        "caveat": "",
    }


def test_retrieval_session_pages_once_with_hard_byte_budget(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite")
    payload = {
        "status": "known",
        "selectedKnowledgeScope": "local_user",
        "selectedSourceCaseRef": "case:many",
        "deepResearchRecords": [
            {
                "recordId": f"drr-{index:016x}",
                "recordKind": "mechanic_chain",
                "title": f"Record {index}",
                "summary": "x" * 180,
                "content": "机制" * 900,
            }
            for index in range(80)
        ],
        "results": [],
        "buildFamilies": [],
        "semanticEdges": [],
        "buildPatterns": [],
        "transferablePatterns": [],
        "familyRecordCoverage": [],
        "familyRecordIndex": [],
        "familyPremiseCatalog": [],
        "criticalPremiseDigest": [],
        "noRawMatureBuildMaterial": True,
    }
    page = service.start_retrieval_session(
        _with_raw_compact_dq(service, payload),
        response_profile="create_compact",
        run_ref="generation-run:many",
        claim_ref=None,
    )
    ids: list[str] = []
    refs: list[str] = []
    retrieval_ref = page["retrieval"]["retrievalRef"]
    first_record_id = page["deepResearchRecords"][0]["recordId"]
    incomplete_error, _, _ = progression_provenance.validate_research_use_receipts(
        research_memory_use={
            "retrievalOutcome": "matched",
            "dedupeQueryRefs": [page["dedupeQueryRef"]],
            "deepRecordIds": [first_record_id],
            "selectedKnowledgeScope": "local_user",
            "selectedSourceCaseRef": "case:many",
            "insightDecisions": [
                {
                    "sourceRefs": [first_record_id],
                    "decision": "caveated",
                    "summary": "Only the first page was read.",
                    "application": "Do not authorize an incomplete retrieval.",
                }
            ],
        },
        receipt_reader=service.read_query_receipt,
    )
    assert incomplete_error == "progression_research_retrieval_incomplete"
    while True:
        assert len(json.dumps(page, ensure_ascii=False).encode("utf-8")) <= 65_536
        ids.extend(item["recordId"] for item in page["deepResearchRecords"])
        refs.append(page["dedupeQueryRef"])
        cursor = page["retrieval"]["nextCursor"]
        if cursor is None:
            break
        page = service.continue_retrieval_session(cursor)
        assert page["retrieval"]["retrievalRef"] == retrieval_ref
    assert ids == [f"drr-{index:016x}" for index in range(80)]

    second = service.start_retrieval_session(
        _with_raw_compact_dq(service, payload),
        response_profile="create_compact",
        run_ref="generation-run:many",
        claim_ref=None,
    )
    assert second["retrieval"]["retrievalRef"] != retrieval_ref


def test_retrieval_cursor_rejects_replay_corruption_and_stale_revision(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite")
    payload = {
        "status": "known",
        "selectedKnowledgeScope": "local_user",
        "selectedSourceCaseRef": "case:cursor",
        "deepResearchRecords": [
            {
                "recordId": f"drr-{index:016x}",
                "title": f"Record {index}",
                "content": "机制" * 4_000,
            }
            for index in range(20)
        ],
        "noRawMatureBuildMaterial": True,
    }
    first = service.start_retrieval_session(
        _with_raw_compact_dq(service, payload),
        response_profile="create_compact",
        run_ref="generation-run:cursor",
        claim_ref=None,
    )
    cursor = first["retrieval"]["nextCursor"]
    assert cursor
    bad_tail = "0" if cursor[-1] != "0" else "1"
    corrupted = service.continue_retrieval_session(cursor[:-1] + bad_tail)
    assert corrupted["errorCode"] == "invalid_research_query_cursor"
    second = service.continue_retrieval_session(cursor)
    replay = service.continue_retrieval_session(cursor)
    assert replay["errorCode"] == "research_query_continuation_out_of_order"

    stale_first = service.start_retrieval_session(
        _with_raw_compact_dq(service, payload),
        response_profile="create_compact",
        run_ref="generation-run:stale",
        claim_ref=None,
    )
    stale_cursor = stale_first["retrieval"]["nextCursor"]
    assert stale_cursor
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        research_runtime.bump_memory_revision(con)
        con.commit()
    finally:
        con.close()
    stale = service.continue_retrieval_session(stale_cursor)
    assert stale["errorCode"] == "research_query_continuation_stale"
    assert second["retrieval"]["pageIndex"] == 1


def test_retrieval_session_rejects_raw_query_from_stale_revision(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite")
    payload = _with_raw_compact_dq(
        service,
        {
            "status": "known",
            "selectedKnowledgeScope": "local_user",
            "selectedSourceCaseRef": "case:stale-raw",
            "deepResearchRecords": [],
            "noRawMatureBuildMaterial": True,
        },
    )
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        research_runtime.bump_memory_revision(con)
        con.commit()
    finally:
        con.close()
    result = service.start_retrieval_session(
        payload,
        response_profile="create_compact",
        run_ref="generation-run:stale-raw",
        claim_ref=None,
    )
    assert result["errorCode"] == "research_query_session_stale"
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_query_sessions").fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM research_dedupe_queries WHERE retrieval_ref IS NOT NULL"
        ).fetchone()[0] == 0
    finally:
        con.close()


def test_retrieval_rejects_one_oversize_atomic_item_without_receipt(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite")
    result = service.start_retrieval_session(
        _with_raw_compact_dq(service, {
            "status": "known",
            "selectedKnowledgeScope": "local_user",
            "selectedSourceCaseRef": "case:oversize",
            "deepResearchRecords": [{"recordId": "drr-oversize", "content": "机制" * 40_000}],
            "noRawMatureBuildMaterial": True,
        }),
        response_profile="create_compact",
        run_ref="generation-run:oversize",
        claim_ref=None,
    )
    assert result["errorCode"] == "memory_item_too_large"
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert con.execute(
            "SELECT count(*) FROM research_dedupe_queries WHERE retrieval_ref IS NOT NULL"
        ).fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_query_sessions").fetchone()[0] == 0
    finally:
        con.close()


def test_retrieval_rejects_later_oversize_item_before_first_page(tmp_path) -> None:
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "memory.sqlite")
    result = service.start_retrieval_session(
        _with_raw_compact_dq(service, {
            "status": "known",
            "selectedKnowledgeScope": "local_user",
            "selectedSourceCaseRef": "case:oversize-later",
            "deepResearchRecords": [
                {"recordId": "drr-small", "content": "small"},
                {"recordId": "drr-oversize", "content": "x" * 70_000},
            ],
            "noRawMatureBuildMaterial": True,
        }),
        response_profile="create_compact",
        run_ref="generation-run:oversize-later",
        claim_ref=None,
    )
    assert result["errorCode"] == "memory_item_too_large"
    con = research_memory.mature_learning.connect(service.db_path)
    try:
        assert con.execute(
            "SELECT count(*) FROM research_dedupe_queries WHERE retrieval_ref IS NOT NULL"
        ).fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_query_sessions").fetchone()[0] == 0
    finally:
        con.close()


def test_accepting_queue_recovers_from_committed_final_receipt(tmp_path) -> None:
    memory_path = tmp_path / "memory.sqlite"
    queue_db = tmp_path / "queue.sqlite"
    output_root = tmp_path / "run"
    output_root.mkdir()
    research_mature_builds._init_db(queue_db)
    research_mature_builds._write_metadata(
        queue_db,
        {
            "runId": "recover",
            "currentPatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobVersionOrCommit": "0.22.0",
            "versionContextStatus": "verified",
        },
    )
    now = datetime.now(tz=UTC).isoformat()
    lease_token = "lease-recover"
    packet_safe_hash = "packet-recover"
    review_relative = research_mature_builds._suggested_review_file(
        output_dir=output_root,
        sample_id="case:recover",
        lease_token=lease_token,
    )
    review_path = output_root / review_relative
    review_path.parent.mkdir(parents=True)
    review = {
        "reportId": "poe_bd_research_review",
        "reviewContractVersion": "phase4-safe-review-v3",
        "safeArtifactOnly": True,
        "artifactIdentity": {
            "sampleId": "case:recover",
            "caseRef": "source-hash:recover",
            "safeEvidenceRef": f"evidence:{packet_safe_hash[:16]}",
            "packetSafeHash": packet_safe_hash,
        },
        "knowledgeScope": "global_seed",
        "memoryUse": {"queries": []},
        "sourceSkillGroupReviews": [],
        "pobReadbackAudit": [],
        "deepResearchRecords": [{"title": "recovery fixture"}],
        "candidateReviews": [],
        "semanticEdges": [],
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    canonical_review = research_mature_builds._canonical_review_artifact_identity(
        review_file=review_path,
        sample_id="case:recover",
        source_hash_ref="source-hash:recover",
        packet_safe_hash=packet_safe_hash,
        version_context=research_mature_builds._queue_version_context(queue_db),
    )
    canonical_review_hash = research_runtime.stable_hash(canonical_review)
    attempt_key = research_runtime.accept_attempt_key(
        run_id="recover",
        sample_id="case:recover",
        packet_safe_hash=packet_safe_hash,
        canonical_review_hash=canonical_review_hash,
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
    )
    service = research_memory.ResearchMemoryService(
        db_path=memory_path, graph_service=_graph_service()
    )
    service.accept_research_unit(
        run_ref="research-run:recover",
        sample_id="case:recover",
        accept_attempt_key=attempt_key,
        packet_safe_hash=packet_safe_hash,
        canonical_review_hash=canonical_review_hash,
        contract_version="phase4-safe-review-v3",
        expected_origin_state="claimed",
        pattern_payload={"schema_version": 4},
        deep_payload={"schema_version": 6, "deep_research_records": [_record()]},
        edge_payload={"schema_version": 4},
    )
    with sqlite3.connect(queue_db) as con:
        con.execute(
            """
            INSERT INTO cases(
                sample_id,status,source_type,source_hash,source_hash_ref,character_ref,
                league,level,class_name,ascendancy,main_skill,safe_error,packet_id,
                packet_safe_hash,created_at,updated_at,lease_token,lease_owner,
                lease_expires_at,accept_attempt_key,accept_origin_state,finalization_status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "case:recover",
                "accepting",
                "poe_ninja_import_code",
                "source-recover",
                "source-hash:recover",
                "",
                "test",
                98,
                "Witch",
                "Blood Mage",
                "Comet",
                "",
                "packet-id",
                packet_safe_hash,
                now,
                now,
                lease_token,
                "worker",
                now,
                attempt_key,
                "claimed",
                "",
            ),
        )
        con.commit()
    recovered = research_mature_builds.accept_case(
        queue_db_path=queue_db,
        lease_token=lease_token,
        review_file=review_path,
        output_dir=output_root,
        memory_db_path=memory_path,
        intake_ledger_path=tmp_path / "unused-ledger.sqlite",
    )
    assert recovered is not None
    assert recovered["status"] == "accepted"
    with sqlite3.connect(queue_db) as con:
        assert (
            con.execute("SELECT status FROM cases WHERE sample_id = 'case:recover'").fetchone()[0]
            == "accepted"
        )

    replay = research_mature_builds.accept_case(
        queue_db_path=queue_db,
        lease_token=lease_token,
        review_file=review_path,
        output_dir=output_root,
        memory_db_path=memory_path,
        intake_ledger_path=tmp_path / "unused-ledger.sqlite",
    )
    assert replay is not None
    assert replay["responseReplay"] is True

    changed_review = {**review, "pobReadbackAudit": [{"disposition": "unavailable"}]}
    review_path.write_text(json.dumps(changed_review), encoding="utf-8")
    with pytest.raises(ValueError, match="review hash"):
        research_mature_builds.accept_case(
            queue_db_path=queue_db,
            lease_token=lease_token,
            review_file=review_path,
            output_dir=output_root,
            memory_db_path=memory_path,
            intake_ledger_path=tmp_path / "unused-ledger.sqlite",
        )
