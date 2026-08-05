"""Complete local delivery package for a verified multi-stage progression route."""

from __future__ import annotations

import hashlib
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


def export_build_progression_recovery_package(
    state: dict[str, Any],
    *,
    name: str = "",
    author: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Export recoverable verified artifacts from any unfinished anchored progression.

    This deliberately cannot produce a Route artifact or claim a complete progression.  It gives
    the user the immutable target anchor (and any already completed milestones) instead of turning
    a late stage failure, control-plane timeout, or approval interruption into a zero-file delivery.
    """

    progression_status = str(state.get("status") or "")
    if progression_status == "completed":
        return {"status": "rejected", "errorCode": "progression_recovery_not_available"}
    target = state.get("targetAnchor") or {}
    target_artifact_id = target.get("artifactId")
    if target.get("status") not in {"bound", "anchor_bound"} or not isinstance(
        target_artifact_id, str
    ):
        return {"status": "rejected", "errorCode": "progression_recovery_target_not_bound"}
    metadata = {"name": name, "author": author, "description": description}
    if copy_safety.copyability_flags(metadata) or copy_safety.contains_raw_url(metadata):
        return {"status": "rejected", "errorCode": "unsafe_progression_export_metadata"}

    progression_id = str(state.get("progressionId") or "")
    blueprint = state.get("blueprint") or {}
    route_name = str(
        name
        or blueprint.get("routeName")
        or f"{state.get('request', {}).get('baseClass', 'PoE2')}-progression-recovery"
    )
    package_name = _safe_filename(route_name)
    package_dir = (
        paths.build_progression_exports_dir()
        / f"{package_name}-{progression_id[:8]}-{uuid4().hex[:8]}-incomplete"
    )
    try:
        package_dir.mkdir(parents=True, exist_ok=False)
    except OSError:
        return {"status": "rejected", "errorCode": "progression_export_directory_failed"}

    blueprints_by_id = {
        item.get("stageId"): item
        for item in blueprint.get("stages", [])
        if isinstance(item, dict) and item.get("stageId")
    }
    recoverable: list[dict[str, Any]] = []
    seen_artifacts: set[str] = set()
    for stage in state.get("stages", []):
        artifact_id = stage.get("artifactId")
        if stage.get("status") != "completed" or not isinstance(artifact_id, str):
            continue
        stage_id = str(stage.get("stageId") or "stage:unknown")
        stage_blueprint = blueprints_by_id.get(stage_id) or {}
        recoverable.append(
            {
                "stageId": stage_id,
                "targetLevel": stage_blueprint.get("targetLevel") or 0,
                "artifactId": artifact_id,
                "scope": "completed_stage",
            }
        )
        seen_artifacts.add(artifact_id)
    if target_artifact_id not in seen_artifacts:
        recoverable.append(
            {
                "stageId": "stage:target-anchor-recovery",
                "targetLevel": state.get("request", {}).get("targetLevel") or 0,
                "artifactId": target_artifact_id,
                "scope": "target_anchor",
            }
        )

    inventory: list[dict[str, Any]] = []
    for ordinal, item in enumerate(recoverable, start=1):
        loaded = artifacts.read_final_build_artifact_for_export(item["artifactId"])
        if loaded is None:
            inventory.extend(
                [
                    _failed_row("stage_pob_xml", item["stageId"], "final_artifact_invalid"),
                    _failed_row(
                        "stage_pob_import_code",
                        item["stageId"],
                        "final_artifact_invalid",
                    ),
                ]
            )
            continue
        manifest, xml = loaded
        stem = _safe_filename(
            f"{ordinal:02d}-{item['stageId'].removeprefix('stage:')}-level-{item['targetLevel']}"
        )
        for artifact_type, suffix, content in (
            ("stage_pob_xml", ".xml", xml),
            ("stage_pob_import_code", ".pobcode.txt", encode_code(xml) + "\n"),
        ):
            output = package_dir / f"{stem}{suffix}"
            try:
                _atomic_write(output, content)
            except OSError:
                inventory.append(
                    _failed_row(artifact_type, item["stageId"], "pob_export_write_failed")
                )
            else:
                inventory.append(
                    {
                        "artifactType": artifact_type,
                        "stageId": item["stageId"],
                        "artifactId": manifest.artifact_id,
                        "status": "exported",
                        "outputPath": str(output),
                        "errorCode": None,
                        "recoveryScope": item["scope"],
                    }
                )

    failed_stage = next(
        (item for item in state.get("stages", []) if item.get("status") == "failed"),
        None,
    )
    guide_output = package_dir / "progression-recovery.md"
    guide = _recovery_guide(
        route_name=route_name,
        target_artifact_id=target_artifact_id,
        failed_stage=failed_stage,
        state=state,
    )
    try:
        _atomic_write(guide_output, guide)
    except OSError:
        inventory.append(
            _failed_row("progression_recovery_guide", None, "route_guide_write_failed")
        )
    else:
        inventory.append(
            {
                "artifactType": "progression_recovery_guide",
                "stageId": None,
                "status": "exported",
                "outputPath": str(guide_output),
                "errorCode": None,
            }
        )

    official_output = package_dir / f"{package_name}-target-recovery.build"
    official = build_planner_exporter.export_final_build_artifact(
        target_artifact_id,
        name=name or route_name,
        author=author,
        description=description or "Incomplete progression recovery: verified target stage only.",
        _destination_path=official_output,
    )
    if official.get("status") == "exported" and official.get("outputPath"):
        output = Path(str(official["outputPath"]))
        if output.resolve() == official_output.resolve() and output.is_file():
            inventory.append(
                {
                    "artifactType": "target_official_build",
                    "stageId": "stage:target-anchor-recovery",
                    "artifactId": target_artifact_id,
                    "status": "exported",
                    "outputPath": str(output),
                    "errorCode": None,
                    "warnings": official.get("warnings") or [],
                    "singleStage": True,
                    "recoveryScope": "target_anchor",
                }
            )
        else:
            inventory.append(
                _failed_row("target_official_build", None, "build_package_destination_mismatch")
            )
    else:
        inventory.append(
            {
                **_failed_row(
                    "target_official_build",
                    "stage:target-anchor-recovery",
                    str(official.get("errorCode") or "build_export_failed"),
                ),
                "artifactId": target_artifact_id,
                "warnings": official.get("warnings") or [],
                "singleStage": True,
                "recoveryScope": "target_anchor",
            }
        )

    return {
        "status": "partial",
        "progressionId": progression_id,
        "progressionState": progression_status,
        "routeId": None,
        "routeIncomplete": True,
        "recoveryReason": "stage_failed" if failed_stage else "route_incomplete",
        "targetArtifactId": target_artifact_id,
        "activeStageId": state.get("activeStageId"),
        "failedStageId": failed_stage.get("stageId") if failed_stage else None,
        "failureCode": failed_stage.get("failureCode") if failed_stage else None,
        "packageDirectory": str(package_dir),
        "artifacts": inventory,
        "exportedCount": sum(row["status"] == "exported" for row in inventory),
        "expectedCount": len(recoverable) * 2 + 2,
        "officialBuildScope": "verified_target_anchor_recovery_only",
        "responseContainsRawPob": False,
        "localFilesContainPobMaterial": True,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
    }


def _recovery_guide(
    *,
    route_name: str,
    target_artifact_id: str,
    failed_stage: dict[str, Any] | None,
    state: dict[str, Any],
) -> str:
    pending = [
        str(item.get("stageId"))
        for item in state.get("stages", [])
        if item.get("status") not in {"completed", "failed"}
    ]
    target_coverage = (state.get("targetAnchor") or {}).get("designCoverage") or {}
    target_caveats = list(target_coverage.get("unresolvedCaveats") or [])
    lines = [
        f"# {route_name} · 未完成路线恢复包",
        "",
        "这不是完整成长路线。流程尚未完成，只恢复交付已经可信保存的文件。",
        "",
        f"- 当前流程状态：{state.get('status') or 'unknown'}",
        f"- 当前活动阶段：{state.get('activeStageId') or 'none'}",
        f"- 目标 artifact：{target_artifact_id}",
        *(
            [
                f"- 失败阶段：{failed_stage.get('stageId') or 'unknown'}",
                f"- 失败代码：{failed_stage.get('failureCode') or 'unknown'}",
            ]
            if failed_stage
            else ["- 失败记录：尚未写入；路线在运行中或控制/审批步骤中断"]
        ),
        f"- 尚未完成：{', '.join(pending) if pending else 'none'}",
        "",
        *(
            [
                "目标 Research / 机制限制：",
                "",
                *[f"- {item}" for item in target_caveats],
                "",
            ]
            if target_caveats
            else []
        ),
        "目标 `.build` 只表示目标阶段，不能据此声称早期成长路线已经验证。",
        "",
    ]
    return "\n".join(lines)


def _route_guide(route: dict[str, Any]) -> str:
    facts = {
        item["artifactId"]: item
        for item in route.get("artifactFacts", [])
        if isinstance(item, dict) and item.get("artifactId")
    }
    target_coverage = route.get("targetDesignCoverage") or {}
    target_caveats = list(target_coverage.get("unresolvedCaveats") or [])
    lines = [
        f"# {route['routeName']}",
        "",
        route["routeSummary"],
        "",
        f"- 职业起点：{route['classShell']}",
        f"- 最终目标等级：{route['stages'][-1]['targetLevel']}",
        "",
        *(
            [
                "## 开始前先知道的限制",
                "",
                *[f"- {item}" for item in target_caveats],
                "",
            ]
            if target_caveats
            else []
        ),
        "## 从建号到成型",
        "",
    ]
    for stage in route["stages"]:
        player_guide = stage.get("playerGuide") or {}
        lines.extend(
            [
                f"### 等级 {stage['targetLevel']}：这一阶段怎么打",
                "",
                "#### 这一阶段要完成什么",
                "",
                stage["purpose"],
                "",
            ]
        )
        mechanic_explanation = player_guide.get("mechanicExplanation")
        if mechanic_explanation:
            lines.extend(["#### 为什么这样搭配", "", mechanic_explanation, ""])
        lines.extend(["#### 实战怎么操作", "", stage["playPattern"], ""])
        leveling_steps = player_guide.get("levelingSteps") or []
        if leveling_steps:
            lines.extend(
                [
                    "#### 这段等级怎么成长",
                    "",
                    *[f"{index}. {item}" for index, item in enumerate(leveling_steps, start=1)],
                    "",
                ]
            )
        changes = stage.get("changesFromPrevious") or []
        if changes:
            lines.extend(["#### 相比上一阶段，主要变了什么", ""])
            for change in changes:
                if change.get("replaces"):
                    lines.append(
                        f"- **{change['subject']}**：替换 {change['replaces']}。{change['reason']}"
                    )
                else:
                    lines.append(f"- **{change['subject']}**：{change['reason']}")
            lines.append("")
        priorities = stage.get("acquisitionPriorities") or []
        if priorities:
            lines.extend(
                [
                    "#### 装备、技能和天赋先做什么",
                    "",
                    *[f"- {item}" for item in priorities],
                    "",
                ]
            )
        common_problems = player_guide.get("commonProblems") or []
        if common_problems:
            lines.extend(["#### 常见问题怎么处理", ""])
            for problem in common_problems:
                lines.append(f"- **{problem['symptom']}**：{problem['solution']}")
            lines.append("")
        bridge = stage.get("transitionBridge")
        if isinstance(bridge, dict):
            lines.extend(
                [
                    "#### 什么时候可以进入下一阶段",
                    "",
                    bridge["summary"],
                    "",
                    *[
                        (
                            f"- [{'x' if requirement['status'] == 'satisfied' else ' '}] "
                            f"{requirement['description']}"
                        )
                        for requirement in bridge["requirements"]
                    ],
                    "",
                ]
            )
        caveats = stage.get("caveats") or []
        if caveats:
            lines.extend(["#### 容易踩坑的地方", "", *[f"- {item}" for item in caveats], ""])

    lines.extend(
        [
            "## 技术验证附录",
            "",
            "下面是给复核者看的内部验证与成本元数据；正常游玩只需阅读前面的成长说明。",
            "",
            f"- 路线质量：{route['qualityStatus']}",
            f"- 目标 artifact：{route['targetArtifactId']}",
            "",
        ]
    )
    for stage in route["stages"]:
        fact = facts.get(stage["artifactId"], {})
        cost = stage.get("costProfile") or {}
        lines.extend(
            [
                f"### 等级 {stage['targetLevel']} 验证记录",
                "",
                f"- stageId：{stage['stageId']}",
                f"- 路线角色：{stage['routeRole']}",
                f"- 生命周期：{stage['lifecycleStage']}",
                f"- 证据状态：{stage['evidenceStatus']}",
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
        judge_disclosures = [
            *fact.get("judgePlayabilityFailures", []),
            *fact.get("judgeQualityWarnings", []),
            *fact.get("judgeCaveats", []),
        ]
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
    # Do not repeat the full destination filename in the temporary sibling.  On Windows that can
    # push only the longer import-code file over MAX_PATH even though its XML sibling succeeds.
    temp = path.parent / f".tmp-{uuid4().hex}.tmp"
    try:
        temp.write_text(content, encoding="utf-8")
        temp.replace(path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    # The package directory and stage filename are composed together.  Keeping each component
    # short prevents Windows MAX_PATH failures where XML succeeds but the longer `.pobcode.txt`
    # sibling silently becomes the only failed inventory row. Preserve a content suffix when
    # truncating so two long stage ids with the same prefix cannot overwrite one another.
    if len(cleaned) > 48:
        digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8]
        cleaned = f"{cleaned[:39]}-{digest}"
    return cleaned or "poe2-progression"
