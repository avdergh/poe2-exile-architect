from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest import mock
from xml.etree import ElementTree as ET

from server.compute.engine import PobEngine
from server.compute import skillgroups, supportopt
from server.compute.state import build_state_hash
from server.generation import evaluation, models, preflight, validation_checkpoint
from server.knowledge import db


RUZHAN_SUPPORTS = [
    "Bidding III",
    "Fire Penetration II",
    "Rapid Casting II",
    "Potent Exposure",
    "Concentrated Area",
]
KELARI_SUPPORTS = [
    "Bidding III",
    "Brutality III",
    "Heft",
    "Execute II",
    "Exploit Weakness",
]
COMING_CALAMITY = """Rarity: Unique
The Coming Calamity
Heroic Armour
--------
Grants Skill: Level 20 Herald of Ash
Grants Skill: Level 20 Herald of Ice
Grants Skill: Level 20 Herald of Thunder
+70 to maximum Life
+35% to all Elemental Resistances
Herald Skills deal 75% increased Damage
Enemies in your Presence have no Elemental Resistances"""
COVENANT = """Rarity: Unique
The Covenant
Altar Robe
--------
Grants Skill: Level 14 Life Remnants
+100 to maximum Life
Skills Gain 100% of Mana Cost as Extra Life Cost"""


def _complete_support_measurement(*keys: str, current=(), recommended=()) -> dict:
    objective_keys = list(keys or ("TotalDPS",))
    positive = sorted(current) != sorted(recommended)
    return {
        "status": "complete",
        "checkpointEligible": True,
        "baseMeasurable": True,
        "currentCombinationMeasurable": True,
        "coverageComplete": True,
        "classificationComplete": True,
        "usageConditionContractVersion": 1,
        "usageConditionContracts": [],
        "supportCapacity": 5,
        "maxSupports": 5,
        "candidateLimit": 1,
        "totalRelevantCandidates": 1,
        "screenedCandidates": 1,
        "measuredCandidates": 1,
        "rejectedCandidates": 0,
        "classifiedCandidates": 1,
        "failedCandidates": 0,
        "rejectedCombinations": 0,
        "failedCombinations": 0,
        "changedCandidates": 1,
        "finalConstraintsSatisfied": True,
        "objectiveKeys": objective_keys,
        "objectiveDirections": {key: "higher" for key in objective_keys},
        "measurementKeys": objective_keys,
        "combinationComparison": {
            "status": "complete",
            "baselineSupports": list(current),
            "candidateSupports": list(recommended),
            "baselineMetrics": {key: 100 for key in objective_keys},
            "candidateMetrics": {key: 110 if positive else 100 for key in objective_keys},
            "baselineScore": 100.0,
            "candidateScore": 110.0 if positive else 100.0,
            "netGain": 10.0 if positive else 0.0,
            "baselineMeasurable": True,
            "candidateMeasurable": True,
            "candidateConstraintsSatisfied": True,
            "candidateLegalityNonRegressing": True,
            "sameContext": True,
            "positiveGainProven": positive,
        },
    }


class _AuditProbeEngine:
    def __init__(self, stats_by_support: dict[str, dict]) -> None:
        self.stats_by_support = stats_by_support
        self.xml = "<PathOfBuilding2><Build level='95'/><Skills><Skill><Gem nameSpec='Spark' level='20' quality='20'/></Skill></Skills><Items/></PathOfBuilding2>"

    @contextmanager
    def transaction_lock(self):
        yield

    def get_xml(self) -> str:
        return self.xml

    def load_build_xml(self, xml: str, **__: object) -> None:
        self.xml = xml

    def get_build(self) -> dict:
        return {"mainSkillGroup": [{"name": "Spark", "level": 20, "quality": 20}]}

    def call(self, method: str, **params: object) -> dict:
        if method == "resolve_support_gem_identity":
            return {
                "ok": True,
                "status": "resolved",
                "name": params["requestedName"],
                "gemId": "oracle:" + str(params["requestedName"]),
                "effectId": "effect:" + str(params["requestedName"]),
                "naturalMaxLevel": 1,
            }
        if method == "list_skill_groups":
            gems = ET.fromstring(self.xml).findall("./Skills/Skill/Gem")
            return {
                "mainGroupIndex": 1,
                "groups": [
                    {
                        "index": 1,
                        "source": None,
                        "sourceKind": None,
                        "noSupports": False,
                        "activeSkill": "Spark",
                        "gems": [
                            {
                                "name": gem.get("nameSpec"),
                                "level": int(gem.get("level")),
                                "quality": int(gem.get("quality")),
                                "isSupport": gem.get("nameSpec") != "Spark",
                            }
                            for gem in gems
                        ],
                    }
                ],
            }
        if method == "set_skill_group_state":
            return {"ok": True}
        if method == "inspect_support_evaluation_capability":
            return {
                "ok": True,
                "applicationCheck": "verified",
                "numericRanking": "supported",
                "triggerRate": "not_applicable",
                "capabilitySource": "pob_runtime",
                "usageConditionContractVersion": 1,
                "usageConditionContracts": [],
            }
        raise AssertionError(method)

    def get_stats(self, _keys=None) -> dict:
        result = self.paste_skill(self.xml)
        result['stats'] = {'Life': 100, 'LifeReserved': 0, 'LifeUnreserved': 100, **result['stats']}
        return result

    def probe_regular_skill_group(
        self,
        *,
        group_index,
        group_xml,
        active_skill_index,
        expected_skill_name,
        keys,
        objective_keys,
        expected_effect_id=None,
    ):
        root = ET.fromstring(self.xml)
        skills = root.find("Skills")
        skills.remove(skills.findall("Skill")[group_index - 1])
        skills.insert(group_index - 1, ET.fromstring(group_xml))
        self.xml = ET.tostring(root, encoding="unicode")
        return {
            "ok": True,
            "state": self.call("list_skill_groups"),
            "capability": self.call("inspect_support_evaluation_capability"),
            **self.get_stats(keys),
        }

    def paste_skill(self, text: str) -> dict:
        for support, stats in self.stats_by_support.items():
            if support and support in text:
                return {"stats": dict(stats)}
        return {"stats": dict(self.stats_by_support.get("", {}))}


class _TriggerAuditEngine(_AuditProbeEngine):
    def __init__(self) -> None:
        super().__init__({"": {"FullDPS": 999999.0}})

    def get_build(self) -> dict:
        return {
            "mainSkillGroup": [
                {"name": "Cast on Critical", "level": 20, "quality": 20},
                {"name": "Comet", "level": 20, "quality": 20},
            ]
        }

    def call(self, method: str, **_: object) -> dict:
        if method == "list_skill_groups":
            return {
                "mainGroupIndex": 1,
                "groups": [
                    {
                        "index": 1,
                        "source": None,
                        "sourceKind": None,
                        "noSupports": False,
                        "activeSkill": "Cast on Critical",
                        "gems": [
                            {"name": "Cast on Critical", "isSupport": False, "level": 20},
                            {"name": "Comet", "isSupport": False, "level": 20},
                        ],
                    }
                ],
            }
        if method == "set_skill_group_state":
            return {"ok": True}
        raise AssertionError(method)


class _RuntimeTriggerAuditEngine(_TriggerAuditEngine):
    def __init__(self, trigger_rate: str = "unmodelled") -> None:
        super().__init__()
        self.trigger_rate = trigger_rate

    def call(self, method: str, **kwargs: object) -> dict:
        if method == "inspect_support_evaluation_capability":
            reason = (
                "trigger_rate_unmodelled"
                if self.trigger_rate == "unmodelled"
                else "trigger_rate_zero_or_inactive"
            )
            return {
                "ok": True,
                "applicationCheck": "verified",
                "numericRanking": "unsupported",
                "triggerRate": self.trigger_rate,
                "reasonCodes": [reason],
                "capabilitySource": "pob_runtime",
                "usageConditionContractVersion": 1,
                "usageConditionContracts": [],
            }
        return super().call(method, **kwargs)


def _find_source_group(listed: dict, *, kind: str, root_skill: str | None = None,
                       source: str | None = None) -> dict:
    """Locate one actual source group without relying on auto-group ordering."""
    matches = [
        group for group in listed["groups"]
        if group.get("sourceKind") == kind
        and (source is None or group.get("source") == source)
        and (root_skill is None or group["gems"][0]["name"] == root_skill)
    ]
    if len(matches) != 1:
        raise AssertionError({"kind": kind, "source": source, "rootSkill": root_skill,
                              "matches": matches, "groups": listed["groups"]})
    return matches[0]


class TreeSourceSupportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = PobEngine()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.close()

    def _new_varashta(self, *node_ids: int) -> dict:
        self.engine.new_build()
        result = self.engine.set_class("Sorceress", "Disciple of Varashta")
        self.assertTrue(result["ok"])
        self.engine.set_level(95)
        for node_id in node_ids:
            self.assertTrue(self.engine.alloc_passive(node_id)["ok"])
        return skillgroups.list_skill_groups(self.engine)

    def _tree_group(self, node_id: int, listed: dict | None = None) -> dict:
        return _find_source_group(
            listed or skillgroups.list_skill_groups(self.engine),
            kind="tree", source=f"Tree:{node_id}",
        )

    def _select_command(self, node_id: int) -> dict:
        listed = skillgroups.list_skill_groups(self.engine)
        group = self._tree_group(node_id, listed)
        changed = skillgroups.set_skill_group_state(
            self.engine,
            group_index=group["index"],
            expected_fingerprint=group["fingerprint"],
            expected_state_hash=listed["stateHash"],
            active_skill_index=next(effect["index"] for effect in group["activeSkills"] if effect["name"] == "Command"),
            make_main=True,
        )
        self.assertTrue(changed["ok"])
        return skillgroups.list_skill_groups(self.engine)

    def _configure(self, node_id: int, supports: list[str]) -> dict:
        listed = skillgroups.list_skill_groups(self.engine)
        group = self._tree_group(node_id, listed)
        return skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=supports,
            expected_fingerprint=group["fingerprint"],
            expected_state_hash=listed["stateHash"],
        )

    def test_level_95_roots_have_five_slots_and_five_supports(self) -> None:
        listed = self._new_varashta(34207, 13289)
        self.assertEqual(sum(group.get("sourceKind") == "tree" for group in listed["groups"]), 2)
        self.assertEqual([self._tree_group(node_id, listed)["gems"][0]["level"] for node_id in (34207, 13289)], [20, 20])

        self._select_command(34207)
        ruzhan = self._configure(34207, RUZHAN_SUPPORTS)
        self.assertTrue(ruzhan["ok"])
        self.assertEqual(ruzhan["supportCapacity"], 5)
        self.assertEqual(len(ruzhan["supportApplication"]), 5)
        self.assertTrue(
            any("Command" in value["activeSkills"] for value in ruzhan["supportApplication"])
        )

        self._select_command(13289)
        kelari = self._configure(13289, KELARI_SUPPORTS)
        self.assertTrue(kelari["ok"])
        self.assertEqual(kelari["skillLevel"], 20)
        self.assertEqual(kelari["supportCapacity"], 5)

        before_xml = self.engine.get_xml()
        rejected = self._configure(13289, [*KELARI_SUPPORTS, "Muster"])
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["errorCode"], "source_support_capacity_exceeded")
        self.assertEqual(self.engine.get_xml(), before_xml)

    def test_roundtrip_preserves_source_supports_command_and_spirit(self) -> None:
        self._new_varashta(34207)
        self._select_command(34207)
        configured = self._configure(34207, RUZHAN_SUPPORTS)
        self.assertTrue(configured["ok"])
        xml = self.engine.get_xml()
        before = skillgroups.list_skill_groups(self.engine)
        before_build = self.engine.get_build()

        self.engine.load_build_xml(xml, name="tree-source-roundtrip")
        self.engine.get_stats()
        self.engine.get_stats()
        after = skillgroups.list_skill_groups(self.engine)
        after_build = self.engine.get_build()
        self.assertEqual(len(after["groups"]), len(before["groups"]))
        self.assertEqual(self._tree_group(34207, after)["source"], "Tree:34207")
        restored_group = self._tree_group(34207, after)
        self.assertEqual(
            restored_group["mainActiveSkillCalcs"],
            next(effect["index"] for effect in restored_group["activeSkills"] if effect["name"] == "Command"),
        )
        self.assertEqual(
            [gem["name"] for gem in self._tree_group(34207, after)["gems"]],
            [gem["name"] for gem in self._tree_group(34207, before)["gems"]],
        )
        self.assertEqual(after_build.get("spiritUsed"), before_build.get("spiritUsed"))

    def test_invalid_duplicate_family_and_stale_cas_are_atomic(self) -> None:
        listed = self._new_varashta(34207)
        original_xml = self.engine.get_xml()
        original_hash = build_state_hash(original_xml)
        group = self._tree_group(34207, listed)
        duplicate = skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=["Bidding I", "Bidding III"],
            expected_fingerprint=group["fingerprint"],
            expected_state_hash=listed["stateHash"],
        )
        self.assertEqual(duplicate["errorCode"], "duplicate_support_family")
        self.assertEqual(build_state_hash(self.engine.get_xml()), original_hash)

        unknown = skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=["Definitely Not A Support"],
            expected_fingerprint=group["fingerprint"],
            expected_state_hash=listed["stateHash"],
        )
        self.assertEqual(unknown["errorCode"], "unknown_support_gem")
        self.assertEqual(self.engine.get_xml(), original_xml)

        stale = skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=["Bidding III"],
            expected_fingerprint="skill-group:stale",
            expected_state_hash=listed["stateHash"],
        )
        self.assertEqual(stale["errorCode"], "skill_group_conflict")
        self.assertEqual(self.engine.get_xml(), original_xml)

    def test_optimizer_measures_real_tree_group_but_exploratory_metric_is_not_audit(self) -> None:
        listed = self._new_varashta(34207)
        self._select_command(34207)
        listed = skillgroups.list_skill_groups(self.engine)
        original_xml = self.engine.get_xml()
        original_hash = build_state_hash(original_xml)
        result = supportopt.optimize_supports(
            self.engine,
            metric="ReqInt",
            max_supports=1,
            candidates=4,
            screen=4,
            group_index=self._tree_group(34207, listed)["index"],
            expected_fingerprint=self._tree_group(34207, listed)["fingerprint"],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "Tree:34207")
        self.assertEqual(result["skill"], "Command")
        self.assertEqual(len(result["supports"]), 1)
        self.assertTrue(result["supports"][0].startswith("Bidding "))
        self.assertGreater(result["finalValue"], 0)
        self.assertIn(result["baseValue"], (None, 0))
        self.assertEqual(result["supportAudit"]["status"], "inconclusive")
        self.assertFalse(result["measurement"]["checkpointEligible"])
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, original_hash, self._tree_group(34207, listed)["index"])["status"],
            "inconclusive",
        )
        self.assertEqual(build_state_hash(self.engine.get_xml()), original_hash)

        configured = self._configure(34207, result["supports"])
        self.assertTrue(configured["ok"])
        self.assertIsNone(configured["supportAudit"])

    def test_deallocating_ascendancy_node_removes_source_group(self) -> None:
        self._new_varashta(34207)
        self.assertTrue(self.engine.dealloc_passive(34207)["ok"])
        groups = skillgroups.list_skill_groups(self.engine)["groups"]
        self.assertFalse(any(group.get("source") == "Tree:34207" for group in groups))


class ItemSourceSupportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = PobEngine()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.close()

    def _new_calamity(self, *, extra_spirit: bool = True) -> dict:
        self.engine.new_build()
        self.engine.set_class("Mercenary", "Tactician")
        self.engine.set_level(95)
        weapon = self.engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        self.assertTrue(weapon["ok"], weapon)
        if extra_spirit:
            self.engine.set_config(custom_mods="+200 to Spirit")
        armour = self.engine.add_item(COMING_CALAMITY, slot="Body Armour")
        self.assertTrue(armour["ok"], armour)
        listed = skillgroups.list_skill_groups(self.engine)
        ash = self._item_group(listed=listed)
        selected = skillgroups.set_skill_group_state(
            self.engine, group_index=ash["index"],
            expected_fingerprint=ash["fingerprint"],
            expected_state_hash=listed["stateHash"], make_main=True,
        )
        self.assertTrue(selected["ok"], selected)
        return skillgroups.list_skill_groups(self.engine)

    def _item_group(self, skill: str = "Herald of Ash", listed: dict | None = None) -> dict:
        return _find_source_group(
            listed or skillgroups.list_skill_groups(self.engine),
            kind="item", root_skill=skill,
        )

    def _herald_groups(self, listed: dict) -> list[dict]:
        return [self._item_group(skill, listed) for skill in (
            "Herald of Ash", "Herald of Ice", "Herald of Thunder",
        )]

    def _configure(self, skill: str, supports: list[str]) -> dict:
        listed = skillgroups.list_skill_groups(self.engine)
        group = self._item_group(skill, listed)
        return skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=supports,
            expected_fingerprint=group["fingerprint"],
            expected_state_hash=listed["stateHash"],
        )

    def test_level_14_item_source_uses_its_real_support_capacity(self) -> None:
        self.engine.new_build()
        self.engine.set_class("Witch", "Infernalist")
        self.engine.set_level(95)
        equipped = self.engine.add_item(COVENANT, slot="Body Armour")
        self.assertTrue(equipped["ok"], equipped)
        listed = skillgroups.list_skill_groups(self.engine)
        group = self._item_group("Life Remnants", listed)
        self.assertEqual(group["sourceKind"], "item")
        self.assertEqual(group["gems"][0]["level"], 14)

        configured = self._configure("Life Remnants", ["Precision I"])
        self.assertTrue(configured["ok"], configured)
        self.assertEqual(configured["skillLevel"], 14)
        self.assertEqual(configured["supportCapacity"], 3)
        self.assertEqual(
            [{key: row[key] for key in ("name", "activeSkills")} for row in configured["supportApplication"]],
            [{"name": "Precision I", "activeSkills": ["Life Remnants"]}],
        )

        before_hash = build_state_hash(self.engine.get_xml())
        over_capacity = self._configure(
            "Life Remnants",
            ["Precision I", "Clarity I", "Vitality I", "Magnified Area I"],
        )
        self.assertEqual(over_capacity["errorCode"], "source_support_capacity_exceeded")
        self.assertEqual(over_capacity["capacity"], 3)
        self.assertEqual(before_hash, build_state_hash(self.engine.get_xml()))

    def test_item_sources_configure_independently_and_roundtrip(self) -> None:
        listed = self._new_calamity()
        self.assertEqual([group["sourceKind"] for group in self._herald_groups(listed)], ["item"] * 3)
        self.assertEqual(len([group for group in listed["groups"] if group.get("sourceKind") == "item"]), 3)
        self.assertTrue(any(group.get("source") == "Default Attack" for group in listed["groups"]))
        self.assertTrue(all(not group["noSupports"] for group in self._herald_groups(listed)))

        self.assertTrue(self._configure("Herald of Ash", ["Precision I"])["ok"])
        self.assertTrue(self._configure("Herald of Ice", ["Magnified Area I"])["ok"])
        self.assertTrue(self._configure("Herald of Thunder", ["Deadly Herald"])["ok"])
        groups = skillgroups.list_skill_groups(self.engine)["groups"]
        self.assertEqual(
            [[gem["name"] for gem in group["gems"]] for group in self._herald_groups({"groups": groups})],
            [
                ["Herald of Ash", "Precision I"],
                ["Herald of Ice", "Magnified Area I"],
                ["Herald of Thunder", "Deadly Herald"],
            ],
        )

        before_spirit = self.engine.get_build()["spiritRequested"]
        snapshot = self.engine.get_xml()
        self.engine.load_build_xml(snapshot, name="item-source-public-roundtrip")
        self.engine.get_stats()
        self.engine.get_stats()
        after = skillgroups.list_skill_groups(self.engine)["groups"]
        self.assertEqual(
            [[gem["name"] for gem in group["gems"]] for group in after],
            [[gem["name"] for gem in group["gems"]] for group in groups],
        )
        self.assertEqual(before_spirit, self.engine.get_build()["spiritRequested"])

    def test_item_source_failures_are_atomic(self) -> None:
        listed = self._new_calamity(extra_spirit=False)
        self.engine.set_config(custom_mods="-95 to Spirit")
        listed = skillgroups.list_skill_groups(self.engine)
        original_xml = self.engine.get_xml()
        original_hash = build_state_hash(original_xml)
        group = self._item_group(listed=listed)

        stale_fingerprint = skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=["Precision I"],
            expected_fingerprint="skill-group:stale",
            expected_state_hash=listed["stateHash"],
        )
        self.assertEqual(stale_fingerprint["errorCode"], "skill_group_conflict")
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))

        stale_state = skillgroups.configure_source_skill_supports(
            self.engine,
            source_group_index=group["index"],
            supports=["Precision I"],
            expected_fingerprint=group["fingerprint"],
            expected_state_hash="sha256:stale",
        )
        self.assertEqual(stale_state["errorCode"], "build_state_conflict")
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))

        incompatible = self._configure("Herald of Ash", ["Bidding III"])
        self.assertEqual(incompatible["errorCode"], "source_support_not_applied")
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))

        over_spirit = self._configure("Herald of Ash", ["Precision II"])
        self.assertEqual(over_spirit["errorCode"], "spirit_over_reserved")
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))

    def test_coming_calamity_base_spirit_is_free_but_supports_are_not(self) -> None:
        self._new_calamity(extra_spirit=False)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 0)

        precision = self._configure("Herald of Ash", ["Precision I"])
        self.assertTrue(precision["ok"], precision)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 10)

        area = self._configure("Herald of Ice", ["Magnified Area I"])
        self.assertTrue(area["ok"], area)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 10)

        deadly = self._configure("Herald of Thunder", ["Deadly Herald"])
        self.assertTrue(deadly["ok"], deadly)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 30)

    def test_solid_plan_scales_only_the_support_spirit_cost(self) -> None:
        self._new_calamity(extra_spirit=False)
        precision = self._configure("Herald of Ash", ["Precision I"])
        self.assertTrue(precision["ok"], precision)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 10)

        allocated = self.engine.alloc_passive(15044)
        self.assertTrue(allocated["ok"], allocated)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 5)

    def test_disabled_herald_keeps_free_base_and_recovers_support_cost_with_weapon(self) -> None:
        self.engine.new_build()
        self.engine.set_class("Mercenary", "Tactician")
        self.engine.set_level(95)
        armour = self.engine.add_item(COMING_CALAMITY, slot="Body Armour")
        self.assertTrue(armour["ok"], armour)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 0)

        precision = self._configure("Herald of Ash", ["Precision I"])
        self.assertTrue(precision["ok"], precision)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 0)

        weapon = self.engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        self.assertTrue(weapon["ok"], weapon)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 10)
        groups = skillgroups.list_skill_groups(self.engine)["groups"]
        self.assertEqual(
            [gem["name"] for gem in self._item_group(listed={"groups": groups})["gems"]], ["Herald of Ash", "Precision I"]
        )

    def test_no_reservation_rule_requires_the_exact_unique_and_base(self) -> None:
        self.engine.new_build()
        self.engine.set_class("Mercenary", "Tactician")
        self.engine.set_level(95)
        self.engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        other = self.engine.add_item(
            """Rarity: Unique
Other Herald Armour
Ringmail Gauntlets
--------
Grants Skill: Level 20 Herald of Ash""",
            slot="Gloves",
        )
        self.assertTrue(other["ok"], other)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 30)

        self.engine.new_build()
        self.engine.set_class("Mercenary", "Tactician")
        self.engine.set_level(95)
        self.engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        same_title_wrong_base = self.engine.add_item(
            """Rarity: Unique
The Coming Calamity
Chain Mail
--------
Grants Skill: Level 20 Herald of Ash""",
            slot="Body Armour",
        )
        self.assertTrue(same_title_wrong_base["ok"], same_title_wrong_base)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 30)

        self.engine.new_build()
        self.engine.set_class("Mercenary", "Tactician")
        self.engine.set_level(95)
        self.engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        rare_spoof = self.engine.add_item(
            """Rarity: Rare
The Coming Calamity
Heroic Armour
--------
Grants Skill: Level 20 Herald of Ash
Grants Skill: Level 20 Herald of Ice
Grants Skill: Level 20 Herald of Thunder""",
            slot="Body Armour",
        )
        self.assertTrue(rare_spoof["ok"], rare_spoof)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 90)

        self.engine.new_build()
        self.engine.set_class("Mercenary", "Tactician")
        self.engine.set_level(95)
        self.engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        incomplete_unique = self.engine.add_item(
            """Rarity: Unique
The Coming Calamity
Heroic Armour
--------
Grants Skill: Level 20 Herald of Ash""",
            slot="Body Armour",
        )
        self.assertTrue(incomplete_unique["ok"], incomplete_unique)
        self.assertEqual(self.engine.get_build()["spiritRequested"], 30)

    def test_replacing_source_item_invalidates_supports_and_current_audit(self) -> None:
        listed = self._new_calamity()
        before_hash = listed["stateHash"]
        before_xml = self.engine.get_xml()
        self._configure("Herald of Ash", ["Precision I"])
        measured_group = self._item_group()
        self.engine.load_build_xml(before_xml)
        before_hash = build_state_hash(self.engine.get_xml())
        measurement = _complete_support_measurement("TotalDPS", recommended=["Precision I"])
        measurement["combinationComparison"]["candidateGroupFingerprint"] = (
            supportopt._comparison_group_fingerprint(measured_group)
        )
        supportopt._record_support_audit(
            engine=self.engine,
            state_hash=before_hash,
            group_index=self._item_group(listed=listed)["index"],
            skill="Herald of Ash",
            current_supports=[],
            recommended_supports=["Precision I"],
            constraints={},
            measurement=measurement,
        )
        configured = self._configure("Herald of Ash", ["Precision I"])
        self.assertTrue(configured["ok"], configured)
        configured_hash = configured["stateHash"]
        self.assertEqual(
            (configured["supportAudit"] or {}).get("status"),
            "passed",
            {
                "expectedFingerprint": measurement["combinationComparison"][
                    "candidateGroupFingerprint"
                ],
                "actualFingerprint": supportopt._comparison_group_fingerprint(
                    self._item_group()
                ),
                "expectedGroup": measured_group,
                "actualGroup": self._item_group(),
                "beforeAudit": supportopt.support_audit_for_state(self.engine, before_hash, self._item_group(listed=listed)["index"]),
            },
        )
        self.assertIsNotNone(supportopt.support_audit_for_state(self.engine, configured_hash, self._item_group(listed=listed)["index"]))

        replaced = self.engine.add_item(COMING_CALAMITY, slot="Body Armour")
        self.assertTrue(replaced["ok"], replaced)
        current = skillgroups.list_skill_groups(self.engine)
        self.assertNotEqual(configured_hash, current["stateHash"])
        self.assertTrue(all(len(group["gems"]) == 1 for group in current["groups"]))
        self.assertIsNone(supportopt.support_audit_for_state(self.engine, current["stateHash"], self._item_group(listed=listed)["index"]))

    def test_optimizer_measures_the_real_item_source_group_without_proxy(self) -> None:
        listed = self._new_calamity()
        original_xml = self.engine.get_xml()
        original_hash = build_state_hash(original_xml)
        with mock.patch.object(
            self.engine,
            "paste_skill",
            side_effect=AssertionError("source optimizer must not create a proxy skill"),
        ):
            result = supportopt.optimize_supports(
                self.engine,
                metric="ReqDex",
                max_supports=1,
                candidates=4,
                screen=6,
                group_index=self._item_group(listed=listed)["index"],
                expected_fingerprint=self._item_group(listed=listed)["fingerprint"],
            )
        self.assertTrue(result["ok"], result)
        self.assertTrue(str(result["source"]).startswith("Item:"))
        self.assertEqual(result["groupIndex"], self._item_group(listed=listed)["index"])
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))
        groups = skillgroups.list_skill_groups(self.engine)["groups"]
        self.assertEqual(len(groups), len(listed["groups"]))
        self.assertEqual(len(self._herald_groups({"groups": groups})), 3)
        self.assertEqual(
            [(group["source"], group["gems"][0]["name"]) for group in groups],
            [(group["source"], group["gems"][0]["name"]) for group in listed["groups"]],
        )

    def test_item_source_audit_classifies_authoritative_rejections(self) -> None:
        self._new_calamity()
        self.engine.set_config(custom_mods="+200 to Spirit\n+1 to Strength")
        listed = skillgroups.list_skill_groups(self.engine)
        state_hash = listed["stateHash"]
        insight = db.find_skills("Insight", limit=20)
        morrigan = next(
            gem["name"]
            for gem in insight
            if str(gem.get("id") or "").endswith("SupportGemMorrigansInsight")
        )
        with mock.patch.object(
            supportopt,
            "_screen_set",
            return_value=[
                "Precision I",
                "Crater",
                "Armour Explosion",
                "Dreamer's Knell",
                morrigan,
            ],
        ):
            result = supportopt.optimize_supports(
                self.engine,
                metric="SpiritReserved",
                group_index=self._item_group(listed=listed)["index"],
                expected_fingerprint=self._item_group(listed=listed)["fingerprint"],
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["supports"], [])
        self.assertEqual(result["measurement"]["status"], "complete")
        self.assertTrue(result["measurement"]["classificationComplete"])
        self.assertEqual(result["measurement"]["classifiedCandidates"], 5)
        self.assertEqual(result["measurement"]["measuredCandidates"], 1)
        self.assertEqual(result["measurement"]["rejectedCandidates"], 4)
        self.assertEqual(result["measurement"]["failedCandidates"], 0)
        self.assertEqual(
            result["measurement"]["candidateRejectionCodes"],
            {
                "support_model_unavailable": 1,
                "source_group_count_changed": 1,
                "source_support_not_applied": 2,
            },
        )
        self.assertEqual(result["supportAudit"]["status"], "passed")
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, self._item_group(listed=listed)["index"])["status"],
            "passed",
        )
        inspected = preflight.inspect_generation_snapshot(self.engine, self.engine.get_xml())
        checklist = validation_checkpoint._create_quality_checklist(
            engine=self.engine,
            xml=self.engine.get_xml(),
            state_hash=state_hash,
            build=self.engine.get_build(),
            stats={},
            completeness_result={
                "passiveJewels": {},
                "runes": {},
                "charms": {},
                "flasks": {},
            },
            preflight_result={
                "skillGroups": [
                    group for group in inspected["skillGroups"] if group["groupIndex"] == self._item_group(listed=listed)["index"]
                ]
            },
        )
        self.assertEqual(checklist["skillSupportAudit"]["status"], "passed", checklist)
        self.assertEqual(state_hash, build_state_hash(self.engine.get_xml()))

    def test_known_infeasible_combination_is_not_a_measurement_failure(self) -> None:
        self._new_calamity()
        self.engine.set_config(custom_mods="+200 to Spirit\n+2 to Strength")
        listed = skillgroups.list_skill_groups(self.engine)
        with mock.patch.object(
            supportopt,
            "_screen_set",
            return_value=["Precision I", "Precision II"],
        ):
            result = supportopt.optimize_supports(
                self.engine,
                goals={"SpiritReserved": 1},
                group_index=self._item_group(listed=listed)["index"],
                expected_fingerprint=self._item_group(listed=listed)["fingerprint"],
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["supports"], ["Precision II"])
        self.assertEqual(result["measurement"]["rejectedCombinations"], 1)
        self.assertEqual(result["measurement"]["failedCombinations"], 0)
        self.assertEqual(
            result["measurement"]["combinationRejectionCodes"],
            {"duplicate_support_family": 1},
        )
        self.assertEqual(result["supportAudit"]["status"], "inconclusive")

    def test_unknown_or_impossible_source_measurement_errors_still_fail_closed(self) -> None:
        self._new_calamity()
        self.engine.set_config(custom_mods="+200 to Spirit\n+3 to Strength")
        original_call = self.engine.call

        for error_code in (
            "source_group_count_changed",
            "source_support_capacity_exceeded",
            "duplicate_support_family",
        ):
            with self.subTest(error_code=error_code):
                listed = skillgroups.list_skill_groups(self.engine)
                state_hash = listed["stateHash"]

                def fail_nonempty_configuration(method: str, **params: object) -> dict:
                    if method == "configure_source_skill_supports" and params.get("supportGemIds"):
                        return {"ok": False, "errorCode": error_code}
                    return original_call(method, **params)

                with (
                    mock.patch.object(
                        self.engine,
                        "call",
                        side_effect=fail_nonempty_configuration,
                    ),
                    mock.patch.object(supportopt, "_screen_set", return_value=["Precision I"]),
                ):
                    result = supportopt.optimize_supports(
                        self.engine,
                        metric="SpiritReserved",
                        group_index=self._item_group(listed=listed)["index"],
                        expected_fingerprint=self._item_group(listed=listed)["fingerprint"],
                    )

                self.assertFalse(result["ok"])
                self.assertEqual(result["errorCode"], "support_optimization_inconclusive")
                self.assertTrue(result["measurement"]["classificationComplete"])
                self.assertEqual(result["measurement"]["rejectedCandidates"], 0)
                self.assertEqual(result["measurement"]["failedCandidates"], 1)
                self.assertEqual(
                    result["measurement"]["candidateFailureCodes"],
                    {error_code: 1},
                )
                self.assertEqual(
                    supportopt.support_audit_for_state(self.engine, state_hash, self._item_group(listed=listed)["index"])["status"],
                    "inconclusive",
                )
                self.assertEqual(state_hash, build_state_hash(self.engine.get_xml()))

    def test_mixed_measured_and_failed_source_candidates_cannot_pass(self) -> None:
        self._new_calamity()
        self.engine.set_config(custom_mods="+200 to Spirit\n+4 to Strength")
        listed = skillgroups.list_skill_groups(self.engine)
        state_hash = listed["stateHash"]
        original_call = self.engine.call
        rejected_id = str(
            self.engine.call(
                "resolve_support_gem_identity",
                **supportopt._support_identity_subject("Precision I"),
            )["gemId"]
        )

        def fail_one_configuration(method: str, **params: object) -> dict:
            if method == "configure_source_skill_supports" and params.get("supportGemIds") == [
                rejected_id
            ]:
                return {"ok": False, "errorCode": "source_support_capacity_exceeded"}
            return original_call(method, **params)

        with (
            mock.patch.object(
                self.engine,
                "call",
                side_effect=fail_one_configuration,
            ),
            mock.patch.object(
                supportopt,
                "_screen_set",
                return_value=["Precision I", "Precision II"],
            ),
        ):
            result = supportopt.optimize_supports(
                self.engine,
                metric="SpiritReserved",
                group_index=self._item_group(listed=listed)["index"],
                expected_fingerprint=self._item_group(listed=listed)["fingerprint"],
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["supportAudit"]["status"], "inconclusive")
        self.assertEqual(result["measurement"]["measuredCandidates"], 1)
        self.assertEqual(result["measurement"]["rejectedCandidates"], 0)
        self.assertEqual(result["measurement"]["failedCandidates"], 1)
        self.assertEqual(
            result["measurement"]["candidateFailureCodes"],
            {"source_support_capacity_exceeded": 1},
        )
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, self._item_group(listed=listed)["index"])["status"],
            "inconclusive",
        )
        self.assertEqual(state_hash, build_state_hash(self.engine.get_xml()))

    def test_empty_source_baseline_error_cannot_be_treated_as_rejected(self) -> None:
        self._new_calamity()
        self.engine.set_config(custom_mods="+200 to Spirit\n+5 to Strength")
        listed = skillgroups.list_skill_groups(self.engine)
        state_hash = listed["stateHash"]
        original_call = self.engine.call

        def fail_empty_configuration(method: str, **params: object) -> dict:
            if method == "configure_source_skill_supports" and params.get("supportGemIds") == []:
                return {"ok": False, "errorCode": "source_support_not_applied"}
            return original_call(method, **params)

        with (
            mock.patch.object(
                self.engine,
                "call",
                side_effect=fail_empty_configuration,
            ),
            mock.patch.object(supportopt, "_screen_set", return_value=["Precision I"]),
        ):
            result = supportopt.optimize_supports(
                self.engine,
                metric="SpiritReserved",
                group_index=self._item_group(listed=listed)["index"],
                expected_fingerprint=self._item_group(listed=listed)["fingerprint"],
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["supportAudit"]["status"], "inconclusive")
        self.assertFalse(result["measurement"]["baseMeasurable"])
        self.assertEqual(
            result["measurement"]["baseFailureCode"],
            "source_support_not_applied",
        )
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, self._item_group(listed=listed)["index"])["status"],
            "inconclusive",
        )
        self.assertEqual(state_hash, build_state_hash(self.engine.get_xml()))

    def test_optimizer_defaults_to_the_actual_non_first_main_group(self) -> None:
        self._new_calamity()
        self.engine.set_config(custom_mods="+201 to Spirit")
        listed = skillgroups.list_skill_groups(self.engine)
        second = self._item_group("Herald of Ice", listed)
        self.assertGreater(second["index"], 1)
        selected = skillgroups.set_skill_group_state(
            self.engine,
            group_index=self._item_group("Herald of Ice", listed)["index"],
            expected_fingerprint=second["fingerprint"],
            expected_state_hash=listed["stateHash"],
            make_main=True,
        )
        self.assertTrue(selected["ok"], selected)
        listed = skillgroups.list_skill_groups(self.engine)
        original_hash = listed["stateHash"]
        second = self._item_group("Herald of Ice", listed)

        stale = supportopt.optimize_supports(
            self.engine,
            metric="ReqDex",
            max_supports=1,
            candidates=2,
            screen=2,
            expected_fingerprint="skill-group:stale",
        )
        self.assertEqual(stale["errorCode"], "skill_group_conflict")
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))

        result = supportopt.optimize_supports(
            self.engine,
            metric="ReqDex",
            max_supports=1,
            candidates=4,
            screen=6,
            expected_fingerprint=second["fingerprint"],
            max_mana_cost=0,
            spirit_limit=301,
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["groupIndex"], second["index"])
        self.assertEqual(result["skill"], "Herald of Ice")
        self.assertEqual(original_hash, build_state_hash(self.engine.get_xml()))
        self.assertIsNone(supportopt.support_audit_for_state(self.engine, original_hash, self._item_group(listed=listed)["index"]))
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, original_hash, second["index"])["status"],
            "inconclusive",
        )

    def test_optimizer_restores_after_exception_following_temporary_selection(self) -> None:
        listed = self._new_calamity()
        original_hash = listed["stateHash"]
        self.assertEqual(listed["mainGroupIndex"], self._item_group(listed=listed)["index"])
        with mock.patch.object(self.engine, "get_build", side_effect=RuntimeError("probe failure")):
            with self.assertRaisesRegex(RuntimeError, "probe failure"):
                supportopt.optimize_supports(
                    self.engine,
                    group_index=self._item_group("Herald of Ice", listed)["index"],
                    expected_fingerprint=self._item_group("Herald of Ice", listed)["fingerprint"],
                )
        restored = skillgroups.list_skill_groups(self.engine)
        self.assertEqual(restored["stateHash"], original_hash)
        self.assertEqual(restored["mainGroupIndex"], listed["mainGroupIndex"])


class SupportAuditIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        original_subject = supportopt._support_identity_subject
        subject_patch = mock.patch.object(
            supportopt,
            "_support_identity_subject",
            side_effect=lambda name: (
                {"gemIds": ["oracle:" + name], "effectIds": ["effect:" + name]}
                if name in {"Good", "Broken"}
                else original_subject(name)
            ),
        )
        subject_patch.start()
        self.addCleanup(subject_patch.stop)
        self.engine = PobEngine()
        self.engine.new_build()
        self.engine.set_class("Sorceress", "Stormweaver")
        self.engine.set_level(95)
        self.engine.paste_skill("Spark 20/20  1")

    def tearDown(self) -> None:
        self.engine.close()

    def _listed(self) -> dict:
        return skillgroups.list_skill_groups(self.engine)

    def test_invalid_empty_search_parameters_do_not_overwrite_failed_audit(self) -> None:
        listed = self._listed()
        state_hash = listed["stateHash"]
        supportopt._record_support_audit(
            engine=self.engine,
            state_hash=state_hash,
            group_index=1,
            skill="Spark",
            current_supports=[],
            recommended_supports=["Acceleration I"],
            constraints={},
            measurement=_complete_support_measurement("TotalDPS", recommended=["Acceleration I"]),
        )
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, 1)["status"],
            "failed",
        )

        invalid = supportopt.optimize_supports(
            self.engine,
            max_supports=0,
            group_index=1,
            expected_fingerprint=listed["groups"][0]["fingerprint"],
        )
        self.assertEqual(invalid["errorCode"], "invalid_max_supports")
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, 1)["status"],
            "failed",
        )
        self.assertEqual(
            supportopt.optimize_supports(self.engine, candidates=0)["errorCode"],
            "invalid_candidates",
        )
        self.assertEqual(
            supportopt.optimize_supports(self.engine, screen=0)["errorCode"],
            "invalid_screen",
        )
        narrow = supportopt.optimize_supports(
            self.engine,
            metric="TotalDPS",
            max_supports=1,
            candidates=1,
            screen=1,
            group_index=1,
            expected_fingerprint=listed["groups"][0]["fingerprint"],
        )
        self.assertTrue(narrow["ok"], narrow)
        self.assertEqual(narrow["supportAudit"]["status"], "inconclusive")
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, 1)["status"],
            "failed",
        )
        unrelated = supportopt.optimize_supports(
            self.engine,
            metric="Life",
            max_supports=5,
            group_index=1,
            expected_fingerprint=listed["groups"][0]["fingerprint"],
        )
        self.assertTrue(unrelated["ok"], unrelated)
        self.assertEqual(unrelated["supportAudit"]["status"], "inconclusive")
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, state_hash, 1)["status"],
            "failed",
        )
        self.assertEqual(
            supportopt.optimize_supports(self.engine, max_mana_cost=-1)["errorCode"],
            "invalid_max_mana_cost",
        )
        self.assertEqual(
            supportopt.optimize_supports(self.engine, spirit_limit=float("nan"))["errorCode"],
            "invalid_spirit_limit",
        )

    def test_legacy_trigger_hint_cannot_claim_verified_capability_gap(self) -> None:
        engine = _TriggerAuditEngine()

        result = supportopt.optimize_supports(engine, metric="FullDPS")

        assert result["ok"] is False
        assert result["reasonCode"] == "trigger_rate_unmodelled"
        assert result["supportAudit"]["status"] == "inconclusive"
        assert result["supportAudit"]["reasonClass"] == "evidence_gap"
        assert "supports" not in result
        assert "progression" not in result

    def test_runtime_trigger_gap_short_circuits_as_candidate_only_capability(self) -> None:
        result = supportopt.optimize_supports(
            _RuntimeTriggerAuditEngine(),
            metric="FullDPS",
        )

        assert result["ok"] is False
        assert result["reasonCode"] == "trigger_rate_unmodelled"
        assert result["supportAudit"]["auditVersion"] == "support_audit_v5"
        assert result["supportAudit"]["reasonClass"] == "capability_gap"
        assert result["supportAudit"]["verificationRequired"] is True
        assert result["measurement"]["screenedCandidates"] == 0

    def test_zero_trigger_rate_is_actionable_not_a_model_gap(self) -> None:
        result = supportopt.optimize_supports(
            _RuntimeTriggerAuditEngine("zero_or_inactive"),
            metric="FullDPS",
        )

        assert result["supportAudit"]["status"] == "failed"
        assert result["supportAudit"]["reasonClass"] == "actionable_gap"
        assert result["reasonCode"] == "trigger_rate_zero_or_inactive"

    def test_known_broader_model_gap_preserves_candidate_without_numeric_ranking(self) -> None:
        class IncompleteModelEngine(_RuntimeTriggerAuditEngine):
            def call(self, method: str, **kwargs: object) -> dict:
                result = super().call(method, **kwargs)
                if method == "inspect_support_evaluation_capability":
                    result["declaredDamageModel"] = "incomplete"
                    result["reasonCodes"].append("declared_duration_dot_model_missing")
                return result

        result = supportopt.optimize_supports(IncompleteModelEngine(), metric="FullDPS")

        assert result["ok"] is False
        assert result["supportAudit"]["reasonClass"] == "capability_gap"
        assert result["supportAudit"]["verificationRequired"] is True
        assert result["supportAudit"]["status"] == "inconclusive"
        assert result["capability"]["numericRanking"] == "unsupported"
        assert not supportopt.support_capability_is_rate_only_gap(result["capability"])
        assert supportopt.support_capability_is_model_gap(result["capability"])
        assert "supports" not in result
        assert result["measurement"]["screenedCandidates"] == 0

    def test_rate_gap_contract_rejects_missing_malformed_and_mixed_reasons(self) -> None:
        capability = _RuntimeTriggerAuditEngine().call("inspect_support_evaluation_capability")
        assert supportopt.support_capability_is_rate_only_gap(capability)
        for reasons in (
            None,
            [],
            "trigger_rate_unmodelled",
            [{}],
            ["trigger_rate_unmodelled", "other_model_missing"],
        ):
            assert not supportopt.support_capability_is_rate_only_gap(
                {**capability, "reasonCodes": reasons}
            )
        assert not supportopt.support_capability_is_rate_only_gap(
            {**capability, "declaredDamageModel": "incomplete"}
        )
        assert not supportopt.support_capability_is_model_gap(
            {**capability, "declaredDamageModel": "incomplete"}
        )
        assert not supportopt.support_capability_is_model_gap(
            {**capability, "reasonCodes": ["trigger_rate_unmodelled", "unknown_measurement_error"]}
        )

    def test_unmeasurable_metric_is_inconclusive_and_is_cached(self) -> None:
        listed = self._listed()
        result = supportopt.optimize_supports(
            self.engine,
            metric="DefinitelyMissingMetric",
            max_supports=1,
            candidates=4,
            screen=4,
            group_index=1,
            expected_fingerprint=listed["groups"][0]["fingerprint"],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["errorCode"], "support_optimization_inconclusive")
        self.assertEqual(result["measurement"]["status"], "inconclusive")
        self.assertEqual(
            supportopt.support_audit_for_state(self.engine, listed["stateHash"], 1)["status"],
            "inconclusive",
        )
        self.assertEqual(listed["stateHash"], build_state_hash(self.engine.get_xml()))

    def test_partial_candidate_measurement_cannot_write_passed_audit(self) -> None:
        engine = _AuditProbeEngine(
            {
                "": {"TotalDPS": 100.0},
                "Good": {"TotalDPS": 100.0},
                "Broken": {},
            }
        )
        with mock.patch.object(supportopt, "_screen_set", return_value=["Good", "Broken"]):
            result = supportopt.optimize_supports(engine, metric="TotalDPS")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["supportAudit"]["status"], "inconclusive")
        self.assertEqual(result["measurement"]["failedCandidates"], 1)
        self.assertFalse(result["measurement"]["checkpointEligible"])
        self.assertEqual(
            supportopt.support_audit_for_state(engine, build_state_hash(engine.get_xml()), 1)[
                "status"
            ],
            "inconclusive",
        )

    def test_missing_constraint_or_goal_fields_make_audit_inconclusive(self) -> None:
        missing_constraint = _AuditProbeEngine(
            {
                "": {"TotalDPS": 100.0},
                "Good": {"TotalDPS": 110.0},
            }
        )
        with mock.patch.object(supportopt, "_screen_set", return_value=["Good"]):
            constrained = supportopt.optimize_supports(
                missing_constraint,
                metric="TotalDPS",
                max_mana_cost=20,
            )
        self.assertTrue(constrained["ok"], constrained)
        self.assertEqual(constrained["supportAudit"]["status"], "inconclusive")
        self.assertFalse(constrained["measurement"]["baseMeasurable"])

        split_goals = _AuditProbeEngine(
            {
                "": {"TotalDPS": 100.0},
                "Good": {"TotalEHP": 1000.0},
            }
        )
        with mock.patch.object(supportopt, "_screen_set", return_value=["Good"]):
            blended = supportopt.optimize_supports(
                split_goals,
                goals={"TotalDPS": 0.5, "TotalEHP": 0.5},
            )
        self.assertTrue(blended["ok"], blended)
        self.assertEqual(blended["supportAudit"]["status"], "inconclusive")
        self.assertFalse(blended["measurement"]["baseMeasurable"])

    def test_unsatisfied_constraints_and_non_finite_values_cannot_pass(self) -> None:
        cases = (
            ("max_mana_cost", "ManaCost"),
            ("spirit_limit", "SpiritReserved"),
        )
        for argument, stat in cases:
            engine = _AuditProbeEngine(
                {
                    "": {"TotalDPS": 100.0, stat: 30.0},
                    "Good": {"TotalDPS": 90.0, stat: 30.0},
                }
            )
            with mock.patch.object(supportopt, "_screen_set", return_value=["Good"]):
                result = supportopt.optimize_supports(
                    engine,
                    metric="TotalDPS",
                    **{argument: 20},
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["supportAudit"]["status"], "inconclusive")
            self.assertFalse(result["measurement"]["finalConstraintsSatisfied"])
            self.assertEqual(
                supportopt.support_audit_for_state(engine, build_state_hash(engine.get_xml()), 1)[
                    "status"
                ],
                "inconclusive",
            )

        invalid_goals = supportopt.optimize_supports(
            _AuditProbeEngine({"": {"TotalDPS": 100.0}}),
            goals={"TotalDPS": float("inf")},
        )
        self.assertEqual(invalid_goals["errorCode"], "invalid_goals")

        non_finite_stats = _AuditProbeEngine(
            {"": {"TotalDPS": float("nan")}, "Good": {"TotalDPS": float("inf")}}
        )
        with mock.patch.object(supportopt, "_screen_set", return_value=["Good"]):
            non_finite = supportopt.optimize_supports(non_finite_stats, metric="TotalDPS")
        self.assertFalse(non_finite["ok"])
        self.assertEqual(non_finite["errorCode"], "support_optimization_inconclusive")

    def test_complete_eligible_search_passes_after_recommendation_is_applied(self) -> None:
        listed = self._listed()
        initial = supportopt.optimize_supports(
            self.engine,
            metric="ManaCost",
            max_supports=5,
            group_index=1,
            expected_fingerprint=listed["groups"][0]["fingerprint"],
        )
        self.assertTrue(initial["ok"], initial)
        self.assertTrue(initial["supports"])
        self.assertEqual(initial["supportAudit"]["status"], "failed", initial)
        applied = skillgroups.set_main_skill(
            self.engine,
            "Spark 20/20  1\n" + "\n".join(initial["supports"]),
        )
        self.assertIsNot(applied.get("ok"), False, applied)
        self.assertEqual(
            [gem["name"] for gem in self._listed()["groups"][0]["gems"]][1:],
            initial["supports"],
        )

        listed = self._listed()
        result = supportopt.optimize_supports(
            self.engine,
            metric="ManaCost",
            max_supports=5,
            group_index=1,
            expected_fingerprint=listed["groups"][0]["fingerprint"],
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["measurement"]["status"], "complete")
        self.assertTrue(result["measurement"]["checkpointEligible"])
        self.assertGreater(result["measurement"]["measuredCandidates"], 0)
        self.assertEqual(result["supportAudit"]["status"], "passed")
        self.assertEqual(listed["stateHash"], build_state_hash(self.engine.get_xml()))


class SyntheticSourceNoSupportsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = PobEngine()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.close()

    def test_explode_and_thorns_remain_not_applicable_after_xml_roundtrip(self) -> None:
        cases = (
            (
                "Explode",
                """Rarity: Unique
Quecholli
Crumbling Maul
--------
Causes Enemies to Explode on Critical kill, for 10% of their Life as Physical Damage""",
                "Weapon 1",
            ),
            (
                "Thorns",
                """Rarity: Rare
Thorn Test
Ringmail Gauntlets
--------
25 to 35 Fire Thorns damage""",
                "Gloves",
            ),
        )
        for expected_source, item, slot in cases:
            self.engine.new_build()
            self.engine.set_level(95)
            equipped = self.engine.add_item(item, slot=slot)
            self.assertTrue(equipped["ok"], equipped)
            before = next(
                group
                for group in skillgroups.list_skill_groups(self.engine)["groups"]
                if group.get("source") == expected_source
            )
            self.assertTrue(before["noSupports"])
            listed = skillgroups.list_skill_groups(self.engine)
            selected = skillgroups.set_skill_group_state(
                self.engine,
                group_index=before["index"],
                expected_fingerprint=before["fingerprint"],
                expected_state_hash=listed["stateHash"],
                make_main=True,
            )
            self.assertTrue(selected["ok"], selected)

            snapshot = self.engine.get_xml()
            self.engine.load_build_xml(snapshot, name=f"{expected_source}-roundtrip")
            self.engine.get_stats()
            self.engine.get_stats()
            listed = skillgroups.list_skill_groups(self.engine)
            after = next(
                group for group in listed["groups"] if group.get("source") == expected_source
            )
            self.assertEqual(after["sourceKind"], "other")
            self.assertTrue(after["noSupports"])

            inspected = preflight.inspect_generation_snapshot(
                self.engine,
                self.engine.get_xml(),
                completeness_result={"hardFailures": [], "advisories": []},
            )
            diagnostic = next(
                group
                for group in inspected["skillGroups"]
                if group.get("source") == expected_source
            )
            self.assertEqual(diagnostic["sourceKind"], "other")
            self.assertTrue(diagnostic["noSupports"])

            checklist = validation_checkpoint._create_quality_checklist(
                engine=self.engine,
                xml=self.engine.get_xml(),
                state_hash=listed["stateHash"],
                build={"level": 95, "gear": {}},
                stats={},
                completeness_result={
                    "passiveJewels": {},
                    "runes": {},
                    "charms": {},
                    "flasks": {},
                },
                preflight_result=inspected,
            )
            self.assertEqual(checklist["skillSupportAudit"]["status"], "not_applicable")
            self.assertEqual(checklist["mechanismDependencies"]["status"], "passed")


