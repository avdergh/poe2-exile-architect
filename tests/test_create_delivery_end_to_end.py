"""One isolated Create run from real Python gates to real local exports.

Numerical readbacks and PoB load/save are a deterministic engine double, not gameplay evidence.
Blueprint/Draft validation, checkpoint/preflight, Judge rules, trusted receipt writing, artifact
binding/round-trip checks, lifecycle, review, exports and the installed Node converter run for
real. Only the final HTTP POST is mocked. No receipt or accepted gate is injected by this test.
"""

from copy import deepcopy
import json
from pathlib import Path
import urllib.parse
from xml.etree import ElementTree as ET

import pytest

from server import main
from server.build_planner import converter
from server.compute.pob_code import decode_code
from server.compute.state import build_state_hash
from server.generation import evaluation, pob_sharing, run_store, validation_checkpoint
from tests.test_generation_draft_recovery import _review_payload, _setup
from tests.test_phase5_generation_evaluation import BUILD_XML, _CheckpointActiveEngine, _JudgeEngine
from tests.test_poe_ninja_pob_share import _Response


DELIVERY_XML = BUILD_XML.replace("PathOfBuilding", "PathOfBuilding2")


class ContractEngine(_CheckpointActiveEngine):
    """Synthetic level-68 fixture exercises production gates without a new endgame build."""

    def __init__(self):
        super().__init__(xml=DELIVERY_XML)

    def get_build(self):
        build = _JudgeEngine().get_build()
        build.update(
            mainSkillGroup=deepcopy(build["judgeSelectedSkillGroup"]),
            judgeSupplementalSkills=[],
            gear={},
        )
        return build

    def get_stats(self, keys=None):
        return {"stats": {
            "Life": 4000, "LifeReserved": 0, "LifeUnreserved": 4000,
            "Mana": 600, "ManaUnreserved": 600, "ManaUnreservedPercent": 100,
            "ManaCost": 10, "LifeCost": 0, "Speed": 2,
            "ManaRegenRecovery": 100, "NetManaRegen": 100,
            "LifeRegenRecovery": 200, "NetLifeRegen": 200,
            "Spirit": 100, "SpiritReserved": 81,
            "TotalDPS": 42000, "CombinedDPS": 42000, "FullDPS": 42000,
            "LightningHitAverage": 100,
            "TotalEHP": 20000, "HitChance": 100,
        }}

    def get_defenses(self):
        return {
            **super().get_defenses(), "life": 4000, "totalEHP": 20000,
            "mana": 600, "energyShield": 0,
        }

    def load_build_xml(self, xml, name=""):
        self.xml = xml
        return {"ok": True}

    def call(self, method, **kwargs):
        if method == "set_skill_group_state":
            assert kwargs["index"] == 1
            assert kwargs.get("activeSkillIndex", 1) == 1
            return {"ok": True}
        if method != "list_skill_groups":
            raise AssertionError(method)
        groups = []
        for index, node in enumerate(ET.fromstring(self.xml).findall("./Skills/SkillSet/Skill"), 1):
            gems = list(node.findall("Gem"))
            name = gems[0].get("nameSpec")
            groups.append({
                "index": index, "isMain": index == 1, "enabled": True,
                "rootSkillId": gems[0].get("skillId"), "sourceKind": "ordinary",
                "activeSkill": name, "mainActiveSkill": 1, "mainActiveSkillCalcs": 1,
                "activeSkills": [{"index": 1, "name": name, "effectId": gems[0].get("skillId")}],
                "gems": [{
                    "name": gem.get("nameSpec"), "gemId": gem.get("gemId"),
                    "skillId": gem.get("skillId"), "isSupport": position > 0,
                    "level": 1, "quality": 0, "enabled": True,
                } for position, gem in enumerate(gems)],
            })
        return {"ok": True, "mainGroupIndex": 1, "calcsGroupIndex": 1, "groups": groups}

    def select_judge_skill(self, *, offense_skill_group_index, expected_skill_name):
        assert offense_skill_group_index == 1
        assert expected_skill_name == "Lightning Arrow"
        selected = {
            "groupIndex": 1, "activeIndex": 1, "skillName": expected_skill_name,
            "sourceMetric": "TotalDPS",
        }
        return {
            "status": "selected", "selectedSkill": selected,
            "selectedSkillGroup": self.get_build()["mainSkillGroup"],
            "supplementalSkills": [], "calculationContext": selected,
        }

    def close(self):
        pass


