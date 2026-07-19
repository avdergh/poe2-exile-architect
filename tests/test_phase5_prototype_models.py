from __future__ import annotations

import base64
import copy
import zlib

from server.compute.pob_code import encode_code
from server.generation import prototype


def version_context() -> dict[str, str]:
    return {
        "league": "Dawn of the Hunt",
        "ruleset": "softcore_trade",
        "game_patch": "0.5.4",
        "passive_tree_version": "0_5",
        "pob_version_or_commit": "unknown",
        "graph_snapshot_id": "snapshot:phase5",
        "research_memory_ref": "dq-0123456789abcdef",
    }


def agent_submission_payload() -> dict[str, object]:
    return {
        "packet_id": "human-review:prototype:1",
        "agentRefinedBuildPrompt": {
            "prompt_id": "prompt:1",
            "request_ref": "request:starter-high-ceiling",
            "user_request_summary": (
                "用户想要开荒顺畅，后期同职业洗点转攻坚和终局上限较高的 BD；当前只要开荒阶段。"
            ),
            "refined_prompt_summary": ("围绕同一职业设计开荒阶段，并保留后期攻坚/终局转型目标。"),
            "current_output_stages": ["campaign_late", "maps_entry"],
            "target_lifecycle_stages": [
                "campaign_late",
                "maps_entry",
                "budget_endgame",
                "final_endgame",
            ],
            "cross_stage_locked_dimensions": ["class"],
            "field_sources": {
                "user_request_summary": "user_explicit",
                "current_output_stages": "user_explicit",
                "target_lifecycle_stages": "agent_inferred",
                "cross_stage_locked_dimensions": "defaulted",
                "refined_prompt_summary": "agent_inferred",
            },
            "default_assumptions": ["trade league", "low initial budget"],
            "clarification_questions": [],
            "unresolved_items": ["No main skill hard-lock from user."],
            "version_context": version_context(),
            "no_raw_material": True,
        },
        "prototypeBuildCandidate": {
            "candidate_id": "candidate:starter-shell:1",
            "prompt_ref": "prompt:1",
            "current_output_stages": ["campaign_late", "maps_entry"],
            "target_lifecycle_stages": [
                "campaign_late",
                "maps_entry",
                "budget_endgame",
                "final_endgame",
            ],
            "cross_stage_locked_dimensions": ["class"],
            "class_shell": "Ranger-class starter shell; ascendancy can be changed later.",
            "primary_skill_intent": "Projectile attack clear skill chosen by Agent after querying tools.",
            "secondary_skill_intents": ["single-target swap candidate remains unresolved"],
            "mechanic_axes": ["projectile scaling", "weapon damage", "attack speed"],
            "defense_layers": ["life", "evasion", "elemental resistance cap"],
            "spirit_assumptions": ["avoid reservation-heavy setup before gear stabilizes"],
            "gear_roles": ["rare weapon role", "life/resistance rare armour roles"],
            "passive_anchor_intents": ["Ranger projectile and life/evasion area"],
            "transition_gates": ["同职业转型；允许洗点、换技能、换装备和洗升华，不能换职业。"],
            "unresolved_caveats": ["No transient PoB state has been assembled yet."],
            "tool_references": [
                {
                    "tool_name": "get_freshness_report",
                    "query_ref": "freshness:phase5:test",
                    "summary": "Freshness probe completed for the current run.",
                },
                {
                    "tool_name": "query_research_memory",
                    "query_ref": "dq-0123456789abcdef",
                    "summary": "Found starter projectile advisory patterns.",
                },
            ],
            "memory_references": [
                "dq-0123456789abcdef",
                "bf-1234567890abcdef",
                "drr-1234567890abcdef",
                "bdp-1234567890abcdef",
            ],
            "research_memory_use": {
                "retrieval_outcome": "matched",
                "dedupe_query_refs": ["dq-0123456789abcdef"],
                "component_keys": [
                    "ascendancy:ranger:deadeye",
                    "skill:LightningArrowPlayer",
                ],
                "build_family_keys": ["bf-1234567890abcdef"],
                "deep_record_ids": ["drr-1234567890abcdef"],
                "pattern_ids": ["bdp-1234567890abcdef"],
                "semantic_edge_ids": [],
                "memory_item_ids": [],
                "insight_decisions": [
                    {
                        "source_refs": [
                            "drr-1234567890abcdef",
                            "bdp-1234567890abcdef",
                        ],
                        "decision": "adopted",
                        "summary": "投射物清图壳需要独立保留单体兑现方案。",
                        "application": "候选保留单体技能组并交给 PoB/Judge 分别验证。",
                    }
                ],
                "no_match_reason": None,
            },
            "rationale_summary": ("职业先服务后期上限，开荒阶段只保留低成本、低复杂度的机制。"),
            "version_context": version_context(),
            "no_raw_material": True,
        },
        "transientBuildState": {
            "status": "missing",
            "snapshot_id": None,
            "source_hash": None,
            "safe_summary": {},
            "missing_reasons": ["Agent has not assembled an evaluable PoB state yet."],
            "version_context": version_context(),
            "no_raw_material": True,
        },
        "judgeAdvisoryReport": {
            "report_id": "judge:not-evaluated:1",
            "status": "not_evaluated",
            "hard_failures": [],
            "caveats": ["No transient build state was provided."],
            "reward_strength": "unknown",
            "version_context": version_context(),
            "no_raw_material": True,
        },
    }


