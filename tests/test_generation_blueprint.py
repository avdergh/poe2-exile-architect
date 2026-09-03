from __future__ import annotations

import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import create_build
from server.generation import models


EVIDENCE_REF = "graph:blueprint-test"


def _blueprint(*, evidence_ref: str = EVIDENCE_REF) -> dict:
    claims = [
        {
            "claimId": f"mbc-{index:016x}",
            "title": title,
            "status": "grounded",
            "explanation": (
                f"{title} is described as a causal build mechanism with its prerequisites, "
                "failure window, downstream responsibilities and explicit verification boundary. "
                "The statement is intentionally substantive rather than a short generic label."
            ),
            "sourceRefs": [evidence_ref],
            "componentKeys": [f"skill:BlueprintTest{index}"],
            "conditions": ["The referenced component is active in the selected design."],
            "failureConditions": ["The mechanism stops when its prerequisite is absent."],
            "verificationTasks": ["Verify the stated interaction against current engine facts."],
        }
        for index, title in enumerate(
            [
                "Damage delivery",
                "Clear and boss operation",
                "Defense and life recovery",
                "Mana, Spirit and rotation",
            ],
            start=1,
        )
    ]
    coverage_claims = {
        "damage_delivery": claims[0]["claimId"],
        "clear": claims[1]["claimId"],
        "boss": claims[1]["claimId"],
        "defense": claims[2]["claimId"],
        "life_recovery": claims[2]["claimId"],
        "mana_recovery": claims[3]["claimId"],
        "spirit": claims[3]["claimId"],
        "rotation": claims[3]["claimId"],
    }
    document = "\n\n".join(
        [
            "This free-form mechanism dossier explains how the selected build produces and "
            "delivers damage, separates ordinary-pack clearing from no-add Boss operation, and "
            "identifies the precise trigger and uptime assumptions that must remain true.",
            "It then models the primary defensive pool, mitigation and recovery sequence across "
            "hit, no-hit, kill and no-kill states. Resource costs, Spirit reservations and the "
            "player action loop are treated as causal systems rather than disconnected stats.",
            "Every adopted conclusion is tied to the evidence index below. Missing dynamic values "
            "remain verification tasks instead of being invented, and downstream equipment is "
            "assigned responsibilities only after this blueprint is accepted.",
        ]
    )
    document = (document + "\n") * 3
    return {
        "document": document,
        "claims": claims,
        "coverage": [
            {
                "axis": axis,
                "status": "covered",
                "explanation": (
                    f"The {axis} direction is explicitly explained by an evidence-backed claim "
                    "and retains its conditions, failure state and verification boundary."
                ),
                "claimRefs": [claim_ref],
            }
            for axis, claim_ref in coverage_claims.items()
        ],
        "unresolvedQuestions": [
            "Dynamic encounter uptime remains subject to current PoB and practical verification."
        ],
    }


def _version_context() -> dict:
    return {
        "league": "test-league",
        "ruleset": "poe2",
        "gamePatch": "0.5.4",
        "passiveTreeVersion": "0_5",
        "pobVersionOrCommit": "test-pob",
        "graphSnapshotId": "test-graph",
        "researchMemoryRef": "disabled:no_memory_baseline",
    }


