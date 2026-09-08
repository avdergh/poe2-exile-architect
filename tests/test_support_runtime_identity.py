"""Exact corpus/PoB support identity and recommendation-to-application integration."""

import pytest

from server.compute import skillgroups
from server.compute.engine import PobEngine
from server.compute.state import build_state_hash
from server.knowledge import db


@pytest.fixture(scope="module")
def engine():
    instance = PobEngine()
    yield instance
    instance.close()


@pytest.mark.parametrize("corpus_name,runtime_name", [
    ("Mórrigan's Insight", "Morrigan's Insight"),
    ("Oisín's Oath", "Oisin's Oath"),
])
def test_exact_ids_resolve_runtime_label_without_mutation(engine, corpus_name, runtime_name):
    gem = db.get_gem(corpus_name)
    before = build_state_hash(engine.get_xml())
    result = engine.call("resolve_support_gem_identity", gemIds=[gem["id"]], effectIds=gem["grants"])
    assert result["status"] == "resolved"
    assert result["name"] == runtime_name
    assert result["gameId"] == gem["id"]
    assert result["effectId"] in gem["grants"]
    assert result["gemId"]
    assert build_state_hash(engine.get_xml()) == before


def test_identity_disagreement_is_ambiguous_and_names_do_not_override_ids(engine):
    first, second = db.get_gem("Zenith II"), db.get_gem("Rapid Casting II")
    result = engine.call("resolve_support_gem_identity", gemIds=[first["id"]], effectIds=second["grants"], requestedName="Zenith II")
    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) >= 2


def test_missing_support_is_distinct_from_missing_identity_or_active_skill(engine):
    unavailable = db.get_gem("Fusillade")
    assert engine.call("resolve_support_gem_identity", gemIds=[unavailable["id"]], effectIds=unavailable["grants"])["status"] == "model_unavailable"
    assert engine.call("resolve_support_gem_identity", requestedName="Zenith II")["ok"] is False
    active = db.get_gem("Spark")
    assert engine.call("resolve_support_gem_identity", gemIds=[active["id"]], effectIds=active["grants"])["status"] == "model_unavailable"
    assert engine.call("resolve_support_gem_identity", runtimeName="Oisins Oath")["status"] == "model_unavailable"


@pytest.mark.parametrize("name", ["Mórrigan's Insight", "Morrigan's Insight", "Oisín's Oath", "Oisin's Oath"])
def test_public_normal_group_accepts_both_id_verified_labels(engine, name):
    engine.new_build()
    engine.set_level(95)
    result = skillgroups.set_main_skill(engine, f"Spark 20/13 2\n{name} 1/17 1")
    assert result.get("ok") is not False, result
    group = skillgroups.list_skill_groups(engine)["groups"][0]
    assert len(group["gems"]) == 2
    assert group["gems"][0]["quality"] == 13
    assert group["gems"][1]["quality"] == 17
    assert group["gems"][1]["name"] in {"Morrigan's Insight", "Oisin's Oath"}


@pytest.mark.parametrize("name", ["Oisín's Oath", "Oisin's Oath"])
def test_public_source_group_accepts_id_verified_labels(engine, name):
    engine.new_build()
    engine.set_class("Sorceress", "Disciple of Varashta")
    engine.set_level(95)
    engine.alloc_passive(34207)
    listed = skillgroups.list_skill_groups(engine)
    group = listed["groups"][0]
    result = skillgroups.configure_source_skill_supports(
        engine, source_group_index=group["index"], supports=[name],
        expected_fingerprint=group["fingerprint"], expected_state_hash=listed["stateHash"],
    )
    assert result["ok"], result
    assert result["requestedSupports"] == ["Oisin's Oath"]


def test_unavailable_support_rejects_before_mutating(engine):
    engine.new_build()
    engine.set_level(95)
    before = build_state_hash(engine.get_xml())
    result = skillgroups.set_main_skill(engine, "Spark\nFusillade")
    assert result["ok"] is False
    assert result["errorCode"] == "unknown_skill_gem"
    assert build_state_hash(engine.get_xml()) == before
