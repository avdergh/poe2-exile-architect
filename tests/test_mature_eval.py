from __future__ import annotations

from server.knowledge import mature_eval


def test_creator_input_rejects_evaluator_only_and_raw_material():
    creator_input = {
        "goal": "给我一个强力 BD",
        "evidence": [
            {"visibility": "creator_visible", "split": "train_context", "summary": "safe"},
            {"visibility": "evaluator_only", "split": "eval_holdout", "summary": "holdout"},
        ],
        "pobCode": "eNrt" + "A" * 180,
    }

    result = mature_eval.validate_creator_research_input(creator_input)

    assert result["ok"] is False
    assert result["error"] == "creator_input_contamination"
    assert "evaluator_only" in result["flags"]
    assert "eval_holdout" in result["flags"]
    assert "raw_pob_code" in result["flags"]


def test_creator_input_rejects_quarantined_and_copyable_text():
    creator_input = {
        "evidence": [{"visibility": "quarantined", "split": "quarantine"}],
        "summary": "Supports: A, B, C, D, E",
    }

    result = mature_eval.validate_creator_research_input(creator_input)

    assert result["ok"] is False
    assert {"quarantined", "quarantine", "full_support_link_like"} <= set(result["flags"])


def test_creator_input_accepts_creator_visible_sanitized_context():
    creator_input = {
        "goal": "给我一个强力 BD",
        "evidence": [
            {
                "visibility": "creator_visible",
                "split": "train_context",
                "summary": "coarse lightning caster technique",
            }
        ],
    }

    assert mature_eval.validate_creator_research_input(creator_input) == {"ok": True}


def test_validate_evaluator_gap_accepts_known_gap():
    gap = {
        "gapType": "missing_core_mechanism",
        "severity": "high",
        "evidence": "held-out evidence indicates a missing scaling identity",
        "fixIdea": "add a non-copyable mechanism card candidate",
    }

    assert mature_eval.validate_evaluator_gap(gap) == {
        "ok": True,
        "gapType": "missing_core_mechanism",
        "severity": "high",
    }


def test_validate_evaluator_gap_rejects_unknown_type_or_severity():
    bad_type = {
        "gapType": "copied_exact_tree",
        "severity": "high",
        "evidence": "unsafe",
        "fixIdea": "reject",
    }
    bad_severity = {
        "gapType": "defense_gap",
        "severity": "urgent",
        "evidence": "missing defense",
        "fixIdea": "add defense gate",
    }

    assert mature_eval.validate_evaluator_gap(bad_type)["error"] == "invalid_gap_type"
    assert mature_eval.validate_evaluator_gap(bad_severity)["error"] == "invalid_gap_severity"
    assert "copied_exact_tree" not in str(mature_eval.validate_evaluator_gap(bad_type))


def test_validate_evaluator_gap_handles_unhashable_enum_values_without_raising():
    result = mature_eval.validate_evaluator_gap(
        {
            "gapType": ["defense_gap"],
            "severity": {"level": "high"},
            "evidence": "missing defense",
            "fixIdea": "add defense gate",
        }
    )

    assert result["ok"] is False
    assert result["error"] == "invalid_gap_type"


def test_validate_evaluator_gap_rejects_copyable_gap_content():
    gap = {
        "gapType": "copyability_risk",
        "severity": "critical",
        "evidence": "eNrt" + "A" * 180,
        "fixIdea": "remove raw code",
    }

    result = mature_eval.validate_evaluator_gap(gap)

    assert result["ok"] is False
    assert result["error"] == "gap_copyability_risk"


def test_creator_input_rejects_raw_payload_variants_short_links_and_slot_gear_text():
    creator_input = {
        "goal": "给我一个强力 BD",
        "rawPayload": {"must": "not enter creator"},
        "summary": "https://pobb.in/abc123\nRing 1: exact copied rare ring",
    }

    result = mature_eval.validate_creator_research_input(creator_input)

    assert result["ok"] is False
    assert "raw_copyable_field" in result["flags"]
    assert "raw_pob_code" in result["flags"]
    assert "slot_exact_gear_like" in result["flags"]


def test_creator_input_rejects_copyable_dict_keys_support_lists_and_passive_paths():
    creator_input = {
        "goal": "给我一个强力 BD",
        "notes": {
            "https://pobb.in/abc123": "safe-looking value",
            "supportPlan": "Support gems: A, B, C, D, E",
            "treePlan": "Passive path: 1 -> 2 -> 3 -> 4 -> 5",
        },
    }

    result = mature_eval.validate_creator_research_input(creator_input)

    assert result["ok"] is False
    assert "copyable_build_link" in result["flags"]
    assert "raw_pob_code" in result["flags"]
    assert "full_support_link_like" in result["flags"]
    assert "ordered_passive_path" in result["flags"]
    assert "abc123" not in str(result)
