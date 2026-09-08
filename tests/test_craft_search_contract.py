"""Craft consumer tests for the shared replacement-search and trusted-receipt contract."""

from copy import deepcopy

import pytest

from server.compute import craftopt
from server.compute.state import build_state_hash
from tests.test_item_search_contract import ItemOracle, raw_item


SLOT = "Body Armour"
BASE = "Sacramental Robe"
ORIGINAL = raw_item(["+40 to maximum Life"], BASE)
CONTEXT = {"groupIndex": 3, "activeSkillIndex": 2, "skillName": "Fireball"}


class CraftOracle(ItemOracle):
    info = {}

    def __init__(self):
        super().__init__(
            {SLOT: ORIGINAL, "Helmet": raw_item(base="Silk Hood")},
            {
                "+40 to maximum Life": 40,
                "+100 to maximum Life": 100,
                "{rune}+20 to Armour": 20,
                "+1 to Level of all Skills": 5,
            },
        )
        self.options = {
            "ok": True,
            "essences": [],
            "runes": [{"name": "Iron Rune", "mods": ["+20 to Armour"]}],
            "corruptions": [{"line": "+1 to Level of all Skills"}],
        }
        self.add_count = 0
        self.batch_count = 0
        self.fail_batch = None
        self.fail_batch_result = None
        self.fail_add_at = None
        self.corrupt_final_item = False
        self.context_drift_at = None
        self.invalid_stats_at = None
        self.fail_final_restore = False
        self.silent_final_restore = False
        self.drop_final_slot = False
        self.final_metric_delta = 0
        self.mutate_batch_state = False
        self.context_selections = []

    def crafting_options(self, slot):
        assert slot == SLOT
        assert "+40 to maximum Life" not in self.items[slot]
        return deepcopy(self.options)

    def add_item(self, raw, slot):
        assert slot not in self.items, "every staged candidate must clear old Rune inheritance"
        self.add_count += 1
        if self.add_count == self.fail_add_at:
            return {"ok": False}
        if self.add_count == 3 and self.corrupt_final_item:
            raw = raw.replace("+100 to maximum Life", "+999 to maximum Life")
        result = super().add_item(raw, slot)
        if self.add_count == 3:
            if self.drop_final_slot:
                self.items.pop("Helmet", None)
            if self.fail_final_restore:
                self.restore_fails = True
        return result

    def load_build_xml(self, xml, **kwargs):
        if self.add_count >= 3 and self.silent_final_restore:
            return {"ok": True}
        return super().load_build_xml(xml, **kwargs)

    def inspect_item_replacement_context(self, expected_context=None):
        if (
            expected_context is not None
            and self.context_drift_at is not None
            and self.add_count >= self.context_drift_at
        ):
            return {"ok": False, "errorCode": "original_output_missing"}
        if expected_context is not None:
            assert expected_context == CONTEXT
        return {"ok": True, "calculationContext": dict(CONTEXT)}

    def call(self, command, **kwargs):
        assert command == "set_skill_group_state"
        assert kwargs == {"index": 3, "activeSkillIndex": 2, "makeMain": True}
        self.context_selections.append(kwargs)
        return {"ok": True}

    def get_stats(self, keys):
        if self.invalid_stats_at == self.add_count:
            return {"stats": {}}
        result = super().get_stats(keys)
        if self.add_count >= 3:
            result["stats"] = {
                key: value + self.final_metric_delta for key, value in result["stats"].items()
            }
        return result

    def eval_items(self, slot, items, keys, *, replacement_context=False):
        self.batch_count += 1
        assert replacement_context is True
        if self.fail_batch == self.batch_count:
            return {
                "contextVersion": "item_replacement_context_v1",
                "rolledBack": True,
                **deepcopy(self.fail_batch_result),
            }
        result = super().eval_items(slot, items, keys, replacement_context=replacement_context)
        if self.mutate_batch_state:
            self.items.pop("Helmet", None)
        return result


