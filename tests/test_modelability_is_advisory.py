from __future__ import annotations

import unittest

from server import main
from server.generation import preflight
from server.judge import comparison, modelability, rules, runner, sample_audit
from server.knowledge import lifecycle_verification


def _skill_xml(*names: str) -> str:
    gems = "".join(
        f'<Gem enabled="true" gemId="Metadata/Items/Gems/{name.replace(" ", "")}" '
        f'nameSpec="{name}" skillId="{name.replace(" ", "")}" />'
        for name in names
    )
    return (
        '<PathOfBuilding><Build mainSocketGroup="1" />'
        '<Skills activeSkillSet="1"><SkillSet id="1">'
        f'<Skill enabled="true">{gems}</Skill>'
        '</SkillSet></Skills></PathOfBuilding>'
    )


class ModelabilityAdvisoryTests(unittest.TestCase):
    def test_meta_host_and_payload_are_a_legal_active_composition(self) -> None:
        group = [
            {"name": "Cast on Critical", "isSupport": True},
            {"name": "Comet", "isSupport": False},
            {"name": "Arcane Tempo", "isSupport": True, "supportKnown": True},
        ]

        failures, caveats = rules.check_main_skill_group(group)

        self.assertEqual(failures, [])
        self.assertEqual(caveats, [])
        self.assertTrue(rules.is_valid_active_skill_group(["Cast on Critical", "Comet"]))

    def test_ordinary_multi_active_group_still_fails(self) -> None:
        failures, _ = rules.check_main_skill_group(
            [
                {"name": "Spark", "isSupport": False},
                {"name": "Comet", "isSupport": False},
            ]
        )

        self.assertIn("invalid_socket_setup", failures)
        self.assertFalse(rules.is_valid_active_skill_group(["Spark", "Comet"]))

    def test_preflight_socket_check_accepts_meta_host_payload_xml(self) -> None:
        meta = preflight.inspect_main_skill_socketed(_skill_xml("Cast on Critical", "Comet"))
        ordinary = preflight.inspect_main_skill_socketed(_skill_xml("Spark", "Comet"))

        self.assertTrue(meta["socketed"])
        self.assertEqual(meta["activeSkillCount"], 2)
        self.assertFalse(ordinary["socketed"])

    def test_runtime_effect_names_do_not_change_socket_structure(self) -> None:
        xml = _skill_xml("Ruzhan, the Blazing Sword")
        parsed = preflight._parse_skill_groups(xml)  # noqa: SLF001 - structural regression test.

        class FakeEngine:
            @staticmethod
            def call(method: str) -> dict:
                self_result = {
                    "groups": [
                        {
                            "index": 1,
                            "rootSkillId": "Ruzhan,theBlazingSword",
                            "mainActiveSkillCalcs": 2,
                            "activeSkills": [
                                {"index": 1, "name": "Ruzhan, the Blazing Sword"},
                                {"index": 2, "name": "Command"},
                            ],
                        }
                    ]
                }
                if method != "list_skill_groups":
                    raise AssertionError(method)
                return self_result

        preflight._decorate_runtime_active_names(FakeEngine(), parsed)  # noqa: SLF001
        group = parsed["groups"][0]
        self.assertEqual(group["activeNames"], [
            "Ruzhan, the Blazing Sword",
            "Command",
        ])
        self.assertEqual(group["socketedActiveNames"], ["Ruzhan, the Blazing Sword"])
        self.assertEqual(group["mainActiveSkillCalcs"], 2)
        self.assertIsNone(group["activeSkillSelectionError"])
        self.assertTrue(preflight._socket_composition_valid(group))  # noqa: SLF001

    def test_current_payload_hosts_are_structurally_accepted(self) -> None:
        for host, payload in (
            ("Cast on Dodge", "Comet"),
            ("Cast on Elemental Ailment", "Comet"),
            ("Spell Totem", "Spark"),
            ("Blasphemy", "Vulnerability"),
            ("Spellslinger", "Comet"),
        ):
            with self.subTest(host=host):
                self.assertTrue(rules.is_valid_active_skill_group([host, payload]))

    def test_unmodelled_meta_is_advisory_not_a_core_blocker(self) -> None:
        result = modelability.evaluate_modelability(
            {
                "mainSkillGroup": [
                    {"name": "Cast on Critical", "isSupport": False},
                    {"name": "Comet", "isSupport": False},
                ]
            }
        )

        self.assertEqual(result["status"], "not_modelable")
        self.assertFalse(result["coreBlocked"])
        self.assertEqual(result["failureCodes"], [])

    def test_unavailable_score_abstains_from_numeric_comparison(self) -> None:
        candidate = {
            "pass": True,
            "aggregateScore": {"value": 0.7},
            "modelability": {"status": "not_modelable", "coreBlocked": False},
            "scoreApplicability": {"status": "unavailable"},
        }
        reference = {
            "pass": True,
            "aggregateScore": {"value": 0.6},
            "modelability": {"status": "full", "coreBlocked": False},
            "scoreApplicability": {"status": "applicable"},
        }

        result = comparison.compare_evaluations(candidate, reference)

        self.assertEqual(result["selectionWinner"], "unknown")
        self.assertEqual(result["rewardWinner"], "unknown")
        self.assertEqual(result["comparisonStatus"], "numeric_evidence_unavailable")
        self.assertEqual(result["rewardStrength"], "none")

    def test_pob_support_is_advisory_for_every_lifecycle_stage(self) -> None:
        for stage in lifecycle_verification.known_stages():
            with self.subTest(stage=stage):
                plan = lifecycle_verification.plan_stage_verification(stage)
                self.assertNotIn("pob_model_supported", plan["requiredChecks"])
                self.assertIn("pob_model_supported", plan["advisoryChecks"])

    def test_detected_unmodelled_recovery_does_not_block_lifecycle(self) -> None:
        result = lifecycle_verification._sustain_check(  # noqa: SLF001 - policy regression test.
            {
                "manaSustain": {
                    "classification": "model_gap_flask_assisted",
                    "unmodelledManaMechanisms": ["mana_remnants"],
                }
            }
        )

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["ok"])
        self.assertTrue(result["verificationRequired"])

    def test_pob_compute_failure_is_not_a_build_hard_failure(self) -> None:
        result = runner.compute_failed_evaluation("snapshot:test", "TimeoutError")

        self.assertFalse(result["pass"])
        self.assertEqual(result["hardFailures"], [])
        self.assertFalse(result["modelability"]["coreBlocked"])
        self.assertEqual(result["scoreApplicability"]["status"], "unavailable")

    def test_unavailable_numeric_score_does_not_trigger_score_repair(self) -> None:
        result = sample_audit.finalize_sample_classification(
            {
                "pass": True,
                "playabilityFailures": [],
                "hardFailures": [],
                "scoreApplicability": {"status": "unavailable"},
                "aggregateScore": {"value": 0.0},
                "scoreVector": {
                    "offense": {"value": 0.0},
                    "defense": {"value": 1.0},
                    "recovery": {"value": 1.0},
                    "mobility": {"value": 1.0},
                },
            }
        )

        self.assertFalse(result["scoreReviewNeeded"])
        self.assertEqual(result["finalClassification"], "judge_pass_numeric_evidence_limited")

    def test_unavailable_offense_still_audits_other_dimensions(self) -> None:
        result = sample_audit.finalize_sample_classification(
            {
                "pass": True,
                "playabilityFailures": [],
                "hardFailures": [],
                "scoreApplicability": {"status": "unavailable"},
                "aggregateScore": {"value": 0.0},
                "scoreVector": {
                    "offense": {"value": 0.0},
                    "defense": {"value": 0.2},
                    "recovery": {"value": 1.0},
                    "mobility": {"value": 1.0},
                },
                "scoreBreakdown": {"defense": {}},
                "defenseModel": {},
            }
        )

        self.assertIn("defense_below_0_5", result["scoreReviewReasons"])
        self.assertNotEqual(
            result["finalClassification"],
            "judge_pass_numeric_evidence_limited",
        )

    def test_compute_error_is_not_compared_as_an_invalid_build(self) -> None:
        failed = runner.compute_failed_evaluation("snapshot:test", "TimeoutError")
        reference = {
            "pass": True,
            "aggregateScore": {"value": 0.6},
            "scoreApplicability": {"status": "applicable"},
        }

        result = comparison.compare_evaluations(failed, reference)

        self.assertEqual(result["selectionWinner"], "unknown")
        self.assertEqual(result["comparisonStatus"], "candidate_evidence_unavailable")

    def test_compact_lifecycle_does_not_label_advisory_as_blocking(self) -> None:
        result = main._compact_lifecycle_verification_response(  # noqa: SLF001
            {
                "ok": True,
                "stage": "endgame_final",
                "status": "passed",
                "pass": True,
                "failedChecks": [],
                "unknownChecks": [],
                "checks": [
                    {"check": "main_skill_socketed", "status": "passed"},
                    {"check": "basic_defense_online", "status": "passed"},
                    {"check": "sustain_ok", "status": "passed"},
                    {"check": "pob_model_supported", "status": "failed"},
                ],
            }
        )

        self.assertTrue(result["pass"])
        self.assertEqual(result["blockingChecks"], [])
        self.assertEqual(result["checkStatuses"]["pob_model_supported"], "failed")


if __name__ == "__main__":
    unittest.main()
