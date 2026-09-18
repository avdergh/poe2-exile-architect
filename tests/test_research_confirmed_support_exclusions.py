"""Confirmed source mistakes may be omitted without authorizing invalid knowledge."""

from copy import deepcopy
import json

import pytest

from scripts import run_phase4_deep_review_acceptance as acceptance
from tests.test_research_support_source_context import (
    SUPPORTS,
    graph,
    grant_graph,
    group,
    package,
)


def _retained_package(source, names):
    value = package(source)
    retained = [
        (key, ref)
        for key, ref in zip(value["supportKeys"], value["socketedItemRefs"], strict=True)
        if key in {SUPPORTS[name] for name in names}
    ]
    value["supportKeys"] = [key for key, _ in retained]
    value["socketedItemRefs"] = [ref for _, ref in retained]
    return value


def _record(source, retained=()):
    root = source["rootSkill"]["skillId"]
    components = [
        {
            "candidateName": root,
            "componentKey": "skill:" + root,
            "role": "primary_damage",
        }
    ]
    components.extend(
        {"candidateName": name, "componentKey": SUPPORTS[name], "role": "support_modifier"}
        for name in retained
    )
    return {
        "sampleId": "fixture",
        "researchGroupId": "research:fixture",
        "caseRef": "case:fixture",
        "safeEvidenceRefs": ["evidence:fixture"],
        "recordKind": "skill_package",
        "title": "已确认的技能组合",
        "summary": "只保存有来源且适用的组合。",
        "content": "技能组合的使用条件仍须独立验证。",
        "components": components,
        "typedPayload": {
            "supportPackages": [_retained_package(source, retained)] if retained else []
        },
    }


def _review(sources, records, dispositions):
    return {
        "safeArtifactOnly": True,
        "reviewContractVersion": "phase4-safe-review-v3",
        "caseCoverage": {"supports": "covered"},
        "deepResearchRecords": records,
        "sourceSkillGroupReviews": [
            {
                "groupRef": source["groupRef"],
                "researchDisposition": "represented" if records else "not_relevant",
                "supportDisposition": dispositions[source["groupRef"]],
                "affectedRecords": [record["title"] for record in records],
                "reason": "依照本来源的静态兼容结果处理。",
            }
            for source in sources
        ],
    }


def _diagnose(service, sources, records, dispositions):
    manifest = {"activeSkillGroups": sources}
    review = _review(sources, records, dispositions)
    before = deepcopy((manifest, review, records))
    diagnostics = acceptance._source_skill_evidence_diagnostics(
        review=review,
        accepted_records=records,
        source_skill_manifest=manifest,
        graph_service=service,
        source_skill_resolutions={},
    )
    # Exclusion is an audit result, never a rewrite of source evidence or knowledge.
    assert (manifest, review, records) == before
    return manifest, review, diagnostics


def _core_gaps(service, manifest, review, records):
    return acceptance._core_skill_group_support_gaps(
        records,
        source_skill_manifest=manifest,
        source_group_reviews=review["sourceSkillGroupReviews"],
        graph_service=service,
    )


def _support_coverage(service, manifest, review, records, diagnostics):
    coverage, _ = acceptance._evaluate_case_coverage(
        review=review,
        accepted_records=records,
        graph_service=service,
        source_skill_manifest=manifest,
        source_evidence_diagnostics=deepcopy(diagnostics),
    )
    return coverage["supports"]