@pytest.fixture
def craft_fixture(monkeypatch):
    engine = CraftOracle()
    original_xml = engine.get_xml()
    recorded = []

    def optimize(observed, slot, **kwargs):
        assert observed is engine
        assert observed.get_xml() == original_xml, "bare option probe must not become the baseline"
        assert slot == SLOT
        return {"ok": True, "affixes": ["+100 to maximum Life"], "attainabilityPolicy": {}}

    def persist(receipt):
        assert engine.get_xml() == original_xml, "receipt must follow verified snapshot restoration"
        recorded.append(deepcopy(receipt))
        return {
            "status": "recorded",
            "craftReceiptRef": receipt["receiptRef"],
            "itemFingerprint": receipt["itemFingerprint"],
        }

    monkeypatch.setattr(craftopt.itemopt, "optimize_item", optimize)
    monkeypatch.setattr(craftopt.itemopt, "_generated_item_property_lines", lambda *_a, **_k: [])
    monkeypatch.setattr(craftopt.itemopt, "_generated_item_implicit_lines", lambda *_a, **_k: [])
    monkeypatch.setattr(craftopt.itemopt, "_item_attainability_reasons", lambda *_a, **_k: [])
    monkeypatch.setattr(craftopt.itemparse.db, "illegal_affixes", lambda *_a, **_k: [])
    monkeypatch.setattr(
        craftopt.hard_legality,
        "audit_build",
        lambda *_a, **_k: {"hardLegalityReady": True, "hardFailures": [], "checks": {}},
    )
    monkeypatch.setattr(
        craftopt.craft_receipts,
        "current_runtime_context",
        lambda *_a: {"dataVersion": "test", "pobCommit": "test", "passiveTreeVersion": "test"},
    )
    monkeypatch.setattr(craftopt.craft_receipts, "persist_receipt", persist)
    return engine, original_xml, recorded


def run_craft(engine, **kwargs):
    return craftopt.craft_item(engine, SLOT, metric="TotalEHP", rune_sockets=1, **kwargs)


def assert_rejected(result, engine, original_xml, recorded, code):
    assert result["ok"] is False, result
    assert result["errorCode"] == code, result
    assert "item" not in result
    assert "craftReceiptRef" not in result
    assert not recorded
    assert engine.get_xml() == original_xml
    assert result["rolledBack"] is True
    assert result["recoveryRequired"] is False


def test_craft_uses_original_baseline_and_persists_only_after_verified_restoration(craft_fixture):
    engine, original_xml, recorded = craft_fixture
    result = run_craft(engine)

    assert result["ok"], result
    assert result["metricBefore"] == 140
    assert result["metricBare"] == 200
    assert result["metricCrafted"] == result["metricAfter"] == 225
    assert result["comparison"] == {
        "baseline": "current_equipped_item",
        "baselineStatus": "measured",
        "comparisonAvailable": True,
        "sameContext": True,
        "baselineScore": 140,
        "candidateScore": 225,
        "netGain": 85,
        "positiveGainProven": True,
    }
    assert result["calculationContext"] == CONTEXT
    assert result["roundTripLegalityCheck"]["provenanceStatus"] == "verified"
    assert result["stateHash"] == build_state_hash(original_xml)
    assert engine.get_xml() == original_xml
    assert len(recorded) == 1
    assert len(engine.context_selections) == 2


def test_weighted_metrics_distinguish_current_item_from_plain_rare(craft_fixture):
    engine, _, _ = craft_fixture
    result = run_craft(engine, goals={"TotalEHP": 1.0})
    assert result["ok"], result
    assert result["metricsBefore"] == {"TotalEHP": 140}
    assert result["metricsBare"] == {"TotalEHP": 200}
    assert result["metricsAfter"] == {"TotalEHP": 225}


def test_crafted_candidate_is_not_labelled_upgrade_when_original_item_is_better(craft_fixture):
    engine, _, _ = craft_fixture
    engine.gains["+40 to maximum Life"] = 1000
    result = run_craft(engine)
    assert result["ok"], result
    assert result["metricBefore"] == 1100
    assert result["metricAfter"] == 225
    assert result["comparison"]["positiveGainProven"] is False
    assert result["comparison"]["netGain"] == -875


