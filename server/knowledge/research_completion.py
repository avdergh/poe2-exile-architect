"""Raw-free Research completion diagnostics shared by acceptance and cleanup.

An accepted subset is not proof that the source case has been fully researched.
This projection retains typed gap locations, never rejected candidate prose.
"""

from __future__ import annotations

import re
from typing import Any

from . import copy_safety, research_runtime


_COVERAGE_DIMENSIONS = {
    "supports", "rotation", "passiveAscendancy", "gearRoles", "resourceDefense"
}
_COVERAGE_STATUSES = {"covered", "evidence_missing", "not_applicable"}
_REQUIRED_COUNTS = (
    "deferredCandidateCount", "unresolvedDeepRecordMentionCount", "caseCoverageGapCount"
)
_COUNTS = (*_REQUIRED_COUNTS, "unresolvedUniqueComponentCount", "unkeyedDeepRecordCount")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_SUBJECT_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COMPONENT_KEY = re.compile(
    r"(?:skill|gem|support|item|unique|passive|ascendancy|keystone|notable|jewel|stat):"
    r"[A-Za-z0-9_:./-]{1,160}\Z"
)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _code(value: Any) -> str | None:
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def component_subject_hash(mention: dict[str, Any]) -> str:
    """定位同一声明，不由显示名或指纹授权任何图组件。"""
    def value(canonical: str, review: str) -> Any:
        return mention.get(canonical, mention.get(review))

    identity = {
        "name": str(value("candidate_name", "candidateName") or "").strip().casefold(),
        "query": str(value("resolver_query", "resolverQuery") or "").strip().casefold(),
        "role": mention.get("role"), "scope": mention.get("scope"),
        "expectedTypes": sorted(value("expected_node_types", "expectedNodeTypes") or []),
    }
    return research_runtime.stable_hash(identity)


def record_subject_hash(record: dict[str, Any], *, source_claim_key: str | None = None) -> str:
    """保留条件分支和组件声明的精确身份；正文修正及解析状态不参与身份。"""
    def value(canonical: str, review: str, default: Any = None) -> Any:
        return record.get(canonical, record.get(review, default))

    return research_runtime.stable_hash({
        "recordKind": value("record_kind", "recordKind"),
        "title": record.get("title"),
        "conditions": record.get("conditions", []),
        "failureConditions": value("failure_conditions", "failureConditions", []),
        "sourceStateScope": value("source_state_scope", "sourceStateScope"),
        "sourceClaimKey": source_claim_key or value("source_claim_key", "sourceClaimKey", "default"),
        "components": sorted(component_subject_hash(mention) for mention in
                             value("component_mentions", "components", [])),
    })


def _subject_hashes(item: dict[str, Any]) -> dict[str, str]:
    return {key: value for key in ("recordSubjectHash", "componentSubjectHash")
            if isinstance(value := item.get(key), str) and _SUBJECT_HASH.fullmatch(value)}


def _gap_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        # The ordinal locates the diagnostic inside the same canonical review. The
        # receipt separately binds that review's hash; this is not a graph receipt.
        gap: dict[str, Any] = {
            "diagnosticIndex": _count(item.get("diagnosticIndex"))
            if "diagnosticIndex" in item else index,
            "reason": _code(item.get("reason")) or "unclassified_diagnostic",
            **_subject_hashes(item),
        }
        for key in ("candidateKind", "recordKind"):
            code = _code(item.get(key))
            if code is not None:
                gap[key] = code
        keys = item.get("componentKeys")
        if isinstance(keys, list):
            gap["componentKeys"] = sorted({
                key for key in keys if isinstance(key, str) and _COMPONENT_KEY.fullmatch(key)
            })
        result.append(gap)
    return result


def _unresolved_gap_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        gap = {
            key: _count(item.get(key))
            for key in ("acceptedRecordIndex", "unresolvedComponentIndex")
        }
        if any(index is None for index in gap.values()):
            continue
        kind = _code(item.get("recordKind"))
        if kind:
            gap["recordKind"] = kind
        gap.update(_subject_hashes(item))
        result.append(gap)
    return result


