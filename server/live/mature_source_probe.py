"""Safe comparison helpers for mature sample sources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_ORDER = {"low": 1, "medium": 2, "high": 3}
_RAW_KEYS = {"rawHtml", "rawJson", "rawPayload", "rawContent", "payload", "html", "json"}
_METRIC_LABELS = {
    "discoverability": "发现便利度",
    "popularityTrust": "热度可信度",
    "payloadRichness": "payload 丰富度",
    "sanitizationBurden": "清洗负担",
    "duplicationRisk": "重复风险",
    "browserDependence": "浏览器依赖",
}
_UNKNOWN_LEVEL = "unknown"


def compare_sources(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a copy-safe comparison matrix and role recommendations."""
    sanitized_rows = [_sanitize_probe_row(row) for row in rows]
    if not sanitized_rows:
        return {
            "ok": False,
            "sources": [],
            "recommended": {
                "discoverySource": None,
                "payloadSource": None,
            },
            "unavailableReason": "no source probes supplied",
        }

    discovery = max(
        sanitized_rows,
        key=lambda row: (
            _score(row["discoverability"]),
            _score(row["popularityTrust"]),
            -_score(row["browserDependence"]),
        ),
    )
    payload_candidates = [
        row for row in sanitized_rows if _shape_ok_bonus(row.get("shapeReport", {})) > 0
    ]
    payload = (
        max(
            payload_candidates,
            key=lambda row: (
                _score(row["payloadRichness"]),
                -_score(row["sanitizationBurden"]),
                -_score(row["duplicationRisk"]),
                -_score(row["browserDependence"]),
            ),
        )
        if payload_candidates
        else None
    )
    return {
        "ok": True,
        "sources": sanitized_rows,
        "recommended": {
            "discoverySource": discovery["sourceType"],
            "payloadSource": payload["sourceType"] if payload else None,
        },
    }


def render_probe_report(report: Mapping[str, Any]) -> str:
    """Render a Chinese, copy-safe source probe report."""
    safe_report = _strip_raw_fields(report)
    recommended = safe_report.get("recommended", {})
    lines = [
        "# 成熟样本源探测报告",
        "",
        f"- 推荐的热门发现源：`{recommended.get('discoverySource', 'unknown')}`",
        f"- 推荐的 payload 源：`{recommended.get('payloadSource', 'unknown')}`",
        "",
        "## 候选源矩阵",
    ]
    for row in safe_report.get("sources", []):
        lines.append(f"### `{row.get('sourceType', 'unknown')}`")
        shape_report = row.get("shapeReport", {})
        if isinstance(shape_report, Mapping):
            ok_label = "可用于 payload 采样" if shape_report.get("ok") else "仅适合辅助判断"
            lines.append(f"- Shape 结论：{ok_label}")
            if shape_report.get("unavailableReason"):
                lines.append(f"- Shape 摘要：{shape_report['unavailableReason']}")
            if shape_report.get("responseShape"):
                lines.append(f"- 响应结构：{_format_shape(shape_report['responseShape'])}")
            if shape_report.get("rowShape"):
                lines.append(f"- 行结构：{_format_shape(shape_report['rowShape'])}")
        for key, label in _METRIC_LABELS.items():
            if key in row:
                lines.append(f"- {label}：`{row[key]}`")
        lines.append("")
    return "\n".join(lines).strip()


def _sanitize_probe_row(row: Mapping[str, Any]) -> dict[str, Any]:
    shape_report = row.get("shapeReport", {})
    safe_shape = _strip_raw_fields(shape_report if isinstance(shape_report, Mapping) else {})
    safe_row = {
        "sourceType": _safe_text(row.get("sourceType"), default="unknown"),
        "shapeReport": safe_shape,
    }
    for key in _METRIC_LABELS:
        safe_row[key] = _normalize_level(row.get(key))
    return safe_row


def _strip_raw_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_raw_fields(item) for key, item in value.items() if not _is_raw_key(key)
        }
    if isinstance(value, list):
        return [_strip_raw_fields(item) for item in value]
    return value


def _score(level: str) -> int:
    return _ORDER.get(str(level).lower(), 0)


def _shape_ok_bonus(shape_report: Mapping[str, Any]) -> int:
    return 1 if shape_report.get("ok") else 0


def _normalize_level(value: Any) -> str:
    normalized = _safe_text(value, default=_UNKNOWN_LEVEL).lower()
    return normalized if normalized in _ORDER else _UNKNOWN_LEVEL


def _safe_text(value: Any, *, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _is_raw_key(key: Any) -> bool:
    normalized = "".join(ch for ch in str(key).lower() if ch.isalnum())
    return normalized in {
        "rawhtml",
        "rawjson",
        "rawpayload",
        "rawcontent",
        "payload",
        "html",
        "json",
    }


def _format_shape(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
