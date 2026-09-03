from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from pydantic import ValidationError

from scripts import create_build
from server.generation import models
from server.knowledge import research_execution


AUTH_PACKAGE = "rep-1111111111111111"
COMPARE_PACKAGE = "rep-2222222222222222"
PLAN_ID = "xcp-3333333333333333"
CONTRACT_REF = "rec-4444444444444444"


def _contract() -> dict:
    return {
        "status": "ready",
        "contractRef": CONTRACT_REF,
        "selectedDesignCaseRef": "case:authoritative",
        "comparisonCaseRefs": ["case:comparison"],
        "authoritativeDeepReadRecordIds": ["drr-auth-record"],
        "comparisonDeepReadRecordIds": ["drr-compare-record"],
        "reviewRequiredPackageIds": [AUTH_PACKAGE, COMPARE_PACKAGE],
        "packages": [
            {
                "packageId": AUTH_PACKAGE,
                "recordId": "drr-auth-record",
                "authority": "authoritative",
                "sourceCaseRefs": ["case:authoritative"],
            },
            {
                "packageId": COMPARE_PACKAGE,
                "recordId": "drr-compare-record",
                "authority": "comparison",
                "sourceCaseRefs": ["case:comparison"],
            },
        ],
    }


def _decision(package_id: str, *, adopted: bool, plan_ref: str | None = None) -> dict:
    return {
        "packageId": package_id,
        "decision": "adopted" if adopted else "retained_as_alternative",
        "mechanismRationale": (
            "The package has a concrete mechanical duty and was compared against the selected "
            "variant instead of being copied for generic power."
        ),
        "buildApplication": (
            "Apply the exact duty through the named skill, gear, passive, and resource slots, "
            "then verify the resulting active build state."
        ),
        "verificationEvidenceRefs": ["checkpoint:test-state"],
        "crossCasePlanRef": plan_ref,
    }


def _cross_case_plan() -> dict:
    return {
        "planId": PLAN_ID,
        "sourceCaseRefs": ["case:comparison"],
        "sourcePackageIds": [COMPARE_PACKAGE],
        "targetCompanionPackageIds": [AUTH_PACKAGE],
        "additionalCompanionPackageIds": [],
        "mechanismRationale": (
            "The transferred mechanism closes a resource duty that the selected case leaves "
            "open, and the full source package is retained rather than extracting one modifier."
        ),
        "compatibilityRationale": (
            "Its skill tags, weapon requirements, reservation demand, and trigger ownership are "
            "compatible with the authoritative package after the listed companion changes."
        ),
        "tradeoffRationale": (
            "The plan accepts an explicit socket and gear opportunity cost in exchange for a "
            "measurable resource and rotation benefit."
        ),
        "implementationPlan": [
            "Install the complete source skill and support duty in a dedicated enabled group.",
            "Rebalance the authoritative gear and passive responsibilities around that duty.",
        ],
        "conflictResolutionPlan": [
            "Remove the conflicting resource assumption and keep only the verified replacement."
        ],
        "verificationPlan": [
            "Verify the selected skill group, reservation ledger, and resource stats in PoB.",
            "Run checkpoint and lifecycle checks with the same boss combat assumptions.",
        ],
        "failureExitConditions": [
            "Reject the transfer if the resource loop, legality, or target-case defenses regress."
        ],
        "evidenceRefs": ["checkpoint:test-state", "mechanic:test-mechanism"],
    }


