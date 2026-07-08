from __future__ import annotations

import json

from scripts import apply_phase4_secondary_endpoint_decisions as decisions


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


def test_apply_secondary_endpoint_decisions_accepts_player_active_skill_backfill_keys(tmp_path):
    review_path = tmp_path / "secondary-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")

    report = decisions.build_reviewed_secondary_endpoint_mapping_report(
        input_report=review_path,
        accepted_mappings={
            "phase4_user_pob_001|Barrage": "skill:BarragePlayer",
            "phase4_user_pob_001|Whirling Slash": "skill:WhirlingSlashPlayer",
            "phase4_user_pob_002|Barrage": "skill:BarragePlayer",
            "phase4_user_pob_002|Pounce": "skill:WolfPouncePlayer",
            "phase4_user_pob_003|Escape Shot": "skill:EscapeShotPlayer",
            "phase4_user_pob_003|Mirage Archer": "skill:MetaMirageArcherPlayer",
            "phase4_user_pob_004|Wild Protector": "skill:WildProtectorPlayer",
            "phase4_user_pob_004|Herald of Thunder": "skill:HeraldOfThunderPlayer",
        },
    )

    assert report["status"] == "secondary_endpoint_mapping_accepted"
    assert report["acceptedCount"] == 8
    assert report["pendingCount"] == 0
    assert report["blockedPrimaryCount"] == 0
    assert report["semanticEdgeWrite"]["attempted"] is False

    by_name = {item["candidateName"]: item for item in report["reviewItems"]}
    assert by_name["Barrage"]["acceptedStableKey"] == "skill:BarragePlayer"
    assert by_name["Whirling Slash"]["acceptedStableKey"] == "skill:WhirlingSlashPlayer"
    assert by_name["Escape Shot"]["acceptedStableKey"] == "skill:EscapeShotPlayer"
    assert by_name["Mirage Archer"]["acceptedStableKey"] == "skill:MetaMirageArcherPlayer"
    assert by_name["Wild Protector"]["acceptedStableKey"] == "skill:WildProtectorPlayer"
    assert by_name["Wild Protector"]["primaryStableKey"] == "skill:VividStampedePlayer"
    assert by_name["Herald of Thunder"]["acceptedStableKey"] == "skill:HeraldOfThunderPlayer"
    assert all(
        item["semanticEdgeActionAfterReview"] == "ready_for_external_semantic_edge"
        for item in report["reviewItems"]
    )
    assert report["blockedPrimaryItems"] == []

    serialized = json.dumps(report, ensure_ascii=False)
    assert "skill:EscapeShotPlayer" in serialized
    assert not any(marker in serialized for marker in RAW_MARKERS)


def test_apply_secondary_endpoint_decisions_rejects_missing_candidate_key(tmp_path):
    review_path = tmp_path / "secondary-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")

    try:
        decisions.build_reviewed_secondary_endpoint_mapping_report(
            input_report=review_path,
            accepted_mappings={
                "phase4_user_pob_004|Wild Protector": "skill:Wrong",
            },
        )
    except ValueError as exc:
        assert "candidate" in str(exc)
    else:
        raise AssertionError("secondary accepted stable key must be a reviewed candidate")


def test_apply_secondary_endpoint_decisions_writes_safe_json_and_markdown(tmp_path):
    review_path = tmp_path / "secondary-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")
    output_json = tmp_path / "reviewed-secondary.json"
    output_md = tmp_path / "reviewed-secondary.md"

    report = decisions.write_reviewed_secondary_endpoint_mapping_report(
        input_report=review_path,
        accepted_mappings={
            "phase4_user_pob_004|Wild Protector": "skill:WildProtectorPlayer",
            "phase4_user_pob_004|Herald of Thunder": "skill:HeraldOfThunderPlayer",
        },
        json_output=output_json,
        md_output=output_md,
    )

    assert json.loads(output_json.read_text(encoding="utf-8")) == report
    markdown = output_md.read_text(encoding="utf-8")
    assert "Phase 4 Reviewed Secondary Endpoint Mapping" in markdown
    assert "Wild Protector" in markdown
    assert "Herald of Thunder" in markdown
    assert not any(marker in markdown for marker in RAW_MARKERS)


