from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.learning import comparison, memory, models, service


FAMILY_RECORDS = [
    {
        "record_kind": "skill_package",
        "ascendancy_key": "ascendancy:invoker",
        "component_mentions": [
            {"role": "primary_damage", "component_key": "skill:tempest_flurry"},
            {"role": "boss_skill", "component_key": "skill:charged_staff"},
        ],
        "typed_payload": {"familyCoreSkillKeys": ["skill:charged_staff"]},
    }
]


def _xml(level: int = 80) -> str:
    return (
        '<PathOfBuilding><Build level="%d" className="Monk" ascendClassName="Invoker" />'
        '<Skills><Skill enabled="true"><Gem nameSpec="Tempest Flurry" /></Skill></Skills>'
        "</PathOfBuilding>" % level
    )


def _version() -> dict[str, object]:
    return {
        "gamePatch": "0.5.0",
        "passiveTreeVersion": "0_5",
        "pobVersionOrCommit": "0.22.0",
    }


def _evidence(side: str, case_id: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "evidenceRef": f"evidence:{side}:{case_id}",
        "side": side,
        "summary": f"{side} build safe comparison summary",
        "dimensionNotes": {"damage_loop_delivery": "short safe observation"},
        "configurationCaveats": ["conditional uptime requires review"],
        "legalityStatus": "passed",
        "modelabilityStatus": "partial",
        "safeEvidenceRefs": [f"safe:{side}:{case_id}"],
        "judgeAdvisory": {
            "advisoryOnly": True,
            "available": True,
            "scoreApplicability": "limited",
            "modelability": "partial",
            "safeSummary": "numeric evidence is incomplete",
            "metrics": {"aggregate": 50.0 if side == "reference" else 80.0},
        },
        "noRawMaterial": True,
    }


def _memory_use(query: dict[str, object]) -> dict[str, object]:
    recalled = list(query["recalledLessonIds"])
    return {
        "queryRef": query["queryRef"],
        "recalledLessonIds": recalled,
        "decisions": [
            {
                "lessonId": lesson_id,
                "decision": "caveated",
                "application": "Reviewed for this blind Create; no unsafe reference context used.",
                "harmfulOrIncorrect": False,
                "observation": "Kept within the recalled scope.",
            }
            for lesson_id in recalled
        ],
    }


def _query_create_memory(
    campaign_id: str, case_id: str, claim: dict[str, object], operation_id: str
) -> dict[str, object]:
    result = service.query_memory_for_create(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=str(claim["claimId"]),
        thread_id="thread-create",
        expected_revision=int(claim["revision"]),
        operation_id=operation_id,
    )
    assert result["status"] == "ok"
    return result


def _report(case_id: str, *, verdict: str = "generated_stronger") -> dict[str, object]:
    dimensions = []
    for name in models.COMPARISON_DIMENSIONS:
        dimensions.append(
            {
                "dimension": name,
                "verdict": "tie",
                "rationale": "independent comparator reviewed both safe evidence packets",
                "generatedEvidenceRefs": [f"safe:generated:{case_id}"],
                "referenceEvidenceRefs": [f"safe:reference:{case_id}"],
                "criticalGap": False,
            }
        )
    return {
        "schemaVersion": 1,
        "comparisonId": f"cmp:{case_id}",
        "caseId": case_id,
        "familyMatch": True,
        "levelMatch": True,
        "generatedLegal": True,
        "referenceLegal": True,
        "dimensions": dimensions,
        "overallVerdict": verdict,
        "gaps": [],
        # Reference has the higher Judge aggregate on purpose. The explicit Comparator verdict
        # remains authoritative and proves the service does not auto-select from Judge numbers.
        "judgeAdvisory": {
            "generated": _evidence("generated", case_id)["judgeAdvisory"],
            "reference": {
                **_evidence("reference", case_id)["judgeAdvisory"],
                "metrics": {"aggregate": 99.0},
            },
        },
        "comparatorSummary": "Generated is stronger for non-numeric delivery reasons.",
        "noAutomaticWinner": True,
        "noRewardWrite": True,
        "noRawMaterial": True,
    }