class ResearchExecutionPlanTests(unittest.TestCase):
    def test_complete_cross_case_plan_passes(self) -> None:
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": (
                "The authoritative case best matches the requested stage, defense model, and "
                "operation budget after comparing every available case profile."
            ),
            "coherenceSummary": (
                "The final package keeps one defense and resource model, and every transferred "
                "mechanism includes its companion skills, gear, passives, and verification plan."
            ),
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=True, plan_ref=PLAN_ID),
            ],
            "crossCaseMechanismPlans": [_cross_case_plan()],
        }
        validated = models.ResearchExecutionPlan.model_validate(payload)
        error, caveats, summary = research_execution.validate_research_execution_plan(
            validated.model_dump(mode="json", by_alias=True),
            _contract(),
        )
        self.assertIsNone(error)
        self.assertEqual(caveats, [])
        self.assertEqual((summary or {})["adoptedCrossCasePackageCount"], 1)

    def test_cross_case_adoption_without_plan_is_rejected(self) -> None:
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "A" * 90,
            "coherenceSummary": "B" * 90,
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=True),
            ],
            "crossCaseMechanismPlans": [],
        }
        validated = models.ResearchExecutionPlan.model_validate(payload)
        error, _, _ = research_execution.validate_research_execution_plan(
            validated.model_dump(mode="json", by_alias=True),
            _contract(),
        )
        self.assertEqual(error, "research_execution_cross_case_plan_required")

    def test_comparison_package_may_be_retained_as_alternative(self) -> None:
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "A" * 90,
            "coherenceSummary": "B" * 90,
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=False),
            ],
            "crossCaseMechanismPlans": [],
        }
        validated = models.ResearchExecutionPlan.model_validate(payload)
        error, _, _ = research_execution.validate_research_execution_plan(
            validated.model_dump(mode="json", by_alias=True),
            _contract(),
        )
        self.assertIsNone(error)

    def test_generic_cross_case_steps_fail_schema(self) -> None:
        plan = _cross_case_plan()
        plan["implementationPlan"] = ["Use it", "Test it"]
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "A" * 90,
            "coherenceSummary": "B" * 90,
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=True, plan_ref=PLAN_ID),
            ],
            "crossCaseMechanismPlans": [plan],
        }
        with self.assertRaises(ValidationError):
            models.ResearchExecutionPlan.model_validate(payload)

    def test_unregistered_evidence_ref_is_rejected(self) -> None:
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "A" * 90,
            "coherenceSummary": "B" * 90,
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=False),
            ],
            "crossCaseMechanismPlans": [],
        }
        validated = models.ResearchExecutionPlan.model_validate(payload)
        error, _, _ = research_execution.validate_research_execution_plan(
            validated.model_dump(mode="json", by_alias=True),
            _contract(),
            allowed_evidence_refs={AUTH_PACKAGE, COMPARE_PACKAGE},
        )
        self.assertEqual(error, "research_execution_decision_evidence_unknown")

    def test_structure_hash_allows_judge_driven_realization_updates(self) -> None:
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "A" * 90,
            "coherenceSummary": "B" * 90,
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=True, plan_ref=PLAN_ID),
            ],
            "crossCaseMechanismPlans": [_cross_case_plan()],
        }
        validated = models.ResearchExecutionPlan.model_validate(payload)
        camel = validated.model_dump(mode="json", by_alias=True)
        snake = validated.model_dump(mode="json", by_alias=False)
        revised = deepcopy(camel)
        revised["selectedVariantRationale"] = "Judge evidence refined this rationale. " * 4
        revised["coherenceSummary"] = "The final implementation now reflects the verified state. " * 3
        for decision in revised["packageDecisions"]:
            decision["mechanismRationale"] = "Updated mechanism explanation after Judge. " * 3
            decision["buildApplication"] = "Apply the corrected supports, gear, and passives. " * 2
            decision["verificationEvidenceRefs"] = ["checkpoint:judge-retry"]
        cross_case = revised["crossCaseMechanismPlans"][0]
        cross_case["mechanismRationale"] = "Updated mechanism evidence after Judge. " * 4
        cross_case["compatibilityRationale"] = "Updated compatibility evidence after Judge. " * 4
        cross_case["tradeoffRationale"] = "Updated trade-off evidence after Judge. " * 3
        cross_case["implementationPlan"] = [
            "Apply the corrected skill and support arrangement from the passing Judge state.",
            "Rebalance gear and passives around the corrected resource requirement.",
        ]
        cross_case["conflictResolutionPlan"] = [
            "Remove the conflicting pre-Judge implementation and retain the verified replacement."
        ]
        cross_case["verificationPlan"] = [
            "Verify the corrected active skill group and resource ledger in PoB.",
            "Run the final Judge against the corrected combat assumptions and build state.",
        ]
        cross_case["failureExitConditions"] = [
            "Reject the correction if the final resource loop or defenses regress."
        ]
        cross_case["evidenceRefs"] = ["checkpoint:judge-retry"]

        expected = research_execution.stable_plan_structure_hash(camel)
        self.assertEqual(research_execution.stable_plan_structure_hash(snake), expected)
        self.assertEqual(research_execution.stable_plan_structure_hash(revised), expected)
        self.assertNotEqual(
            research_execution.stable_plan_hash(revised),
            research_execution.stable_plan_hash(camel),
        )

    def test_structure_hash_rejects_decision_or_dependency_changes(self) -> None:
        payload = {
            "contractRef": CONTRACT_REF,
            "selectedDesignCaseRef": "case:authoritative",
            "selectedVariantRationale": "A" * 90,
            "coherenceSummary": "B" * 90,
            "packageDecisions": [
                _decision(AUTH_PACKAGE, adopted=True),
                _decision(COMPARE_PACKAGE, adopted=True, plan_ref=PLAN_ID),
            ],
            "crossCaseMechanismPlans": [_cross_case_plan()],
        }
        baseline = models.ResearchExecutionPlan.model_validate(payload).model_dump(
            mode="json",
            by_alias=True,
        )
        decision_changed = deepcopy(baseline)
        decision_changed["packageDecisions"][0]["decision"] = "tested_and_rejected"
        dependency_changed = deepcopy(baseline)
        dependency_changed["crossCaseMechanismPlans"][0][
            "targetCompanionPackageIds"
        ] = ["rep-9999999999999999"]

        expected = research_execution.stable_plan_structure_hash(baseline)
        self.assertNotEqual(
            research_execution.stable_plan_structure_hash(decision_changed),
            expected,
        )
        self.assertNotEqual(
            research_execution.stable_plan_structure_hash(dependency_changed),
            expected,
        )


