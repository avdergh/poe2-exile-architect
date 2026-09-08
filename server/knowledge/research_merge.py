"""Model-authored, reviewer-approved deep-record merge preview and apply gates.

The service never decides semantic equivalence.  It validates a bounded model proposal, shows the
recall/evidence impact, and applies only an explicitly approved, revision-pinned plan.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from server.runtime.file_lock import interprocess_file_lock

from . import (
    copy_safety,
    mature_learning,
    research_identity,
    research_claim_writes,
    research_memory,
    research_models,
    research_runtime,
)


PLAN_REPORT_ID = "research-merge-plan-v1"
ALLOWED_ACTIONS = {
    "merge_into_head",
    "keep_distinct",
    "deprecate_incorrect",
}
DISPOSITIONS = {"preserved", "revised", "retired_with_evidence"}
MERGE_FIELDS = {
    "title",
    "summary",
    "content",
    "content_language",
    "length_exception_reason",
    "component_keys",
    "component_mentions",
    "conditions",
    "failure_conditions",
    "typed_payload",
    "class_key",
    "ascendancy_key",
    "extraction_method_version",
    "record_schema_version",
    "game_patch",
    "passive_tree_version",
    "pob_version_or_commit",
    "visibility",
    "split",
    "knowledge_scope",
    "status",
    "copy_safety_state",
    "source_state_scope",
}
PRIMARY_SOURCE_KINDS = {"official_ggg", "pinned_pob", "poe2_wiki_revision"}


class ResearchMergeService:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else mature_learning.mature_learning_path()
        mature_learning.initialize_store(self.db_path)

    def inspect_candidates(
        self,
        *,
        knowledge_scope: str | None = None,
        build_family_key: str | None = None,
        record_kind: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 50))
        where = [
            "superseded_by_id IS NULL",
            "status IN ('valid', 'needs_revalidation')",
            "build_family_key IS NOT NULL",
        ]
        params: list[Any] = []
        if knowledge_scope:
            where.append("knowledge_scope = ?")
            params.append(str(knowledge_scope))
        if build_family_key:
            where.append("build_family_key = ?")
            params.append(str(build_family_key))
        if record_kind:
            where.append("record_kind = ?")
            params.append(str(record_kind))
        con = mature_learning.connect(self.db_path)
        try:
            rows = con.execute(
                "SELECT record_id, knowledge_scope, build_family_key, record_kind, title, "
                "component_keys, record_schema_version, status, projection_hash "
                "FROM deep_research_records WHERE "
                + " AND ".join(where)
                + " ORDER BY knowledge_scope, build_family_key, record_kind, record_id LIMIT 500",
                params,
            ).fetchall()
        finally:
            con.close()
        candidates: list[dict[str, Any]] = []
        for index, left in enumerate(rows):
            left_components = set(_loads(left["component_keys"], []))
            for right in rows[index + 1 :]:
                if (
                    left["knowledge_scope"],
                    left["build_family_key"],
                    left["record_kind"],
                ) != (
                    right["knowledge_scope"],
                    right["build_family_key"],
                    right["record_kind"],
                ):
                    continue
                shared = sorted(left_components & set(_loads(right["component_keys"], [])))
                same_title = str(left["title"]).strip() == str(right["title"]).strip()
                if not same_title and not shared:
                    continue
                candidates.append(
                    {
                        "candidateOnly": True,
                        "recordIds": [str(left["record_id"]), str(right["record_id"])],
                        "knowledgeScope": str(left["knowledge_scope"]),
                        "buildFamilyKey": str(left["build_family_key"]),
                        "recordKind": str(left["record_kind"]),
                        "matchSignals": {
                            "sameExactTitle": same_title,
                            "sharedComponentKeys": shared[:12],
                        },
                        "recordSchemas": [
                            int(left["record_schema_version"]),
                            int(right["record_schema_version"]),
                        ],
                        "semanticDecisionRequired": True,
                    }
                )
                if len(candidates) >= bounded_limit:
                    break
            if len(candidates) >= bounded_limit:
                break
        return {
            "reportId": "research-merge-candidates-v1",
            "status": "ok",
            "candidateCount": len(candidates),
            "candidates": candidates,
            "caveats": [
                "Match signals discover candidates only; they never authorize merge or supersession."
            ],
            "noRawMatureBuildMaterial": True,
        }

    def preview(self, plan: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = _validate_plan_shape(plan)
            con = mature_learning.connect(self.db_path)
            try:
                revision = research_runtime.get_memory_revision(con)
                items = [self._preview_item(con, item) for item in normalized["items"]]
            finally:
                con.close()
        except (ValueError, research_models.ValidationError) as exc:
            return _error("research_merge_plan_invalid", str(exc))
        plan_hash = _stable_hash({"plan": normalized, "memoryRevision": revision})
        return {
            "reportId": "research-merge-preview-v1",
            "status": "preview_ready",
            "expectedMemoryRevision": revision,
            "mergePlanHash": plan_hash,
            "itemCount": len(items),
            "writeItemCount": sum(item["wouldWrite"] for item in items),
            "items": items,
            "requiresUserApproval": bool(any(item["wouldWrite"] for item in items)),
            "noRawMatureBuildMaterial": True,
        }

    def apply(
        self,
        plan: dict[str, Any],
        *,
        expected_memory_revision: int,
        merge_plan_hash: str,
        user_approved: bool,
    ) -> dict[str, Any]:
        if not user_approved:
            return _error("research_merge_user_approval_required", "user_approved must be true")
        preview = self.preview(plan)
        if preview.get("status") != "preview_ready":
            return preview
        if (
            int(preview["expectedMemoryRevision"]) != int(expected_memory_revision)
            or str(preview["mergePlanHash"]) != str(merge_plan_hash)
        ):
            return _error(
                "research_merge_preview_stale",
                "Memory revision or merge plan changed; generate a new preview",
            )
        normalized = _validate_plan_shape(plan)
        if not any(item["action"] != "keep_distinct" for item in normalized["items"]):
            return {
                "reportId": "research-merge-apply-v1",
                "status": "no_change",
                "memoryRevision": expected_memory_revision,
                "appliedItemCount": 0,
                "noRawMatureBuildMaterial": True,
            }

        with interprocess_file_lock(research_runtime.research_write_lock_path(self.db_path)):
            con = mature_learning.connect(self.db_path)
            try:
                con.execute("BEGIN IMMEDIATE")
                current_revision = research_runtime.get_memory_revision(con)
                if current_revision != int(expected_memory_revision):
                    con.rollback()
                    return _error(
                        "research_merge_preview_stale",
                        "Memory changed after preview; generate a new preview",
                    )
                applied = [
                    self._apply_item(con, item)
                    for item in normalized["items"]
                    if item["action"] != "keep_distinct"
                ]
                new_revision = research_runtime.bump_memory_revision(con)
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                con.close()
        return {
            "reportId": "research-merge-apply-v1",
            "status": "applied",
            "memoryRevisionBefore": expected_memory_revision,
            "memoryRevisionAfter": new_revision,
            "appliedItemCount": len(applied),
            "items": applied,
            "noRawMatureBuildMaterial": True,
        }

    def _preview_item(self, con: Any, item: dict[str, Any]) -> dict[str, Any]:
        rows = _load_rows(con, item["sourceRecordIds"])
        target = next((row for row in rows if row["record_id"] == item["targetRecordId"]), None)
        if target is None:
            raise ValueError("targetRecordId must be included in sourceRecordIds")
        _validate_source_rows(rows)
        if item["action"] == "keep_distinct":
            return {
                "action": "keep_distinct",
                "targetRecordId": item["targetRecordId"],
                "sourceRecordIds": item["sourceRecordIds"],
                "wouldWrite": False,
                "recallImpact": "all active heads remain unchanged",
            }
        proposal = _validated_proposal(item, rows, target)
        family = _family_identity(con, target)
        knowledge_key = research_identity.knowledge_key(proposal, family)
        if not knowledge_key:
            raise ValueError("mergedRecord does not produce a canonical knowledge identity")
        valid_projection = research_runtime.projection_hash(
            {**proposal.model_dump(mode="json"), "source_state_scope": proposal.source_state_scope}
        )
        witnesses = _projection_witnesses(con, rows, valid_projection)
        final_status = "valid" if witnesses else "needs_revalidation"
        final_projection = research_runtime.projection_hash(
            {
                **proposal.model_dump(mode="json"),
                "status": final_status,
                "source_state_scope": proposal.source_state_scope,
            }
        )
        final_id = _select_merge_target(
            con, rows, target, proposal, item["action"], knowledge_key, final_projection
        )
        _validate_claim_destinations(
            con, rows, _projection_witness_rows(con, rows, valid_projection), knowledge_key
        )
        return {
            "action": item["action"],
            "targetRecordId": item["targetRecordId"],
            "sourceRecordIds": item["sourceRecordIds"],
            "proposedHeadRecordId": final_id,
            "proposedKnowledgeKey": knowledge_key,
            "proposedProjectionHash": final_projection,
            "wouldWrite": True,
            "wouldRemainCreateAuthorizing": bool(witnesses),
            "projectionWitnessSourceCaseRefs": witnesses,
            "before": {
                "activeRecordIds": [str(row["record_id"]) for row in rows],
                "titles": sorted({str(row["title"]) for row in rows}),
                "componentKeys": sorted(
                    {key for row in rows for key in _loads(row["component_keys"], [])}
                ),
                "familyKey": str(target["build_family_key"] or ""),
                "recordKind": str(target["record_kind"]),
            },
            "after": {
                "activeRecordIds": [final_id],
                "title": proposal.title,
                "componentKeys": proposal.component_keys,
                "status": final_status,
            },
            "retiredFields": [
                entry["field"]
                for entry in item["fieldDispositions"]
                if entry["disposition"] == "retired_with_evidence"
            ],
            "reviewerExternalResearch": item["reviewer"]["externalResearch"],
        }

    def _apply_item(self, con: Any, item: dict[str, Any]) -> dict[str, Any]:
        rows = _load_rows(con, item["sourceRecordIds"])
        target = next(row for row in rows if row["record_id"] == item["targetRecordId"])
        _validate_source_rows(rows)
        proposal = _validated_proposal(item, rows, target)
        family = _family_identity(con, target)
        knowledge_key = research_identity.knowledge_key(proposal, family)
        if not knowledge_key:
            raise ValueError("mergedRecord does not produce a canonical knowledge identity")
        service = research_memory.ResearchMemoryService(initialize_store=False)
        valid_projection = research_runtime.projection_hash(
            {**proposal.model_dump(mode="json"), "source_state_scope": proposal.source_state_scope}
        )
        witness_rows = _projection_witness_rows(con, rows, valid_projection)
        persisted_proposal = (
            proposal
            if witness_rows
            else proposal.model_copy(update={"status": "needs_revalidation"})
        )
        final_projection = research_runtime.projection_hash(persisted_proposal.model_dump(mode="json"))
        final_id = _select_merge_target(
            con, rows, target, persisted_proposal, item["action"], knowledge_key, final_projection
        )
        _validate_claim_destinations(con, rows, witness_rows, knowledge_key)
        values = service._deep_record_values(
            persisted_proposal,
            record_id=final_id,
            build_family_key=str(target["build_family_key"] or "") or None,
            knowledge_key=knowledge_key,
            evidence_count=0,
            now=_now(),
        )
        projection = str(values["projection_hash"] or "")
        values["evidence_count"] = len({str(row["source_case_ref"]) for row in witness_rows})
        values["source_case_refs"] = json.dumps(
            sorted({str(row["source_case_ref"]) for row in witness_rows}), ensure_ascii=False
        )
        values["safe_evidence_refs"] = json.dumps(
            sorted({ref for row in witness_rows for ref in _loads(row["safe_evidence_refs"], [])}),
            ensure_ascii=False,
        )
        existing = con.execute(
            "SELECT record_id, created_at, superseded_by_id FROM deep_research_records "
            "WHERE record_id = ?",
            (final_id,),
        ).fetchone()
        source_ids = {str(row["record_id"]) for row in rows}
        if existing is not None and str(existing["record_id"]) not in source_ids:
            raise ValueError("proposed canonical head is occupied by an unrelated record")
        if existing is not None:
            values["created_at"] = existing["created_at"]
        for row in rows:
            record_id = str(row["record_id"])
            # Preserve old claims as unresolved history. Only exact witnesses below may
            # acquire the final content; retirement itself cannot confer new evidence.
            con.execute(
                "UPDATE deep_research_record_evidence SET record_id = NULL, binding_issue = ? "
                "WHERE record_id = ?",
                ("merge_content_revised" if record_id == final_id else "record_retired", record_id),
            )
            if record_id == final_id:
                continue
            con.execute(
                "UPDATE deep_research_records SET status = 'deprecated', superseded_by_id = ?, "
                "last_seen_at = ? WHERE record_id = ?",
                (final_id, _now(), record_id),
            )
            con.execute(
                "UPDATE deep_research_records SET superseded_by_id = ? "
                "WHERE superseded_by_id = ? AND record_id != ?",
                (final_id, record_id, final_id),
            )
        columns = tuple(values)
        if existing is None:
            con.execute(
                f"INSERT INTO deep_research_records({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
        else:
            updates = [column for column in columns if column != "record_id"]
            con.execute(
                "UPDATE deep_research_records SET " + ",".join(f"{column}=?" for column in updates)
                + " WHERE record_id=?",
                (*(values[column] for column in updates), final_id),
            )
        for witness in witness_rows:
            con.execute(
                """
                INSERT INTO deep_research_record_evidence(
                    knowledge_scope, knowledge_key, source_case_ref, safe_evidence_refs,
                    observed_component_keys, observed_component_mentions, conditions,
                    failure_conditions, game_patch, passive_tree_version, pob_version_or_commit,
                    accepted_projection_hash, source_state_scope, first_seen_at, last_seen_at,
                    record_id, binding_issue, source_claim_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(knowledge_scope, knowledge_key, source_case_ref, source_claim_key,
                            game_patch, passive_tree_version) DO UPDATE SET
                    safe_evidence_refs = excluded.safe_evidence_refs,
                    observed_component_keys = excluded.observed_component_keys,
                    observed_component_mentions = excluded.observed_component_mentions,
                    conditions = excluded.conditions,
                    failure_conditions = excluded.failure_conditions,
                    game_patch = excluded.game_patch,
                    passive_tree_version = excluded.passive_tree_version,
                    pob_version_or_commit = excluded.pob_version_or_commit,
                    accepted_projection_hash = excluded.accepted_projection_hash,
                    source_state_scope = excluded.source_state_scope,
                    record_id = excluded.record_id,
                    binding_issue = NULL,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    proposal.knowledge_scope,
                    knowledge_key,
                    witness["source_case_ref"],
                    witness["safe_evidence_refs"],
                    witness["observed_component_keys"],
                    witness["observed_component_mentions"],
                    witness["conditions"],
                    witness["failure_conditions"],
                    witness["game_patch"],
                    witness["passive_tree_version"],
                    witness["pob_version_or_commit"],
                    projection,
                    witness["source_state_scope"],
                    witness["first_seen_at"],
                    _now(),
                    final_id,
                    witness["source_claim_key"],
                ),
            )
        if witness_rows:
            research_claim_writes.refresh_record_evidence(con, final_id, _now())
        return {
            "action": item["action"],
            "targetRecordId": item["targetRecordId"],
            "headRecordId": final_id,
            "knowledgeKey": knowledge_key,
            "status": values["status"],
            "projectionWitnessCount": len({str(row["source_case_ref"]) for row in witness_rows}),
            "supersededRecordIds": sorted(
                str(row["record_id"]) for row in rows if str(row["record_id"]) != final_id
            ),
        }


