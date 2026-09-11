"""移除事件、静态身份和模型覆盖分别验证。"""

from copy import deepcopy
from xml.etree import ElementTree as ET
from weakref import WeakKeyDictionary

import pytest

from server.knowledge import db, gem_availability
from server.compute.state import build_state_hash
from server.generation import leveled_build, preflight, validation_checkpoint
from server.judge import evaluator, hard_legality

WIND = "Metadata/Items/Gems/SupportGemWindWave"


def test_official_removed_batch_is_bound_and_excluded_from_candidate_queries():
    catalog = gem_availability.catalog()
    assert len(catalog["entries"]) == 37
    assert gem_availability.validate_corpus_bindings(db._conn())["checkedBindings"] == 37
    removed = {entry["componentKey"].removeprefix("gem:") for entry in catalog["entries"]}
    assert not removed.intersection(row["id"] for row in db.find_skills(limit=99999))
    assert not removed.intersection(row["id"] for row in db.list_gems_for_level(95, limit=99999))
    assert "Wind Wave" not in [
        row["name"] for row in db.find_supports_for("Wind Dancer", 99999)["compatible"]
    ]
    assert db.get_gem(WIND)["availability"]["status"] == "unavailable"
    assert db.find_skills("Wind Wave", include_unavailable=True)[0]["id"] == WIND


def test_removed_correction_keeps_historical_identity_and_does_not_guess_from_name():
    assert (
        gem_availability.inspect_ids([WIND], target_patch="0.2.0")["status"]
        == "not_flagged_unavailable"
    )
    assert (
        gem_availability.inspect_ids(["gem:" + WIND], target_patch="0.5.5")["status"]
        == "unavailable"
    )
    assert gem_availability.inspect_ids(["Wind Wave"])["status"] == "not_flagged_unavailable"
    assert gem_availability.inspect_ids([WIND + "Two"])["status"] == "not_flagged_unavailable"


def test_zero_crafting_level_or_missing_crafting_types_do_not_remove_lineage_support():
    gem = db.get_gem("Eonyr's Thunder")
    assert gem["crafting_level"] == 0
    assert gem["is_lineage"] is True
    assert gem["availability"]["status"] == "not_flagged_unavailable"
    assert db.find_skills("Eonyr's Thunder")


