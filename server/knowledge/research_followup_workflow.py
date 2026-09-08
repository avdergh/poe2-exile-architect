"""Typed follow-up operations over private Research runtime and immutable receipts."""

from __future__ import annotations

import json
import re
from typing import Any
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scripts import research_mature_builds as runs
from server import paths
from server.runtime.file_lock import interprocess_file_lock
from . import research_followups as gaps
from . import research_memory, research_reacquisition as reacquire, research_retention, research_runtime
from . import research_workflow as workflow


class GapDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gapRef: str = Field(pattern=r"^rgap-[0-9a-f]{24}$")
    disposition: Literal["resolved", "not_applicable", "successor_evidence", "reopen"]
    rationale: str = Field(min_length=1, max_length=600)
    supportingWriteReceiptRef: str | None = Field(default=None, pattern=r"^rwr-[0-9a-f]{20}$")
    supportingRecordIds: list[str] | None = Field(default=None, min_length=1, max_length=100)


def _failure(code: str, **facts: Any) -> dict[str, Any]:
    return {"status": "rejected", "errorCode": code, **facts, "noRawMatureBuildMaterial": True}


def _context(run_ref: str, sample_id: str) -> dict[str, Any]:
    run_dir = workflow._run_dir(run_ref, require_queue=False)
    db = run_dir / runs.QUEUE_DB_FILENAME
    if db.is_file():
        rows = runs._fetch_cases(db)
        metadata = runs._read_metadata(db)
        patch = metadata.get("currentPatch", "unknown")
    else:
        audit = runs.read_run_audit(output_dir=workflow._product_runtime_root(), run_id=run_dir.name)
        if not audit:
            raise ValueError("research_run_not_found")
        rows = audit.get("samples") or []
        patch = audit.get("sourceGamePatch", "unknown")
    matching = [row for row in rows if row.get("sampleId") == sample_id]
    if len(matching) != 1 or matching[0].get("status") != "accepted":
        raise ValueError("accepted_research_sample_required")
    return {**matching[0], "sourceGamePatch": patch}


def get_followup_status(
    *, run_ref: str, sample_id: str, view: str = "gaps", cursor: int = 0, limit: int = 24,
) -> dict[str, Any]:
    workflow._run_dir(run_ref, require_queue=False)
    if view not in {"gaps", "events", "reacquisitions"}:
        return _failure("invalid_followup_view")
    if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 200:
        return _failure("followup_pagination_invalid")
    requests = reacquire.list_requests(
        workflow._product_runtime_root() / "reacquisition.sqlite",
        parent_run_ref=run_ref, sample_id=sample_id,
    )
    if view == "reacquisitions":
        return _bounded_status({
            "status": "ok", "runRef": run_ref, "sampleId": sample_id,
            "reacquisitions": requests[cursor:cursor + limit], "total": len(requests), "offset": cursor,
            "nextOffset": cursor + limit if cursor + limit < len(requests) else None,
        }, "reacquisitions", cursor)
    inspect = gaps.inspect_followups if view == "gaps" else gaps.inspect_followup_events
    result = inspect(
        db_path=workflow._product_runtime_root() / "followups.sqlite",
        memory_db_path=paths.mature_learning_path(), run_ref=run_ref, sample_id=sample_id,
        offset=cursor, limit=limit,
    )
    if result.get("status") == "ok":
        result["reacquisitionSummary"] = {
            "requestCount": len(requests),
            "activeCount": sum(item["status"] in {"reserved", "queued"} for item in requests),
            "latestRequest": requests[-1] if requests else None,
        }
    return _bounded_status(result, "gaps" if view == "gaps" else "events", cursor)


def _bounded_status(result: dict[str, Any], key: str, cursor: int) -> dict[str, Any]:
    result = workflow._without_paths(result)
    items = list(result.get(key) or [])
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 65536:
        if len(items) <= 1:
            return _failure("followup_item_exceeds_transport_budget")
        items.pop()
        result[key] = items
        result["nextOffset"] = cursor + len(items)
    return result


