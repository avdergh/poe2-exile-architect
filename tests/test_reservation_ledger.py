from __future__ import annotations

import json
import threading
from xml.etree import ElementTree as ET

import pytest

from server.compute.engine import PobEngine, PobEngineError
from server.compute.state import build_state_hash


def _reset(engine):
    engine.new_build()
    engine.set_level(90)
    engine.paste_skill("Frostbolt 20/0 1")
    engine.set_config(custom_mods="+500 to Spirit\n20% increased Reservation Efficiency")


def _inspect(engine):
    before = engine.get_xml()
    selection = engine.call("list_skill_groups")
    ledger = engine.inspect_reservation_ledger()
    assert engine.get_xml() == before
    assert engine.call("list_skill_groups") == selection
    assert ledger["buildStateHash"] == build_state_hash(before)
    assert ledger["readOnlyVerified"] is True
    assert ledger["schemaVersion"] == "pob_reservation_ledger_v1"
    assert ledger["status"] == "available"
    return ledger


def _effect(ledger, effect_id):
    return next(row for row in ledger["effects"] if row["effectId"] == effect_id)


def test_native_ledger_keeps_extra_effects_and_absent_values_separate(engine):
    _reset(engine)
    engine.add_skill_group("Archmage 20/0 1\nClarity II 1/0 1")
    engine.add_skill_group("Blink 20/0 1")
    engine.add_skill_group("Cast on Critical 20/0 1\nComet 20/0 1")
    ledger = _inspect(engine)
    archmage = _effect(ledger, "ArchmagePlayer")
    assert archmage["extraSpirit"] == 20
    assert archmage["pools"]["Spirit"]["grantedLevelFlat"] == 100
    assert archmage["pools"]["Spirit"]["efficiencyInc"] == 20
    assert archmage["pools"]["Spirit"]["nativeReservedBase"] == 100
    reservation = _effect(ledger, "BlinkReservationPlayer")
    blink = _effect(ledger, "BlinkPlayer")
    assert reservation["groupIndex"] == blink["groupIndex"] == 3
    assert reservation["gemIndex"] == blink["gemIndex"] == 1
    assert reservation["sourceEffectId"] == blink["sourceEffectId"] == "BlinkReservationPlayer"
    assert reservation["reservesInAllWeaponSets"] is True
    assert reservation["pools"]["Spirit"]["nativeReservedBase"] == 50
    assert blink["participatesInCurrentReservation"] is False
    assert blink["pools"]["Spirit"]["nativeReservedBase"] is None
    assert _effect(ledger, "CometPlayer")["gemIndex"] == 2
    native = engine.get_build()
    assert ledger["totals"]["Spirit"]["reservedCapped"] == native["spiritReservedCapped"]
    assert ledger["totals"]["Spirit"]["unreserved"] == native["spiritUnreserved"]
    assert not any("Cost" in key for row in ledger["effects"] for key in row)


def test_native_life_replacement_preserves_percent_and_global_rounding(engine):
    _reset(engine)
    engine.add_skill_group("Archmage 20/0 1\nAtziri's Communion 1/0 1\nClarity II 1/0 1")
    engine.add_skill_group("Blink 20/0 1\nAtziri's Communion 1/0 1")
    engine.set_config(custom_mods="+500 to Spirit\n20% increased Reservation Efficiency\n+1 to maximum Life")
    ledger = _inspect(engine)
    archmage = _effect(ledger, "ArchmagePlayer")
    assert archmage["lifeReservePercentPerSpirit"] == pytest.approx(0.66)
    assert archmage["pools"]["Life"]["nativeReservedPercent"] == 66
    assert archmage["pools"]["Spirit"]["nativeReservedBase"] is None
    total = ledger["totals"]["Life"]
    individual_displays = sum(row["pools"]["Life"]["nativeReservedBase"] or 0 for row in ledger["effects"])
    # Native actor rounding happens after percent amounts are combined. A ledger
    # that rebuilds the total by summing per-effect display amounts is incorrect.
    assert individual_displays != total["maximum"] - total["unreserved"]
    assert total["unreserved"] > 0


def test_native_overreservation_keeps_capped_and_uncapped_totals(engine):
    _reset(engine)
    engine.set_config(custom_mods="")
    engine.add_skill_group("Cast on Critical 20/0 1\nComet 20/0 1")
    engine.add_skill_group("Cast on Elemental Ailment 20/0 1\nSpark 20/0 1")
    ledger = _inspect(engine)
    total = ledger["totals"]["Spirit"]
    assert total["unreserved"] < 0
    assert total["nativeReservedFlatTotal"] > total["maximum"]
    assert total["reservedCapped"] == total["maximum"]


