from copy import deepcopy

import pytest

from server.knowledge import mature_learning, research_execution, research_memory
from server.knowledge import patch_reviews
from server import main
from test_research_memory import _family_deep_payload, _graph_service, _edge_payload


def seeded(tmp_path):
    service = research_memory.ResearchMemoryService(
        db_path=tmp_path / "memory.sqlite", graph_service=_graph_service()
    )
    payload = _family_deep_payload()
    payload["schema_version"] = 6
    record = payload["deep_research_records"][0]
    record.update(record_schema_version=2, source_state_scope="active_state")
    result = service.propose_deep_research_records(payload)
    assert result["status"] == "accepted", result
    return service, payload, result


def query(service, family, patch="0.5.5", **kwargs):
    return service.query_research_memory(
        "", build_family_keys=[family], game_patch=patch, passive_tree_version="0_5", **kwargs
    )


def test_historical_family_full_create_lane_and_execution_remain_available(tmp_path):
    service, _, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    discovery = service.query_research_memory(
        "",
        detail_level="family",
        class_key="class:monk",
        game_patch="0.5.5",
        passive_tree_version="0_5",
    )
    assert discovery["buildFamilies"][0]["createEligibility"]["status"] == "authorized"
    assert discovery["buildFamilies"][0]["gamePatch"] is None
    assert discovery["buildFamilies"][0]["sourceGamePatches"] == ["0.5.4"]
    result = query(service, family, detail_level="record", response_profile="create_compact")
    record = result["deepResearchRecords"][0]
    assert record["gamePatch"] == "0.5.4"
    assert record["targetApplicability"]["status"] == "historical_unreviewed"
    compact = main._compact_create_research_response(result)
    page = service.start_retrieval_session(
        compact, response_profile="create_compact", run_ref=None, claim_ref=None
    )
    receipt = service.read_query_receipt(page["dedupeQueryRef"])
    assert (
        receipt["result"]["recordApplicability"][record["recordId"]]["sourceGamePatch"] == "0.5.4"
    )
    con = mature_learning.connect(service.db_path)
    try:
        rows = research_execution._fetch_lane_records(
            con,
            build_family_key=family,
            knowledge_scope="global_seed",
            source_case_ref="case:la-safe",
            game_patch="0.5.5",
            passive_tree_version="0_5",
        )
        assert rows and rows[0]["game_patch"] == "0.5.4"
    finally:
        con.close()


def test_same_family_new_patch_preserves_old_record_even_same_source(tmp_path):
    service, payload, old = seeded(tmp_path)
    revised = deepcopy(payload)
    revised["deep_research_records"][0].update(
        game_patch="0.5.5", content="新补丁下单独保存机制核查结果，旧版本正文保持不变。"
    )
    new = service.propose_deep_research_records(revised)
    assert new["status"] == "accepted", new
    assert new["buildFamilyKeys"] == old["buildFamilyKeys"]
    assert new["recordIds"] != old["recordIds"]
    rows = query(service, old["buildFamilyKeys"][0], detail_level="record")["deepResearchRecords"]
    assert len(rows) == 2
    assert rows[0]["gamePatch"] == "0.5.5"
    assert len({row["knowledgeConceptKey"] for row in rows}) == 1
    historical = query(service, old["buildFamilyKeys"][0], patch="0.5.4", detail_level="record")
    assert (
        historical["deepResearchRecords"][0]["content"]
        == payload["deep_research_records"][0]["content"]
    )


def review_payload(service):
    target = service.inspect_patch_review_targets(target_game_patch="0.5.5")["targets"][0]
    return dict(
        target_kind="deep_research_record",
        target_id=target["targetId"],
        knowledge_scope="global_seed",
        target_game_patch="0.5.5",
        source_fingerprint=target["sourceFingerprint"],
        outcome="invalid",
        rationale="独立逐条比对补丁与记录正文，确认目标版本机制前提不再成立。",
        correction_summary="仅禁止目标版本依赖这一旧前提，保留原版本记录。",
        patch_evidence_refs=["ggg:patch:0.5.5"],
        review_evidence_refs=["review:independent:fixture"],
        author_ref="agent:author",
        reviewer_ref="agent:reviewer",
    )