def submit_gap_review(
    *, run_ref: str, sample_id: str, expected_revision: int, request_id: str,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    workflow._run_dir(run_ref, require_queue=False)
    memory = paths.mature_learning_path()
    if not memory.is_file():
        return _failure("research_memory_unavailable")
    # Serialize evidence validation and appended decisions with accepted knowledge
    # writes and cleanup. The gap module never initializes or migrates Memory.
    with runs._ACCEPT_LOCK, interprocess_file_lock(runs._accept_lock_path(memory)):
        result = gaps.submit_followup_decisions(
            db_path=workflow._product_runtime_root() / "followups.sqlite", memory_db_path=memory,
            run_ref=run_ref, sample_id=sample_id, expected_revision=expected_revision,
            request_id=request_id, decisions=decisions,
        )
    return workflow._without_paths(result)


def _lineage_matches(request: dict[str, Any], metadata: dict[str, Any]) -> bool:
    return all(metadata.get(key) == request[field] for key, field in (
        ("reacquisitionParentRunRef", "parentRunRef"),
        ("reacquisitionParentSampleId", "sampleId"), ("reacquisitionRequestId", "requestId"),
    ))


def _accepted_receipt_matches(run_ref: str, row: dict[str, Any]) -> bool:
    memory = paths.mature_learning_path()
    if not memory.is_file() or not row.get("sampleId"):
        return False
    receipt = research_memory.ResearchMemoryService(db_path=memory, initialize_store=False).get_research_write_receipt(
        research_runtime.write_receipt_ref(run_ref, row["sampleId"])
    )
    if not receipt or receipt.get("runRef") != run_ref or receipt.get("sampleId") != row["sampleId"]:
        return False
    summary = receipt.get("acceptanceSummary") or {}
    context = summary.get("sourceContext") or {}
    return (
        receipt.get("provenance") == "transactional"
        and context.get("sourceHashRef") == row.get("sourceHashRef")
        and context.get("sourceHash") == row.get("sourceHash")
        and context.get("gamePatch") == row.get("sourceGamePatch")
        and any(row.get("sourceHashRef") in write.get("writtenSourceCaseRefs", [])
                for write in receipt.get("writtenMapping") or [])
    )


def _reconcile_request(request: dict[str, Any]) -> dict[str, Any]:
    """Finish a committed queue association after an interrupted collector response."""
    if request["status"] == "failed":
        return request
    child = workflow._run_dir(request["newRunRef"], require_queue=False)
    db = child / runs.QUEUE_DB_FILENAME
    ledger = workflow._product_runtime_root() / "reacquisition.sqlite"
    if db.is_file():
        rows = runs._fetch_cases(db)
        usable = [row for row in rows if row.get("status") != "import_failed"]
        if len(usable) != 1 or usable[0].get("characterRef") != request["characterRef"]:
            return {**request, "recoveryRequired": True, "recoveryReason": "target_queue_binding_incomplete"}
        row = usable[0]
        metadata = runs._read_metadata(db)
        if (not _lineage_matches(request, metadata) or row.get("league") != request["league"]
                or metadata.get("leagueUrl") != request["league"]):
            return {**request, "recoveryRequired": True, "recoveryReason": "target_queue_lineage_mismatch"}
        if request["status"] in {"reserved", "queued", "completed"}:
            try:
                request = reacquire.mark_queued(
                    ledger, request_id=request["requestId"], new_run_ref=request["newRunRef"],
                    source_hash=row["sourceHash"], source_patch=metadata["currentPatch"],
                    character_ref=row["characterRef"], league=request["league"],
                )
            except (ValueError, KeyError):
                return {**request, "recoveryRequired": True, "recoveryReason": "target_queue_source_mismatch"}
        if row.get("status") == "accepted" and row.get("finalizationStatus") == "complete":
            if not _accepted_receipt_matches(request["newRunRef"], {**row, "sourceGamePatch": metadata["currentPatch"]}):
                return {**request, "recoveryRequired": True, "recoveryReason": "accepted_child_receipt_required"}
            request = reacquire.finalize(
                ledger, request_id=request["requestId"], new_run_ref=request["newRunRef"],
            )
    else:
        audit = runs.read_run_audit(output_dir=workflow._product_runtime_root(), run_id=child.name)
        if audit and audit.get("status") == "archived" and request["status"] == "queued":
            samples = audit.get("samples") or []
            if (not _lineage_matches(request, audit) or len(samples) != 1
                    or samples[0].get("sourceHash") != request["sourceHash"]
                    or samples[0].get("characterRef") != request["characterRef"]
                    or samples[0].get("league") != request["league"]
                    or samples[0].get("sourceHashRef") not in {
                        f"source-hash:{request['sourceHash']}", f"source-hash:{request['sourceHash'][:16]}"
                    }
                    or audit.get("sourceGamePatch") != request["sourcePatch"]):
                return {**request, "recoveryRequired": True, "recoveryReason": "target_archive_binding_mismatch"}
            if audit.get("acceptedCount") == 1:
                if samples[0].get("status") != "accepted" or not _accepted_receipt_matches(
                    request["newRunRef"], {**samples[0], "sourceGamePatch": audit["sourceGamePatch"]}
                ):
                    return {**request, "recoveryRequired": True, "recoveryReason": "accepted_child_receipt_required"}
                request = reacquire.finalize(ledger, request_id=request["requestId"], new_run_ref=request["newRunRef"])
            else:
                request = reacquire.release(ledger, request_id=request["requestId"], new_run_ref=request["newRunRef"], reason_code="child_disposed")
    return request


def reacquire_source(
    *, run_ref: str, sample_id: str, request_id: str, action: str = "start", retention_days: int = 7,
) -> dict[str, Any]:
    """Explicitly re-find one hashed character; never fill a miss with another source."""
    workflow._run_dir(run_ref, require_queue=False)
    if action not in {"start", "status", "release"}:
        return _failure("invalid_reacquisition_action")
    research_retention.create_policy(retention_days=retention_days)
    runtime = workflow._product_runtime_root()
    ledger = runtime / "reacquisition.sqlite"
    prior = reacquire.get_request(ledger, request_id=request_id)
    if prior is not None:
        if prior["parentRunRef"] != run_ref or prior["sampleId"] != sample_id:
            return _failure("reacquisition_request_conflict")
        child = workflow._run_dir(prior["newRunRef"], require_queue=False)
        if action == "release":
            # The collector owns the child run lock until it has persisted its
            # queue or stopped. Time alone never transfers that ownership.
            with interprocess_file_lock(runs._run_lock_path(child / runs.QUEUE_DB_FILENAME)):
                prior = reacquire.get_request(ledger, request_id=request_id)
                prior = _reconcile_request(prior)
                if prior.get("recoveryRequired"):
                    return prior
                if prior["status"] in {"failed", "completed"}:
                    return {**prior, "idempotent": True}
                if (child / runs.QUEUE_DB_FILENAME).is_file() or child.with_name(child.name + ".cleanup-staging").exists():
                    return _failure("reacquisition_child_cleanup_required", newRunRef=prior["newRunRef"])
                return reacquire.release(ledger, request_id=request_id, new_run_ref=prior["newRunRef"], reason_code="explicit_release")
        # A reserved request is not a second grant to run the collector. A status
        # read may reconcile only a queue already committed by the first call.
        if prior["status"] == "reserved" and not (child / runs.QUEUE_DB_FILENAME).is_file():
            return {**prior, "idempotent": True, "recoveryRequired": True, "nextAction": "Wait for the collector or explicitly release the stopped request."}
        return {**_reconcile_request(prior), "idempotent": True}
    if action != "start":
        return _failure("reacquisition_request_not_found")
    try:
        context = _context(run_ref, sample_id)
    except ValueError as exc:
        return _failure(str(exc))
    state = get_followup_status(run_ref=run_ref, sample_id=sample_id, limit=1)
    if state.get("status") != "ok" or not state.get("openGapCount"):
        return _failure("open_research_gap_required")
    character = str(context.get("characterRef") or "")
    source_hash = str(context.get("sourceHash") or "")
    source_ref = str(context.get("sourceHashRef") or "")
    if (not re.fullmatch(r"character-hash:[0-9a-f]{16}", character)
            or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
            or source_ref not in {f"source-hash:{source_hash}", f"source-hash:{source_hash[:16]}"}):
        return _failure("research_source_not_locatable", nextAction="Provide a new source file with its actual source patch.")
    source_identity = state.get("sourceIdentity") or {}
    if (source_identity.get("sourceHashRef") != context.get("sourceHashRef")
            or (source_identity.get("sourceHash") and source_identity["sourceHash"] != source_hash)):
        return _failure("reacquisition_origin_source_mismatch")
    patch, league = workflow._source_patch_for_run(source_game_patch=None, league="current", offline=False, prior_run=None)
    run_id, child = runs._allocate_run_output_dir(runtime)
    child_ref = workflow._run_ref(run_id)
    try:
        request = reacquire.reserve(
            ledger, league=league, character_ref=character, parent_run_ref=run_ref,
            sample_id=sample_id, origin_fingerprint=state["originFingerprint"],
            request_id=request_id, new_run_ref=child_ref, origin_source_hash=source_hash,
            origin_patch=str(source_identity.get("gamePatch") or context["sourceGamePatch"]),
        )
    except (reacquire.ReacquisitionConflict, ValueError):
        child.rmdir()  # Newly allocated, verified empty directory only.
        concurrent = reacquire.get_request(ledger, request_id=request_id)
        if concurrent and all(concurrent.get(key) == value for key, value in {
            "parentRunRef": run_ref, "sampleId": sample_id, "originFingerprint": state["originFingerprint"],
            "league": league, "characterRef": character,
        }.items()):
            return {**concurrent, "idempotent": True}
        return _failure("reacquisition_scope_reserved")
    with interprocess_file_lock(runs._run_lock_path(child / runs.QUEUE_DB_FILENAME)):
        request = reacquire.get_request(ledger, request_id=request_id)
        if request["status"] != "reserved":
            return {**request, "idempotent": True}
        try:
            report = runs.queue_cases(
                league_url=league, current_patch=patch, output_dir=child, limit=1, worker_count=1,
                level_min=1, level_max=100, target_character_refs={character}, retention_days=retention_days,
                reacquisition_context={"parentRunRef": run_ref, "sampleId": sample_id, "requestId": request_id},
            )
            rows = runs._fetch_cases(child / runs.QUEUE_DB_FILENAME)
            usable = [row for row in rows if row.get("status") != "import_failed"]
            if not usable:
                request = reacquire.release(ledger, request_id=request_id, new_run_ref=child_ref, reason_code="target_not_found_in_search_scope")
                return {**request, "searchOutcome": "not_found_within_search_scope", "runRef": child_ref, "noRawMatureBuildMaterial": True}
            if (len(usable) != 1 or usable[0].get("characterRef") != character
                    or usable[0].get("league") != league):
                return _failure("reacquisition_target_mismatch", newRunRef=child_ref, recoveryRequired=True)
            row = usable[0]
            request = reacquire.mark_queued(
                ledger, request_id=request_id, new_run_ref=child_ref,
                source_hash=row["sourceHash"], source_patch=patch, character_ref=character, league=league,
            )
            return {**workflow._without_paths(report), "runId": run_id, "runRef": child_ref, "reacquisition": request}
        except Exception:
            # Preserve any committed queue/receipt. The original request can be
            # inspected/reconciled; an unfinished fetch is never blindly restarted.
            return _failure("research_reacquisition_interrupted", newRunRef=child_ref, requestId=request_id, recoveryRequired=True)