def test_agent_led_prototype_submission_builds_safe_human_review_packet():
    result = prototype.validate_and_build_human_review_packet(agent_submission_payload())

    assert result["status"] == "accepted"
    packet = result["humanReviewPacket"]
    assert packet["agentRefinedBuildPrompt"]["crossStageLockedDimensions"] == ["class"]
    assert packet["prototypeBuildCandidate"]["currentOutputStages"] == [
        "campaign_late",
        "maps_entry",
    ]
    assert packet["prototypeBuildCandidate"]["researchMemoryUse"]["retrievalOutcome"] == ("matched")
    assert packet["prototypeBuildCandidate"]["researchMemoryUse"]["deepRecordIds"] == [
        "drr-1234567890abcdef"
    ]
    assert packet["judgeAdvisoryReport"]["status"] == "not_evaluated"
    assert packet["recommendedNextAction"] == "human_review_required"
    assert packet["humanReviewFields"]["briefFit"] == "pending"
    assert packet["humanReviewFields"]["designValue"] == "pending"
    assert packet["noRawMaterial"] is True
    assert packet["noHiddenChainOfThought"] is True


def test_candidate_requires_agent_query_or_memory_evidence():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["tool_references"] = []
    payload["prototypeBuildCandidate"]["memory_references"] = []
    payload["prototypeBuildCandidate"]["research_memory_use"] = None

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_evidence_references"


def test_candidate_rejects_untraceable_research_memory_decision():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["research_memory_use"]["insight_decisions"][0][
        "source_refs"
    ] = ["drr-not-recalled"]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def test_candidate_derives_denormalized_memory_references_from_typed_usage():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["memory_references"] = []

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"
    assert result["humanReviewPacket"]["prototypeBuildCandidate"]["memoryReferences"] == [
        "dq-0123456789abcdef",
        "bf-1234567890abcdef",
        "drr-1234567890abcdef",
        "bdp-1234567890abcdef",
    ]


def test_not_evaluated_judge_requires_clear_missing_state_reason():
    payload = agent_submission_payload()
    payload["transientBuildState"]["missing_reasons"] = []

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_not_evaluated_reason"


def test_prototype_safety_rejects_hidden_reasoning_and_raw_build_material():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["chain_of_thought"] = "private reasoning"

    hidden_result = prototype.validate_and_build_human_review_packet(payload)

    assert hidden_result["status"] == "rejected"
    assert hidden_result["errorCode"] == "unsafe_reasoning_material"

    payload = agent_submission_payload()
    payload["transientBuildState"]["safe_summary"] = {
        "rawXml": "<PathOfBuilding><Build></Build></PathOfBuilding>"
    }

    raw_result = prototype.validate_and_build_human_review_packet(payload)

    assert raw_result["status"] == "rejected"
    assert raw_result["errorCode"] == "copy_safety_violation"


def test_prototype_safety_rejects_hidden_reasoning_label_inside_text_value():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["rationale_summary"] = (
        "chain_of_thought: hidden intermediate reasoning"
    )

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "unsafe_reasoning_material"


def test_prototype_safety_redacts_unsafe_hidden_reasoning_paths():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["https://pobb.in/abcd_chain_of_thought"] = "private"

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "unsafe_reasoning_material"
    assert "pobb.in" not in " ".join(result["caveats"])


def test_prototype_safety_rejects_raw_prompt_key_inside_nested_maps():
    payload = agent_submission_payload()
    payload["transientBuildState"]["safe_summary"] = {"rawPrompt": "copy of original request"}

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "unsafe_reasoning_material"