def _validate_plan_shape(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("reportId") != PLAN_REPORT_ID:
        raise ValueError(f"reportId must be {PLAN_REPORT_ID}")
    raw_items = plan.get("items") if isinstance(plan.get("items"), list) else []
    forbidden_paths = [
        f"items[{index}].mergedRecord.{path}"
        for index, item in enumerate(raw_items)
        if isinstance(item, dict) and isinstance(item.get("mergedRecord"), dict)
        for path in copy_safety.find_forbidden_paths(item["mergedRecord"])
    ]
    durable_flags = [
        flag
        for item in raw_items
        if isinstance(item, dict) and isinstance(item.get("mergedRecord"), dict)
        for flag in copy_safety.durable_knowledge_flags(item["mergedRecord"])
    ]
    if forbidden_paths or durable_flags or copy_safety.contains_raw_url(plan):
        detail = ", ".join(forbidden_paths[:8]) if forbidden_paths else "full_url"
        if durable_flags:
            detail = ", ".join(sorted(set(durable_flags))[:8])
        raise ValueError("merge plan contains forbidden raw fields or full URLs: " + detail)
    items = plan.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError("items must contain 1-50 merge decisions")
    normalized = {"reportId": PLAN_REPORT_ID, "items": []}
    seen_sources: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "action",
            "targetRecordId",
            "sourceRecordIds",
            "mergedRecord",
            "fieldDispositions",
            "reviewer",
            "requiresExternalResearch",
        }:
            raise ValueError("merge item must contain only the canonical fields")
        action = str(item.get("action") or "")
        if action not in ALLOWED_ACTIONS:
            raise ValueError("invalid merge action")
        target = _record_id(item.get("targetRecordId"))
        sources = [_record_id(value) for value in item.get("sourceRecordIds") or []]
        if not sources or len(sources) != len(set(sources)) or target not in sources:
            raise ValueError("sourceRecordIds must be unique and include targetRecordId")
        if seen_sources & set(sources):
            raise ValueError("one record cannot participate in multiple merge items")
        seen_sources.update(sources)
        if action == "keep_distinct":
            merged = None
            dispositions: list[dict[str, Any]] = []
        else:
            merged = item.get("mergedRecord")
            if not isinstance(merged, dict):
                raise ValueError("write actions require a complete mergedRecord")
            dispositions = _field_dispositions(item.get("fieldDispositions"))
        reviewer = _reviewer(item.get("reviewer"), bool(item.get("requiresExternalResearch")))
        normalized["items"].append(
            {
                "action": action,
                "targetRecordId": target,
                "sourceRecordIds": sources,
                "mergedRecord": merged,
                "fieldDispositions": dispositions,
                "reviewer": reviewer,
                "requiresExternalResearch": bool(item.get("requiresExternalResearch")),
            }
        )
    return normalized


