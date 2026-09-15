"""顶层校验解释全部确定性拒绝，不改变原有拒绝语义。"""

import pytest

from scripts import research_mature_builds as workflow


@pytest.mark.parametrize("section", ["patternWrite", "deepRecordWrite", "semanticEdgeWrite"])
def test_writer_error_is_visible_at_top_level(section):
    result = workflow._validation_only_result(
        {
            "status": "rejected",
            section: {
                "status": "rejected",
                "errorCode": "duplicate_knowledge_identity_in_payload",
                "facts": {"candidateIndexes": [1, 3]},
                "suggestedRepair": "",
            },
        },
        sample_id="case:fixture",
    )
    assert result["readyForAccept"] is False
    assert result["blockingReasonCount"] == 1
    assert result["blockingReasons"][0]["candidateIndexes"] == [1, 3]
    assert result["blockingReasons"][0]["suggestedRepair"]
    assert result["validationIssues"][0]["type"] == "duplicate_knowledge_identity_in_payload"
    public_section = section.replace("Write", "Validation")
    assert result["validationIssues"][0]["loc"] == [public_section]
    assert (
        result[result["blockingReasons"][0]["loc"][0]]["errorCode"]
        == "duplicate_knowledge_identity_in_payload"
    )
    assert result["schemaIssueCount"] == 0


def test_structured_schema_paths_remain_available():
    issue = {
        "loc": ["deepResearchRecords", 2, "content"],
        "msg": "content too long",
        "type": "value_error",
    }
    result = workflow._validation_only_result(
        {
            "status": "rejected",
            "deepRecordWrite": {
                "status": "rejected",
                "errorCode": "invalid_schema",
                "facts": {"validationIssues": [issue]},
            },
        },
        sample_id="case:fixture",
    )
    assert result["schemaIssueCount"] == 1
    assert result["validationIssues"] == [issue]
    assert result["blockingReasons"][0]["errorCode"] == "invalid_schema"


def test_success_and_accepted_safe_subset_have_no_fabricated_blocker():
    for deferred in ([], [{"reason": "source_coverage_gap"}]):
        result = workflow._validation_only_result(
            {
                "status": "accepted",
                "deepRecordWrite": {"status": "accepted"},
                "deferredCandidates": deferred,
                "deferredCandidateCount": len(deferred),
            },
            sample_id="case:fixture",
        )
        assert result["readyForAccept"] is True
        assert result["blockingReasons"] == []
        assert result["fullyResolvedForAccept"] is (not deferred)