def test_prototype_safety_rejects_raw_pob_import_code_embedded_in_text():
    payload = agent_submission_payload()
    raw_code = encode_code("<PathOfBuilding2><Build></Build></PathOfBuilding2>")
    payload["prototypeBuildCandidate"]["unresolved_caveats"].append(
        f"temporary import material {raw_code}"
    )

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "copy_safety_violation"


def test_prototype_safety_rejects_non_max_compression_pob_import_code():
    payload = agent_submission_payload()
    xml = "<PathOfBuilding2><Build></Build></PathOfBuilding2>"
    raw_code = base64.urlsafe_b64encode(zlib.compress(xml.encode(), level=6)).decode()
    assert raw_code.startswith("eJ")
    payload["prototypeBuildCandidate"]["unresolved_caveats"].append(
        f"temporary import material {raw_code}"
    )

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "copy_safety_violation"


def test_prototype_helper_allows_agent_generated_complete_skill_and_gear_summaries():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["primary_skill_intent"] = (
        "Use Skeletal Storm Mage with Martial Tempo / Minion Mastery / Lightning Infusion / "
        "Elemental Focus / Persistence as the tested starter package."
    )
    payload["prototypeBuildCandidate"]["secondary_skill_intents"] = [
        "Skeletal Cleric / Last Gasp / Ingenuity / Feeding Frenzy for uptime and recovery.",
        "Use Flame Wall -> Orb of Storms -> Conductivity only as optional player-cast utility.",
    ]
    payload["prototypeBuildCandidate"]["gear_roles"] = [
        "Weapon - Rare sceptre with minion level, Spirit, and minion damage priorities.",
        "Helmet - Rare ES base with life, energy shield, and two resistance suffixes.",
        "Boots - Rare boots with movement speed, life, and missing resistance.",
    ]
    payload["prototypeBuildCandidate"]["passive_anchor_intents"] = [
        "Witch start -> Raw Power -> Pure Energy -> nearby minion damage wheel -> jewel socket."
    ]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"


def test_prototype_helper_allows_specific_unique_or_slot_summary_when_agent_generated():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["gear_roles"] = [
        "helmet: Goldrim",
        "belt: Headhunter",
        "ring 1: Kikazaru",
    ]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"


def test_prototype_safety_rejects_raw_query_like_tool_references():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["tool_references"][0]["query_ref"] = "MATCH (n) RETURN n"

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "raw_query_violation"


def test_public_camel_case_agent_payload_is_accepted():
    payload = _camelize(copy.deepcopy(agent_submission_payload()))

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"
    packet = result["humanReviewPacket"]
    assert packet["agentRefinedBuildPrompt"]["currentOutputStages"] == [
        "campaign_late",
        "maps_entry",
    ]
    assert packet["prototypeBuildCandidate"]["targetLifecycleStages"] == [
        "campaign_late",
        "maps_entry",
        "endgame_budget",
        "endgame_final",
    ]


def test_stage_contract_keeps_class_as_only_cross_stage_lock():
    payload = agent_submission_payload()
    payload["agentRefinedBuildPrompt"]["cross_stage_locked_dimensions"] = ["class", "ascendancy"]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def test_lifecycle_targets_must_cover_current_output_stages():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["target_lifecycle_stages"] = ["campaign_late"]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def test_candidate_stages_must_match_refined_prompt_stages():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["current_output_stages"] = ["final_endgame"]
    payload["prototypeBuildCandidate"]["target_lifecycle_stages"] = ["final_endgame"]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def test_candidate_rejects_obvious_cross_stage_class_change_contradiction():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["transition_gates"] = [
        "After campaign, switch class into a Warrior endgame shell."
    ]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_class_lifecycle_contract"


def test_candidate_accepts_natural_language_class_lock_statement():
    payload = agent_submission_payload()
    payload["prototypeBuildCandidate"]["transition_gates"] = [
        "职业不能更换；后期可以洗升华、技能、天赋和装备。"
    ]

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"


