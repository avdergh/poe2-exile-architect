from __future__ import annotations

import json

from scripts import apply_phase4_endpoint_decisions as decisions


RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "pobb.in/",
    "poe.ninja/",
)


def test_apply_endpoint_decisions_accepts_player_active_skill_endpoints_including_crossbow(
    tmp_path,
):
    review_path = tmp_path / "endpoint-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")

    report = decisions.build_reviewed_endpoint_mapping_report(
        input_report=review_path,
    )

    assert report["status"] == "endpoint_mapping_accepted"
    assert report["acceptedCount"] == 4
    assert report["pendingCount"] == 0
    assert report["semanticEdgeWrite"]["attempted"] is False

    by_sample = {item["sampleId"]: item for item in report["reviewItems"]}
    assert by_sample["phase4_user_pob_001"]["reviewStatus"] == "accepted"
    assert by_sample["phase4_user_pob_001"]["acceptedStableKey"] == "skill:HollowFocusPlayer"
    assert by_sample["phase4_user_pob_003"]["reviewStatus"] == "accepted"
    assert by_sample["phase4_user_pob_003"]["acceptedStableKey"] == "skill:MeleeCrossbowPlayer"
    assert (
        by_sample["phase4_user_pob_003"]["semanticEdgeActionAfterReview"]
        == "ready_for_researcher_semantic_review"
    )

    serialized = json.dumps(report, ensure_ascii=False)
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_apply_endpoint_decisions_rejects_unlisted_or_mismatched_stable_key(tmp_path):
    review_path = tmp_path / "endpoint-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")

    try:
        decisions.build_reviewed_endpoint_mapping_report(
            input_report=review_path,
            accepted_mappings={"phase4_user_pob_001": "skill:Wrong"},
            pending_samples={"phase4_user_pob_003"},
        )
    except ValueError as exc:
        assert "candidate" in str(exc)
    else:
        raise AssertionError("mismatched accepted stable key should be rejected")


def test_apply_endpoint_decisions_writes_safe_json_and_markdown(tmp_path):
    review_path = tmp_path / "endpoint-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")
    output_json = tmp_path / "reviewed.json"
    output_md = tmp_path / "reviewed.md"

    report = decisions.write_reviewed_endpoint_mapping_report(
        input_report=review_path,
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Reviewed Endpoint Mapping" in markdown
    assert "endpoint_mapping_accepted" in markdown
    assert "skill:MeleeCrossbowPlayer" in markdown
    assert "pending_manual_review" not in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def _review_report():
    return {
        "reportId": "phase4-endpoint-review-v1",
        "status": "needs_manual_endpoint_review",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "reviewItems": [
            _item(
                "phase4_user_pob_001",
                "Hollow Focus",
                "skill:HollowFocusPlayer",
                [
                    "gem:Metadata/Items/Gem/SkillGemAscendancyHollowFocus",
                    "skill:HollowFocusPlayer",
                ],
            ),
            _item(
                "phase4_user_pob_002",
                "Mirage Deadeye",
                "skill:MetaMirageDeadeyePlayer",
                [
                    "gem:Metadata/Items/Gem/SkillGemAscendancyMirageDeadeye",
                    "skill:MetaMirageDeadeyePlayer",
                ],
            ),
            _item(
                "phase4_user_pob_003",
                "Crossbow Shot",
                None,
                [
                    "gem:Metadata/Items/Gem/SkillGemPlayerDefaultCrossbow",
                    "skill:MeleeCrossbowPlayer",
                    "skill:MeleeCrossbowRogueExile",
                ],
            ),
            _item(
                "phase4_user_pob_004",
                "Vivid Stampede",
                "skill:VividStampedePlayer",
                [
                    "gem:Metadata/Items/Gem/SkillGemAscendancyVividStampede",
                    "skill:VividStampedePlayer",
                ],
            ),
        ],
    }


def _item(sample_id, candidate_name, recommended, candidates):
    return {
        "sampleId": sample_id,
        "candidateName": candidate_name,
        "resolverStatus": "ambiguous",
        "reviewStatus": "needs_manual_review",
        "recommendedStableKey": recommended,
        "acceptedStableKey": None,
        "requiresUserDecision": True,
        "semanticEdgeActionAfterReview": "blocked_until_review_acceptance",
        "candidates": [
            {
                "stableKey": stable_key,
                "nodeType": "active_skill" if stable_key.startswith("skill:") else "skill_gem",
                "sourceRefs": ["repoe:skills"]
                if stable_key.startswith("skill:")
                else ["repoe:skill_gems"],
            }
            for stable_key in candidates
        ],
    }
