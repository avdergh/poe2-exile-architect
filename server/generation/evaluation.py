"""Trusted PoB snapshot and Judge bridge for Agent-created generation candidates."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Callable

from pydantic import ValidationError

from server.compute.engine import PobEngine
from server.compute.state import build_state_hash
from server.judge import evaluator, rules, runner, sample_audit
from server.knowledge import research_memory

from . import (
    evaluation_snapshots,
    mechanism_evidence,
    mechanism_signature,
    models,
    preflight,
    progression_provenance,
    run_store,
    validation_checkpoint,
)


def evaluate_generation_candidate(
    active_engine: Any,
    *,
    run_id: str,
    run_token: str,
    candidate_id: str,
    version_context: dict[str, Any],
    strict_mode: bool = False,
    offense_skill_group_index: int | None = None,
    expected_skill_name: str | None = None,
    engine_factory: Callable[[], Any] = PobEngine,
    timeout_seconds: float | None = 900.0,
    receipt_reader: Callable[[str], dict[str, Any] | None] | None = None,
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
    if run_store.generation_contract_upgrade_required(bound_run.manifest):
        return {
            **_rejected("generation_contract_upgrade_requires_restart"),
            "attemptConsumed": False,
        }
    memory_mode = str(
        ((bound_run.manifest or {}).get("experimentContext") or {}).get("memoryMode") or ""
    )
    draft_required = bool(
        ((bound_run.manifest or {}).get("experimentContext") or {}).get(
            "mechanismBlueprintRequired"
        )
    )
    if memory_mode == "memory_assisted" and _family_discovery_binding(bound_run) is None:
        return {
            **_rejected("generation_family_discovery_required"),
            "attemptConsumed": False,
        }
    if draft_required and not _draft_validation_matches(
        bound_run,
        candidate_id=candidate_id,
        research_memory_ref=version.research_memory_ref,
        memory_mode=memory_mode,
    ):
        return {
            **_rejected("generation_draft_validation_required"),
            "attemptConsumed": False,
        }

    # Fail fast on research-receipt provenance before any attempt is consumed: the receipt is
    # bound into the trusted evaluation and cannot be replaced later, while validate/review only
    # enforce the run-freshness rule after the fact. A stale or missing ref would otherwise
    # strand the whole run. Only the exact ``disabled:no_memory_baseline`` sentinel (--no-memory)
    # skips receipt lookup; any other ``disabled:*`` prefix is a typo or an unsupported mode and
    # must not silently consume a Judge attempt.
    research_ref = version.research_memory_ref
    if research_ref == "disabled:no_memory_baseline":
        research_receipt = None
    elif research_ref.startswith("disabled:"):
        return {
            **_rejected("invalid_research_memory_ref"),
            "attemptConsumed": False,
            "detail": (
                "only the exact 'disabled:no_memory_baseline' sentinel disables receipt lookup; "
                "other disabled:* refs are rejected without consuming an attempt"
            ),
        }
    else:
        if not research_ref.startswith("dq-"):
            return {
                **_rejected("invalid_research_memory_ref"),
                "attemptConsumed": False,
            }
        reader = receipt_reader or research_memory.ResearchMemoryService().read_query_receipt
        research_receipt = reader(research_ref)
        started_at = str((bound_run.manifest or {}).get("startedAt") or "")
        if research_receipt is None:
            return {
                **_rejected("research_memory_receipt_missing"),
                "attemptConsumed": False,
            }
        if not progression_provenance.receipt_was_seen_at_or_after(research_receipt, started_at):
            return {
                **_rejected("research_memory_receipt_not_current_run"),
                "attemptConsumed": False,
                "detail": (
                    "the version_context.researchMemoryRef must identify a query receipt created "
                    "after this Phase 5 run started; re-query Research inside the current run and "
                    "pass the new dedupeQueryRef"
                ),
            }

    lock_path = bound_run.run_dir / "evaluation-lock"
    if not _acquire_evaluation_lock(lock_path, timeout_seconds=timeout_seconds):
        return _rejected("generation_evaluation_in_progress")

    try:
        if bound_run.artifact_selection_path.exists():
            return {**_rejected("final_artifact_already_exists"), "attemptConsumed": False}
        try:
            existing_receipts = run_store.read_trusted_evaluations_strict(bound_run)
        except run_store.RunStoreError as exc:
            return _rejected(exc.code)
        if len(existing_receipts) >= 3:
            return _rejected("retry_limit_reached")
        requested_feedback_mode = "strict" if strict_mode else "hard_only"
        if existing_receipts:
            existing_feedback_mode = str(
                (existing_receipts[0].get("judgeAdvisoryReport") or {}).get(
                    "feedbackMode",
                    "strict",
                )
            )
            if existing_feedback_mode != requested_feedback_mode:
                return {
                    **_rejected("judge_feedback_mode_mismatch"),
                    "expectedFeedbackMode": existing_feedback_mode,
                    "actualFeedbackMode": requested_feedback_mode,
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }
        try:
            xml = active_engine.get_xml()
        except Exception:  # noqa: BLE001 - MCP response must not expose engine internals.
            return _rejected("active_build_snapshot_failed")
        draft_marker = _read_draft_validation(bound_run)
        mechanism_binding = None
        if draft_required and draft_marker is not None:
            draft_context = dict(draft_marker.get("calculationContext") or {})
            draft_group = int(draft_context.get("groupIndex") or 0)
            draft_skill = str(draft_context.get("skillName") or "")
            if draft_group < 1 or not draft_skill:
                return {
                    **_rejected("generation_draft_validation_required"),
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }
            mechanism_binding = run_store.current_mechanism_binding(bound_run)
            if mechanism_binding is None:
                return {
                    **_rejected("generation_draft_validation_required"),
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }
            if (offense_skill_group_index is None) != (expected_skill_name is None):
                return {
                    **_rejected("selected_skill_conflict"),
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }
            if offense_skill_group_index is None:
                offense_skill_group_index = draft_group
                expected_skill_name = draft_skill
            elif (
                int(offense_skill_group_index) != draft_group
                or str(expected_skill_name or "").casefold() != draft_skill.casefold()
            ):
                return {
                    **_rejected("selected_skill_conflict"),
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }
            if not existing_receipts and draft_marker.get("buildStateHash") != build_state_hash(
                xml
            ):
                return {
                    **_rejected("generation_draft_state_changed"),
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }
            declared_signature = dict(draft_marker.get("mechanismSignature") or {})
            observed_signature = mechanism_signature.observe(active_engine, declared_signature)
            if (
                not observed_signature.get("ok")
                or not mechanism_signature.matches(
                    declared_signature,
                    dict(observed_signature.get("signature") or {}),
                )
                or observed_signature.get("signatureHash")
                != draft_marker.get("mechanismSignatureHash")
            ):
                return {
                    **_rejected("generation_mechanism_drift"),
                    "attemptConsumed": False,
                    "attemptCount": len(existing_receipts),
                }

        try:
            frozen_draft = (
                mechanism_evidence.read_validated_draft(bound_run, candidate_id=candidate_id)
                if draft_required
                else None
            )
        except run_store.RunStoreError as exc:
            return {**_rejected(exc.code), "attemptConsumed": False}
        if draft_required and frozen_draft is None:
            return {
                **_rejected("generation_draft_evidence_required"),
                "attemptConsumed": False,
                "attemptCount": len(existing_receipts),
                "detail": (
                    "Revalidate the same Draft in this run to rebuild its process-local design "
                    "evidence; the existing validation time and Research decisions stay fixed."
                ),
            }

        quality_checkpoint: dict[str, Any] = {}
        checkpoint_capable = all(
            callable(getattr(active_engine, name, None))
            for name in ("transaction_lock", "get_stats", "get_defenses", "get_build")
        )
        if checkpoint_capable:
            quality_checkpoint = validation_checkpoint.inspect_generation_checkpoint(
                active_engine,
                strict_mode=strict_mode,
                offense_skill_group_index=offense_skill_group_index,
                expected_skill_name=expected_skill_name,
            )
        if checkpoint_capable and quality_checkpoint.get("status") == "error":
            return {
                **_rejected("generation_final_checks_incomplete"),
                "finalCheckBlockers": ["checkpoint:inspection_error"],
                "attemptConsumed": False,
                "attemptCount": len(existing_receipts),
            }
        preflight_report = (
            dict(quality_checkpoint.get("preflight") or {})
            if quality_checkpoint.get("status") != "error"
            else {}
        )
        if not preflight_report:
            preflight_report = preflight.inspect_generation_snapshot(active_engine, xml)
        if not preflight_report.get("readyForJudge"):
            return {
                **_rejected("generation_preflight_failed"),
                "preflight": preflight.project_feedback(
                    preflight_report,
                    strict_mode=strict_mode,
                ),
                "feedbackMode": requested_feedback_mode,
                "subjectiveFeedbackSuppressed": not strict_mode,
                "attemptConsumed": False,
                "attemptCount": len(existing_receipts),
            }
        final_check_blockers = (
            _final_check_blockers(quality_checkpoint.get("createQualityChecklist") or {})
            if checkpoint_capable
            else []
        )
        if final_check_blockers:
            return {
                **_rejected("generation_final_checks_incomplete"),
                "finalCheckBlockers": final_check_blockers,
                "attemptConsumed": False,
                "attemptCount": len(existing_receipts),
            }

        try:
            runtime_skill_groups = active_engine.call("list_skill_groups")
        except Exception:  # noqa: BLE001 - XML root skills remain available to lightweight fakes.
            runtime_skill_groups = None
        parsed = _parse_build_snapshot(xml, runtime_skill_groups=runtime_skill_groups)
        if parsed.get("errorCode"):
            return _rejected(str(parsed["errorCode"]))
        offense_selection = _resolve_offense_selection(
            parsed,
            offense_skill_group_index=offense_skill_group_index,
            expected_skill_name=expected_skill_name,
        )
        if offense_selection.get("errorCode"):
            return {
                **_rejected(str(offense_selection["errorCode"])),
                "attemptConsumed": False,
                "expectedSkillName": expected_skill_name,
                "offenseSkillGroupIndex": offense_skill_group_index,
            }

        source_hash = evaluator.compute_source_hash(xml)
        semantic_state_hash = build_state_hash(xml)
        snapshot_id = f"generation:{bound_run.run_id}:{source_hash}"
        captured: dict[str, Any] = {}

        def judge_engine_factory() -> Any:
            engine = engine_factory()
            try:
                engine.load_build_xml(xml, name=snapshot_id)
                selector = getattr(engine, "select_judge_skill", None)
                if callable(selector):
                    selection = selector(
                        offense_skill_group_index=int(offense_selection["groupIndex"]),
                        expected_skill_name=str(offense_selection["skillName"]),
                    )
                    if selection.get("status") != "selected":
                        raise ValueError("selected_skill_conflict")
                    build = dict(engine.get_build())
                else:
                    # Lightweight test/fake engines may already provide an explicit selected
                    # skill in their sanitized build readback.  Production PobEngine always uses
                    # the typed selector above.
                    build = dict(engine.get_build())
                    selected = dict(build.get("judgeSelectedSkill") or {})
                    if int(selected.get("groupIndex") or 0) != int(
                        offense_selection["groupIndex"]
                    ) or str(selected.get("skillName") or "") != str(
                        offense_selection["skillName"]
                    ):
                        selected = {
                            "groupIndex": int(offense_selection["groupIndex"]),
                            "activeIndex": 1,
                            "skillName": str(offense_selection["skillName"]),
                            "sourceMetric": "unknown",
                        }
                    selection = {
                        "selectedSkill": selected,
                        "selectedSkillGroup": build.get("mainSkillGroup") or [],
                        "supplementalSkills": list(build.get("judgeSupplementalSkills") or []),
                        "calculationContext": {
                            "groupIndex": int(offense_selection["groupIndex"]),
                            "activeIndex": int(selected.get("activeIndex") or 1),
                            "skillName": str(offense_selection["skillName"]),
                            "sourceMetric": str(selected.get("sourceMetric") or "unknown"),
                        },
                    }
                build["judgeSelectedSkill"] = dict(selection.get("selectedSkill") or {})
                build["judgeSelectedSkillGroup"] = list(selection.get("selectedSkillGroup") or [])
                build["judgeSupplementalSkills"] = list(selection.get("supplementalSkills") or [])
                build["judgeCalculationContext"] = dict(selection.get("calculationContext") or {})
                captured["build"] = build
                engine._judge_build_override = build
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
            completeness_advisories=[
                str(item)
                for item in preflight_report.get("advisories") or []
                if strict_mode or str(item) == "spirit_opportunity_review_required"
            ],
            snapshot_id=snapshot_id,
            source_hash=source_hash,
            semantic_state_hash=semantic_state_hash,
            version=version,
        )
        judge_report = _build_judge_report(
            classified,
            parsed=parsed,
            build=captured.get("build") or {},
            snapshot_id=snapshot_id,
            source_hash=source_hash,
            version=version,
            strict_mode=strict_mode,
        )
        receipt = {
            "candidateId": candidate_id,
            **({"mechanismBinding": mechanism_binding} if mechanism_binding is not None else {}),
            "transientBuildState": state,
            "judgeAdvisoryReport": judge_report,
            "hardLegalityAudit": {
                **dict(preflight_report.get("hardLegality") or {}),
                "stateHash": semantic_state_hash,
                "validationRef": f"hard-legality:{semantic_state_hash[:24]}",
            },
            "deliveryStatus": str(quality_checkpoint.get("deliveryStatus") or "candidate"),
            "createQualityChecklist": dict(
                quality_checkpoint.get("createQualityChecklist") or _unavailable_quality_checklist()
            ),
            "qualityRepairPlan": list(quality_checkpoint.get("qualityRepairPlan") or []),
            "lifecycleVerification": dict(
                quality_checkpoint.get("lifecycleVerification")
                or {
                    "stage": "unknown",
                    "status": "unknown",
                    "pass": False,
                    "requiredChecks": [],
                    "advisoryChecks": [],
                    "failedChecks": [],
                    "unknownChecks": ["quality_checkpoint_unavailable"],
                }
            ),
        }
        expected_attempt_index = len(existing_receipts)
        try:
            historical_evidence = mechanism_evidence.bind_evaluation(
                frozen_draft,
                receipt,
                run_id=bound_run.run_id,
                attempt_index=expected_attempt_index,
            )
            if historical_evidence is not None:
                receipt["mechanismEvidence"] = historical_evidence
            evaluation_snapshots.remember(
                run_id=bound_run.run_id,
                attempt_index=expected_attempt_index,
                candidate_id=candidate_id,
                source_hash=source_hash,
                xml=xml,
                mechanism_evidence_hash=(
                    historical_evidence["bundleHash"] if historical_evidence is not None else None
                ),
            )
            attempt_index = run_store.write_trusted_evaluation(bound_run, receipt)
        except (run_store.RunStoreError, ValueError) as exc:
            evaluation_snapshots.forget(
                run_id=bound_run.run_id,
                attempt_index=expected_attempt_index,
            )
            if isinstance(exc, run_store.RunStoreError):
                return _rejected(exc.code)
            return _rejected("trusted_evaluation_snapshot_failed")
        if attempt_index != expected_attempt_index:
            evaluation_snapshots.forget(
                run_id=bound_run.run_id,
                attempt_index=expected_attempt_index,
            )
            if attempt_index is None:
                return _rejected("run_state_write_failed")
            return _rejected("trusted_attempt_index_mismatch")
        if attempt_index is None:
            evaluation_snapshots.forget(
                run_id=bound_run.run_id,
                attempt_index=expected_attempt_index,
            )
            return _rejected("run_state_write_failed")
        return {
            "status": judge_report["status"],
            "feedbackMode": requested_feedback_mode,
            "subjectiveFeedbackSuppressed": not strict_mode,
            "attemptIndex": attempt_index,
            "attemptConsumed": True,
            **{key: value for key, value in receipt.items() if key != "mechanismEvidence"},
            **(
                {"mechanismEvidenceHash": historical_evidence["bundleHash"]}
                if historical_evidence is not None
                else {}
            ),
            "trustedEvaluation": True,
            "trustedEvaluationScope": "snapshot_and_judge_only",
            "versionContextTrusted": False,
            "noRawMaterial": True,
        }
    finally:
        run_store.release_generation_lock(lock_path)


def _parse_build_snapshot(
    xml: str,
    *,
    runtime_skill_groups: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    runtime_by_index = {
        int(group.get("index") or 0): group
        for group in ((runtime_skill_groups or {}).get("groups") or [])
        if isinstance(group, dict)
    }
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
        runtime_group = runtime_by_index.get(index) or {}
        runtime_names = [
            str(active.get("name") or "").strip()
            for active in (runtime_group.get("activeSkills") or [])
            if isinstance(active, dict) and str(active.get("name") or "").strip()
        ]
        if runtime_names:
            active_names = list(dict.fromkeys(runtime_names))
        runtime_active = str(runtime_group.get("activeSkill") or "").strip()
        active_skill = runtime_active if runtime_active in active_names else active_names[0]
        supports = [str(gem.get("nameSpec") or "").strip() for gem in gems if _is_support_gem(gem)]
        supports = [name for name in supports if name]
        is_main = str(index) == main_group
        groups.append(
            {
                "groupIndex": index,
                "role": "pob_main_group" if is_main else "additional_skill_group",
                "activeSkill": active_skill,
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


def _unavailable_quality_checklist() -> dict[str, dict[str, Any]]:
    return {
        name: {"status": "failed", "reasons": ["quality_checkpoint_unavailable"]}
        for name in (
            "skillSupportAudit",
            "mechanismDependencies",
            "bootstrapItems",
            "gearAttainability",
            "charmLoadout",
            "jewelDecision",
            "itemSockets",
            "sustain",
        )
    }


def _final_check_blockers(checklist: dict[str, Any]) -> list[str]:
    """Compatibility entry point; checkpoint and Judge share the same gate."""
    return preflight.final_check_blockers(checklist)


def _draft_validation_matches(
    bound_run: run_store.BoundRun,
    *,
    candidate_id: str,
    research_memory_ref: str,
    memory_mode: str = "memory_assisted",
) -> bool:
    payload = _read_draft_validation(bound_run)
    if payload is None:
        return False
    family_binding = _family_discovery_binding(bound_run)
    family_ready = memory_mode == "no_memory" or family_binding is not None
    premise_ready = (
        payload.get("researchPremiseAuditReady") is False
        if memory_mode == "no_memory"
        else payload.get("researchPremiseAuditReady") is True
    )
    try:
        blueprint = json.loads(
            (bound_run.run_dir / "mechanism-blueprint-validation.json").read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        blueprint = None
    return bool(
        isinstance(payload, dict)
        and payload.get("schemaVersion") in {2, 3}
        and payload.get("candidateId") == candidate_id
        and payload.get("researchMemoryRef") == research_memory_ref
        and premise_ready
        and family_ready
        and (
            memory_mode == "no_memory"
            or payload.get("familyDiscoveryRef") == family_binding.get("familyDiscoveryRef")
        )
        and (
            memory_mode == "no_memory"
            or payload.get("selectedFamilyKey") == family_binding.get("selectedFamilyKey")
        )
        and isinstance(blueprint, dict)
        and isinstance(blueprint.get("evidenceAudit"), dict)
        and isinstance(payload.get("evidenceAuditHash"), str)
        and payload.get("evidenceAuditHash") == blueprint.get("evidenceAuditHash")
        and isinstance(payload.get("designToolsHash"), str)
        and isinstance(payload.get("designEvidenceUses"), dict)
        and isinstance(payload.get("designEvidenceUsesHash"), str)
        and payload.get("mechanismBlueprintRef") == blueprint.get("blueprintRef")
        and payload.get("mechanismBlueprintHash") == blueprint.get("blueprintHash")
        and isinstance(payload.get("mechanismSignatureHash"), str)
        and isinstance(payload.get("mechanismSignature"), dict)
        and isinstance(payload.get("buildStateHash"), str)
        and payload.get("noRawMaterial") is True
    )


def _read_draft_validation(bound_run: run_store.BoundRun) -> dict[str, Any] | None:
    try:
        payload = json.loads(
            (bound_run.run_dir / "draft-validation.json").read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _family_discovery_binding(bound_run: run_store.BoundRun) -> dict[str, Any] | None:
    try:
        payload = json.loads(
            (bound_run.run_dir / "family-discovery.json").read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != 1
        or payload.get("status") not in {"selected", "no_family"}
        or not isinstance(payload.get("familyDiscoveryRef"), str)
        or payload.get("noRawMaterial") is not True
    ):
        return None
    return payload


def _resolve_offense_selection(
    parsed: dict[str, Any],
    *,
    offense_skill_group_index: int | None,
    expected_skill_name: str | None,
) -> dict[str, Any]:
    groups = [dict(group) for group in parsed.get("testedSkillGroups") or []]
    if not groups:
        return {"errorCode": "selected_skill_conflict"}
    expected = str(expected_skill_name or "").strip()
    if expected.casefold().startswith(("load ", "reload ")):
        return {"errorCode": "selected_skill_conflict"}
    selected: dict[str, Any] | None = None
    if offense_skill_group_index is not None:
        selected = next(
            (
                group
                for group in groups
                if int(group.get("groupIndex") or 0) == int(offense_skill_group_index)
            ),
            None,
        )
    elif expected:
        matches = [group for group in groups if expected in (group.get("activeSkills") or [])]
        selected = matches[0] if len(matches) == 1 else None
    else:
        selected = next(
            (group for group in groups if group.get("role") == "pob_main_group"),
            None,
        )
    if selected is None:
        return {"errorCode": "selected_skill_conflict"}
    selected_name = expected or str(selected.get("activeSkill") or "")
    if selected_name not in (selected.get("activeSkills") or []):
        return {"errorCode": "selected_skill_conflict"}
    return {
        "groupIndex": int(selected["groupIndex"]),
        "skillName": selected_name,
    }


def _build_state_ref(
    parsed: dict[str, Any],
    build: dict[str, Any],
    *,
    completeness_advisories: list[str],
    snapshot_id: str,
    source_hash: str,
    semantic_state_hash: str,
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
    }
    for key in (
        "spiritAvailable",
        "spiritReservedCapped",
        "spiritUnreserved",
        "spiritRequested",
        "spiritOverBy",
        "spiritUsed",
        "activeWeaponSet",
    ):
        if build.get(key) is not None:
            summary[key] = str(build[key])
    state = models.TransientBuildStateRef(
        status="available",
        snapshot_id=snapshot_id,
        source_hash=source_hash,
        semantic_state_hash=semantic_state_hash,
        safe_summary=summary,
        tested_skill_groups=parsed["testedSkillGroups"],
        completeness_advisories=list(dict.fromkeys(completeness_advisories)),
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
    strict_mode: bool,
) -> dict[str, Any]:
    error_kind = result.get("errorKind")
    if error_kind:
        report = models.JudgeAdvisoryReport(
            report_id=f"judge:{snapshot_id}",
            status="error",
            feedback_mode="strict" if strict_mode else "hard_only",
            subjective_feedback_suppressed=not strict_mode,
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
        feedback_mode="strict" if strict_mode else "hard_only",
        subjective_feedback_suppressed=not strict_mode,
        hard_failures=[str(item) for item in result.get("hardFailures") or []],
        playability_failures=(
            [str(item) for item in result.get("playabilityFailures") or []] if strict_mode else []
        ),
        quality_warnings=(
            [str(item) for item in result.get("qualityWarnings") or []] if strict_mode else []
        ),
        caveats=[str(item) for item in result.get("caveats") or []] if strict_mode else [],
        aggregate_score=max(0.0, min(1.0, aggregate)) if strict_mode else None,
        reward_strength=reward_strength if strict_mode else "unknown",
        reward_limit_reasons=(
            [str(item) for item in result.get("rewardLimitReasons") or []] if strict_mode else []
        ),
        evaluated_snapshot_id=snapshot_id,
        evaluated_source_hash=source_hash,
        passed=bool(result.get("pass")),
        quality_band=str(result.get("qualityBand") or "unknown") if strict_mode else None,
        score_vector=_safe_score_vector(result.get("scoreVector") or {}) if strict_mode else None,
        offense_evidence=(
            _safe_offense_evidence((result.get("scoreBreakdown") or {}).get("offense") or {})
            if strict_mode
            else None
        ),
        modelability_status=modelability_status if strict_mode else None,
        score_applicability=score_applicability if strict_mode else "unknown",
        level_band=str(result.get("levelBand") or "unknown") if strict_mode else None,
        evaluator_version=str(
            (result.get("reproducibility") or {}).get("evaluatorVersion") or "unknown"
        ),
        final_classification=(
            str(result.get("finalClassification") or "unknown") if strict_mode else None
        ),
        selected_skill=_selected_skill_diagnostic(build),
        calculation_context=(dict(build.get("judgeCalculationContext") or {}) or None),
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
                "singleActiveSkillValid": rules.is_valid_active_skill_group(active_skills),
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
                "singleActiveSkillValid": rules.is_valid_active_skill_group(readback_active),
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
    contributors_by_attribute: dict[str, list[dict[str, Any]]] = {}
    for source in build.get("attributeRequirementSources") or []:
        if not isinstance(source, dict):
            continue
        source_name = str(source.get("source") or "")
        kind = str(source.get("kind") or "item")
        if not source_name:
            continue
        for attribute, keys in aliases.items():
            required = _first_number(source, keys)
            if required <= 0:
                continue
            contributors_by_attribute.setdefault(attribute, []).append(
                {"source": source_name, "kind": kind, "required": required}
            )
    output: list[dict[str, Any]] = []
    for attribute, keys in aliases.items():
        current = _first_number(attributes, keys)
        required = _first_number(requirements, keys)
        if required > current:
            entry: dict[str, Any] = {
                "attribute": attribute,
                "current": current,
                "required": required,
                "shortfall": required - current,
            }
            contributors = contributors_by_attribute.get(attribute)
            if contributors:
                entry["contributors"] = sorted(
                    contributors,
                    key=lambda item: item["required"],
                    reverse=True,
                )[:8]
            output.append(entry)
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
    return run_store.acquire_generation_lock(path, timeout_seconds=timeout_seconds)


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