def test_agent_reported_judge_result_still_requires_human_review():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:1",
        "source_hash": "sha256:abc123",
        "safe_summary": {
            "class": "Ranger",
            "stage": "maps_entry",
            "main_skill": "Agent-selected projectile skill",
        },
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Lightning Arrow",
                "supports": ["Martial Tempo", "Lightning Infusion"],
                "enabled": True,
            }
        ],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:evaluated:1",
        "status": "evaluated",
        "hard_failures": [],
        "caveats": ["projectile overlap remains limited evidence"],
        "aggregate_score": 0.42,
        "reward_strength": "limited",
        "evaluated_snapshot_id": "snapshot:runtime:starter:1",
        "evaluated_source_hash": "sha256:abc123",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"
    packet = result["humanReviewPacket"]
    assert packet["recommendedNextAction"] == "human_review_required"
    assert packet["transientBuildState"]["snapshotId"] == "snapshot:runtime:starter:1"
    assert packet["transientBuildState"]["testedSkillGroups"][0]["activeSkill"] == (
        "Lightning Arrow"
    )
    assert packet["judgeAdvisoryReport"]["aggregateScore"] == 0.42
    assert packet["judgeAdvisoryReport"]["evaluatedSourceHash"] == "sha256:abc123"


def test_evaluated_judge_report_must_bind_to_transient_state_hash():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:1",
        "source_hash": "sha256:abc123",
        "safe_summary": {"class": "Ranger"},
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Lightning Arrow",
                "supports": ["Martial Tempo"],
                "enabled": True,
            }
        ],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:evaluated:mismatch",
        "status": "evaluated",
        "hard_failures": [],
        "caveats": ["hash mismatch should be rejected"],
        "aggregate_score": 0.42,
        "reward_strength": "limited",
        "evaluated_snapshot_id": "snapshot:runtime:other",
        "evaluated_source_hash": "sha256:other",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "judge_state_mismatch"


def test_unevaluated_judge_report_cannot_carry_score_or_reward_signal():
    payload = agent_submission_payload()
    payload["judgeAdvisoryReport"]["aggregate_score"] = 0.5

    score_result = prototype.validate_and_build_human_review_packet(payload)

    assert score_result["status"] == "rejected"
    assert score_result["errorCode"] == "invalid_schema"

    payload = agent_submission_payload()
    payload["judgeAdvisoryReport"]["reward_strength"] = "limited"

    reward_result = prototype.validate_and_build_human_review_packet(payload)

    assert reward_result["status"] == "rejected"
    assert reward_result["errorCode"] == "invalid_schema"


def test_evaluated_judge_report_score_is_bounded_and_cannot_claim_strong_reward():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:1",
        "source_hash": "sha256:abc123",
        "safe_summary": {"class": "Ranger"},
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Lightning Arrow",
                "supports": ["Martial Tempo"],
                "enabled": True,
            }
        ],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:evaluated:bad-score",
        "status": "evaluated",
        "hard_failures": [],
        "caveats": ["synthetic score should be rejected"],
        "aggregate_score": 999.0,
        "reward_strength": "limited",
        "evaluated_snapshot_id": "snapshot:runtime:starter:1",
        "evaluated_source_hash": "sha256:abc123",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    score_result = prototype.validate_and_build_human_review_packet(payload)

    assert score_result["status"] == "rejected"
    assert score_result["errorCode"] == "invalid_schema"

    payload["judgeAdvisoryReport"]["aggregate_score"] = 0.9
    payload["judgeAdvisoryReport"]["reward_strength"] = "strong"

    reward_result = prototype.validate_and_build_human_review_packet(payload)

    assert reward_result["status"] == "rejected"
    assert reward_result["errorCode"] == "invalid_schema"


def test_evaluated_judge_report_requires_score_and_state_ref():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:1",
        "source_hash": "sha256:abc123",
        "safe_summary": {"class": "Ranger"},
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Lightning Arrow",
                "supports": ["Martial Tempo"],
                "enabled": True,
            }
        ],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:evaluated:missing-score",
        "status": "evaluated",
        "hard_failures": [],
        "caveats": ["missing score should be rejected"],
        "reward_strength": "limited",
        "evaluated_snapshot_id": "snapshot:runtime:starter:1",
        "evaluated_source_hash": "sha256:abc123",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    score_result = prototype.validate_and_build_human_review_packet(payload)

    assert score_result["status"] == "rejected"
    assert score_result["errorCode"] == "invalid_schema"

    payload["judgeAdvisoryReport"]["aggregate_score"] = 0.4
    del payload["judgeAdvisoryReport"]["evaluated_source_hash"]

    state_ref_result = prototype.validate_and_build_human_review_packet(payload)

    assert state_ref_result["status"] == "rejected"
    assert state_ref_result["errorCode"] == "invalid_schema"


def test_error_transient_state_requires_missing_reason():
    payload = agent_submission_payload()
    payload["transientBuildState"]["status"] = "error"
    payload["transientBuildState"]["missing_reasons"] = []
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:not-evaluated:no-state",
        "status": "not_evaluated",
        "hard_failures": [],
        "caveats": ["No transient state was available for Judge."],
        "reward_strength": "unknown",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "missing_transient_state_reason"


