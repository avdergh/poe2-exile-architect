from __future__ import annotations

from contextlib import contextmanager
import xml.etree.ElementTree as ET

import pytest

from server.compute import mutation_batch, supportopt
from server.compute.state import build_state_hash
from server.generation import validation_checkpoint


class FakeMutationEngine:
    def __init__(self) -> None:
        self.xml = '<PathOfBuilding2><Build className="Monk" level="1"/></PathOfBuilding2>'
        self.fail_rollback = False

    @contextmanager
    def transaction_lock(self):
        yield

    def get_xml(self) -> str:
        return self.xml

    def load_build_xml(self, xml: str, name: str = "") -> dict[str, object]:
        if self.fail_rollback and "rollback" in name:
            raise RuntimeError("fixture rollback failure")
        self.xml = xml
        return {"ok": True, "name": name}

    def new_build(self) -> dict[str, object]:
        self.xml = '<PathOfBuilding2><Build className="None" level="1"/></PathOfBuilding2>'
        return {"ok": True}

    def set_class(self, class_name: str, ascendancy: str | None = None) -> dict[str, object]:
        self._set_build_attributes(
            className=class_name,
            ascendClassName=ascendancy or "None",
        )
        return {"ok": True, "class": class_name, "ascendancy": ascendancy or "None"}

    def set_level(self, level: int) -> dict[str, object]:
        if level == 13:
            return {"ok": False, "errorCode": "fixture_level_rejected"}
        self._set_build_attributes(level=str(level))
        return {"ok": True, "level": level}

    def paste_skill(self, skill: str) -> dict[str, object]:
        main_skill = skill.splitlines()[0].split(" 20/")[0].strip()
        self._set_build_attributes(mainSkill=main_skill)
        return {"mainSkill": main_skill}

    def add_skill_group(
        self,
        skill: str,
        include_in_full_dps: bool = False,
    ) -> dict[str, object]:
        root = ET.fromstring(self.xml)
        groups = root.find("SkillGroups")
        if groups is None:
            groups = ET.SubElement(root, "SkillGroups")
        ET.SubElement(
            groups,
            "SkillGroup",
            {
                "name": skill.splitlines()[0].strip(),
                "includeInFullDPS": str(include_in_full_dps).lower(),
            },
        )
        self.xml = ET.tostring(root, encoding="unicode")
        return {"mainSkill": self._build().get("mainSkill")}

    def add_item(self, raw: str, slot: str | None = None) -> dict[str, object]:
        assert slot is not None
        root = ET.fromstring(self.xml)
        items = root.find("Items")
        if items is None:
            items = ET.SubElement(root, "Items", {"activeItemSet": "1"})
        item_set = items.find("ItemSet")
        if item_set is None:
            item_set = ET.SubElement(items, "ItemSet", {"id": "1"})
        for old_slot in list(item_set.findall("Slot")):
            if old_slot.get("name") == slot:
                item_set.remove(old_slot)
        next_id = max([int(item.get("id") or 0) for item in items.findall("Item")] or [0]) + 1
        item = ET.SubElement(items, "Item", {"id": str(next_id)})
        item.text = raw
        ET.SubElement(item_set, "Slot", {"name": slot, "itemId": str(next_id)})
        self.xml = ET.tostring(root, encoding="unicode")
        if "Wrong Wand" in raw:
            self._set_build_attributes(weaponCompatible="false")
        return {"ok": True, "slot": slot}

    def unequip_item(self, slot: str) -> dict[str, object]:
        root = ET.fromstring(self.xml)
        items = root.find("Items")
        if items is not None:
            item_set = items.find("ItemSet")
            if item_set is not None:
                for old_slot in list(item_set.findall("Slot")):
                    if old_slot.get("name") == slot:
                        item_set.remove(old_slot)
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True, "slot": slot}

    def equip_jewel(
        self,
        raw: str,
        socket: int | None = None,
    ) -> dict[str, object]:
        assert socket is not None
        root = ET.fromstring(self.xml)
        ET.SubElement(root, "Jewel", {"socket": str(socket), "name": raw[:80]})
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True, "socket": socket}

    def alloc_passive(self, node: str | int) -> dict[str, object]:
        root = ET.fromstring(self.xml)
        ET.SubElement(root, "Passive", {"node": str(node)})
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True, "node": {"id": node}, "pointsSpent": 1}

    def dealloc_passive(self, node: str | int) -> dict[str, object]:
        root = ET.fromstring(self.xml)
        for passive in list(root.findall("Passive")):
            if passive.get("node") == str(node):
                root.remove(passive)
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True, "node": {"id": node}, "pointsFreed": 1}

    def set_config(
        self,
        options=None,
        custom_mods=None,
    ) -> dict[str, object]:
        root = ET.fromstring(self.xml)
        config = root.find("Config")
        if config is None:
            config = ET.SubElement(root, "Config")
        for key, value in (options or {}).items():
            config.set(str(key), str(value))
        if custom_mods is not None:
            config.set("customMods", custom_mods)
        self.xml = ET.tostring(root, encoding="unicode")
        return {"stats": {}}

    def get_build(self) -> dict[str, object]:
        build = self._build()
        compatible = build.get("weaponCompatible") != "false"
        return {
            "class": build.get("className"),
            "ascendancy": build.get("ascendClassName", "None"),
            "level": int(build.get("level", "1")),
            "mainSkill": build.get("mainSkill"),
            "mainSkillWeaponCheck": {
                "skillName": build.get("mainSkill"),
                "weaponTypes": ["Quarterstaff"],
                "equippedWeaponTypes": ["Wand"] if not compatible else ["Quarterstaff"],
                "compatible": compatible,
            },
        }

    def call(self, method: str):
        assert method == "list_skill_groups"
        root = ET.fromstring(self.xml)
        main_skill = self._build().get("mainSkill")
        names = []
        if main_skill:
            names.append(main_skill)
        names.extend(group.get("name") for group in root.findall("./SkillGroups/SkillGroup"))
        groups = [
            {
                "index": index,
                "activeSkill": name,
                "gems": [{"name": name}],
            }
            for index, name in enumerate(names, start=1)
            if name
        ]
        return {"mainGroupIndex": 1 if groups else 0, "groups": groups}

    def _set_build_attributes(self, **attributes: str) -> None:
        root = ET.fromstring(self.xml)
        build = root.find("Build")
        assert build is not None
        for key, value in attributes.items():
            build.set(key, value)
        self.xml = ET.tostring(root, encoding="unicode")

    def _build(self) -> dict[str, str]:
        root = ET.fromstring(self.xml)
        build = root.find("Build")
        assert build is not None
        return dict(build.attrib)


