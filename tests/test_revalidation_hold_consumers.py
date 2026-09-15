from contextlib import closing
from copy import deepcopy

from server.knowledge import mature_learning
from test_deep_revalidation_holds import _seed, _row


def test_held_family_keeps_identity_but_loses_create_authorization(tmp_path):
    service, _, request = _seed(tmp_path)
    assert service.submit_revalidation_result(**request)["status"] == "accepted"
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        result = service._family_create_eligibility(
            con, knowledge_scope=row["knowledge_scope"], build_family_key=row["build_family_key"],
            game_patch=row["game_patch"], passive_tree_version=row["passive_tree_version"],
        )
        assert result["status"] == "needs_revalidation"
        assert "revalidation_hold" in result["blockers"]
        assert con.execute("SELECT count(*) FROM research_build_families").fetchone()[0] == 1


def test_default_source_selection_counts_only_unheld_bindings(tmp_path):
    service, payload, request = _seed(tmp_path)
    assert service.submit_revalidation_result(**request)["status"] == "accepted"
    independent = deepcopy(payload)
    record = independent["deep_research_records"][0]
    record["source_case_refs"] = ["case:zz-independent"]
    record["research_group_id"] = "research:zz-independent"
    record["content"] = "Separate source observation with a different condition."
    assert service.propose_deep_research_records(independent)["status"] == "accepted"
    with closing(mature_learning.connect(service.db_path)) as con:
        row = _row(con, request["target_id"])
        family_key = row["build_family_key"]
    result = service.query_research_memory(
        "", build_family_keys=[family_key], response_profile="create_compact",
    )
    assert result["selectedSourceCaseRef"] == "case:zz-independent"
    assert len(result["deepResearchRecords"]) == 1