class ResearchExecutionDraftBoundaryTests(unittest.TestCase):
    def _validate_with_marker(self, marker: dict, summary: dict) -> tuple[str | None, list[str]]:
        payload = {
            "prototypeBuildCandidate": {
                "researchMemoryUse": {"retrievalOutcome": "matched"},
                "versionContext": {
                    "gamePatch": "0.5.0",
                    "passiveTreeVersion": "0_5",
                },
                "researchExecutionPlan": {"contractRef": CONTRACT_REF},
                "toolReferences": [],
            }
        }
        contract = {"status": "ready", "contractRef": CONTRACT_REF, "packages": []}
        with TemporaryDirectory() as directory:
            Path(directory, "draft-validation.json").write_text(
                json.dumps(marker),
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    create_build.progression_provenance,
                    "validate_research_use_receipts",
                    return_value=(None, {}, []),
                ),
                mock.patch.object(
                    create_build.research_execution,
                    "construct_from_research_use",
                    return_value=contract,
                ),
                mock.patch.object(
                    create_build.research_execution,
                    "validate_research_execution_plan",
                    return_value=(None, [], summary),
                ),
            ):
                return create_build._validate_candidate_research_use(
                    payload,
                    receipt_reader=lambda _ref: None,
                    run_dir=Path(directory),
                )

    def test_new_marker_allows_full_plan_change_when_structure_matches(self) -> None:
        error, caveats = self._validate_with_marker(
            {
                "researchExecutionContractRef": CONTRACT_REF,
                "researchExecutionPlanHash": "draft-full-plan",
                "researchExecutionStructureHash": "stable-structure",
            },
            {"planHash": "final-full-plan", "structureHash": "stable-structure"},
        )
        self.assertIsNone(error)
        self.assertEqual(caveats, [])

    def test_new_marker_rejects_structure_change(self) -> None:
        error, _ = self._validate_with_marker(
            {
                "researchExecutionContractRef": CONTRACT_REF,
                "researchExecutionPlanHash": "draft-full-plan",
                "researchExecutionStructureHash": "draft-structure",
            },
            {"planHash": "final-full-plan", "structureHash": "final-structure"},
        )
        self.assertEqual(error, "research_execution_plan_changed_after_draft")

    def test_legacy_marker_keeps_full_plan_freeze(self) -> None:
        error, _ = self._validate_with_marker(
            {
                "researchExecutionContractRef": CONTRACT_REF,
                "researchExecutionPlanHash": "draft-full-plan",
            },
            {"planHash": "final-full-plan", "structureHash": "stable-structure"},
        )
        self.assertEqual(error, "research_execution_plan_changed_after_draft")