class SourceSupportBoundaryTests(unittest.TestCase):
    @staticmethod
    def _version_context() -> models.VersionContext:
        return models.VersionContext(
            league="test-league",
            ruleset="poe2",
            game_patch="0.5.4",
            passive_tree_version="0_5",
            pob_version_or_commit="test-pob",
            graph_snapshot_id="test-graph",
            research_memory_ref="disabled:test",
        )

    def _validate_transient_groups(self, groups: list[dict]) -> models.TransientBuildStateRef:
        return models.TransientBuildStateRef(
            status="available",
            snapshot_id="snapshot:test-runtime-names",
            source_hash="source:test-runtime-names",
            semantic_state_hash="semantic:test-runtime-names",
            safe_summary={},
            tested_skill_groups=groups,
            completeness_advisories=[],
            missing_reasons=[],
            version_context=self._version_context(),
            no_raw_material=True,
        )

    def test_item_source_with_no_supports_is_not_applicable(self) -> None:
        class FakeEngine:
            xml = "<PathOfBuilding/>"

            @contextmanager
            def transaction_lock(self):
                yield

            def get_xml(self) -> str:
                return self.xml

            def call(self, method: str, **_: object) -> dict:
                self.assert_method(method)
                return {
                    "groups": [
                        {
                            "index": 1,
                            "source": "Item:Example",
                            "sourceKind": "item",
                            "noSupports": True,
                            "gems": [{"name": "Example Skill", "isSupport": False}],
                        }
                    ]
                }

            @staticmethod
            def assert_method(method: str) -> None:
                if method != "list_skill_groups":
                    raise AssertionError(method)

        engine = FakeEngine()
        listed = skillgroups._decorate(
            engine.call("list_skill_groups"),
            state_hash=build_state_hash(engine.get_xml()),
        )
        result = skillgroups.configure_source_skill_supports(
            engine,
            source_group_index=1,
            supports=[],
            expected_fingerprint=listed["groups"][0]["fingerprint"],
            expected_state_hash=listed["stateHash"],
        )
        self.assertEqual(result["errorCode"], "source_skill_no_supports")

    def test_runtime_commands_decorate_preflight_and_judge_selection(self) -> None:
        xml = """<PathOfBuilding><Build className="Sorceress" ascendClassName="Disciple of Varashta" level="95" mainSocketGroup="1"/><Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true" source="Tree:34207"><Gem enabled="true" skillId="AscendancySummonFireDjinnPlayer" nameSpec="Ruzhan, the Blazing Sword" level="20" quality="0"/></Skill></SkillSet></Skills><Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>"""
        runtime = {
            "groups": [
                {
                    "index": 1,
                    "source": "Tree:34207",
                    "activeSkill": "Command",
                    "activeSkills": [
                        {"index": 1, "name": "Ruzhan, the Blazing Sword"},
                        {"index": 2, "name": "Command"},
                    ],
                }
            ]
        }
        parsed = evaluation._parse_build_snapshot(xml, runtime_skill_groups=runtime)
        self.assertEqual(
            parsed["testedSkillGroups"][0]["activeSkills"],
            [
                "Ruzhan, the Blazing Sword",
                "Command",
            ],
        )
        state = self._validate_transient_groups(parsed["testedSkillGroups"])
        self.assertEqual(state.tested_skill_groups[0].active_skill, "Command")
        selected = evaluation._resolve_offense_selection(
            parsed,
            offense_skill_group_index=1,
            expected_skill_name="Command",
        )
        self.assertEqual(selected["groupIndex"], 1)
        self.assertEqual(selected["skillName"], "Command")

    def test_runtime_minion_effect_names_are_consistent_across_preflight_and_judge(self) -> None:
        minions = [
            ("SummonSkeletalClericPlayer", "Skeletal Cleric", "Skeletal Cleric Minion"),
            ("SummonSkeletalStormMagePlayer", "Skeletal Storm Mage", "Skeletal Storm Mage Minion"),
            ("SummonSkeletalBrutePlayer", "Skeletal Brute", "Skeletal Brute Minion"),
            ("SummonSkeletalArsonistPlayer", "Skeletal Arsonist", "Skeletal Arsonist Minion"),
            ("SummonSkeletalSniperPlayer", "Skeletal Sniper", "Skeletal Sniper Minion"),
        ]
        skill_groups = "".join(
            f'<Skill enabled="true"><Gem enabled="true" skillId="{skill_id}" '
            f'nameSpec="{xml_name}" level="20" quality="20"/></Skill>'
            for skill_id, xml_name, _ in minions
        )
        xml = (
            '<PathOfBuilding><Build className="Sorceress" '
            'ascendClassName="Disciple of Varashta" level="95" mainSocketGroup="1"/>'
            f'<Skills activeSkillSet="1"><SkillSet id="1">{skill_groups}</SkillSet></Skills>'
            '<Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>'
        )
        runtime = {
            "groups": [
                {
                    "index": index,
                    "activeSkill": runtime_name,
                    "activeSkills": [{"index": 1, "name": runtime_name}],
                    "rootSkillId": skill_id,
                    "gems": [{"name": xml_name}],
                }
                for index, (skill_id, xml_name, runtime_name) in enumerate(minions, start=1)
            ]
        }

        parsed = evaluation._parse_build_snapshot(xml, runtime_skill_groups=runtime)
        groups = parsed["testedSkillGroups"]
        self.assertEqual(
            [group["activeSkill"] for group in groups],
            [runtime_name for _, _, runtime_name in minions],
        )
        for group in groups:
            self.assertEqual(group["activeSkills"], [group["activeSkill"]])
            self.assertEqual(group["activeSkillCount"], len(group["activeSkills"]))
        state = self._validate_transient_groups(parsed["testedSkillGroups"])
        self.assertEqual(len(state.tested_skill_groups), len(minions))

        class FakeEngine:
            @staticmethod
            def call(method: str) -> dict:
                if method != "list_skill_groups":
                    raise AssertionError(method)
                return runtime

        inspected = preflight._parse_skill_groups(xml)
        preflight._decorate_runtime_active_names(FakeEngine(), inspected)
        self.assertEqual(
            [group["activeNames"] for group in inspected["groups"]],
            [[runtime_name] for _, _, runtime_name in minions],
        )

    def test_runtime_selected_skill_outside_runtime_names_falls_back_safely(self) -> None:
        xml = """<PathOfBuilding><Build className="Sorceress" ascendClassName="Disciple of Varashta" level="95" mainSocketGroup="1"/><Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true"><Gem enabled="true" skillId="SummonSkeletalClericPlayer" nameSpec="Skeletal Cleric" level="20" quality="20"/></Skill></SkillSet></Skills><Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>"""
        runtime = {
            "groups": [
                {
                    "index": 1,
                    "activeSkill": "Stale Selected Effect",
                    "activeSkills": [{"index": 1, "name": "Skeletal Cleric Minion"}],
                }
            ]
        }
        parsed = evaluation._parse_build_snapshot(xml, runtime_skill_groups=runtime)
        group = parsed["testedSkillGroups"][0]
        self.assertEqual(group["activeSkill"], "Skeletal Cleric Minion")
        self.assertIn(group["activeSkill"], group["activeSkills"])
        self._validate_transient_groups(parsed["testedSkillGroups"])

    def test_runtime_source_metadata_is_not_joined_across_reordered_groups(self) -> None:
        parsed = {
            "groups": [
                {
                    "groupIndex": 1,
                    "source": "Item:Expected",
                    "rootSkillId": "HeraldOfAshPlayer",
                    "activeNames": ["Herald of Ash"],
                },
                {
                    "groupIndex": 2,
                    "source": None,
                    "rootSkillId": "SparkPlayer",
                    "activeNames": ["Spark"],
                },
            ]
        }

        class ReorderedEngine:
            @staticmethod
            def call(method: str) -> dict:
                if method != "list_skill_groups":
                    raise AssertionError(method)
                return {
                    "groups": [
                        {
                            "index": 1,
                            "source": None,
                            "sourceKind": None,
                            "noSupports": False,
                            "rootSkillId": "SparkPlayer",
                            "gems": [{"name": "Spark"}],
                            "activeSkills": [{"name": "Spark"}],
                        },
                        {
                            "index": 2,
                            "source": "Item:Expected",
                            "sourceKind": "item",
                            "noSupports": True,
                            "rootSkillId": "HeraldOfAshPlayer",
                            "gems": [{"name": "Herald of Ash"}],
                            "activeSkills": [{"name": "Herald of Ash"}],
                        },
                    ]
                }

        preflight._decorate_runtime_active_names(ReorderedEngine(), parsed)
        self.assertNotIn("sourceKind", parsed["groups"][0])
        self.assertNotIn("noSupports", parsed["groups"][0])
        self.assertNotIn("sourceKind", parsed["groups"][1])
        self.assertNotIn("noSupports", parsed["groups"][1])

    def test_runtime_source_metadata_requires_a_root_skill_identity(self) -> None:
        parsed = {
            "groups": [
                {
                    "groupIndex": 1,
                    "source": "Item:Expected",
                    "rootSkillId": "HeraldOfAshPlayer",
                    "activeNames": ["Herald of Ash"],
                }
            ]
        }

        class MissingRootEngine:
            @staticmethod
            def call(method: str) -> dict:
                if method != "list_skill_groups":
                    raise AssertionError(method)
                return {
                    "groups": [
                        {
                            "index": 1,
                            "source": "Item:Expected",
                            "sourceKind": "item",
                            "noSupports": True,
                            "gems": [],
                            "activeSkills": [{"name": "Wrong Skill"}],
                        }
                    ]
                }

        preflight._decorate_runtime_active_names(MissingRootEngine(), parsed)
        self.assertEqual(parsed["groups"][0]["activeNames"], ["Herald of Ash"])
        self.assertNotIn("sourceKind", parsed["groups"][0])
        self.assertNotIn("noSupports", parsed["groups"][0])

    def test_missing_runtime_group_falls_back_to_xml_root_name(self) -> None:
        xml = """<PathOfBuilding><Build className="Sorceress" ascendClassName="Disciple of Varashta" level="95" mainSocketGroup="1"/><Skills activeSkillSet="1"><SkillSet id="1"><Skill enabled="true"><Gem enabled="true" skillId="SummonSkeletalClericPlayer" nameSpec="Skeletal Cleric" level="20" quality="20"/></Skill></SkillSet></Skills><Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>"""
        parsed = evaluation._parse_build_snapshot(xml, runtime_skill_groups={"groups": []})
        group = parsed["testedSkillGroups"][0]
        self.assertEqual(group["activeSkill"], "Skeletal Cleric")
        self.assertEqual(group["activeSkills"], ["Skeletal Cleric"])
        self._validate_transient_groups(parsed["testedSkillGroups"])

    def test_tree_and_item_sources_use_support_audits(self) -> None:
        class AuditEngine:
            @staticmethod
            def get_xml() -> str:
                return "<PathOfBuilding><Items activeItemSet='1'><ItemSet id='1'/></Items></PathOfBuilding>"

        engine = AuditEngine()
        state_hash = "sha256:test"
        supportopt._record_support_audit(
            engine=engine,
            state_hash=state_hash,
            group_index=1,
            skill="Command",
            current_supports=["Bidding III"],
            recommended_supports=["Bidding III"],
            constraints={},
            measurement=_complete_support_measurement(
                "TotalDPS", current=["Bidding III"], recommended=["Bidding III"]
            ),
        )
        supportopt._record_support_audit(
            engine=engine,
            state_hash=state_hash,
            group_index=2,
            skill="Herald of Ash",
            current_supports=["Precision I"],
            recommended_supports=["Precision I"],
            constraints={},
            measurement=_complete_support_measurement(
                "TotalDPS", current=["Precision I"], recommended=["Precision I"]
            ),
        )
        checklist = validation_checkpoint._create_quality_checklist(
            engine=engine,
            xml="<PathOfBuilding><Items activeItemSet='1'><ItemSet id='1'/></Items></PathOfBuilding>",
            state_hash=state_hash,
            build={"level": 95, "gear": {}},
            stats={},
            completeness_result={"passiveJewels": {}, "runes": {}, "charms": {}, "flasks": {}},
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": "Tree:34207",
                        "sourceKind": "tree",
                        "noSupports": False,
                        "activeSkills": ["Command"],
                        "mainActiveSkillCalcs": 1,
                        "activeSkillSelectionError": None,
                    },
                    {
                        "groupIndex": 2,
                        "source": "Item:Example",
                        "sourceKind": "item",
                        "noSupports": False,
                        "activeSkills": ["Herald of Ash"],
                        "mainActiveSkillCalcs": 1,
                        "activeSkillSelectionError": None,
                    },
                ]
            },
        )
        self.assertEqual(checklist["skillSupportAudit"]["status"], "passed")
        self.assertEqual(checklist["mechanismDependencies"]["status"], "passed")
        self.assertEqual(checklist["mechanismDependencies"]["reasons"], [])

    def test_checkpoint_rejects_inconclusive_support_audit(self) -> None:
        class AuditEngine:
            @staticmethod
            def get_xml() -> str:
                return "<PathOfBuilding><Items activeItemSet='1'><ItemSet id='1'/></Items></PathOfBuilding>"

        engine = AuditEngine()
        state_hash = "sha256:inconclusive"
        audit = supportopt._record_support_audit(
            engine=engine,
            state_hash=state_hash,
            group_index=1,
            skill="Spark",
            current_supports=[],
            recommended_supports=[],
            constraints={},
            measurement={
                "status": "inconclusive",
                "baseMeasurable": False,
                "screenedCandidates": 4,
                "measuredCandidates": 0,
                "objectiveKeys": ["TotalDPS"],
                "measurementKeys": ["TotalDPS"],
            },
        )
        self.assertEqual(audit["status"], "inconclusive")
        self.assertEqual(
            supportopt.support_audit_for_state(engine, state_hash, 1)["status"],
            "inconclusive",
        )
        checklist = validation_checkpoint._create_quality_checklist(
            engine=engine,
            xml=engine.get_xml(),
            state_hash=state_hash,
            build={"level": 95, "gear": {}},
            stats={},
            completeness_result={"passiveJewels": {}, "runes": {}, "charms": {}, "flasks": {}},
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": None,
                        "sourceKind": None,
                        "noSupports": False,
                        "activeSkills": ["Spark"],
                        "mainActiveSkillCalcs": 1,
                        "activeSkillSelectionError": None,
                    }
                ]
            },
        )
        self.assertEqual(checklist["skillSupportAudit"]["status"], "failed")
        self.assertEqual(
            checklist["skillSupportAudit"]["reasons"],
            ["support_audit_inconclusive:1"],
        )

    def test_no_support_source_is_not_applicable_and_unknown_source_is_candidate(self) -> None:
        class AuditEngine:
            @staticmethod
            def get_xml() -> str:
                return "<PathOfBuilding><Items activeItemSet='1'><ItemSet id='1'/></Items></PathOfBuilding>"

        common = {
            "engine": AuditEngine(),
            "xml": "<PathOfBuilding><Items activeItemSet='1'><ItemSet id='1'/></Items></PathOfBuilding>",
            "state_hash": "sha256:test-no-supports",
            "build": {"level": 95, "gear": {}},
            "stats": {},
            "completeness_result": {
                "passiveJewels": {},
                "runes": {},
                "charms": {},
                "flasks": {},
            },
        }
        no_supports = validation_checkpoint._create_quality_checklist(
            **common,
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": "Item:Example",
                        "sourceKind": "item",
                        "noSupports": True,
                    }
                ]
            },
        )
        self.assertEqual(no_supports["skillSupportAudit"]["status"], "not_applicable")
        self.assertEqual(no_supports["mechanismDependencies"]["reasons"], [])

        source_less = validation_checkpoint._create_quality_checklist(
            **common,
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": None,
                        "sourceKind": None,
                        "noSupports": True,
                    }
                ]
            },
        )
        self.assertEqual(source_less["skillSupportAudit"]["status"], "failed")
        self.assertEqual(
            source_less["skillSupportAudit"]["reasons"],
            ["support_audit_missing:1"],
        )

        for source, source_kind in (
            ("Tree:34207", "tree"),
            ("Item:Example", "item"),
            ("Explode", "other"),
            ("Thorns", "other"),
            ("FutureSyntheticEffect", "other"),
        ):
            not_applicable = validation_checkpoint._create_quality_checklist(
                **common,
                preflight_result={
                    "skillGroups": [
                        {
                            "groupIndex": 1,
                            "source": source,
                            "sourceKind": source_kind,
                            "noSupports": True,
                        }
                    ]
                },
            )
            self.assertEqual(not_applicable["skillSupportAudit"]["status"], "not_applicable")
            self.assertEqual(not_applicable["mechanismDependencies"]["reasons"], [])

        unknown = validation_checkpoint._create_quality_checklist(
            **common,
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": "Other:Example",
                        "sourceKind": "other",
                        "noSupports": False,
                    }
                ]
            },
        )
        self.assertEqual(unknown["skillSupportAudit"]["status"], "not_applicable")
        self.assertEqual(
            unknown["mechanismDependencies"]["reasons"],
            ["source_skill_supports_unverified:1"],
        )
        self.assertTrue(unknown["mechanismDependencies"]["verificationRequired"])
        self.assertEqual(unknown["mechanismDependencies"]["status"], "failed")

        forged = validation_checkpoint._create_quality_checklist(
            **{**common, "build": {"level": 75, "gear": {}}},
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": "Item:forged",
                        "sourceKind": "other",
                        "noSupports": True,
                    }
                ]
            },
        )
        self.assertEqual(forged["mechanismDependencies"]["status"], "failed")

        missing_kind = validation_checkpoint._create_quality_checklist(
            **common,
            preflight_result={
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": "Explode",
                        "sourceKind": None,
                        "noSupports": True,
                    }
                ]
            },
        )
        self.assertEqual(missing_kind["mechanismDependencies"]["status"], "failed")

        refreshed = {
            "readyForJudge": True,
            "lifecycleVerification": {"pass": True},
            "completeness": common["completeness_result"],
            "preflight": {
                "skillGroups": [
                    {
                        "groupIndex": 1,
                        "source": "Other:Example",
                        "sourceKind": "other",
                        "noSupports": False,
                    }
                ]
            },
            "_checkpointInputs": {"build": common["build"], "stats": {}},
        }
        validation_checkpoint._refresh_dynamic_quality(
            refreshed,
            engine=common["engine"],
            xml=common["xml"],
            state_hash=common["state_hash"],
        )
        self.assertEqual(refreshed["deliveryStatus"], "candidate")


if __name__ == "__main__":
    unittest.main()
