"""开发验收：合成来源经真实 PoB 观察后返回会话，不生成网页。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.compute.engine import PobEngine  # noqa: E402
from server.study import service  # noqa: E402
from tests.test_study_workflow import lesson_for  # noqa: E402


def smoke() -> dict:
    # This is a structural fixture, never an automatic explanation generator.
    previous = os.environ.get("POE2_MCP_DATA")
    try:
        with tempfile.TemporaryDirectory(prefix="study-conversation-smoke-") as temp:
            os.environ["POE2_MCP_DATA"] = str(Path(temp) / "user")
            with PobEngine(show_engine_logs=False) as engine:
                engine.new_build()
                engine.set_class("Sorceress", "Stormweaver")
                engine.set_level(80)
                engine.paste_skill("Spark 18/0  1\nRapid Casting I 1/0  1")
                engine.add_item("Rarity: NORMAL\nWithered Wand\nItem Level: 80", slot="Weapon 1")
                source = Path(temp) / "synthetic.xml"
                source.write_text(engine.get_xml(), encoding="utf-8")
            run = service.start(source_file=str(source), user_language="zh")
            ref = run["runRef"]
            observed = service.observe(ref, group_index=1, skill_name="Spark")
            if observed["status"] == "selection_required":
                choices = [c for c in observed["availableOutputs"] if c["skillName"] == "Spark"]
                assert len(choices) == 1, observed
                observed = service.observe(
                    ref, group_index=choices[0]["groupIndex"], skill_name="Spark"
                )
            assert observed["status"] == "observed", observed
            assert observed["before"]["selectedSkill"]["skillName"] == "Spark"
            lesson = lesson_for(ref)
            complete = service.complete(ref, lesson)
            assert complete["status"] == "ready_for_delivery", complete
            assert (
                Path(complete["files"]["learning-guide.html"]["path"])
                .read_text("utf-8")
                .startswith("<!doctype html>")
            )
            assert not list(Path(temp).rglob("*.pdf"))
            cleanup = service.cleanup(ref)
            return {
                k: complete[k] for k in ("status", "delivery", "componentCount", "skillGroupCount")
            } | {
                "selectedOutput": "Spark",
                "rawSourceRemoved": cleanup["rawSourceRemoved"],
                "knowledgeWritten": complete["knowledgeWritten"],
                "qualityAssessment": "structural_fixture_only",
            }
    finally:
        if previous is None:
            os.environ.pop("POE2_MCP_DATA", None)
        else:
            os.environ["POE2_MCP_DATA"] = previous


if __name__ == "__main__":
    print(json.dumps(smoke(), ensure_ascii=False))
