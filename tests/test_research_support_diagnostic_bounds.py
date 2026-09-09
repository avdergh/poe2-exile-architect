"""Generated support diagnostics must preserve failures without hiding behind copy safety."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import run_phase4_deep_review_acceptance as acceptance


@pytest.mark.parametrize("pair_count", [5, 12])
def test_large_support_failure_keeps_all_pairs_and_safe_readable_diagnostics(
    monkeypatch, pair_count
):
    skill_key = "skill:fixture-root-effect"
    support_keys = [f"gem:fixture-support-{index}" for index in range(pair_count)]
    snapshot = SimpleNamespace(
        nodes=[
            SimpleNamespace(stable_key=key, display_name=f"Fixture component {index}")
            for index, key in enumerate([skill_key, *support_keys])
        ]
    )
    monkeypatch.setattr(acceptance, "_active_gem_endpoint_keys", lambda **_kwargs: [skill_key])
    monkeypatch.setattr(acceptance, "_source_socket_package_skill_keys", lambda **_kwargs: set())

    def unsupported_candidates(*, support_keys, **_kwargs):
        return [
            SimpleNamespace(
                status="unsupported",
                request=SimpleNamespace(inputs={"support_key": key}),
                facts={
                    "excluded_reason": "excluded_types_matched",
                    "required_types_expr": ["Spell"],
                    "excluded_types_expr": ["FixtureExcludedType"],
                    "matched_skill_types": [f"FixtureSkillType{index}" for index in range(24)],
                },
                source_refs=["static:fixture-contract"],
            )
            for key in support_keys
        ]

    monkeypatch.setattr(
        acceptance.physical_graph, "support_skill_group_candidates", unsupported_candidates
    )
    record = {
        "component_keys": [skill_key, *support_keys],
        "typed_payload": {
            "supportPackages": [{"skillKey": skill_key, "supportKeys": support_keys}]
        },
    }
    original = deepcopy(record)
    summary = {
        "titleZh": "多个辅助均被静态组合合同拒绝",
        "recordKind": "skill_package",
        "sampleId": "fixture_sample_001",
        "componentKeys": record["component_keys"],
    }
    kept, summaries, deferred = (
        acceptance._filter_records_with_unsupported_structured_support_packages(
            graph_service=SimpleNamespace(snapshot=snapshot),
            deep_payload={"schema_version": 5, "deep_research_records": [record]},
            accepted_records=[summary],
        )
    )

    assert record == original
    assert kept["deep_research_records"] == [] and summaries == []
    assert deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert len(deferred[0]["unsupportedPairs"]) == pair_count
    assert {item["supportKey"] for item in deferred[0]["unsupportedPairs"]} == set(support_keys)
    assert all(len(item["endpointSkillTypes"]) == 24 for item in deferred[0]["unsupportedPairs"])
    assert "supportCoverageExceptions" in deferred[0]["caveats"][1]
    assert "source_coverage_gap" in deferred[0]["caveats"][1]
    acceptance._assert_safe({"deferredCandidates": deferred})
