"""Append-only, local-only Learning Memory for cross-case Create guidance."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from server import paths

from . import models
from .file_lock import interprocess_file_lock


_LOCK = threading.RLock()


def memory_path() -> Path:
    return paths.comparative_learning_memory_path().resolve()


def propose_lesson(payload: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Validate and append a reviewed cross-dimensional lesson."""

    if isinstance(payload, dict) and payload.get("dbFit") is True:
        return _rejected("research_schema_fit_required")
    try:
        proposal = models.LearningLessonProposal.model_validate(payload)
    except ValidationError as exc:
        return _schema_rejected(exc)
    target = (path or memory_path()).resolve()
    with _LOCK, interprocess_file_lock(_lock_path(target)):
        events = _read_events(target)
        state = _materialize(events)
        key = _lesson_key(proposal.lesson)
        equivalents = [entry for entry in state.values() if key in _entry_lesson_keys(entry)]
        if equivalents:
            correction_ids = {
                correction["correctionId"]
                for entry in equivalents
                for correction in entry.get("corrections", [])
            }
            if correction_ids:
                cited = set(proposal.cited_correction_ids)
                if not correction_ids.intersection(cited) or not proposal.new_evidence_refs:
                    return _rejected(
                        "corrected_lesson_requires_new_evidence",
                        correctionRefs=sorted(correction_ids),
                    )
            else:
                return _rejected(
                    "duplicate_learning_lesson",
                    lessonId=equivalents[-1]["lessonId"],
                )

        now = models.utc_now()
        lesson_id = f"lesson:{uuid4()}"
        entry = models.LearningMemoryEntry(
            **proposal.model_dump(),
            lesson_id=lesson_id,
            lesson_key=key,
            status="active",
            created_at=now,
            updated_at=now,
        )
        event: dict[str, Any] = {
            "eventType": "lesson",
            "schemaVersion": 1,
            "entry": entry.model_dump(mode="json", by_alias=True),
        }
        if not _append_event(target, event):
            return _rejected("learning_memory_write_failed")
    return {
        "status": "accepted",
        "lesson": _safe_entry(event["entry"], corrections=[]),
        "availableForNextCreate": True,
        "localOnly": True,
    }


