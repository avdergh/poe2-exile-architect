from __future__ import annotations

from pathlib import Path
import unittest

from skill_document_helpers import read_skill_documents


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
        cls.documents = read_skill_documents(SKILL.parent)
        cls.text = cls.documents["SKILL.md"]
        cls.delivery = cls.documents["references/delivery.md"]
        cls.blind = cls.documents["references/blind-mode.md"]
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
        self.assertIn("Blind/自动 Create 不询问，也不执行用户交付导出", self.text)
        self.assertIn("submit_learning_create_result", self.blind)
        self.assertIn("不是普通 review 流程的", self.blind)
        self.assertIn("不执行用户导出或本任务清理", self.delivery)
        self.assertIn("其他自动 Create 同样不进行面向", self.delivery)

    def test_local_and_share_routes_use_only_existing_export_tools(self) -> None:
        local = next(row for row in self.delivery.splitlines() if row.startswith("| 仅本地 |"))
        share = next(row for row in self.delivery.splitlines() if row.startswith("| 本地 + poe.ninja |"))
        self.assertIn('export_final_pob_artifact(artifact_id, format="both", name=...)', local)
        self.assertIn("export_final_build_artifact", local)
        self.assertNotIn("export_final_build_package", local)
        self.assertNotIn("cleanup_completed_task_runtime", local)
        self.assertIn("不调用整包或 poe.ninja 发布入口", local)
        self.assertIn("部分导出失败时展示对应 errorCode 并保留现场", self.delivery)
        self.assertIn("成功项给路径、失败项给 errorCode", self.delivery)
        self.assertIn("export_final_build_package", share)
        self.assertIn("runtimeCleanupReady=true", share)
        self.assertNotIn("delivery_policy", self.delivery)


if __name__ == "__main__":
    unittest.main()