@pytest.fixture
def isolated_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("POE2_MCP_DATA", str(tmp_path / "user-data"))
    monkeypatch.setattr(
        service,
        "_artifact_metadata",
        lambda artifact_id: {"level": 80, "sourceHash": f"hash:{artifact_id}"},
    )
    return tmp_path / "user-data"


def _start_and_intake(source_mode: str = "direct") -> tuple[str, str, int]:
    started = service.start_campaign(operation_id=f"start-{source_mode}")
    intaked = service.intake_case(
        campaign_id=started["campaignId"],
        expected_revision=started["revision"],
        operation_id=f"intake-{source_mode}",
        source=_xml(),
        source_mode=source_mode,
        source_ref="collector-ref" if source_mode == "automatic" else "",
    )
    assert intaked["status"] == "case_intaked"
    return started["campaignId"], intaked["caseId"], intaked["revision"]


def _profile_case(campaign_id: str, case_id: str, revision: int) -> tuple[str, int]:
    claimed = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="profile",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=revision,
        operation_id="claim-profile",
    )
    profiled = service.submit_profile(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claimed["claimId"],
        thread_id="thread-reference",
        expected_revision=claimed["revision"],
        operation_id="submit-profile",
        identity_records=FAMILY_RECORDS,
        target_level=80,
        version_context=_version(),
        reference_evidence=_evidence("reference", case_id),
    )
    assert profiled["status"] == "profile_accepted"
    return profiled["familyTarget"]["buildFamilyKey"], profiled["revision"]


def test_family_target_reuses_research_identity_and_ambiguity_fails_closed(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    family_key, _ = _profile_case(campaign_id, case_id, revision)
    assert family_key.startswith("bf-")

    campaign_id, case_id, revision = _start_and_intake("automatic")
    claimed = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="profile",
        task_id="task-ref-2",
        thread_id="thread-ref-2",
        expected_revision=revision,
        operation_id="claim-profile-2",
    )
    ambiguous = FAMILY_RECORDS + [
        {
            "record_kind": "skill_package",
            "ascendancy_key": "ascendancy:invoker",
            "component_mentions": [{"role": "primary_damage", "component_key": "skill:ice_strike"}],
        }
    ]
    result = service.submit_profile(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claimed["claimId"],
        thread_id="thread-ref-2",
        expected_revision=claimed["revision"],
        operation_id="ambiguous-profile",
        identity_records=ambiguous,
        target_level=80,
        version_context=_version(),
        reference_evidence=_evidence("reference", case_id),
    )
    assert result["status"] == "case_failed"
    assert result["errorCode"] == "ambiguous_build_family"


def test_blind_create_packet_has_no_reference_build_details(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    _, revision = _profile_case(campaign_id, case_id, revision)
    claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-create",
        thread_id="thread-create",
        expected_revision=revision,
        operation_id="claim-create",
    )
    packet = service.get_blind_create_packet(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim["claimId"],
        thread_id="thread-create",
    )["blindCreatePacket"]
    serialized = json.dumps(packet).casefold()
    assert set(packet) == {
        "schemaVersion",
        "campaignId",
        "caseId",
        "familyTarget",
        "defaultGoal",
        "referenceBlind",
        "researchAllowed",
        "learningMemoryAllowed",
        "createInvocationLimit",
        "phase5InternalRetryLimit",
    }
    for forbidden in (
        "referenceevidence",
        "gear",
        "passivenode",
        "skillgroups",
        "mechanism",
        "judge",
        "pathofbuilding",
    ):
        assert forbidden not in serialized

    with pytest.raises(ValidationError):
        models.BlindCreatePacket.model_validate({**packet, "referenceGear": ["secret"]})