def test_mutation_batch_applies_exact_operations_and_returns_state_hashes():
    engine = FakeMutationEngine()
    before = build_state_hash(engine.get_xml())
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
                ascendancy="Martial Artist",
            ),
            mutation_batch.BuildMutationOperation(operation="set_level", level=18),
        ],
        expected_state_hash=before,
    )

    assert result["status"] == "applied"
    assert result["operationCount"] == 3
    assert result["inputStateHash"] == before
    assert result["outputStateHash"] == build_state_hash(engine.get_xml())
    assert result["changed"] is True
    assert result["optimizerOperationsAllowed"] is False


def test_mutation_batch_rolls_back_the_whole_batch_on_one_failed_step():
    engine = FakeMutationEngine()
    original = engine.get_xml()
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
                ascendancy="Martial Artist",
            ),
            mutation_batch.BuildMutationOperation(operation="set_level", level=13),
        ],
    )

    assert result["errorCode"] == "fixture_level_rejected"
    assert result["failedOperationIndex"] == 2
    assert result["rolledBack"] is True
    assert engine.get_xml() == original


def test_mutation_batch_rejects_stale_state_and_optimizer_operations():
    engine = FakeMutationEngine()
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="config",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="set_config",
                options={"enemyIsBoss": "Boss"},
            )
        ],
        expected_state_hash="sha256:stale",
    )
    assert result["errorCode"] == "build_state_conflict"

    with pytest.raises(ValueError):
        mutation_batch.BuildMutationOperation.model_validate({"operation": "optimize_build"})