def test_native_item_grant_and_same_named_ordinary_group_are_not_merged(engine):
    _reset(engine)
    result = engine.add_item(
        "Rarity: RARE\nPrivate Fixture Label\nAbsent Amulet\nItem Level: 80\n"
        "Grants Skill: Level 20 Cast on Elemental Ailment",
        slot="Amulet",
    )
    assert result["ok"] is True
    engine.add_skill_group("Cast on Elemental Ailment 20/0 1\nSpark 20/0 1")
    ledger = _inspect(engine)
    hosts = [row for row in ledger["effects"] if row["effectId"] == "MetaCastOnElementalAilmentPlayer"]
    assert len(hosts) == 2
    granted = next(row for row in hosts if row["fromItem"])
    ordinary = next(row for row in hosts if not row["fromItem"])
    assert granted["groupIndex"] != ordinary["groupIndex"]
    assert granted["noReservation"] is True
    assert granted["pools"]["Spirit"]["grantedLevelFlat"] == 0
    assert granted["pools"]["Spirit"]["nativeReservedBase"] is None
    assert ordinary["pools"]["Spirit"]["nativeReservedBase"] == 83
    owner = next(row for row in ledger["groups"] if row["groupIndex"] == granted["groupIndex"])
    assert owner["sourceKind"] == "item"
    assert owner["sourceItemId"] is not None
    assert owner["ownerSlot"] == "Amulet"
    assert "Private Fixture Label" not in json.dumps(ledger)
    assert ledger["sourceGroupMappingStatus"] == "not_observed"


def test_alternate_actor_and_blink_all_sets_use_actual_runtime_scope(engine):
    _reset(engine)
    engine.add_skill_group("Mana Remnants 20/0 1")
    engine.add_skill_group("Blink 20/0 1")
    root = ET.fromstring(engine.get_xml())
    groups = root.findall("./Skills/SkillSet/Skill")
    for group in groups[1:3]:
        group.set("set1", "false")
        group.set("set2", "true")
    engine.load_build_xml(ET.tostring(root, encoding="unicode"))
    ledger = _inspect(engine)
    remnant = _effect(ledger, "ManaRemnantsPlayer")
    assert remnant["actorMatches"] is False
    assert remnant["actorWeaponSet"] == 2
    assert remnant["participatesInCurrentReservation"] is False
    assert remnant["pools"]["Spirit"]["nativeReservedBase"] is None
    group = next(row for row in ledger["groups"] if row["groupIndex"] == remnant["groupIndex"])
    assert group["usingWeaponSet"] == 2
    blink = _effect(ledger, "BlinkReservationPlayer")
    assert blink["reservesInAllWeaponSets"] is True
    assert blink["participatesInCurrentReservation"] is True
    assert ledger["totals"]["Spirit"]["nativeReservedFlatTotal"] == 50
    engine.call("set_skill_group_state", index=2, enabled=False)
    after = _inspect(engine)
    assert next(row for row in after["groups"] if row["groupIndex"] == 2)["enabled"] is False
    assert after["totals"] == ledger["totals"]


def test_engine_guard_rejects_mutation_without_claiming_readonly_success():
    class MutatingProbe:
        _lock = threading.RLock()
        reads = iter(["before", "after"])

        def get_xml(self):
            return next(self.reads)

        def call(self, _method):
            return {"schemaVersion": "pob_reservation_ledger_v1"}

    with pytest.raises(PobEngineError, match="changed build state"):
        PobEngine.inspect_reservation_ledger(MutatingProbe())


def test_research_readback_binds_native_ledger_to_observed_xml(engine, monkeypatch):
    from server.knowledge import research_packet, research_readback

    _reset(engine)
    engine.add_skill_group("Archmage 20/0 1\nAtziri's Communion 1/0 1")
    xml = engine.get_xml()
    monkeypatch.setattr(
        research_readback, "PobEngine",
        lambda **_kwargs: PobEngine(script=engine.script),
    )
    result = research_readback.build_safe_readback(
        xml, source_hash_ref="source-hash:synthetic-ledger", version_context={},
    )
    assert result["status"] == "available"
    ledger = result["reservationLedger"]
    assert ledger["buildStateHash"] == result["stateBinding"]["observedBuildStateHash"]
    assert ledger["snapshotRef"] == result["snapshotRef"]
    assert ledger["sourceHashRef"] == result["sourceHashRef"]
    assert _effect(ledger, "ArchmagePlayer")["pools"]["Life"]["nativeReservedPercent"] > 0
    packet = {"rawContext": {"rawXml": xml}, "pobReadback": result,
              "safeMetadata": {"sourceRef": "source-hash:synthetic-ledger"}}
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    assert engine.get_xml() == xml  # The Research engine is independent of this fixture.
