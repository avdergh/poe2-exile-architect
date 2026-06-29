from __future__ import annotations

from server.knowledge import mature_source_intake


def test_group_payload_variants_before_split_assignment():
    rows = [
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "poe_ninja_export",
            "sourceRef": "https://poe.ninja/build/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "pobb_in",
            "sourceRef": "https://pobb.in/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
    ]

    grouped = mature_source_intake.group_source_variants(rows)

    assert grouped["ok"] is True
    assert grouped["groupCount"] == 1
    assert grouped["groups"][0]["sourceRefs"] == [
        "https://poe.ninja/build/alpha",
        "https://pobb.in/alpha",
    ]


def test_group_source_variants_keeps_multiple_payload_sources_without_duplicate_refs():
    rows = [
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "poe_ninja_export",
            "sourceRef": "https://poe.ninja/build/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "poe_ninja_export",
            "sourceRef": "https://poe.ninja/build/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "pobb_in",
            "sourceRef": "https://pobb.in/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
        {
            "discoverySource": "forum_index",
            "payloadSource": "forum_post",
            "sourceRef": "https://forum.example/build/beta",
            "buildFamilyKey": "gemling-minions-beta",
        },
    ]

    grouped = mature_source_intake.group_source_variants(rows)

    assert grouped["ok"] is True
    assert grouped["groupCount"] == 2
    assert grouped["groups"][0]["payloadSources"] == ["poe_ninja_export", "pobb_in"]
    assert grouped["groups"][0]["sourceRefs"] == [
        "https://poe.ninja/build/alpha",
        "https://pobb.in/alpha",
    ]
    assert grouped["groups"][1]["buildFamilyKey"] == "gemling-minions-beta"
    assert grouped["groups"][1]["payloadSources"] == ["forum_post"]


def test_group_source_variants_rejects_missing_or_blank_build_family_key():
    rows = [
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "poe_ninja_export",
            "sourceRef": "https://poe.ninja/build/alpha",
            "buildFamilyKey": None,
        },
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "pobb_in",
            "sourceRef": "https://pobb.in/alpha",
            "buildFamilyKey": "   ",
        },
    ]

    grouped = mature_source_intake.group_source_variants(rows)

    assert grouped["ok"] is False
    assert grouped["error"] == "invalid_build_family_key"
    assert grouped["invalidRows"] == [
        {"index": 0, "reason": "missing_build_family_key"},
        {"index": 1, "reason": "missing_build_family_key"},
    ]