def _field_dispositions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("fieldDispositions must be a list")
    result: list[dict[str, Any]] = []
    fields: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "field",
            "disposition",
            "reason",
            "safeEvidenceRefs",
        }:
            raise ValueError("field disposition must contain only canonical fields")
        field = str(item.get("field") or "")
        disposition = str(item.get("disposition") or "")
        reason = str(item.get("reason") or "").strip()
        evidence = _safe_refs(item.get("safeEvidenceRefs"))
        if field not in MERGE_FIELDS or field in fields:
            raise ValueError("fieldDispositions must cover each canonical field exactly once")
        if disposition not in DISPOSITIONS or not reason or len(reason) > 320:
            raise ValueError("invalid field disposition")
        if disposition == "retired_with_evidence" and not evidence:
            raise ValueError("retired fields require safe evidence")
        fields.add(field)
        result.append(
            {
                "field": field,
                "disposition": disposition,
                "reason": reason,
                "safeEvidenceRefs": evidence,
            }
        )
    if fields != MERGE_FIELDS:
        raise ValueError("fieldDispositions must cover all canonical deep-record fields")
    return result


def _reviewer(value: Any, requires_external: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "verdict",
        "fieldIssues",
        "externalResearch",
    }:
        raise ValueError("reviewer must contain verdict, fieldIssues and externalResearch")
    verdict = str(value.get("verdict") or "")
    issues = value.get("fieldIssues")
    external = value.get("externalResearch")
    if verdict not in {"approve", "reject"} or not isinstance(issues, list):
        raise ValueError("invalid reviewer verdict or fieldIssues")
    if verdict == "approve" and issues:
        raise ValueError("approved reviewer result cannot contain field issues")
    if not isinstance(external, dict) or set(external) != {
        "status",
        "reason",
        "queries",
        "sources",
        "conclusion",
        "confidence",
        "residualUncertainty",
    }:
        raise ValueError("externalResearch must use the canonical fields")
    status = str(external.get("status") or "")
    if status not in {"not_needed", "completed", "blocked"}:
        raise ValueError("invalid externalResearch status")
    sources = external.get("sources")
    if not isinstance(sources, list) or len(sources) > 12:
        raise ValueError("externalResearch.sources must contain at most 12 entries")
    normalized_sources: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict) or set(source) != {
            "kind",
            "versionOrRevision",
            "assessment",
            "safeEvidenceRef",
        }:
            raise ValueError("external research sources must use canonical fields")
        kind = str(source.get("kind") or "")
        if kind not in PRIMARY_SOURCE_KINDS | {"other_discovery_only"}:
            raise ValueError("invalid external research source kind")
        normalized_sources.append(
            {
                "kind": kind,
                "versionOrRevision": str(source.get("versionOrRevision") or "")[:160],
                "assessment": str(source.get("assessment") or "")[:320],
                "safeEvidenceRef": _safe_ref(source.get("safeEvidenceRef")),
            }
        )
    if requires_external and status != "completed":
        raise ValueError("unfamiliar or disputed PoE2 knowledge requires completed external research")
    if status == "completed" and not any(
        source["kind"] in PRIMARY_SOURCE_KINDS for source in normalized_sources
    ):
        raise ValueError("completed external research requires at least one primary source")
    if verdict == "approve" and status == "blocked":
        raise ValueError("blocked external research cannot approve a merge")
    if verdict != "approve":
        raise ValueError("only reviewer-approved write decisions can enter a merge plan")
    return {
        "verdict": verdict,
        "fieldIssues": [str(item)[:320] for item in issues],
        "externalResearch": {
            "status": status,
            "reason": str(external.get("reason") or "")[:320],
            "queries": [str(item)[:200] for item in (external.get("queries") or [])[:8]],
            "sources": normalized_sources,
            "conclusion": str(external.get("conclusion") or "")[:500],
            "confidence": str(external.get("confidence") or ""),
            "residualUncertainty": str(external.get("residualUncertainty") or "")[:320],
        },
    }


