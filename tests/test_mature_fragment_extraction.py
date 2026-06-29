from __future__ import annotations

from server.knowledge import mature_fragment_extraction


def _valid_output(**overrides):
    base = {
        "schemaVersion": 3,
        "fragments": [
            {
                "fragmentType": "mechanic",
                "title": "Lightning projectile crit scaling shell",
                "summary": "Uses projectile spell coverage plus crit and shock scaling as an endgame identity.",
                "sourceCaseRefs": ["case-safe-spark"],
                "confidence": "medium",
                "copyabilityRisk": "low",
                "evidenceRefs": ["case-safe-spark"],
                "componentNames": ["Spark", "Stormweaver"],
                "conditions": ["requires stable crit and endgame passive budget"],
                "risks": ["damage and sustain may be weak before crit foundation"],
                "modelability": "partial",
                "reusablePrinciple": "Treat high-frequency projectile spell shells as scaling platforms, not full build recipes.",
                "verificationTasks": ["Compare crit foundation against current patch PoB output."],
                "notes": ["main skill plus damage and coverage support roles; no full link list"],
            }
        ],
    }
    base.update(overrides)
    return base


def _raw_case(**overrides):
    base = {
        "safeMetadata": {
            "case_id": "case-safe-spark",
            "class": "Sorceress",
            "ascendancy": "Stormweaver",
            "mainSkill": "Spark",
            "league": "Runes of Aldur",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "keypoints": ["Endgame lightning caster scaling fixture."],
        },
        "rawContext": {
            "pobCode": "eNrt" + "A" * 180,
            "gear": {"Weapon": {"name": "Example staff"}},
            "skillGroups": {"main": ["Spark", "Support A"]},
            "passiveTree": {"nodes": [1, 2, 3]},
            "pageText": "Raw forum guide prose.",
        },
    }
    base.update(overrides)
    return base


def test_normalize_extractor_case_accepts_raw_rich_input():
    result = mature_fragment_extraction.normalize_extractor_case(_raw_case())

    assert result["ok"] is True
    assert result["extractorCase"]["caseRef"] == "case-safe-spark"
    assert result["extractorCase"]["rawContext"]["pobCode"].startswith("eNrt")


def test_normalize_extractor_case_rejects_copyable_safe_metadata_fields():
    result = mature_fragment_extraction.normalize_extractor_case(
        _raw_case(safeMetadata={"case_id": "x", "pobCode": "eNrt" + "A" * 180})
    )

    assert result["ok"] is False
    assert result["error"] == "copyable_safe_metadata_field"


def test_build_fragment_prompt_package_is_agent_research_brief_not_single_question():
    package = mature_fragment_extraction.build_fragment_prompt_package(
        _raw_case(),
        user_language="zh-CN",
    )

    text = "\n".join(str(message["content"]) for message in package["messages"])
    assert package["ok"] is True
    assert package["schemaVersion"] == 3
    assert "schemaVersion" in text
    assert '"schemaVersion": 3' in text
    assert "rawContext" in text
    assert "pobCode" in text
    assert "Simplified Chinese" in text
    assert "sample fact inventory" in text
    assert "core mechanism" in text
    assert "reusable principle" in text
    assert "endgame-only" in text
    assert "starter risk" in text
    assert "transition gate" in text
    assert "failure mode" in text
    assert "PoB modelability" in text
    assert "verification task" in text
    assert "What reusable fragments can be extracted" not in text


def test_validate_fragment_extraction_accepts_non_copyable_output():
    result = mature_fragment_extraction.validate_fragment_extraction_output(_valid_output())

    assert result == {
        "ok": True,
        "schemaVersion": 3,
        "fragmentCount": 1,
        "extractionMethod": "agent_mature_fragment_v3",
    }


def test_validate_fragment_extraction_requires_reusable_principle_and_verification_tasks():
    payload = _valid_output()
    del payload["fragments"][0]["reusablePrinciple"]

    missing_principle = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    payload = _valid_output()
    payload["fragments"][0]["verificationTasks"] = []

    missing_tasks = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert missing_principle["ok"] is False
    assert missing_principle["error"] == "fragment_missing_required_fields"
    assert missing_tasks["ok"] is False
    assert missing_tasks["error"] == "invalid_verificationTasks"


def test_validate_fragment_extraction_allows_sparse_optional_fields():
    payload = {
        "schemaVersion": 3,
        "fragments": [
            {
                "fragmentType": "transition_gate",
                "title": "Switch after crit foundation",
                "summary": "Only switch once the crit package is online.",
                "sourceCaseRefs": ["case-safe-spark"],
                "confidence": "low",
                "copyabilityRisk": "low",
                "reusablePrinciple": "Do not switch into a crit shell until its enabling package exists.",
                "verificationTasks": ["Check crit chance and sustain on the target patch."],
            }
        ],
    }

    result = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert result["ok"] is True


def test_validate_fragment_extraction_rejects_v2_output():
    payload = _valid_output(schemaVersion=2)

    result = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "unsupported_schema_version"


def test_validate_fragment_extraction_rejects_raw_copyable_fields():
    payload = _valid_output(pobCode="eNrt" + "A" * 180)

    result = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyable_output_field"


def test_validate_fragment_extraction_rejects_recipe_like_output():
    payload = _valid_output()
    payload["fragments"][0]["summary"] = "Supports: A, B, C, D, E"

    result = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"


def test_validate_fragment_extraction_rejects_missing_required_fields():
    payload = _valid_output()
    del payload["fragments"][0]["title"]

    result = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "fragment_missing_required_fields"


def test_validate_fragment_extraction_rejects_high_copyability_risk():
    payload = _valid_output()
    payload["fragments"][0]["copyabilityRisk"] = "high"

    result = mature_fragment_extraction.validate_fragment_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "high_copyability_risk"


def test_validate_report_markdown_rejects_recipe_like_content():
    result = mature_fragment_extraction.validate_fragment_report_markdown(
        "Main build\nSupports: A, B, C, D, E"
    )

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"


def test_validate_report_markdown_accepts_mechanism_level_exact_names():
    result = mature_fragment_extraction.validate_fragment_report_markdown(
        "Spark + Stormweaver forms a high-frequency crit and shock shell."
    )

    assert result == {"ok": True}