def test_create_run_reaches_real_local_exports_and_mocked_share(tmp_path, monkeypatch):
    provider = converter.converter_status()
    if provider["status"] != "ready":
        pytest.skip("Pinned Build Planner provider/Node unavailable: " + ", ".join(provider["issues"]))

    original_judge_runner = evaluation.runner.safe_evaluate_active_build
    original_observe = evaluation.mechanism_signature.observe
    bound, token, payload, _ = _setup(tmp_path, monkeypatch, memory=False)
    # Reuse only the blueprint/Draft fixture setup; run the real Judge rule evaluator below.
    monkeypatch.setattr(evaluation.runner, "safe_evaluate_active_build", original_judge_runner)
    monkeypatch.setattr(evaluation.mechanism_signature, "observe", original_observe)
    monkeypatch.setitem(
        evaluation.evaluate_generation_candidate.__kwdefaults__, "engine_factory", ContractEngine
    )
    engine = ContractEngine()
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setenv("POE_BD_POB_EXPORTS_DIR", str(tmp_path / "pob"))
    monkeypatch.setenv("POE_BD_BUILD_EXPORTS_DIR", str(tmp_path / "planner"))
    validation_checkpoint.clear_validation_checkpoint_cache()
    draft = main.validate_generation_draft(
        bound.run_id, token, payload, 1, "Lightning Arrow"
    )
    assert draft["status"] == "accepted", draft

    checkpoint = main.inspect_generation_checkpoint(
        offense_skill_group_index=1, expected_skill_name="Lightning Arrow"
    )
    assert checkpoint["hardLegalityReady"] is True, checkpoint
    assert checkpoint["readyForJudge"] is True, checkpoint
    assert checkpoint["finalCheckBlockers"] == []
    assert checkpoint["stateHash"] == build_state_hash(DELIVERY_XML)
    # This fixture is below the endgame search thresholds; the real policy marks these
    # checks not applicable. It does not pretend to certify a level-98 support optimum.
    assert checkpoint["createQualityChecklist"]["skillSupportAudit"]["status"] == "not_applicable"
    assert checkpoint["createQualityChecklist"]["jewelDecision"]["status"] == "not_applicable"

    candidate = payload["prototypeBuildCandidate"]
    evaluated = main.evaluate_generation_candidate(
        bound.run_id, token, candidate["candidateId"], candidate["versionContext"],
        offense_skill_group_index=1, expected_skill_name="Lightning Arrow",
    )
    assert evaluated["status"] == "evaluated", evaluated
    assert evaluated["attemptConsumed"] is True
    assert evaluated["judgeAdvisoryReport"]["passed"] is True, evaluated
    receipts = run_store.read_trusted_evaluations_strict(bound)
    assert len(receipts) == 1 and receipts[0]["candidateId"] == candidate["candidateId"]

    saved = main.save_final_build_artifact(bound.run_id, token, candidate["candidateId"], 0)
    assert saved["status"] == "saved", saved
    artifact = saved["finalBuildArtifact"]
    assert artifact["pobRoundTrip"]["status"] == "passed"
    artifact_id = artifact["artifactId"]
    lifecycle = main.verify_lifecycle_stage("maps_entry", artifact_id=artifact_id)
    assert lifecycle["pass"] is True, lifecycle
    assert lifecycle["artifactBound"] is True
    assert lifecycle["scope"] == "selected_skill_only"
    assert lifecycle["rotationCovered"] is False
    output = _review_payload(payload, evaluated)
    assert main.validate_generation_output(bound.run_id, token, output)["status"] == "accepted"
    assert main.complete_generation_review(bound.run_id, token, output)["status"] == "accepted"

    uploaded = []

    def http_mock(request, *, timeout):
        assert request.full_url == pob_sharing.UPLOAD_URL and request.method == "POST"
        assert timeout == pob_sharing.UPLOAD_TIMEOUT_SECONDS
        posted = urllib.parse.parse_qs(request.data.decode("ascii"), strict_parsing=True)
        uploaded.append(decode_code(posted["code"][0]))
        return _Response(b"https://poe.ninja/poe2/pob/isolated_test\n")

    monkeypatch.setattr(pob_sharing.urllib.request, "urlopen", http_mock)
    result = main.export_final_build_package(artifact_id, name="Isolated delivery regression")
    assert result["status"] == "exported", result
    assert result["exportedCount"] == result["expectedCount"] == 4
    assert result["runtimeCleanupReady"] is True
    inventory = {row["artifactType"]: row for row in result["artifacts"]}
    xml = Path(inventory["pob_xml"]["outputPath"]).read_text(encoding="utf-8")
    code = Path(inventory["pob_import_code"]["outputPath"]).read_text(encoding="utf-8").strip()
    build = json.loads(Path(inventory["official_build"]["outputPath"]).read_text(encoding="utf-8"))
    assert xml == decode_code(code) == DELIVERY_XML
    assert uploaded == [xml]
    assert build["name"] == "Isolated delivery regression"
    assert converter.validate_single_stage_build(build) == []
    lightning = next(row for row in build["skills"] if isinstance(row, dict))
    assert lightning["id"] == "Metadata/Items/Gem/SkillGemLightningArrow"
    assert lightning["support_skills"] == ["Metadata/Items/Gems/SupportGemMartialTempo"]
    assert inventory["official_build"]["guidanceOnly"]["authoritativeFormat"] == "pob_xml_or_import_code"
    assert inventory["poe_ninja_pob"]["url"] == "https://poe.ninja/poe2/pob/isolated_test"
    assert artifact["sourceHash"] == receipts[0]["transientBuildState"]["sourceHash"]
    assert result["deliveryStatus"] == artifact["deliveryStatus"]
    assert engine.get_xml() == DELIVERY_XML
    validation_checkpoint.clear_validation_checkpoint_cache()
