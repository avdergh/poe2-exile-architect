"""Canonical Research keys must survive the Create schema without rewriting identity."""

from copy import deepcopy
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from scripts import create_build
from server.generation import models
from server.knowledge import research_execution
from tests.test_generation_blueprint import _blueprint, _version_context
from tests.test_research_execution_contract import _cross_case_plan, _decision


UNIQUE_KEYS = ("unique:pob:kalandra's_touch", "unique:pob:lavianga's_spirits")


class GenerationStableKeyContractTests(unittest.TestCase):
    def test_contract_subjects_round_trip_without_identity_rewriting(self) -> None:
        subjects = research_execution._required_insight_decision_subjects(
            [
                {
                    "authority": "authoritative",
                    "recordId": "drr-source",
                    "sourceCaseRefs": ["source-hash:1234567890abcdef"],
                    "componentResponsibilities": [
                        {"componentKey": key, "role": "unique_enabler"} for key in UNIQUE_KEYS
                    ],
                }
            ],
            selected_source_case_ref="source-hash:1234567890abcdef",
        )
        usage = models.ResearchMemoryUse.model_validate(
            {
                "retrievalOutcome": "matched",
                "dedupeQueryRefs": ["dq-0123456789abcdef"],
                "deepRecordIds": ["drr-source"],
                "insightDecisions": [
                    {
                        "subjectRef": row["subjectRef"],
                        "sourceRefs": row["sourceRecordIds"],
                        "decision": "adopted",
                        "summary": "Preserve the canonical component identity.",
                        "application": "Equip the component and verify its actual resource duty.",
                    }
                    for row in subjects
                ],
            }
        ).model_dump(mode="json", by_alias=True)
        contract = {"requiredInsightDecisionSubjects": subjects}
        self.assertEqual(
            [row["subjectRef"] for row in usage["insightDecisions"]], list(UNIQUE_KEYS)
        )
        self.assertEqual(
            research_execution.validate_insight_decision_subjects(usage, contract), (None, [])
        )

        rewritten = deepcopy(usage)
        rewritten["insightDecisions"][0]["subjectRef"] = UNIQUE_KEYS[0].replace("'", "")
        self.assertEqual(
            research_execution.validate_insight_decision_subjects(rewritten, contract)[0],
            "research_execution_insight_subject_unknown",
        )
        wrong_source = deepcopy(usage)
        wrong_source["insightDecisions"][0]["sourceRefs"] = ["drr-other"]
        self.assertEqual(
            research_execution.validate_insight_decision_subjects(wrong_source, contract)[0],
            "research_execution_insight_subject_source_mismatch",
        )

    def test_component_evidence_survives_blueprint_and_package_models(self) -> None:
        blueprint = _blueprint(evidence_ref=UNIQUE_KEYS[0])
        blueprint["claims"][0]["componentKeys"] = list(UNIQUE_KEYS)
        parsed = models.MechanismBlueprint.model_validate(blueprint)
        self.assertEqual(parsed.claims[0].component_keys, list(UNIQUE_KEYS))
        decision = _decision("rep-1111111111111111", adopted=True)
        decision["verificationEvidenceRefs"] = list(UNIQUE_KEYS)
        self.assertEqual(
            models.ResearchExecutionPackageDecision.model_validate(
                decision
            ).verification_evidence_refs,
            list(UNIQUE_KEYS),
        )
        plan = _cross_case_plan()
        plan["evidenceRefs"] = list(UNIQUE_KEYS)
        self.assertEqual(
            models.CrossCaseMechanismPlan.model_validate(plan).evidence_refs, list(UNIQUE_KEYS)
        )

    def test_reference_charset_and_bounds_remain_restricted(self) -> None:
        for ref in (
            "unique:pob:bad key",
            "unique:pob:bad\nkey",
            'unique:pob:bad"key',
            "unique:pob:bad;key",
            "unique:pob:" + "x" * 240,
        ):
            with self.subTest(ref=ref):
                decision = _decision("rep-1111111111111111", adopted=True)
                decision["verificationEvidenceRefs"] = [ref]
                with self.assertRaises(ValidationError):
                    models.ResearchExecutionPackageDecision.model_validate(decision)
                with self.assertRaises(ValidationError):
                    models.ResearchMemoryInsightDecision.model_validate(
                        {
                            "subjectRef": ref,
                            "sourceRefs": ["drr-source"],
                            "decision": "adopted",
                            "summary": "Canonical subject.",
                            "application": "Verify actual item.",
                        }
                    )

    def test_public_blueprint_boundary_still_rejects_full_urls(self) -> None:
        draft = {
            "candidateId": "candidate:test",
            "versionContext": _version_context(),
            "noRawMaterial": True,
            "toolReferences": [
                {
                    "toolName": "graph_tool_query",
                    "queryRef": UNIQUE_KEYS[0],
                    "summary": "Exact canonical component evidence.",
                    "evidenceKind": "agent_reviewed",
                    "reviewBasis": "Agent inspected the exact canonical component and its mechanism conditions.",
                }
            ],
            "mechanismBlueprint": _blueprint(evidence_ref=UNIQUE_KEYS[0]),
        }
        with (
            TemporaryDirectory() as run_dir,
            patch.dict(os.environ, {"POE_BD_CREATE_RUNS_DIR": run_dir}),
        ):
            run = create_build.start_generation_run("no_memory")["runContext"]
            accepted = create_build.validate_generation_blueprint(
                run["runId"], run["runToken"], draft
            )
            self.assertEqual(accepted["status"], "accepted")
            draft["toolReferences"][0]["queryRef"] = "https://example.com/item"
            result = create_build.validate_generation_blueprint(
                run["runId"], run["runToken"], draft
            )
        self.assertEqual(result["errorCode"], "copy_safety_violation")


if __name__ == "__main__":
    unittest.main()