def test_mutation_batch_rejects_a_late_or_repeated_reset_without_touching_state():
    engine = FakeMutationEngine()
    original = engine.get_xml()

    late = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
                ascendancy="Martial Artist",
            ),
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(operation="set_level", level=18),
        ],
    )
    repeated = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
            ),
        ],
    )

    assert late["errorCode"] == "mutation_batch_reset_must_be_first"
    assert repeated["errorCode"] == "mutation_batch_reset_must_be_first"
    assert engine.get_xml() == original


def test_functional_batches_reject_mixed_scopes_and_require_chained_state_hash():
    engine = FakeMutationEngine()
    mixed = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="passive_delta",
        operations=[
            mutation_batch.BuildMutationOperation(operation="allocate_passive", node=101),
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nTest\nRuby Ring",
                slot="Ring 1",
            ),
        ],
        expected_state_hash=build_state_hash(engine.get_xml()),
    )
    missing_hash = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="ordinary_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nTest\nRuby Ring",
                slot="Ring 1",
            )
        ],
    )

    assert mixed["errorCode"] == "mutation_batch_scope_operation_invalid"
    assert missing_hash["errorCode"] == "mutation_batch_expected_state_hash_required"
    assert mixed["stateChanged"] is False
    assert missing_hash["stateChanged"] is False


def test_mechanism_shell_rolls_back_when_weapon_postcondition_fails():
    engine = FakeMutationEngine()
    before = engine.get_xml()
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="mechanism_shell",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="set_main_skill",
                skill="Storm Wave",
            ),
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nWrong Wand\nWithered Wand\nItem Level: 80",
                slot="Weapon 1",
            ),
        ],
        expected_state_hash=build_state_hash(before),
    )

    assert result["errorCode"] == "mutation_batch_mechanism_weapon_incompatible"
    assert result["failedOperation"] == "scope_postconditions"
    assert result["rolledBack"] is True
    assert result["persistedOperationCount"] == 0
    assert engine.get_xml() == before


def test_gear_batch_rejects_deterministic_illegal_affixes_and_restores():
    engine = FakeMutationEngine()
    before = engine.get_xml()

    def decorate(_operation, result):
        result["illegalAffixes"] = ["invented affix"]
        return result

    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nImpossible Ring\nRuby Ring",
                slot="Ring 1",
            )
        ],
        expected_state_hash=build_state_hash(before),
        result_decorator=decorate,
    )

    assert result["errorCode"] == "mutation_batch_item_legality_rejected"
    assert result["failureDetails"]["illegalAffixCount"] == 1
    assert result["rolledBack"] is True
    assert engine.get_xml() == before


def test_failed_rollback_marks_session_recovery_required():
    engine = FakeMutationEngine()
    before_hash = build_state_hash(engine.get_xml())
    engine.fail_rollback = True
    result = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
                ascendancy="Martial Artist",
            ),
            mutation_batch.BuildMutationOperation(operation="set_level", level=13),
        ],
        expected_state_hash=before_hash,
    )

    assert result["rolledBack"] is False
    assert result["atomic"] is False
    assert result["recoveryRequired"] is True
    assert result["persistedOperationCount"] is None

    blocked = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="config",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="set_config",
                options={"enemyIsBoss": "Boss"},
            )
        ],
        expected_state_hash=before_hash,
    )
    assert blocked["errorCode"] == "mutation_batch_recovery_required"
    assert blocked["recoveryAction"] == "run_bootstrap_from_new_build"

    recovered = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="bootstrap",
        operations=[
            mutation_batch.BuildMutationOperation(operation="new_build"),
            mutation_batch.BuildMutationOperation(
                operation="set_class",
                class_name="Monk",
            ),
            mutation_batch.BuildMutationOperation(operation="set_level", level=18),
        ],
    )
    assert recovered["ok"] is True
    assert recovered["recoveryRequired"] is False


