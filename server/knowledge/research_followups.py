"""Research 缺口的安全目录及追加处置事件；不修改知识正文或原始 write receipt。"""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from . import copy_safety, research_completion, research_runtime


_IDENTITY_FIELDS = (
    "sourceHash", "gamePatch", "passiveTreeVersion", "knowledgeScope"
)
_OPTIONAL_IDENTITY_FIELDS = ("pobVersionOrCommit", "sourceSnapshotHash", "activeSets")
_STATES = {"active_state", "alternate_weapon_state", "state_agnostic"}
_SOURCE_HASH_REF = re.compile(r"source-hash:(?:[0-9a-f]{16}|[0-9a-f]{64})\Z")
_FULL_SOURCE_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS followup_origins (
    receipt_ref TEXT PRIMARY KEY, run_ref TEXT NOT NULL, sample_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL, source_identity TEXT NOT NULL,
    completion_summary TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, UNIQUE(run_ref, sample_id)
);
CREATE TABLE IF NOT EXISTS followup_gaps (
    gap_ref TEXT PRIMARY KEY, receipt_ref TEXT NOT NULL,
    location TEXT NOT NULL, diagnostic TEXT NOT NULL,
    UNIQUE(receipt_ref, location),
    FOREIGN KEY(receipt_ref) REFERENCES followup_origins(receipt_ref)
);
CREATE TABLE IF NOT EXISTS followup_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_ref TEXT NOT NULL,
    revision INTEGER NOT NULL, gap_ref TEXT NOT NULL, disposition TEXT NOT NULL,
    rationale TEXT NOT NULL, support_receipt TEXT, support_fingerprint TEXT,
    support_records TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(gap_ref) REFERENCES followup_gaps(gap_ref)
);
CREATE TABLE IF NOT EXISTS followup_requests (
    receipt_ref TEXT NOT NULL, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
    response TEXT NOT NULL, PRIMARY KEY(receipt_ref, request_id)
);
"""


class FollowupError(ValueError):
    """不包含调用方原文的可安全公开错误。"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe(value: Any) -> None:
    if copy_safety.find_forbidden_paths(value) or copy_safety.copyability_flags(value):
        raise FollowupError("followup_copy_safety_failed")


def _load(value: str, kind: type) -> Any:
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise FollowupError("followup_receipt_invalid") from exc
    if not isinstance(parsed, kind):
        raise FollowupError("followup_receipt_invalid")
    return parsed


def _memory(path: str | Path) -> sqlite3.Connection:
    # 不触发建库、迁移或 seed 导入；缺少原 receipt 不能由调用者补造。
    if not Path(path).is_file():
        raise FollowupError("followup_memory_missing")
    con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("BEGIN")
    return con


