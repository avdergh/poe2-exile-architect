"""Real PoB regressions for item-owned outputs and incremental essence provenance."""

from pathlib import Path
import re
import threading
from xml.sax.saxutils import escape

import pytest

from server.compute import completeness, craftopt, equipment, skillgroups, socket_probe
from server.compute.state import build_state_hash
from server.knowledge import item_legality, itemparse
from server.runtime import craft_receipts


def _start(engine, class_name):
    engine.new_build()
    engine.set_class(class_name)
    engine.set_level(92)
    engine.paste_skill("Fireball 20/0  1")
    engine.set_config(custom_mods="+500 to Strength\n+500 to Dexterity\n+500 to Intelligence")


def _molten_shower(engine):
    _start(engine, "Warrior")
    source = (
        Path(__file__).resolve().parents[1] / "pob/PathOfBuilding-PoE2/src/Data/Uniques/mace.lua"
    )
    blocks = re.findall(r"\[\[(.*?)\]\]", source.read_text(encoding="utf-8"), re.S)
    block = next(
        block.strip() for block in blocks if block.strip().startswith("Brutus' Lead Sprinkler\n")
    )
    lines = block.splitlines()
    lines.insert(2, "Item Level: 90")
    raw = "Rarity: Unique\n" + craftopt._roll("\n".join(lines), "realistic")
    assert engine.add_item(raw, slot="Weapon 1")["ok"]
    listed = skillgroups.list_skill_groups(engine)
    group = next(group for group in listed["groups"] if group.get("sourceKind") == "item")
    configured = skillgroups.configure_source_skill_supports(
        engine,
        source_group_index=group["index"],
        supports=["Concentrated Area"],
        expected_fingerprint=group["fingerprint"],
        expected_state_hash=listed["stateHash"],
    )
    assert configured["ok"], configured
    engine.select_judge_skill(
        offense_skill_group_index=group["index"], expected_skill_name="Molten Shower"
    )


def _only_iron(engine, monkeypatch, slot):
    original = engine.crafting_options
    option = next(option for option in original(slot)["runes"] if option["name"] == "Iron Rune")
    monkeypatch.setattr(
        engine, "crafting_options", lambda slot: {**original(slot), "runes": [option]}
    )
    return option


def test_molten_shower_socket_probe_keeps_exact_output_supports_and_matches_pob_oracle(
    engine,
    monkeypatch,
):
    _molten_shower(engine)
    option = _only_iron(engine, monkeypatch, "Weapon 1")
    before = engine.get_xml()
    context = engine.inspect_item_replacement_context()["calculationContext"]
    original_stats = engine.get_stats
    observed = []

    def stats(keys):
        result = original_stats(keys)
        observed.append(result["mainSkill"])
        assert engine.inspect_item_replacement_context(expected_context=context)["ok"]
        return result

    monkeypatch.setattr(engine, "get_stats", stats)
    result = craftopt.optimize_item_sockets(
        engine, slot="Weapon 1", socket_count=1, goals={"TotalDPS": 1}
    )
    assert result["ok"] and result["changed"], result
    assert result["decision"] == "socketed"
    assert result["calculationContext"] == context
    assert set(observed) == {"Molten Shower"}
    assert result["metricsAfter"]["TotalDPS"] > result["metricsBefore"]["TotalDPS"]
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)
    raw = completeness.equipped_item_text(before, "Weapon 1")
    candidate = craftopt._augment_item_with_runes(
        raw,
        [(option["name"], [line for line in option["mods"] if not line.startswith("Bonded:")])],
        socket_capacity=1,
    )
    # Independent original review oracle: direct PoB reload with the same item ID/source group.
    oracle = re.sub(
        r"(<Item\b[^>]*>)(.*?)(</Item>)",
        lambda match: match[1] + "\n" + escape(candidate) + "\n" + match[3],
        before,
        count=1,
        flags=re.S,
    )
    try:
        engine.load_build_xml(oracle)
        assert engine.inspect_item_replacement_context(expected_context=context)["ok"]
        assert result["metricsAfter"]["TotalDPS"] == pytest.approx(
            original_stats(["TotalDPS"])["stats"]["TotalDPS"]
        )
    finally:
        engine.load_build_xml(before)