def test_gear_and_passive_batches_enforce_small_scope_contracts():
    engine = FakeMutationEngine()
    current_hash = build_state_hash(engine.get_xml())
    implicit_slot = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="ordinary_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nTest\nRuby Ring",
            )
        ],
        expected_state_hash=current_hash,
    )
    too_many_required_items = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="unequip_item",
                slot=slot,
            )
            for slot in ("Ring 1", "Ring 2", "Amulet", "Belt", "Boots")
        ],
        expected_state_hash=current_hash,
    )
    duplicate_slot = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="ordinary_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw="Rarity: Rare\nTest\nRuby Ring",
                slot="Ring 1",
            ),
            mutation_batch.BuildMutationOperation(
                operation="unequip_item",
                slot="Ring 1",
            ),
        ],
        expected_state_hash=current_hash,
    )
    oversized_payload = mutation_batch.apply_build_mutation_batch(
        engine,
        batch_kind="required_gear",
        operations=[
            mutation_batch.BuildMutationOperation(
                operation="equip_item",
                raw=f"Rarity: Rare\nLarge Test\nRuby Ring\n{'x' * 35_000}",
                slot=slot,
            )
            for slot in ("Ring 1", "Ring 2", "Amulet", "Belt")
        ],
        expected_state_hash=current_hash,
    )

    assert implicit_slot["errorCode"] == "mutation_batch_explicit_item_slot_required"
    assert too_many_required_items["errorCode"] == "mutation_batch_scope_size_invalid"
    assert too_many_required_items["scopeOperationLimit"] == 4
    assert duplicate_slot["errorCode"] == "mutation_batch_duplicate_selector"
    assert oversized_payload["errorCode"] == "mutation_batch_payload_too_large"
    assert oversized_payload["maximumPayloadBytes"] == 128_000


class FakeCheckpointEngine:
    def __init__(self) -> None:
        self.xml = '<PathOfBuilding2><Build className="Monk" level="18"/></PathOfBuilding2>'
        self.calls = {"build": 0, "stats": 0, "defenses": 0}

    @contextmanager
    def transaction_lock(self):
        yield

    def get_xml(self) -> str:
        return self.xml

    def get_build(self) -> dict[str, object]:
        self.calls["build"] += 1
        return {
            "class": "Monk",
            "ascendancy": "None",
            "level": 18,
            "mainSkill": "Ice Strike",
        }

    def get_stats(self, _keys) -> dict[str, object]:
        self.calls["stats"] += 1
        return {"stats": {"TotalDPS": 1234, "Life": 500}}

    def get_defenses(self) -> dict[str, object]:
        self.calls["defenses"] += 1
        return {"totalEHP": 900}


def test_generation_checkpoint_reuses_validation_for_the_same_semantic_hash(monkeypatch):
    engine = FakeCheckpointEngine()
    validation_checkpoint.clear_validation_checkpoint_cache()
    completeness_calls = {"count": 0}
    preflight_calls = {"count": 0}

    def fake_completeness(_engine, *, snapshot_xml):
        completeness_calls["count"] += 1
        assert snapshot_xml == engine.xml
        return {
            "status": "needs_attention",
            "hardFailures": [],
            "advisories": ["optional_quality_polish"],
        }

    def fake_preflight(_engine, xml, *, completeness_result):
        preflight_calls["count"] += 1
        assert xml == engine.xml
        assert completeness_result["status"] == "needs_attention"
        return {
            "status": "needs_attention",
            "readyForJudge": True,
            "qualityAdvisories": ["optional_quality_polish"],
            "advisories": ["optional_quality_polish"],
            "completeness": completeness_result,
        }

    monkeypatch.setattr(
        validation_checkpoint.completeness,
        "inspect_build_completeness",
        fake_completeness,
    )
    monkeypatch.setattr(
        validation_checkpoint.preflight,
        "inspect_generation_snapshot",
        fake_preflight,
    )

    first = validation_checkpoint.inspect_generation_checkpoint(engine)
    second = validation_checkpoint.inspect_generation_checkpoint(engine)
    strict = validation_checkpoint.inspect_generation_checkpoint(engine, strict_mode=True)

    assert first["cacheHit"] is False
    assert second["cacheHit"] is True
    assert first["feedbackMode"] == "hard_only"
    assert first["subjectiveFeedbackSuppressed"] is True
    assert first["qualityAdvisories"] == []
    assert first["completeness"]["advisories"] == []
    assert strict["cacheHit"] is True
    assert strict["feedbackMode"] == "strict"
    assert strict["subjectiveFeedbackSuppressed"] is False
    assert strict["qualityAdvisories"] == ["optional_quality_polish"]
    assert first["validationRef"] == second["validationRef"]
    assert completeness_calls["count"] == 1
    assert preflight_calls["count"] == 1
    assert engine.calls == {"build": 1, "stats": 1, "defenses": 1}

    engine.xml = engine.xml.replace('level="18"', 'level="19"')
    third = validation_checkpoint.inspect_generation_checkpoint(engine)
    assert third["cacheHit"] is False
    assert third["validationRef"] != first["validationRef"]
    assert completeness_calls["count"] == 2