def _load_rows(con: Any, record_ids: list[str]) -> list[Any]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = con.execute(
        f"SELECT * FROM deep_research_records WHERE record_id IN ({placeholders})",
        record_ids,
    ).fetchall()
    if len(rows) != len(record_ids):
        raise ValueError("one or more sourceRecordIds do not exist")
    return rows


def _validate_source_rows(rows: list[Any]) -> None:
    scopes = {str(row["knowledge_scope"]) for row in rows}
    families = {str(row["build_family_key"] or "") for row in rows}
    kinds = {str(row["record_kind"]) for row in rows}
    if len(scopes) != 1 or len(families) != 1 or len(kinds) != 1 or "" in families:
        raise ValueError("merge sources must share one scope, Family and record kind")
    for row in rows:
        if row["superseded_by_id"] is not None:
            raise ValueError("merge sources must be active heads")
        if str(row["status"]) not in {"valid", "needs_revalidation"}:
            raise ValueError("merge sources must be valid or needs_revalidation")


def _validated_proposal(item: dict[str, Any], rows: list[Any], target: Any) -> Any:
    proposal = research_models.DeepResearchRecordProposal.model_validate(item["mergedRecord"])
    version_fields = ("game_patch", "passive_tree_version", "pob_version_or_commit")
    if any(
        row[field] != target[field] or getattr(proposal, field) != target[field]
        for row in rows for field in version_fields
    ):
        raise ValueError("merge_cannot_relabel_source_versions; preserve separate version records")
    union_sources = sorted(
        {source for row in rows for source in _loads(row["source_case_refs"], [])}
    )
    allowed_evidence = {
        evidence for row in rows for evidence in _loads(row["safe_evidence_refs"], [])
    }
    if proposal.source_case_refs != union_sources:
        raise ValueError("mergedRecord.source_case_refs must equal the exact source union")
    if not set(proposal.safe_evidence_refs) <= allowed_evidence:
        raise ValueError("mergedRecord cannot introduce new evidence refs")
    if proposal.research_group_id != str(target["research_group_id"]):
        raise ValueError("mergedRecord cannot change research_group_id")
    if proposal.knowledge_scope != str(target["knowledge_scope"]):
        raise ValueError("mergedRecord cannot change knowledge_scope")
    if proposal.record_kind != str(target["record_kind"]):
        raise ValueError("mergedRecord cannot change record_kind")
    if proposal.copy_safety_state != "passed":
        raise ValueError("mergedRecord must pass copy-safety")
    if proposal.status != "valid":
        raise ValueError("mergedRecord must propose a valid head; the service derives revalidation")
    if copy_safety.durable_knowledge_flags(proposal.model_dump(mode="json")):
        raise ValueError("mergedRecord failed copy-safety")
    return proposal


