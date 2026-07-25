"""Complete local delivery package for a verified multi-stage progression route."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from server import paths
from server.build_planner import exporter as build_planner_exporter
from server.compute.pob_code import encode_code
from server.knowledge import copy_safety

from . import artifacts, progression


def export_build_progression_package(
    route_id: str,
    *,
    name: str = "",
    author: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Export every stage as PoB files and only the target as an official `.build`."""

    route = progression.read_progression_route(route_id)
    if route is None:
        return {"status": "rejected", "errorCode": "progression_route_not_found"}
    metadata = {"name": name, "author": author, "description": description}
    if copy_safety.copyability_flags(metadata) or copy_safety.contains_raw_url(metadata):
        return {
            "status": "rejected",
            "errorCode": "unsafe_progression_export_metadata",
        }
    package_name = _safe_filename(name or route["routeName"])
    package_dir = (
        paths.build_progression_exports_dir() / f"{package_name}-{route_id[:8]}-{uuid4().hex[:8]}"
    )
    try:
        package_dir.mkdir(parents=True, exist_ok=False)
    except OSError:
        return {"status": "rejected", "errorCode": "progression_export_directory_failed"}

    inventory: list[dict[str, Any]] = []
    for ordinal, stage in enumerate(route["stages"], start=1):
        artifact_id = stage["artifactId"]
        loaded = artifacts.read_final_build_artifact_for_export(artifact_id)
        stem = _safe_filename(
            f"{ordinal:02d}-{stage['stageId'].removeprefix('stage:')}-level-{stage['targetLevel']}"
        )
        if loaded is None:
            inventory.extend(
                [
                    _failed_row("stage_pob_xml", stage["stageId"], "final_artifact_invalid"),
                    _failed_row(
                        "stage_pob_import_code",
                        stage["stageId"],
                        "final_artifact_invalid",
                    ),
                ]
            )
            continue
        manifest, xml = loaded
        for artifact_type, suffix, content in (
            ("stage_pob_xml", ".xml", xml),
            ("stage_pob_import_code", ".pobcode.txt", encode_code(xml) + "\n"),
        ):
            output = package_dir / f"{stem}{suffix}"
            try:
                _atomic_write(output, content)
            except OSError:
                inventory.append(
                    _failed_row(artifact_type, stage["stageId"], "pob_export_write_failed")
                )
            else:
                inventory.append(
                    {
                        "artifactType": artifact_type,
                        "stageId": stage["stageId"],
                        "artifactId": manifest.artifact_id,
                        "status": "exported",
                        "outputPath": str(output),
                        "errorCode": None,
                    }
                )

    guide_output = package_dir / "progression-route.md"
    try:
        _atomic_write(guide_output, _route_guide(route))
    except OSError:
        inventory.append(_failed_row("progression_route_guide", None, "route_guide_write_failed"))
    else:
        inventory.append(
            {
                "artifactType": "progression_route_guide",
                "stageId": None,
                "status": "exported",
                "outputPath": str(guide_output),
                "errorCode": None,
            }
        )

    target_artifact_id = route["targetArtifactId"]
    official_output = package_dir / f"{package_name}-target.build"
    official = build_planner_exporter.export_final_build_artifact(
        target_artifact_id,
        name=name or route["routeName"],
        author=author,
        description=description or route["routeSummary"],
        _destination_path=official_output,
    )
    if official.get("status") == "exported" and official.get("outputPath"):
        output = Path(str(official["outputPath"]))
        if output.resolve() != official_output.resolve() or not output.is_file():
            inventory.append(
                _failed_row("target_official_build", None, "build_package_destination_mismatch")
            )
        else:
            inventory.append(
                {
                    "artifactType": "target_official_build",
                    "stageId": route["stages"][-1]["stageId"],
                    "artifactId": target_artifact_id,
                    "status": "exported",
                    "outputPath": str(output),
                    "errorCode": None,
                    "warnings": official.get("warnings") or [],
                    "singleStage": True,
                }
            )
    else:
        inventory.append(
            {
                **_failed_row(
                    "target_official_build",
                    route["stages"][-1]["stageId"],
                    str(official.get("errorCode") or "build_export_failed"),
                ),
                "artifactId": target_artifact_id,
                "warnings": official.get("warnings") or [],
                "singleStage": True,
            }
        )

    exported_count = sum(row["status"] == "exported" for row in inventory)
    expected_count = len(route["stages"]) * 2 + 2
    return {
        "status": "exported" if exported_count == expected_count else "partial",
        "routeId": route_id,
        "targetArtifactId": target_artifact_id,
        "packageDirectory": str(package_dir),
        "artifacts": inventory,
        "exportedCount": exported_count,
        "expectedCount": expected_count,
        "officialBuildScope": "target_stage_only",
        "responseContainsRawPob": False,
        "localFilesContainPobMaterial": True,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
    }