def test_endgame_quality_checklist_keeps_unassessed_systems_at_candidate(monkeypatch):
    monkeypatch.setattr(
        validation_checkpoint.supportopt,
        "support_audit_for_state",
        lambda _engine, _state_hash, _group_index: None,
    )
    monkeypatch.setattr(
        validation_checkpoint.itemopt,
        "next_jewel_decision_for_state",
        lambda _engine, _state_hash: None,
    )
    monkeypatch.setattr(
        validation_checkpoint.craftopt,
        "socket_batch_decisions_for_state",
        lambda _engine, _state_hash: {},
    )
    checklist = validation_checkpoint._create_quality_checklist(
        engine=object(),
        xml='<PathOfBuilding><Build className="Mercenary" level="95"/></PathOfBuilding>',
        state_hash="sha256:test",
        build={
            "level": 95,
            "gear": {
                "Weapon 1": {"rarity": "Normal", "base": "Makeshift Crossbow"},
                "Flask 1": {"rarity": "Normal", "name": "Life Flask"},
                "Charm 1": {"rarity": "Normal", "name": "Amethyst Charm"},
            },
        },
        stats={"ManaCost": 10, "Speed": 2, "ManaRegenRecovery": 0, "Mana": 100},
        completeness_result={
            "scaffoldSlots": [],
            "unverifiedSpecialSourceSlots": [],
            "runes": {"decisionRequiredSlots": ["Weapon 1"]},
            "passiveJewels": {
                "availableSockets": 3,
                "allocatedSockets": 2,
                "filledSockets": 2,
            },
            "flasks": {
                "expectedSlots": ["Flask 1", "Flask 2"],
                "equippedSlots": ["Flask 1"],
                "details": [
                    {
                        "slot": "Flask 1",
                        "rarity": "normal",
                        "prefixes": 0,
                        "suffixes": 0,
                    }
                ],
            },
            "charms": {"beltCapacity": 3, "equippedSlots": ["Charm 1"]},
        },
        preflight_result={
            "skillGroups": [
                {
                    "groupIndex": 1,
                    "role": "pob_main_group",
                    "activeSkills": ["Stormblast Bolts"],
                    "supports": [],
                    "source": None,
                }
            ]
        },
    )

    assert checklist["skillSupportAudit"]["status"] == "failed"
    assert checklist["bootstrapItems"]["status"] == "failed"
    assert checklist["charmLoadout"]["status"] == "failed"
    assert checklist["jewelDecision"]["status"] == "failed"
    assert checklist["itemSockets"]["status"] == "failed"
    assert checklist["sustain"]["status"] == "failed"
    repair = validation_checkpoint._quality_repair_plan(checklist)
    assert {entry["check"] for entry in repair} >= {
        "skillSupportAudit",
        "charmLoadout",
        "jewelDecision",
        "itemSockets",
        "sustain",
    }


