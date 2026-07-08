from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3

from server.knowledge import mature_learning
from server.knowledge import graph_tools as gt
from server.knowledge import physical_graph as pg
from server.knowledge import research_memory
from server.knowledge import research_models
from server.knowledge import research_packet


def _tables(con: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _graph_service(
    *,
    extra_nodes: list[pg.GraphNode] | None = None,
    extra_aliases: list[pg.GraphAlias] | None = None,
) -> gt.GraphQueryService:
    source = pg.GraphSource(
        source_id="fixture:phase4",
        kind="test_fixture",
        source_file="tests/test_research_memory.py",
        claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
    )
    nodes = (
        pg.GraphNode("gem:A", "skill_gem", "A", (source.source_id,)),
        pg.GraphNode("mechanic:BC", "mechanic", "BC", (source.source_id,)),
        pg.GraphNode("gem:AB", "skill_gem", "AB", (source.source_id,)),
        pg.GraphNode("mechanic:C", "mechanic", "C", (source.source_id,)),
        pg.GraphNode(
            "skill:LightningArrowPlayer", "active_skill", "Lightning Arrow", (source.source_id,)
        ),
        pg.GraphNode(
            "ascendancy:monk:martial_artist",
            "ascendancy",
            "Martial Artist",
            (source.source_id,),
        ),
        pg.GraphNode("support:Scattershot", "support_gem", "Scattershot", (source.source_id,)),
        pg.GraphNode("passive:pob:0_5:100", "passive", "Projectile Cluster", (source.source_id,)),
        pg.GraphNode(
            "caveat:projectile_floor", "caveat", "Projectile floor caveat", (source.source_id,)
        ),
        *(extra_nodes or []),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:phase4",
        created_at=datetime(2026, 7, 2, tzinfo=UTC),
        sources=(source,),
        nodes=nodes,
        aliases=tuple(extra_aliases or ()),
        edges=(),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)


def _fragment_payload(title: str = "Projectile overlap principle") -> dict[str, object]:
    return {
        "schema_version": 4,
        "fragments": [
            {
                "fragment_type": "mechanic",
                "title": title,
                "summary": "Projectile builds can scale clear when extra projectiles preserve single-target checks.",
                "reusable_principle": "Treat projectile count as conditional coverage until Judge verifies target context.",
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "confidence": "medium",
                "copyability_risk": "low",
                "lifecycle_stages": ["endgame_budget"],
                "modelability": "partial",
                "verification_tasks": ["Run selected-skill Judge readback for projectile count."],
                "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "conditions": ["projectile context"],
                "risks": ["single-target overclaim"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "semantic_edges": [],
    }


def _resolution_evidence(stable_key: str) -> dict[str, object]:
    return {
        "tool_name": "resolve_graph_component",
        "status": "resolved",
        "stable_key": stable_key,
        "snapshot_id": "snapshot:phase4",
        "evidence_path_nodes": [stable_key],
        "source_refs": ["fixture:phase4"],
    }


def _edge_payload(
    source: str, target: str, edge_type: str = "synergizes_with"
) -> dict[str, object]:
    return {
        "schema_version": 4,
        "fragments": [],
        "semantic_edges": [
            {
                "source_key": source,
                "target_key": target,
                "source_resolution": _resolution_evidence(source),
                "target_resolution": _resolution_evidence(target),
                "edge_type": edge_type,
                "rationale": "Safe mechanism-level relationship, not a build recipe.",
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "status": "valid",
                "confidence": "medium",
                "modelability": "partial",
                "copy_safety_state": "passed",
                "context_requirements": [
                    {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_budget"]}
                ],
                "affected_component_keys": [source, target],
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
                "directionality": "associative"
                if edge_type == "synergizes_with"
                else "directional",
            }
        ],
    }


def test_initialize_store_adds_phase4_schema_with_colon_safe_fts(tmp_path):
    db_path = tmp_path / "mature.sqlite"

    mature_learning.initialize_store(db_path)
    con = mature_learning.connect(db_path)
    try:
        assert mature_learning.schema_version(con) == 2
        assert {
            "research_fragments",
            "research_fragment_evidence",
            "research_fragment_fts",
            "research_semantic_edges",
            "research_rejected_proposals",
            "research_revalidation_events",
        } <= _tables(con)

        service = research_memory.ResearchMemoryService(db_path=db_path)
        query_ref = service.query_research_memory(
            "Lightning Arrow", component_keys=["skill:LightningArrowPlayer"]
        )["dedupeQueryRef"]
        accepted = service.propose_research_fragments(
            _fragment_payload(), dedupe_query_ref=query_ref
        )
        assert accepted["status"] == "accepted"

        rows = con.execute(
            "SELECT fragment_id FROM research_fragment_fts WHERE research_fragment_fts MATCH ?",
            ('"skill:LightningArrowPlayer"',),
        ).fetchall()
        assert rows
    finally:
        con.close()


def test_rejected_proposals_are_idempotent_and_increment_retry_count(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    bad = _fragment_payload()
    bad["fragments"][0]["summary"] = "Supports: A, B, C, D, E"
    query_ref = service.query_research_memory("copy safety rejection", component_keys=[])[
        "dedupeQueryRef"
    ]

    first = service.propose_research_fragments(bad, dedupe_query_ref=query_ref)
    second = service.propose_research_fragments(bad, dedupe_query_ref=query_ref)

    assert first["status"] == "rejected"
    assert first["errorCode"] == "copy_safety_violation"
    assert second["status"] == "rejected"
    assert second["errorCode"] == "copy_safety_violation"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute("SELECT retry_count FROM research_rejected_proposals").fetchone()
        assert row["retry_count"] == 2
    finally:
        con.close()


def test_context_requirements_reject_arbitrary_dicts():
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["context_requirements"] = [
        {"context_type": "invented_context", "need_more_dps": True}
    ]

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(result)


def test_context_requirements_accept_phase3_graph_tool_context(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload(
        "skill:LightningArrowPlayer", "support:Scattershot", "requires_transition_gate"
    )
    payload["semantic_edges"][0]["context_requirements"] = [
        {"context_type": "passive_context", "active_weapon_set": 1}
    ]

    validated = research_models.validate_researcher_output(payload)
    accepted = service.propose_semantic_edges(payload)

    assert validated["status"] == "accepted"
    assert accepted["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT context_requirements FROM research_semantic_edges WHERE edge_id = ?",
            (accepted["edgeIds"][0],),
        ).fetchone()
        stored = json.loads(row["context_requirements"])
        assert stored == [{"active_weapon_set": 1, "context_type": "passive_context"}]
    finally:
        con.close()


def _pattern_payload(confidence_tier: str = "case_observation") -> dict[str, object]:
    return {
        "schema_version": 4,
        "build_design_observations": [
            {
                "observation_type": "build_archetype",
                "title": "Lightning projectile shell",
                "summary": "A safe observation about a projectile shell.",
                "axes": ["character_shell", "primary_skill_package", "scaling_axis"],
                "components": [
                    {
                        "component_key": "skill:LightningArrowPlayer",
                        "role": "primary_damage",
                        "resolution": _resolution_evidence("skill:LightningArrowPlayer"),
                    },
                    {
                        "component_key": "support:Scattershot",
                        "role": "support_modifier",
                        "resolution": _resolution_evidence("support:Scattershot"),
                    },
                ],
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
        "patterns": [
            {
                "pattern_type": "cooccurrence",
                "title": "Projectile primary plus projectile support",
                "summary": "A safe co-occurrence pattern without recipe detail.",
                "component_keys": ["skill:LightningArrowPlayer", "support:Scattershot"],
                "component_roles": {
                    "skill:LightningArrowPlayer": "primary_damage",
                    "support:Scattershot": "support_modifier",
                },
                "confidence_tier": confidence_tier,
                "sample_count": 1,
                "family_count": 1,
                "source_diversity_count": 1,
                "denominator": 1,
                "source_case_refs": ["case:la-safe"],
                "safe_evidence_refs": ["safe:la:hash"],
                "context_requirements": [
                    {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_budget"]}
                ],
                "planner_hint": "Try this as an advisory projectile package candidate.",
                "verification_tasks": ["Verify support legality with socket helper."],
                "game_patch": "0.5.4",
                "passive_tree_version": "0_5",
                "pob_version_or_commit": "unknown",
                "visibility": "creator_visible",
                "split": "train_context",
                "knowledge_scope": "global_seed",
            }
        ],
    }


def test_pattern_payload_accepts_build_design_observation_and_case_pattern():
    result = research_models.validate_researcher_output(_pattern_payload())

    assert result["status"] == "accepted"
    assert result["observationCount"] == 1


def test_pattern_payload_accepts_ascendancy_shell_role():
    payload = _pattern_payload()
    ascendancy_component = {
        "component_key": "ascendancy:monk:martial_artist",
        "role": "ascendancy_shell",
        "resolution": _resolution_evidence("ascendancy:monk:martial_artist"),
    }
    payload["build_design_observations"][0]["components"].append(ascendancy_component)
    payload["patterns"][0]["component_keys"].append("ascendancy:monk:martial_artist")
    payload["patterns"][0]["component_roles"]["ascendancy:monk:martial_artist"] = "ascendancy_shell"

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "accepted"
    assert result["patternCount"] == 1


def test_pattern_payload_rejects_common_claim_with_low_sample_count():
    payload = _pattern_payload(confidence_tier="common_within_archetype")

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "insufficient_pattern_evidence"


def test_propose_build_patterns_persists_creator_visible_safe_patterns(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    result = service.propose_build_patterns(_pattern_payload())

    assert result["status"] == "accepted"
    assert result["observationIds"]
    assert result["patternIds"]
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        pattern = con.execute("SELECT * FROM research_build_patterns").fetchone()
        assert pattern["pattern_type"] == "cooccurrence"
        assert pattern["confidence_tier"] == "case_observation"
        assert pattern["planner_visible"] == 1
    finally:
        con.close()


def test_propose_build_patterns_refreshes_source_refs_on_idempotent_update(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    first = _pattern_payload()
    second = _pattern_payload()
    second["build_design_observations"][0]["source_case_refs"] = ["case:new-ref"]
    second["build_design_observations"][0]["safe_evidence_refs"] = ["safe:new-ref"]
    second["patterns"][0]["source_case_refs"] = ["case:new-ref"]
    second["patterns"][0]["safe_evidence_refs"] = ["safe:new-ref"]

    assert service.propose_build_patterns(first)["status"] == "accepted"
    assert service.propose_build_patterns(second)["status"] == "accepted"

    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        observation = con.execute(
            "SELECT source_case_refs FROM research_build_design_observations"
        ).fetchone()
        pattern = con.execute("SELECT source_case_refs FROM research_build_patterns").fetchone()
        assert json.loads(observation["source_case_refs"]) == ["case:new-ref"]
        assert json.loads(pattern["source_case_refs"]) == ["case:new-ref"]
    finally:
        con.close()


def test_propose_build_patterns_persists_ascendancy_shell_role(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    ascendancy_component = {
        "component_key": "ascendancy:monk:martial_artist",
        "role": "ascendancy_shell",
        "resolution": _resolution_evidence("ascendancy:monk:martial_artist"),
    }
    payload["build_design_observations"][0]["components"].append(ascendancy_component)
    payload["patterns"][0]["component_keys"].append("ascendancy:monk:martial_artist")
    payload["patterns"][0]["component_roles"]["ascendancy:monk:martial_artist"] = "ascendancy_shell"

    result = service.propose_build_patterns(payload)

    assert result["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute("SELECT component_roles FROM research_build_patterns").fetchone()
        assert (
            json.loads(row["component_roles"])["ascendancy:monk:martial_artist"]
            == "ascendancy_shell"
        )
    finally:
        con.close()


def test_propose_build_patterns_accepts_apostrophe_unique_stable_key(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(
            extra_nodes=[
                pg.GraphNode(
                    stable_key="unique:pob:alpha's_howl",
                    node_type="unique",
                    display_name="Alpha's Howl",
                    status="valid",
                    source_refs=("fixture:phase4",),
                )
            ],
            extra_aliases=[
                pg.GraphAlias(
                    alias="Alpha's Howl",
                    target_key="unique:pob:alpha's_howl",
                    source_refs=("fixture:phase4",),
                )
            ],
        ),
    )
    payload = _pattern_payload()
    unique_component = {
        "component_key": "unique:pob:alpha's_howl",
        "role": "unique_enabler",
        "resolution": _resolution_evidence("unique:pob:alpha's_howl"),
    }
    payload["build_design_observations"][0]["components"].append(unique_component)
    payload["patterns"][0]["component_keys"].append("unique:pob:alpha's_howl")
    payload["patterns"][0]["component_roles"]["unique:pob:alpha's_howl"] = "unique_enabler"

    result = service.propose_build_patterns(payload)

    assert result["status"] == "accepted"


def test_propose_build_patterns_rejects_unresolved_component_endpoint(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"][0]["components"][0]["resolution"] = None

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_endpoint_resolution"


def test_propose_build_patterns_requires_observation_for_pattern(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"] = []

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_build_design_observation"


def test_propose_build_patterns_rejects_pattern_patched_from_unrelated_observations(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"] = [
        {
            **payload["build_design_observations"][0],
            "components": [payload["build_design_observations"][0]["components"][0]],
        },
        {
            **payload["build_design_observations"][0],
            "title": "Unrelated support observation",
            "components": [payload["build_design_observations"][0]["components"][1]],
        },
    ]

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_build_design_observation"


def test_propose_build_patterns_rejects_visibility_or_version_mismatch_observation(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _pattern_payload()
    payload["build_design_observations"][0]["visibility"] = "evaluator_only"
    payload["build_design_observations"][0]["split"] = "eval_holdout"

    result = service.propose_build_patterns(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_build_design_observation"


def test_pattern_payload_rejects_case_observation_using_common_language():
    payload = _pattern_payload()
    payload["patterns"][0]["summary"] = "This commonly appears as a usual package."

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "overclaimed_pattern_confidence"


def test_pattern_payload_allows_negated_common_language_guardrail():
    payload = _pattern_payload()
    payload["patterns"][0]["summary"] = (
        "This is a single-sample observation and cannot be claimed as common."
    )
    payload["patterns"][0]["planner_hint"] = "不能外推为常见组合，只能作为低置信观察。"

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "accepted"


def test_pattern_payload_rejects_common_without_source_diversity():
    payload = _pattern_payload(confidence_tier="common_within_archetype")
    payload["patterns"][0]["sample_count"] = 8
    payload["patterns"][0]["family_count"] = 1
    payload["patterns"][0]["source_diversity_count"] = 1
    payload["patterns"][0]["denominator"] = 12

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "insufficient_pattern_evidence"


def test_pattern_payload_rejects_open_build_state_context_requirement():
    payload = _pattern_payload()
    payload["patterns"][0]["context_requirements"] = [
        {
            "context_type": "build_state_context",
            "spirit_reservation_summary": {"anything": {"nested": "dict"}},
        }
    ]

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_rejects_component_role_key_or_role_mismatch():
    payload = _pattern_payload()
    payload["patterns"][0]["component_roles"] = {
        "skill:LightningArrowPlayer": "primary_damage",
        "skill:NotInPattern": "whatever_role",
    }

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_rejects_blank_component_key():
    payload = _pattern_payload()
    payload["build_design_observations"][0]["components"][0]["component_key"] = ""
    payload["build_design_observations"][0]["components"][0]["resolution"]["stable_key"] = ""
    payload["build_design_observations"][0]["components"][0]["resolution"][
        "evidence_path_nodes"
    ] = [""]
    payload["patterns"][0]["component_keys"][0] = ""
    payload["patterns"][0]["component_roles"] = {
        "": "primary_damage",
        "support:Scattershot": "support_modifier",
    }

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "invalid_schema"


def test_pattern_payload_rejects_denominator_below_sample_count():
    payload = _pattern_payload(confidence_tier="common_within_archetype")
    payload["patterns"][0]["sample_count"] = 8
    payload["patterns"][0]["family_count"] = 2
    payload["patterns"][0]["source_diversity_count"] = 2
    payload["patterns"][0]["denominator"] = 7

    result = research_models.validate_researcher_output(payload)

    assert result["status"] == "error"
    assert result["errorCode"] == "insufficient_pattern_evidence"


def test_pattern_patch_decay_removes_pattern_from_planner_visible_context(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_build_patterns(_pattern_payload())

    decay = service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    assert decay["patternsUpdated"] == 1
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, planner_visible FROM research_build_patterns WHERE pattern_id = ?",
            (accepted["patternIds"][0],),
        ).fetchone()
        assert row["status"] == "needs_revalidation"
        assert row["planner_visible"] == 0
    finally:
        con.close()


def test_pattern_revalidation_can_restore_planner_visible_context(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_build_patterns(_pattern_payload())
    pattern_id = accepted["patternIds"][0]
    service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    result = service.submit_revalidation_result(
        target_kind="build_pattern",
        target_id=pattern_id,
        outcome="still_valid",
        new_version_context={
            "game_patch": "0.6.0",
            "passive_tree_version": "0_6",
            "pob_version_or_commit": "unknown",
        },
        safe_evidence_refs=["safe:pattern-revalidated"],
        affected_component_keys=["support:Scattershot"],
    )

    assert result["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            """
            SELECT status, planner_visible, game_patch, passive_tree_version, current_version_context
            FROM research_build_patterns
            WHERE pattern_id = ?
            """,
            (pattern_id,),
        ).fetchone()
        assert row["status"] == "valid"
        assert row["planner_visible"] == 1
        assert row["game_patch"] == "0.6.0"
        assert row["passive_tree_version"] == "0_6"
        assert json.loads(row["current_version_context"])["game_patch"] == "0.6.0"
        event = con.execute(
            "SELECT target_kind FROM research_revalidation_events WHERE target_id = ?",
            (pattern_id,),
        ).fetchone()
        assert event["target_kind"] == "build_pattern"
    finally:
        con.close()


def test_pattern_revalidation_migrates_legacy_revalidation_event_check(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
        con.execute(
            """
            CREATE TABLE research_revalidation_events (
                event_id TEXT PRIMARY KEY,
                target_kind TEXT NOT NULL,
                target_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                old_version_context TEXT NOT NULL,
                new_version_context TEXT NOT NULL,
                safe_evidence_refs TEXT NOT NULL,
                affected_component_keys TEXT NOT NULL,
                created_at TEXT NOT NULL,
                CHECK (target_kind IN ('fragment', 'semantic_edge')),
                CHECK (outcome IN ('still_valid', 'invalidated', 'changed_scope', 'needs_review'))
            )
            """
        )
        con.commit()
    finally:
        con.close()

    service = research_memory.ResearchMemoryService(db_path=db_path, graph_service=_graph_service())
    accepted = service.propose_build_patterns(_pattern_payload())
    pattern_id = accepted["patternIds"][0]
    service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    result = service.submit_revalidation_result(
        target_kind="build_pattern",
        target_id=pattern_id,
        outcome="still_valid",
        new_version_context={
            "game_patch": "0.6.0",
            "passive_tree_version": "0_6",
            "pob_version_or_commit": "unknown",
        },
        safe_evidence_refs=["safe:pattern-revalidated"],
        affected_component_keys=["support:Scattershot"],
    )

    assert result["status"] == "accepted"


def test_transient_packet_uses_temp_prefix_and_startup_gc(tmp_path):
    case = {
        "safeMetadata": {"caseId": "safe-case", "mainSkill": "Lightning Arrow"},
        "rawContext": {"pobCode": "eNrt" + "A" * 80},
    }
    result = research_packet.build_research_packet(
        case,
        persist_for_transport=True,
        ttl_seconds=1,
        temp_root=tmp_path,
    )

    assert result["ok"] is True
    packet_path = Path(result["packetPath"])
    assert "poe-bd-creator-research-packet-" in str(packet_path)
    assert result["packet"]["safeHash"]
    assert "pobCode" in json.loads(packet_path.read_text(encoding="utf-8"))["rawContext"]

    removed = research_packet.cleanup_expired_packets(
        temp_root=tmp_path, now=result["packet"]["expiresAt"]
    )
    assert removed["removed"] == 1
    assert not packet_path.parent.exists()


def test_transient_packet_path_is_json_serializable_string(tmp_path):
    result = research_packet.build_research_packet(
        {"safeMetadata": {"caseId": "safe-case"}, "rawContext": {"raw": "quarantine-only"}},
        persist_for_transport=True,
        ttl_seconds=1,
        temp_root=tmp_path,
    )

    json.dumps(result)
    assert isinstance(result["packetPath"], str)


def test_query_before_propose_and_append_evidence_prevent_duplicate_fragments(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    missing = service.propose_research_fragments(_fragment_payload())
    assert missing["errorCode"] == "missing_dedupe_query"

    forged = service.propose_research_fragments(
        _fragment_payload("Forged query ref should fail"),
        dedupe_query_ref="dq-forged",
    )
    assert forged["status"] == "rejected"
    assert forged["errorCode"] == "invalid_dedupe_query_ref"

    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    duplicate = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)

    assert accepted["status"] == "accepted"
    assert duplicate["status"] == "rejected"
    assert duplicate["errorCode"] == "duplicate_fragment_candidate"

    fragment_id = accepted["fragmentIds"][0]
    appended = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:la-second"],
        safe_evidence_refs=["safe:la:second"],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="unknown",
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        confidence="medium",
    )
    holdout = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:holdout"],
        safe_evidence_refs=["safe:holdout"],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="unknown",
        visibility="evaluator_only",
        split="eval_holdout",
        knowledge_scope="eval_ephemeral",
        confidence="medium",
    )

    assert appended["status"] == "accepted"
    assert appended["evidenceCount"] == 2
    assert holdout["status"] == "rejected"
    assert holdout["errorCode"] == "holdout_boundary_violation"


def test_semantic_edges_require_resolver_evidence_for_each_endpoint(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    del payload["semantic_edges"][0]["source_resolution"]

    result = service.propose_semantic_edges(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_endpoint_resolution"


def test_semantic_edge_resolver_evidence_must_match_stable_key_and_snapshot(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    mismatch = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    mismatch["semantic_edges"][0]["source_resolution"]["stable_key"] = "support:Scattershot"
    stale_snapshot = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    stale_snapshot["semantic_edges"][0]["target_resolution"]["snapshot_id"] = "snapshot:old"

    mismatch_result = service.propose_semantic_edges(mismatch)
    stale_result = service.propose_semantic_edges(stale_snapshot)

    assert mismatch_result["status"] == "rejected"
    assert mismatch_result["errorCode"] == "endpoint_resolution_mismatch"
    assert stale_result["status"] == "rejected"
    assert stale_result["errorCode"] == "stale_endpoint_resolution"


def test_semantic_edge_resolver_evidence_source_refs_must_match_graph_sources(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["source_resolution"]["source_refs"] = ["fixture:wrong"]

    result = service.propose_semantic_edges(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "endpoint_resolution_mismatch"
    assert "source refs" in result["caveats"][0]


def test_semantic_edge_resolver_evidence_rejects_forged_extra_source_refs(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["source_resolution"]["source_refs"] = [
        "fixture:phase4",
        "fixture:forged",
    ]

    result = service.propose_semantic_edges(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "endpoint_resolution_mismatch"
    assert "source refs" in result["caveats"][0]


def test_synergizes_with_id_uses_canonical_payload_not_raw_concatenation(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    first = service.propose_semantic_edges(_edge_payload("gem:A", "mechanic:BC"))
    second = service.propose_semantic_edges(_edge_payload("gem:AB", "mechanic:C"))

    assert first["status"] == "accepted"
    assert second["status"] == "accepted"
    assert first["edgeIds"][0] != second["edgeIds"][0]


def test_directional_short_cycle_detection_is_bounded_to_depth_three(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    assert (
        service.propose_semantic_edges(
            _edge_payload("skill:LightningArrowPlayer", "support:Scattershot", "enables_mechanic")
        )["status"]
        == "accepted"
    )
    assert (
        service.propose_semantic_edges(
            _edge_payload("support:Scattershot", "passive:pob:0_5:100", "enables_mechanic")
        )["status"]
        == "accepted"
    )
    cycle = service.propose_semantic_edges(
        _edge_payload("passive:pob:0_5:100", "skill:LightningArrowPlayer", "enables_mechanic")
    )

    assert cycle["status"] == "rejected"
    assert cycle["errorCode"] == "semantic_cycle_or_conflict"
    assert cycle["facts"]["maxDepthChecked"] == 3


def test_non_valid_or_unsafe_semantic_edges_are_not_planner_visible(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["status"] = "needs_revalidation"
    payload["semantic_edges"][0]["copy_safety_state"] = "needs_review"

    accepted = service.propose_semantic_edges(payload)

    assert accepted["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (accepted["edgeIds"][0],),
        ).fetchone()
        assert row["planner_visible"] == 0
    finally:
        con.close()


def test_patch_decay_can_be_revalidated_without_duplicate_successor(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    decay = service.apply_patch_decay(
        changed_component_keys=["skill:LightningArrowPlayer"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )
    renewed = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:revalidated"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert decay["itemsUpdated"] == 1
    assert renewed["status"] == "accepted"
    assert renewed["targetId"] == fragment_id
    result = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )
    assert result["results"][0]["status"] == "valid"
    assert result["results"][0]["gamePatch"] == "0.6.0"


def test_semantic_edges_require_graph_service_endpoint_validation(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    result = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "graph_service_unavailable"
    assert result["endpointAssessment"]["classification"] == "graph_snapshot_unavailable"
    assert result["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert result["endpointAssessment"]["candidateEndpointKeys"] == []
    assert result["endpointAssessment"]["missingEndpointKeys"] == []


def test_missing_endpoint_is_reported_as_source_coverage_gap_not_hallucination(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )

    result = service.propose_semantic_edges(
        _edge_payload("skill:VividStampedePlayer", "support:Scattershot")
    )

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_endpoint"
    assert result["endpointAssessment"]["classification"] == "source_coverage_gap"
    assert result["endpointAssessment"]["hallucinationVerdict"] == "not_assessed"
    assert result["endpointAssessment"]["candidateEndpointKeys"] == ["skill:VividStampedePlayer"]
    assert result["endpointAssessment"]["missingEndpointKeys"] == ["skill:VividStampedePlayer"]
    assert result["facts"]["missingEndpointKeys"] == ["skill:VividStampedePlayer"]


def test_append_and_revalidation_reject_copyable_evidence_refs(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    append_result = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:copyable"],
        safe_evidence_refs=["eNrt" + "A" * 80],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="unknown",
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        confidence="medium",
    )
    revalidation_result = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["eNrt" + "B" * 80],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert append_result["status"] == "rejected"
    assert append_result["errorCode"] == "copy_safety_violation"
    assert revalidation_result["status"] == "rejected"
    assert revalidation_result["errorCode"] == "copy_safety_violation"


def test_fragment_proposal_rejects_profile_urls_and_long_guide_prose(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    profile_url = _fragment_payload("Profile URL leak")
    profile_url["fragments"][0]["summary"] = (
        "See https://www.pathofexile.com/account/view-profile/example/characters"
    )
    ninja_url = _fragment_payload("Ninja URL leak")
    ninja_url["fragments"][0]["summary"] = (
        "See https://poe.ninja/poe2/builds/standard/character/Account/Character"
    )
    guide_prose = _fragment_payload("Long guide leak")
    guide_prose["fragments"][0]["summary"] = " ".join(f"guideword{i}" for i in range(230))

    profile_ref = service.query_research_memory("profile leak", component_keys=[])["dedupeQueryRef"]
    ninja_ref = service.query_research_memory("ninja leak", component_keys=[])["dedupeQueryRef"]
    prose_ref = service.query_research_memory("guide prose leak", component_keys=[])[
        "dedupeQueryRef"
    ]

    profile_result = service.propose_research_fragments(profile_url, dedupe_query_ref=profile_ref)
    ninja_result = service.propose_research_fragments(ninja_url, dedupe_query_ref=ninja_ref)
    prose_result = service.propose_research_fragments(guide_prose, dedupe_query_ref=prose_ref)

    assert profile_result["status"] == "rejected"
    assert profile_result["errorCode"] == "copy_safety_violation"
    assert ninja_result["status"] == "rejected"
    assert ninja_result["errorCode"] == "copy_safety_violation"
    assert prose_result["status"] == "rejected"
    assert prose_result["errorCode"] == "copy_safety_violation"


def test_append_and_revalidation_check_all_persisted_version_context(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    append_result = service.append_evidence_to_fragment(
        fragment_id=fragment_id,
        source_case_refs=["case:safe"],
        safe_evidence_refs=["safe:review"],
        game_patch="0.5.4",
        passive_tree_version="0_5",
        pob_version_or_commit="eNrt" + "C" * 80,
        visibility="creator_visible",
        split="train_context",
        knowledge_scope="global_seed",
        confidence="medium",
    )
    revalidation_result = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"pob_version_or_commit": "eNrt" + "D" * 80},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert append_result["status"] == "rejected"
    assert append_result["errorCode"] == "copy_safety_violation"
    assert revalidation_result["status"] == "rejected"
    assert revalidation_result["errorCode"] == "copy_safety_violation"


def test_non_dict_proposals_return_public_errors_without_traceback(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")

    query_ref = service.query_research_memory("schema validation", component_keys=[])[
        "dedupeQueryRef"
    ]
    fragments = service.propose_research_fragments([], dedupe_query_ref=query_ref)  # type: ignore[arg-type]
    edges = service.propose_semantic_edges([])  # type: ignore[arg-type]

    assert fragments["status"] == "error"
    assert fragments["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(fragments)
    assert edges["status"] == "error"
    assert edges["errorCode"] == "invalid_schema"
    assert "Traceback" not in str(edges)


def test_revalidation_rejects_invalid_target_kind_and_outcome(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    bad_kind = service.submit_revalidation_result(
        target_kind="raw_sql",
        target_id=fragment_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0"},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )
    bad_outcome = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="bless_forever",
        new_version_context={"game_patch": "0.6.0"},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )

    assert bad_kind["status"] == "rejected"
    assert bad_kind["errorCode"] == "invalid_revalidation_target_kind"
    assert bad_outcome["status"] == "rejected"
    assert bad_outcome["errorCode"] == "invalid_revalidation_outcome"


def test_query_uses_fts_text_not_only_component_filter(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)

    hit = service.query_research_memory("projectile", component_keys=["skill:LightningArrowPlayer"])
    miss = service.query_research_memory(
        "mana flask", component_keys=["skill:LightningArrowPlayer"]
    )

    assert hit["results"]
    assert miss["results"] == []


def test_query_component_filter_uses_exact_stable_key_not_substring(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    payload = _fragment_payload("Projectile substring near miss")
    payload["fragments"][0]["component_keys"] = ["skill:LightningArrowPlayerExtra"]
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayerExtra"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(payload, dedupe_query_ref=query_ref)

    near_miss = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )
    exact = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayerExtra"]
    )

    assert accepted["status"] == "accepted"
    assert near_miss["results"] == []
    assert exact["results"]


def test_query_hides_deprecated_fragments_after_changed_scope_revalidation(tmp_path):
    service = research_memory.ResearchMemoryService(db_path=tmp_path / "mature.sqlite")
    query_ref = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )["dedupeQueryRef"]
    accepted = service.propose_research_fragments(_fragment_payload(), dedupe_query_ref=query_ref)
    fragment_id = accepted["fragmentIds"][0]

    revalidated = service.submit_revalidation_result(
        target_kind="fragment",
        target_id=fragment_id,
        outcome="changed_scope",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:changed"],
        affected_component_keys=["skill:LightningArrowPlayer"],
    )
    result = service.query_research_memory(
        "projectile", component_keys=["skill:LightningArrowPlayer"]
    )

    assert revalidated["status"] == "accepted"
    assert result["results"] == []


def test_patch_decay_updates_semantic_edges_by_affected_components(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )
    edge_id = accepted["edgeIds"][0]

    decay = service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )

    assert decay["edgesUpdated"] == 1
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, current_version_context FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        assert row["status"] == "needs_revalidation"
        assert json.loads(row["current_version_context"])["game_patch"] == "0.6.0"
    finally:
        con.close()


def test_semantic_edge_lifecycle_changes_clear_planner_visibility(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    accepted = service.propose_semantic_edges(
        _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    )
    edge_id = accepted["edgeIds"][0]

    decay = service.apply_patch_decay(
        changed_component_keys=["support:Scattershot"],
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
    )
    changed = service.submit_revalidation_result(
        target_kind="semantic_edge",
        target_id=edge_id,
        outcome="changed_scope",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:changed"],
        affected_component_keys=["support:Scattershot"],
    )

    assert decay["edgesUpdated"] == 1
    assert changed["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        assert row["status"] == "deprecated"
        assert row["planner_visible"] == 0
    finally:
        con.close()


def test_still_valid_revalidation_does_not_promote_unsafe_semantic_edge(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "mature.sqlite",
        graph_service=_graph_service(),
    )
    payload = _edge_payload("skill:LightningArrowPlayer", "support:Scattershot")
    payload["semantic_edges"][0]["status"] = "needs_revalidation"
    payload["semantic_edges"][0]["copy_safety_state"] = "needs_review"
    accepted = service.propose_semantic_edges(payload)
    edge_id = accepted["edgeIds"][0]

    renewed = service.submit_revalidation_result(
        target_kind="semantic_edge",
        target_id=edge_id,
        outcome="still_valid",
        new_version_context={"game_patch": "0.6.0", "passive_tree_version": "0_6"},
        safe_evidence_refs=["safe:review"],
        affected_component_keys=["support:Scattershot"],
    )

    assert renewed["status"] == "accepted"
    con = mature_learning.connect(tmp_path / "mature.sqlite")
    try:
        row = con.execute(
            "SELECT status, copy_safety_state, planner_visible FROM research_semantic_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        assert row["status"] == "valid"
        assert row["copy_safety_state"] == "needs_review"
        assert row["planner_visible"] == 0
    finally:
        con.close()