@pytest.mark.parametrize("source_mode", ["direct", "automatic"])
def test_intake_modes_keep_raw_material_out_of_durable_campaign(
    isolated_data: Path, source_mode: str
):
    campaign_id, _, _ = _start_and_intake(source_mode)
    campaign_text = next(
        (isolated_data / "comparative-learning" / "campaigns").glob("*.json")
    ).read_text(encoding="utf-8")
    assert "PathOfBuilding" not in campaign_text
    assert "Tempest Flurry" not in campaign_text
    assert _xml() not in campaign_text
    quarantine = isolated_data / "comparative-learning" / "quarantine"
    assert "PathOfBuilding" in next(quarantine.glob("*/source.json")).read_text(encoding="utf-8")
    assert service.campaign_status(campaign_id=campaign_id)["containsRawMaterial"] is False


def test_source_file_intake_e2e(isolated_data: Path, tmp_path: Path):
    source_path = tmp_path / "reference.xml"
    source_path.write_text(_xml(), encoding="utf-8")
    started = service.start_campaign(operation_id="start-file")
    intaked = service.intake_case(
        campaign_id=started["campaignId"],
        expected_revision=0,
        operation_id="intake-file",
        source=str(source_path),
        source_mode="source_file",
    )
    assert intaked["status"] == "case_intaked"
    assert str(source_path) not in json.dumps(intaked)


def test_task_binding_cas_idempotency_pause_resume_and_retry(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="profile",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=revision,
        operation_id="claim-once",
    )
    duplicate = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="profile",
        task_id="different",
        thread_id="different",
        expected_revision=revision,
        operation_id="claim-once",
    )
    assert duplicate["status"] == "idempotent"
    assert duplicate["claimId"] == claim["claimId"]
    conflict = service.pause_campaign(
        campaign_id=campaign_id,
        expected_revision=revision,
        operation_id="stale-pause",
        reason="check CAS",
    )
    assert conflict["errorCode"] == "campaign_revision_conflict"

    failed = service.fail_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim["claimId"],
        thread_id="thread-reference",
        expected_revision=claim["revision"],
        operation_id="fail-profile",
        error_code="transient_tool_failure",
    )
    retried = service.retry_failed_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        expected_revision=failed["revision"],
        operation_id="retry-profile",
    )
    assert retried["phase"] == "profile"
    paused = service.pause_campaign(
        campaign_id=campaign_id,
        expected_revision=retried["revision"],
        operation_id="pause",
        reason="user requested boundary pause",
    )
    resumed = service.resume_campaign(
        campaign_id=campaign_id,
        expected_revision=paused["revision"],
        operation_id="resume",
    )
    assert resumed["status"] == "resumed"
    assert resumed["phase"] == "profile_pending"


def test_create_task_is_independent_and_result_family_level_are_exact(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    _, revision = _profile_case(campaign_id, case_id, revision)
    same_task = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=revision,
        operation_id="bad-create-claim",
    )
    assert same_task["errorCode"] == "create_task_must_be_independent"
    claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-create",
        thread_id="thread-create",
        expected_revision=revision,
        operation_id="good-create-claim",
    )
    queried = _query_create_memory(campaign_id, case_id, claim, "query-create-memory")
    mismatched_use = _memory_use(queried)
    mismatched_use["queryRef"] = "learning-query:00000000000000000000"
    mismatch = service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim["claimId"],
        thread_id="thread-create",
        expected_revision=queried["revision"],
        operation_id="submit-create-with-fake-receipt",
        identity_records=FAMILY_RECORDS,
        target_level=80,
        artifact_id="final-build:generated-test",
        generated_evidence=_evidence("generated", case_id),
        learning_memory_use=mismatched_use,
    )
    assert mismatch["errorCode"] == "learning_memory_use_receipt_mismatch"
    result = service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim["claimId"],
        thread_id="thread-create",
        expected_revision=queried["revision"],
        operation_id="submit-create",
        identity_records=FAMILY_RECORDS,
        target_level=80,
        artifact_id="final-build:generated-test",
        generated_evidence=_evidence("generated", case_id),
        learning_memory_use=_memory_use(queried),
    )
    assert result["status"] == "create_accepted"
    assert result["familyMatch"] and result["levelMatch"]