def test_checkpoint_cache_refreshes_session_local_quality_audits(monkeypatch):
    from test_tree_source_skill_supports import _complete_support_measurement

    engine = FakeCheckpointEngine()
    engine.xml = """<PathOfBuilding><Build className="Mercenary" level="95" mainSocketGroup="1"/>
    <Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true">
    <Gem nameSpec="Stormblast Bolts" gemId="Metadata/Items/Gem/SkillGemStormblastBolts"
    skillId="StormblastBoltsPlayer"/></Skill></SkillSet></Skills></PathOfBuilding>"""
    engine.get_build = lambda: {
        "class": "Mercenary",
        "ascendancy": "Tactician",
        "level": 95,
        "mainSkill": "Stormblast Bolts",
        "gear": {},
    }
    engine.get_stats = lambda _keys: {
        "stats": {
            "ManaCost": 0,
            "Speed": 1,
            "Life": 1000,
            "TotalEHP": 1000,
        }
    }
    engine.get_defenses = lambda: {"totalEHP": 1000, "resistances": {}}
    complete = {
        "hardFailures": [],
        "advisories": [],
        "scaffoldSlots": [],
        "unverifiedSpecialSourceSlots": [],
        "runes": {"decisionRequiredSlots": []},
        "passiveJewels": {"availableSockets": 0, "allocatedSockets": 0, "filledSockets": 0},
        "flasks": {"expectedSlots": [], "equippedSlots": [], "details": []},
        "charms": {"beltCapacity": 0, "equippedSlots": []},
    }
    preflight_result = {
        "readyForJudge": True,
        "hardLegalityReady": True,
        "mechanismReady": True,
        "readinessReady": True,
        "skillGroups": [
            {
                "groupIndex": 1,
                "role": "pob_main_group",
                "activeSkills": ["Stormblast Bolts"],
                "supports": [],
                "source": None,
            }
        ],
        "hardLegality": {"status": "passed", "hardLegalityReady": True},
    }
    audit = {"value": None}
    monkeypatch.setattr(
        validation_checkpoint.completeness,
        "inspect_build_completeness",
        lambda *_args, **_kwargs: complete,
    )
    monkeypatch.setattr(
        validation_checkpoint.preflight,
        "inspect_generation_snapshot",
        lambda *_args, **_kwargs: preflight_result,
    )
    monkeypatch.setattr(
        validation_checkpoint.supportopt,
        "support_audit_for_state",
        lambda _engine, _state_hash, _group_index: audit["value"],
    )
    monkeypatch.setattr(
        validation_checkpoint.supportopt,
        "support_audit_freshness",
        lambda _engine, _state_hash, _group_index: (
            "current" if audit["value"] is not None else "missing"
        ),
    )
    monkeypatch.setattr(
        validation_checkpoint.itemopt,
        "next_jewel_decision_for_state",
        lambda _engine, _state_hash: None,
    )
    monkeypatch.setattr(
        validation_checkpoint.craftopt,
        "socket_batch_decisions_for_state",
        lambda _engine, _state_hash: {},
    )
    validation_checkpoint.clear_validation_checkpoint_cache()

    before = validation_checkpoint.inspect_generation_checkpoint(engine)
    audit["value"] = {
        "auditVersion": "support_audit_v3",
        "status": "passed",
        "groupIndex": 1,
        "activeSkillIndex": 1,
        "skill": "Stormblast Bolts",
        "currentSupports": [],
        "recommendedSupports": [],
        "positiveGainSupportsMissing": [],
        "measurement": _complete_support_measurement(),
    }
    after = validation_checkpoint.inspect_generation_checkpoint(engine)

    assert before["createQualityChecklist"]["skillSupportAudit"]["status"] == "failed"
    assert after["cacheHit"] is True
    assert after["createQualityChecklist"]["skillSupportAudit"]["status"] == "passed"


def test_unknown_quality_check_keeps_delivery_candidate(monkeypatch):
    monkeypatch.setattr(
        validation_checkpoint,
        "_create_quality_checklist",
        lambda **_kwargs: {
            "jewelDecision": {
                "status": "unknown",
                "reasons": ["selected_candidate_socket_policy_limited"],
            }
        },
    )
    result = {
        "readyForJudge": True,
        "lifecycleVerification": {"pass": True},
        "completeness": {},
        "preflight": {},
        "_checkpointInputs": {"build": {}, "stats": {}},
    }

    validation_checkpoint._refresh_dynamic_quality(
        result,
        engine=object(),
        xml="<PathOfBuilding />",
        state_hash="sha256:test",
    )

    assert result["deliveryStatus"] == "candidate"


