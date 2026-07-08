"""Phase 4 semantic research memory service."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import copy_safety
from . import graph_tools
from . import mature_learning
from . import research_models

SHORT_CYCLE_MAX_DEPTH = 3
DIRECTIONAL_EDGE_TYPES = {
    "enables_mechanic",
    "scales_with",
    "mitigates_weakness_of",
    "requires_transition_gate",
    "has_modelability_caveat",
    "creates_failure_risk_for",
}
VALID_REVALIDATION_TARGET_KINDS = {"fragment", "semantic_edge", "build_pattern"}
VALID_REVALIDATION_OUTCOMES = {"still_valid", "invalidated", "changed_scope", "needs_review"}


class ResearchMemoryService:
    def __init__(
        self,
        *,
        db_path: Path | None = None,
        graph_service: graph_tools.GraphQueryService | None = None,
    ) -> None:
        self.db_path = db_path
        self.graph_service = graph_service
        mature_learning.initialize_store(db_path)

    def query_research_memory(
        self,
        query: str,
        *,
        component_keys: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        component_keys = sorted({str(key) for key in component_keys or [] if str(key).strip()})
        dedupe_ref = (
            "dq-"
            + _stable_hash({"query": _normalize_text(query), "component_keys": component_keys})[:16]
        )
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            self._record_dedupe_query(
                con,
                dedupe_ref=dedupe_ref,
                query=query,
                component_keys=component_keys,
                now=now,
            )
            rows = self._query_rows(con, query, component_keys, limit)
            results = [self._fragment_result(row) for row in rows]
            con.commit()
        finally:
            con.close()
        return {
            "status": "known",
            "dedupeQueryRef": dedupe_ref,
            "results": results,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def propose_research_fragments(
        self,
        payload: dict[str, Any],
        *,
        dedupe_query_ref: str | None = None,
    ) -> dict[str, Any]:
        if not dedupe_query_ref:
            result = research_models.rejection(
                "missing_dedupe_query",
                suggested_repair="Call query_research_memory before proposing a new fragment.",
            )
            self._record_rejection(payload, result)
            return result
        if not self._dedupe_query_ref_exists(dedupe_query_ref):
            result = research_models.rejection(
                "invalid_dedupe_query_ref",
                suggested_repair=(
                    "Call query_research_memory in this memory store before proposing a new "
                    "fragment, then pass back the returned dedupeQueryRef."
                ),
            )
            self._record_rejection(payload, result)
            return result

        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            fragment_ids: list[str] = []
            for fragment in output.fragments:
                duplicate = self._duplicate_fragment(con, fragment)
                if duplicate is not None:
                    result = research_models.rejection(
                        "duplicate_fragment_candidate",
                        proposal_id=duplicate,
                        suggested_repair="Call append_evidence_to_fragment for the existing fragment.",
                        facts={"existingFragmentIds": [duplicate]},
                    )
                    self._record_rejection(payload, result, con=con)
                    con.commit()
                    return result
                fragment_id = _fragment_id(fragment)
                self._insert_fragment(con, fragment_id, fragment, now)
                self._insert_fragment_evidence(
                    con,
                    fragment_id=fragment_id,
                    source_case_refs=fragment.source_case_refs,
                    safe_evidence_refs=fragment.safe_evidence_refs,
                    game_patch=fragment.game_patch,
                    passive_tree_version=fragment.passive_tree_version,
                    pob_version_or_commit=fragment.pob_version_or_commit,
                    visibility=fragment.visibility,
                    split=fragment.split,
                    knowledge_scope=fragment.knowledge_scope,
                    confidence=fragment.confidence,
                    now=now,
                )
                fragment_ids.append(fragment_id)
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "fragmentIds": fragment_ids,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def append_evidence_to_fragment(
        self,
        *,
        fragment_id: str,
        source_case_refs: list[str],
        safe_evidence_refs: list[str],
        game_patch: str,
        passive_tree_version: str,
        pob_version_or_commit: str,
        visibility: str,
        split: str,
        knowledge_scope: str,
        confidence: str,
    ) -> dict[str, Any]:
        copy_error = _copy_safety_error(
            {
                "source_case_refs": source_case_refs,
                "safe_evidence_refs": safe_evidence_refs,
                "game_patch": game_patch,
                "passive_tree_version": passive_tree_version,
                "pob_version_or_commit": pob_version_or_commit,
                "visibility": visibility,
                "split": split,
                "knowledge_scope": knowledge_scope,
                "confidence": confidence,
            }
        )
        if copy_error is not None:
            return copy_error
        con = mature_learning.connect(self.db_path)
        try:
            row = con.execute(
                "SELECT * FROM research_fragments WHERE fragment_id = ?",
                (fragment_id,),
            ).fetchone()
            if row is None:
                return research_models.rejection("missing_fragment")
            if (
                row["visibility"] != visibility
                or row["split"] != split
                or row["knowledge_scope"] != knowledge_scope
            ):
                return research_models.rejection("holdout_boundary_violation")
            now = _now()
            self._insert_fragment_evidence(
                con,
                fragment_id=fragment_id,
                source_case_refs=source_case_refs,
                safe_evidence_refs=safe_evidence_refs,
                game_patch=game_patch,
                passive_tree_version=passive_tree_version,
                pob_version_or_commit=pob_version_or_commit,
                visibility=visibility,
                split=split,
                knowledge_scope=knowledge_scope,
                confidence=confidence,
                now=now,
            )
            con.commit()
            count = con.execute(
                "SELECT evidence_count FROM research_fragments WHERE fragment_id = ?",
                (fragment_id,),
            ).fetchone()["evidence_count"]
        finally:
            con.close()
        return {
            "status": "accepted",
            "fragmentId": fragment_id,
            "evidenceCount": count,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def propose_semantic_edges(self, payload: dict[str, Any]) -> dict[str, Any]:
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            edge_ids: list[str] = []
            for edge in output.semantic_edges:
                resolution_error = self._endpoint_resolution_error(edge)
                if resolution_error is not None:
                    self._record_rejection(payload, resolution_error, con=con)
                    con.commit()
                    return resolution_error
                endpoint_error = self._endpoint_error(edge.source_key, edge.target_key)
                if endpoint_error is not None:
                    self._record_rejection(payload, endpoint_error, con=con)
                    con.commit()
                    return endpoint_error
                conflict = self._semantic_conflict(con, edge)
                if conflict is not None:
                    self._record_rejection(payload, conflict, con=con)
                    con.commit()
                    return conflict
                edge_id, source_key, target_key = _edge_identity(edge)
                planner_visible = _planner_visible(edge.status, edge.copy_safety_state)
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
                    ON CONFLICT(edge_id) DO UPDATE SET
                        rationale = excluded.rationale,
                        safe_evidence_refs = excluded.safe_evidence_refs,
                        status = excluded.status,
                        confidence = excluded.confidence,
                        copy_safety_state = excluded.copy_safety_state,
                        context_requirements = excluded.context_requirements,
                        affected_component_keys = excluded.affected_component_keys,
                        planner_visible = excluded.planner_visible,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        edge_id,
                        edge.source_key,
                        edge.target_key,
                        source_key,
                        target_key,
                        edge.edge_type,
                        edge.rationale,
                        _json(edge.source_case_refs),
                        _json(edge.safe_evidence_refs),
                        edge.game_patch,
                        edge.passive_tree_version,
                        edge.pob_version_or_commit,
                        edge.status,
                        edge.confidence,
                        edge.modelability,
                        edge.copy_safety_state,
                        _json(
                            [
                                item.model_dump(exclude_none=True, exclude_defaults=True)
                                for item in edge.context_requirements
                            ]
                        ),
                        _json(sorted(set(edge.affected_component_keys))),
                        edge.visibility,
                        edge.split,
                        edge.knowledge_scope,
                        edge.directionality,
                        planner_visible,
                        _json(
                            {
                                "game_patch": edge.game_patch,
                                "passive_tree_version": edge.passive_tree_version,
                                "pob_version_or_commit": edge.pob_version_or_commit,
                            }
                        ),
                        now,
                        now,
                        now,
                    ),
                )
                edge_ids.append(edge_id)
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "edgeIds": edge_ids,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def propose_build_patterns(self, payload: dict[str, Any]) -> dict[str, Any]:
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        observation_link_error = _pattern_observation_link_error(output)
        if observation_link_error is not None:
            self._record_rejection(payload, observation_link_error)
            return observation_link_error
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            observation_ids: list[str] = []
            pattern_ids: list[str] = []
            for observation in output.build_design_observations:
                resolution_error = self._observation_resolution_error(observation)
                if resolution_error is not None:
                    self._record_rejection(payload, resolution_error, con=con)
                    con.commit()
                    return resolution_error
                endpoint_error = self._component_endpoint_error(
                    [component.component_key for component in observation.components]
                )
                if endpoint_error is not None:
                    self._record_rejection(payload, endpoint_error, con=con)
                    con.commit()
                    return endpoint_error
                observation_id = _observation_id(observation)
                con.execute(
                    """
                    INSERT INTO research_build_design_observations(
                        observation_id, observation_type, title, summary, axes, components,
                        component_keys, source_case_refs, safe_evidence_refs, game_patch,
                        passive_tree_version, pob_version_or_commit, visibility, split,
                        knowledge_scope, copy_safety_state, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'passed', ?, ?)
                    ON CONFLICT(observation_id) DO UPDATE SET
                        summary = excluded.summary,
                        source_case_refs = excluded.source_case_refs,
                        safe_evidence_refs = excluded.safe_evidence_refs,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        observation_id,
                        observation.observation_type,
                        observation.title,
                        observation.summary,
                        _json(sorted(set(observation.axes))),
                        _json(
                            [
                                component.model_dump(exclude_none=True, exclude_defaults=True)
                                for component in observation.components
                            ]
                        ),
                        _json(
                            sorted(
                                {component.component_key for component in observation.components}
                            )
                        ),
                        _json(observation.source_case_refs),
                        _json(observation.safe_evidence_refs),
                        observation.game_patch,
                        observation.passive_tree_version,
                        observation.pob_version_or_commit,
                        observation.visibility,
                        observation.split,
                        observation.knowledge_scope,
                        now,
                        now,
                    ),
                )
                observation_ids.append(observation_id)

            for pattern in output.patterns:
                endpoint_error = self._component_endpoint_error(pattern.component_keys)
                if endpoint_error is not None:
                    self._record_rejection(payload, endpoint_error, con=con)
                    con.commit()
                    return endpoint_error
                pattern_id = _pattern_id(pattern)
                planner_visible = _pattern_planner_visible(pattern)
                con.execute(
                    """
                    INSERT INTO research_build_patterns(
                        pattern_id, pattern_type, title, summary, component_keys,
                        component_roles, confidence_tier, sample_count, family_count,
                        source_diversity_count, denominator, source_case_refs,
                        safe_evidence_refs, context_requirements, planner_hint,
                        verification_tasks, game_patch, passive_tree_version,
                        pob_version_or_commit, visibility, split, knowledge_scope,
                        status, copy_safety_state, current_version_context, planner_visible,
                        created_at, last_seen_at, last_validated_at, superseded_by_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              'valid', 'passed', ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(pattern_id) DO UPDATE SET
                        summary = excluded.summary,
                        source_case_refs = excluded.source_case_refs,
                        safe_evidence_refs = excluded.safe_evidence_refs,
                        confidence_tier = excluded.confidence_tier,
                        sample_count = excluded.sample_count,
                        family_count = excluded.family_count,
                        source_diversity_count = excluded.source_diversity_count,
                        status = excluded.status,
                        current_version_context = excluded.current_version_context,
                        planner_visible = excluded.planner_visible,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        pattern_id,
                        pattern.pattern_type,
                        pattern.title,
                        pattern.summary,
                        _json(sorted(set(pattern.component_keys))),
                        _json(dict(sorted(pattern.component_roles.items()))),
                        pattern.confidence_tier,
                        pattern.sample_count,
                        pattern.family_count,
                        pattern.source_diversity_count,
                        pattern.denominator,
                        _json(pattern.source_case_refs),
                        _json(pattern.safe_evidence_refs),
                        _json(
                            [
                                item.model_dump(exclude_none=True, exclude_defaults=True)
                                for item in pattern.context_requirements
                            ]
                        ),
                        pattern.planner_hint,
                        _json(pattern.verification_tasks),
                        pattern.game_patch,
                        pattern.passive_tree_version,
                        pattern.pob_version_or_commit,
                        pattern.visibility,
                        pattern.split,
                        pattern.knowledge_scope,
                        _json(
                            {
                                "game_patch": pattern.game_patch,
                                "passive_tree_version": pattern.passive_tree_version,
                                "pob_version_or_commit": pattern.pob_version_or_commit,
                            }
                        ),
                        planner_visible,
                        now,
                        now,
                        now,
                    ),
                )
                pattern_ids.append(pattern_id)
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "observationIds": observation_ids,
            "patternIds": pattern_ids,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def apply_patch_decay(
        self,
        *,
        changed_component_keys: list[str],
        new_version_context: dict[str, str],
    ) -> dict[str, Any]:
        changed = set(changed_component_keys)
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            fragment_rows = con.execute(
                "SELECT fragment_id, affected_component_keys, status FROM research_fragments"
            ).fetchall()
            fragments_updated = 0
            for row in fragment_rows:
                affected = set(_loads(row["affected_component_keys"], []))
                if not (changed & affected):
                    continue
                con.execute(
                    """
                    UPDATE research_fragments
                    SET status = 'needs_revalidation',
                        current_version_context = ?,
                        last_seen_at = ?
                    WHERE fragment_id = ?
                    """,
                    (_json(new_version_context), now, row["fragment_id"]),
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO research_decay_events(
                        event_id, target_kind, target_id, decay_scope, old_status, new_status,
                        changed_component_keys, new_version_context, created_at
                    ) VALUES (?, 'fragment', ?, 'component_scoped', ?, 'needs_revalidation', ?, ?, ?)
                    """,
                    (
                        "decay-" + _stable_hash([row["fragment_id"], changed_component_keys])[:16],
                        row["fragment_id"],
                        row["status"],
                        _json(sorted(changed)),
                        _json(new_version_context),
                        now,
                    ),
                )
                fragments_updated += 1
            edge_rows = con.execute(
                "SELECT edge_id, affected_component_keys, status FROM research_semantic_edges"
            ).fetchall()
            edges_updated = 0
            for row in edge_rows:
                affected = set(_loads(row["affected_component_keys"], []))
                if not (changed & affected):
                    continue
                con.execute(
                    """
                    UPDATE research_semantic_edges
                    SET status = 'needs_revalidation',
                        planner_visible = 0,
                        current_version_context = ?,
                        last_seen_at = ?
                    WHERE edge_id = ?
                    """,
                    (_json(new_version_context), now, row["edge_id"]),
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO research_decay_events(
                        event_id, target_kind, target_id, decay_scope, old_status, new_status,
                        changed_component_keys, new_version_context, created_at
                    ) VALUES (?, 'semantic_edge', ?, 'component_scoped', ?, 'needs_revalidation', ?, ?, ?)
                    """,
                    (
                        "decay-"
                        + _stable_hash(["edge", row["edge_id"], changed_component_keys])[:16],
                        row["edge_id"],
                        row["status"],
                        _json(sorted(changed)),
                        _json(new_version_context),
                        now,
                    ),
                )
                edges_updated += 1
            pattern_rows = con.execute(
                "SELECT pattern_id, component_keys, status FROM research_build_patterns"
            ).fetchall()
            patterns_updated = 0
            for row in pattern_rows:
                affected = set(_loads(row["component_keys"], []))
                if not (changed & affected):
                    continue
                con.execute(
                    """
                    UPDATE research_build_patterns
                    SET status = 'needs_revalidation',
                        planner_visible = 0,
                        current_version_context = ?,
                        last_seen_at = ?
                    WHERE pattern_id = ?
                    """,
                    (_json(new_version_context), now, row["pattern_id"]),
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO research_decay_events(
                        event_id, target_kind, target_id, decay_scope, old_status, new_status,
                        changed_component_keys, new_version_context, created_at
                    ) VALUES (?, 'build_pattern', ?, 'component_scoped', ?, 'needs_revalidation', ?, ?, ?)
                    """,
                    (
                        "decay-"
                        + _stable_hash(["pattern", row["pattern_id"], changed_component_keys])[:16],
                        row["pattern_id"],
                        row["status"],
                        _json(sorted(changed)),
                        _json(new_version_context),
                        now,
                    ),
                )
                patterns_updated += 1
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "itemsUpdated": fragments_updated,
            "edgesUpdated": edges_updated,
            "patternsUpdated": patterns_updated,
        }

    def submit_revalidation_result(
        self,
        *,
        target_kind: str,
        target_id: str,
        outcome: str,
        new_version_context: dict[str, str],
        safe_evidence_refs: list[str],
        affected_component_keys: list[str],
    ) -> dict[str, Any]:
        if target_kind not in VALID_REVALIDATION_TARGET_KINDS:
            return research_models.rejection("invalid_revalidation_target_kind")
        if outcome not in VALID_REVALIDATION_OUTCOMES:
            return research_models.rejection("invalid_revalidation_outcome")
        copy_error = _copy_safety_error(
            {
                "target_kind": target_kind,
                "target_id": target_id,
                "outcome": outcome,
                "new_version_context": new_version_context,
                "safe_evidence_refs": safe_evidence_refs,
                "affected_component_keys": affected_component_keys,
            }
        )
        if copy_error is not None:
            return copy_error
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            table, id_column = _revalidation_target_table(target_kind)
            row = con.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?", (target_id,)
            ).fetchone()
            if row is None:
                return research_models.rejection("missing_revalidation_target")
            event_id = (
                "rev-" + _stable_hash([target_kind, target_id, outcome, new_version_context])[:16]
            )
            if outcome == "still_valid":
                planner_visible_update = ""
                planner_visible_params: tuple[int, ...] = ()
                if target_kind in {"semantic_edge", "build_pattern"}:
                    planner_visible_update = ", planner_visible = ?"
                    planner_visible_params = (
                        _planner_visible("valid", str(row["copy_safety_state"])),
                    )
                con.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'valid',
                        game_patch = ?,
                        passive_tree_version = ?,
                        current_version_context = ?,
                        last_validated_at = ?,
                        last_seen_at = ?
                        {planner_visible_update}
                    WHERE {id_column} = ?
                    """,
                    (
                        new_version_context.get("game_patch", row["game_patch"]),
                        new_version_context.get(
                            "passive_tree_version", row["passive_tree_version"]
                        ),
                        _json(new_version_context),
                        now,
                        now,
                        *planner_visible_params,
                        target_id,
                    ),
                )
                successor_id = None
            elif outcome == "changed_scope":
                successor_id = target_id + "-successor-" + _stable_hash(new_version_context)[:8]
                planner_visible_update = (
                    ", planner_visible = 0"
                    if target_kind in {"semantic_edge", "build_pattern"}
                    else ""
                )
                con.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'deprecated',
                        superseded_by_id = ?
                        {planner_visible_update}
                    WHERE {id_column} = ?
                    """,
                    (successor_id, target_id),
                )
            else:
                successor_id = None
                planner_visible_update = (
                    ", planner_visible = 0"
                    if target_kind in {"semantic_edge", "build_pattern"}
                    else ""
                )
                con.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'needs_revalidation'
                        {planner_visible_update}
                    WHERE {id_column} = ?
                    """,
                    (target_id,),
                )
            con.execute(
                """
                INSERT OR REPLACE INTO research_revalidation_events(
                    event_id, target_kind, target_id, outcome, old_version_context,
                    new_version_context, safe_evidence_refs, affected_component_keys, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    target_kind,
                    target_id,
                    outcome,
                    row["current_version_context"],
                    _json(new_version_context),
                    _json(safe_evidence_refs),
                    _json(affected_component_keys),
                    now,
                ),
            )
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "targetId": target_id,
            "successorId": successor_id,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def _query_rows(
        self,
        con: sqlite3.Connection,
        query: str,
        component_keys: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        params: list[Any] = []
        where = [
            "visibility = 'creator_visible'",
            "split = 'train_context'",
            "copy_safety_state = 'passed'",
            "status IN ('valid', 'needs_revalidation')",
        ]
        ids: list[str] | None = None
        if query.strip():
            fts_query = _fts_query(query)
            fts_rows = con.execute(
                """
                SELECT fragment_id
                FROM research_fragment_fts
                WHERE research_fragment_fts MATCH ?
                ORDER BY bm25(research_fragment_fts)
                LIMIT ?
                """,
                (fts_query, max(limit * 4, limit)),
            ).fetchall()
            ids = [str(row["fragment_id"]) for row in fts_rows]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            where.append(f"fragment_id IN ({placeholders})")
            params.extend(ids)
        if component_keys:
            for key in component_keys:
                where.append(
                    """
                    EXISTS (
                        SELECT 1 FROM json_each(research_fragments.component_keys)
                        WHERE json_each.value = ?
                    )
                    """
                )
                params.append(key)
        sql = "SELECT * FROM research_fragments WHERE " + " AND ".join(where)
        sql += " ORDER BY evidence_count DESC, fragment_id LIMIT ?"
        params.append(limit)
        return list(con.execute(sql, params).fetchall())

    def _record_dedupe_query(
        self,
        con: sqlite3.Connection,
        *,
        dedupe_ref: str,
        query: str,
        component_keys: list[str],
        now: str,
    ) -> None:
        con.execute(
            """
            INSERT INTO research_dedupe_queries(
                dedupe_query_ref, query_hash, query_text_preview, component_keys,
                visibility, split, knowledge_scope, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, 'creator_visible', 'train_context', 'global_seed', ?, ?)
            ON CONFLICT(dedupe_query_ref) DO UPDATE SET
                query_text_preview = excluded.query_text_preview,
                component_keys = excluded.component_keys,
                last_seen_at = excluded.last_seen_at
            """,
            (
                dedupe_ref,
                _stable_hash({"query": _normalize_text(query), "component_keys": component_keys}),
                _normalize_text(query)[:240],
                _json(component_keys),
                now,
                now,
            ),
        )

    def _dedupe_query_ref_exists(self, dedupe_query_ref: str) -> bool:
        if not re.fullmatch(r"dq-[A-Fa-f0-9]{16}", str(dedupe_query_ref or "")):
            return False
        con = mature_learning.connect(self.db_path)
        try:
            row = con.execute(
                "SELECT 1 FROM research_dedupe_queries WHERE dedupe_query_ref = ? LIMIT 1",
                (dedupe_query_ref,),
            ).fetchone()
            return row is not None
        finally:
            con.close()

    def _fragment_result(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memoryItemId": row["fragment_id"],
            "fragmentId": row["fragment_id"],
            "matchedFragmentIds": [row["fragment_id"]],
            "matchedSemanticEdgeIds": [],
            "sourceCaseRefs": _loads(row["source_case_refs"], []),
            "safeEvidenceRefs": _loads(row["safe_evidence_refs"], []),
            "confidence": row["confidence"],
            "modelability": row["modelability"],
            "gamePatch": row["game_patch"],
            "passiveTreeVersion": row["passive_tree_version"],
            "status": row["status"],
            "copySafetyState": row["copy_safety_state"],
            "contextCaveats": ["needs_revalidation"]
            if row["status"] == "needs_revalidation"
            else [],
            "noRawMatureBuildMaterial": True,
        }

    def _duplicate_fragment(
        self,
        con: sqlite3.Connection,
        fragment: research_models.CleanFragmentProposal,
    ) -> str | None:
        row = con.execute(
            """
            SELECT fragment_id FROM research_fragments
            WHERE dedupe_key = ?
              AND visibility = ?
              AND split = ?
              AND knowledge_scope = ?
            LIMIT 1
            """,
            (
                _fragment_dedupe_key(fragment),
                fragment.visibility,
                fragment.split,
                fragment.knowledge_scope,
            ),
        ).fetchone()
        return str(row["fragment_id"]) if row else None

    def _insert_fragment(
        self,
        con: sqlite3.Connection,
        fragment_id: str,
        fragment: research_models.CleanFragmentProposal,
        now: str,
    ) -> None:
        chunk_text = _chunk_text(fragment)
        version = {
            "game_patch": fragment.game_patch,
            "passive_tree_version": fragment.passive_tree_version,
            "pob_version_or_commit": fragment.pob_version_or_commit,
        }
        con.execute(
            """
            INSERT INTO research_fragments(
                fragment_id, dedupe_key, fragment_type, title, summary, reusable_principle,
                chunk_text, component_keys, source_case_refs, safe_evidence_refs, confidence,
                copyability_risk, lifecycle_stages, modelability, verification_tasks,
                conditions, risks, game_patch, passive_tree_version, pob_version_or_commit,
                visibility, split, knowledge_scope, status, copy_safety_state,
                current_version_context, affected_component_keys, evidence_count,
                created_at, last_seen_at, last_validated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid',
                      'passed', ?, ?, 0, ?, ?, ?)
            ON CONFLICT(fragment_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                chunk_text = excluded.chunk_text
            """,
            (
                fragment_id,
                _fragment_dedupe_key(fragment),
                fragment.fragment_type,
                fragment.title,
                fragment.summary,
                fragment.reusable_principle,
                chunk_text,
                _json(sorted(set(fragment.component_keys))),
                _json(fragment.source_case_refs),
                _json(fragment.safe_evidence_refs),
                fragment.confidence,
                fragment.copyability_risk,
                _json(fragment.lifecycle_stages),
                fragment.modelability,
                _json(fragment.verification_tasks),
                _json(fragment.conditions),
                _json(fragment.risks),
                fragment.game_patch,
                fragment.passive_tree_version,
                fragment.pob_version_or_commit,
                fragment.visibility,
                fragment.split,
                fragment.knowledge_scope,
                _json(version),
                _json(sorted(set(fragment.component_keys))),
                now,
                now,
                now,
            ),
        )

    def _insert_fragment_evidence(
        self,
        con: sqlite3.Connection,
        *,
        fragment_id: str,
        source_case_refs: list[str],
        safe_evidence_refs: list[str],
        game_patch: str,
        passive_tree_version: str,
        pob_version_or_commit: str,
        visibility: str,
        split: str,
        knowledge_scope: str,
        confidence: str,
        now: str,
    ) -> str:
        evidence_id = (
            "rfe-"
            + _stable_hash(
                {
                    "fragment_id": fragment_id,
                    "source_case_refs": sorted(source_case_refs),
                    "safe_evidence_refs": sorted(safe_evidence_refs),
                    "visibility": visibility,
                    "split": split,
                    "knowledge_scope": knowledge_scope,
                }
            )[:16]
        )
        con.execute(
            """
            INSERT INTO research_fragment_evidence(
                evidence_id, fragment_id, source_case_refs, safe_evidence_refs, game_patch,
                passive_tree_version, pob_version_or_commit, visibility, split, knowledge_scope,
                confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                safe_evidence_refs = excluded.safe_evidence_refs,
                confidence = excluded.confidence
            """,
            (
                evidence_id,
                fragment_id,
                _json(source_case_refs),
                _json(safe_evidence_refs),
                game_patch,
                passive_tree_version,
                pob_version_or_commit,
                visibility,
                split,
                knowledge_scope,
                confidence,
                now,
            ),
        )
        con.execute(
            """
            UPDATE research_fragments
            SET evidence_count = (
                SELECT count(*) FROM research_fragment_evidence
                WHERE fragment_id = research_fragments.fragment_id
            ),
                last_seen_at = ?
            WHERE fragment_id = ?
            """,
            (now, fragment_id),
        )
        return evidence_id

    def _endpoint_error(self, source_key: str, target_key: str) -> dict[str, Any] | None:
        if self.graph_service is None:
            return research_models.rejection(
                "graph_service_unavailable",
                caveats=["semantic edge endpoint validation requires a graph service"],
                facts={
                    "endpointAssessment": _endpoint_assessment(
                        "graph_snapshot_unavailable",
                        [],
                    )
                },
            )
        keys = getattr(self.graph_service, "_nodes_by_key", {})
        missing = [key for key in (source_key, target_key) if key not in keys]
        if missing:
            return research_models.rejection(
                "missing_endpoint",
                caveats=[
                    "endpoint is not present in the current physical graph snapshot",
                    "treat as source coverage gap until static source ingestion proves otherwise",
                ],
                suggested_repair=(
                    "Do not classify this as hallucination from this rejection alone. "
                    "First verify whether the component exists in current game data, then add or "
                    "refresh the Phase 2/3 static-source graph snapshot."
                ),
                facts={
                    "missingEndpointKeys": missing,
                    "endpointAssessment": _endpoint_assessment(
                        "source_coverage_gap",
                        missing,
                    ),
                },
            )
        return None

    def _component_endpoint_error(self, component_keys: list[str]) -> dict[str, Any] | None:
        if self.graph_service is None:
            return research_models.rejection(
                "graph_service_unavailable",
                caveats=["pattern endpoint validation requires a graph service"],
                facts={
                    "endpointAssessment": _endpoint_assessment("graph_snapshot_unavailable", [])
                },
            )
        keys = getattr(self.graph_service, "_nodes_by_key", {})
        missing = sorted({key for key in component_keys if key and key not in keys})
        if missing:
            return research_models.rejection(
                "missing_endpoint",
                caveats=[
                    "pattern component endpoint is not present in the current physical graph snapshot",
                    "treat as source coverage gap until static source ingestion proves otherwise",
                ],
                facts={
                    "missingEndpointKeys": missing,
                    "endpointAssessment": _endpoint_assessment("source_coverage_gap", missing),
                },
            )
        return None

    def _observation_resolution_error(
        self,
        observation: research_models.BuildDesignObservation,
    ) -> dict[str, Any] | None:
        if self.graph_service is None:
            return None
        snapshot_id = getattr(getattr(self.graph_service, "snapshot", None), "snapshot_id", None)
        nodes_by_key = getattr(self.graph_service, "_nodes_by_key", {})
        for component in observation.components:
            evidence = component.resolution
            expected_key = component.component_key
            if evidence is None:
                return research_models.rejection(
                    "missing_endpoint_resolution",
                    caveats=[
                        f"pattern component {expected_key} must include resolve_graph_component evidence"
                    ],
                )
            if (
                evidence.stable_key != expected_key
                or expected_key not in evidence.evidence_path_nodes
            ):
                return research_models.rejection(
                    "endpoint_resolution_mismatch",
                    caveats=["pattern component resolution does not match component_key"],
                )
            if snapshot_id is not None and evidence.snapshot_id != snapshot_id:
                return research_models.rejection("stale_endpoint_resolution")
            node = nodes_by_key.get(expected_key)
            if node is not None and set(getattr(node, "source_refs", ())) != set(
                evidence.source_refs
            ):
                return research_models.rejection(
                    "endpoint_resolution_mismatch",
                    caveats=["pattern component resolver source refs do not match graph evidence"],
                )
        return None

    def _endpoint_resolution_error(
        self,
        edge: research_models.SemanticEdgeProposal,
    ) -> dict[str, Any] | None:
        if self.graph_service is None:
            return None
        snapshot_id = getattr(getattr(self.graph_service, "snapshot", None), "snapshot_id", None)
        nodes_by_key = getattr(self.graph_service, "_nodes_by_key", {})
        checks = (
            ("source", edge.source_key, edge.source_resolution),
            ("target", edge.target_key, edge.target_resolution),
        )
        for role, expected_key, evidence in checks:
            if evidence is None:
                return research_models.rejection(
                    "missing_endpoint_resolution",
                    caveats=[f"{role} endpoint must include resolve_graph_component evidence"],
                    suggested_repair=(
                        "Call graph_tool_query with tool_name='resolve_graph_component' for each "
                        "semantic edge endpoint and include the resolved evidence."
                    ),
                )
            if (
                evidence.stable_key != expected_key
                or expected_key not in evidence.evidence_path_nodes
            ):
                return research_models.rejection(
                    "endpoint_resolution_mismatch",
                    caveats=[f"{role} endpoint resolution does not match the proposed stable key"],
                    suggested_repair="Use the stable_key returned by resolve_graph_component.",
                )
            if snapshot_id is not None and evidence.snapshot_id != snapshot_id:
                return research_models.rejection(
                    "stale_endpoint_resolution",
                    caveats=[f"{role} endpoint was resolved against a different graph snapshot"],
                    suggested_repair="Re-run resolve_graph_component against the current graph snapshot.",
                )
            node = nodes_by_key.get(expected_key)
            if node is not None:
                expected_source_refs = set(getattr(node, "source_refs", ()))
                supplied_source_refs = set(evidence.source_refs)
                if expected_source_refs != supplied_source_refs:
                    return research_models.rejection(
                        "endpoint_resolution_mismatch",
                        caveats=[
                            f"{role} endpoint resolver source refs do not match graph evidence"
                        ],
                        suggested_repair=(
                            "Use the sourceRefs returned by graph_tool_query "
                            "resolve_graph_component for this endpoint."
                        ),
                    )
        return None

    def _semantic_conflict(
        self,
        con: sqlite3.Connection,
        edge: research_models.SemanticEdgeProposal,
    ) -> dict[str, Any] | None:
        if edge.edge_type not in DIRECTIONAL_EDGE_TYPES:
            return None
        inverse = con.execute(
            """
            SELECT edge_id FROM research_semantic_edges
            WHERE source_key = ?
              AND target_key = ?
              AND edge_type = ?
              AND visibility = ?
              AND split = ?
              AND knowledge_scope = ?
              AND directionality = 'directional'
              AND planner_visible = 1
            LIMIT 1
            """,
            (
                edge.target_key,
                edge.source_key,
                edge.edge_type,
                edge.visibility,
                edge.split,
                edge.knowledge_scope,
            ),
        ).fetchone()
        if inverse:
            return research_models.rejection(
                "semantic_cycle_or_conflict",
                facts={"maxDepthChecked": SHORT_CYCLE_MAX_DEPTH},
            )

        cycle = con.execute(
            """
            WITH RECURSIVE walk(node, depth) AS (
                SELECT target_key, 1
                FROM research_semantic_edges
                WHERE source_key = ?
                  AND visibility = ?
                  AND split = ?
                  AND knowledge_scope = ?
                  AND directionality = 'directional'
                  AND planner_visible = 1
                UNION ALL
                SELECT e.target_key, walk.depth + 1
                FROM research_semantic_edges e
                JOIN walk ON e.source_key = walk.node
                WHERE walk.depth < ?
                  AND e.visibility = ?
                  AND e.split = ?
                  AND e.knowledge_scope = ?
                  AND e.directionality = 'directional'
                  AND e.planner_visible = 1
            )
            SELECT 1 FROM walk WHERE node = ? LIMIT 1
            """,
            (
                edge.target_key,
                edge.visibility,
                edge.split,
                edge.knowledge_scope,
                SHORT_CYCLE_MAX_DEPTH,
                edge.visibility,
                edge.split,
                edge.knowledge_scope,
                edge.source_key,
            ),
        ).fetchone()
        if cycle:
            return research_models.rejection(
                "semantic_cycle_or_conflict",
                facts={"maxDepthChecked": SHORT_CYCLE_MAX_DEPTH},
            )
        return None

    def _record_rejection(
        self,
        payload: dict[str, Any],
        result: dict[str, Any],
        *,
        con: sqlite3.Connection | None = None,
    ) -> None:
        owned = con is None
        connection = con or mature_learning.connect(self.db_path)
        try:
            proposal_hash = _stable_hash(_safe_projection(payload))
            visibility, split, scope = _proposal_bucket(payload)
            rejection_id = (
                "rj-"
                + _stable_hash(
                    {
                        "proposal_hash": proposal_hash,
                        "error_code": result.get("errorCode"),
                        "visibility": visibility,
                        "split": split,
                        "knowledge_scope": scope,
                    }
                )[:16]
            )
            now = _now()
            connection.execute(
                """
                INSERT INTO research_rejected_proposals(
                    rejection_id, proposal_hash, error_code, visibility, split, knowledge_scope,
                    retry_count, caveats, suggested_repair, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(rejection_id) DO UPDATE SET
                    retry_count = retry_count + 1,
                    caveats = excluded.caveats,
                    suggested_repair = excluded.suggested_repair,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    rejection_id,
                    proposal_hash,
                    str(result.get("errorCode") or "unknown"),
                    visibility,
                    split,
                    scope,
                    _json(result.get("caveats") or []),
                    str(result.get("suggestedRepair") or ""),
                    now,
                    now,
                ),
            )
            if owned:
                connection.commit()
        finally:
            if owned:
                connection.close()


def _copy_safety_error(payload: Any) -> dict[str, Any] | None:
    paths = copy_safety.find_forbidden_paths(payload)
    if paths:
        return research_models.rejection("copy_safety_violation", caveats=["forbidden raw field"])
    flags = copy_safety.copyability_flags(payload)
    if flags:
        return research_models.rejection("copy_safety_violation", caveats=flags)
    return None


def _endpoint_assessment(
    classification: str,
    missing_endpoint_keys: list[str],
) -> dict[str, Any]:
    reason = {
        "graph_snapshot_unavailable": (
            "No physical graph snapshot was available, so endpoint reality could not be assessed."
        ),
        "source_coverage_gap": (
            "The current physical graph snapshot lacks the proposed endpoint. This can be a static "
            "source coverage gap for a real game entity, so it is not evidence of hallucination by itself."
        ),
    }.get(classification, "Endpoint reality was not assessed.")
    return {
        "classification": classification,
        "hallucinationVerdict": "not_assessed",
        "candidateEndpointKeys": sorted(set(missing_endpoint_keys)),
        "missingEndpointKeys": sorted(set(missing_endpoint_keys)),
        "reason": reason,
        "requiresStaticSourceReview": True,
    }


def _pattern_observation_link_error(
    output: research_models.ResearcherOutput,
) -> dict[str, Any] | None:
    if not output.patterns:
        return None
    if not output.build_design_observations:
        return research_models.rejection(
            "missing_build_design_observation",
            caveats=[
                "Build pattern proposals must be submitted with same-batch BuildDesignObservation evidence."
            ],
            suggested_repair=(
                "First extract BuildDesignObservation components with resolver evidence, then submit "
                "the pattern in the same propose_build_patterns payload."
            ),
        )
    for pattern in output.patterns:
        pattern_keys = set(pattern.component_keys)
        supporting_observations = [
            observation
            for observation in output.build_design_observations
            if _observation_matches_pattern_bucket(observation, pattern)
            and pattern_keys.issubset(
                {component.component_key for component in observation.components}
            )
        ]
        if not supporting_observations:
            observed_keys = {
                component.component_key
                for observation in output.build_design_observations
                if _observation_matches_pattern_bucket(observation, pattern)
                for component in observation.components
            }
            return research_models.rejection(
                "missing_build_design_observation",
                caveats=[
                    "Each pattern must be covered by at least one same-bucket same-version BuildDesignObservation containing all pattern component keys."
                ],
                facts={
                    "missingObservationComponentKeys": sorted(pattern_keys - observed_keys),
                    "requiredComponentKeys": sorted(pattern_keys),
                },
            )
    return None


def _observation_matches_pattern_bucket(
    observation: research_models.BuildDesignObservation,
    pattern: research_models.BuildPatternProposal,
) -> bool:
    return (
        observation.visibility == pattern.visibility
        and observation.split == pattern.split
        and observation.knowledge_scope == pattern.knowledge_scope
        and observation.game_patch == pattern.game_patch
        and observation.passive_tree_version == pattern.passive_tree_version
        and observation.pob_version_or_commit == pattern.pob_version_or_commit
    )


def _revalidation_target_table(target_kind: str) -> tuple[str, str]:
    if target_kind == "fragment":
        return "research_fragments", "fragment_id"
    if target_kind == "semantic_edge":
        return "research_semantic_edges", "edge_id"
    if target_kind == "build_pattern":
        return "research_build_patterns", "pattern_id"
    raise ValueError(f"unsupported revalidation target kind: {target_kind}")


def _planner_visible(status: str, copy_safety_state: str) -> int:
    return 1 if status == "valid" and copy_safety_state == "passed" else 0


def _fragment_id(fragment: research_models.CleanFragmentProposal) -> str:
    return (
        "rf-"
        + _stable_hash(
            {
                "dedupe_key": _fragment_dedupe_key(fragment),
                "visibility": fragment.visibility,
                "split": fragment.split,
                "knowledge_scope": fragment.knowledge_scope,
                "version": {
                    "game_patch": fragment.game_patch,
                    "passive_tree_version": fragment.passive_tree_version,
                },
            }
        )[:16]
    )


def _fragment_dedupe_key(fragment: research_models.CleanFragmentProposal) -> str:
    return _stable_hash(
        {
            "fragment_type": fragment.fragment_type,
            "title": _normalize_text(fragment.title),
            "summary": _normalize_text(fragment.summary),
            "principle": _normalize_text(fragment.reusable_principle),
            "component_keys": sorted(set(fragment.component_keys)),
            "lifecycle_stages": sorted(set(fragment.lifecycle_stages)),
            "modelability": fragment.modelability,
        }
    )


def _chunk_text(fragment: research_models.CleanFragmentProposal) -> str:
    parts = [
        fragment.title,
        fragment.summary,
        fragment.reusable_principle,
        " ".join(fragment.component_keys),
        " ".join(fragment.conditions),
        " ".join(fragment.risks),
        " ".join(fragment.verification_tasks),
    ]
    return "\n".join(part for part in parts if part)


def _edge_identity(edge: research_models.SemanticEdgeProposal) -> tuple[str, str, str]:
    if edge.edge_type == "synergizes_with":
        endpoints = sorted([edge.source_key, edge.target_key])
        source_key, target_key = endpoints[0], endpoints[1]
    else:
        source_key, target_key = edge.source_key, edge.target_key
    payload = {
        "edge_type": edge.edge_type,
        "endpoints": [source_key, target_key],
        "visibility": edge.visibility,
        "split": edge.split,
        "knowledge_scope": edge.knowledge_scope,
        "version": {
            "game_patch": edge.game_patch,
            "passive_tree_version": edge.passive_tree_version,
            "pob_version_or_commit": edge.pob_version_or_commit,
        },
    }
    return "rse-" + _stable_hash(payload)[:16], source_key, target_key


def _observation_id(observation: research_models.BuildDesignObservation) -> str:
    return (
        "bdo-"
        + _stable_hash(
            {
                "observation_type": observation.observation_type,
                "title": _normalize_text(observation.title),
                "axes": sorted(set(observation.axes)),
                "component_keys": sorted(
                    {component.component_key for component in observation.components}
                ),
                "visibility": observation.visibility,
                "split": observation.split,
                "knowledge_scope": observation.knowledge_scope,
                "version": {
                    "game_patch": observation.game_patch,
                    "passive_tree_version": observation.passive_tree_version,
                },
            }
        )[:16]
    )


def _pattern_id(pattern: research_models.BuildPatternProposal) -> str:
    return (
        "bdp-"
        + _stable_hash(
            {
                "pattern_type": pattern.pattern_type,
                "title": _normalize_text(pattern.title),
                "component_keys": sorted(set(pattern.component_keys)),
                "visibility": pattern.visibility,
                "split": pattern.split,
                "knowledge_scope": pattern.knowledge_scope,
                "version": {
                    "game_patch": pattern.game_patch,
                    "passive_tree_version": pattern.passive_tree_version,
                },
            }
        )[:16]
    )


def _pattern_planner_visible(pattern: research_models.BuildPatternProposal) -> int:
    return 1 if pattern.visibility == "creator_visible" and pattern.split == "train_context" else 0


def _proposal_bucket(payload: Any) -> tuple[str, str, str]:
    if not isinstance(payload, dict):
        return "unknown", "unknown", "unknown"
    for key in ("fragments", "semantic_edges", "build_design_observations", "patterns"):
        values = payload.get(key)
        if isinstance(values, list) and values and isinstance(values[0], dict):
            row = values[0]
            return (
                str(row.get("visibility") or "unknown"),
                str(row.get("split") or "unknown"),
                str(row.get("knowledge_scope") or "unknown"),
            )
    return "unknown", "unknown", "unknown"


def _safe_projection(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            str(key): _safe_projection(value)
            for key, value in payload.items()
            if not copy_safety.find_forbidden_paths({key: value})
        }
    if isinstance(payload, list):
        return [_safe_projection(item) for item in payload]
    if isinstance(payload, str):
        if copy_safety.copyability_flags(payload):
            return "redacted-copyable-text"
        return payload[:240]
    return payload


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _fts_query(value: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_:]+", value)
    return " ".join(f'"{term}"' for term in terms) if terms else '""'