def append_correction(payload: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    """Append a correction event without mutating or deleting history."""

    try:
        proposal = models.LearningCorrectionProposal.model_validate(payload)
    except ValidationError as exc:
        return _schema_rejected(exc)
    target = (path or memory_path()).resolve()
    with _LOCK, interprocess_file_lock(_lock_path(target)):
        events = _read_events(target)
        state = _materialize(events)
        current = state.get(proposal.target_lesson_id)
        if current is None:
            return _rejected("learning_lesson_not_found")
        if current["status"] in {"superseded", "deprecated", "stale"}:
            return _rejected("learning_lesson_not_correctable", status=current["status"])
        if proposal.replacement_lesson_id:
            replacement = state.get(proposal.replacement_lesson_id)
            if replacement is None or replacement["status"] not in {"active", "narrowed"}:
                return _rejected("replacement_learning_lesson_not_active")
            if replacement["lessonId"] == current["lessonId"]:
                return _rejected("replacement_learning_lesson_must_differ")
        if proposal.action in {"narrow", "revise"}:
            after_key = _lesson_key(str(proposal.after_lesson))
            duplicate = next(
                (
                    entry
                    for lesson_id, entry in state.items()
                    if lesson_id != current["lessonId"]
                    and entry.get("status") in {"active", "narrowed"}
                    and after_key in _entry_lesson_keys(entry)
                ),
                None,
            )
            if duplicate is not None:
                return _rejected(
                    "learning_correction_would_duplicate_lesson",
                    lessonId=duplicate["lessonId"],
                )

        before = str(current["lesson"])
        if proposal.action == "narrow":
            new_status = "narrowed"
            after = str(proposal.after_lesson)
        elif proposal.action == "revise":
            new_status = "active"
            after = str(proposal.after_lesson)
        elif proposal.action == "supersede":
            new_status = "superseded"
            after = f"superseded by {proposal.replacement_lesson_id}"
        else:
            new_status = "deprecated"
            after = "deprecated; do not repeat"
        correction = models.LearningMemoryCorrection(
            **proposal.model_dump(),
            correction_id=f"correction:{uuid4()}",
            before_summary=before,
            after_summary=after,
            created_at=models.utc_now(),
        )
        event = {
            "eventType": "correction",
            "schemaVersion": 1,
            "targetLessonId": proposal.target_lesson_id,
            "newStatus": new_status,
            "correction": correction.model_dump(mode="json", by_alias=True),
        }
        if not _append_event(target, event):
            return _rejected("learning_memory_write_failed")
    return {
        "status": "corrected",
        "correction": event["correction"],
        "effectiveStatus": new_status,
        "appendOnly": True,
        "localOnly": True,
    }


def validate_references(
    *,
    lesson_ids: list[str] | None = None,
    correction_ids: list[str] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Confirm that a Learn outcome only cites events present in local Memory."""

    requested_lessons = list(lesson_ids or [])
    requested_corrections = list(correction_ids or [])
    if any(not isinstance(value, str) or not value for value in requested_lessons):
        return _rejected("invalid_learning_lesson_ref")
    if any(not isinstance(value, str) or not value for value in requested_corrections):
        return _rejected("invalid_learning_correction_ref")
    target = (path or memory_path()).resolve()
    with _LOCK, interprocess_file_lock(_lock_path(target)):
        state = _materialize(_read_events(target))
    known_lessons = set(state)
    known_corrections = {
        str(correction.get("correctionId"))
        for entry in state.values()
        for correction in entry.get("corrections", [])
        if correction.get("correctionId")
    }
    missing_lessons = sorted(set(requested_lessons) - known_lessons)
    missing_corrections = sorted(set(requested_corrections) - known_corrections)
    if missing_lessons or missing_corrections:
        return _rejected(
            "learning_memory_refs_not_found",
            missingLessonIds=missing_lessons,
            missingCorrectionIds=missing_corrections,
        )
    return {
        "status": "ok",
        "lessonCount": len(set(requested_lessons)),
        "correctionCount": len(set(requested_corrections)),
        "localOnly": True,
        "containsRawMaterial": False,
    }


def query_memory(
    *,
    family_key: str,
    target_level: int,
    dimensions: list[str] | None = None,
    limit: int = 8,
    version_context: dict[str, Any] | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Return effective lessons plus relevant correction/do-not-repeat summaries."""

    if not re.fullmatch(r"bf-[a-f0-9]{20}", str(family_key or "")):
        return _rejected("invalid_build_family_key")
    if (
        isinstance(target_level, bool)
        or not isinstance(target_level, int)
        or not 1 <= target_level <= 100
    ):
        return _rejected("invalid_target_level")
    requested_dimensions = set(dimensions or [])
    if not requested_dimensions.issubset(set(models.COMPARISON_DIMENSIONS)):
        return _rejected("invalid_comparison_dimension")
    bounded_limit = max(1, min(int(limit), 20))
    requested_version = None
    if version_context is not None:
        try:
            requested_version = models.LearningVersionContext.model_validate(version_context)
        except ValidationError as exc:
            return _schema_rejected(exc)
    target = (path or memory_path()).resolve()
    with _LOCK, interprocess_file_lock(_lock_path(target)):
        state = _materialize(_read_events(target))
    eligible: list[dict[str, Any]] = []
    corrections: list[dict[str, Any]] = []
    contextual_stale: list[dict[str, Any]] = []
    for entry in state.values():
        entry_corrections = entry.get("corrections", [])
        if requested_dimensions and entry["dimension"] not in requested_dimensions:
            continue
        if not _scope_matches(entry, family_key=family_key, target_level=target_level):
            continue
        if entry["status"] not in {"active", "narrowed"}:
            corrections.extend(
                _safe_correction(item, entry["lessonId"]) for item in entry_corrections
            )
            continue
        if requested_version is not None and not _version_matches(entry, requested_version):
            contextual_stale.append(
                {
                    "lessonId": entry["lessonId"],
                    "effectiveStatus": "stale",
                    "reason": "version_context_mismatch",
                    "verificationTasks": entry.get("verificationTasks", []),
                }
            )
            continue
        eligible.append(entry)
    scope_rank = {"family": 0, "level_band": 1, "global": 2}
    eligible.sort(key=lambda item: (item.get("updatedAt", ""), item["lessonId"]), reverse=True)
    eligible.sort(key=lambda item: scope_rank.get(item["scope"], 9))
    selected = eligible[:bounded_limit]
    for entry in selected:
        corrections.extend(
            _safe_correction(item, entry["lessonId"]) for item in entry.get("corrections", [])
        )
    query_ref = _query_ref(family_key, target_level, requested_dimensions, state)
    return {
        "status": "ok",
        "queryRef": query_ref,
        "retrievalOutcome": "matched" if selected else "no_matching_memory",
        "recalledLessonIds": [entry["lessonId"] for entry in selected],
        "lessons": [
            _safe_entry(entry, corrections=entry.get("corrections", [])) for entry in selected
        ],
        "correctionsAndDoNotRepeat": _dedupe_corrections(corrections),
        "contextualStaleLessons": contextual_stale,
        "localOnly": True,
        "containsRawMaterial": False,
    }


def _materialize(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("eventType") == "lesson" and isinstance(event.get("entry"), dict):
            raw = dict(event["entry"])
            try:
                valid = models.LearningMemoryEntry.model_validate(raw)
            except ValidationError:
                continue
            value = valid.model_dump(mode="json", by_alias=True)
            value["corrections"] = []
            entries[value["lessonId"]] = value
            continue
        if event.get("eventType") != "correction":
            continue
        target_id = event.get("targetLessonId")
        current = entries.get(str(target_id))
        if current is None or not isinstance(event.get("correction"), dict):
            continue
        try:
            correction = models.LearningMemoryCorrection.model_validate(event["correction"])
        except ValidationError:
            continue
        current["corrections"].append(correction.model_dump(mode="json", by_alias=True))
        current["status"] = event.get("newStatus", current["status"])
        current["updatedAt"] = correction.created_at
        if correction.action in {"narrow", "revise"}:
            current["lesson"] = correction.after_lesson
            current["lessonKey"] = _lesson_key(str(correction.after_lesson))
            # Empty lists are meaningful: a review may remove an over-narrow condition or
            # exclusion.  Always materialize the correction payload instead of accidentally
            # retaining stale values from the original lesson.
            current["conditions"] = correction.after_conditions
            current["exclusions"] = correction.after_exclusions
    return entries


def _safe_entry(entry: dict[str, Any], *, corrections: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "lessonId",
        "lesson",
        "scope",
        "familyKey",
        "levelMin",
        "levelMax",
        "dimension",
        "conditions",
        "exclusions",
        "recommendedCreateBehavior",
        "verificationTasks",
        "status",
        "createdAt",
        "updatedAt",
    )
    safe = {key: entry.get(key) for key in keys}
    safe["correctionRefs"] = [item.get("correctionId") for item in corrections]
    return safe


def _safe_correction(correction: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    return {
        "correctionId": correction.get("correctionId"),
        "lessonId": lesson_id,
        "action": correction.get("action"),
        "beforeSummary": correction.get("beforeSummary"),
        "afterSummary": correction.get("afterSummary"),
        "reason": correction.get("reason"),
        "triggerCaseId": correction.get("triggerCaseId"),
    }


def _scope_matches(entry: dict[str, Any], *, family_key: str, target_level: int) -> bool:
    if entry["scope"] == "global":
        return True
    if entry["scope"] == "family":
        return entry.get("familyKey") == family_key
    return (
        entry.get("levelMin") is not None
        and entry.get("levelMax") is not None
        and int(entry["levelMin"]) <= target_level <= int(entry["levelMax"])
    )


def _version_matches(entry: dict[str, Any], requested: models.LearningVersionContext) -> bool:
    stored = entry.get("versionContext")
    if not isinstance(stored, dict):
        return False
    stored_patch = str(stored.get("gamePatch") or "")
    if _season_family(stored_patch) != _season_family(requested.game_patch):
        return False
    if str(stored.get("passiveTreeVersion") or "") != requested.passive_tree_version:
        return False
    return True


def _season_family(value: str) -> str:
    parts = re.findall(r"\d+", str(value or ""))
    return ".".join(parts[:2]) if len(parts) >= 2 else str(value or "").casefold()


def _lesson_key(value: str) -> str:
    normalized = re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _entry_lesson_keys(entry: dict[str, Any]) -> set[str]:
    keys = {str(entry.get("lessonKey") or "")}
    for correction in entry.get("corrections", []):
        for field in ("beforeSummary", "afterLesson"):
            value = correction.get(field)
            if isinstance(value, str) and value:
                keys.add(_lesson_key(value))
    keys.discard("")
    return keys


def _query_ref(
    family_key: str,
    target_level: int,
    dimensions: set[str],
    state: dict[str, dict[str, Any]],
) -> str:
    payload = json.dumps(
        {
            "family": family_key,
            "level": target_level,
            "dimensions": sorted(dimensions),
            "memory": sorted((key, value.get("updatedAt")) for key, value in state.items()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"learning-query:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("schemaVersion") == 1:
            events.append(event)
    return events


def _append_event(path: Path, event: dict[str, Any]) -> bool:
    try:
        models.ensure_safe_durable_payload(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    except (OSError, ValueError):
        return False
    return True


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _dedupe_corrections(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        key = str(value.get("correctionId") or "")
        if key and key not in seen:
            output.append(value)
            seen.add(key)
    return output


def _schema_rejected(exc: ValidationError) -> dict[str, Any]:
    first: Any = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(part) for part in first.get("loc", ())) or "input"
    return _rejected(
        "invalid_learning_memory_schema", detail=f"{loc}: {first.get('msg', '')}"[:240]
    )


def _rejected(error_code: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "rejected",
        "errorCode": error_code,
        "containsRawMaterial": False,
        **extra,
    }