def test_source_configuration_loss_is_measurement_error_and_never_no_positive(engine, monkeypatch):
    _molten_shower(engine)
    _only_iron(engine, monkeypatch, "Weapon 1")
    before = engine.get_xml()
    load = engine.load_build_xml

    def lose_support(xml, *args, **kwargs):
        if "Rune: Iron Rune" in xml:
            xml = re.sub(r'<Gem\b[^>]*nameSpec="Concentrated Area"[^>]*/>', "", xml)
        return load(xml, *args, **kwargs)

    monkeypatch.setattr(engine, "load_build_xml", lose_support)
    result = craftopt.optimize_item_sockets(
        engine, slot="Weapon 1", socket_count=1, goals={"TotalDPS": 1}
    )
    assert result["decision"] == "measurement_error", result
    assert result["errorCode"] == "socket_probe_non_item_inputs_changed"
    assert "craftReceiptRef" not in result
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)


def test_real_pob_partial_socket_receipt_keeps_empty_capacity_without_inventing_rune(
    engine, monkeypatch
):
    _molten_shower(engine)
    slot = "Helmet"
    engine.add_item(
        "Rarity: Rare\nPartial Rune Probe\nImperial Greathelm\nItem Level: 95\n"
        "+50 to maximum Life", slot=slot
    )
    original = engine.crafting_options
    option = next(
        option for option in original(slot)["runes"] if option["name"] == "Legacy of Greymake"
    )
    monkeypatch.setattr(
        engine, "crafting_options", lambda slot: {**original(slot), "runes": [option]}
    )
    before = engine.get_xml()
    result = craftopt.optimize_item_sockets(
        engine, slot=slot, socket_count=2, goals={"Life": 1}
    )
    assert result["ok"] and result["decision"] == "partial_socketed", result
    assert result["socketCapacity"] == 2 and result["filledSocketCount"] == 1
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)
    assert "Rune: None" in result["item"]
    equipped = equipment.equip_item_verified(
        engine, raw=result["item"], slot=slot, craft_receipt_ref=result["craftReceiptRef"]
    )
    assert equipped["readbackVerified"], equipped
    actual = completeness.equipped_item_text(engine.get_xml(), slot)
    structure = itemparse.semantic_item_structure(actual)
    assert structure["runeSockets"] == 2
    assert structure["runeNames"] == ["Legacy of Greymake"]
    # PoB may wrap the displayed Rune line in {enchant}; the canonical receipt
    # must still verify exactly one installed Rune and preserve every non-Rune effect.
    assert itemparse.semantic_item_structure(craftopt._without_socketed_runes(actual))[
        "itemFingerprint"
    ] == itemparse.semantic_item_structure(
        craftopt._without_socketed_runes(completeness.equipped_item_text(before, slot))
    )["itemFingerprint"]
    item = completeness._parse_item_text(actual, slot=slot, require_special_provenance=True)
    assert item["runeSockets"] == 2 and item["verifiedRuneCount"] == 1
    assert item["runes"] == ["Legacy of Greymake"]
    assert item["affixLegality"]["ok"]

    wand = "Rarity: Rare\nQuota Probe\nAttuned Wand\nItem Level: 95\n50% increased Spell Damage"
    # The remaining assertion only checks the shared Rune quota. Equip the wand in its
    # legal main-hand slot; a wand cannot be used as Brutus' Lead Sprinkler's offhand.
    assert engine.add_item(wand, slot="Weapon 1")["ok"]
    from server.compute import socket_limits

    lifesprig = next(
        option for option in original("Weapon 1")["runes"]
        if option["name"] == "Legacy of Lifesprig"
    )
    assert lifesprig["constraints"][0]["evidencePatch"] == "0.5.5"
    quota = socket_limits.audit(engine.get_xml(), replacements={"Weapon 1": [lifesprig]})
    assert not quota["ok"], quota
    assert quota["violations"][0]["group"] == "AldursLegacyLimit1"


def test_empty_socket_sentinel_is_exact_and_unknown_rune_names_remain_visible():
    raw = "Rarity: Rare\nRune Probe\nImperial Greathelm\nItem Level: 95\nSockets: S S\n"
    assert itemparse.semantic_item_structure(raw + "Rune: None")["runeNames"] == []
    assert itemparse.semantic_item_structure(raw + "Rune: none")["runeNames"] == ["none"]
    assert itemparse.semantic_item_structure(raw + "Rune: Unknown Rune")["runeNames"] == [
        "Unknown Rune"
    ]