def _ledger(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(_SCHEMA)
    return con


def _receipt(con: sqlite3.Connection, ref: str) -> dict[str, Any]:
    if not re.fullmatch(r"rwr-[0-9a-f]{20}", str(ref)):
        raise FollowupError("followup_receipt_ref_invalid")
    row = con.execute(
        "SELECT * FROM research_record_write_receipts WHERE receipt_ref=?", (ref,)
    ).fetchone()
    if row is None:
        raise FollowupError("followup_receipt_missing")
    value = dict(row)
    value["fingerprint"] = research_runtime.stable_hash(value)
    value["summary"] = _load(value["acceptance_summary"], dict)
    value["writes"] = _load(value["record_writes_json"], list)
    if any(not isinstance(write, dict) for write in value["writes"]):
        raise FollowupError("followup_receipt_invalid")
    for write in value["writes"]:
        refs = write.get("writtenSourceCaseRefs", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise FollowupError("followup_receipt_invalid")
        for key in ("sourceGamePatch", "sourcePassiveTreeVersion", "sourcePobVersionOrCommit",
                    "knowledgeScope", "sourceStateScope", "recordId", "sourceClaimKey",
                    "afterProjectionHash", "knowledgeKey"):
            if write.get(key) is not None and not isinstance(write[key], str):
                raise FollowupError("followup_receipt_invalid")
    value["completion"] = research_completion.completion_summary(value["summary"])
    value["identity"] = _source_identity(value)
    return value


def _source_identity(receipt: dict[str, Any]) -> dict[str, Any]:
    context = receipt["summary"].get("sourceContext")
    context = context if isinstance(context, dict) else {}
    identity: dict[str, Any] = {}
    for field in (*_IDENTITY_FIELDS, "sourceHashRef", "sourceStateScope", *_OPTIONAL_IDENTITY_FIELDS):
        value = context.get(field)
        if isinstance(value, str) and value and len(value) <= 200:
            identity[field] = value
        elif field == "activeSets" and isinstance(value, dict):
            # 只保留四个活动身份，不保存完整配置。
            if set(value) <= {"skillSet", "itemSet", "passiveSpec", "configSet"} and all(
                isinstance(part, str | int) and not isinstance(part, bool)
                and len(str(part)) <= 40 for part in value.values()
            ):
                identity[field] = value
    writes = receipt["writes"]
    columns = {
        "gamePatch": "sourceGamePatch", "passiveTreeVersion": "sourcePassiveTreeVersion",
        "knowledgeScope": "knowledgeScope", "sourceStateScope": "sourceStateScope",
        "pobVersionOrCommit": "sourcePobVersionOrCommit",
    }
    for field, column in columns.items():
        values = {write.get(column) for write in writes if isinstance(write.get(column), str)}
        if len(values) == 1 and all(write.get(column) in values for write in writes):
            value = next(iter(values))
            if field in identity and identity[field] not in ("unknown", value):
                raise FollowupError("followup_source_identity_conflict")
            if value:
                identity[field] = value
    scopes = {write.get("sourceStateScope") for write in writes}
    if scopes and all(isinstance(scope, str) and scope in _STATES for scope in scopes):
        identity["sourceStateScopes"] = sorted(scopes)
    elif identity.get("sourceStateScope") in _STATES:
        identity["sourceStateScopes"] = [identity["sourceStateScope"]]
    refs = {
        ref for write in writes for ref in write.get("writtenSourceCaseRefs", [])
        if isinstance(ref, str)
    }
    if len(refs) == 1 and _SOURCE_HASH_REF.fullmatch(next(iter(refs))):
        source = next(iter(refs))
        if identity.get("sourceHashRef", source) != source:
            raise FollowupError("followup_source_identity_conflict")
        identity["sourceHashRef"] = source
    source_ref = str(identity.get("sourceHashRef") or "")
    full_hash = identity.get("sourceHash")
    if _SOURCE_HASH_REF.fullmatch(source_ref):
        suffix = source_ref.removeprefix("source-hash:")
        # 历史完整 ref 本身就是不可变的完整 hash；短 ref 不得扩展或猜补。
        if full_hash is None and len(suffix) == 64:
            identity["sourceHash"] = full_hash = suffix
        if full_hash is not None and (
            not _FULL_SOURCE_HASH.fullmatch(str(full_hash)) or not full_hash.startswith(suffix)
        ):
            raise FollowupError("followup_source_identity_conflict")
    _safe(identity)
    return identity


def _identity_complete(identity: dict[str, Any]) -> bool:
    return (
        all(identity.get(field) not in (None, "", "unknown") for field in _IDENTITY_FIELDS)
        and bool(_SOURCE_HASH_REF.fullmatch(str(identity.get("sourceHashRef") or "")))
        and bool(_FULL_SOURCE_HASH.fullmatch(str(identity.get("sourceHash") or "")))
        and bool(identity.get("sourceStateScopes"))
        and all(scope in _STATES for scope in identity["sourceStateScopes"])
        and identity.get("knowledgeScope") in {"global_seed", "local_user", "eval_ephemeral"}
    )


def _catalog(summary: dict[str, Any], writes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每个可定位缺口一项；只有计数时保留聚合缺口，未知诊断永不被默默丢掉。"""
    result: list[dict[str, Any]] = []

    def add(location: str, kind: str, **data: Any) -> None:
        result.append({"location": location, "kind": kind, **data})

    coverage = sorted(set(summary["caseCoverageGaps"]))
    for dimension in coverage:
        add("coverage/" + dimension, "coverage", dimension=dimension)
    deferred = summary["deferredGapSummaries"]
    for ordinal, diagnostic in enumerate(deferred):
        add(f"deferred/{ordinal}", "deferred", **diagnostic)
    unresolved = summary["unresolvedComponentGapSummaries"]
    for ordinal, diagnostic in enumerate(unresolved):
        record_index = diagnostic["acceptedRecordIndex"]
        scope = writes[record_index].get("sourceStateScope") if record_index < len(writes) else None
        add(f"unresolved/{ordinal}", "unresolved_component", **diagnostic,
            **({"sourceStateScope": scope} if scope in _STATES else {}))
    reason_counts = Counter(item.get("reason") for item in deferred)
    located_mentions = len({
        (item["acceptedRecordIndex"], item["unresolvedComponentIndex"]) for item in unresolved
    })
    mention_count = summary.get("unresolvedDeepRecordMentionCount")
    # Unique 是这些 mention 去重后的组件身份数，并非另一组任务。只有所有 mention
    # 均已定位时才能确认其完整覆盖；缺定位或计数矛盾仍保留余项供全案复核。
    represented_unique = located_mentions if mention_count == located_mentions else 0
    counts = {
        "caseCoverageGapCount": len(coverage), "deferredCandidateCount": len(deferred),
        "unresolvedDeepRecordMentionCount": located_mentions,
        "unresolvedUniqueComponentCount": represented_unique,
        "unkeyedDeepRecordCount": reason_counts["missing_knowledge_identity"],
    }
    for field, represented in counts.items():
        count = summary.get(field)
        if isinstance(count, int) and count > represented:
            add("aggregate/" + field, "aggregate", count=count - represented, countField=field)
    for reason, count in sorted(summary["deferredReasonCounts"].items()):
        if count > reason_counts[reason]:
            add("reason/" + reason, "aggregate", reason=reason, count=count - reason_counts[reason])
    if summary["completionDiagnosticsIncomplete"] or summary["researchCompletion"] == "unknown":
        add("diagnostics/unknown", "unknown", reason="completion_diagnostics_incomplete")
    if summary["researchCompletion"] != "complete" and not result:
        add("diagnostics/unclassified", "unknown", reason="unclassified_followup")
    _safe(result)
    return result


def _sync(con: sqlite3.Connection, receipt: dict[str, Any]) -> None:
    ref = receipt["receipt_ref"]
    expected = [{"gapRef": "rgap-" + research_runtime.stable_hash(
        {"receiptRef": ref, "location": item["location"]})[:24], **item}
        for item in _catalog(receipt["completion"], receipt["writes"])]
    existing = con.execute("SELECT fingerprint FROM followup_origins WHERE receipt_ref=?", (ref,)).fetchone()
    if existing is not None:
        if existing[0] != receipt["fingerprint"]:
            raise FollowupError("followup_origin_receipt_changed")
        persisted = [{"gapRef": row["gap_ref"], **_load(row["diagnostic"], dict)} for row in con.execute(
            "SELECT * FROM followup_gaps WHERE receipt_ref=? ORDER BY location", (ref,)
        )]
        if persisted != sorted(expected, key=lambda gap: gap["location"]):
            raise FollowupError("followup_gap_catalog_changed")
        return
    con.execute(
        "INSERT INTO followup_origins(receipt_ref,run_ref,sample_id,fingerprint,source_identity,"
        "completion_summary,created_at) VALUES (?,?,?,?,?,?,?)",
        (ref, receipt["run_ref"], receipt["sample_id"], receipt["fingerprint"],
         _json(receipt["identity"]), _json(receipt["completion"]), datetime.now(UTC).isoformat()),
    )
    for item in expected:
        gap_ref = item["gapRef"]
        con.execute(
            "INSERT INTO followup_gaps(gap_ref,receipt_ref,location,diagnostic) VALUES (?,?,?,?)",
            (gap_ref, ref, item["location"], _json({key: value for key, value in item.items() if key != "gapRef"})),
        )


def _origin(con: sqlite3.Connection, run_ref: str, sample_id: str) -> dict[str, Any]:
    _safe({"runRef": run_ref, "sampleId": sample_id})
    if not isinstance(run_ref, str) or not isinstance(sample_id, str) or max(len(run_ref), len(sample_id)) > 200:
        raise FollowupError("followup_origin_invalid")
    receipt = _receipt(con, research_runtime.write_receipt_ref(run_ref, sample_id))
    if receipt["run_ref"] != run_ref or receipt["sample_id"] != sample_id:
        raise FollowupError("followup_origin_binding_mismatch")
    return receipt


def _state(con: sqlite3.Connection, memory: sqlite3.Connection, receipt: dict[str, Any],
           *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    ref = receipt["receipt_ref"]
    rows = con.execute(
        "SELECT * FROM followup_gaps WHERE receipt_ref=? ORDER BY location", (ref,)
    ).fetchall()
    events = con.execute(
        "SELECT * FROM followup_events WHERE receipt_ref=? ORDER BY event_id", (ref,)
    ).fetchall()
    states: dict[str, str] = {}
    latest: dict[str, dict[str, Any]] = {}
    closures: dict[str, dict[str, Any]] = {}
    for event in events:
        gap_ref = event["gap_ref"]
        disposition = event["disposition"]
        if disposition != "successor_evidence":
            states[gap_ref] = disposition
            closures[gap_ref] = _event(event)
        latest[gap_ref] = _event(event)
    gaps = [{
        "gapRef": row["gap_ref"], **_load(row["diagnostic"], dict),
        "status": "closed" if states.get(row["gap_ref"]) in {"resolved", "not_applicable"} else "open",
        "disposition": states.get(row["gap_ref"], "open"),
        "latestEvent": latest.get(row["gap_ref"]),
    } for row in rows]
    for gap in gaps:
        if gap["status"] != "closed":
            continue
        event = closures[gap["gapRef"]]
        try:
            support = _verify_support(memory, receipt, gap, event)
            if support["fingerprint"] != event["supportingReceiptFingerprint"]:
                raise FollowupError("followup_support_receipt_changed")
            gap["closureEvidenceStatus"] = "current"
        except FollowupError as exc:
            gap.update(status="open", closureEvidenceStatus="stale", reopenReason=str(exc))
    opened = sum(gap["status"] == "open" for gap in gaps)
    origin = con.execute("SELECT revision FROM followup_origins WHERE receipt_ref=?", (ref,)).fetchone()
    eligible = receipt["provenance"] == "transactional" and _identity_complete(receipt["identity"])
    result = {
        "status": "ok", "runRef": receipt["run_ref"], "sampleId": receipt["sample_id"],
        "originWriteReceiptRef": ref, "originFingerprint": receipt["fingerprint"],
        "sourceIdentity": receipt["identity"], "closureEligible": eligible,
        "closureIneligibleReason": None if eligible else "origin_source_identity_or_provenance_incomplete",
        "revision": origin["revision"], "gaps": gaps[offset:offset + limit],
        "total": len(gaps), "offset": offset, "nextOffset": offset + limit if offset + limit < len(gaps) else None,
        "openGapCount": opened, "closedGapCount": len(gaps) - opened, "eventCount": len(events),
        "researchCompletion": "needs_followup" if opened else "complete",
        "effectiveResearchCompletion": "needs_followup" if opened else "complete",
        "originalResearchCompletion": receipt["completion"]["researchCompletion"],
        "originResearchCompletion": receipt["completion"]["researchCompletion"],
        "createAuthorizing": False, "noRawMatureBuildMaterial": True,
    }
    _safe(result)
    return result


def _event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "eventId": row["event_id"], "revision": row["revision"], "gapRef": row["gap_ref"],
        "disposition": row["disposition"], "rationale": row["rationale"],
        "supportingWriteReceiptRef": row["support_receipt"],
        "supportingReceiptFingerprint": row["support_fingerprint"],
        "supportingRecordIds": _load(row["support_records"], list), "createdAt": row["created_at"],
    }


def _page(offset: int, limit: int) -> None:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise FollowupError("followup_pagination_invalid")


def _error(exc: FollowupError) -> dict[str, Any]:
    return {"status": "rejected", "errorCode": str(exc), "noRawMatureBuildMaterial": True}


def inspect_followups(*, db_path: str | Path, memory_db_path: str | Path, run_ref: str,
                     sample_id: str, offset: int = 0, limit: int = 50,
                     source_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """从不可变 receipt 同步目录；source_context 不参与闭合授权，也不覆盖旧诊断。"""
    del source_context
    try:
        _page(offset, limit)
        with closing(_memory(memory_db_path)) as memory, closing(_ledger(db_path)) as con, con:
            receipt = _origin(memory, run_ref, sample_id)
            con.execute("BEGIN IMMEDIATE")
            _sync(con, receipt)
            return _state(con, memory, receipt, offset=offset, limit=limit)
    except FollowupError as exc:
        return _error(exc)


def inspect_followup_events(*, db_path: str | Path, memory_db_path: str | Path, run_ref: str,
                           sample_id: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    """分页读取追加审计，包括已重新打开的缺口过去的关闭事件。"""
    try:
        _page(offset, limit)
        with closing(_memory(memory_db_path)) as memory, closing(_ledger(db_path)) as con, con:
            receipt = _origin(memory, run_ref, sample_id)
            con.execute("BEGIN IMMEDIATE")
            _sync(con, receipt)
            rows = con.execute(
                "SELECT * FROM followup_events WHERE receipt_ref=? ORDER BY event_id LIMIT ? OFFSET ?",
                (receipt["receipt_ref"], limit, offset),
            ).fetchall()
            count = con.execute("SELECT COUNT(*) FROM followup_events WHERE receipt_ref=?", (receipt["receipt_ref"],)).fetchone()[0]
            result = {"status": "ok", "events": [_event(row) for row in rows], "total": count,
                      "offset": offset, "nextOffset": offset + limit if offset + limit < count else None,
                      "noRawMatureBuildMaterial": True}
            _safe(result)
            return result
    except FollowupError as exc:
        return _error(exc)


def _decision(value: Any) -> dict[str, Any]:
    allowed = {"gapRef", "disposition", "rationale", "supportingWriteReceiptRef", "supportingRecordIds"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise FollowupError("followup_decision_invalid")
    _safe(value)
    if not isinstance(value.get("gapRef"), str) or not re.fullmatch(r"rgap-[0-9a-f]{24}", value["gapRef"]):
        raise FollowupError("followup_gap_ref_invalid")
    if not isinstance(value.get("disposition"), str) or value["disposition"] not in {
        "resolved", "not_applicable", "successor_evidence", "reopen"
    }:
        raise FollowupError("followup_disposition_invalid")
    rationale = value.get("rationale")
    if not isinstance(rationale, str) or not 1 <= len(rationale.strip()) <= 600:
        raise FollowupError("followup_rationale_invalid")
    if value["disposition"] != "reopen":
        ids = value.get("supportingRecordIds")
        if (not isinstance(ids, list) or not ids or len(ids) > 100
                or any(not isinstance(item, str) or not re.fullmatch(r"drr-[0-9a-f]{16}", item) for item in ids)
                or len(ids) != len(set(ids))):
            raise FollowupError("followup_support_records_invalid")
        if not isinstance(value.get("supportingWriteReceiptRef"), str):
            raise FollowupError("followup_support_receipt_required")
    elif value.get("supportingWriteReceiptRef") or value.get("supportingRecordIds"):
        raise FollowupError("followup_reopen_support_not_allowed")
    return {**value, "rationale": rationale.strip()}


def _later(support: dict[str, Any], origin: dict[str, Any]) -> bool:
    try:
        newer = datetime.fromisoformat(support["created_at"])
        older = datetime.fromisoformat(origin["created_at"])
        return newer.tzinfo is not None and older.tzinfo is not None and newer > older
    except (ValueError, TypeError):
        return False


def _exact_record(con: sqlite3.Connection, support: dict[str, Any], record_id: str) -> dict[str, Any]:
    identity = support["identity"]
    mappings = [write for write in support["writes"] if write.get("recordId") == record_id]
    row = con.execute("SELECT * FROM deep_research_records WHERE record_id=?", (record_id,)).fetchone()
    if not mappings or row is None:
        raise FollowupError("followup_support_record_not_written")
    if (row["status"] != "valid" or row["superseded_by_id"] is not None
            or row["copy_safety_state"] != "passed" or int(row["record_schema_version"]) < 2
            or row["source_state_scope"] not in identity.get("sourceStateScopes", [])):
        raise FollowupError("followup_support_record_ineligible")
    verified_claim_keys = set()
    for write in mappings:
        expected = write.get("afterProjectionHash")
        if (not expected or expected != row["projection_hash"]
                or research_runtime.projection_hash(row) != expected):
            continue
        if (identity["sourceHashRef"] not in write.get("writtenSourceCaseRefs", [])
                or write.get("sourceGamePatch") != identity["gamePatch"]
                or write.get("sourcePassiveTreeVersion") != identity["passiveTreeVersion"]
                or write.get("knowledgeScope") != identity["knowledgeScope"]
                or write.get("knowledgeKey") != row["knowledge_key"]
                or write.get("sourceStateScope", identity.get("sourceStateScope")) != row["source_state_scope"]):
            continue
        claim = con.execute(
            "SELECT * FROM deep_research_record_evidence WHERE record_id=? AND knowledge_scope=? "
            "AND knowledge_key=? AND source_case_ref=? AND source_claim_key=? AND game_patch=? "
            "AND passive_tree_version=? AND accepted_projection_hash=? AND binding_issue IS NULL",
            (record_id, identity["knowledgeScope"], write["knowledgeKey"], identity["sourceHashRef"],
             write.get("sourceClaimKey") or "default", identity["gamePatch"], identity["passiveTreeVersion"], expected),
        ).fetchone()
        if claim is not None and claim["source_state_scope"] == row["source_state_scope"]:
            pob = identity.get("pobVersionOrCommit")
            if pob not in (None, "", "unknown") and claim["pob_version_or_commit"] != pob:
                continue
            verified_claim_keys.add(write.get("sourceClaimKey") or "default")
    if verified_claim_keys:
        record = dict(row)
        for field in ("component_mentions", "conditions", "failure_conditions"):
            record[field] = _load(record[field], list)
        record["typed_payload"] = _load(record["typed_payload"], dict)
        record["_verified_source_claim_keys"] = sorted(verified_claim_keys)
        return record
    raise FollowupError("followup_support_projection_stale")


def _verify_located_gap(gap: dict[str, Any], decision: dict[str, Any],
                       summary: dict[str, Any], records: list[dict[str, Any]]) -> None:
    """同源、较晚不等于解决；把本项条件与实际已接受的 typed 组件对齐。"""
    complete_case = summary["researchCompletion"] == "complete" and summary["completionScope"] == "case"
    subject = gap.get("recordSubjectHash")
    component = gap.get("componentSubjectHash")
    if not subject or (gap["kind"] == "unresolved_component" and not component):
        # 历史目录只有序号。序号不能跨 review 复用，也不能借一份干净补录解除缺口。
        if not complete_case:
            raise FollowupError("followup_complete_acceptance_required")
        if gap["kind"] == "unresolved_component" and decision["disposition"] == "resolved":
            if not component:
                raise FollowupError("followup_target_identity_missing")
            if not any(research_completion.component_subject_hash(mention) == component
                       for record in records for mention in record["component_mentions"]):
                raise FollowupError("followup_target_resolution_unproven")
        if any(mention.get("resolution_status") != "resolved" or not mention.get("component_key")
               for record in records for mention in record["component_mentions"]):
            raise FollowupError("followup_component_still_unresolved")
        return
    pending = (summary["unresolvedComponentGapSummaries"] if gap["kind"] == "unresolved_component"
               else summary["deferredGapSummaries"])
    if any(item.get("recordSubjectHash") == subject and (
        gap["kind"] != "unresolved_component" or item.get("componentSubjectHash") == component
    ) for item in pending):
        raise FollowupError("followup_target_still_unresolved")
    matching = [record for record in records if any(
        research_completion.record_subject_hash(record, source_claim_key=key) == subject
        for key in record["_verified_source_claim_keys"]
    )]
    # 完整 case 可以复核主题/条件纠正，但 resolved 仍须找到原组件的实际
    # typed 解决记录；省略目标只能显式 not_applicable，不能当作已解决。
    if not matching and complete_case:
        if any(mention.get("resolution_status") != "resolved" or not mention.get("component_key")
               for record in records for mention in record["component_mentions"]):
            raise FollowupError("followup_component_still_unresolved")
        if gap["kind"] == "unresolved_component":
            matching = records
        else:
            return
    if gap["kind"] == "unresolved_component":
        mentions = [mention for record in matching for mention in record["component_mentions"]
                    if research_completion.component_subject_hash(mention) == component]
        if any(mention.get("resolution_status") != "resolved" or not mention.get("component_key")
               for mention in mentions):
            raise FollowupError("followup_component_still_unresolved")
        if decision["disposition"] == "resolved" and not mentions:
            raise FollowupError("followup_target_resolution_unproven")
    elif decision["disposition"] == "resolved" and not matching:
        raise FollowupError("followup_target_resolution_unproven")
    # 现行组件/候选模型没有逐项 not_applicable 证明字段；完整 case 复核仍可
    # 证明它不适用。coverage 则直接使用其已有的 typed not_applicable 状态。
    if decision["disposition"] == "not_applicable" and not complete_case:
        raise FollowupError("followup_complete_acceptance_required")


def _verify_support(memory: sqlite3.Connection, origin: dict[str, Any], gap: dict[str, Any],
                    decision: dict[str, Any]) -> dict[str, Any]:
    support = _receipt(memory, decision["supportingWriteReceiptRef"])
    if support["receipt_ref"] == origin["receipt_ref"] or not _later(support, origin):
        raise FollowupError("followup_support_must_be_later")
    if support["provenance"] != "transactional" or not _identity_complete(support["identity"]):
        raise FollowupError("followup_support_identity_incomplete")
    records = [_exact_record(memory, support, record_id) for record_id in decision["supportingRecordIds"]]
    states = {record["source_state_scope"] for record in records}
    if decision["disposition"] == "successor_evidence":
        return support
    if origin["provenance"] != "transactional" or not _identity_complete(origin["identity"]):
        raise FollowupError("followup_origin_identity_incomplete")
    for field in (*_IDENTITY_FIELDS, *_OPTIONAL_IDENTITY_FIELDS):
        original_value = origin["identity"].get(field)
        if original_value is not None and support["identity"].get(field) != original_value:
            raise FollowupError("followup_source_mismatch_use_successor_evidence")
    allowed_scopes = {gap["sourceStateScope"]} if gap.get("sourceStateScope") else set(origin["identity"]["sourceStateScopes"])
    if not states <= allowed_scopes:
        raise FollowupError("followup_source_state_mismatch")
    summary = support["completion"]
    if gap["kind"] == "coverage":
        expected = "not_applicable" if decision["disposition"] == "not_applicable" else "covered"
        if summary["caseCoverage"].get(gap["dimension"]) != expected:
            raise FollowupError("followup_support_coverage_unproven")
    if gap["kind"] in {"unknown", "aggregate"} and (
        summary["researchCompletion"] != "complete" or summary["completionScope"] != "case"
    ):
        raise FollowupError("followup_complete_acceptance_required")
    if gap["kind"] in {"unresolved_component", "deferred"}:
        _verify_located_gap(gap, decision, summary, records)
    return support


def submit_followup_decisions(*, db_path: str | Path, memory_db_path: str | Path,
                              run_ref: str, sample_id: str, expected_revision: int,
                              request_id: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """原子追加一组 Agent 处置；CAS 与请求指纹分别防止并发覆盖和重复提交。"""
    try:
        if type(expected_revision) is not int or expected_revision < 0:
            raise FollowupError("followup_revision_invalid")
        if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
            raise FollowupError("followup_request_id_invalid")
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= 100:
            raise FollowupError("followup_decisions_invalid")
        parsed = [_decision(value) for value in decisions]
        if len({item["gapRef"] for item in parsed}) != len(parsed):
            raise FollowupError("followup_duplicate_gap_decision")
        fingerprint = research_runtime.stable_hash({"expectedRevision": expected_revision, "decisions": parsed})
        with closing(_memory(memory_db_path)) as memory, closing(_ledger(db_path)) as con, con:
            origin = _origin(memory, run_ref, sample_id)
            con.execute("BEGIN IMMEDIATE")
            _sync(con, origin)
            ref = origin["receipt_ref"]
            replay = con.execute("SELECT * FROM followup_requests WHERE receipt_ref=? AND request_id=?", (ref, request_id)).fetchone()
            if replay:
                if replay["payload_hash"] != fingerprint:
                    raise FollowupError("followup_request_conflict")
                return {**_load(replay["response"], dict), **_state(con, memory, origin),
                        "status": "accepted", "idempotentReplay": True}
            revision = con.execute("SELECT revision FROM followup_origins WHERE receipt_ref=?", (ref,)).fetchone()[0]
            if revision != expected_revision:
                raise FollowupError("followup_revision_conflict")
            pending = []
            for decision in parsed:
                gap = con.execute("SELECT diagnostic FROM followup_gaps WHERE receipt_ref=? AND gap_ref=?", (ref, decision["gapRef"])).fetchone()
                if gap is None:
                    raise FollowupError("followup_gap_not_in_origin")
                support = None if decision["disposition"] == "reopen" else _verify_support(
                    memory, origin, _load(gap[0], dict), decision
                )
                pending.append((decision, support))
            now = datetime.now(UTC).isoformat()
            for decision, support in pending:
                con.execute(
                    "INSERT INTO followup_events(receipt_ref,revision,gap_ref,disposition,rationale,"
                    "support_receipt,support_fingerprint,support_records,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ref, revision + 1, decision["gapRef"], decision["disposition"], decision["rationale"],
                     support["receipt_ref"] if support else None, support["fingerprint"] if support else None,
                     _json(decision.get("supportingRecordIds") or []), now),
                )
            con.execute("UPDATE followup_origins SET revision=? WHERE receipt_ref=? AND revision=?", (revision + 1, ref, revision))
            result = {**_state(con, memory, origin), "status": "accepted", "idempotentReplay": False,
                      "appendedEventCount": len(parsed)}
            _safe(result)
            con.execute("INSERT INTO followup_requests(receipt_ref,request_id,payload_hash,response) VALUES (?,?,?,?)", (ref, request_id, fingerprint, _json(result)))
            return result
    except FollowupError as exc:
        return _error(exc)


def state_fingerprint(db_path: str | Path, run_ref: str) -> str:
    """供清理快照绑定使用；只读，不创建缺失目录或数据库。"""
    if not Path(db_path).is_file():
        return research_runtime.stable_hash([])
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"followup_origins", "followup_events"} <= tables:
            return research_runtime.stable_hash([])
        origins = [dict(row) for row in con.execute(
            "SELECT * FROM followup_origins WHERE run_ref=? ORDER BY receipt_ref", (run_ref,)
        )]
        events = [dict(row) for row in con.execute(
            "SELECT e.* FROM followup_events e JOIN followup_origins o ON e.receipt_ref=o.receipt_ref "
            "WHERE o.run_ref=? ORDER BY e.event_id", (run_ref,)
        )]
    return research_runtime.stable_hash({"origins": origins, "events": events})