@pytest.mark.parametrize("retain_record", [False, True])
def test_all_confirmed_incompatible_supports_close_without_negative_record(retain_record):
    source = group("group:all-invalid", root="PayloadAPlayer", supports=("Damage", "Host"))
    records = [_record(source)] if retain_record else []
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "excluded_incompatible"}
    )

    assert diagnostics["excludedIncompatibleSupportCount"] == 2
    pairs = diagnostics["excludedIncompatibleSupportPairs"]
    assert {(row["groupRef"], row["supportKey"], row["socketedItemRef"]) for row in pairs} == {
        (source["groupRef"], "support:" + item["gemId"], item["socketedItemRef"])
        for item in source["supports"]
    }
    state = diagnostics["skillGroupDispositions"][0]
    assert state["disposition"] == "excluded_incompatible"
    assert state["supportCount"] == state["excludedSupportCount"] == 2
    assert state["unrepresentedSupportNames"] == []
    assert diagnostics["undisposedSkillGroupCount"] == 0
    assert not diagnostics["supportCoverageBlockedByStructuredOmission"]
    assert all(record["recordKind"] != "open_question" for record in records)
    if records:
        assert _core_gaps(service, manifest, review, records) == []
        assert _support_coverage(service, manifest, review, records, diagnostics) == "covered"


def test_mixed_source_keeps_one_compatible_support_and_excludes_only_bad_instance():
    source = group("group:mixed", root="PayloadBPlayer", supports=("Host", "Damage"))
    records = [_record(source, ("Damage",))]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "packaged"}
    )

    assert diagnostics["excludedIncompatibleSupportCount"] == 1
    assert diagnostics["excludedIncompatibleSupportPairs"][0]["supportKey"] == SUPPORTS["Host"]
    state = diagnostics["skillGroupDispositions"][0]
    assert state["disposition"] == "packaged"
    assert state["supportCount"] == 2 and state["excludedSupportCount"] == 1
    assert state["unrepresentedSupportNames"] == []
    assert _core_gaps(service, manifest, review, records) == []
    assert _support_coverage(service, manifest, review, records, diagnostics) == "covered"
    clean = acceptance._without_source_support_bindings(
        {"deep_research_records": [{"typed_payload": deepcopy(records[0]["typedPayload"])}]}
    )
    assert SUPPORTS["Host"] not in json.dumps(clean)
    assert "excludedIncompatibleSupport" not in json.dumps(clean)


def test_mixed_source_cannot_drop_one_of_two_remaining_compatible_supports():
    source = group("group:two-valid", root="MinionPlayer", supports=("Host", "Minion", "Damage"))
    records = [_record(source, ("Minion",))]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "packaged"}
    )

    assert diagnostics["excludedIncompatibleSupportCount"] == 1
    state = diagnostics["skillGroupDispositions"][0]
    assert state["disposition"] == "partially_packaged"
    assert state["unrepresentedSupportNames"] == ["Damage"]
    assert _core_gaps(service, manifest, review, records) == ["skill:MinionPlayer"]
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


def test_fully_retained_mixed_source_closes_with_two_compatible_supports():
    source = group("group:two-valid", root="MinionPlayer", supports=("Host", "Minion", "Damage"))
    records = [_record(source, ("Minion", "Damage"))]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "packaged"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 1
    assert diagnostics["skillGroupDispositions"][0]["disposition"] == "packaged"
    assert _core_gaps(service, manifest, review, records) == []
    assert _support_coverage(service, manifest, review, records, diagnostics) == "covered"


@pytest.mark.parametrize("disposition", ["packaged", "excluded_incompatible"])
def test_unknown_payload_is_not_a_confirmed_exclusion(disposition):
    source = group("group:unknown", root="MinionPlayer", supports=("Damage",))
    records = [_record(source)]
    service = graph(payload_known=False)
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: disposition}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["excludedIncompatibleSupportPairs"] == []
    assert diagnostics["undisposedSkillGroupCount"] == 1
    assert _core_gaps(service, manifest, review, records) == ["skill:MinionPlayer"]
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


@pytest.mark.parametrize("bad_id", [None, "Metadata/Items/Gem/MissingDamageIdentity"])
def test_missing_exact_support_identity_cannot_borrow_name_to_exclude(bad_id):
    source = group("group:missing-gem", supports=("Damage",))
    source["supports"][0]["gemId"] = bad_id
    records = [_record(source)]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "excluded_incompatible"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["undisposedSkillGroupCount"] == 1
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