@pytest.mark.parametrize("extra_reason", [None, "declared_duration_dot_model_missing"])
def test_support_capability_gap_is_unknown_with_group_evidence(extra_reason):
    engine = FakeCheckpointEngine()
    state_hash = build_state_hash(engine.get_xml())
    supportopt._record_support_audit(
        engine=engine,
        state_hash=state_hash,
        group_index=1,
        skill="Cast on Critical",
        current_supports=[],
        recommended_supports=[],
        constraints={},
        active_skill_index=1,
        capability={
            "capabilitySource": "pob_runtime",
            "applicationCheck": "verified",
            "numericRanking": "unsupported",
            "triggerRate": "unmodelled",
            "reasonCodes": ["trigger_rate_unmodelled"] + ([extra_reason] if extra_reason else []),
        },
        measurement={
            "status": "inconclusive",
            "checkpointEligible": False,
            "reasonClass": "capability_gap",
            "reasonCodes": ["trigger_rate_unmodelled"],
            "coverageComplete": True,
            "classificationComplete": True,
            "failedCandidates": 0,
            "failedCombinations": 0,
            "finalConstraintsSatisfied": True,
        },
    )

    checklist = validation_checkpoint._create_quality_checklist(
        engine=engine,
        xml=engine.get_xml(),
        state_hash=state_hash,
        build={"level": 95, "gear": {}},
        stats={},
        completeness_result={
            "passiveJewels": {
                "availableSockets": 0,
                "allocatedSockets": 0,
                "filledSockets": 0,
            },
            "runes": {"decisionRequiredSlots": []},
            "flasks": {"expectedSlots": [], "equippedSlots": [], "details": []},
            "charms": {"beltCapacity": None, "equippedSlots": []},
        },
        preflight_result={
            "skillGroups": [
                {
                    "groupIndex": 1,
                    "mainActiveSkillCalcs": 1,
                    "activeSkills": ["Cast on Critical"],
                    "source": None,
                    "sourceKind": None,
                    "noSupports": False,
                }
            ]
        },
    )

    support = checklist["skillSupportAudit"]
    assert support["status"] == ("failed" if extra_reason else "unknown")
    assert support["verificationRequired"] is (extra_reason is None)
    if extra_reason is None:
        assert support["groupResults"][0]["reasonClass"] == "capability_gap"


class _TargetGroupCheckpointEngine:
    def __init__(self) -> None:
        self.selected_group = 1
        self.xml = """<PathOfBuilding><Build className="Mercenary" level="95" mainSocketGroup="1"/>
        <Skills activeSkillSet="1"><SkillSet id="1">
        <Skill enabled="true"><Gem nameSpec="Galvanic Shards"
        gemId="Metadata/Items/Gem/SkillGemGalvanicShards" skillId="GalvanicShardsPlayer"/></Skill>
        <Skill enabled="true"><Gem nameSpec="Stormblast Bolts"
        gemId="Metadata/Items/Gem/SkillGemStormblastBolts" skillId="StormblastBoltsPlayer"/></Skill>
        </SkillSet></Skills></PathOfBuilding>"""

    @contextmanager
    def transaction_lock(self):
        yield

    def get_xml(self):
        return self.xml

    def get_build(self):
        return {
            "class": "Mercenary",
            "ascendancy": "Tactician",
            "level": 95,
            "mainSkill": "Galvanic Shards",
            "gear": {},
        }

    def get_stats(self, _keys):
        return {
            "stats": {
                "ManaCost": 5 if self.selected_group == 1 else 50,
                "Speed": 1,
                "ManaRegenRecovery": 10,
                "Mana": 100,
                "Life": 1000,
                "TotalEHP": 1000,
            }
        }

    def get_defenses(self):
        return {"totalEHP": 1000, "resistances": {}}

    def call(self, method, **params):
        assert method == "set_skill_group_state"
        self.selected_group = int(params["index"])
        return {"ok": True}

    def load_build_xml(self, xml, name=""):
        del name
        self.xml = xml
        self.selected_group = 1
        return {"ok": True}