def test_pinned_rune_options_publish_real_shared_and_individual_quota_evidence(engine):
    _start(engine, "Sorceress")
    engine.add_item("Rarity: Rare\nQuota Probe\nImperial Greathelm\nItem Level: 95", slot="Helmet")
    options = {option["name"]: option for option in engine.crafting_options("Helmet")["runes"]}
    from server.compute import socket_limits

    assert socket_limits.constraints(options["Jiquani's Thesis"]) == [
        {"group": "AncientAugment", "limit": 1}
    ]
    assert socket_limits.constraints(options["Kurgal's Gaze"]) == [
        {"group": "AncientAugment", "limit": 1}
    ]
    assert socket_limits.constraints(options["Soul Core of Zalatl"]) == [
        {"group": "Soul Core of Zalatl", "limit": 1}
    ]
    assert socket_limits.constraints(options["Mind Rune"]) == []
    assert not socket_limits.audit(
        engine.get_xml(), replacements={"Helmet": [options["Jiquani's Thesis"], options["Kurgal's Gaze"]]}
    )["ok"]


@pytest.mark.parametrize(
    "slot,base,rune",
    [
        ("Body Armour", "Sacramental Robe", "Tempered Rune"),
        ("Helmet", "Imperial Greathelm", "Tempered Rune"),
        ("Helmet", "Imperial Greathelm", "Legacy of Deidbell"),
    ],
)
def test_thorns_rune_can_add_pob_derived_group_without_changing_selected_source(
    engine, monkeypatch, slot, base, rune
):
    _molten_shower(engine)
    engine.add_item(
        f"Rarity: Rare\nThorns Probe\n{base}\nItem Level: 95\n+50 to maximum Life", slot=slot
    )
    original = engine.crafting_options
    option = next(option for option in original(slot)["runes"] if option["name"] == rune)
    monkeypatch.setattr(
        engine, "crafting_options", lambda slot: {**original(slot), "runes": [option]}
    )
    before = engine.get_xml()
    context = engine.inspect_item_replacement_context()["calculationContext"]
    result = craftopt.optimize_item_sockets(
        engine, slot=slot, socket_count=1, goals={"TotalDPS": 1}
    )
    assert result["ok"], result
    assert result["decision"] == "no_positive"
    assert result["measurementComplete"] is True
    assert result["calculationContext"] == context
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)


@pytest.mark.parametrize("change", ["source_support", "thorns_full_dps"])
def test_derived_thorns_allowance_never_authorizes_other_input_changes(engine, monkeypatch, change):
    _molten_shower(engine)
    slot = "Body Armour"
    engine.add_item(
        "Rarity: Rare\nThorns Probe\nSacramental Robe\nItem Level: 95\n+50 to maximum Life",
        slot=slot,
    )
    original_options = engine.crafting_options
    option = next(
        option for option in original_options(slot)["runes"] if option["name"] == "Tempered Rune"
    )
    monkeypatch.setattr(
        engine, "crafting_options", lambda slot: {**original_options(slot), "runes": [option]}
    )
    before = engine.get_xml()
    load = engine.load_build_xml

    def alter_input(xml, *args, **kwargs):
        if "Rune: Tempered Rune" not in xml:
            return load(xml, *args, **kwargs)
        if change == "source_support":
            xml = re.sub(r'<Gem\b[^>]*nameSpec="Concentrated Area"[^>]*/>', "", xml)
            return load(xml, *args, **kwargs)
        load(xml, *args, **kwargs)
        changed = re.sub(
            r'<Skill\b[^>]*source="Thorns"[^>]*>',
            lambda match: re.sub(r'includeInFullDPS="[^"]*"', 'includeInFullDPS="true"', match[0]),
            engine.get_xml(),
        )
        return load(changed, *args, **kwargs)

    monkeypatch.setattr(engine, "load_build_xml", alter_input)
    result = craftopt.optimize_item_sockets(
        engine, slot=slot, socket_count=1, goals={"TotalDPS": 1}
    )
    assert result["ok"] is False
    assert result["errorCode"] == "socket_probe_non_item_inputs_changed"
    assert result["decision"] == "measurement_error"
    assert build_state_hash(engine.get_xml()) == build_state_hash(before)


