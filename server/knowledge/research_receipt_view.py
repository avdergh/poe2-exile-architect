"""Research 写入回执的有界公开投影；原始持久回执和内部验收合同保持完整。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal


ReceiptDetail = Literal["summary", "records", "diagnostics"]
_SUMMARY_OMITTED_FIELDS = {"canonicalRecord", "crossFamilyDuplicateAdvisories"}


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _summary(value: dict[str, Any]) -> dict[str, Any]:
    """Keep authoritative scalar results; omitted lists remain discoverable by section."""
    result = {}
    for key, item in value.items():
        if _scalar(item):
            result[key] = item
        elif isinstance(item, dict):
            result[key] = {k: v for k, v in item.items() if _scalar(v)}
        elif key == "caseCoverageGaps":
            result[key] = item
    return result


def _diagnostic_sections(receipt: dict[str, Any]) -> dict[str, list[Any]]:
    sections: dict[str, list[Any]] = {}

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                # These mappings already have a dedicated, record-bound paginated view.
                if path == "deepRecordWrite" and key == "recordWrites":
                    continue
                visit(item, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            sections[path] = value

    visit(receipt.get("acceptanceSummary") or {}, "")
    for index, write in enumerate(receipt.get("writtenMapping") or []):
        advisories = write.get("crossFamilyDuplicateAdvisories") or []
        if advisories:
            sections[f"writtenMapping[{index}].crossFamilyDuplicateAdvisories"] = advisories
    return sections


def project_receipt(
    receipt: dict[str, Any],
    *,
    detail: ReceiptDetail = "summary",
    cursor: int = 0,
    limit: int = 20,
    section: str | None = None,
) -> dict[str, Any]:
    """Page an already copy-safe receipt without changing its stored values or authority."""
    if detail not in {"summary", "records", "diagnostics"}:
        raise ValueError("invalid_receipt_detail")
    if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid_receipt_page")
    if section is not None and detail != "diagnostics":
        raise ValueError("receipt_section_requires_diagnostics")
    sections = _diagnostic_sections(receipt)
    if detail == "diagnostics" and section not in sections:
        return {
            "status": "error",
            "errorCode": "receipt_diagnostic_section_required",
            "writeReceiptRef": receipt.get("writeReceiptRef"),
            "diagnosticSections": [{"section": k, "count": len(v)} for k, v in sections.items()],
            "createAuthorizing": False,
            "noRawMatureBuildMaterial": True,
        }
    result = {
        key: value
        for key, value in receipt.items()
        if key not in {"acceptanceSummary", "writtenMapping", "currentProjection"}
    }
    writes = receipt.get("writtenMapping") or []
    projections = receipt.get("currentProjection") or []
    result.update(
        responseSchema="research_write_receipt_view_v1",
        detail=detail,
        acceptanceSummary=_summary(receipt.get("acceptanceSummary") or {}),
        recordCount=len(writes),
        projectionCount=len(projections),
        diagnosticSections=[{"section": k, "count": len(v)} for k, v in sections.items()],
        canonicalRecordScope="persisted_summary_not_full_content",
        recordContentRead={
            "tool": "query_research_memory",
            "detail_level": "record",
            "response_profile": "full",
            "record_ids": "Use actual recordId values from writtenMapping.",
            "note": "Record detail is its current projection; compare source binding and hashes, not a historical body snapshot.",
        },
    )
    if detail == "diagnostics":
        entries = sections[section]
        result.update(section=section, entries=entries[cursor : cursor + limit])
        count = len(entries)
    else:
        selected = writes[cursor : cursor + limit]
        selected_indexes = set(range(cursor, cursor + len(selected)))
        result["writtenMapping"] = [
            {
                **{
                    k: v
                    for k, v in item.items()
                    if k
                    not in (
                        _SUMMARY_OMITTED_FIELDS
                        if detail == "summary"
                        else {"crossFamilyDuplicateAdvisories"}
                    )
                },
                "writtenMappingIndex": cursor + offset,
            }
            for offset, item in enumerate(selected)
        ]
        result["currentProjection"] = [
            item
            for item in projections
            if type(item.get("writtenMappingIndex")) is int
            and item["writtenMappingIndex"] in selected_indexes
        ]
        result["projectionMappingComplete"] = all(
            type(item.get("writtenMappingIndex")) is int for item in projections
        ) and selected_indexes.issubset(
            {item["writtenMappingIndex"] for item in result["currentProjection"]}
        )
        count = len(writes)
    next_cursor = cursor + limit if cursor + limit < count else None
    result["pagination"] = {
        "cursor": cursor,
        "limit": limit,
        "total": count,
        "unit": "diagnostic_entry" if detail == "diagnostics" else "written_mapping",
        "nextCursor": next_cursor,
        "complete": next_cursor is None,
    }
    result["projectionScope"] = (
        "Live eligibility for this page only; counts of unreturned records do not certify them."
    )
    return deepcopy(result)