def test_group_source_variants_preserves_mixed_discovery_source_provenance():
    rows = [
        {
            "discoverySource": "poe_ninja",
            "payloadSource": "poe_ninja_export",
            "sourceRef": "https://poe.ninja/build/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
        {
            "discoverySource": "forum_index",
            "payloadSource": "pobb_in",
            "sourceRef": "https://pobb.in/alpha",
            "buildFamilyKey": "stormweaver-spark-alpha",
        },
    ]

    grouped = mature_source_intake.group_source_variants(rows)

    assert grouped["ok"] is True
    assert grouped["groups"][0]["discoverySources"] == ["poe_ninja", "forum_index"]


def test_rich_brief_metadata_is_quarantine_only():
    result = mature_source_intake.build_rich_brief_metadata(
        build_family_key="stormweaver-spark-alpha",
        summary="Non-copyable rich brief summary.",
    )

    assert result["ok"] is True
    assert result["visibility"] == "quarantined"
    assert result["split"] == "quarantine"
    assert result["creatorVisible"] is False


def test_rich_brief_metadata_preserves_quarantine_only_source_shape():
    result = mature_source_intake.build_rich_brief_metadata(
        build_family_key="stormweaver-spark-alpha",
        summary="Safe summary",
        source_refs=["https://poe.ninja/build/alpha", "https://pobb.in/alpha"],
        payload_sources=["poe_ninja_export", "pobb_in"],
    )

    assert result["briefType"] == "rich_brief"
    assert result["buildFamilyKey"] == "stormweaver-spark-alpha"
    assert result["sourceRefs"] == [
        "https://poe.ninja/build/alpha",
        "https://pobb.in/alpha",
    ]
    assert result["payloadSources"] == ["poe_ninja_export", "pobb_in"]
    assert result["creatorVisible"] is False


def test_rich_brief_metadata_filters_empty_values_and_dedupes_sources():
    result = mature_source_intake.build_rich_brief_metadata(
        build_family_key="stormweaver-spark-alpha",
        summary="Safe summary",
        source_refs=[
            "https://poe.ninja/build/alpha",
            "",
            "  ",
            None,
            "https://poe.ninja/build/alpha",
            "https://pobb.in/alpha",
        ],
        payload_sources=["poe_ninja_export", "", "pobb_in", None, "poe_ninja_export"],
    )

    assert result["sourceRefs"] == [
        "https://poe.ninja/build/alpha",
        "https://pobb.in/alpha",
    ]
    assert result["payloadSources"] == ["poe_ninja_export", "pobb_in"]


def test_build_raw_rich_case_combines_discovery_and_payload_rows():
    result = mature_source_intake.build_raw_rich_case(
        build_family_key="stormweaver-spark-alpha",
        discovery_row={
            "discoverySource": "poe_ninja",
            "sourceType": "poe_ninja",
            "sourceRef": "https://poe.ninja/build/alpha",
            "league": "Dawn of the Hunt",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "class": "Sorceress",
            "ascendancy": "Stormweaver",
            "mainSkill": "Spark",
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledgeScope": "global_seed",
            "evidenceType": "poe_ninja_hot",
            "freshnessStatus": "verified_current",
            "compatibilityStatus": "current",
            "keypoints": ["Top ladder Spark shell."],
        },
        payload_row={
            "payloadSource": "pobb_in",
            "sourceType": "pobb_in",
            "sourceRef": "https://pobb.in/alpha",
            "mainSkill": "Spark",
            "damageTypes": ["lightning"],
            "deliveryTags": ["spell", "projectile"],
            "mechanicTags": ["crit", "shock"],
            "budgetBand": "expensive",
            "pobModelability": "partial",
            "gear": {"Weapon": {"name": "Example staff"}},
            "skillGroups": {"main": ["Spark", "Spell Echo"]},
            "sourcePayload": {"kind": "pobb_in_export", "id": "alpha"},
        },
    )

    assert result["ok"] is True
    case = result["case"]
    assert case["discoverySource"] == "poe_ninja"
    assert case["payloadSource"] == "pobb_in"
    assert case["safeMetadata"]["sourceRef"] == "https://pobb.in/alpha"
    assert case["safeMetadata"]["diversityBucket"] == "stormweaver-spark-alpha"
    assert case["rawContext"]["gear"] == {"Weapon": {"name": "Example staff"}}
    assert case["rawContext"]["skillGroups"] == {"main": ["Spark", "Spell Echo"]}


def test_build_raw_rich_case_requires_object_rows_and_family_key():
    no_key = mature_source_intake.build_raw_rich_case(
        build_family_key="",
        discovery_row={},
        payload_row={},
    )
    bad_discovery = mature_source_intake.build_raw_rich_case(
        build_family_key="stormweaver-spark-alpha",
        discovery_row="bad",
        payload_row={},
    )
    bad_payload = mature_source_intake.build_raw_rich_case(
        build_family_key="stormweaver-spark-alpha",
        discovery_row={},
        payload_row="bad",
    )

    assert no_key["ok"] is False
    assert no_key["error"] == "build_family_key_required"
    assert bad_discovery["ok"] is False
    assert bad_discovery["error"] == "discovery_row_must_be_object"
    assert bad_payload["ok"] is False
    assert bad_payload["error"] == "payload_row_must_be_object"
