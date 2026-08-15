from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from server.knowledge import graph_tools as gt
from server.knowledge import mature_learning
from server.knowledge import physical_graph as pg
from server.knowledge import research_memory
from scripts import backfill_semantic_edges as bf

SOURCE = pg.GraphSource(
    source_id="fixture:backfill",
    kind="test_fixture",
    source_file="tests/test_backfill_semantic_edges.py",
    claims=(pg.SourceClaim("passive_tree_version", "0_5"),),
)
VERSION = ("0.5.4", "0_5", "0.22.0")


def _graph() -> gt.GraphQueryService:
    nodes = (
        pg.GraphNode("skill:ASkillPlayer", "active_skill", "A Skill", (SOURCE.source_id,)),
        pg.GraphNode("skill:BSkillPlayer", "active_skill", "B Skill", (SOURCE.source_id,)),
        pg.GraphNode("skill:GeneratorPlayer", "active_skill", "Generator", (SOURCE.source_id,)),
        pg.GraphNode("skill:PayoffPlayer", "active_skill", "Payoff", (SOURCE.source_id,)),
        pg.GraphNode(
            "skill:TriggerHostPlayer", "active_skill", "Trigger Host", (SOURCE.source_id,)
        ),
        pg.GraphNode("skill:SecondaryPlayer", "active_skill", "Secondary", (SOURCE.source_id,)),
        pg.GraphNode("unique:pob:the_enabler", "unique", "The Enabler", (SOURCE.source_id,)),
        pg.GraphNode("support:SomeSupport", "support_gem", "Some Support", (SOURCE.source_id,)),
        pg.GraphNode("notable:pob:0_5:1", "notable", "Notable One", (SOURCE.source_id,)),
        pg.GraphNode("keystone:pob:0_5:2", "keystone", "Keystone Two", (SOURCE.source_id,)),
        pg.GraphNode("skill:CycleSPlayer", "active_skill", "Cycle S", (SOURCE.source_id,)),
        pg.GraphNode("skill:CycleTPlayer", "active_skill", "Cycle T", (SOURCE.source_id,)),
        pg.GraphNode("skill:CycleAPlayer", "active_skill", "Cycle A", (SOURCE.source_id,)),
        pg.GraphNode("skill:CycleBPlayer", "active_skill", "Cycle B", (SOURCE.source_id,)),
        pg.GraphNode(
            "item_base:Metadata/Items/Armours/Shields/FourShieldStr7Cruel",
            "armour_base",
            "Shield",
            (SOURCE.source_id,),
        ),
    )
    snapshot = pg.GraphSnapshot(
        snapshot_id="snapshot:backfill",
        created_at=datetime(2026, 8, 15, tzinfo=UTC),
        sources=(SOURCE,),
        nodes=nodes,
        aliases=(),
        edges=(),
    )
    return gt.GraphQueryService.from_snapshot(snapshot)