def _family_identity(con: Any, target: Any) -> research_identity.BuildFamilyIdentity:
    row = con.execute(
        "SELECT * FROM research_build_families WHERE knowledge_scope = ? AND build_family_key = ?",
        (target["knowledge_scope"], target["build_family_key"]),
    ).fetchone()
    if row is None:
        raise ValueError("target Build Family does not exist")
    primary = _loads(row["primary_skill_keys"], None)
    if not primary:
        primary = [str(row["primary_skill_key"] or "")]
    return research_identity.BuildFamilyIdentity(
        ascendancy_key=str(row["ascendancy_key"]),
        primary_skill_keys=tuple(sorted(value for value in primary if value)),
        secondary_skill_keys=tuple(sorted(_loads(row["secondary_skill_keys"], []))),
        authoritative_key=str(row["build_family_key"]),
    )


def _projection_witnesses(con: Any, rows: list[Any], projection: str) -> list[str]:
    return sorted({str(row["source_case_ref"]) for row in _projection_witness_rows(con, rows, projection)})


def _projection_witness_rows(con: Any, rows: list[Any], projection: str) -> list[Any]:
    witnesses: list[Any] = []
    for row in rows:
        if str(row["projection_hash"] or "") != projection or not row["knowledge_key"]:
            continue
        witnesses.extend(
            con.execute(
                "SELECT * FROM deep_research_record_evidence WHERE knowledge_scope = ? "
                "AND knowledge_key = ? AND accepted_projection_hash = ? AND record_id = ? "
                "AND binding_issue IS NULL",
                (row["knowledge_scope"], row["knowledge_key"], projection, row["record_id"]),
            ).fetchall()
        )
    return witnesses