@pytest.mark.parametrize("phase", [1, 2, 3, 4])
@pytest.mark.parametrize(
    ("response", "code"),
    [
        ({"ok": False}, "item_candidate_evaluation_failed"),
        ({"results": []}, "item_measurement_count_mismatch"),
        ({"results": [False]}, "item_measurement_incomplete"),
        ({"results": [{}]}, "item_measurement_incomplete"),
        ({"results": [{"TotalEHP": float("nan")}]}, "item_measurement_incomplete"),
    ],
)
def test_rune_and_corruption_failures_never_become_no_gain(phase, response, code, craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.fail_batch = phase
    engine.fail_batch_result = response
    assert_rejected(run_craft(engine), engine, original_xml, recorded, code)


@pytest.mark.parametrize("phase", [1, 2, 3])
def test_every_temporary_write_checks_explicit_add_success(phase, craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.fail_add_at = phase
    assert_rejected(
        run_craft(engine), engine, original_xml, recorded, "item_candidate_equip_failed"
    )


@pytest.mark.parametrize("phase", [2, 3])
def test_original_exact_output_cannot_change_for_rare_or_final_item(phase, craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.context_drift_at = phase
    assert_rejected(
        run_craft(engine), engine, original_xml, recorded, "item_calculation_context_mismatch"
    )


@pytest.mark.parametrize("phase", [0, 2, 3])
def test_current_rare_and_final_stats_all_require_complete_finite_keys(phase, craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.invalid_stats_at = phase
    assert_rejected(
        run_craft(engine), engine, original_xml, recorded, "item_measurement_incomplete"
    )


def test_final_slot_readback_cannot_substitute_different_item(craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.corrupt_final_item = True
    assert_rejected(
        run_craft(engine), engine, original_xml, recorded, "item_candidate_readback_mismatch"
    )


def test_final_character_cannot_silently_lose_another_equipped_slot(craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.drop_final_slot = True
    result = run_craft(engine)
    assert_rejected(result, engine, original_xml, recorded, "whole_build_legality_check_failed")
    assert result["missingEquippedSlots"] == ["Helmet"]


def test_final_full_item_metrics_must_reproduce_the_selected_measurement(craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.final_metric_delta = 9
    assert_rejected(
        run_craft(engine), engine, original_xml, recorded, "item_candidate_measurement_mismatch"
    )


def test_probe_cannot_change_character_state(craft_fixture):
    engine, original_xml, recorded = craft_fixture
    engine.mutate_batch_state = True
    assert_rejected(
        run_craft(engine), engine, original_xml, recorded, "item_candidate_state_changed"
    )


@pytest.mark.parametrize("mode", ["exception", "false_success"])
def test_failed_restore_never_persists_or_authorizes_item(mode, craft_fixture):
    engine, _, recorded = craft_fixture
    engine.fail_final_restore = mode == "exception"
    engine.silent_final_restore = mode == "false_success"
    result = run_craft(engine)
    assert result["ok"] is False
    assert result["errorCode"] == "item_search_restore_failed"
    assert result["rolledBack"] is False
    assert result["recoveryRequired"] is True
    assert "item" not in result
    assert "craftReceiptRef" not in result
    assert not recorded
    assert run_craft(engine)["errorCode"] == "build_state_recovery_required"


def test_receipt_write_failure_preserves_restore_fields_without_item(craft_fixture, monkeypatch):
    engine, original_xml, recorded = craft_fixture
    monkeypatch.setattr(
        craftopt.craft_receipts, "persist_receipt", lambda *_a: {"status": "failed"}
    )
    assert_rejected(run_craft(engine), engine, original_xml, recorded, "craft_receipt_write_failed")


def test_final_canonical_source_audit_is_required(craft_fixture, monkeypatch):
    engine, original_xml, recorded = craft_fixture
    actual_audit = craftopt.item_legality.audit_item

    def reject_roundtrip(*args, **kwargs):
        if engine.add_count >= 3:
            return {"ok": False, "issues": ["fixture_source_mismatch"]}
        return actual_audit(*args, **kwargs)

    monkeypatch.setattr(craftopt.item_legality, "audit_item", reject_roundtrip)
    assert_rejected(
        run_craft(engine),
        engine,
        original_xml,
        recorded,
        "generated_item_roundtrip_legality_check_failed",
    )
