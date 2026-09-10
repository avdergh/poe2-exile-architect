"""Lifecycle declarations preserve canonical identities at every typed boundary."""

from html import escape

import pytest
from pydantic import ValidationError

from server.generation import lifecycle_observation
from server.knowledge.lifecycle_verification import LifecycleStageVerificationState


@pytest.mark.parametrize("name,base,slot,key", [
    ("Shavronne's Satchel", "Fine Belt", "Belt", "unique:pob:shavronne's_satchel"),
    ("Cadiro's Gambit", "Primed Quiver", "Weapon 2", "unique:pob:cadiro's_gambit"),
    ("Atziri's Disdain", "Gold Circlet", "Helmet", "unique:pob:atziri's_disdain"),
])
def test_apostrophe_key_roundtrips_and_still_requires_active_equipment(name, base, slot, key):
    state = LifecycleStageVerificationState(
        buildDefiningComponentKind="item",
        buildDefiningComponentName=name,
        buildDefiningComponentKey=key,
        buildDefiningEvidenceRefs=[key, "drr-0123456789abcdef"],
    )
    payload = state.model_dump(mode="json", by_alias=True)
    assert LifecycleStageVerificationState.model_validate(payload) == state
    assert lifecycle_observation.declaration_payload(payload)["buildDefiningComponentKey"] == key
    item = escape(f"Rarity: Unique\n{name}\n{base}")
    xml = (
        '<PathOfBuilding><Build className="Witch" ascendClassName="Lich" level="90" '
        'mainSocketGroup="1"/><Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">'
        '<Gem nameSpec="Spark" skillId="SparkPlayer"/></Skill></SkillSet></Skills>'
        f'<Items activeItemSet="1"><Item id="1">{item}</Item>'
        f'<ItemSet id="1"><Slot name="{slot}" itemId="1"/></ItemSet>'
        '<ItemSet id="2"/></Items></PathOfBuilding>'
    )
    target = {"groupIndex": 1, "activeIndex": 1, "skillName": "Spark"}
    observed = lifecycle_observation.observe_state(
        xml, build={}, observation_target=target, state=state,
    )
    assert observed["buildDefiningComponent"]["verified"] is True
    assert observed["buildDefiningComponent"]["componentKey"] == key
    assert observed["buildDefiningComponent"]["evidenceRefs"] == [key, "drr-0123456789abcdef"]
    inactive = lifecycle_observation.observe_state(
        xml.replace('activeItemSet="1"', 'activeItemSet="2"'),
        build={}, observation_target=target, state=state,
    )
    assert inactive["buildDefiningComponent"]["verified"] is False


@pytest.mark.parametrize("value", [
    "https://example.com/item",
    "unique:https://example.com/item",
    "unique:pob:shavronne’s_satchel",
    "unique:pob:shavronne's satchel",
    "unique:pob:bad\nkey",
    "unique:pob:<item>",
    "unique:pob:" + "a" * 240,
])
@pytest.mark.parametrize("field", ["buildDefiningComponentKey", "buildDefiningEvidenceRefs"])
def test_lifecycle_keys_and_refs_reject_unsafe_inputs(field, value):
    payload = {
        "buildDefiningComponentKind": "item",
        "buildDefiningComponentName": "Shavronne's Satchel",
        "buildDefiningComponentKey": "unique:pob:shavronne's_satchel",
        "buildDefiningEvidenceRefs": ["drr-0123456789abcdef"],
    }
    payload[field] = [value] if field.endswith("Refs") else value
    with pytest.raises(ValidationError):
        LifecycleStageVerificationState.model_validate(payload)


def test_apostrophes_do_not_relax_component_kind_or_duplicate_ref_guards():
    with pytest.raises(ValidationError, match="type must match"):
        LifecycleStageVerificationState(
            buildDefiningComponentKind="skill",
            buildDefiningComponentName="Spark",
            buildDefiningComponentKey="unique:pob:shavronne's_satchel",
            buildDefiningEvidenceRefs=["drr-0123456789abcdef"],
        )
    with pytest.raises(ValidationError, match="unique safe refs"):
        LifecycleStageVerificationState(
            singleTargetSkillName="Spark",
            singleTargetEvidenceRefs=["unique:pob:shavronne's_satchel"] * 2,
        )