def test_missing_availability_catalog_is_not_an_empty_exclusion_list(tmp_path, monkeypatch):
    monkeypatch.setattr(gem_availability, "CATALOG_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        gem_availability.inspect_ids([WIND])


def test_level_check_rejects_removed_gem_before_querying_level_curve():
    class NoCurve:
        def gem_level_requirements(self, _):
            raise AssertionError("A level curve cannot certify a removed gem")

    result = leveled_build.validate_level_availability(NoCurve(), ["gem:" + WIND], 95)
    assert result["results"][0]["reason"] == "gem_unavailable_in_target_patch"


@pytest.mark.parametrize("class_name,host", [("Ranger", "Wind Dancer"), ("Warrior", "Earthquake")])
def test_native_removed_gem_cannot_enter_generated_judge_but_reference_is_readable(
    engine, class_name, host
):
    engine.new_build()
    engine.set_class(class_name)
    engine.set_level(95)
    engine.paste_skill(host + " 20/20 1\nWind Wave")
    before = build_state_hash(engine.get_xml())
    build = engine.get_build()
    check = hard_legality.check_gem_availability(build)
    assert check["unavailable"][0]["componentKey"] == "gem:" + WIND
    failure = "equipped_gem_unavailable_in_target_patch"
    assert failure in preflight.inspect_generation_preflight(engine)["blockingIssues"]
    assert (
        failure in evaluator.evaluate_active_build(engine, "removed-support-test")["hardFailures"]
    )
    assert (
        failure
        not in hard_legality.audit_build(build, source_context="trusted_reference")["hardFailures"]
    )
    assert build_state_hash(engine.get_xml()) == before
    # Disabled gems are historical input, not part of the equipped active combination.
    root = ET.fromstring(engine.get_xml())
    for gem in root.findall(".//Skills//Gem"):
        if gem.get("nameSpec") == "Wind Wave":
            gem.set("enabled", "false")
    engine.load_build_xml(ET.tostring(root, encoding="unicode"))
    assert hard_legality.check_gem_availability(engine.get_build())["unavailableCount"] == 0


def valid_review():
    return {
        "componentKey": "gem:" + WIND,
        "targetPatch": "0.5.5",
        "reason": "removed",
        "sourceReviews": [
            {
                "url": "https://www.pathofexile.com/forum/view-thread/3828542/filter-account-type/staff",
                "assessment": "supports_unavailable",
                "relevanceReason": "已读官方 Removed Items，逐项确认 Wind Wave 被移除。",
            },
            {
                "url": "https://www.poe2wiki.net/wiki/Wind_Wave",
                "assessment": "supports_unavailable",
                "relevanceReason": "已读独立页面的移除版本与当前不可用声明，和官方清单一致。",
            },
        ],
    }


def test_new_availability_evidence_invalidates_checkpoint_and_survives_snapshot_restore(engine, monkeypatch):
    # Synthetic session review tests evidence propagation, not the actual availability of Blind II.
    monkeypatch.setattr(gem_availability, "_SESSION_REVIEWS", WeakKeyDictionary())
    engine.new_build()
    engine.set_class("Sorceress")
    engine.set_level(95)
    engine.paste_skill("Fireball 20/20 1\nBlind II")
    snapshot = engine.get_xml()
    state = build_state_hash(snapshot)
    before = validation_checkpoint.inspect_generation_checkpoint(engine, offense_skill_group_index=1, expected_skill_name="Fireball")
    repeated = validation_checkpoint.inspect_generation_checkpoint(engine, offense_skill_group_index=1, expected_skill_name="Fireball")
    assert repeated["cacheHit"] is True
    gem = db.get_gem("Blind II")
    subject = next(row for row in engine.get_build()["gemAvailabilitySubjects"] if row["name"] == "Blind II")
    review = {"componentKey":"gem:"+gem["id"], "gemIds":[subject["gemId"],subject["gameId"]],
              "reason":"removed","targetPatch":"0.5.5","evidenceKind":"agent_reviewed","reviewRef":"synthetic-reviewed-removal"}
    gem_availability.register_session_reviews(engine,{review["componentKey"]:review})
    after = validation_checkpoint.inspect_generation_checkpoint(engine, offense_skill_group_index=1, expected_skill_name="Fireball")
    assert after["cacheHit"] is False
    assert before["availabilityContextRef"] != after["availabilityContextRef"]
    assert "equipped_gem_unavailable_in_target_patch" in after["hardLegality"]["hardFailures"]
    assert build_state_hash(engine.get_xml()) == state
    engine.load_build_xml(snapshot)
    restored = hard_legality.audit_active_build(engine)
    assert "equipped_gem_unavailable_in_target_patch" in restored["hardFailures"]
    assert restored["checks"]["gemAvailability"]["unavailable"][0]["evidenceKind"] == "agent_reviewed"


@pytest.mark.parametrize(
    "change", ["no_official", "same_site", "wrong_key", "unverified", "no_reading"]
)
def test_agent_review_cannot_be_name_only_or_upgrade_its_evidence_authority(change):
    review = deepcopy(valid_review())
    if change == "no_official":
        review["sourceReviews"][0]["url"] = "https://example.org/claim"
    elif change == "same_site":
        review["sourceReviews"][1]["url"] = review["sourceReviews"][0]["url"]
    elif change == "wrong_key":
        review["componentKey"] = "Wind Wave"
    elif change == "unverified":
        review["evidenceKind"] = "internal_verified"
    else:
        review["sourceReviews"][0]["relevanceReason"] = ""
    with pytest.raises(ValueError):
        gem_availability.SupportAvailabilityReview.model_validate(review)
