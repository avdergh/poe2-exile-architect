from __future__ import annotations

from pathlib import Path
import unittest


SKILL = (
    Path(__file__).resolve().parents[1]
    / "poe-bd-creator-plugin"
    / "skills"
    / "poe-bd-create"
    / "SKILL.md"
)
GUIDE = Path(__file__).resolve().parents[1] / "server" / "ASSISTANT_GUIDE.md"


class CreateDeliveryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SKILL.read_text(encoding="utf-8")
        cls.guide = GUIDE.read_text(encoding="utf-8")

    def test_only_delivery_method_is_asked_and_existing_choice_is_not_repeated(self) -> None:
        self.assertIn("普通交互 Create 开始时只确认交付方式", self.text)
        self.assertIn("① 仅生成本地 PoB 文件", self.text)
        self.assertIn("② 本地文件之外，再生成 poe.ninja 分享链接", self.text)
        self.assertIn("用户已经明确", self.text)
        self.assertIn("不得重复询问", self.text)
        self.assertIn("不得为了补齐字段再开启第二轮", self.text)
        self.assertNotIn("combine\n  the goal question", self.guide)
        self.assertIn("ask only for local", self.guide)

    def test_blind_and_automatic_create_do_not_ask_export_or_upload(self) -> None:
        self.assertIn("Blind/自动\nCreate 不询问，也不执行用户交付导出", self.text)
        self.assertIn("Blind 或其他自动 Create 不执行面向", self.text)
        self.assertIn("只保存内部 artifact 并进入 Compare", self.text)
        self.assertIn("Blind/\n    自动 Create 跳过本步骤", self.text)
        self.assertIn("Blind/自动 Create 不展示用户导出项", self.text)

    def test_local_and_share_routes_use_only_existing_export_tools(self) -> None:
        local = self.text.split("**仅本地**：", 1)[1].split("**本地 + poe.ninja**：", 1)[0]
        share = self.text.split("**本地 + poe.ninja**：", 1)[1].split(
            "不新增 delivery policy", 1
        )[0]
        self.assertIn('export_final_pob_artifact(artifact_id, format="both", name=...)', local)
        self.assertIn("export_final_build_artifact", local)
        self.assertIn("不得调用 `export_final_build_package`", local)
        self.assertIn("不得调用任何 poe.ninja 发布入口", local)
        self.assertIn("任一失败时展示对应 errorCode 并保留现场", local)
        self.assertIn("成功项给路径、失败项给 errorCode", self.text)
        self.assertIn("export_final_build_package", share)
        self.assertNotIn("delivery_policy", self.text)


if __name__ == "__main__":
    unittest.main()
