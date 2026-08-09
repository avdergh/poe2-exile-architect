from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

from server.knowledge import mature_learning
from server.knowledge import graph_tools
from server.knowledge import physical_graph
from server.knowledge import research_maintenance
from server.knowledge import research_memory


def _fragment_payload(*, summary: str, components: list[str]) -> dict[str, object]:
    return {
        "schema_version": 4,
        "fragments": [
            {
                "fragment_type": "mechanism_pattern",
                "title": "Crossbow Shot mature sample: ammo rotation",
                "summary": summary,
                "reusable_principle": summary,
                "source_case_refs": ["case:legacy-crossbow"],
                "safe_evidence_refs": [f"safe:{summary}"],
                "confidence": "medium",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_budget"],
                "modelability": "partial",
                "verification_tasks": ["Judge the rotation."],
                "component_keys": components,
                "conditions": ["ammo available"],
                "risks": ["rotation stalls"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "0.22.0",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "semantic_edges": [],
    }


def _deep_payload() -> dict[str, object]:
    return {
        "schema_version": 5,
        "deep_research_records": [
            {
                "research_group_id": "research:legacy-familyless",
                "record_kind": "mechanic_chain",
                "title": "Legacy familyless chain",
                "summary": "A useful but unclassified historical observation.",
                "content": "The historical record lacks enough identity evidence for a BuildFamily.",
                "content_language": "en",
                "length_exception_reason": None,
                "component_keys": ["skill:LegacyPlayer"],
                "component_mentions": [],
                "source_case_refs": ["source-hash:legacy"],
                "safe_evidence_refs": ["safe:legacy"],
                "conditions": ["historical sample"],
                "failure_conditions": ["identity unresolved"],
                "typed_payload": {},
                "class_key": None,
                "ascendancy_key": None,
                "extraction_method_version": "deep_research_mvp_v1",
                "record_schema_version": 1,
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "0.22.0",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def _graph_service() -> graph_tools.GraphQueryService:
    source = physical_graph.GraphSource(
        source_id="fixture:legacy-cleanup",
        kind="test_fixture",
        source_file="tests/test_research_maintenance.py",
        claims=(physical_graph.SourceClaim("passive_tree_version", "0_5"),),
    )
    snapshot = physical_graph.GraphSnapshot(
        snapshot_id="snapshot:legacy-cleanup",
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
        sources=(source,),
        nodes=(
            physical_graph.GraphNode(
                "skill:LegacyPlayer",
                "active_skill",
                "Legacy",
                (source.source_id,),
            ),
            physical_graph.GraphNode(
                "ascendancy:sorceress:stormweaver",
                "ascendancy",
                "Stormweaver",
                (source.source_id,),
            ),
            physical_graph.GraphNode(
                "skill:SparkPlayer", "active_skill", "Spark", (source.source_id,)
            ),
            physical_graph.GraphNode(
                "skill:MetaCastOnCritPlayer",
                "active_skill",
                "Cast on Critical",
                (source.source_id,),
            ),
            physical_graph.GraphNode(
                "skill:CometPlayer", "active_skill", "Comet", (source.source_id,)
            ),
            *(
                physical_graph.GraphNode(key, "support_gem", name, (source.source_id,))
                for key, name in (
                    (
                        "support:Metadata/Items/Gem/SupportGemConsideredCasting",
                        "Considered Casting",
                    ),
                    (
                        "support:Metadata/Items/Gems/SupportGemArcaneTempoTwo",
                        "Rapid Casting II",
                    ),
                    (
                        "support:Metadata/Items/Gems/SupportGemPinpointCritical",
                        "Pinpoint Critical",
                    ),
                    (
                        "support:Metadata/Items/Gem/SupportGemFluke",
                        "Fluke",
                    ),
                    (
                        "support:Metadata/Items/Gems/SupportGemColdMastery",
                        "Cold Mastery",
                    ),
                    (
                        "support:Metadata/Items/Gems/SupportGemInspirationTwo",
                        "Efficiency II",
                    ),
                    (
                        "support:Metadata/Items/Gems/SupportGemAccelerationTwo",
                        "Projectile Acceleration II",
                    ),
                )
            ),
            physical_graph.GraphNode(
                "unique:pob:rathpith_globe",
                "unique",
                "Rathpith Globe",
                (source.source_id,),
            ),
        ),
        edges=(),
    )
    return graph_tools.GraphQueryService.from_snapshot(snapshot)


def test_legacy_cleanup_is_dry_run_backed_up_and_idempotent(tmp_path: Path):
    db_path = tmp_path / "mature.sqlite"
    backup_path = tmp_path / "mature.backup.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    for index, components in enumerate(([], ["skill:LegacyPlayer"])):
        query_ref = service.query_research_memory(f"legacy-{index}")["dedupeQueryRef"]
        result = service.propose_research_fragments(
            _fragment_payload(summary=f"legacy summary {index}", components=components),
            dedupe_query_ref=query_ref,
        )
        assert result["status"] == "accepted"
    assert service.propose_deep_research_records(_deep_payload())["status"] == "accepted"

    planned = research_maintenance.cleanup_legacy_research_memory(db_path=db_path)
    assert planned["status"] == "planned"
    assert planned["fragmentSupersessionCount"] == 1
    assert planned["quarantinedDeepRecordCount"] == 1
    assert not backup_path.exists()

    applied = research_maintenance.cleanup_legacy_research_memory(
        db_path=db_path,
        apply=True,
        backup_path=backup_path,
    )
    assert applied["status"] == "applied"
    assert applied["physicalDeleteCount"] == 0
    assert backup_path.exists()

    con = mature_learning.connect(db_path)
    try:
        assert (
            con.execute(
                "SELECT count(*) FROM research_fragments WHERE status = 'deprecated'"
            ).fetchone()[0]
            == 1
        )
        row = con.execute("SELECT visibility, split, status FROM deep_research_records").fetchone()
        assert tuple(row) == ("quarantined", "quarantine", "quarantined")
        marker = con.execute(
            "SELECT value FROM meta WHERE key = ?",
            (research_maintenance.LEGACY_CLEANUP_MARKER,),
        ).fetchone()
        assert json.loads(marker[0])["quarantinedDeepRecordCount"] == 1
    finally:
        con.close()

    repeated = research_maintenance.cleanup_legacy_research_memory(
        db_path=db_path,
        apply=True,
    )
    assert repeated["status"] == "already_applied"


def test_research_contract_calibration_is_backed_up_and_idempotent(tmp_path: Path):
    db_path = tmp_path / "mature.sqlite"
    backup_path = tmp_path / "mature.backup.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    source_ref = "source-hash:9dcc40c506855f93"
    support_rows = [
        (
            "Considered Casting",
            "support:Metadata/Items/Gem/SupportGemConsideredCasting",
        ),
        (
            "Rapid Casting II",
            "support:Metadata/Items/Gems/SupportGemArcaneTempoTwo",
        ),
        (
            "Pinpoint Critical",
            "support:Metadata/Items/Gems/SupportGemPinpointCritical",
        ),
        ("Fluke", "support:Metadata/Items/Gem/SupportGemFluke"),
        (
            "Cold Mastery",
            "support:Metadata/Items/Gems/SupportGemColdMastery",
        ),
        (
            "Efficiency II",
            "support:Metadata/Items/Gems/SupportGemInspirationTwo",
        ),
    ]
    mentions = [
        _mention("Spark", "primary_damage", "skill:SparkPlayer", "active_skill"),
        _mention(
            "Cast on Critical",
            "trigger_host",
            "skill:MetaCastOnCritPlayer",
            "active_skill",
        ),
        _mention("Comet", "triggered_payload", "skill:CometPlayer", "active_skill"),
        *[_mention(name, "support_modifier", key, "support_gem") for name, key in support_rows],
    ]
    skill_payload = _deep_payload()
    skill = skill_payload["deep_research_records"][0]
    skill.update(
        {
            "research_group_id": "research:case:poe-bd-research-9dcc40c506855f93",
            "record_kind": "skill_package",
            "title": "Spark 暴击触发 Comet 技能包",
            "summary": "Spark 与 CoC-Comet 的旧辅助记录。",
            "content": "旧记录有具体辅助，但还没有结构化辅助归属。",
            "content_language": "zh-CN",
            "component_keys": [item["component_key"] for item in mentions],
            "component_mentions": mentions,
            "source_case_refs": [source_ref],
            "safe_evidence_refs": ["evidence:fixture"],
            "typed_payload": {
                "familyCoreSkillKeys": ["skill:MetaCastOnCritPlayer"],
                "supportPackages": [
                    {
                        "skillKey": "skill:MetaCastOnCritPlayer",
                        "supportKeys": [key for _name, key in support_rows],
                    }
                ],
            },
            "ascendancy_key": "ascendancy:sorceress:stormweaver",
        }
    )
    skill_result = service.propose_deep_research_records(skill_payload)
    assert skill_result["status"] == "accepted", skill_result
    # The public proposal contract now rejects this historical shape. Seed a valid record first,
    # then remove the field in storage so the maintenance test still exercises a true legacy row.
    legacy_con = mature_learning.connect(db_path)
    try:
        legacy_con.execute(
            """
            UPDATE deep_research_records
            SET typed_payload = ?
            WHERE record_kind = 'skill_package'
              AND status = 'valid'
            """,
            (json.dumps({"familyCoreSkillKeys": ["skill:MetaCastOnCritPlayer"]}),),
        )
        legacy_con.commit()
    finally:
        legacy_con.close()

    mutated_payload = _deep_payload()
    mutated = mutated_payload["deep_research_records"][0]
    mutated_mentions = [
        _mention("Spark", "primary_damage", "skill:SparkPlayer", "active_skill"),
        _mention(
            "Rathpith Globe",
            "unique_enabler",
            "unique:pob:rathpith_globe",
            "unique",
        ),
    ]
    mutated.update(
        {
            "research_group_id": "research:case:poe-bd-research-6b65a3b2bfcc639f",
            "record_kind": "gear_synergy",
            "title": "Rathpith instance-specific role",
            "summary": "A source-specific item instance changes the case.",
            "content": "The source-specific item instance must not become generic advice.",
            "component_keys": [item["component_key"] for item in mutated_mentions],
            "component_mentions": mutated_mentions,
            "source_case_refs": ["source-hash:6b65a3b2bfcc639f"],
            "safe_evidence_refs": ["evidence:fixture"],
            "ascendancy_key": "ascendancy:sorceress:stormweaver",
        }
    )
    assert service.propose_deep_research_records(mutated_payload)["status"] == "accepted"

    planned = research_maintenance.calibrate_research_contract_v1(db_path=db_path)
    assert planned["status"] == "planned"
    assert planned["supportPackageRecordCount"] == 1
    assert planned["sourceSpecificRandomRecordCount"] == 1

    applied = research_maintenance.calibrate_research_contract_v1(
        db_path=db_path,
        apply=True,
        backup_path=backup_path,
    )
    assert applied["status"] == "applied"
    assert backup_path.exists()
    con = mature_learning.connect(db_path)
    try:
        skill_row = con.execute(
            """
            SELECT typed_payload FROM deep_research_records
            WHERE record_kind = 'skill_package' AND status = 'valid'
            """
        ).fetchone()
        packages = json.loads(skill_row["typed_payload"])["supportPackages"]
        assert any(
            "support:Metadata/Items/Gems/SupportGemAccelerationTwo" in package["supportKeys"]
            for package in packages
        )
        mutated_row = con.execute(
            """
            SELECT typed_payload FROM deep_research_records
            WHERE record_kind = 'gear_synergy' AND status = 'valid'
            """
        ).fetchone()
        assert json.loads(mutated_row["typed_payload"])["availability"] == (
            "source_specific_random"
        )
    finally:
        con.close()

    repeated = research_maintenance.calibrate_research_contract_v1(
        db_path=db_path,
        apply=True,
    )
    assert repeated["status"] == "already_applied"


def test_remove_exclusive_research_sources_is_dry_run_backed_up_and_conservative(tmp_path: Path):
    db_path = tmp_path / "mature.sqlite"
    backup_path = tmp_path / "mature.backup.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    first = _deep_payload()
    first_record = first["deep_research_records"][0]
    first_record.update(
        {
            "research_group_id": "research:remove-one",
            "ascendancy_key": "ascendancy:sorceress:stormweaver",
            "component_mentions": [
                _mention("Spark", "primary_damage", "skill:SparkPlayer", "active_skill")
            ],
            "component_keys": ["skill:SparkPlayer"],
            "source_case_refs": ["source-hash:remove-one"],
        }
    )
    second = json.loads(json.dumps(first))
    second_record = second["deep_research_records"][0]
    second_record.update(
        {
            "research_group_id": "research:remove-two",
            "title": "Second exclusive source",
            "source_case_refs": ["source-hash:remove-two"],
        }
    )
    assert service.propose_deep_research_records(first)["status"] == "accepted"
    assert service.propose_deep_research_records(second)["status"] == "accepted"
    fragment_payload = _fragment_payload(
        summary="exclusive fragment",
        components=["skill:SparkPlayer"],
    )
    fragment_payload["fragments"][0]["source_case_refs"] = ["source-hash:remove-one"]
    query_ref = service.query_research_memory("exclusive fragment")["dedupeQueryRef"]
    assert (
        service.propose_research_fragments(
            fragment_payload,
            dedupe_query_ref=query_ref,
        )["status"]
        == "accepted"
    )

    planned = research_maintenance.remove_exclusive_research_sources(
        ["source-hash:remove-one", "source-hash:remove-two"],
        db_path=db_path,
    )

    assert planned["status"] == "planned"
    assert planned["deleteCounts"]["deep_research_records"] == 1
    assert planned["deleteCounts"]["research_fragments"] == 1
    assert planned["deleteCountsByEvidenceTable"]["research_fragment_evidence"] == 1
    applied = research_maintenance.remove_exclusive_research_sources(
        ["source-hash:remove-one", "source-hash:remove-two"],
        db_path=db_path,
        apply=True,
        backup_path=backup_path,
    )
    assert applied["status"] == "applied"
    assert backup_path.exists()
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_fragments").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_fragment_evidence").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM research_build_families").fetchone()[0] == 0
    finally:
        con.close()


def test_remove_exclusive_research_sources_blocks_shared_record(tmp_path: Path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    payload = _deep_payload()
    record = payload["deep_research_records"][0]
    record.update(
        {
            "ascendancy_key": "ascendancy:sorceress:stormweaver",
            "component_mentions": [
                _mention("Spark", "primary_damage", "skill:SparkPlayer", "active_skill")
            ],
            "component_keys": ["skill:SparkPlayer"],
            "source_case_refs": ["source-hash:remove", "source-hash:retain"],
        }
    )
    assert service.propose_deep_research_records(payload)["status"] == "accepted"

    report = research_maintenance.remove_exclusive_research_sources(
        ["source-hash:remove"], db_path=db_path, apply=True
    )

    assert report["status"] == "blocked_shared_evidence"
    assert report["sharedDurableUnits"]


def _mention(name: str, role: str, key: str, node_type: str) -> dict[str, object]:
    return {
        "candidate_name": name,
        "role": role,
        "resolver_query": key,
        "expected_node_types": [node_type],
        "scope": "player" if node_type == "active_skill" else "any",
        "component_key": key,
        "resolution_status": "resolved",
    }


def _keyed_deep_payload() -> dict[str, object]:
    payload = _deep_payload()
    record = payload["deep_research_records"][0]
    record.update(
        {
            "record_kind": "skill_package",
            "ascendancy_key": "ascendancy:sorceress:stormweaver",
            "component_keys": [
                "skill:SparkPlayer",
                "skill:MetaCastOnCritPlayer",
                "skill:CometPlayer",
                "support:Metadata/Items/Gem/SupportGemFluke",
            ],
            "component_mentions": [
                _mention("Spark", "primary_damage", "skill:SparkPlayer", "active_skill"),
                _mention(
                    "Cast on Critical",
                    "trigger_host",
                    "skill:MetaCastOnCritPlayer",
                    "active_skill",
                ),
                _mention("Comet", "triggered_payload", "skill:CometPlayer", "active_skill"),
                _mention(
                    "Fluke",
                    "support_modifier",
                    "support:Metadata/Items/Gem/SupportGemFluke",
                    "support_gem",
                ),
            ],
            "typed_payload": {
                "supportPackages": [
                    {
                        "skillKey": "skill:SparkPlayer",
                        "supportKeys": ["support:Metadata/Items/Gem/SupportGemFluke"],
                    }
                ]
            },
        }
    )
    return payload


def test_reconcile_deep_record_ids_plan_apply_and_idempotent(tmp_path: Path):
    db_path = tmp_path / "mature.sqlite"
    backup_path = tmp_path / "mature.reconcile.backup.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    first = service.propose_deep_research_records(_keyed_deep_payload())
    record_id = first["recordIds"][0]
    drifted_key = "ku-" + "f" * 20
    con = mature_learning.connect(db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET knowledge_key = ? WHERE record_id = ?",
            (drifted_key, record_id),
        )
        con.commit()
    finally:
        con.close()

    plan = research_maintenance.reconcile_deep_record_ids(db_path=db_path)
    assert plan["status"] == "planned"
    assert plan["relocationCount"] == 1
    assert plan["relocations"][0]["recordId"] == record_id
    assert plan["conflictCount"] == 0

    applied = research_maintenance.reconcile_deep_record_ids(
        db_path=db_path, apply=True, backup_path=backup_path
    )
    assert applied["status"] == "applied"
    assert applied["relocationCount"] == 1
    assert applied["databaseIntegrity"] == "ok"
    assert applied["foreignKeyViolationCount"] == 0
    assert backup_path.exists()

    target_id = "drr-" + research_memory._stable_hash({"knowledge_key": drifted_key})[:16]
    con = mature_learning.connect(db_path)
    try:
        active = con.execute(
            "SELECT record_id, knowledge_key, status, superseded_by_id "
            "FROM deep_research_records WHERE status IN ('valid', 'needs_revalidation')"
        ).fetchall()
        assert len(active) == 1
        assert active[0]["record_id"] == target_id
        assert active[0]["knowledge_key"] == drifted_key
        tombstone = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        assert tombstone is not None
        assert tombstone["status"] == "deprecated"
        assert tombstone["superseded_by_id"] == target_id
    finally:
        con.close()

    again = research_maintenance.reconcile_deep_record_ids(db_path=db_path)
    assert again["status"] == "already_applied"


def test_reconcile_deep_record_ids_replaces_husk_at_anchor(tmp_path: Path):
    db_path = tmp_path / "mature.sqlite"
    service = research_memory.ResearchMemoryService(
        db_path=db_path,
        graph_service=_graph_service(),
    )
    first = service.propose_deep_research_records(_keyed_deep_payload())
    record_id = first["recordIds"][0]
    drifted_key = "ku-" + "c" * 20
    target_id = "drr-" + research_memory._stable_hash({"knowledge_key": drifted_key})[:16]
    husk_head_id = "drr-" + "1" * 16
    con = mature_learning.connect(db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET knowledge_key = ? WHERE record_id = ?",
            (drifted_key, record_id),
        )
        husk = dict(
            con.execute(
                "SELECT * FROM deep_research_records WHERE record_id = ?", (record_id,)
            ).fetchone()
        )
        husk["record_id"] = target_id
        husk["knowledge_key"] = "ku-" + "b" * 20
        husk["status"] = "deprecated"
        husk["superseded_by_id"] = husk_head_id
        columns = tuple(husk)
        con.execute(
            f"INSERT INTO deep_research_records({', '.join(columns)}) "
            f"VALUES ({', '.join('?' for _ in columns)})",
            tuple(husk[column] for column in columns),
        )
        con.commit()
    finally:
        con.close()

    plan = research_maintenance.reconcile_deep_record_ids(db_path=db_path)
    assert plan["status"] == "planned"
    assert plan["huskReplacementCount"] == 1
    assert plan["relocationCount"] == 1

    applied = research_maintenance.reconcile_deep_record_ids(db_path=db_path, apply=True)
    assert applied["status"] == "applied"
    assert applied["relocationCount"] == 1
    assert applied["huskReplacementCount"] == 1
    assert applied["physicalDeleteCount"] == 1

    con = mature_learning.connect(db_path)
    try:
        active = con.execute(
            "SELECT record_id, knowledge_key FROM deep_research_records "
            "WHERE status IN ('valid', 'needs_revalidation')"
        ).fetchall()
        assert len(active) == 1
        assert active[0]["record_id"] == target_id
        assert active[0]["knowledge_key"] == drifted_key
        husk_gone = con.execute(
            "SELECT status FROM deep_research_records WHERE record_id = ?", (target_id,)
        ).fetchone()
        assert husk_gone is not None
        assert husk_gone["status"] == "valid"
        tombstone = con.execute(
            "SELECT status, superseded_by_id FROM deep_research_records WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        assert tombstone is not None
        assert tombstone["status"] == "deprecated"
        assert tombstone["superseded_by_id"] == target_id
    finally:
        con.close()