def _select_merge_target(
    con: Any, rows: list[Any], target: Any, proposal: Any,
    action: str, knowledge_key: str, projection: str,
) -> str:
    """Choose a conclusion identity without retiring another condition branch."""
    source_ids = {str(row["record_id"]) for row in rows}
    if action == "merge_into_head":
        final_id = str(target["record_id"])
    else:
        if projection == str(target["projection_hash"] or ""):
            raise ValueError("deprecate_incorrect requires a distinct corrected identity")
        anchor = research_runtime.canonical_record_id(proposal.knowledge_scope, knowledge_key)
        occupied = con.execute(
            "SELECT 1 FROM deep_research_records WHERE record_id = ?", (anchor,)
        ).fetchone()
        final_id = (
            research_claim_writes.variant_record_id(proposal.knowledge_scope, knowledge_key, projection)
            if occupied else anchor
        )
    occupants = con.execute(
        "SELECT record_id FROM deep_research_records WHERE record_id = ? OR "
        "(knowledge_scope = ? AND knowledge_key = ? AND projection_hash = ? "
        "AND superseded_by_id IS NULL)",
        (final_id, proposal.knowledge_scope, knowledge_key, projection),
    ).fetchall()
    if any(str(row["record_id"]) not in source_ids for row in occupants):
        raise ValueError("proposed conclusion is occupied by an unrelated active head")
    return final_id


