from __future__ import annotations

from pathlib import Path
import contextlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from server.compute import engine as engine_module
from server.compute.engine import PobEngine
from server.compute.skillgroups import list_skill_groups
from server.knowledge import db


ROOT = Path(__file__).resolve().parents[1]
POB_ROOT = ROOT / "pob" / "PathOfBuilding-PoE2"
PATCH_ROOT = ROOT / "pob" / "patches"
COMING_CALAMITY = """Rarity: Unique
The Coming Calamity
Heroic Armour
--------
Grants Skill: Level 20 Herald of Ash
Grants Skill: Level 20 Herald of Ice
Grants Skill: Level 20 Herald of Thunder"""
LINKING_GLOVES = """Rarity: Unique
Test Linked Supports
Ringmail Gauntlets
--------
Grants Skill: Level 20 Herald of Blood
Socketed Support Gems can also Support Skills from your Equipped Body Armour"""


class PobPatchContractTests(unittest.TestCase):
    @contextlib.contextmanager
    def _item_source_test_engine(self):
        bridge = (ROOT / "pob" / "pob_headless.lua").read_text(encoding="utf-8")
        marker = """function methods.list_skill_groups()
\treturn skillGroupState()
end
"""
        debug_method = marker + """
function methods.test_applied_supports(p)
\trunCallback("OnFrame")
\tlocal group = (build.skillsTab.socketGroupList or {})[math.floor(tonumber(p and p.index) or 0)]
\tlocal names = { }
\tlocal active = group and group.displaySkillList and group.displaySkillList[1]
\tfor index = 2, #(active and active.effectList or { }) do
\t\tnames[#names + 1] = active.effectList[index].grantedEffect.name
\tend
\ttable.sort(names)
\treturn { supports = names }
end
"""
        self.assertEqual(bridge.count(marker), 1)
        bridge = bridge.replace(marker, debug_method, 1)

        handle, name = tempfile.mkstemp(suffix=".lua")
        os.close(handle)
        script = Path(name)
        script.write_text(bridge, encoding="utf-8")
        engine: PobEngine | None = None
        try:
            with mock.patch.object(
                engine_module,
                "_resolve_runtime_paths",
                return_value=(POB_ROOT / "src", script),
            ):
                engine = PobEngine()
            yield engine
        finally:
            if engine is not None:
                engine.close()
                if engine.proc.stdout is not None:
                    engine.proc.stdout.close()
            script.unlink(missing_ok=True)

    @staticmethod
    def _prepare_item_build(engine: PobEngine) -> None:
        engine.new_build()
        engine.set_class("Mercenary", "Tactician")
        engine.set_level(95)
        weapon = engine.add_item("Rarity: Normal\nBombard Crossbow", slot="Weapon 1")
        if not weapon.get("ok"):
            raise AssertionError(weapon)
        armour = engine.add_item(COMING_CALAMITY, slot="Body Armour")
        if not armour.get("ok"):
            raise AssertionError(armour)

    def test_source_support_patches_are_tracked_and_match_the_vendored_core(self) -> None:
        patches = [
            PATCH_ROOT / "0001-split-personality-alternate-class-starts.patch",
            PATCH_ROOT / "0002-tree-source-skill-supports.patch",
            PATCH_ROOT / "0003-isolate-item-source-supports.patch",
            PATCH_ROOT / "0004-coming-calamity-no-base-reservation.patch",
            PATCH_ROOT / "0005-refresh-synthetic-no-supports.patch",
            PATCH_ROOT / "0006-augment-limit-metadata.patch",
            PATCH_ROOT / "0007-standard-luajit-syntax.patch",
            PATCH_ROOT / "0008-normalize-sparse-item-grant-levels.patch",
        ]
        for patch in patches:
            self.assertTrue(patch.is_file(), patch)

        tracked_files = sorted({
            Path(name)
            for patch in patches
            for name in re.findall(r"^\+\+\+ b/(.+)$", patch.read_text(encoding="utf-8"), re.M)
        })
        self.assertIn(Path("src/Classes/PassiveSpec.lua"), tracked_files)
        self.assertIn(Path("src/Modules/CalcSetup.lua"), tracked_files)
        with tempfile.TemporaryDirectory() as temp_name:
            replay_root = Path(temp_name)
            # Own repository prevents git apply from silently resolving against
            # this project's parent when the test temp directory is inside it.
            subprocess.run(["git", "init", "-q"], cwd=replay_root, check=True)
            subprocess.run(
                ["git", "config", "core.autocrlf", "false"], cwd=replay_root, check=True
            )
            repository_root = subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"], cwd=replay_root, text=True
            ).strip()
            self.assertEqual(Path(repository_root).resolve(), replay_root.resolve())
            for relative in tracked_files:
                target = replay_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(POB_ROOT / relative, target)

            for patch in reversed(patches):
                reverted = subprocess.run(
                    ["git", "apply", "--reverse", "--verbose", str(patch)],
                    cwd=replay_root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(reverted.returncode, 0, reverted.stderr)
                self.assertIn("Checking patch", f"{reverted.stdout}\n{reverted.stderr}")

            for patch in patches:
                applied = subprocess.run(
                    ["git", "apply", "--verbose", str(patch)],
                    cwd=replay_root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(applied.returncode, 0, applied.stderr)
                self.assertIn("Checking patch", f"{applied.stdout}\n{applied.stderr}")

            for relative in tracked_files:
                self.assertEqual((POB_ROOT / relative).read_bytes(),
                                 (replay_root / relative).read_bytes(), relative)

    def test_item_source_supports_are_isolated_but_source_less_groups_still_share(self) -> None:
        calc_setup = (POB_ROOT / "src" / "Modules" / "CalcSetup.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "migrateLegacySlotSupports(group, legacySupportGroups[grantedSkill.slotName], migratedLegacyGroups)",
            calc_setup,
        )
        self.assertIn(
            "if not socketGroup.source and socketGroup.slot then",
            calc_setup,
        )
        self.assertIn("if not linkedSupportSlots[legacyGroup.slot] then", calc_setup)
        self.assertIn(
            "if not otherSocketGroup.source and otherSocketGroup.slot and "
            "otherSocketGroup.slot == crossLinkedSupportSlot then", calc_setup
        )
        self.assertIn(
            "for supportSourceGroup, supportGroup in pairs(supportLists[crossLinkedSupportSlot]) do",
            calc_setup,
        )
        self.assertIn("if not supportSourceGroup.source then", calc_setup)
        self.assertIn(
            "if crossLinkedSupportedSlot == slotName and "
            "supportLists[crossLinkedSupportSlot] then",
            calc_setup,
        )
        self.assertNotIn(
            "for _, supportGroup in pairs(supportLists[slotName]) do", calc_setup
        )

        bridge = (ROOT / "pob" / "pob_headless.lua").read_text(encoding="utf-8")
        self.assertIn("group.gemList[1] and group.gemList[1].noSupports", bridge)

    def _item_group(self, engine: PobEngine, name: str) -> dict:
        matches = [
            group for group in list_skill_groups(engine)["groups"]
            if group.get("sourceKind") == "item" and group["gems"][0]["name"] == name
        ]
        self.assertEqual(len(matches), 1, {"skill": name, "matches": matches})
        return matches[0]

    def test_real_engine_isolates_item_supports_spirit_roundtrip_and_cross_links(self) -> None:
        precision_id = str(db.get_gem("Precision I")["id"])

        with self._item_source_test_engine() as engine:
            self._prepare_item_build(engine)
            ash = self._item_group(engine, "Herald of Ash")
            before = float(engine.get_build()["spiritRequested"])
            configured = engine.call(
                "configure_source_skill_supports",
                index=ash["index"],
                supportGemIds=[precision_id],
            )
            self.assertTrue(configured["ok"], configured)
            self.assertEqual(before + 10, float(engine.get_build()["spiritRequested"]))
            for name, expected in (
                ("Herald of Ash", ["Precision I"]), ("Herald of Ice", []), ("Herald of Thunder", [])
            ):
                self.assertEqual(expected, engine.call(
                    "test_applied_supports", index=self._item_group(engine, name)["index"]
                )["supports"])

            snapshot = engine.get_xml()
            engine.load_build_xml(snapshot, name="item-source-isolation-roundtrip")
            engine.get_stats()
            engine.get_stats()
            self.assertEqual(before + 10, float(engine.get_build()["spiritRequested"]))
            groups = list_skill_groups(engine)["groups"]
            self.assertTrue(any(group.get("source") == "Default Attack" for group in groups))
            for name, expected in (
                ("Herald of Ash", ["Herald of Ash", "Precision I"]),
                ("Herald of Ice", ["Herald of Ice"]),
                ("Herald of Thunder", ["Herald of Thunder"]),
            ):
                self.assertEqual(expected, [gem["name"] for gem in self._item_group(engine, name)["gems"]])

        with self._item_source_test_engine() as engine:
            self._prepare_item_build(engine)
            engine.set_config(custom_mods="+200 to Spirit")
            gloves = engine.add_item(LINKING_GLOVES, slot="Gloves")
            self.assertTrue(gloves["ok"], gloves)
            blood = self._item_group(engine, "Herald of Blood")["index"]
            configured = engine.call(
                "configure_source_skill_supports",
                index=blood,
                supportGemIds=[precision_id],
            )
            self.assertTrue(configured["ok"], configured)
            engine.add_skill_group("Slot: Gloves\nDeadly Herald 1/0  1")

            for name in ("Herald of Ash", "Herald of Ice", "Herald of Thunder"):
                self.assertEqual(
                    ["Deadly Herald"],
                    engine.call("test_applied_supports", index=self._item_group(engine, name)["index"])["supports"],
                )
            self.assertEqual(
                ["Deadly Herald", "Precision I"],
                engine.call("test_applied_supports", index=blood)["supports"],
            )
            engine.load_build_xml(engine.get_xml(), name="cross-linked-source-roundtrip")
            for name in ("Herald of Ash", "Herald of Ice", "Herald of Thunder"):
                self.assertEqual(["Deadly Herald"], engine.call(
                    "test_applied_supports", index=self._item_group(engine, name)["index"]
                )["supports"])
            self.assertEqual(["Deadly Herald", "Precision I"], engine.call(
                "test_applied_supports", index=self._item_group(engine, "Herald of Blood")["index"]
            )["supports"])


if __name__ == "__main__":
    unittest.main()