def completion_summary(
    report: dict[str, Any] | None, *, supplement: bool = False
) -> dict[str, Any]:
    """Project diagnostics without inventing closure for incomplete or legacy data.

    ``completionScope=supplement`` describes only that acceptance unit. Its clean
    completion cannot close any parent case's existing gap ledger.
    """
    source = report if isinstance(report, dict) else {}
    mode = source.get("acceptanceMode")
    if not isinstance(mode, str) or mode not in {"clean", "partial_with_deferred", "blocked"}:
        mode = "unknown"
    counts = {key: _count(source.get(key)) for key in _COUNTS}
    if counts["unresolvedDeepRecordMentionCount"] is None:
        counts["unresolvedDeepRecordMentionCount"] = _count(
            source.get("unresolvedDeepRecordComponentCount")
        )
    incomplete = source.get("completionDiagnosticsIncomplete") is True or any(
        counts[key] is None for key in _REQUIRED_COUNTS
    )
    incomplete |= any(
        source.get(key) is not None and _count(source[key]) is None for key in _COUNTS
    )
    coverage_input = source.get("caseCoverage")
    coverage = {
        key: value for key, value in coverage_input.items()
        if key in _COVERAGE_DIMENSIONS and isinstance(value, str) and value in _COVERAGE_STATUSES
    } if isinstance(coverage_input, dict) else {}
    incomplete |= coverage_input is not None and (
        not isinstance(coverage_input, dict) or len(coverage_input) != len(coverage)
    )
    gap_input = source.get("caseCoverageGaps")
    coverage_gaps = list(dict.fromkeys(
        value for value in gap_input if isinstance(value, str) and value in _COVERAGE_DIMENSIONS
    )) if isinstance(gap_input, list) else []
    for key, value in coverage.items():
        if value == "evidence_missing" and key not in coverage_gaps:
            coverage_gaps.append(key)
    reason_input = source.get("deferredReasonCounts")
    reasons: dict[str, int] = {}
    if isinstance(reason_input, dict):
        for key, value in reason_input.items():
            count = _count(value)
            if count is not None and count > 0:
                reason = _code(key) or "unclassified_diagnostic"
                reasons[reason] = reasons.get(reason, 0) + count
            if count is None:
                incomplete = True
    elif reason_input is not None:
        incomplete = True
    gaps = _gap_summaries(source.get("deferredGapSummaries", source.get("deferredCandidates")))
    unresolved_gaps = _unresolved_gap_summaries(source.get("unresolvedComponentGapSummaries"))
    for key in ("deferredGapSummaries", "deferredCandidates", "unresolvedComponentGapSummaries"):
        value = source.get(key)
        if value is not None and (
            not isinstance(value, list) or any(not isinstance(item, dict) for item in value)
        ):
            incomplete = True
    has_gaps = (
        mode == "partial_with_deferred"
        or any(value is not None and value > 0 for value in counts.values())
        or bool(reasons or coverage_gaps or gaps or unresolved_gaps)
    )
    completion = (
        "needs_followup" if has_gaps else "complete"
        if mode == "clean" and not incomplete and all(counts[key] == 0 for key in _REQUIRED_COUNTS)
        else "unknown"
    )
    result = {
        "completionDiagnosticsVersion": 1,
        "completionDiagnosticsIncomplete": incomplete,
        "completionScope": "supplement"
        if supplement or source.get("completionScope") == "supplement" else "case",
        "researchCompletion": completion,
        "acceptanceMode": mode,
        **counts,
        "deferredReasonCounts": reasons,
        "deferredGapSummaries": gaps,
        "unresolvedComponentGapSummaries": unresolved_gaps,
        "caseCoverage": coverage,
        "caseCoverageGaps": coverage_gaps,
    }
    # Even recognized fields may arrive through maintenance/legacy callers. Never
    # retain unsafe free text or silently turn a rejected projection into clean.
    if copy_safety.find_forbidden_paths(result) or copy_safety.durable_knowledge_flags(result):
        result.update(
            researchCompletion="needs_followup" if has_gaps else "unknown",
            deferredReasonCounts={"unsafe_diagnostic_omitted": 1},
            deferredGapSummaries=[],
        )
    return result