def test_judge_invocation_error_is_human_review_required_not_build_blocker():
    payload = agent_submission_payload()
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:error:timeout",
        "status": "error",
        "hard_failures": [],
        "caveats": ["Judge timed out before producing an evaluation."],
        "reward_strength": "unknown",
        "error_code": "judge_timeout",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"
    packet = result["humanReviewPacket"]
    assert packet["judgeAdvisoryReport"]["errorCode"] == "judge_timeout"
    assert packet["recommendedNextAction"] == "human_review_required"


def test_available_transient_state_can_be_not_evaluated_when_judge_was_not_run():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:not-judged",
        "source_hash": "sha256:notjudged",
        "safe_summary": {
            "class": "Witch",
            "stage": "maps_entry",
            "computed_mana_cost": "159",
        },
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Flame Wall",
                "supports": ["Magnified Effect", "Fire Penetration"],
                "enabled": True,
            },
            {
                "role": "persistent_damage",
                "active_skill": "Raging Spirits",
                "supports": ["Minion Mastery"],
                "enabled": True,
            },
        ],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:not-run:available-state",
        "status": "not_evaluated",
        "hard_failures": [],
        "caveats": ["Formal Judge was not run for this transient state."],
        "reward_strength": "unknown",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "accepted"
    packet = result["humanReviewPacket"]
    assert packet["judgeAdvisoryReport"]["status"] == "not_evaluated"
    assert packet["recommendedNextAction"] == "human_review_required"


def test_available_transient_state_requires_actual_tested_skill_groups():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:missing-skills",
        "source_hash": "sha256:missingskills",
        "safe_summary": {"class": "Witch", "main_skill": "Flame Wall with light supports"},
        "tested_skill_groups": [],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:not-run:missing-skills",
        "status": "not_evaluated",
        "hard_failures": [],
        "caveats": ["Formal Judge was not run."],
        "reward_strength": "unknown",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def test_tested_skill_group_requires_explicit_supports_and_enabled_state():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "available",
        "snapshot_id": "snapshot:runtime:starter:incomplete-skill-group",
        "source_hash": "sha256:incompleteskillgroup",
        "safe_summary": {"class": "Witch"},
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Flame Wall",
            }
        ],
        "missing_reasons": [],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:not-run:incomplete-skill-group",
        "status": "not_evaluated",
        "hard_failures": [],
        "caveats": ["Formal Judge was not run."],
        "reward_strength": "unknown",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def test_judge_error_requires_error_code_and_cannot_claim_build_hard_failure():
    payload = agent_submission_payload()
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:error:no-code",
        "status": "error",
        "hard_failures": [],
        "caveats": ["Judge process exited unexpectedly."],
        "reward_strength": "unknown",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    missing_code = prototype.validate_and_build_human_review_packet(payload)

    assert missing_code["status"] == "rejected"
    assert missing_code["errorCode"] == "invalid_schema"

    payload["judgeAdvisoryReport"]["error_code"] = "judge_process_error"
    payload["judgeAdvisoryReport"]["hard_failures"] = ["low_life"]

    hard_failure = prototype.validate_and_build_human_review_packet(payload)

    assert hard_failure["status"] == "rejected"
    assert hard_failure["errorCode"] == "invalid_schema"


def test_non_available_transient_state_cannot_carry_snapshot_or_tested_skill_groups():
    payload = agent_submission_payload()
    payload["transientBuildState"] = {
        "status": "error",
        "snapshot_id": "snapshot:should-not-exist",
        "source_hash": "sha256:shouldnotexist",
        "safe_summary": {},
        "tested_skill_groups": [
            {
                "role": "main_damage",
                "active_skill": "Flame Wall",
                "supports": [],
                "enabled": True,
            }
        ],
        "missing_reasons": ["PoB state assembly failed."],
        "version_context": version_context(),
        "no_raw_material": True,
    }
    payload["judgeAdvisoryReport"] = {
        "report_id": "judge:not-evaluated:no-state",
        "status": "not_evaluated",
        "hard_failures": [],
        "caveats": ["No transient state was available for Judge."],
        "reward_strength": "unknown",
        "version_context": version_context(),
        "no_raw_material": True,
    }

    result = prototype.validate_and_build_human_review_packet(payload)

    assert result["status"] == "rejected"
    assert result["errorCode"] == "invalid_schema"


def _camelize(value):
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {_snake_to_camel(str(key)): _camelize(child) for key, child in value.items()}


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])