def test_apply_secondary_endpoint_decisions_cli_accepts_repeatable_mappings(tmp_path):
    review_path = tmp_path / "secondary-review.json"
    review_path.write_text(json.dumps(_review_report(), ensure_ascii=False), encoding="utf-8")
    output_json = tmp_path / "reviewed-secondary.json"
    output_md = tmp_path / "reviewed-secondary.md"

    exit_code = decisions.main(
        [
            "--input-report",
            str(review_path),
            "--json-output",
            str(output_json),
            "--md-output",
            str(output_md),
            "--accept",
            "phase4_user_pob_004|Wild Protector=skill:WildProtectorPlayer",
            "--accept",
            "phase4_user_pob_004|Herald of Thunder=skill:HeraldOfThunderPlayer",
        ]
    )

    assert exit_code == 0
    report = json.loads(output_json.read_text(encoding="utf-8"))
    assert report["acceptedCount"] == 8
    assert report["pendingCount"] == 0
    accepted_by_sample_and_name = {
        f"{item['sampleId']}|{item['candidateName']}": item["acceptedStableKey"]
        for item in report["reviewItems"]
    }
    assert accepted_by_sample_and_name == {
        "phase4_user_pob_001|Barrage": "skill:BarragePlayer",
        "phase4_user_pob_001|Whirling Slash": "skill:WhirlingSlashPlayer",
        "phase4_user_pob_002|Barrage": "skill:BarragePlayer",
        "phase4_user_pob_002|Pounce": "skill:WolfPouncePlayer",
        "phase4_user_pob_003|Escape Shot": "skill:EscapeShotPlayer",
        "phase4_user_pob_003|Mirage Archer": "skill:MetaMirageArcherPlayer",
        "phase4_user_pob_004|Wild Protector": "skill:WildProtectorPlayer",
        "phase4_user_pob_004|Herald of Thunder": "skill:HeraldOfThunderPlayer",
    }


def _review_report():
    return {
        "reportId": "phase4-secondary-endpoint-review-v1",
        "status": "needs_manual_secondary_endpoint_review",
        "safeArtifactOnly": True,
        "snapshotId": "physical-graph-fixture",
        "reviewItems": [
            _item(
                sample_id="phase4_user_pob_001",
                primary_key="skill:HollowFocusPlayer",
                candidate_name="Barrage",
                recommended=None,
                candidates=[
                    "gem:Metadata/Items/Gems/SkillGemBarrage",
                    "skill:BarragePlayer",
                    "skill:BarrageRogueExileRanger1",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_001",
                primary_key="skill:HollowFocusPlayer",
                candidate_name="Whirling Slash",
                recommended=None,
                candidates=[
                    "gem:Metadata/Items/Gems/SkillGemWhirlingSlash",
                    "skill:WhirlingSlashPlayer",
                    "skill:WhirlingSlashRogueExileHuntress1",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_002",
                primary_key="skill:MetaMirageDeadeyePlayer",
                candidate_name="Barrage",
                recommended=None,
                candidates=[
                    "gem:Metadata/Items/Gems/SkillGemBarrage",
                    "skill:BarragePlayer",
                    "skill:BarrageRogueExileRanger1",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_002",
                primary_key="skill:MetaMirageDeadeyePlayer",
                candidate_name="Pounce",
                recommended="skill:WolfPouncePlayer",
                candidates=[
                    "gem:Metadata/Items/Gems/SkillGemWolfPounce",
                    "skill:WolfPouncePlayer",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_003",
                primary_key="skill:MeleeCrossbowPlayer",
                candidate_name="Escape Shot",
                recommended=None,
                candidates=[
                    "gem:Metadata/Items/Gems/SkillGemEscapeShot",
                    "skill:EscapeShotPlayer",
                    "skill:EscapeShotRogueExileRanger1",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_003",
                primary_key="skill:MeleeCrossbowPlayer",
                candidate_name="Mirage Archer",
                recommended=None,
                candidates=[
                    "gem:Metadata/Items/Gem/SkillGemMirageArcher",
                    "skill:MetaMirageArcherPlayer",
                    "skill:MetaMirageArcherRogueExileHuntress2",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_004",
                primary_key="skill:VividStampedePlayer",
                candidate_name="Wild Protector",
                recommended="skill:WildProtectorPlayer",
                candidates=[
                    "gem:Metadata/Items/Gem/SkillGemWildProtector",
                    "skill:WildProtectorPlayer",
                ],
            ),
            _item(
                sample_id="phase4_user_pob_004",
                primary_key="skill:VividStampedePlayer",
                candidate_name="Herald of Thunder",
                recommended=None,
                candidates=[
                    "skill:HeraldOfThunderPlayer",
                    "skill:UniqueHeraldOfThunderPlayer",
                ],
            ),
        ],
        "blockedPrimaryItems": [],
    }


def _item(sample_id, primary_key, candidate_name, recommended, candidates):
    return {
        "sampleId": sample_id,
        "sampleEndpointStatus": "accepted",
        "primaryStableKey": primary_key,
        "candidateName": candidate_name,
        "candidateKind": "secondary_component",
        "resolverStatus": "ambiguous",
        "reviewStatus": "needs_manual_review",
        "recommendedStableKey": recommended,
        "acceptedStableKey": None,
        "requiresUserDecision": True,
        "semanticEdgeActionAfterReview": "blocked_until_secondary_review_acceptance",
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
