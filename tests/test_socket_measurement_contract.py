"""Socket decisions require complete PoB measurements and verified state restoration."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest

from server.compute import craftopt
from server.compute.state import build_state_hash
from server.generation import validation_checkpoint


RAW = "Rarity: Rare\nSocket Target\nSacramental Robe\nItem Level: 82\n--------\n+50 to maximum Life"


class SocketEngine:
    info = {}

    def __init__(self, *, responses=None, raw=RAW):
        self.raw = raw
        self.responses = list(responses or [])
        self.options = [{"name": "Iron Rune", "mods": ["+20 to Armour"]}]
        self.stats_calls = 0
        self.eval_calls = 0
        self.overrides = {}
        self.resistances = {"fire": 60, "cold": 60, "lightning": 60, "chaos": 30}
        self.restore_fails = False
        self.probe_mutates = False
        self.equip_fails = False

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        root = ET.Element("PathOfBuilding2")
        ET.SubElement(root, "Build", level="90", className="Sorceress")
        items = ET.SubElement(root, "Items", activeItemSet="1")
        ET.SubElement(items, "Item", id="1").text = self.raw
        item_set = ET.SubElement(items, "ItemSet", id="1")
        ET.SubElement(item_set, "Slot", name="Body Armour", itemId="1")
        return ET.tostring(root, encoding="unicode")

    def load_build_xml(self, xml):
        if self.restore_fails:
            return {"ok": False}
        self.raw = ET.fromstring(xml).find("Items/Item").text
        return {"ok": True}

    def get_build(self):
        return {"level": 90, "gear": {"Body Armour": {"base": "Sacramental Robe"}}}

    def add_item(self, raw, slot=None):
        if self.equip_fails:
            return {"ok": False}
        self.raw = raw
        return {"ok": True}

    def unequip_item(self, slot):
        self.raw = ""
        return {"ok": True}

    def crafting_options(self, slot):
        return {"ok": True, "runes": self.options}

    def inspect_item_replacement_context(self, expected_context=None):
        return {"ok": True, "contextStatus": "no_active_output"}

    def get_defenses(self):
        return {"resistances": self.resistances}

    def get_stats(self, keys):
        self.stats_calls += 1
        return deepcopy(self.overrides.get(self.stats_calls, {"stats": self.measure(self.raw)}))

    def measure(self, raw):
        return {"TotalEHP": 100 + 20 * raw.count("Rune: Iron Rune")}

    def eval_items(self, slot, texts, keys, *, replacement_context=False):
        assert replacement_context is True
        self.eval_calls += 1
        if self.probe_mutates:
            self.raw = texts[0]
        if self.responses:
            result = self.responses.pop(0)
        else:
            result = {"results": [self.measure(text) for text in texts]}
        return (
            {"contextVersion": "item_replacement_context_v1", "rolledBack": True, **result}
            if isinstance(result, dict)
            else result
        )


@pytest.fixture
def safe_audits(monkeypatch):
    writes = []
    monkeypatch.setattr(
        craftopt.hard_legality, "augment_build_with_snapshot_gear", lambda build, *a, **kw: build
    )
    monkeypatch.setattr(
        craftopt.hard_legality,
        "audit_build",
        lambda build: {"hardLegalityReady": True, "hardFailures": []},
    )
    monkeypatch.setattr(
        craftopt.hard_legality,
        "compare_audits_for_regression",
        lambda *a: {"regressed": False, "reasons": []},
    )
    monkeypatch.setattr(craftopt.item_legality, "audit_item", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr(
        craftopt.craft_receipts,
        "prepare_receipt",
        lambda *a, **kw: {"acceptedItemFingerprints": ["sha256:test"]},
    )
    monkeypatch.setattr(
        craftopt.craft_receipts,
        "persist_receipt",
        lambda value: (
            writes.append(value)
            or {
                "status": "recorded",
                "craftReceiptRef": "craft-legality:test",
                "itemFingerprint": "sha256:test",
            }
        ),
    )
    return writes


def plan(engine, count=1):
    return craftopt.plan_item_sockets_batch(
        engine, slot_socket_counts={"Body Armour": count}, goals={"TotalEHP": 1}
    )


def direct_plan(engine, count=1):
    return craftopt.optimize_item_sockets(
        engine,
        slot="Body Armour",
        socket_count=count,
        goals={"TotalEHP": 1},
    )


def socket_check(engine, state_hash, *, full=False):
    return validation_checkpoint._create_quality_checklist(
        engine=engine,
        xml=engine.get_xml(),
        state_hash=state_hash,
        build={"level": 90, "gear": {}},
        stats={},
        completeness_result={"runes": {"decisionRequiredSlots": [] if full else ["Body Armour"]}},
        preflight_result={"skillGroups": []},
    )["itemSockets"]


@pytest.mark.parametrize(
    "response",
    [
        {"results": [False]},
        {"results": []},
        {"results": [{"TotalEHP": 100}, {"TotalEHP": 120}]},
        {},
        False,
        {"results": None},
        {"results": [None]},
        {"results": [[]]},
        {"results": [{}]},
        {"results": [{"TotalEHP": None}]},
        {"results": [{"TotalEHP": True}]},
        {"results": [{"TotalEHP": "120"}]},
        {"results": [{"TotalEHP": float("nan")}]},
        {"results": [{"TotalEHP": float("inf")}]},
        {"results": [{"TotalEHP": -float("inf")}]},
    ],
)
def test_incomplete_socket_probe_never_becomes_verified_no_gain(response, safe_audits):
    engine = SocketEngine(responses=[response])
    before = engine.get_xml()
    result = plan(engine)
    assert result["ok"] is False
    assert result["decisions"] == {"Body Armour": "measurement_error"}
    assert socket_check(engine, result["stateHash"])["status"] == "failed"
    assert engine.get_xml() == before
    assert safe_audits == []


def test_one_success_does_not_hide_an_unmeasured_candidate(safe_audits):
    engine = SocketEngine(responses=[{"results": [{"TotalEHP": 120}, False]}])
    engine.options.append({"name": "Other Rune", "mods": ["+10 to Armour"]})
    assert plan(engine)["decisions"] == {"Body Armour": "measurement_error"}
    assert safe_audits == []


def test_second_socket_failure_does_not_authorize_partial_no_gain(safe_audits):
    engine = SocketEngine(responses=[{"results": [{"TotalEHP": 120}]}, {"results": [False]}])
    result = plan(engine, 2)
    assert result["ok"] is False
    assert result["decisions"] == {"Body Armour": "measurement_error"}
    assert safe_audits == []


@pytest.mark.parametrize(
    "stats,status",
    [
        ({"stats": {}}, "capability_gap"),
        ({"stats": {"TotalEHP": None}}, "capability_gap"),
        ({"stats": {"TotalEHP": float("nan")}}, "measurement_error"),
        (False, "measurement_error"),
    ],
)
def test_baseline_capability_gap_remains_unverified(stats, status, safe_audits):
    engine = SocketEngine()
    engine.overrides[1] = stats
    result = plan(engine)
    assert result["decisions"] == {"Body Armour": status}
    assert socket_check(engine, result["stateHash"])["status"] == "failed"
    assert engine.eval_calls == 0


@pytest.mark.parametrize("value", [None, True, "60", float("nan")])
def test_missing_or_invalid_resistance_constraints_block_pruning(value, safe_audits):
    engine = SocketEngine()
    engine.resistances["fire"] = value
    assert plan(engine)["decisions"] == {"Body Armour": "measurement_error"}
    assert engine.eval_calls == 0


def test_complete_measured_no_gain_can_authorize_checkpoint(safe_audits):
    engine = SocketEngine(responses=[{"results": [{"TotalEHP": 100}]}])
    result = plan(engine)
    assert result["ok"] is True
    assert result["decisions"] == {"Body Armour": "no_positive"}
    assert socket_check(engine, result["stateHash"])["status"] == "passed"
    assert safe_audits == []


def test_positive_plan_is_unapplied_until_equipped(safe_audits):
    engine = SocketEngine()
    before = engine.get_xml()
    result = plan(engine)
    assert result["ok"] is True
    assert result["decisions"] == {"Body Armour": "socketed"}
    assert socket_check(engine, result["stateHash"])["status"] == "failed"
    assert engine.get_xml() == before
    assert len(safe_audits) == 1


def test_partial_plan_must_be_equipped_before_no_gain_carry(safe_audits):
    engine = SocketEngine(
        responses=[{"results": [{"TotalEHP": 120}]}, {"results": [{"TotalEHP": 120}]}]
    )
    result = plan(engine, 2)
    assert result["decisions"] == {"Body Armour": "partial_socketed"}
    assert socket_check(engine, result["stateHash"])["status"] == "failed"
    engine.add_item(result["results"][0]["item"])
    after = build_state_hash(engine.get_xml())
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=result["stateHash"],
            output_state_hash=after,
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        == "partial_no_positive"
    )
    assert socket_check(engine, after)["status"] == "passed"
    assert craftopt.socket_batch_decisions_for_state(engine, "different-config-state") == {}
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash="different-config-state",
            output_state_hash="later-state",
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        is None
    )


def test_existing_full_socket_item_is_the_comparison_baseline(safe_audits):
    raw = craftopt._augment_item_with_runes(RAW, [("Iron Rune", ["+20 to Armour"])])
    engine = SocketEngine(raw=raw)
    result = plan(engine)
    assert result["decisions"] == {"Body Armour": "no_positive"}
    assert engine.raw == raw
    assert safe_audits == []


def test_explicit_failed_probe_blocks_even_when_item_has_all_sockets_filled(safe_audits):
    raw = craftopt._augment_item_with_runes(RAW, [("Iron Rune", ["+20 to Armour"])])
    engine = SocketEngine(raw=raw, responses=[{"results": [False]}])
    result = plan(engine)
    assert socket_check(engine, result["stateHash"], full=True)["status"] == "failed"


def test_eval_items_mutating_activity_is_rejected_and_restored(safe_audits):
    engine = SocketEngine()
    engine.probe_mutates = True
    before = engine.get_xml()
    result = plan(engine)
    assert result["decisions"] == {"Body Armour": "measurement_error"}
    assert result["results"][0]["errorCode"] == "item_candidate_state_changed"
    assert engine.get_xml() == before


def test_equip_failure_is_not_a_zero_gain_probe(safe_audits):
    engine = SocketEngine()
    engine.equip_fails = True
    assert plan(engine)["decisions"] == {"Body Armour": "measurement_error"}


def test_restore_failure_stops_batch_and_does_not_persist_receipt(safe_audits):
    engine = SocketEngine()
    engine.restore_fails = True
    result = plan(engine)
    assert result["ok"] is False
    assert result["recoveryRequired"] is True
    assert result["decisions"] == {}
    assert safe_audits == []
    assert (
        craftopt.socket_batch_decisions_for_state(engine, build_state_hash(engine.get_xml())) == {}
    )


@pytest.mark.parametrize(
    "stats", [{}, {"TotalEHP": float("nan")}, {"TotalEHP": 100}, {"TotalEHP": 130}]
)
def test_positive_candidate_requires_valid_reproduced_final_metrics(stats, safe_audits):
    engine = SocketEngine()
    engine.overrides[3] = {"stats": stats}
    assert plan(engine)["decisions"] == {"Body Armour": "measurement_error"}
    assert safe_audits == []


def test_legacy_unversioned_socket_cache_cannot_authorize_checkpoint(safe_audits):
    engine = SocketEngine()
    state_hash = build_state_hash(engine.get_xml())
    craftopt._SOCKET_BATCH_DECISIONS[engine] = {state_hash: {"Body Armour": "no_positive"}}
    assert craftopt.socket_batch_decisions_for_state(engine, state_hash) == {}
    assert socket_check(engine, state_hash)["status"] == "failed"


def test_existing_socket_capacity_is_preserved(safe_audits):
    raw = craftopt._augment_item_with_runes(RAW, [], socket_capacity=2)
    engine = SocketEngine(raw=raw)
    result = plan(engine, 1)
    assert result["ok"] is True
    assert result["results"][0]["socketCapacity"] == 2
    assert "Sockets: S S" in result["results"][0]["item"]


def test_final_item_probe_cannot_remove_an_equipped_slot(monkeypatch, safe_audits):
    engine = SocketEngine()
    builds = [
        {"level": 90, "gear": {"Body Armour": {}, "Boots": {}}},
        {"level": 90, "gear": {"Body Armour": {}}},
    ]
    monkeypatch.setattr(engine, "get_build", lambda: builds.pop(0))
    result = plan(engine)
    assert result["ok"] is False
    assert result["results"][0]["missingEquippedSlots"] == ["Boots"]
    assert safe_audits == []


def test_final_item_probe_reuses_shared_whole_build_legality(monkeypatch, safe_audits):
    engine = SocketEngine()
    monkeypatch.setattr(
        craftopt.hard_legality,
        "compare_audits_for_regression",
        lambda *a: {
            "regressed": True,
            "reasons": [{"code": "attribute_requirement_unmet"}],
        },
    )
    result = plan(engine)
    assert result["ok"] is False
    assert result["results"][0]["errorCode"] == "whole_build_legality_check_failed"
    assert safe_audits == []


def test_legacy_unversioned_item_carry_cannot_authorize_checkpoint(safe_audits):
    engine = SocketEngine()
    state_hash = build_state_hash(engine.get_xml())
    craftopt._SOCKET_ITEM_DECISIONS[engine] = {
        "Body Armour": {
            "sha256:test": {
                "decision": "partial_no_positive",
                "sourceStateHash": state_hash,
            }
        }
    }
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=state_hash,
            output_state_hash="after",
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        is None
    )


@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"measurementComplete": False, "measurementStatus": "no_positive"},
        {"measurementComplete": True, "measurementStatus": "measurement_error"},
    ],
)
def test_version_alone_does_not_authorize_incomplete_socket_evidence(evidence, safe_audits):
    engine = SocketEngine()
    state_hash = build_state_hash(engine.get_xml())
    craftopt._SOCKET_BATCH_DECISIONS[engine] = {
        state_hash: {
            "reviewPolicyVersion": "item_socket_review_v2",
            "decisions": {"Body Armour": "no_positive"},
            "measurements": {"Body Armour": evidence},
        }
    }
    assert craftopt.socket_batch_decisions_for_state(engine, state_hash) == {}
    assert socket_check(engine, state_hash)["status"] == "failed"


@pytest.mark.parametrize("failure", ["rejected", "exception", "malformed", "incomplete"])
def test_receipt_persistence_failure_preserves_restore_evidence_without_equip_authority(
    failure,
    monkeypatch,
    safe_audits,
):
    engine = SocketEngine()
    original = engine.get_xml()
    state_hash = build_state_hash(original)

    def fail_persistence(_prepared):
        if failure == "exception":
            raise OSError("fixture write failed")
        if failure == "malformed":
            return False
        if failure == "incomplete":
            return {"status": "recorded"}
        return {"status": "rejected", "errorCode": "fixture_receipt_rejected"}

    monkeypatch.setattr(craftopt.craft_receipts, "persist_receipt", fail_persistence)
    result = plan(engine)
    assert result["ok"] is False
    assert result["decisions"] == {"Body Armour": "failed"}
    failed = result["results"][0]
    assert failed["stateHash"] == state_hash
    assert failed["rolledBack"] is True
    assert failed["recoveryRequired"] is False
    assert failed["reviewPolicyVersion"] == "item_socket_review_v2"
    assert failed["errorCode"] == (
        "fixture_receipt_rejected" if failure == "rejected" else "craft_receipt_write_failed"
    )
    assert (
        not {"item", "craftReceiptRef", "itemFingerprint", "acceptedItemFingerprints"}
        & failed.keys()
    )
    assert socket_check(engine, state_hash)["status"] == "failed"
    assert engine.get_xml() == original
    assert not craftopt._SOCKET_ITEM_DECISIONS.get(engine)


def test_direct_single_slot_no_gain_publishes_current_checkpoint_evidence(safe_audits):
    engine = SocketEngine(responses=[{"results": [{"TotalEHP": 100}]}])
    result = direct_plan(engine)
    assert result["ok"] is True
    assert result["decision"] == "no_positive"
    assert (
        craftopt.socket_decision_freshness(engine, result["stateHash"], "Body Armour") == "current"
    )
    assert socket_check(engine, result["stateHash"])["status"] == "passed"


def test_direct_partial_plan_publishes_pending_and_revokes_it_after_failed_reassessment(
    safe_audits,
):
    engine = SocketEngine(
        responses=[{"results": [{"TotalEHP": 120}]}, {"results": [{"TotalEHP": 120}]}]
    )
    before = engine.get_xml()
    result = direct_plan(engine, 2)
    assert result["decision"] == "partial_socketed"
    engine.add_item(result["item"])
    after = build_state_hash(engine.get_xml())
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=result["stateHash"],
            output_state_hash=after,
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        == "partial_no_positive"
    )
    engine.load_build_xml(before)
    engine.responses = [{"results": [False]}]
    failed = direct_plan(engine, 2)
    assert failed["decision"] == "measurement_error"
    assert not craftopt._SOCKET_ITEM_DECISIONS.get(engine)
    assert craftopt.socket_batch_decisions_for_state(engine, after) == {}
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=result["stateHash"],
            output_state_hash=after,
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        is None
    )


@pytest.mark.parametrize("failure", ["persist", "restore"])
def test_failed_direct_reassessment_revokes_existing_pending_receipt(
    failure, monkeypatch, safe_audits
):
    engine = SocketEngine()
    first = direct_plan(engine)
    assert first["ok"] is True
    if failure == "persist":
        monkeypatch.setattr(
            craftopt.craft_receipts, "persist_receipt", lambda _: {"status": "rejected"}
        )
    else:
        engine.restore_fails = True
    second = direct_plan(engine)
    assert second["ok"] is False
    assert not craftopt._SOCKET_ITEM_DECISIONS.get(engine)
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=first["stateHash"],
            output_state_hash="after",
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        is None
    )


def test_batch_merges_other_slot_failure_and_records_each_probe_once(monkeypatch, safe_audits):
    engine = SocketEngine()
    state_hash = build_state_hash(engine.get_xml())
    craftopt._record_socket_result(
        engine,
        state_hash,
        "Boots",
        {
            "ok": False,
            "measurementStatus": "measurement_error",
            "reviewPolicyVersion": "item_socket_review_v2",
        },
    )
    original = craftopt._record_socket_result
    calls = []

    def record(*args):
        calls.append(args[2])
        return original(*args)

    monkeypatch.setattr(craftopt, "_record_socket_result", record)
    result = plan(engine)
    assert result["ok"] is True
    assert calls == ["Body Armour"]
    assert craftopt.socket_batch_decisions_for_state(engine, state_hash) == {
        "Boots": "measurement_error",
        "Body Armour": "socketed",
    }


def test_socket_probe_replaces_without_empty_intermediate_state(monkeypatch, safe_audits):
    engine = SocketEngine()

    def unexpected_clear(_):
        pytest.fail("a complete item replacement must not clear dependent equipment")

    monkeypatch.setattr(engine, "unequip_item", unexpected_clear)
    result = direct_plan(engine)
    assert result["ok"] is True


def test_socket_probe_rejects_semantically_different_readback(monkeypatch, safe_audits):
    engine = SocketEngine()
    original = engine.add_item
    monkeypatch.setattr(
        engine,
        "add_item",
        lambda raw, slot: original(raw.replace("+50 to maximum Life", "+40 to maximum Life"), slot),
    )
    result = direct_plan(engine)
    assert result["errorCode"] == "socket_probe_readback_mismatch"
    assert result["decision"] == "measurement_error"


def test_canonical_rune_tags_are_removed_without_losing_other_item_effects():
    raw = (
        "Rarity: Rare\nSocket Target\nSacramental Robe\nItem Level: 82\n"
        "Sockets: S S\nRune: Iron Rune\nRune: Iron Rune\nImplicits: 4\n"
        "{enchant}{rune}32% increased Armour, Evasion and Energy Shield\n"
        "{enchant}{rune}Bonded: +40 to maximum Life\n"
        "{enchant}20% increased Spell Damage\n10% increased Rarity of Items found\n"
        "+50 to maximum Life"
    )
    bare = craftopt._without_socketed_runes(raw)
    assert "{rune}" not in bare
    assert "Rune:" not in bare
    assert "Sockets:" not in bare
    assert "Implicits: 2" in bare
    assert "{enchant}20% increased Spell Damage" in bare
    assert "10% increased Rarity of Items found" in bare
    assert "+50 to maximum Life" in bare


@pytest.mark.parametrize("change", ["affix", "rune", "capacity", "base", "level"])
def test_canonical_rune_readback_cannot_change_other_item_identity(change):
    expected = craftopt._augment_item_with_runes(RAW, [("Iron Rune", ["+20 to Armour"])])
    actual = expected.replace("{rune}+20 to Armour", "{enchant}{rune}+20 to Armour")
    if change == "affix":
        actual = actual.replace("+50 to maximum Life", "+40 to maximum Life")
    elif change == "rune":
        actual = actual.replace("Rune: Iron Rune", "Rune: Lesser Iron Rune")
    elif change == "capacity":
        actual = actual.replace("Sockets: S", "Sockets: S S")
    elif change == "base":
        actual = actual.replace("Sacramental Robe", "Elegant Robe")
    else:
        actual = actual.replace("Item Level: 82", "Item Level: 81")
    assert craftopt._socket_item_readback_matches(expected, actual) is False


def test_rune_effect_normalization_still_requires_final_source_legality(monkeypatch, safe_audits):
    engine = SocketEngine()
    audits = [{"ok": True}, {"ok": False, "issues": ["special_source_provenance_required"]}]
    monkeypatch.setattr(craftopt.item_legality, "audit_item", lambda *a, **kw: audits.pop(0))
    result = direct_plan(engine)
    assert result["ok"] is False
    assert result["errorCode"] == "whole_build_legality_check_failed"
    assert safe_audits == []


def test_failed_reassessment_after_equip_revokes_ancestor_and_blocks_noop_re_equip(safe_audits):
    engine = SocketEngine(
        responses=[{"results": [{"TotalEHP": 120}]}, {"results": [{"TotalEHP": 120}]}]
    )
    planned = direct_plan(engine, 2)
    engine.add_item(planned["item"])
    equipped_hash = build_state_hash(engine.get_xml())
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=planned["stateHash"],
            output_state_hash=equipped_hash,
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        == "partial_no_positive"
    )
    engine.responses = [{"results": [False]}]
    failed = direct_plan(engine, 2)
    assert failed["stateHash"] == equipped_hash
    assert failed["decision"] == "measurement_error"
    assert not craftopt._SOCKET_ITEM_DECISIONS.get(engine)
    assert (
        craftopt.carry_socket_decision_to_equipped_state(
            engine,
            input_state_hash=equipped_hash,
            output_state_hash=equipped_hash,
            slot="Body Armour",
            item_fingerprint="sha256:test",
        )
        is None
    )
    assert socket_check(engine, equipped_hash)["status"] == "failed"


def test_re_equip_carry_preserves_another_slots_exact_output_failure(safe_audits):
    engine = SocketEngine(
        responses=[{"results": [{"TotalEHP": 120}]}, {"results": [{"TotalEHP": 120}]}]
    )
    original_xml = engine.get_xml()
    planned = direct_plan(engine, 2)
    engine.add_item(planned["item"])
    equipped_hash = build_state_hash(engine.get_xml())
    carry_args = dict(
        input_state_hash=planned["stateHash"],
        output_state_hash=equipped_hash,
        slot="Body Armour",
        item_fingerprint="sha256:test",
    )
    assert (
        craftopt.carry_socket_decision_to_equipped_state(engine, **carry_args)
        == "partial_no_positive"
    )
    craftopt._record_socket_result(
        engine,
        equipped_hash,
        "Boots",
        {
            "ok": False,
            "measurementStatus": "measurement_error",
            "reviewPolicyVersion": "item_socket_review_v2",
        },
    )
    engine.load_build_xml(original_xml)
    assert (
        craftopt.carry_socket_decision_to_equipped_state(engine, **carry_args)
        == "partial_no_positive"
    )
    assert craftopt.socket_batch_decisions_for_state(engine, equipped_hash) == {
        "Body Armour": "partial_no_positive",
        "Boots": "measurement_error",
    }
    assert socket_check(engine, equipped_hash, full=True)["status"] == "failed"


def test_socket_probe_rejects_changed_original_output_before_any_no_gain_measurement(
    monkeypatch, safe_audits
):
    engine = SocketEngine(responses=[{"results": [{"TotalEHP": 100}]}])
    context = {"groupIndex": 2, "activeSkillIndex": 1, "skillName": "Molten Shower"}
    monkeypatch.setattr(
        engine,
        "inspect_item_replacement_context",
        lambda expected_context=None: (
            {"ok": False}
            if expected_context is not None
            else {"ok": True, "calculationContext": context}
        ),
    )
    result = direct_plan(engine)
    assert result["decision"] == "measurement_error"
    assert result["errorCode"] == "item_calculation_context_mismatch"
    assert engine.eval_calls == 0
    assert safe_audits == []


@pytest.mark.parametrize(
    "response",
    [
        {"results": [{"TotalEHP": 100}], "contextVersion": None},
        {"results": [{"TotalEHP": 100}], "rolledBack": False},
        {"results": [{"TotalEHP": 100}], "failureCodes": ["item_replacement_group_config_changed"]},
    ],
)
def test_socket_batch_requires_complete_original_context_evidence(response, safe_audits):
    result = direct_plan(SocketEngine(responses=[response]))
    assert result["decision"] == "measurement_error"
    assert not result["ok"]
    assert safe_audits == []
