"""同正文跨补丁比较只折叠展示，来源版本与深读权限保持独立。"""

from contextlib import closing
from copy import deepcopy

import pytest

from server import main
from server.knowledge import mature_learning, patch_reviews, research_execution
from test_patch_reviews import query, review_payload, seeded
from test_research_execution_contract import _decision


SOURCE_A = "case:la-safe"
SOURCE_B = "case:current-comparison"


def _two_versions(tmp_path, *, different_conditions=False):
    service, payload, old = seeded(tmp_path)
    second = deepcopy(payload)
    record = second["deep_research_records"][0]
    record.update(
        game_patch="0.5.5", source_case_refs=[SOURCE_B],
        research_group_id="research:current-comparison",
    )
    if different_conditions:
        record["conditions"] = ["无小怪时需要独立验证的命中条件。"]
    new = service.propose_deep_research_records(second)
    assert new["status"] == "accepted", new
    assert old["recordIds"] != new["recordIds"]
    assert old["buildFamilyKeys"] == new["buildFamilyKeys"]
    return service, old, new


def _receipt(service, family, source):
    result = query(
        service, family, patch="0.5.5", detail_level="record",
        response_profile="create_compact", knowledge_scope="global_seed", source_case_ref=source,
    )
    page = service.start_retrieval_session(
        main._compact_create_research_response(result), response_profile="create_compact",
        run_ref=None, claim_ref=None,
    )
    assert page["retrieval"]["complete"] is True, page
    return result, page["dedupeQueryRef"]


def _contract(service, old, *, authoritative=SOURCE_A, comparison=SOURCE_B):
    family = old["buildFamilyKeys"][0]
    _, auth_ref = _receipt(service, family, authoritative)
    comparison_refs = [_receipt(service, family, comparison)[1]] if comparison else []
    return research_execution.construct_research_execution_contract(
        authoritative_dedupe_query_refs=[auth_ref], comparison_dedupe_query_refs=comparison_refs,
        build_family_key=family, selected_knowledge_scope="global_seed",
        selected_source_case_ref=authoritative, game_patch="0.5.5", passive_tree_version="0_5",
        db_path=service.db_path,
    )


def _plan(contract):
    return {
        "contractRef": contract["contractRef"],
        "selectedDesignCaseRef": contract["selectedDesignCaseRef"],
        "packageDecisions": [_decision(item["packageId"], adopted=True) for item in contract["packages"]],
        "crossCaseMechanismPlans": [],
    }


def test_cross_patch_identical_content_uses_one_authoritative_package_with_version_bindings(tmp_path):
    service, old, new = _two_versions(tmp_path)
    with closing(mature_learning.connect(service.db_path)) as con:
        assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 1
    contract = _contract(service, old)
    assert contract["status"] == "ready", contract
    assert len(contract["packages"]) == len(contract["reviewRequiredPackageIds"]) == 1
    package = contract["packages"][0]
    assert package["recordId"] == old["recordIds"][0]
    assert package["authority"] == "authoritative_and_comparison"
    assert package["sourceCaseRefs"] == sorted([SOURCE_A, SOURCE_B])
    assert package["targetApplicability"]["sourceGamePatch"] == "0.5.4"
    bindings = package["comparisonRecordBindings"]
    assert len(bindings) == 1
    assert bindings[0]["recordId"] == new["recordIds"][0]
    assert bindings[0]["sourceCaseRef"] == SOURCE_B
    assert bindings[0]["sourceGamePatch"] == "0.5.5"
    assert bindings[0]["targetApplicability"]["status"] == "current_evidence"
    assert research_execution.validate_research_execution_plan(_plan(contract), contract)[0] is None


def test_comparison_deep_read_cannot_replace_folded_authoritative_read_or_cross_case_role(tmp_path):
    service, old, new = _two_versions(tmp_path)
    contract = _contract(service, old)
    assert contract["status"] == "ready", contract
    assert contract["comparisonDeepReadRecordIds"] == new["recordIds"]
    without_authoritative_read = deepcopy(contract)
    without_authoritative_read["authoritativeDeepReadRecordIds"] = []
    assert research_execution.validate_research_execution_plan(
        _plan(contract), without_authoritative_read
    )[0] == "research_execution_authoritative_package_not_deep_read"
    cross_case_disguise = _plan(contract)
    cross_case_disguise["packageDecisions"][0]["crossCasePlanRef"] = "xcp-fake-comparison"
    assert research_execution.validate_research_execution_plan(
        cross_case_disguise, contract
    )[0] == "research_execution_authoritative_package_has_cross_case_plan"


@pytest.mark.parametrize("outcome", ["invalid", "changed_scope"])
def test_inapplicable_old_record_cannot_borrow_identical_new_record_authority(tmp_path, outcome):
    service, old, new = _two_versions(tmp_path)
    payload = review_payload(service)
    payload.update(target_id=old["recordIds"][0], outcome=outcome)
    with closing(mature_learning.connect(service.db_path)) as con:
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (old["recordIds"][0],)
        ).fetchone()
        payload["source_fingerprint"] = patch_reviews.fingerprint(row)
    reviewed = service.submit_patch_review(payload)
    assert reviewed["status"] == "accepted", reviewed
    family = old["buildFamilyKeys"][0]
    old_lane, _ = _receipt(service, family, SOURCE_A)
    assert old_lane["deepResearchRecords"] == []
    assert old_lane["selectedSourceCaseRef"] is None
    rejected = _contract(service, old)
    assert rejected["status"] == "error", rejected
    current_only = _contract(service, old, authoritative=SOURCE_B, comparison=None)
    assert current_only["status"] == "ready", current_only
    assert current_only["packages"][0]["recordId"] == new["recordIds"][0]
    assert current_only["packages"][0].get("comparisonRecordBindings", []) == []
    assert current_only["packages"][0]["sourceCaseRefs"] == [SOURCE_B]


def test_condition_difference_keeps_separate_authoritative_and_comparison_packages(tmp_path):
    service, old, new = _two_versions(tmp_path, different_conditions=True)
    contract = _contract(service, old)
    assert contract["status"] == "ready", contract
    assert len(contract["packages"]) == 2
    assert {package["recordId"] for package in contract["packages"]} == set(old["recordIds"] + new["recordIds"])
    assert {package["authority"] for package in contract["packages"]} == {"authoritative", "comparison"}
    assert all(not package.get("comparisonRecordBindings") for package in contract["packages"])
