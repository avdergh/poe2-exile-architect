from __future__ import annotations

from server.knowledge import mature_sample_contract


def _manifest(**overrides):
    base = {
        "sourceType": "poe_ninja",
        "sourceRef": "https://poe.ninja/poe2/builds/runesofaldur",
        "popularity": {"basis": "rank", "rank": 1, "source": "source_probe"},
        "freshness": {
            "league": "Runes of Aldur",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "snapshotDate": "2026-06-27",
        },
        "diversityBucket": "stormweaver-lightning-spell",
    }
    base.update(overrides)
    return base


def test_sample_manifest_requires_popularity_freshness_and_diversity():
    manifest = {
        "sourceType": "poe_ninja",
        "sourceRef": "https://poe.ninja/poe2/builds/runesofaldur",
    }

    result = mature_sample_contract.validate_sample_manifest(manifest)

    assert result["ok"] is False
    assert result["error"] == "sample_manifest_incomplete"
    assert "popularity" in result["missing"]
    assert "freshness" in result["missing"]
    assert "diversityBucket" in result["missing"]


def test_sample_manifest_accepts_minimal_copy_safe_manifest():
    result = mature_sample_contract.validate_sample_manifest(_manifest())

    assert result == {
        "ok": True,
        "sourceType": "poe_ninja",
        "diversityBucket": "stormweaver-lightning-spell",
    }


def test_sample_manifest_rejects_raw_copyable_fields():
    manifest = _manifest(
        sourceType="pobb_in",
        pobCode="eNrt" + "A" * 180,
        passiveTree={"nodes": [1, 2, 3]},
        fullGemLinks=["A", "B", "C", "D", "E"],
    )

    result = mature_sample_contract.validate_sample_manifest(manifest)

    assert result["ok"] is False
    assert result["error"] == "copyable_manifest_field"
    assert {"pobCode", "passiveTree", "fullGemLinks"} <= set(result["paths"])


def test_sample_manifest_rejects_nested_copyable_fields():
    manifest = _manifest(
        freshness={
            "league": "Runes of Aldur",
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "gear": {"Ring 1": "Exact copied item"},
        }
    )

    result = mature_sample_contract.validate_sample_manifest(manifest)

    assert result["ok"] is False
    assert result["error"] == "copyable_manifest_field"
    assert "freshness.gear" in result["paths"]


def test_sample_manifest_rejects_pob_blob_and_full_link_like_text():
    blob_manifest = _manifest(notes="eNrt" + "A" * 180)
    links_manifest = _manifest(notes="Supports: A, B, C, D, E")
    support_gems_manifest = _manifest(notes="Support gems: A, B, C, D, E")
    passive_path_manifest = _manifest(notes="Passive path: 1 -> 2 -> 3 -> 4 -> 5")

    blob = mature_sample_contract.validate_sample_manifest(blob_manifest)
    links = mature_sample_contract.validate_sample_manifest(links_manifest)
    support_gems = mature_sample_contract.validate_sample_manifest(support_gems_manifest)
    passive_path = mature_sample_contract.validate_sample_manifest(passive_path_manifest)

    assert blob["ok"] is False
    assert blob["error"] == "copyability_guard_failed"
    assert "pob_code_like_blob" in blob["flags"]
    assert links["ok"] is False
    assert links["error"] == "copyability_guard_failed"
    assert "full_support_link_like" in links["flags"]
    assert support_gems["ok"] is False
    assert "full_support_link_like" in support_gems["flags"]
    assert passive_path["ok"] is False
    assert "ordered_passive_path" in passive_path["flags"]


def test_sample_manifest_rejects_short_copyable_build_links_and_slot_gear_text():
    short_link = mature_sample_contract.validate_sample_manifest(
        _manifest(sourceRef="https://pobb.in/abc123")
    )
    pastebin = mature_sample_contract.validate_sample_manifest(
        _manifest(notes="https://pastebin.com/a1b2c3d4")
    )
    gear_slot = mature_sample_contract.validate_sample_manifest(
        _manifest(notes="Ring 1: exact copied rare ring")
    )

    assert short_link["ok"] is False
    assert short_link["error"] == "copyability_guard_failed"
    assert "copyable_build_link" in short_link["flags"]
    assert pastebin["ok"] is False
    assert "copyable_build_link" in pastebin["flags"]
    assert gear_slot["ok"] is False
    assert "slot_exact_gear_like" in gear_slot["flags"]


def test_sample_manifest_rejects_copyable_dict_keys_without_echoing_them():
    result = mature_sample_contract.validate_sample_manifest(
        _manifest(notes={"https://pobb.in/abc123": "safe-looking value"})
    )
    nested_raw = mature_sample_contract.validate_sample_manifest(
        _manifest(notes={"https://pobb.in/abc123": {"rawPayload": "unsafe"}})
    )

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "copyable_build_link" in result["flags"]
    assert "abc123" not in str(result)
    assert nested_raw["ok"] is False
    assert nested_raw["error"] == "copyable_manifest_field"
    assert "redacted-key:" in str(nested_raw["paths"])
    assert "abc123" not in str(nested_raw["paths"])


def test_sample_manifest_rejects_raw_payload_variants_and_character_urls():
    raw_payload = mature_sample_contract.validate_sample_manifest(
        _manifest(rawPayload={"anything": "must not persist"})
    )
    character_url = mature_sample_contract.validate_sample_manifest(
        _manifest(characterUrl="https://example.test/account/character")
    )
    nested = mature_sample_contract.validate_sample_manifest(
        _manifest(popularity={"basis": "rank", "rank": 1, "raw_html": "<html>raw</html>"})
    )

    assert raw_payload["ok"] is False
    assert raw_payload["error"] == "copyable_manifest_field"
    assert "rawPayload" in raw_payload["paths"]
    assert character_url["ok"] is False
    assert "characterUrl" in character_url["paths"]
    assert nested["ok"] is False
    assert "popularity.raw_html" in nested["paths"]


def test_sample_manifest_does_not_echo_invalid_source_type_raw_value():
    result = mature_sample_contract.validate_sample_manifest(
        _manifest(sourceType="eNrt" + "A" * 180)
    )

    assert result["ok"] is False
    assert result["error"] == "copyability_guard_failed"
    assert "eNrt" not in str(result)


def test_sample_manifest_requires_popularity_basis_and_strength():
    missing_basis = _manifest(popularity={"rank": 1})
    missing_strength = _manifest(popularity={"basis": "forum_heat"})

    basis = mature_sample_contract.validate_sample_manifest(missing_basis)
    strength = mature_sample_contract.validate_sample_manifest(missing_strength)

    assert basis["ok"] is False
    assert basis["error"] == "popularity_incomplete"
    assert "basis" in basis["missing"]
    assert strength["ok"] is False
    assert strength["error"] == "popularity_incomplete"
    assert "rank/count/share/weight" in strength["missing"]


def test_sample_manifest_requires_freshness_version_fields():
    result = mature_sample_contract.validate_sample_manifest(
        _manifest(freshness={"league": "Runes of Aldur"})
    )

    assert result["ok"] is False
    assert result["error"] == "freshness_incomplete"
    assert result["missing"] == ["gamePatch", "passiveTreeVersion"]


def test_sample_manifest_rejects_unknown_source_type():
    result = mature_sample_contract.validate_sample_manifest(_manifest(sourceType="random_blog"))

    assert result["ok"] is False
    assert result["error"] == "invalid_sample_source_type"