def test_consumed_create_mismatch_is_terminal_and_releases_serial_slot(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    _, revision = _profile_case(campaign_id, case_id, revision)
    claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-create",
        thread_id="thread-create",
        expected_revision=revision,
        operation_id="terminal-claim-create",
    )
    queried = _query_create_memory(campaign_id, case_id, claim, "terminal-query-memory")
    failed = service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim["claimId"],
        thread_id="thread-create",
        expected_revision=queried["revision"],
        operation_id="terminal-submit-create",
        identity_records=FAMILY_RECORDS,
        target_level=79,
        artifact_id="final-build:mismatched-test",
        generated_evidence=_evidence("generated", case_id),
        learning_memory_use=_memory_use(queried),
    )
    assert failed["terminalFailure"] is True
    assert failed["retryAllowed"] is False
    status = service.campaign_status(campaign_id=campaign_id)
    assert status["activeCaseId"] is None
    next_case = service.intake_case(
        campaign_id=campaign_id,
        expected_revision=failed["revision"],
        operation_id="intake-after-terminal-failure",
        source=_xml().replace("Tempest Flurry", "Ice Strike"),
        source_mode="direct",
    )
    assert next_case["status"] == "case_intaked"


def test_duplicate_reference_source_is_rejected_before_quarantine_write(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    _, revision = _profile_case(campaign_id, case_id, revision)
    claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-create",
        thread_id="thread-create",
        expected_revision=revision,
        operation_id="duplicate-claim-create",
    )
    queried = _query_create_memory(campaign_id, case_id, claim, "duplicate-query-memory")
    failed = service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=claim["claimId"],
        thread_id="thread-create",
        expected_revision=queried["revision"],
        operation_id="duplicate-terminal-create",
        identity_records=FAMILY_RECORDS,
        target_level=79,
        artifact_id="final-build:duplicate-terminal",
        generated_evidence=_evidence("generated", case_id),
        learning_memory_use=_memory_use(queried),
    )
    quarantine = isolated_data / "comparative-learning" / "quarantine"
    before = sorted(path.name for path in quarantine.iterdir())

    duplicate = service.intake_case(
        campaign_id=campaign_id,
        expected_revision=failed["revision"],
        operation_id="reject-duplicate-source",
        source=_xml(),
        source_mode="automatic",
        source_ref="different-collector-row",
    )

    assert duplicate["status"] == "rejected"
    assert duplicate["errorCode"] == "duplicate_reference_source"
    assert sorted(path.name for path in quarantine.iterdir()) == before
    status = service.campaign_status(campaign_id=campaign_id)
    assert status["activeCaseId"] is None
    assert len(status["cases"]) == 1


def test_legacy_unstarted_duplicate_intake_can_be_discarded_with_audit(
    isolated_data: Path, monkeypatch: pytest.MonkeyPatch
):
    campaign_id, original_case_id, revision = _start_and_intake()
    campaign_path = service.campaigns_dir() / f"{campaign_id}.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    campaign["activeCaseId"] = None
    campaign["cases"][0]["phase"] = "completed"
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
    original_source = campaign["cases"][0]["source"]
    duplicate_case_id = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr(
        service.case_store,
        "intake_reference_source",
        lambda **_kwargs: {
            "status": "intaked",
            "case": {**original_source, "caseId": duplicate_case_id},
        },
    )
    intaked = service.intake_case(
        campaign_id=campaign_id,
        expected_revision=revision,
        operation_id="legacy-duplicate-intake",
        source=_xml(),
        source_mode="automatic",
    )
    assert intaked["status"] == "case_intaked"

    repaired = service.discard_duplicate_pending_case(
        campaign_id=campaign_id,
        case_id=duplicate_case_id,
        expected_revision=intaked["revision"],
        operation_id="discard-legacy-duplicate",
    )

    assert repaired["status"] == "duplicate_intake_discarded"
    status = service.campaign_status(campaign_id=campaign_id)
    assert status["activeCaseId"] is None
    assert [item["caseId"] for item in status["cases"]] == [original_case_id]
    stored = json.loads(campaign_path.read_text(encoding="utf-8"))
    assert stored["discardedIntakes"][0]["caseId"] == duplicate_case_id
    assert stored["discardedIntakes"][0]["reason"] == "duplicate_reference_source"


