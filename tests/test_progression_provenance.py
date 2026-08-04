from server.generation import progression_models, progression_provenance


IDENTITY = progression_models.StageFamilyIdentity(
    ascendancy_key="ascendancy:target-monk",
    primary_skill_key="skill:target-attack",
    secondary_skill_keys=[],
    ascendancy_name="Target Ascendancy",
    primary_skill_name="Target Attack",
)


def _receipt(
    *,
    ascendancy_key: str = "ascendancy:target-monk",
    primary_skill_key: str = "skill:target-attack",
    primary_skill_keys: list[str] | None = None,
) -> dict[str, object]:
    return {
        "dedupeQueryRef": "dq-0000000000000001",
        "request": {
            "ascendancyKey": ascendancy_key,
            "primarySkillKey": primary_skill_key,
            **({"primarySkillKeys": primary_skill_keys} if primary_skill_keys is not None else {}),
        },
        "result": {
            "buildFamilies": [
                {
                    "buildFamilyKey": "family:target",
                    "ascendancyKey": "ascendancy:target-monk",
                    "primarySkillKey": "skill:target-attack",
                    "secondarySkillKeys": [],
                }
            ],
            "deepRecordIds": ["record:target"],
            "patternIds": ["pattern:target"],
            "semanticEdgeIds": ["edge:target"],
            "memoryItemIds": ["fragment:target"],
        },
        "lastSeenAt": "2026-07-26T12:00:00+00:00",
    }


def _usage() -> dict[str, object]:
    return {
        "retrievalOutcome": "matched",
        "dedupeQueryRefs": ["dq-0000000000000001"],
        "componentKeys": ["ascendancy:target-monk", "skill:target-attack"],
        "buildFamilyKeys": ["family:target"],
        "deepRecordIds": ["record:target"],
        "patternIds": ["pattern:target"],
        "semanticEdgeIds": ["edge:target"],
        "memoryItemIds": ["fragment:target"],
        "insightDecisions": [
            {
                "sourceRefs": ["record:target"],
                "decision": "adopted",
                "summary": "Use the verified target mechanism.",
                "application": "Apply it to the target damage loop.",
            }
        ],
    }


def _premise_receipt(*, deep_read_ids: list[str] | None = None) -> dict[str, object]:
    receipt = _receipt()
    receipt["result"].update(
        {
            "deepRecordIds": ["drr-failure-loop", "drr-alternative-loop"],
            "deepReadRecordIds": list(deep_read_ids or []),
            "familyRecordCoverage": [
                {
                    "buildFamilyKey": "family:target",
                    "eligibleRecordCount": 2,
                    "returnedRecordCount": 2,
                    "unreturnedRecordCount": 0,
                    "recordKindCounts": {"failure_mode": 1, "resource_engine": 1},
                    "responseComplete": True,
                }
            ],
            "familyPremiseCatalog": [
                {
                    "premiseId": "rp-0123456789abcdef",
                    "buildFamilyKey": "family:target",
                    "evidenceRef": "drr-failure-loop",
                    "recordKind": "failure_mode",
                    "premiseType": "failure_condition",
                    "text": "目标场景中原始资源生成方式会失效。",
                    "componentKeys": ["skill:target-attack"],
                }
            ],
            "premiseAuditVersion": 1,
        }
    )
    return receipt


def _premise_usage(
    *,
    decision: str = "resolved",
    resolution_refs: list[str] | None = None,
) -> dict[str, object]:
    usage = _usage()
    usage["deepRecordIds"] = ["drr-failure-loop", "drr-alternative-loop"]
    usage["insightDecisions"] = [
        {
            "sourceRefs": ["drr-alternative-loop"],
            "decision": "adopted",
            "summary": "Adopt the deep-read alternative resource loop.",
            "application": "Use the alternative only in the target scenario.",
        }
    ]
    usage["premiseAuditVersion"] = 1
    premise_decision: dict[str, object] = {
        "premiseId": "rp-0123456789abcdef",
        "decision": decision,
        "resolutionRefs": list(resolution_refs or []),
        "application": "Handle the target resource failure explicitly.",
    }
    if decision == "caveated":
        premise_decision["caveat"] = "The target resource loop remains only partially verified."
    usage["premiseDecisions"] = [premise_decision]
    return usage