def review_edge(service, edge_id, outcome):
    con = mature_learning.connect(service.db_path)
    try:
        row = con.execute("SELECT * FROM research_semantic_edges WHERE edge_id=?", (edge_id,)).fetchone()
        payload = review_payload(service)
        payload.update(target_kind="semantic_edge", target_id=edge_id,
                       source_fingerprint=patch_reviews.fingerprint(row), outcome=outcome)
    finally:
        con.close()
    return service.submit_patch_review(payload)


@pytest.mark.parametrize("outcome, accepted", [(None, False), ("still_valid", False),
    ("uncertain", False), ("invalid", True), ("changed_scope", True)])
def test_new_patch_inverse_ignores_only_reviewed_inapplicable_edges(tmp_path, outcome, accepted):
    service, _, _ = seeded(tmp_path)
    first = service.propose_semantic_edges(_edge_payload(
        "skill:LightningArrowPlayer", "support:Scattershot", "enables_mechanic"))
    edge_id = first["edgeIds"][0]
    if outcome:
        review_edge(service, edge_id, outcome)
    new = _edge_payload("support:Scattershot", "skill:LightningArrowPlayer", "enables_mechanic")
    new["semantic_edges"][0].update(game_patch="0.5.5", source_case_refs=["case:latest-season"])
    result = service.propose_semantic_edges(new)
    assert (result["status"] == "accepted") is accepted, result
    con = mature_learning.connect(service.db_path)
    try:
        row = con.execute("SELECT * FROM research_semantic_edges WHERE edge_id=?", (edge_id,)).fetchone()
        assert row["game_patch"] == "0.5.4" and row["planner_visible"] == 1
        assert patch_reviews.applicability(con, row, "0.5.4", kind="semantic_edge")["adoptionAllowed"]
    finally:
        con.close()


@pytest.mark.parametrize("invalid_index", [0, 1])
def test_new_patch_cycle_excludes_inapplicable_edges_at_every_depth(tmp_path, invalid_index):
    service, _, _ = seeded(tmp_path)
    nodes = ["skill:LightningArrowPlayer", "support:Scattershot", "passive:pob:0_5:100"]
    edges = [service.propose_semantic_edges(_edge_payload(a, b, "enables_mechanic"))["edgeIds"][0]
             for a, b in zip(nodes, nodes[1:])]
    review_edge(service, edges[invalid_index], "invalid")
    new = _edge_payload(nodes[2], nodes[0], "enables_mechanic")
    new["semantic_edges"][0].update(game_patch="0.5.5", source_case_refs=["case:latest-season"])
    assert service.propose_semantic_edges(new)["status"] == "accepted"


def test_expired_edge_review_does_not_exempt_a_changed_claim(tmp_path):
    service, _, _ = seeded(tmp_path)
    edge_id = service.propose_semantic_edges(_edge_payload(
        "skill:LightningArrowPlayer", "support:Scattershot", "enables_mechanic"))["edgeIds"][0]
    review_edge(service, edge_id, "invalid")
    con = mature_learning.connect(service.db_path)
    try:
        con.execute("UPDATE research_semantic_edges SET rationale='Changed mechanism claim requiring review' WHERE edge_id=?", (edge_id,))
        con.commit()
    finally:
        con.close()
    new = _edge_payload("support:Scattershot", "skill:LightningArrowPlayer", "enables_mechanic")
    new["semantic_edges"][0]["game_patch"] = "0.5.5"
    assert service.propose_semantic_edges(new)["errorCode"] == "semantic_cycle_or_conflict"


def test_review_only_excludes_target_adoption_and_invalidates_receipts(tmp_path):
    service, _, accepted = seeded(tmp_path)
    family = accepted["buildFamilyKeys"][0]
    result = query(service, family, detail_level="record", response_profile="create_compact")
    page = service.start_retrieval_session(
        main._compact_create_research_response(result),
        response_profile="create_compact",
        run_ref=None,
        claim_ref=None,
    )
    payload = review_payload(service)
    reviewed = service.submit_patch_review(payload)
    assert reviewed["sourcePreserved"] is True
    assert service.submit_patch_review(payload)["idempotentReplay"] is True
    assert service.read_query_receipt(page["dedupeQueryRef"]) is None
    assert not query(service, family, response_profile="create_compact")["deepResearchRecords"]
    corrected = main._compact_create_research_response(query(service, family, response_profile="create_compact"))
    assert corrected["patchCorrections"][0]["recordId"] == payload["target_id"]
    assert corrected["patchCorrections"][0]["createAuthorizing"] is False
    assert query(service, family, patch="0.5.4", response_profile="create_compact")[
        "deepResearchRecords"
    ]
    assert (
        query(service, family)["deepResearchRecords"][0]["targetApplicability"]["status"]
        == "incompatible"
    )