@pytest.mark.parametrize("source_mode", ["direct", "automatic"])
def test_explicit_and_automatic_source_complete_one_case_e2e(isolated_data: Path, source_mode: str):
    campaign_id, case_id, revision = _start_and_intake(source_mode)
    _, revision = _profile_case(campaign_id, case_id, revision)
    create_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-create",
        thread_id="thread-create",
        expected_revision=revision,
        operation_id="e2e-claim-create",
    )
    queried = _query_create_memory(campaign_id, case_id, create_claim, "e2e-query-memory")
    created = service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=create_claim["claimId"],
        thread_id="thread-create",
        expected_revision=queried["revision"],
        operation_id="e2e-submit-create",
        identity_records=FAMILY_RECORDS,
        target_level=80,
        artifact_id=f"final-build:{source_mode}-e2e",
        generated_evidence=_evidence("generated", case_id),
        learning_memory_use=_memory_use(queried),
    )
    compare_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="compare",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=created["revision"],
        operation_id="e2e-claim-compare",
    )
    compared = service.submit_comparison(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=compare_claim["claimId"],
        thread_id="thread-reference",
        expected_revision=compare_claim["revision"],
        operation_id="e2e-submit-compare",
        report=_report(case_id),
    )
    learn_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="learn",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=compared["revision"],
        operation_id="e2e-claim-learn",
    )
    learned = service.complete_learning(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=learn_claim["claimId"],
        thread_id="thread-reference",
        expected_revision=learn_claim["revision"],
        operation_id="e2e-complete-learn",
        mutations=["none"],
    )
    assert learned["nextPhase"] == "completed"
    status = service.campaign_status(campaign_id=campaign_id)
    assert status["cases"][0]["phase"] == "completed"
    assert status["trend"]["status"] == "insufficient_cases"


def test_judge_is_advisory_and_does_not_choose_comparator_winner():
    case_id = "case-safe"
    validated = comparison.validate_report(_report(case_id), expected_case_id=case_id)
    assert validated["status"] == "accepted"
    assert validated["report"]["overallVerdict"] == "generated_stronger"
    assert validated["report"]["judgeAdvisory"]["reference"]["metrics"]["aggregate"] == 99.0
    assert validated["winnerSource"] == "external_comparator"
    assert validated["judgeAdvisoryOnly"] is True


def _lesson_payload(case_id: str = "case-1") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "lesson": "Before committing damage scaling, verify that the delivery loop remains practical.",
        "scope": "global",
        "familyKey": None,
        "levelMin": None,
        "levelMax": None,
        "dimension": "damage_loop_delivery",
        "conditions": ["multi-step delivery"],
        "exclusions": ["instant single-step delivery"],
        "recommendedCreateBehavior": "Audit setup time and failure states before choosing the final scaler.",
        "verificationTasks": ["review delivery assumptions"],
        "comparisonRefs": [f"comparison:{case_id}"],
        "sourceRefs": [f"source:{case_id}"],
        "candidateRefs": [f"candidate:{case_id}"],
        "versionContext": _version(),
        "reviewedCaseId": case_id,
        "dbFit": False,
        "citedCorrectionIds": [],
        "newEvidenceRefs": [],
    }