def test_progression_research_provenance_accepts_exact_family_and_used_ids():
    error, summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_usage(),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _receipt(),
    )

    assert error is None
    assert summary is not None
    assert summary["exactIdentityQueryRefs"] == ["dq-0000000000000001"]
    assert summary["deepRecordIds"] == ["record:target"]


def test_progression_research_provenance_accepts_graph_backed_gem_query_alias():
    error, summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_usage(),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _receipt(
            primary_skill_key="gem:Metadata/Items/Gems/SkillGemTargetAttack",
            primary_skill_keys=[
                "gem:Metadata/Items/Gems/SkillGemTargetAttack",
                "skill:target-attack",
            ],
        ),
    )

    assert error is None
    assert summary is not None
    assert summary["exactIdentityQueryRefs"] == ["dq-0000000000000001"]


def test_progression_research_provenance_fails_closed_on_wrong_family():
    error, _summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_usage(),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _receipt(
            ascendancy_key="ascendancy:other",
            primary_skill_key="skill:other",
        ),
    )

    assert error == "progression_exact_family_query_missing"


def test_progression_research_provenance_rejects_unreturned_memory_id():
    usage = _usage()
    usage["patternIds"] = ["pattern:not-returned"]

    error, _summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=usage,
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _receipt(),
    )

    assert error == "progression_research_item_not_in_receipt"


def test_progression_research_provenance_requires_a_query_seen_in_the_current_run():
    error, _summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_usage(),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _receipt(),
        not_before="2026-07-26T12:00:01+00:00",
    )

    assert error == "progression_research_receipt_not_current_run"


def test_progression_research_family_must_match_confirmed_core_secondary_skills():
    identity = IDENTITY.model_copy(
        update={
            "secondary_skill_keys": ["skill:TempestBellPlayer"],
            "secondary_skill_names": ["Tempest Bell"],
        }
    )

    error, _summary = progression_provenance.validate_research_provenance(
        identity=identity,
        research_memory_use=_usage(),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _receipt(),
    )

    assert error == "progression_research_family_identity_mismatch"


def test_progression_research_provenance_requires_every_failure_premise_decision():
    usage = _premise_usage(
        resolution_refs=["drr-alternative-loop"],
    )
    usage["premiseDecisions"] = []

    error, _summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=usage,
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _premise_receipt(deep_read_ids=["drr-alternative-loop"]),
    )

    assert error == "progression_research_premise_decision_incomplete"


def test_progression_research_provenance_rejects_a_resolution_seen_only_in_summary():
    error, _summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_premise_usage(
            resolution_refs=["drr-alternative-loop"],
        ),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _premise_receipt(deep_read_ids=[]),
    )

    assert error == "progression_research_resolution_not_deep_read"


def test_progression_research_provenance_rejects_a_forged_premise_receipt_id():
    usage = _premise_usage(
        resolution_refs=["drr-alternative-loop"],
    )
    usage["premiseDecisions"][0]["premiseId"] = "rp-fedcba9876543210"

    error, _summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=usage,
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _premise_receipt(deep_read_ids=["drr-alternative-loop"]),
    )

    assert error == "progression_research_premise_not_in_receipt"


def test_progression_research_provenance_accepts_any_deep_read_alternative_solution():
    error, summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_premise_usage(
            resolution_refs=["drr-alternative-loop"],
        ),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _premise_receipt(deep_read_ids=["drr-alternative-loop"]),
    )

    assert error is None
    assert summary is not None
    assert summary["premiseDecisionIds"] == ["rp-0123456789abcdef"]
    assert summary["caveatedPremiseIds"] == []


def test_progression_research_provenance_preserves_an_explicit_premise_caveat():
    error, summary = progression_provenance.validate_research_provenance(
        identity=IDENTITY,
        research_memory_use=_premise_usage(decision="caveated"),
        artifact_research_ref="dq-0000000000000001",
        receipt_reader=lambda _ref: _premise_receipt(),
    )

    assert error is None
    assert summary is not None
    assert summary["caveatedPremiseIds"] == ["rp-0123456789abcdef"]
