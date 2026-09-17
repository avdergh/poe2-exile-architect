"""Search reuse preserves identities, legal choices, and cooperative stop restoration."""

from collections import Counter
from copy import deepcopy
import pytest

from server.compute import craftopt, socket_limits
from server.compute.state import build_state_hash
from server.runtime.compute_control import ComputeControl, ComputeStopped, use_compute_control
from tests import test_craft_search_contract as craft_contract
from tests import test_socket_measurement_contract as socket_contract

SocketEngine = socket_contract.SocketEngine
run_craft = craft_contract.run_craft


@pytest.fixture
def craft_fixture(monkeypatch):
    return craft_contract.craft_fixture.__wrapped__(monkeypatch)


@pytest.fixture
def safe_audits(monkeypatch):
    return socket_contract.safe_audits.__wrapped__(monkeypatch)


def test_single_rune_pre_rank_first_socket_and_runed_baseline_share_measurement(craft_fixture):
    engine, xml, _ = craft_fixture
    original = engine.eval_items
    texts = []

    def measured(slot, items, keys, **kwargs):
        texts.extend(items)
        return original(slot, items, keys, **kwargs)

    engine.eval_items = measured
    result = run_craft(engine)
    assert result["ok"] and result["metricAfter"] == 225
    assert (
        len(texts) == 2
    )  # Single rune and corruption; final full-item readback stays independent.
    assert max(Counter(texts).values()) == 1
    assert engine.get_xml() == xml


@pytest.mark.parametrize("names", [("Rune A", "Rune B"), ("Rune B", "Rune A")])
def test_equal_gain_runes_keep_distinct_identity_and_stable_input_order(names, craft_fixture):
    engine, _, _ = craft_fixture
    engine.options["runes"] = [{"name": name, "mods": ["+20 to Armour"]} for name in names]
    seen = []
    original = engine.eval_items

    def measured(slot, items, keys, **kwargs):
        seen.extend(items)
        return original(slot, items, keys, **kwargs)

    engine.eval_items = measured
    result = run_craft(engine, use_corruption=False)
    assert result["ok"]
    assert len(seen) == 2
    assert f"Rune: {names[0]}" in result["item"]
    assert f"Rune: {names[1]}" not in result["item"]


def test_measurement_cache_never_crosses_operations(craft_fixture):
    engine, _, _ = craft_fixture
    first = run_craft(engine)
    engine.gains["{rune}+20 to Armour"] = 30
    second = run_craft(engine)
    assert first["metricAfter"] == 225
    assert second["metricAfter"] == 235
    assert engine.batch_count == 4


def test_craft_resolves_fixed_base_data_once_per_operation(monkeypatch, craft_fixture):
    engine, before, _ = craft_fixture
    properties = []
    implicits = []

    def property_lines(base, **kwargs):
        properties.append((base, kwargs))
        return []

    def implicit_lines(base, **kwargs):
        implicits.append((base, kwargs))
        return []

    monkeypatch.setattr(craftopt.itemopt, "_generated_item_property_lines", property_lines)
    monkeypatch.setattr(craftopt.itemopt, "_generated_item_implicit_lines", implicit_lines)
    result = run_craft(engine, rune_sockets=2)
    assert result["ok"] and result["metricAfter"] == 245
    assert len(properties) == len(implicits) == 1
    assert implicits[0][1]["reference_raw"] in before


@pytest.mark.parametrize("reason", ["cancelled", "budget_exceeded"])
def test_stopping_socket_measurement_restores_without_receipt(reason, monkeypatch, safe_audits):
    engine = SocketEngine()
    before = engine.get_xml()
    control = ComputeControl(30)
    original = craftopt.item_search.evaluate_items

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        if reason == "cancelled":
            control.cancel()
        else:
            control.deadline = 0
        return result

    monkeypatch.setattr(craftopt.item_search, "evaluate_items", measured)
    with use_compute_control(control), pytest.raises(ComputeStopped) as caught:
        craftopt.optimize_item_sockets(
            engine, slot="Body Armour", goals={"TotalEHP": 1}, socket_count=1
        )
    assert caught.value.reason == reason
    assert engine.get_xml() == before
    assert not getattr(engine, "_poe2_mutation_batch_recovery_required", False)
    assert not safe_audits
    assert craftopt.socket_pending_slots_for_state(engine, build_state_hash(before)) == []
    assert not control.publication_started


@pytest.mark.parametrize("reason", ["cancelled", "budget_exceeded"])
def test_batch_stop_keeps_completed_child_only_and_same_control(reason, monkeypatch, safe_audits):
    engine = SocketEngine()
    before = engine.get_xml()
    control = ComputeControl(30)
    original = craftopt._record_socket_result

    def publish(*args, **kwargs):
        result = original(*args, **kwargs)
        assert not control.publication_started
        if reason == "cancelled":
            control.cancel()
        else:
            control.deadline = 0
        return result

    monkeypatch.setattr(craftopt, "_record_socket_result", publish)
    with use_compute_control(control), pytest.raises(ComputeStopped) as caught:
        craftopt.plan_item_sockets_batch(
            engine, slot_socket_counts={"Body Armour": 1, "Helmet": 1}, goals={"TotalEHP": 1}
        )
    partial = caught.value.partial_result
    assert caught.value.reason == reason
    assert partial["partial"] and not partial["batchComplete"]
    assert partial["completedSlots"] == ["Body Armour"]
    assert len(partial["results"]) == len(safe_audits) == 1
    assert engine.get_xml() == before
    assert not control.publication_started