def test_checkpoint_sustain_stats_follow_explicit_boss_skill_group(monkeypatch):
    engine = _TargetGroupCheckpointEngine()
    complete = {
        "hardFailures": [],
        "advisories": [],
        "scaffoldSlots": [],
        "unverifiedSpecialSourceSlots": [],
        "runes": {"decisionRequiredSlots": []},
        "passiveJewels": {"availableSockets": 0, "allocatedSockets": 0, "filledSockets": 0},
        "flasks": {"expectedSlots": [], "equippedSlots": [], "details": []},
        "charms": {"beltCapacity": 0, "equippedSlots": []},
    }
    groups = [
        {
            "groupIndex": 1,
            "role": "pob_main_group",
            "activeSkills": ["Galvanic Shards"],
            "supports": [],
            "source": None,
        },
        {
            "groupIndex": 2,
            "role": "additional_skill_group",
            "activeSkills": ["Stormblast Bolts"],
            "supports": [],
            "source": None,
        },
    ]
    monkeypatch.setattr(
        validation_checkpoint.completeness,
        "inspect_build_completeness",
        lambda *_args, **_kwargs: complete,
    )
    monkeypatch.setattr(
        validation_checkpoint.preflight,
        "inspect_generation_snapshot",
        lambda *_args, **_kwargs: {
            "readyForJudge": True,
            "hardLegalityReady": True,
            "mechanismReady": True,
            "readinessReady": True,
            "skillGroups": groups,
            "hardLegality": {"status": "passed", "hardLegalityReady": True},
        },
    )
    monkeypatch.setattr(
        validation_checkpoint.supportopt,
        "support_audit_for_state",
        lambda *_args: {"status": "passed", "positiveGainSupportsMissing": []},
    )
    validation_checkpoint.clear_validation_checkpoint_cache()

    boss = validation_checkpoint.inspect_generation_checkpoint(
        engine,
        offense_skill_group_index=2,
        expected_skill_name="Stormblast Bolts",
    )
    clear = validation_checkpoint.inspect_generation_checkpoint(
        engine,
        offense_skill_group_index=1,
        expected_skill_name="Galvanic Shards",
    )

    assert boss["stats"]["ManaCost"] == 50
    assert boss["calculationContext"]["groupIndex"] == 2
    assert clear["stats"]["ManaCost"] == 5
    assert engine.selected_group == 1


def test_checkpoint_selects_explicit_active_skill_inside_current_main_group():
    class SameGroupEngine:
        def __init__(self):
            self.active_index = 1
            self.xml = '<PathOfBuilding><Build className="Mercenary" level="95"/></PathOfBuilding>'

        def get_xml(self):
            return self.xml

        def get_stats(self, _keys):
            return {"stats": {"ManaCost": 5 if self.active_index == 1 else 50}}

        def call(self, method, **params):
            assert method == "set_skill_group_state"
            self.active_index = int(params["activeSkillIndex"])
            return {"ok": True}

        def load_build_xml(self, xml, name=""):
            del name
            self.xml = xml
            self.active_index = 1
            return {"ok": True}

    engine = SameGroupEngine()
    stats, context = validation_checkpoint._read_target_skill_stats(
        engine,
        xml=engine.get_xml(),
        preflight_result={
            "skillGroups": [
                {
                    "groupIndex": 1,
                    "role": "pob_main_group",
                    "activeSkills": ["Clear Skill", "Boss Skill"],
                }
            ]
        },
        offense_skill_group_index=1,
        expected_skill_name="Boss Skill",
    )

    assert context["activeIndex"] == 2
    assert stats["stats"]["ManaCost"] == 50
    assert engine.active_index == 1


def test_checkpoint_selector_restore_failure_sets_recovery_gate():
    class RestoreFailureEngine:
        def __init__(self):
            self.xml = (
                '<PathOfBuilding><Build className="Mercenary" level="95" '
                'mainSocketGroup="1"/></PathOfBuilding>'
            )

        def get_xml(self):
            return self.xml

        def call(self, method, **params):
            assert method == "set_skill_group_state"
            assert params["activeSkillIndex"] == 2
            self.xml = self.xml.replace('mainSocketGroup="1"', 'mainSocketGroup="2"')
            return {"ok": True}

        def get_stats(self, _keys):
            return {"stats": {"ManaCost": 50}}

        def load_build_xml(self, xml, name=""):
            del xml, name
            raise RuntimeError("restore failed")

    engine = RestoreFailureEngine()
    result, context = validation_checkpoint._read_target_skill_stats(
        engine,
        xml=engine.get_xml(),
        preflight_result={
            "skillGroups": [
                {
                    "groupIndex": 1,
                    "role": "pob_main_group",
                    "activeSkills": ["Clear Skill", "Boss Skill"],
                }
            ]
        },
        offense_skill_group_index=1,
        expected_skill_name="Boss Skill",
    )

    assert context == {}
    assert result["errorCode"] == "generation_checkpoint_restore_failed"
    assert result["recoveryRequired"] is True
    assert engine._poe2_mutation_batch_recovery_required is True