def test_perfect_essence_socket_receipt_keeps_source_and_trusted_equip_round_trip(
    engine, monkeypatch
):
    _start(engine, "Sorceress")
    slot = "Body Armour"
    engine.add_item(craftopt._bare("Sacramental Robe", 82), slot=slot)
    essence = next(
        option
        for option in engine.crafting_options(slot)["essences"]
        if option["name"] == "Perfect Essence of the Body"
    )
    line = craftopt._roll(essence["stat"], "realistic")
    raw = craftopt._build_item("Sacramental Robe", [line], [], None, 82)
    engine.unequip_item(slot)
    engine.add_item(raw, slot=slot)
    actual = completeness.equipped_item_text(engine.get_xml(), slot)
    prepared = craft_receipts.prepare_receipt(
        raw,
        canonical_item_text=actual,
        slot=slot,
        item_level=82,
        perfect_essences=[
            {
                "line": line,
                "name": essence["name"],
                "group": essence["group"],
                "affixType": "prefix",
                "option": essence,
            }
        ],
        runtime_context=craft_receipts.current_runtime_context(engine.info),
    )
    original = craft_receipts.persist_receipt(prepared)
    assert equipment.equip_item_verified(
        engine, raw=raw, slot=slot, craft_receipt_ref=original["craftReceiptRef"]
    )["readbackVerified"]
    _only_iron(engine, monkeypatch, slot)
    before = build_state_hash(engine.get_xml())
    result = craftopt.optimize_item_sockets(
        engine, slot=slot, socket_count=1, goals={"EnergyShield": 1}
    )
    assert result["ok"] and result["changed"], result
    assert build_state_hash(engine.get_xml()) == before
    receipt = craft_receipts.read_receipt(result["craftReceiptRef"])
    assert receipt["sources"]["perfectEssences"] == prepared["sources"]["perfectEssences"]
    assert receipt["sourceDerivation"]["sourceReceiptRef"] == original["craftReceiptRef"]
    equipped = equipment.equip_item_verified(
        engine, raw=result["item"], slot=slot, craft_receipt_ref=result["craftReceiptRef"]
    )
    assert equipped["readbackVerified"], equipped
    audit = item_legality.audit_item(
        completeness.equipped_item_text(engine.get_xml(), slot),
        slot=slot,
        craft_receipt_ref=result["craftReceiptRef"],
        require_special_provenance=True,
    )
    assert audit["ok"] and audit["provenanceStatus"] == "verified"
    assert audit["specialSources"] == {
        "perfectEssenceCount": 1,
        "runeCount": 1,
        "corruptionVerified": False,
    }


@pytest.mark.parametrize("batch", [False, True])
def test_waiting_socket_request_rechecks_recovery_gate_without_reading_or_clearing_residual(
    monkeypatch, batch
):
    class Engine:
        def __init__(self):
            self.lock = threading.RLock()
            self.waiting = threading.Event()
            self.xml = '<PathOfBuilding2><Build level="90"/></PathOfBuilding2>'

        def transaction_lock(self):
            engine = self

            class Guard:
                def __enter__(self):
                    engine.waiting.set()
                    engine.lock.acquire()

                def __exit__(self, *_):
                    engine.lock.release()

            return Guard()

        def get_xml(self):
            pytest.fail("a queued socket request must not read a recovery-blocked snapshot")

    engine = Engine()
    result = {}
    monkeypatch.setattr(
        craftopt, "_optimize_item_sockets_locked", lambda *_a, **_k: pytest.fail("probe ran")
    )

    def request():
        if batch:
            result.update(
                craftopt.plan_item_sockets_batch(
                    engine, slot_socket_counts={"Helmet": 1}, goals={"Life": 1}
                )
            )
        else:
            result.update(
                craftopt.optimize_item_sockets(
                    engine, slot="Helmet", goals={"Life": 1}, socket_count=1
                )
            )

    with engine.lock:
        worker = threading.Thread(target=request)
        worker.start()
        assert engine.waiting.wait(5)
        engine.xml = engine.xml.replace('level="90"', 'level="91"')
        engine._poe2_mutation_batch_recovery_required = True
        residual = engine.xml
    worker.join(5)
    assert not worker.is_alive()
    assert result == {
        "ok": False,
        "errorCode": "build_state_recovery_required",
        "recoveryRequired": True,
    }
    assert engine._poe2_mutation_batch_recovery_required is True
    assert engine.xml == residual
    assert craftopt.socket_batch_decisions_for_state(engine, build_state_hash(residual)) == {}


def test_socket_xml_splice_preserves_source_attributes_metadata_and_non_target_bytes():
    before = (
        '<PathOfBuilding2><Items activeItemSet="1"><Item id="7">old'
        '<ModRange id="1" range="0.5"/></Item><Item id="9">other</Item>'
        '<ItemSet id="1"><Slot name="Weapon 1" itemId="7"/></ItemSet></Items>'
        '<Skills><Skill source="Item:7" label="literal\n&#10;&amp;"/></Skills></PathOfBuilding2>'
    )
    after = socket_probe.replace_equipped_item(before, "Weapon 1", "new & raw")
    assert after == before.replace(">old<ModRange", ">\nnew &amp; raw\n<ModRange")
