from __future__ import annotations

from server.knowledge import mature_llm_extraction


def _valid_output(**overrides):
    base = {
        "schemaVersion": 1,
        "sourceCaseId": "case-safe-spark",
        "league": "Runes of Aldur",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "techniques": [
            {
                "techniqueName": "Lightning projectile crit scaling shell",
                "mechanismSummary": (
                    "Uses projectile spell coverage plus crit and shock scaling as an endgame identity."
                ),
                "whyItWorks": (
                    "Coverage handles clear while crit and ailment scaling concentrate investment for bosses."
                ),
                "requiredComponents": ["projectile spell", "crit foundation", "shock scaling"],
                "thresholdsOrBreakpoints": ["requires stable crit and endgame passive budget"],
                "lifecycleApplicability": "starter_then_transition",
                "starterRisks": ["damage and sustain may be weak before crit foundation"],
                "transitionGates": [
                    "switch only after first endgame gear/passive package is online"
                ],
                "skillLinksSummary": "main skill plus damage and coverage supports; no full link list",
                "passiveTreeAnchors": ["projectile spell cluster family", "crit cluster family"],
                "gearOrUniqueRoles": ["gear provides scaling roles, no full item table"],
                "defensePlan": "energy shield and recovery identity",
                "pobModelability": "partial",
                "evidenceRefs": ["case-safe-spark"],
                "confidence": "medium",
                "copyabilityRisk": "low",
            }
        ],
    }
    base.update(overrides)
    return base


def test_validate_llm_extraction_accepts_non_copyable_output():
    result = mature_llm_extraction.validate_llm_extraction_output(_valid_output())

    assert result == {
        "ok": True,
        "schemaVersion": 1,
        "sourceCaseId": "case-safe-spark",
        "techniqueCount": 1,
        "extractionMethod": "llm_mature_technique_v1",
    }


def test_validate_llm_extraction_requires_patch_tree_and_evidence_scope():
    payload = _valid_output(gamePatch="", passiveTreeVersion="")
    payload["techniques"][0]["evidenceRefs"] = []

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "top_level_missing_required_fields"
    assert result["missing"] == ["gamePatch", "passiveTreeVersion"]


def test_validate_llm_extraction_rejects_raw_copyable_fields():
    payload = _valid_output(
        pobCode="eNrt" + "A" * 180,
        passiveTree={"nodes": [1, 2, 3]},
        gear={"Ring 1": "Exact copied item"},
    )

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyable_output_field"
    assert {"pobCode", "passiveTree", "gear"} <= set(result["paths"])


def test_validate_llm_extraction_rejects_pob_code_like_output():
    payload = _valid_output()
    payload["techniques"][0]["whyItWorks"] = "eNrt" + "A" * 180

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "pob_code_like_blob" in result["flags"]


def test_validate_llm_extraction_rejects_full_support_link_like_output():
    payload = _valid_output()
    payload["techniques"][0]["skillLinksSummary"] = "Supports: A, B, C, D, E"

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "full_support_link_like" in result["flags"]


def test_validate_llm_extraction_rejects_short_build_links_and_gem_link_variants():
    short_link = _valid_output()
    short_link["techniques"][0]["whyItWorks"] = "See https://pobb.in/abc123"
    dash_link = _valid_output()
    dash_link["techniques"][0]["skillLinksSummary"] = "A - B - C - D - E"
    support_gems = _valid_output()
    support_gems["techniques"][0]["skillLinksSummary"] = "Support gems: A, B, C, D, E"
    passive_path = _valid_output()
    passive_path["techniques"][0]["passiveTreeAnchors"] = ["Passive path: 1 -> 2 -> 3 -> 4 -> 5"]

    short = mature_llm_extraction.validate_llm_extraction_output(short_link)
    dash = mature_llm_extraction.validate_llm_extraction_output(dash_link)
    support = mature_llm_extraction.validate_llm_extraction_output(support_gems)
    passive = mature_llm_extraction.validate_llm_extraction_output(passive_path)

    assert short["ok"] is False
    assert "copyable_build_link" in short["flags"]
    assert dash["ok"] is False
    assert "full_gem_link_like" in dash["flags"]
    assert support["ok"] is False
    assert "full_support_link_like" in support["flags"]
    assert passive["ok"] is False
    assert "ordered_passive_path" in passive["flags"]


def test_validate_llm_extraction_handles_unhashable_enum_values_without_raising():
    payload = _valid_output()
    payload["techniques"][0]["lifecycleApplicability"] = ["starter_then_transition"]
    payload["techniques"][0]["confidence"] = {"level": "medium"}

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "invalid_lifecycle_applicability"


def test_validate_llm_extraction_rejects_high_copyability_risk():
    payload = _valid_output()
    payload["techniques"][0]["copyabilityRisk"] = "high"

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "high_copyability_risk"
    assert result["techniqueIndex"] == 0


def test_validate_llm_extraction_rejects_invalid_enums_and_lists():
    payload = _valid_output()
    payload["techniques"][0]["lifecycleApplicability"] = "copied_final"

    result = mature_llm_extraction.validate_llm_extraction_output(payload)

    assert result["ok"] is False
    assert result["error"] == "invalid_lifecycle_applicability"


def test_prompt_package_warns_llm_not_to_copy_raw_build_details():
    package = mature_llm_extraction.build_extraction_prompt_package(
        {
            "case_id": "case-safe-spark",
            "class": "Sorceress",
            "ascendancy": "Stormweaver",
            "main_skill": "Spark",
            "sanitized_keypoints": ["Endgame lightning caster scaling fixture."],
        }
    )

    text = "\n".join(package["messages"])
    assert package["ok"] is True
    assert "Do not output PoB code" in text
    assert "Do not output full gear" in text
    assert "full gem links" in text
    assert "JSON" in text
    assert "Endgame lightning caster scaling fixture." in text


def test_prompt_package_rejects_raw_fields_before_llm_call():
    package = mature_llm_extraction.build_extraction_prompt_package(
        {
            "case_id": "case-unsafe",
            "main_skill": "Spark",
            "pobCode": "eNrt" + "A" * 180,
        }
    )

    assert package["ok"] is False
    assert package["error"] == "copyable_prompt_field"
    assert "pobCode" in package["paths"]


def test_prompt_package_rejects_copyable_source_ref_before_llm_call():
    package = mature_llm_extraction.build_extraction_prompt_package(
        {
            "case_id": "case-unsafe-link",
            "sourceRef": "https://pobb.in/abc123",
            "main_skill": "Spark",
        }
    )

    assert package["ok"] is False
    assert package["error"] == "copyability_guard_failed"
    assert "copyable_build_link" in package["flags"]
    assert "abc123" not in str(package)


def test_prompt_package_rejects_copyable_dict_keys_before_llm_call():
    package = mature_llm_extraction.build_extraction_prompt_package(
        {
            "case_id": "case-unsafe-key",
            "numeric_ranges_or_metrics": {"https://pobb.in/abc123": {"min": 1, "max": 2}},
        }
    )

    assert package["ok"] is False
    assert package["error"] == "copyability_guard_failed"
    assert "copyable_build_link" in package["flags"]
    assert "abc123" not in str(package)
