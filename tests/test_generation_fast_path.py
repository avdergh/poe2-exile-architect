from __future__ import annotations

from contextlib import contextmanager
import xml.etree.ElementTree as ET

import pytest

from server.compute import mutation_batch
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
            items = ET.SubElement(root, "Items")
        for item in list(items):
            if item.get("slot") == slot:
                items.remove(item)
        ET.SubElement(items, "Item", {"slot": slot, "name": raw[:80]})
        self.xml = ET.tostring(root, encoding="unicode")
        if "Wrong Wand" in raw:
            self._set_build_attributes(weaponCompatible="false")
        return {"ok": True, "slot": slot}

    def unequip_item(self, slot: str) -> dict[str, object]:
        root = ET.fromstring(self.xml)
        items = root.find("Items")
        if items is not None:
            for item in list(items):
                if item.get("slot") == slot:
                    items.remove(item)
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
        groups = []
        if main_skill:
            groups.append({"activeSkill": main_skill})
        groups.extend(
            {"activeSkill": group.get("name")} for group in root.findall("./SkillGroups/SkillGroup")
        )
        return {"groups": groups}

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
                raw="Wrong Wand",
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
