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