def _memory(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db_path = tmp_path / "memory.sqlite"
    db_path.unlink(missing_ok=True)
    mature_learning.initialize_store(db_path)
    return db_path, mature_learning.connect(db_path)


def _insert_record(
    con: sqlite3.Connection,
    *,
    record_id: str,
    kind: str,
    title: str,
    keys: list[str],
    roles: dict[str, str],
    status: str = "valid",
    source_case_refs: list[str] | None = None,
) -> None:
    mentions = [{"role": role, "component_key": key} for key, role in roles.items()]
    con.execute(
        """
        INSERT INTO deep_research_records(
            record_id, research_group_id, record_kind, title, summary, content,
            content_language, component_keys, component_mentions, source_case_refs,
            safe_evidence_refs, conditions, failure_conditions, typed_payload,
            extraction_method_version, record_schema_version, game_patch,
            passive_tree_version, pob_version_or_commit, visibility, split,
            knowledge_scope, status, copy_safety_state, current_version_context,
            created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            "research:fixture",
            kind,
            title,
            title,
            title,
            "zh-CN",
            json.dumps(keys, ensure_ascii=False),
            json.dumps(mentions, ensure_ascii=False),
            json.dumps(source_case_refs or ["source-hash:fixture0000000000"], ensure_ascii=False),
            json.dumps([f"evidence:{record_id}"], ensure_ascii=False),
            "[]",
            "[]",
            "{}",
            "deep_research_mvp_v1",
            1,
            *VERSION,
            "creator_visible",
            "train_context",
            "global_seed",
            status,
            "passed",
            json.dumps(
                {
                    "game_patch": VERSION[0],
                    "passive_tree_version": VERSION[1],
                    "pob_version_or_commit": VERSION[2],
                }
            ),
            "2026-08-15T00:00:00+00:00",
            "2026-08-15T00:00:00+00:00",
        ),
    )


def _insert_pattern(
    con: sqlite3.Connection,
    *,
    pattern_id: str,
    title: str,
    keys: list[str],
    roles: dict[str, str],
    confidence_tier: str = "case_observation",
    context_requirements: list[dict[str, object]] | None = None,
) -> None:
    con.execute(
        """
        INSERT INTO research_build_patterns(
            pattern_id, pattern_type, title, summary, component_keys, component_roles,
            confidence_tier, sample_count, family_count, source_diversity_count,
            denominator, source_case_refs, safe_evidence_refs, context_requirements,
            verification_tasks, game_patch, passive_tree_version,
            pob_version_or_commit, visibility, split, knowledge_scope, status,
            copy_safety_state, current_version_context, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pattern_id,
            "transition_gate",
            title,
            title,
            json.dumps(keys, ensure_ascii=False),
            json.dumps(roles, ensure_ascii=False),
            confidence_tier,
            1,
            1,
            1,
            1,
            json.dumps(["source-hash:fixture0000000000"], ensure_ascii=False),
            json.dumps([f"evidence:{pattern_id}"], ensure_ascii=False),
            json.dumps(context_requirements or [], ensure_ascii=False),
            json.dumps(["Verify with Judge."], ensure_ascii=False),
            *VERSION,
            "creator_visible",
            "train_context",
            "global_seed",
            "valid",
            "passed",
            json.dumps({"game_patch": VERSION[0]}),
            "2026-08-15T00:00:00+00:00",
            "2026-08-15T00:00:00+00:00",
        ),
    )


def _insert_edge(
    con: sqlite3.Connection,
    *,
    source: str,
    target: str,
    edge_type: str,
) -> None:
    con.execute(
        """
        INSERT INTO research_semantic_edges(
            edge_id, source_key, target_key, canonical_source_key, canonical_target_key,
            edge_type, rationale, source_case_refs, safe_evidence_refs, game_patch,
            passive_tree_version, pob_version_or_commit, status, confidence,
            modelability, copy_safety_state, context_requirements,
            affected_component_keys, visibility, split, knowledge_scope,
            directionality, planner_visible, current_version_context,
            created_at, last_seen_at, last_validated_at, superseded_by_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            f"rse-fixture-{source}-{target}",
            source,
            target,
            source,
            target,
            edge_type,
            "fixture edge",
            json.dumps(["source-hash:fixture0000000000"]),
            json.dumps(["evidence:fixture"]),
            *VERSION,
            "valid",
            "low",
            "partial",
            "passed",
            json.dumps([{"context_type": "verification_gate_requirement", "task": "fixture"}]),
            json.dumps(sorted({source, target})),
            "creator_visible",
            "train_context",
            "global_seed",
            "directional",
            1,
            json.dumps({"game_patch": VERSION[0]}),
            "2026-08-15T00:00:00+00:00",
            "2026-08-15T00:00:00+00:00",
            "2026-08-15T00:00:00+00:00",
        ),
    )


def _derived(
    tmp_path: Path,
    service: gt.GraphQueryService,
    *,
    include_inverse_edge: bool = True,
) -> dict[str, object]:
    db_path, con = _memory(tmp_path)
    try:
        _insert_pattern(
            con,
            pattern_id="bdp-gate-1",
            title="Gate One",
            keys=["skill:ASkillPlayer", "unique:pob:the_enabler"],
            roles={
                "skill:ASkillPlayer": "primary_damage",
                "unique:pob:the_enabler": "unique_enabler",
            },
            context_requirements=[
                {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_mature"]}
            ],
        )
        _insert_pattern(
            con,
            pattern_id="bdp-gate-2",
            title="Gate Two",
            keys=["skill:BSkillPlayer", "keystone:pob:0_5:2"],
            roles={"skill:BSkillPlayer": "payoff", "keystone:pob:0_5:2": "keystone_transformer"},
            confidence_tier="recurring_observation",
        )
        _insert_record(
            con,
            record_id="drr-chain-1",
            kind="mechanic_chain",
            title="Chain One",
            keys=["skill:GeneratorPlayer", "skill:PayoffPlayer", "unique:pob:the_enabler"],
            roles={
                "skill:GeneratorPlayer": "generator",
                "skill:PayoffPlayer": "payoff",
                "unique:pob:the_enabler": "unique_enabler",
            },
        )
        _insert_record(
            con,
            record_id="drr-chain-2",
            kind="mechanic_chain",
            title="Chain Deprecated",
            keys=["skill:GeneratorPlayer", "skill:BSkillPlayer"],
            roles={"skill:GeneratorPlayer": "generator", "skill:BSkillPlayer": "payoff"},
            status="deprecated",
        )
        _insert_record(
            con,
            record_id="drr-chain-3",
            kind="mechanic_chain",
            title="Chain Duplicate Pair",
            keys=["skill:GeneratorPlayer", "skill:PayoffPlayer"],
            roles={"skill:GeneratorPlayer": "generator", "skill:PayoffPlayer": "payoff"},
        )
        _insert_record(
            con,
            record_id="drr-fail-1",
            kind="failure_mode",
            title="Failure One",
            keys=["unique:pob:the_enabler", "skill:PayoffPlayer"],
            roles={"unique:pob:the_enabler": "unique_enabler", "skill:PayoffPlayer": "payoff"},
        )
        _insert_record(
            con,
            record_id="drr-cav-1",
            kind="modelability_caveat",
            title="Caveat One",
            keys=["skill:ASkillPlayer", "support:SomeSupport", "skill:SecondaryPlayer"],
            roles={
                "skill:ASkillPlayer": "primary_damage",
                "support:SomeSupport": "support_modifier",
                "skill:SecondaryPlayer": "secondary_skill",
            },
        )
        _insert_record(
            con,
            record_id="drr-lone-1",
            kind="modelability_caveat",
            title="Lone Component",
            keys=["skill:BSkillPlayer"],
            roles={"skill:BSkillPlayer": "primary_damage"},
        )
        if include_inverse_edge:
            _insert_edge(
                con,
                source="skill:PayoffPlayer",
                target="unique:pob:the_enabler",
                edge_type="creates_failure_risk_for",
            )
        con.commit()
        nodes = getattr(service, "_nodes_by_key", {})
        return bf.derive_candidates(
            db_path=db_path,
            nodes_by_key=nodes,
            snapshot_id=str(service.snapshot.snapshot_id),
        )
    finally:
        con.close()


def _edge_triples(candidates: list[dict[str, object]]) -> set[tuple[str, str, str]]:
    return {(e["source_key"], e["target_key"], e["edge_type"]) for e in candidates}


def test_derivation_rules_and_gates(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service)
    candidates = derived["candidates"]
    stats = derived["stats"]

    triples = _edge_triples(candidates)
    assert ("skill:ASkillPlayer", "unique:pob:the_enabler", "requires_transition_gate") in triples
    assert ("skill:BSkillPlayer", "keystone:pob:0_5:2", "requires_transition_gate") in triples
    assert ("skill:GeneratorPlayer", "skill:PayoffPlayer", "enables_mechanic") in triples
    # the fixture inverse edge (Payoff->the_enabler) makes both the_enabler->Payoff
    # candidates (inverse pair and 2-cycle) fail the pre-check, mirroring the
    # service's whole-chunk conflict gate.
    assert ("unique:pob:the_enabler", "skill:PayoffPlayer", "enables_mechanic") not in triples
    assert (
        "unique:pob:the_enabler",
        "skill:PayoffPlayer",
        "creates_failure_risk_for",
    ) not in triples
    assert ("skill:ASkillPlayer", "support:SomeSupport", "has_modelability_caveat") in triples
    assert ("skill:ASkillPlayer", "skill:SecondaryPlayer", "has_modelability_caveat") in triples

    # deprecated and single-key rows never produce candidates
    assert ("skill:GeneratorPlayer", "skill:BSkillPlayer", "enables_mechanic") not in triples
    assert stats["modelability_caveat"]["skipped_insufficient_keys"] == 1
    # identity duplicates (same pair from different records) collapse to one edge
    assert derived["deduplicated"] >= 1
    assert (
        sum(
            1
            for e in candidates
            if (e["source_key"], e["target_key"], e["edge_type"])
            == ("skill:GeneratorPlayer", "skill:PayoffPlayer", "enables_mechanic")
        )
        == 1
    )

    # inverse edge pre-check drops the candidate that mirrors the stored edge
    assert (
        "skill:PayoffPlayer",
        "unique:pob:the_enabler",
        "creates_failure_risk_for",
    ) not in triples
    assert any(
        d["source_key"] == "unique:pob:the_enabler"
        and d["target_key"] == "skill:PayoffPlayer"
        and d["edge_type"] == "creates_failure_risk_for"
        for d in derived["conflictDropped"]
    )


def test_mechanic_unique_enabler_pair_kept_without_conflict(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service, include_inverse_edge=False)
    triples = _edge_triples(derived["candidates"])
    assert ("unique:pob:the_enabler", "skill:PayoffPlayer", "enables_mechanic") in triples


def test_three_hop_cycle_candidate_is_dropped(tmp_path):
    """The service rejects a candidate that closes a 3-edge cycle (T->A->B->S plus S->T);
    the pre-check must drop it too so apply chunks never trip whole-chunk rejections."""
    service = _graph()
    db_path, con = _memory(tmp_path)
    try:
        for source, target in (
            ("skill:CycleTPlayer", "skill:CycleAPlayer"),
            ("skill:CycleAPlayer", "skill:CycleBPlayer"),
            ("skill:CycleBPlayer", "skill:CycleSPlayer"),
        ):
            _insert_edge(con, source=source, target=target, edge_type="enables_mechanic")
        _insert_record(
            con,
            record_id="drr-cycle-1",
            kind="mechanic_chain",
            title="Cycle Chain",
            keys=["skill:CycleSPlayer", "skill:CycleTPlayer"],
            roles={"skill:CycleSPlayer": "generator", "skill:CycleTPlayer": "payoff"},
        )
        con.commit()
        nodes = getattr(service, "_nodes_by_key", {})
        derived = bf.derive_candidates(
            db_path=db_path,
            nodes_by_key=nodes,
            snapshot_id=str(service.snapshot.snapshot_id),
        )
    finally:
        con.close()
    triples = _edge_triples(derived["candidates"])
    assert ("skill:CycleSPlayer", "skill:CycleTPlayer", "enables_mechanic") not in triples
    assert any(
        d["source_key"] == "skill:CycleSPlayer"
        and d["target_key"] == "skill:CycleTPlayer"
        and d["edge_type"] == "enables_mechanic"
        for d in derived["conflictDropped"]
    )


def test_two_hop_cycle_candidate_is_dropped(tmp_path):
    """Sanity: a 2-edge cycle (T->A->S plus S->T) is also dropped by the pre-check."""
    service = _graph()
    db_path, con = _memory(tmp_path)
    try:
        for source, target in (
            ("skill:CycleTPlayer", "skill:CycleAPlayer"),
            ("skill:CycleAPlayer", "skill:CycleSPlayer"),
        ):
            _insert_edge(con, source=source, target=target, edge_type="enables_mechanic")
        _insert_record(
            con,
            record_id="drr-cycle-2",
            kind="mechanic_chain",
            title="Cycle Chain Two",
            keys=["skill:CycleSPlayer", "skill:CycleTPlayer"],
            roles={"skill:CycleSPlayer": "generator", "skill:CycleTPlayer": "payoff"},
        )
        con.commit()
        nodes = getattr(service, "_nodes_by_key", {})
        derived = bf.derive_candidates(
            db_path=db_path,
            nodes_by_key=nodes,
            snapshot_id=str(service.snapshot.snapshot_id),
        )
    finally:
        con.close()
    triples = _edge_triples(derived["candidates"])
    assert ("skill:CycleSPlayer", "skill:CycleTPlayer", "enables_mechanic") not in triples


def test_evidence_built_from_snapshot_nodes(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service)
    edge = next(
        e
        for e in derived["candidates"]
        if e["source_key"] == "skill:ASkillPlayer" and e["edge_type"] == "requires_transition_gate"
    )
    for role in ("source_resolution", "target_resolution"):
        evidence = edge[role]
        assert evidence["tool_name"] == "resolve_graph_component"
        assert evidence["status"] == "resolved"
        assert evidence["snapshot_id"] == "snapshot:backfill"
        assert evidence["evidence_path_nodes"] == [evidence["stable_key"]]
        assert evidence["source_refs"] == ["fixture:backfill"]
    assert edge["rationale"].startswith("存量回填推导：transition_gate bdp-gate-1")
    assert edge["confidence"] == "low"
    assert edge["affected_component_keys"] == sorted([edge["source_key"], edge["target_key"]])
    assert edge["directionality"] == "directional"
    assert edge["knowledge_scope"] == "global_seed"


def test_recurring_pattern_gets_medium_confidence(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service)
    edge = next(
        e
        for e in derived["candidates"]
        if e["source_key"] == "skill:BSkillPlayer" and e["edge_type"] == "requires_transition_gate"
    )
    assert edge["confidence"] == "medium"


def test_transition_gate_reuses_pattern_context(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service)
    edge = next(
        e
        for e in derived["candidates"]
        if e["source_key"] == "skill:ASkillPlayer" and e["edge_type"] == "requires_transition_gate"
    )
    assert edge["context_requirements"] == [
        {"context_type": "lifecycle_stage_requirement", "stages": ["endgame_mature"]}
    ]


def test_derivation_is_deterministic_in_process(tmp_path):
    service = _graph()
    first = _derived(tmp_path, service)
    second = _derived(tmp_path, service)
    assert _edge_triples(first["candidates"]) == _edge_triples(second["candidates"])
    assert first["candidates"] == second["candidates"]


def test_propose_accepts_derived_payload_and_is_idempotent(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service)
    candidates = derived["candidates"]
    db_path = tmp_path / "memory.sqlite"
    memory = research_memory.ResearchMemoryService(db_path=db_path, graph_service=service)

    first = memory.propose_semantic_edges(
        {"schema_version": 4, "fragments": [], "semantic_edges": candidates}
    )
    assert first["status"] == "accepted"
    assert len(first["edgeIds"]) == len(candidates)

    second = memory.propose_semantic_edges(
        {"schema_version": 4, "fragments": [], "semantic_edges": candidates}
    )
    assert second["status"] == "accepted"
    assert sorted(second["edgeIds"]) == sorted(first["edgeIds"])

    con = mature_learning.connect(db_path)
    try:
        assert (
            con.execute("SELECT count(*) FROM research_semantic_edges").fetchone()[0]
            == len(candidates) + 1
        )
    finally:
        con.close()


def test_validate_mode_accepts_derived_payload(tmp_path):
    service = _graph()
    derived = _derived(tmp_path, service)
    db_path = tmp_path / "memory.sqlite"
    memory = research_memory.ResearchMemoryService(db_path=db_path, graph_service=service)
    result = memory.validate_semantic_edges(
        {"schema_version": 4, "fragments": [], "semantic_edges": derived["candidates"]}
    )
    assert result["status"] == "accepted"
    assert result["semanticEdgeCount"] == len(derived["candidates"])
    con = mature_learning.connect(db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_semantic_edges").fetchone()[0] == 1
    finally:
        con.close()
