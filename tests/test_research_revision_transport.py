"""显式来源修订必须能够从公开深读到safeReview再到proposal，而不依赖DB编辑。"""

import json

from scripts import run_phase4_deep_review_acceptance as acceptance
from test_patch_reviews import seeded
from test_research_source_claims import _variant, _accept, _lane, SOURCE_A
from test_phase4_deep_review_acceptance import _write_review, _graph_service


def test_record_detail_supplies_exact_revision_binding(tmp_path):
    service, payload, first = seeded(tmp_path)
    resource = _variant(payload, record_kind="resource_engine", title="资源条件",
                        typed_payload={**payload["deep_research_records"][0]["typed_payload"], "resourceMechanisms": ["on_hit_recovery"]})
    _accept(service, resource)
    detail = next(row for row in _lane(service, first["buildFamilyKeys"][0], SOURCE_A)["deepResearchRecords"] if row["recordKind"] == "resource_engine")
    revised = _variant(resource, typed_payload={**resource["deep_research_records"][0]["typed_payload"], "resourceMechanisms": ["flask_recovery"]},
                       source_claim_revision={"knowledge_key": detail["knowledgeKey"], "record_id": detail["recordId"], "projection_hash": detail["projectionHash"]})
    result = _accept(service, revised)
    assert result["updatedRecordCount"] == 1


def test_safe_review_revision_is_preserved_in_proposal_and_error_paths(tmp_path):
    path = _write_review(tmp_path, include_deep_record=True, components=[{
        "candidateName": "Resolved Only", "componentKey": "skill:ResolvedOnlyPlayer",
        "role": "primary_damage", "resolverQuery": "Resolved Only",
    }])
    review = json.loads(path.read_text(encoding="utf-8"))
    revision = {"knowledgeKey": "rk-" + "a" * 20, "recordId": "drr-" + "b" * 16, "projectionHash": "c" * 64}
    review["deepResearchRecords"][0]["sourceClaimRevision"] = revision
    normalized = acceptance._deep_record_reviews(review)[0]
    expected = {"knowledge_key": revision["knowledgeKey"], "record_id": revision["recordId"], "projection_hash": revision["projectionHash"]}
    assert normalized["sourceClaimRevision"] == expected
    payload, _, _ = acceptance._build_deep_record_payload(
        graph_service=_graph_service(), review=review, reviewed_mappings={}, confirmed_review_components={},
        source_skill_resolutions={}, source_skill_manifest=None,
        version_context={"gamePatch": "0.5.4", "passiveTreeVersion": "0_5", "pobVersionOrCommit": "unknown"},
    )
    assert payload["deep_research_records"][0]["source_claim_revision"] == expected
