from __future__ import annotations

from pathlib import Path

from scripts import build_learning_memory_release_seed as release_seed
from server import paths
from server.learning import memory


def _lesson_payload(case_id: str = "case-release") -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "lesson": "Verify the delivery loop before committing damage scaling.",
        "scope": "global",
        "familyKey": None,
        "levelMin": None,
        "levelMax": None,
        "dimension": "damage_loop_delivery",
        "conditions": ["multi-step delivery"],
        "exclusions": ["instant single-step delivery"],
        "recommendedCreateBehavior": "Audit setup time and failure states before final scaling.",
        "verificationTasks": ["review delivery assumptions"],
        "comparisonRefs": [f"comparison:{case_id}"],
        "sourceRefs": [f"source:{case_id}"],
        "candidateRefs": [f"candidate:{case_id}"],
        "versionContext": {
            "gamePatch": "0.5.4",
            "passiveTreeVersion": "0_5",
            "pobVersionOrCommit": "0.5.4",
        },
        "reviewedCaseId": case_id,
        "dbFit": False,
        "citedCorrectionIds": [],
        "newEvidenceRefs": [],
    }


def test_learning_memory_seed_preserves_lessons_and_corrections(tmp_path: Path) -> None:
    source = tmp_path / "learning-memory.jsonl"
    output = tmp_path / "learning-memory.seed.jsonl"
    accepted = memory.propose_lesson(_lesson_payload(), path=source)
    lesson_id = accepted["lesson"]["lessonId"]
    corrected = memory.append_correction(
        {
            "schemaVersion": 1,
            "targetLessonId": lesson_id,
            "action": "revise",
            "reason": "The release lesson needs a narrower delivery condition.",
            "triggerCaseId": "case-release-2",
            "safeEvidenceRefs": ["comparison:case-release-2"],
            "afterLesson": "For multi-step delivery, verify setup time before final scaling.",
            "afterConditions": ["multi-step delivery"],
            "afterExclusions": ["one-step delivery"],
            "replacementLessonId": None,
        },
        path=source,
    )
    assert corrected["status"] == "corrected"

    report = release_seed.build_release_seed(source=source, output=output)
    assert report["lessonCount"] == 1
    assert report["correctionCount"] == 1
    memory.validate_release_seed(output)

    recalled = memory.query_memory(
        family_key="bf-0123456789abcdef0123",
        target_level=85,
        path=output,
    )
    assert recalled["recalledLessonIds"] == [lesson_id]
    assert recalled["lessons"][0]["lesson"].startswith("For multi-step delivery")


def test_default_learning_memory_installs_seed_once_without_overwrite(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.jsonl"
    seed = tmp_path / "bundle" / "data" / "comparative_learning" / "learning-memory.seed.jsonl"
    target = tmp_path / "user-data" / "comparative-learning" / "learning-memory.jsonl"
    memory.propose_lesson(_lesson_payload(), path=source)
    release_seed.build_release_seed(source=source, output=seed)
    monkeypatch.setattr(paths, "comparative_learning_memory_path", lambda: target)
    monkeypatch.setattr(paths, "comparative_learning_release_seed_path", lambda: seed)

    assert memory.memory_path() == target.resolve()
    original = target.read_text(encoding="utf-8")
    target.write_text(original + "\n", encoding="utf-8")
    assert memory.memory_path() == target.resolve()
    assert target.read_text(encoding="utf-8") == original + "\n"