def test_missing_root_identity_cannot_certify_incompatibility():
    source = group("group:missing-root", root="UnresolvedRootPlayer", supports=("Damage",))
    records = [_record(source)]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "excluded_incompatible"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["undisposedSkillGroupCount"] == 1
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


def test_missing_graph_cannot_authorize_exclusion():
    source = group("group:no-graph", supports=("Damage",))
    records = [_record(source)]
    _, _, diagnostics = _diagnose(
        None, [source], records, {source["groupRef"]: "excluded_incompatible"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["undisposedSkillGroupCount"] == 1


@pytest.mark.parametrize("retained", [(), ("Damage",)])
def test_compatible_support_cannot_be_declared_excluded_even_when_packaged(retained):
    source = group("group:false-claim", root="PayloadBPlayer", supports=("Damage",))
    records = [_record(source, retained)]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "excluded_incompatible"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["skillGroupDispositions"][0]["disposition"] != "excluded_incompatible"
    assert diagnostics["undisposedSkillGroupCount"] == 1
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


def test_mixed_group_cannot_claim_every_support_was_excluded():
    source = group("group:false-all", root="PayloadBPlayer", supports=("Host", "Damage"))
    records = [_record(source, ("Damage",))]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "excluded_incompatible"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 1
    assert diagnostics["undisposedSkillGroupCount"] == 1
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


def test_same_named_support_is_excluded_only_from_its_incompatible_container():
    first = group("group:without-payload", supports=("Damage",))
    second = group("group:with-payload", payload="PayloadBPlayer", supports=("Damage",))
    records = [_record(second, ("Damage",))]
    _, _, diagnostics = _diagnose(
        graph(),
        [first, second],
        records,
        {first["groupRef"]: "excluded_incompatible", second["groupRef"]: "packaged"},
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 1
    pair = diagnostics["excludedIncompatibleSupportPairs"][0]
    assert pair["groupRef"] == first["groupRef"]
    assert pair["socketedItemRef"] == first["supports"][0]["socketedItemRef"]
    states = {row["groupRef"]: row for row in diagnostics["skillGroupDispositions"]}
    assert states[first["groupRef"]]["disposition"] == "excluded_incompatible"
    assert states[second["groupRef"]]["disposition"] == "packaged"
    assert states[second["groupRef"]]["excludedSupportCount"] == 0


def test_exclusion_of_same_name_elsewhere_does_not_waive_missing_compatible_instance():
    first = group("group:without-payload", supports=("Damage",))
    second = group("group:with-payload", payload="PayloadBPlayer", supports=("Damage",))
    records = [_record(first)]
    service = graph()
    manifest, review, diagnostics = _diagnose(
        service,
        [first, second],
        records,
        {first["groupRef"]: "excluded_incompatible", second["groupRef"]: "packaged"},
    )
    states = {row["groupRef"]: row for row in diagnostics["skillGroupDispositions"]}
    assert states[first["groupRef"]]["excludedSupportCount"] == 1
    assert states[second["groupRef"]]["excludedSupportCount"] == 0
    assert states[second["groupRef"]]["unrepresentedSupportNames"] == ["Damage"]
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


def test_legal_support_grant_is_evaluated_before_deciding_what_to_exclude():
    source = group("group:grant-chain", supports=("Host", "Damage"))
    records = [_record(source, ("Host", "Damage"))]
    service = grant_graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "packaged"}
    )
    # Damage cannot support the Meta root alone; the independently applicable Host
    # support grants a reachable Damage payload, so neither instance is excluded.
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["skillGroupDispositions"][0]["disposition"] == "packaged"
    assert _core_gaps(service, manifest, review, records) == []


def test_unobserved_granted_effect_is_unknown_instead_of_excluded():
    source = group("group:unknown-grant", supports=("Host", "Damage"))
    source["supports"][0]["enableGlobal2"] = False
    records = [_record(source, ("Host",))]
    service = grant_graph()
    manifest, review, diagnostics = _diagnose(
        service, [source], records, {source["groupRef"]: "packaged"}
    )
    assert diagnostics["excludedIncompatibleSupportCount"] == 0
    assert diagnostics["skillGroupDispositions"][0]["unrepresentedSupportNames"] == ["Damage"]
    assert _support_coverage(service, manifest, review, records, diagnostics) == "evidence_missing"


@pytest.mark.parametrize("record_kind", ["skill_package", "open_question"])
def test_submitted_incompatible_knowledge_still_rejected_without_rewriting(record_kind):
    source = group("group:invalid-submission", supports=("Damage",))
    manifest = {"activeSkillGroups": [source]}
    record = {
        "record_kind": record_kind,
        "content": "这是原文；即使描述不兼容，也不能自动删改正文后入库。",
        "component_keys": ["skill:HostPlayer", SUPPORTS["Damage"]],
        "typed_payload": {"supportPackages": [package(source)]},
    }
    payload = {"deep_research_records": [record]}
    summaries = [
        {
            "titleZh": "仍含不兼容配对",
            "recordKind": record_kind,
            "sampleId": "fixture",
            "componentKeys": record["component_keys"],
        }
    ]
    before = deepcopy((manifest, payload, summaries))
    filtered, kept, deferred = (
        acceptance._filter_records_with_unsupported_structured_support_packages(
            graph_service=graph(),
            source_skill_manifest=manifest,
            deep_payload=payload,
            accepted_records=summaries,
        )
    )
    assert not filtered["deep_research_records"] and not kept
    assert deferred[0]["reason"] == "unsupported_structured_skill_support_pair"
    assert (manifest, payload, summaries) == before


def test_exclusion_uniqueness_counts_compatible_instances_in_other_groups():
    bad = group("group:bad", supports=("Damage",))
    good = group("group:good", payload="PayloadBPlayer", supports=("Damage",))
    _, _, diagnostic = _diagnose(
        graph(),
        [bad, good],
        [],
        {bad["groupRef"]: "excluded_incompatible", good["groupRef"]: "packaged"},
    )
    assert diagnostic["excludedIncompatibleSupportPairs"][0]["sourcePairInstanceCount"] == 2


def test_exclusion_uniqueness_is_unknown_when_source_identity_is_incomplete():
    bad = group("group:bad", supports=("Damage",))
    unknown = group("group:unknown", supports=("Damage",))
    unknown["supports"][0]["gemId"] = "Metadata/Items/Gem/Absent"
    _, _, diagnostic = _diagnose(
        graph(),
        [bad, unknown],
        [],
        {bad["groupRef"]: "excluded_incompatible", unknown["groupRef"]: "excluded_incompatible"},
    )
    assert diagnostic["excludedIncompatibleSupportCount"] == 1
    assert diagnostic["excludedIncompatibleSupportPairs"][0]["sourcePairInstanceCount"] is None


def test_excluded_pair_cannot_enter_an_alternative_claim_unless_valid_elsewhere():
    pair = {"skillKey": "skill:HostPlayer", "supportKey": SUPPORTS["Damage"]}
    blocked = acceptance._unretained_excluded_support_pairs([pair], [])
    assert acceptance._contains_excluded_support_pair(
        {pair["skillKey"], pair["supportKey"], "notable:unrelated"}, blocked
    )
    assert not acceptance._contains_excluded_support_pair(
        {"skill:OtherPlayer", pair["supportKey"]}, blocked
    )
    valid = [
        {
            "_supportCompatibility": [
                {
                    "skillKey": pair["skillKey"],
                    "supportKeys": [pair["supportKey"]],
                    "matchedEndpointKeys": ["skill:PayloadBPlayer"],
                }
            ]
        }
    ]
    assert not acceptance._unretained_excluded_support_pairs([pair], valid)
