"""Trusted PoB snapshot and Judge bridge for Agent-created generation candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from server.compute.engine import PobEngine
from server.judge import evaluator, runner, sample_audit

from . import models, preflight, run_store


def evaluate_generation_candidate(
    active_engine: Any,
    *,
    run_id: str,
    run_token: str,
    candidate_id: str,
    version_context: dict[str, Any],
    engine_factory: Callable[[], Any] = PobEngine,
    timeout_seconds: float | None = 900.0,
) -> dict[str, Any]:
    """Snapshot the active Agent-built PoB and evaluate the immutable snapshot."""
    if not _valid_candidate_id(candidate_id):
        return _rejected("invalid_candidate_id")
    try:
        version = models.VersionContext.model_validate(version_context)
    except ValidationError:
        return _rejected("invalid_version_context")
    try:
        bound_run = run_store.load_bound_run(run_id, run_token)
    except run_store.RunStoreError as exc:
        return _rejected(exc.code)

    lock_path = bound_run.run_dir / "evaluation-lock"
    if not _acquire_evaluation_lock(lock_path, timeout_seconds=timeout_seconds):
        return _rejected("generation_evaluation_in_progress")

    try:
        try:
            existing_receipts = run_store.read_trusted_evaluations_strict(bound_run)
        except run_store.RunStoreError as exc:
            return _rejected(exc.code)
        if len(existing_receipts) >= 3:
            return _rejected("retry_limit_reached")
        try:
            xml = active_engine.get_xml()
        except Exception:  # noqa: BLE001 - MCP response must not expose engine internals.
            return _rejected("active_build_snapshot_failed")

        preflight_report = preflight.inspect_generation_snapshot(active_engine, xml)
        if not preflight_report.get("readyForJudge"):
            return {
                **_rejected("generation_preflight_failed"),
                "preflight": preflight_report,
            }

        parsed = _parse_build_snapshot(xml)
        if parsed.get("errorCode"):
            return _rejected(str(parsed["errorCode"]))

        source_hash = evaluator.compute_source_hash(xml)
        snapshot_id = f"generation:{bound_run.run_id}:{source_hash}"
        captured: dict[str, Any] = {}

        def judge_engine_factory() -> Any:
            engine = engine_factory()
            try:
                engine.load_build_xml(xml, name=snapshot_id)
                captured["build"] = engine.get_build()
                return engine
            except Exception:
                close = getattr(engine, "close", None)
                if callable(close):
                    close()
                raise

        raw_judge = runner.safe_evaluate_active_build(
            judge_engine_factory,
            snapshot_id=snapshot_id,
            timeout_seconds=timeout_seconds,
            source_context="generated_candidate",
        )
        raw_judge["sourceHash"] = source_hash
        classified = sample_audit.finalize_sample_classification(raw_judge)
        state = _build_state_ref(
            parsed,
            captured.get("build") or {},
            snapshot_id=snapshot_id,
            source_hash=source_hash,
            version=version,
        )
        judge_report = _build_judge_report(
            classified,
            parsed=parsed,
            build=captured.get("build") or {},
            snapshot_id=snapshot_id,
            source_hash=source_hash,
            version=version,
        )
        receipt = {
            "candidateId": candidate_id,
            "transientBuildState": state,
            "judgeAdvisoryReport": judge_report,
        }
        try:
            attempt_index = run_store.write_trusted_evaluation(bound_run, receipt)
        except run_store.RunStoreError as exc:
            return _rejected(exc.code)
        if attempt_index is None:
            return _rejected("run_state_write_failed")
        return {
            "status": judge_report["status"],
            "attemptIndex": attempt_index,
            **receipt,
            "trustedEvaluation": True,
            "trustedEvaluationScope": "snapshot_and_judge_only",
            "versionContextTrusted": False,
            "noRawMaterial": True,
        }
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_build_snapshot(xml: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(xml)
    except (ET.ParseError, TypeError, ValueError):
        return {"errorCode": "active_build_snapshot_invalid"}
    build = root.find("Build")
    skills = root.find("Skills")
    if build is None or skills is None:
        return {"errorCode": "active_build_snapshot_invalid"}

    class_name = str(build.get("className") or "").strip()
    main_group = str(build.get("mainSocketGroup") or "1")
    skill_set_id = str(skills.get("activeSkillSet") or "1")
    skill_set = next(
        (node for node in skills.findall("SkillSet") if str(node.get("id")) == skill_set_id),
        None,
    )
    if skill_set is None:
        return {"errorCode": "missing_active_skill_group"}

    groups: list[dict[str, Any]] = []
    for index, group in enumerate(skill_set.findall("Skill"), start=1):
        if not _xml_bool(group.get("enabled"), default=True):
            continue
        gems = [gem for gem in group.findall("Gem") if _xml_bool(gem.get("enabled"), default=True)]
        active_gems = [gem for gem in gems if not _is_support_gem(gem)]
        if not active_gems:
            continue
        active_names = [str(gem.get("nameSpec") or "").strip() for gem in active_gems]
        active_names = [name for name in active_names if name]
        if not active_names:
            continue
        supports = [str(gem.get("nameSpec") or "").strip() for gem in gems if _is_support_gem(gem)]
        supports = [name for name in supports if name]
        is_main = str(index) == main_group
        groups.append(
            {
                "groupIndex": index,
                "role": "pob_main_group" if is_main else "additional_skill_group",
                "activeSkill": active_names[0],
                "activeSkills": active_names,
                "activeSkillCount": len(active_names),
                "supports": supports,
                "enabled": True,
            }
        )
    if not groups or not any(group["role"] == "pob_main_group" for group in groups):
        return {"errorCode": "missing_active_skill_group"}
    if not class_name:
        return {"errorCode": "missing_build_class"}

    return {
        "class": class_name,
        "ascendancy": str(build.get("ascendClassName") or "None"),
        "level": str(build.get("level") or "0"),
        "testedSkillGroups": groups,
        "equippedGearSlots": str(_equipped_gear_slot_count(root)),
    }


def _build_state_ref(
    parsed: dict[str, Any],
    build: dict[str, Any],
    *,
    snapshot_id: str,
    source_hash: str,
    version: models.VersionContext,
) -> dict[str, Any]:
    summary = {
        "class": str(build.get("class") or parsed["class"]),
        "ascendancy": str(build.get("ascendancy") or parsed["ascendancy"]),
        "level": str(build.get("level") or parsed["level"]),
        "mainSkill": str(build.get("mainSkill") or parsed["testedSkillGroups"][0]["activeSkill"]),
        "equippedGearSlots": parsed["equippedGearSlots"],
        "passivePointsUsed": str(build.get("pointsUsed") or 0),
        "passivePointsAvailable": str(build.get("pointsAvailable") or 0),
        "spiritUsed": str(build.get("spiritUsed") or 0),
        "spiritAvailable": str(build.get("spiritAvailable") or 0),
    }
    state = models.TransientBuildStateRef(
        status="available",
        snapshot_id=snapshot_id,
        source_hash=source_hash,
        safe_summary=summary,
        tested_skill_groups=parsed["testedSkillGroups"],
        missing_reasons=[],
        version_context=version,
        no_raw_material=True,
    )
    return state.model_dump(mode="json", by_alias=True)


def _build_judge_report(
    result: dict[str, Any],
    *,
    parsed: dict[str, Any],
    build: dict[str, Any],
    snapshot_id: str,
    source_hash: str,
    version: models.VersionContext,
) -> dict[str, Any]:
    error_kind = result.get("errorKind")
    if error_kind:
        report = models.JudgeAdvisoryReport(
            report_id=f"judge:{snapshot_id}",
            status="error",
            hard_failures=[],
            caveats=["judge_execution_failed"],
            reward_strength="unknown",
            error_code=_judge_error_code(str(error_kind)),
            version_context=version,
            no_raw_material=True,
        )
        return report.model_dump(mode="json", by_alias=True)

    aggregate = float((result.get("aggregateScore") or {}).get("value") or 0.0)
    raw_strength = str(result.get("rewardStrength") or "unknown")
    reward_strength = "limited" if raw_strength == "strong" else raw_strength
    if reward_strength not in {"limited", "none", "unknown"}:
        reward_strength = "unknown"
    modelability_status = str((result.get("modelability") or {}).get("status") or "unknown")
    score_applicability = str(
        (result.get("scoreApplicability") or {}).get("status")
        or ("unavailable" if modelability_status == "not_modelable" else "applicable")
    )
    report = models.JudgeAdvisoryReport(
        report_id=f"judge:{snapshot_id}",
        status="evaluated",
        hard_failures=[str(item) for item in result.get("hardFailures") or []],
        playability_failures=[str(item) for item in result.get("playabilityFailures") or []],
        quality_warnings=[str(item) for item in result.get("qualityWarnings") or []],
        caveats=[str(item) for item in result.get("caveats") or []],
        aggregate_score=max(0.0, min(1.0, aggregate)),
        reward_strength=reward_strength,
        reward_limit_reasons=[str(item) for item in result.get("rewardLimitReasons") or []],
        evaluated_snapshot_id=snapshot_id,
        evaluated_source_hash=source_hash,
        passed=bool(result.get("pass")),
        quality_band=str(result.get("qualityBand") or "unknown"),
        score_vector=_safe_score_vector(result.get("scoreVector") or {}),
        offense_evidence=_safe_offense_evidence(
            (result.get("scoreBreakdown") or {}).get("offense") or {}
        ),
        modelability_status=modelability_status,
        score_applicability=score_applicability,
        level_band=str(result.get("levelBand") or "unknown"),
        evaluator_version=str(
            (result.get("reproducibility") or {}).get("evaluatorVersion") or "unknown"
        ),
        final_classification=str(result.get("finalClassification") or "unknown"),
        selected_skill=_selected_skill_diagnostic(build),
        supplemental_skills=_supplemental_skill_diagnostics(build),
        skill_group_diagnostics=_skill_group_diagnostics(parsed, build),
        attribute_shortfalls=_attribute_shortfalls(build),
        version_context=version,
        no_raw_material=True,
    )
    return report.model_dump(mode="json", by_alias=True)


def _safe_offense_evidence(value: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    evidence_level = str(value.get("evidenceLevel") or "unknown")
    if evidence_level not in {"strong", "limited", "none", "unknown"}:
        evidence_level = "unknown"
    metric_status = str(value.get("metricStatus") or "unavailable")
    if metric_status not in {"available", "unavailable"}:
        metric_status = "unavailable"
    floor_status = str(value.get("floorStatus") or "unavailable")
    if floor_status not in {"met", "missed", "unverified", "unavailable"}:
        floor_status = "unavailable"
    delivery_status = str(value.get("deliveryEvidenceStatus") or "unavailable")
    if delivery_status not in {"established", "limited", "unavailable"}:
        delivery_status = "unavailable"
    source_metric = str(
        value.get("sourceMetricDetail") or value.get("sourceMetric") or "unavailable"
    )
    return {
        "rawDps": _nonnegative_float(value.get("rawDps") or value.get("rawValue")),
        "effectiveDps": _nonnegative_float(value.get("effectiveDps") or value.get("rawValue")),
        "directDps": _nonnegative_float(value.get("directDps")),
        "fullDps": _nonnegative_float(value.get("fullDps")),
        "sourceMetric": source_metric,
        "evidenceLevel": evidence_level,
        "metricStatus": metric_status,
        "observedValue": _bounded_score(value.get("observedValue")),
        "floorProgress": _bounded_score(value.get("floorProgress")),
        "floorProgressCredit": _bounded_score(value.get("floorProgressCredit")),
        "floorStatus": floor_status,
        "deliveryEvidenceStatus": delivery_status,
        "scoreConfidenceFactor": _bounded_score(value.get("scoreConfidenceFactor")),
        "scorePolicy": str(value.get("scorePolicy") or "unavailable"),
    }


def _selected_skill_diagnostic(build: dict[str, Any]) -> dict[str, Any] | None:
    selected = build.get("judgeSelectedSkill") or {}
    if not isinstance(selected, dict):
        return None
    skill_name = str(selected.get("skillName") or "").strip()
    if not skill_name:
        return None
    return {
        "skillName": skill_name,
        "groupIndex": _positive_int_or_none(selected.get("groupIndex")),
        "activeSkillCount": _nonnegative_int_or_none(selected.get("activeSkillCount")),
        "groupOrigin": str(selected.get("groupOrigin") or "unknown"),
        "groupSource": str(selected.get("groupSource")) if selected.get("groupSource") else None,
        "socketLegalityApplicable": selected.get("socketLegalityApplicable") is not False,
        "scenarioLimitations": [
            str(value) for value in selected.get("scenarioLimitations") or [] if value
        ],
    }


def _supplemental_skill_diagnostics(build: dict[str, Any]) -> list[dict[str, Any]]:
    components = build.get("judgeSupplementalSkills") or []
    if not isinstance(components, list):
        return []
    output: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            continue
        skill_name = str(component.get("skillName") or "").strip()
        if not skill_name:
            continue
        output.append(
            {
                "skillName": skill_name,
                "groupIndex": _positive_int_or_none(component.get("groupIndex")),
                "groupOrigin": str(component.get("groupOrigin") or "unknown"),
                "scenarioLimitations": [
                    str(value) for value in component.get("scenarioLimitations") or [] if value
                ],
            }
        )
    return output


def _skill_group_diagnostics(
    parsed: dict[str, Any],
    build: dict[str, Any],
) -> list[dict[str, Any]]:
    selected = build.get("judgeSelectedSkill") or {}
    selected_index = (
        _positive_int_or_none(selected.get("groupIndex")) if isinstance(selected, dict) else None
    )
    selected_group = build.get("judgeSelectedSkillGroup") or []
    diagnostics: list[dict[str, Any]] = []
    for group in parsed.get("testedSkillGroups") or []:
        group_index = _positive_int_or_none(group.get("groupIndex"))
        active_skills = list(group.get("activeSkills") or [group.get("activeSkill")])
        active_skills = [str(name) for name in active_skills if name]
        supports = [str(name) for name in group.get("supports") or [] if name]
        if (
            selected_index is not None
            and group_index == selected_index
            and isinstance(selected_group, list)
            and selected_group
        ):
            readback_active = [
                str(gem.get("name") or "").strip()
                for gem in selected_group
                if isinstance(gem, dict) and not gem.get("isSupport") and gem.get("name")
            ]
            readback_supports = [
                str(gem.get("name") or "").strip()
                for gem in selected_group
                if isinstance(gem, dict) and gem.get("isSupport") and gem.get("name")
            ]
            if readback_active:
                active_skills = readback_active
            supports = readback_supports
        diagnostics.append(
            {
                "groupIndex": group_index,
                "activeSkills": active_skills,
                "activeSkillCount": len(active_skills),
                "supports": supports,
                "supportCount": len(supports),
                "singleActiveSkillValid": len(active_skills) == 1,
                "groupOrigin": (
                    str(selected.get("groupOrigin") or "unknown")
                    if group_index == selected_index and isinstance(selected, dict)
                    else "socketed"
                ),
                "groupSource": (
                    str(selected.get("groupSource"))
                    if group_index == selected_index
                    and isinstance(selected, dict)
                    and selected.get("groupSource")
                    else None
                ),
                "selectedByJudge": group_index == selected_index,
            }
        )
    known_indices = {item["groupIndex"] for item in diagnostics}
    if (
        selected_index is not None
        and selected_index not in known_indices
        and isinstance(selected, dict)
    ):
        selected_name = str(selected.get("skillName") or "").strip()
        readback_active = [
            str(gem.get("name") or "").strip()
            for gem in selected_group
            if isinstance(gem, dict) and not gem.get("isSupport") and gem.get("name")
        ]
        readback_supports = [
            str(gem.get("name") or "").strip()
            for gem in selected_group
            if isinstance(gem, dict) and gem.get("isSupport") and gem.get("name")
        ]
        if not readback_active and selected_name:
            readback_active = [selected_name]
        diagnostics.append(
            {
                "groupIndex": selected_index,
                "activeSkills": readback_active,
                "activeSkillCount": len(readback_active),
                "supports": readback_supports,
                "supportCount": len(readback_supports),
                "singleActiveSkillValid": len(readback_active) == 1,
                "groupOrigin": str(selected.get("groupOrigin") or "unknown"),
                "groupSource": (
                    str(selected.get("groupSource")) if selected.get("groupSource") else None
                ),
                "selectedByJudge": True,
            }
        )
    return diagnostics


def _attribute_shortfalls(build: dict[str, Any]) -> list[dict[str, Any]]:
    attributes = build.get("attributes") or build.get("attributeTotals") or {}
    requirements = build.get("attributeRequirements") or {}
    if not isinstance(attributes, dict) or not isinstance(requirements, dict):
        return []
    aliases = {
        "strength": ("strength", "str", "Str"),
        "dexterity": ("dexterity", "dex", "Dex"),
        "intelligence": ("intelligence", "int", "Int"),
    }
    output: list[dict[str, Any]] = []
    for attribute, keys in aliases.items():
        current = _first_number(attributes, keys)
        required = _first_number(requirements, keys)
        if required > current:
            output.append(
                {
                    "attribute": attribute,
                    "current": current,
                    "required": required,
                    "shortfall": required - current,
                }
            )
    return output


def _first_number(values: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in values:
            try:
                return max(0.0, float(values.get(key) or 0.0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _positive_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _nonnegative_int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_score_vector(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for dimension in ("offense", "defense", "recovery", "mobility"):
        raw = value.get(dimension) if isinstance(value, dict) else {}
        raw = raw if isinstance(raw, dict) else {}
        score = float(raw.get("value") or 0.0)
        output[dimension] = {
            "value": max(0.0, min(1.0, score)),
            "blocked": bool(raw.get("blocked")),
        }
    return output


def _bounded_score(value: Any) -> float:
    return min(1.0, _nonnegative_float(value))


def _nonnegative_float(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, parsed)


def _equipped_gear_slot_count(root: ET.Element) -> int:
    items = root.find("Items")
    if items is None:
        return 0
    active_id = str(items.get("activeItemSet") or "1")
    item_set = next(
        (node for node in items.findall("ItemSet") if str(node.get("id")) == active_id),
        None,
    )
    if item_set is None:
        return 0
    return sum(1 for slot in item_set.findall("Slot") if str(slot.get("itemId") or "0") != "0")


def _is_support_gem(gem: ET.Element) -> bool:
    gem_id = str(gem.get("gemId") or "")
    skill_id = str(gem.get("skillId") or "")
    return "SupportGem" in gem_id or skill_id.startswith("Support")


def _xml_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.casefold() in {"1", "true"}


def _valid_candidate_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 160
        and value.strip() == value
        and not any(ord(char) < 32 for char in value)
    )


def _acquire_evaluation_lock(path: Path, *, timeout_seconds: float | None) -> bool:
    try:
        path.open("x", encoding="utf-8").close()
        return True
    except FileExistsError:
        pass
    except OSError:
        return False

    timeout_budget = max(float(timeout_seconds or 900.0), 1.0)
    try:
        age_seconds = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except OSError:
        age_seconds = 0.0
    if age_seconds <= timeout_budget + 60.0:
        return False

    abandoned = path.with_name(f".{path.name}.{uuid4().hex}.stale")
    try:
        path.replace(abandoned)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    else:
        try:
            abandoned.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        path.open("x", encoding="utf-8").close()
        return True
    except (FileExistsError, OSError):
        return False


def _judge_error_code(error_kind: str) -> str:
    normalized = error_kind.casefold()
    if "timeout" in normalized:
        return "judge_timeout"
    if any(token in normalized for token in ("pobengine", "eof", "oserror", "file")):
        return "judge_process_error"
    if any(token in normalized for token in ("json", "protocol", "decode")):
        return "judge_protocol_error"
    return "judge_internal_error"


def _rejected(error_code: str) -> dict[str, Any]:
    return {
        "status": "rejected",
        "errorCode": error_code,
        "trustedEvaluation": False,
        "trustedEvaluationScope": "none",
        "versionContextTrusted": False,
        "noRawMaterial": True,
    }