class AdoptedPrimarySkillPackageTests(unittest.TestCase):
    def _plan(self) -> models.ResearchExecutionPlan:
        return models.ResearchExecutionPlan.model_validate(
            {
                "contractRef": CONTRACT_REF,
                "selectedDesignCaseRef": "case:authoritative",
                "selectedVariantRationale": (
                    "The authoritative package is selected because it owns the primary damage "
                    "skill and its complete socket responsibility for this fixture."
                ),
                "coherenceSummary": (
                    "The fixture keeps a single coherent primary skill package and verifies its "
                    "declared support variants against the observed Draft signature."
                ),
                "packageDecisions": [_decision(AUTH_PACKAGE, adopted=True)],
                "crossCaseMechanismPlans": [],
            }
        )

    @staticmethod
    def _contract_with_support_packages(packages) -> dict:
        return {
            "packages": [
                {
                    "packageId": AUTH_PACKAGE,
                    "recordKind": "skill_package",
                    "componentResponsibilities": [
                        {
                            "componentKey": "skill:WhirlingAssaultPlayer",
                            "role": "primary_damage",
                        }
                    ],
                    "typedResponsibilities": {"supportPackages": packages},
                }
            ]
        }

    def _check(self, packages, supports):
        def gem(name):
            values = {
                "Whirling Assault": {
                    "grants": ["WhirlingAssaultPlayer"],
                    "id": "Metadata/Items/Gems/SkillGemWhirlingAssault",
                },
                "Brutality I": {
                    "grants": ["SupportBrutalityPlayer"],
                    "id": "Metadata/Items/Gems/SupportGemBrutality",
                },
                "Rapid Attacks I": {
                    "grants": ["SupportRapidAttacksPlayer"],
                    "id": "Metadata/Items/Gems/SupportGemRapidAttacks",
                },
            }
            return values.get(name)

        with mock.patch.object(create_build.knowledge_db, "get_gem", side_effect=gem):
            return create_build._adopted_primary_skill_package_error(
                execution_contract=self._contract_with_support_packages(packages),
                execution_plan=self._plan(),
                observed_signature={
                    "activeSkillName": "Whirling Assault",
                    "supportNames": supports,
                },
            )

    def test_missing_declared_support_package_does_not_invent_a_mismatch(self) -> None:
        self.assertIsNone(self._check([], ["Brutality I"]))

    def test_multiple_declared_variants_accept_one_complete_match(self) -> None:
        packages = [
            {
                "skillKey": "skill:WhirlingAssaultPlayer",
                "supportKeys": ["support:SupportGemBrutality"],
            },
            {
                "skillKey": "skill:WhirlingAssaultPlayer",
                "supportKeys": ["support:SupportGemRapidAttacks"],
            },
        ]
        self.assertIsNone(self._check(packages, ["Rapid Attacks I"]))
        self.assertEqual(
            self._check(packages, ["Brutality I", "Rapid Attacks I"]),
            "research_execution_adoption_mismatch",
        )


if __name__ == "__main__":
    unittest.main()