def test_db_fit_is_rejected_and_memory_is_immediately_recalled(isolated_data: Path):
    db_fit = _lesson_payload()
    db_fit["dbFit"] = True
    assert memory.propose_lesson(db_fit)["errorCode"] == "research_schema_fit_required"

    accepted = memory.propose_lesson(_lesson_payload())
    assert accepted["status"] == "accepted"
    recalled = memory.query_memory(
        family_key="bf-0123456789abcdef0123",
        target_level=80,
    )
    assert recalled["retrievalOutcome"] == "matched"
    assert recalled["lessons"][0]["lessonId"] == accepted["lesson"]["lessonId"]


def test_memory_correction_history_and_anti_oscillation(isolated_data: Path):
    accepted = memory.propose_lesson(_lesson_payload())
    lesson_id = accepted["lesson"]["lessonId"]
    corrected = memory.append_correction(
        {
            "schemaVersion": 1,
            "targetLessonId": lesson_id,
            "action": "revise",
            "reason": "The first wording was too broad for one-step delivery builds.",
            "triggerCaseId": "case-2",
            "safeEvidenceRefs": ["comparison:case-2"],
            "afterLesson": "For multi-step delivery, verify setup time before committing damage scaling.",
            "afterConditions": ["multi-step delivery"],
            "afterExclusions": ["one-step delivery"],
            "replacementLessonId": None,
        }
    )
    assert corrected["status"] == "corrected"
    duplicate = memory.propose_lesson(_lesson_payload("case-3"))
    assert duplicate["errorCode"] == "corrected_lesson_requires_new_evidence"
    revised_duplicate = _lesson_payload("case-3")
    revised_duplicate["lesson"] = (
        "For multi-step delivery, verify setup time before committing damage scaling."
    )
    assert (
        memory.propose_lesson(revised_duplicate)["errorCode"]
        == "corrected_lesson_requires_new_evidence"
    )
    recalled = memory.query_memory(
        family_key="bf-0123456789abcdef0123",
        target_level=80,
    )
    assert recalled["lessons"][0]["lesson"].startswith("For multi-step delivery")
    assert (
        recalled["correctionsAndDoNotRepeat"][0]["correctionId"]
        == corrected["correction"]["correctionId"]
    )

    stale = memory.query_memory(
        family_key="bf-0123456789abcdef0123",
        target_level=80,
        version_context={
            "gamePatch": "0.6.0",
            "passiveTreeVersion": "0_6",
            "pobVersionOrCommit": "0.23.0",
        },
    )
    assert stale["retrievalOutcome"] == "no_matching_memory"
    assert stale["contextualStaleLessons"][0]["effectiveStatus"] == "stale"


def test_memory_revision_can_clear_stale_conditions_and_exclusions(isolated_data: Path):
    accepted = memory.propose_lesson(_lesson_payload())
    lesson_id = accepted["lesson"]["lessonId"]
    corrected = memory.append_correction(
        {
            "schemaVersion": 1,
            "targetLessonId": lesson_id,
            "action": "revise",
            "reason": "Later evidence shows the guidance is useful without the original filters.",
            "triggerCaseId": "case-clear-filters",
            "safeEvidenceRefs": ["comparison:case-clear-filters"],
            "afterLesson": "Verify delivery setup time before committing damage scaling.",
            "afterConditions": [],
            "afterExclusions": [],
            "replacementLessonId": None,
        }
    )
    assert corrected["status"] == "corrected"

    recalled = memory.query_memory(
        family_key="bf-0123456789abcdef0123",
        target_level=80,
    )
    assert recalled["lessons"][0]["conditions"] == []
    assert recalled["lessons"][0]["exclusions"] == []