def _validate_claim_destinations(
    con: Any, rows: list[Any], witnesses: list[Any], knowledge_key: str
) -> None:
    selected_ids = {str(row["record_id"]) for row in rows}
    for witness in witnesses:
        current = con.execute(
            "SELECT record_id FROM deep_research_record_evidence WHERE knowledge_scope = ? "
            "AND knowledge_key = ? AND source_case_ref = ? AND source_claim_key = ? "
            "AND game_patch = ? AND passive_tree_version = ?",
            (witness["knowledge_scope"], knowledge_key, witness["source_case_ref"],
             witness["source_claim_key"], witness["game_patch"], witness["passive_tree_version"]),
        ).fetchone()
        if current is not None and str(current["record_id"] or "") not in selected_ids:
            raise ValueError("merge_source_claim_destination_not_in_reviewed_records")


def _record_id(value: Any) -> str:
    text = str(value or "")
    if not text.startswith("drr-") or len(text) > 80:
        raise ValueError("record IDs must use the drr- prefix")
    return text


def _safe_refs(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 32:
        raise ValueError("safeEvidenceRefs must be a list with at most 32 entries")
    return [_safe_ref(item) for item in value]


def _safe_ref(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 240 or "http://" in text or "https://" in text:
        raise ValueError("evidence refs must be bounded opaque references")
    return text


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, json.JSONDecodeError):
        return default


def proposal_payload_from_row(row: Any) -> dict[str, Any]:
    """Return the complete safe proposal projection for model/reviewer fixtures and tooling."""

    return {
        "research_group_id": row["research_group_id"],
        "record_kind": row["record_kind"],
        "title": row["title"],
        "summary": row["summary"],
        "content": row["content"],
        "content_language": row["content_language"],
        "length_exception_reason": row["length_exception_reason"],
        "component_keys": _loads(row["component_keys"], []),
        "component_mentions": _loads(row["component_mentions"], []),
        "source_case_refs": _loads(row["source_case_refs"], []),
        "safe_evidence_refs": _loads(row["safe_evidence_refs"], []),
        "conditions": _loads(row["conditions"], []),
        "failure_conditions": _loads(row["failure_conditions"], []),
        "typed_payload": _loads(row["typed_payload"], {}),
        "class_key": row["class_key"],
        "ascendancy_key": row["ascendancy_key"],
        "extraction_method_version": row["extraction_method_version"],
        "record_schema_version": int(row["record_schema_version"]),
        "game_patch": row["game_patch"],
        "passive_tree_version": row["passive_tree_version"],
        "pob_version_or_commit": row["pob_version_or_commit"],
        "visibility": row["visibility"],
        "split": row["split"],
        "knowledge_scope": row["knowledge_scope"],
        "status": row["status"],
        "copy_safety_state": row["copy_safety_state"],
        "source_state_scope": row["source_state_scope"],
    }


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "rmp-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": code,
        "caveats": [str(message)[:500]],
        "noRawMatureBuildMaterial": True,
    }
