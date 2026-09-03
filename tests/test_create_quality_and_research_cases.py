from __future__ import annotations

import unittest

from server.generation import progression_provenance
from server.compute import completeness
from server.generation import models, preflight
from server.judge import hard_legality


AUTH_REF = "dq-1111111111111111"
COMPARE_REF = "dq-2222222222222222"
FAMILY = "bf-test-family"


def _receipt(ref: str, retrieval: str, case_ref: str) -> dict:
    return {
        "dedupeQueryRef": ref,
        "retrievalRef": retrieval,
        "pageIndex": 0,
        "pageCount": 1,
        "retrievalComplete": True,
        "manifestHash": f"manifest:{retrieval}",
        "memoryRevision": 7,
        "result": {
            "queryContractVersion": 2,
            "createAuthorizing": True,
            "selectedKnowledgeScope": "global_seed",
            "selectedSourceCaseRef": case_ref,
            "requestedBuildFamilyKeys": [FAMILY],
            "requestedGamePatch": "0.5.0",
            "requestedPassiveTreeVersion": "0_5",
            "familyAvailableSourceCaseLanes": [
                {
                    "knowledgeScope": "global_seed",
                    "sourceCaseRef": "case:a",
                    "eligibleRecordKindCount": 8,
                    "eligibleRecordCount": 10,
                },
                {
                    "knowledgeScope": "global_seed",
                    "sourceCaseRef": "case:b",
                    "eligibleRecordKindCount": 6,
                    "eligibleRecordCount": 7,
                },
            ],
            "comparisonRequiredCount": 1,
            "buildFamilies": [{"buildFamilyKey": FAMILY}],
            "deepRecordIds": [],
            "deepReadRecordIds": [],
            "patternIds": [],
            "semanticEdgeIds": [],
            "memoryItemIds": [],
            "familyRecordCoverage": [],
            "familyPremiseCatalog": [],
        },
    }


def _research_use(*, include_comparison: bool) -> dict:
    return {
        "retrievalOutcome": "matched",
        "dedupeQueryRefs": [AUTH_REF],
        "comparisonDedupeQueryRefs": [COMPARE_REF] if include_comparison else [],
        "componentKeys": [],
        "buildFamilyKeys": [FAMILY],
        "selectedKnowledgeScope": "global_seed",
        "selectedSourceCaseRef": "case:a",
        "deepRecordIds": [],
        "patternIds": [],
        "semanticEdgeIds": [],
        "memoryItemIds": [],
        "insightDecisions": [
            {
                "sourceRefs": [FAMILY],
                "decision": "adopted",
                "summary": "Family identity retained.",
                "application": "Use the selected Family shell.",
            }
        ],
        "premiseDecisions": [],
    }