class MechanismBlueprintTests(unittest.TestCase):
    def test_generation_experiment_context_accepts_current_blueprint_flag(self) -> None:
        context = models.GenerationExperimentContext.model_validate(
            {
                "memoryMode": "memory_assisted",
                "maxRetryCount": 2,
                "globalOptimizerAllowed": False,
                "passiveTreeOptimizationMode": "manual_targeted",
                "mutationBatchPreferred": True,
                "mechanismBlueprintRequired": True,
            }
        )
        self.assertTrue(context.mechanism_blueprint_required)
        self.assertTrue(context.model_dump(by_alias=True)["mechanismBlueprintRequired"])

    def test_generation_experiment_context_keeps_legacy_default(self) -> None:
        context = models.GenerationExperimentContext.model_validate(
            {
                "memoryMode": "standard",
                "maxRetryCount": 2,
                "globalOptimizerAllowed": False,
                "passiveTreeOptimizationMode": "manual_targeted",
                "mutationBatchPreferred": True,
            }
        )
        self.assertFalse(context.mechanism_blueprint_required)

    def test_started_run_experiment_context_matches_review_schema(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"POE_BD_CREATE_RUNS_DIR": temp_dir},
        ):
            run = create_build.start_generation_run("memory_assisted")
            context = models.GenerationExperimentContext.model_validate(
                run["experimentContext"]
            )
        self.assertTrue(context.mechanism_blueprint_required)

    def test_blueprint_requires_all_coverage_axes(self) -> None:
        payload = _blueprint()
        payload["coverage"] = payload["coverage"][:-1]
        with self.assertRaises(models.ValidationError):
            models.MechanismBlueprint.model_validate(payload)

    def test_non_unknown_claim_requires_evidence(self) -> None:
        payload = _blueprint()
        payload["claims"][0]["sourceRefs"] = []
        with self.assertRaises(models.ValidationError):
            models.MechanismBlueprint.model_validate(payload)

    def test_no_memory_blueprint_is_validated_and_bound(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"POE_BD_CREATE_RUNS_DIR": temp_dir},
        ):
            run = create_build.start_generation_run("no_memory")
            context = run["runContext"]
            draft = {
                "candidateId": "candidate:blueprint-test",
                "versionContext": _version_context(),
                "noRawMaterial": True,
                "researchMemoryUse": None,
                "researchExecutionPlan": None,
                "toolReferences": [
                    {
                        "toolName": "graph_tool_query",
                        "queryRef": EVIDENCE_REF,
                        "summary": "Current graph evidence for the blueprint test.",
                    }
                ],
                "mechanismBlueprint": _blueprint(),
            }
            result = create_build.validate_generation_blueprint(
                context["runId"],
                context["runToken"],
                draft,
            )
            self.assertEqual("accepted", result["status"])
            self.assertRegex(result["blueprintRef"], r"^gbp-[0-9a-f]{16}$")
            run_dir = Path(temp_dir) / context["runId"]
            self.assertTrue((run_dir / "mechanism-blueprint.json").exists())
            self.assertTrue((run_dir / "mechanism-blueprint-validation.json").exists())
            manifest = json.loads(
                (run_dir / "run-manifest.json").read_text(encoding="utf-8")
            )
            error, _marker = create_build._validate_candidate_blueprint_use(
                {
                    "candidateId": draft["candidateId"],
                    "versionContext": draft["versionContext"],
                    "mechanismBlueprintRef": result["blueprintRef"],
                    "mechanismBlueprint": draft["mechanismBlueprint"],
                },
                run_dir=run_dir,
                manifest=manifest,
                require_draft_binding=False,
            )
            self.assertIsNone(error)
            missing_error, _missing_marker = create_build._validate_candidate_blueprint_use(
                {
                    "candidateId": draft["candidateId"],
                    "versionContext": draft["versionContext"],
                },
                run_dir=run_dir,
                manifest=manifest,
                require_draft_binding=False,
            )
            self.assertEqual("generation_mechanism_blueprint_required", missing_error)

    def test_blueprint_rejects_unresolved_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"POE_BD_CREATE_RUNS_DIR": temp_dir},
        ):
            run = create_build.start_generation_run("no_memory")
            context = run["runContext"]
            result = create_build.validate_generation_blueprint(
                context["runId"],
                context["runToken"],
                {
                    "candidateId": "candidate:blueprint-test",
                    "versionContext": _version_context(),
                    "noRawMaterial": True,
                    "toolReferences": [
                        {
                            "toolName": "graph_tool_query",
                            "queryRef": "graph:different-evidence",
                            "summary": "A different graph receipt.",
                        }
                    ],
                    "mechanismBlueprint": _blueprint(),
                },
            )
            self.assertEqual("rejected", result["status"])
            self.assertEqual("mechanism_blueprint_evidence_unresolved", result["errorCode"])


if __name__ == "__main__":
    unittest.main()