def _route_guide(route: dict[str, Any]) -> str:
    facts = {
        item["artifactId"]: item
        for item in route.get("artifactFacts", [])
        if isinstance(item, dict) and item.get("artifactId")
    }
    lines = [
        f"# {route['routeName']}",
        "",
        route["routeSummary"],
        "",
        f"- 基础职业：{route['classShell']}",
        f"- 路线质量：{route['qualityStatus']}",
        f"- 目标 artifact：{route['targetArtifactId']}",
        "",
        "## 阶段",
        "",
    ]
    for stage in route["stages"]:
        fact = facts.get(stage["artifactId"], {})
        cost = stage.get("costProfile") or {}
        lines.extend(
            [
                f"### {stage['stageId']} · 等级 {stage['targetLevel']}",
                "",
                f"- 路线角色：{stage['routeRole']}",
                f"- 生命周期：{stage['lifecycleStage']}",
                f"- 证据状态：{stage['evidenceStatus']}",
                f"- 目的：{stage['purpose']}",
                f"- 操作循环：{stage['playPattern']}",
                (
                    "- 成本画像："
                    f"最高必需档位 {cost.get('highestRequiredBand', 'unknown')}"
                    f"；必需依赖 {cost.get('requiredDependencyCount', 'unknown')}"
                    f"；付费依赖 {cost.get('paidDependencyCount', 'unknown')}"
                    f"；未知必需依赖 {cost.get('unknownRequiredDependencyCount', 'unknown')}"
                    f"；平替覆盖 {cost.get('fallbackCoverage', 'unknown')}"
                    f"；实时价格覆盖 {cost.get('livePriceCoverage', 'unknown')}"
                    f"；证据 {cost.get('costEvidenceStatus', 'unknown')}"
                ),
                (
                    "- 价格联盟/基准："
                    f"{cost.get('league', 'unknown')} / "
                    f"{cost.get('baseCurrency') or 'unknown'}"
                ),
                f"- 成本画像引用：{stage.get('costProfileRef') or 'unknown'}",
                f"- Judge 可评分性：{fact.get('judgeScoreApplicability', 'unknown')}",
                f"- Judge modelability：{fact.get('judgeModelabilityStatus') or 'unknown'}",
                "",
            ]
        )
        changes = stage.get("changesFromPrevious") or []
        if changes:
            lines.extend(["阶段变化：", ""])
            for change in changes:
                replacement = f"（替换 {change['replaces']}）" if change.get("replaces") else ""
                lines.append(
                    f"- [{change['category']}/{change['action']}] "
                    f"{change['subject']}{replacement}：{change['reason']}"
                )
            lines.append("")
        priorities = stage.get("acquisitionPriorities") or []
        if priorities:
            lines.extend(["获取优先级：", "", *[f"- {item}" for item in priorities], ""])
        bridge = stage.get("transitionBridge")
        if isinstance(bridge, dict):
            lines.extend(
                [
                    f"转型桥梁：{bridge['summary']}",
                    "",
                    *[
                        f"- [{requirement['status']}] {requirement['description']}"
                        for requirement in bridge["requirements"]
                    ],
                    "",
                ]
            )
        caveats = stage.get("caveats") or []
        judge_disclosures = [
            *fact.get("judgePlayabilityFailures", []),
            *fact.get("judgeQualityWarnings", []),
            *fact.get("judgeCaveats", []),
        ]
        if caveats:
            lines.extend(["注意事项：", "", *[f"- {item}" for item in caveats], ""])
        if judge_disclosures:
            lines.extend(
                [
                    "Judge / modelability 披露：",
                    "",
                    *[f"- {item}" for item in judge_disclosures],
                    "",
                ]
            )
    lines.extend(
        [
            "## 交付边界",
            "",
            "每个阶段都包含独立 PoB XML 与导入码；官方 `.build` 仅表示目标阶段。",
            "价格档位只用于说明获取风险，不是自动转型条件。",
            "",
        ]
    )
    return "\n".join(lines)


def _failed_row(
    artifact_type: str,
    stage_id: str | None,
    error_code: str,
) -> dict[str, Any]:
    return {
        "artifactType": artifact_type,
        "stageId": stage_id,
        "status": "failed",
        "outputPath": None,
        "errorCode": error_code,
    }


def _atomic_write(path: Path, content: str) -> None:
    temp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return cleaned[:80] or "poe2-progression"