class CreateCompletionGateTests(unittest.TestCase):
    def _build(self) -> dict:
        return {
            "spiritAvailable": 100.0,
            "spiritUsed": 81.0,
            "unspentPoints": 0,
            "passiveJewels": {"allocatedSockets": 2, "filledSockets": 2},
        }

    def test_complete_final_build_passes(self) -> None:
        result = hard_legality.check_create_completion(self._build(), required=True)
        self.assertTrue(result["ok"])

    def test_exactly_eighty_percent_spirit_triggers_opportunity_review(self) -> None:
        build = self._build()
        build["spiritUsed"] = 80.0
        result = hard_legality.check_create_completion(build, required=True)
        self.assertTrue(result["ok"])
        self.assertEqual([], result["hardFailures"])
        self.assertTrue(result["spirit"]["opportunityReviewRequired"])
        self.assertEqual(0.8, result["spirit"]["opportunityReviewThreshold"])

    def test_above_eighty_percent_spirit_needs_no_opportunity_review(self) -> None:
        result = hard_legality.check_create_completion(self._build(), required=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["spirit"]["opportunityReviewRequired"])

    def test_zero_spirit_utilization_requires_recorded_opportunity_review(self) -> None:
        self.assertTrue(
            completeness.spirit_opportunity_review_required(
                {"spiritAvailable": 100.0, "spiritRequested": 0.0}
            )
        )

    def test_objective_spirit_advisory_survives_hard_only_projection(self) -> None:
        projected = preflight.project_feedback(
            {
                "status": "needs_attention",
                "readyForJudge": True,
                "qualityAdvisories": [
                    "spirit_opportunity_review_required",
                    "subjective_example",
                ],
                "advisories": [
                    "spirit_opportunity_review_required",
                    "subjective_example",
                ],
                "completeness": {
                    "status": "needs_attention",
                    "hardFailures": [],
                    "advisories": [
                        "spirit_opportunity_review_required",
                        "subjective_example",
                    ],
                },
            },
            strict_mode=False,
        )
        self.assertEqual(
            ["spirit_opportunity_review_required"], projected["advisories"]
        )
        self.assertEqual("needs_attention", projected["status"])

    def test_spirit_over_reservation_remains_a_hard_failure(self) -> None:
        result = hard_legality.spirit_budget_check(
            {
                "spiritAvailable": 100.0,
                "spiritReservedCapped": 100.0,
                "spiritUnreserved": -10.0,
                "spiritRequested": 110.0,
                "spiritOverBy": 10.0,
                "spiritUsed": 110.0,
                "activeWeaponSet": 1,
            }
        )
        self.assertFalse(result["ok"])
        self.assertEqual("spirit_budget_exceeded", result["failureCode"])

    def test_final_candidate_must_decide_spirit_opportunity_advisory(self) -> None:
        state = models.TransientBuildStateRef.model_construct(
            completeness_advisories=["spirit_opportunity_review_required"]
        )
        missing = models.PrototypeBuildCandidate.model_construct(
            completeness_advisory_decisions=[]
        )
        with self.assertRaisesRegex(ValueError, "spirit_opportunity_review_required"):
            models._require_completeness_advisory_decisions(missing, state)

        deferred = models.PrototypeBuildCandidate.model_construct(
            completeness_advisory_decisions=[
                models.CompletenessAdvisoryDecision(
                    advisoryCode="spirit_opportunity_review_required",
                    decision="deferred",
                    reason="The remaining Spirit has not been evaluated yet.",
                )
            ]
        )
        with self.assertRaisesRegex(ValueError, "cannot remain deferred"):
            models._require_completeness_advisory_decisions(deferred, state)

        decided = models.PrototypeBuildCandidate.model_construct(
            completeness_advisory_decisions=[
                models.CompletenessAdvisoryDecision(
                    advisoryCode="spirit_opportunity_review_required",
                    decision="intentionally_unused",
                    reason="Current engine probes found no coherent reservation that improved the build.",
                )
            ]
        )
        models._require_completeness_advisory_decisions(decided, state)

    def test_empty_allocated_jewel_socket_fails(self) -> None:
        build = self._build()
        build["passiveJewels"]["filledSockets"] = 1
        result = hard_legality.check_create_completion(build, required=True)
        self.assertIn("allocated_passive_jewel_socket_empty", result["hardFailures"])

    def test_unspent_passive_point_fails(self) -> None:
        build = self._build()
        build["unspentPoints"] = 1
        result = hard_legality.check_create_completion(build, required=True)
        self.assertIn("unspent_passive_points_remaining", result["hardFailures"])


class ResearchCaseComparisonTests(unittest.TestCase):
    def test_available_second_case_is_required(self) -> None:
        receipts = {AUTH_REF: _receipt(AUTH_REF, "rq-auth", "case:a")}
        error, _, _ = progression_provenance.validate_research_use_receipts(
            research_memory_use=_research_use(include_comparison=False),
            receipt_reader=receipts.get,
        )
        self.assertEqual(error, "progression_research_case_comparison_incomplete")

    def test_complete_second_case_comparison_passes(self) -> None:
        receipts = {
            AUTH_REF: _receipt(AUTH_REF, "rq-auth", "case:a"),
            COMPARE_REF: _receipt(COMPARE_REF, "rq-compare", "case:b"),
        }
        error, summary, _ = progression_provenance.validate_research_use_receipts(
            research_memory_use=_research_use(include_comparison=True),
            receipt_reader=receipts.get,
        )
        self.assertIsNone(error)
        self.assertEqual((summary or {})["caseComparison"]["totalCasesReviewed"], 2)


if __name__ == "__main__":
    unittest.main()