def test_mutation_requires_conditional_rereview_in_same_comparator_task(isolated_data: Path):
    campaign_id, case_id, revision = _start_and_intake()
    _, revision = _profile_case(campaign_id, case_id, revision)
    create_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="create",
        task_id="task-create",
        thread_id="thread-create",
        expected_revision=revision,
        operation_id="rr-claim-create",
    )
    queried = _query_create_memory(campaign_id, case_id, create_claim, "rr-query-memory")
    created = service.submit_create_result(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=create_claim["claimId"],
        thread_id="thread-create",
        expected_revision=queried["revision"],
        operation_id="rr-submit-create",
        identity_records=FAMILY_RECORDS,
        target_level=80,
        artifact_id="final-build:rereview-test",
        generated_evidence=_evidence("generated", case_id),
        learning_memory_use=_memory_use(queried),
    )
    compare_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="compare",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=created["revision"],
        operation_id="rr-claim-compare",
    )
    compared = service.submit_comparison(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=compare_claim["claimId"],
        thread_id="thread-reference",
        expected_revision=compare_claim["revision"],
        operation_id="rr-submit-compare",
        report=_report(case_id),
    )
    learn_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="learn",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=compared["revision"],
        operation_id="rr-claim-learn",
    )
    proposal = _lesson_payload(case_id)
    proposal["comparisonRefs"] = [compared["comparisonRef"]]
    lesson = service.propose_memory_lesson(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=learn_claim["claimId"],
        thread_id="thread-reference",
        proposal=proposal,
    )
    assert lesson["status"] == "accepted"
    invalid = service.complete_learning(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=learn_claim["claimId"],
        thread_id="thread-reference",
        expected_revision=learn_claim["revision"],
        operation_id="rr-complete-with-fake-memory",
        mutations=["memory"],
        memory_lesson_ids=["lesson:not-present"],
    )
    assert invalid["errorCode"] == "learning_memory_refs_not_found"
    learned = service.complete_learning(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=learn_claim["claimId"],
        thread_id="thread-reference",
        expected_revision=learn_claim["revision"],
        operation_id="rr-complete-learn",
        mutations=["memory"],
        memory_lesson_ids=[lesson["lesson"]["lessonId"]],
    )
    assert learned["nextPhase"] == "rereview"
    rereview_claim = service.claim_phase(
        campaign_id=campaign_id,
        case_id=case_id,
        phase="rereview",
        task_id="task-reference",
        thread_id="thread-reference",
        expected_revision=learned["revision"],
        operation_id="rr-claim-rereview",
    )
    rereviewed = service.submit_rereview(
        campaign_id=campaign_id,
        case_id=case_id,
        claim_id=rereview_claim["claimId"],
        thread_id="thread-reference",
        expected_revision=rereview_claim["revision"],
        operation_id="rr-submit-rereview",
        accepted=True,
        summary="The lesson is scoped and safe for later Create tasks.",
        safe_evidence_refs=["comparison:rereview-safe"],
    )
    assert rereviewed["status"] == "case_completed"


def test_ten_case_trend_is_directional_only():
    first = [
        {
            "notWeaker": False,
            "referenceAdvantageDimensions": 6,
            "criticalGapCount": 2,
            "generatedLegal": True,
            "familyMatch": True,
            "comparisonCompleted": True,
        }
        for _ in range(3)
    ]
    middle = [
        {
            "notWeaker": True,
            "referenceAdvantageDimensions": 3,
            "criticalGapCount": 1,
            "generatedLegal": True,
            "familyMatch": True,
            "comparisonCompleted": True,
        }
        for _ in range(4)
    ]
    last = [
        {
            "notWeaker": True,
            "referenceAdvantageDimensions": 2,
            "criticalGapCount": 1,
            "generatedLegal": True,
            "familyMatch": True,
            "comparisonCompleted": True,
        }
        for _ in range(3)
    ]
    result = comparison.campaign_trend(first + middle + last)
    assert result["claim"] == "initial_progress_signal"
    assert result["causalProof"] is False
    assert result["middleCaseCount"] == 4

    incomplete = first + middle + [dict(item) for item in last]
    incomplete[-1]["comparisonCompleted"] = False
    unproven = comparison.campaign_trend(incomplete)
    assert unproven["claim"] == "function_complete_learning_unproven"
    assert unproven["conditions"]["comparisonCoverageComplete"] is False