def test_craft_stop_during_ranking_never_publishes_cached_candidate(craft_fixture):
    engine, before, receipts = craft_fixture
    control = ComputeControl(30)
    original = engine.eval_items

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        control.cancel()
        return result

    engine.eval_items = measured
    with use_compute_control(control), pytest.raises(ComputeStopped):
        run_craft(engine)
    assert engine.get_xml() == before
    assert not receipts
    assert not control.publication_started


def test_cancel_with_restore_failure_has_recovery_priority(monkeypatch, safe_audits):
    engine = SocketEngine()
    control = ComputeControl(30)
    original = craftopt.item_search.evaluate_items

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.raw += "\n+1 to maximum Life"
        engine.restore_fails = True
        control.cancel()
        return result

    monkeypatch.setattr(craftopt.item_search, "evaluate_items", measured)
    with use_compute_control(control):
        result = craftopt.optimize_item_sockets(
            engine, slot="Body Armour", goals={"TotalEHP": 1}, socket_count=1
        )
    assert result["recoveryRequired"] and not result["rolledBack"]
    assert result["errorCode"] == "socket_probe_restore_failed"
    assert not safe_audits


def test_prepared_quota_ledger_resolves_each_receipt_once_and_copies_constraints(monkeypatch):
    xml = (
        '<PathOfBuilding><Items activeItemSet="1"><Item id="1">Rune item</Item>'
        '<ItemSet id="1"><Slot name="Helmet" itemId="1"/></ItemSet></Items></PathOfBuilding>'
    )
    calls = []
    source = {"name": "Reserved", "constraints": [{"group": "shared", "limit": 1}]}
    monkeypatch.setattr(
        socket_limits.itemparse, "semantic_item_structure", lambda _: {"runeNames": ["Reserved"]}
    )

    def receipt(*args, **kwargs):
        calls.append(1)
        return {"status": "verified", "receipt": {"sources": {"runes": [source]}}}

    monkeypatch.setattr(socket_limits.craft_receipts, "resolve_receipt", receipt)
    ledger = socket_limits.prepare(xml)
    source["constraints"][0]["limit"] = 100
    for _ in range(20):
        result = ledger.audit(
            replacements={"Body Armour": [{"constraints": [{"group": "shared", "limit": 2}]}]}
        )
        assert not result["ok"] and result["violations"][0]["limit"] == 1
    assert len(calls) == 1


def test_socket_restore_rejects_calcs_drift_even_with_same_semantic_hash(monkeypatch, safe_audits):
    engine = SocketEngine()
    engine.info = {"runtimeContract": 15}
    engine.selection = {"main": {"group": 1}, "calcs": {"group": 1}}
    engine.call = lambda command: deepcopy(engine.selection)
    original = craftopt.item_search.evaluate_items
    before = build_state_hash(engine.get_xml())

    def measured(*args, **kwargs):
        result = original(*args, **kwargs)
        engine.selection["calcs"]["group"] = 2
        return result

    monkeypatch.setattr(craftopt.item_search, "evaluate_items", measured)
    result = craftopt.optimize_item_sockets(
        engine, slot="Body Armour", goals={"TotalEHP": 1}, socket_count=1
    )
    assert build_state_hash(engine.get_xml()) == before
    assert result["errorCode"] == "socket_probe_restore_failed"
    assert result["recoveryRequired"]
    assert not safe_audits


def test_socket_source_failure_keeps_bounded_input_diff(monkeypatch, safe_audits):
    engine = SocketEngine()
    before = engine.get_xml()
    failure = craftopt.socket_probe.SocketProbeInputError(
        '<PathOfBuilding2><Build level="90"/></PathOfBuilding2>',
        '<PathOfBuilding2><Build level="91"/></PathOfBuilding2>',
    )
    monkeypatch.setattr(craftopt.socket_probe, "has_source_groups", lambda _: True)

    def load(*args):
        raise failure

    monkeypatch.setattr(craftopt.socket_probe, "load_candidate", load)
    result = craftopt.optimize_item_sockets(
        engine, slot="Body Armour", goals={"TotalEHP": 1}, socket_count=1
    )
    assert result["errorCode"] == "socket_probe_non_item_inputs_changed"
    assert result["inputDiff"] == failure.details["inputDiff"]
    assert result["rolledBack"] and engine.get_xml() == before


def test_prepared_ledger_preserves_replacement_of_bad_target_quota(monkeypatch):
    xml = (
        '<PathOfBuilding><Items activeItemSet="1"><Item id="1">Rune item</Item>'
        '<ItemSet id="1"><Slot name="Helmet" itemId="1"/></ItemSet></Items></PathOfBuilding>'
    )
    monkeypatch.setattr(
        socket_limits.itemparse, "semantic_item_structure", lambda _: {"runeNames": ["Bad"]}
    )
    monkeypatch.setattr(
        socket_limits.craft_receipts,
        "resolve_receipt",
        lambda *a, **k: {
            "status": "verified",
            "receipt": {"sources": {"runes": [{"constraints": [{"group": "bad", "limit": 0}]}]}},
        },
    )
    ledger = socket_limits.prepare(xml)
    assert ledger.audit(replacements={"Helmet": []})["ok"]
    with pytest.raises(ValueError, match="invalid_socket_limit"):
        ledger.audit(replacements={"Body Armour": []})