@pytest.mark.parametrize("change", ["fingerprint", "same_reviewer", "scope"])
def test_review_rejects_unbound_or_unreviewed_decision(tmp_path, change):
    service, _, _ = seeded(tmp_path)
    payload = review_payload(service)
    if change == "fingerprint":
        payload["source_fingerprint"] = "0" * 64
    if change == "same_reviewer":
        payload["reviewer_ref"] = payload["author_ref"]
    if change == "scope":
        payload["knowledge_scope"] = "local_user"
    with pytest.raises(ValueError):
        service.submit_patch_review(payload)


def test_batch_failure_rolls_back_prior_reviews(tmp_path):
    from scripts.apply_research_patch_reviews import apply_bundle

    service, _, _ = seeded(tmp_path)
    first = review_payload(service)
    missing = {**first, "target_id": "drr-0000000000000000"}
    with pytest.raises(ValueError):
        apply_bundle(service.db_path, [first, missing])
    con = mature_learning.connect(service.db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_patch_reviews").fetchone()[0] == 0
    finally:
        con.close()


def test_adding_evidence_cannot_revoke_invalid_claim_review(tmp_path):
    service, _, accepted = seeded(tmp_path)
    payload = review_payload(service)
    service.submit_patch_review(payload)
    con = mature_learning.connect(service.db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET safe_evidence_refs=? WHERE record_id=?",
            ('["safe:new-evidence"]', payload["target_id"]),
        )
        con.commit()
    finally:
        con.close()
    family = accepted["buildFamilyKeys"][0]
    assert not query(service, family, response_profile="create_compact")["deepResearchRecords"]
    assert (
        query(service, family)["deepResearchRecords"][0]["targetApplicability"]["status"]
        == "incompatible"
    )


def test_release_review_scope_and_source_binding_are_enforced(tmp_path):
    from server.knowledge import patch_reviews

    service, _, _ = seeded(tmp_path)
    service.submit_patch_review(review_payload(service))
    con = mature_learning.connect(service.db_path)
    try:
        patch_reviews.validate_release_reviews(con)
        con.execute("UPDATE research_patch_reviews SET knowledge_scope='local_user'")
        with pytest.raises(ValueError):
            patch_reviews.validate_release_reviews(con)
        patch_reviews.validate_release_reviews(con, prune=True)
        assert con.execute("SELECT count(*) FROM research_patch_reviews").fetchone()[0] == 0
    finally:
        con.close()


def test_release_prunes_expired_reviews_without_deleting_local_history(tmp_path):
    from server.knowledge import patch_reviews

    service, _, _ = seeded(tmp_path)
    payload = review_payload(service)
    service.submit_patch_review(payload)
    con = mature_learning.connect(service.db_path)
    try:
        con.execute(
            "UPDATE deep_research_records SET content='已修订的另一条机制断言。' WHERE record_id=?",
            (payload["target_id"],),
        )
        assert con.execute("SELECT count(*) FROM research_patch_reviews").fetchone()[0] == 1
        patch_reviews.validate_release_reviews(con, prune=True)
        assert con.execute("SELECT count(*) FROM research_patch_reviews").fetchone()[0] == 0
        con.rollback()
        assert con.execute("SELECT count(*) FROM research_patch_reviews").fetchone()[0] == 1
    finally:
        con.close()


def test_backfill_keeps_two_source_patch_versions(tmp_path):
    service, payload, old = seeded(tmp_path)
    payload["deep_research_records"][0]["game_patch"] = "0.5.5"
    new = service.propose_deep_research_records(payload)
    assert new["status"] == "accepted"
    service.backfill_deep_research_knowledge(force=True)
    rows = query(service, old["buildFamilyKeys"][0], detail_level="record")["deepResearchRecords"]
    assert len(rows) == 1 and rows[0]["gamePatch"] == "0.5.5"
    rows = query(service, old["buildFamilyKeys"][0], detail_level="record",
                 record_ids=[*old["recordIds"], *new["recordIds"]])["deepResearchRecords"]
    assert {row["gamePatch"] for row in rows} == {"0.5.4", "0.5.5"}
