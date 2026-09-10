"""Jewel input, protected-socket review and atomic decision regressions."""

from contextlib import nullcontext
import xml.etree.ElementTree as ET

import pytest

from server.compute import itemopt
from server.compute.state import build_state_hash


class _JewelMarginalEngine:
    def __init__(self) -> None:
        self.allocated = False
        self.equipped = False
        self.xml = (
            '<PathOfBuilding><Build className="Mercenary" level="95"/>'
            '<Tree activeSpec="1"><Spec><Sockets /></Spec></Tree>'
            '<Items activeItemSet="1"><ItemSet id="1" /></Items></PathOfBuilding>'
        )
        self.unspent_points = 5
        self.removed: set[int] = set()
        self.mutation_count = 0

    def get_xml(self):
        return self.xml

    def transaction_lock(self):
        return nullcontext()

    def _touch(self):
        self.mutation_count += 1
        while f"mutation{self.mutation_count}=" in self.xml:
            self.mutation_count += 1
        self.xml = self.xml.replace("/>", f' mutation{self.mutation_count}="true"/>', 1)

    def list_jewel_sockets(self):
        root = ET.fromstring(self.xml)
        filled = {int(value.get("nodeId")) for value in root.findall("./Tree/Spec/Sockets/Socket")}
        return {
            "sockets": [
                {
                    "socket": socket,
                    "allocated": socket in filled,
                    "filled": socket in filled,
                }
                for socket in (101, 102, 103)
            ]
        }

    def get_passive(self, node):
        node = int(node)
        filled = {
            int(value.get("nodeId"))
            for value in ET.fromstring(self.xml).findall("./Tree/Spec/Sockets/Socket")
        }
        return {
            "found": True,
            "alloc": node in filled or (node in {201, 202} and node not in self.removed),
            "pathDist": 2,
            "pathNodeIds": [301],
        }

    def get_build(self):
        return {"unspentPoints": self.unspent_points}

    def get_stats(self, _keys):
        value = 100 - 5 * len(self.removed)
        value += 20 * len(ET.fromstring(self.xml).findall("./Tree/Spec/Sockets/Socket"))
        return {"stats": {"Life": value}}

    def list_reallocation_candidates(self, limit=12):
        assert limit is None
        return {
            "candidates": [
                {"id": 201, "name": "Small Life", "type": "Normal", "pointsFreed": 1},
                {"id": 202, "name": "Small Armour", "type": "Normal", "pointsFreed": 1},
            ]
        }

    def dealloc_passive(self, node):
        self.removed.add(int(node))
        self._touch()
        return {"ok": True, "pointsFreed": 1}

    def alloc_passive(self, _node):
        self.allocated = True
        self._touch()
        return {"ok": True, "pointsSpent": 2}

    def equip_jewel(self, _raw, socket=None):
        assert socket in {101, 102, 103}
        self.equipped = True
        root = ET.fromstring(self.xml)
        items = root.find("Items")
        item_id = str(len(items.findall("Item")) + 1)
        item = ET.SubElement(items, "Item", {"id": item_id})
        item.text = _raw
        sockets = root.find("./Tree/Spec/Sockets")
        ET.SubElement(sockets, "Socket", {"nodeId": str(socket), "itemId": item_id})
        self.xml = ET.tostring(root, encoding="unicode")
        return {"ok": True}

    def load_build_xml(self, xml, name=""):
        del name
        self.xml = xml
        socket_count = len(ET.fromstring(xml).findall("./Tree/Spec/Sockets/Socket"))
        self.allocated = socket_count > 0
        self.equipped = socket_count > 0
        self.removed.clear()
        self.mutation_count = 0
        return {"ok": True}


VALID_JEWEL = (
    "Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n"
    "Damage Penetrates 9% Cold Resistance\n18% increased maximum Energy Shield"
)
CORRECTED_JEWEL = VALID_JEWEL.replace("9% Cold", "8% Cold")


@pytest.mark.parametrize("raw,error", [
    ("nonsense", "item_is_not_jewel"),
    ("Rarity: Rare\nRing\nSapphire Ring\nItem Level: 95\n+40 to maximum Mana",
     "item_is_not_jewel"),
    (VALID_JEWEL.replace("Item Level: 95\n", ""), "jewel_item_level_missing"),
    (VALID_JEWEL + "\nCorrupted", "special_source_provenance_required"),
    (VALID_JEWEL + "\n18% increased maximum Energy Shield", "item_legality_check_failed"),
    (VALID_JEWEL.replace("Damage Penetrates 9% Cold Resistance", "9% increased Cold Penetration"),
     "candidate_jewel_unrecognized_affixes"),
])
def test_invalid_candidate_is_rejected_before_probes_or_pending_receipts(monkeypatch, raw, error):
    engine = _JewelMarginalEngine()
    original = engine.get_xml()
    state_hash = build_state_hash(original)

    def no_probe(*_args, **_kwargs):
        pytest.fail("invalid input must not probe or reload the build")

    with monkeypatch.context() as patch:
        for name in ("get_stats", "get_passive", "list_jewel_sockets", "load_build_xml"):
            patch.setattr(engine, name, no_probe)
        rejected = itemopt.evaluate_next_jewel_socket(
            engine, raw=raw, goals={"Life": 1}, protected_node_ids=[201],
        )
    assert rejected["ok"] is False
    assert rejected["errorCode"] == error
    assert rejected["stateHash"] == state_hash
    assert engine.get_xml() == original
    assert itemopt.next_jewel_decision_for_state(engine, state_hash) is None
    engine.unspent_points = 0
    corrected = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    assert corrected["status"] == "inconclusive"
    assert corrected["limitedSocketCount"] == 3


def test_unmeasured_policy_review_allows_candidate_correction_and_preserves_unknown():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0
    original = engine.get_xml()
    first = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    corrected = itemopt.evaluate_next_jewel_socket(
        engine, raw=CORRECTED_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    assert corrected["ok"] is True
    assert corrected["status"] == "inconclusive"
    assert corrected["positiveNetBenefit"] is None
    assert corrected["limitedSocketCount"] == corrected["reachableSocketCount"] == 3
    assert corrected["evaluatedSocketCount"] == corrected["inconclusiveSocketCount"] == 0
    assert corrected["replacesUnmeasuredCandidateFingerprint"] == first["candidateJewelFingerprint"]
    assert corrected["candidateJewelFingerprint"] != first["candidateJewelFingerprint"]
    assert "decisionRef" not in corrected
    assert engine.get_xml() == original
    assert itemopt.next_jewel_decision_for_state(engine, first["stateHash"]) == corrected


@pytest.mark.parametrize("goals,protected", [
    ({"Life": 2}, [201]),
    ({"Life": 1}, []),
    ({"Life": 1}, [201, 202]),
    ({"Life": 1}, None),
])
def test_candidate_correction_cannot_change_objective_or_protection(goals, protected):
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0
    first = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    rejected = itemopt.evaluate_next_jewel_socket(
        engine, raw=CORRECTED_JEWEL, goals=goals, protected_node_ids=protected,
    )
    assert rejected["errorCode"] == "jewel_socket_inconclusive_review_pending"
    assert itemopt.next_jewel_decision_for_state(engine, first["stateHash"]) == first


@pytest.mark.parametrize("measurement_error", [False, True])
def test_partial_measurement_or_probe_error_cannot_be_replaced(measurement_error):
    class PartialEngine(_JewelMarginalEngine):
        def get_passive(self, node):
            result = super().get_passive(node)
            if int(node) == 101:
                result["pathDist"] = 1
            return result

        def alloc_passive(self, node):
            result = super().alloc_passive(node)
            result["pointsSpent"] = self.get_passive(node)["pathDist"]
            return result

        def equip_jewel(self, raw, socket=None):
            if measurement_error:
                return {"ok": False}
            return super().equip_jewel(raw, socket=socket)

        def get_stats(self, keys):
            result = super().get_stats(keys)
            if self.equipped:
                result["stats"]["Life"] = 50
            return result

    engine = PartialEngine()
    engine.unspent_points = 0
    first = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    assert first["status"] == "inconclusive"
    assert first["inconclusiveSocketCount" if measurement_error else "evaluatedSocketCount"] == 1
    rejected = itemopt.evaluate_next_jewel_socket(
        engine, raw=CORRECTED_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    assert rejected["errorCode"] == "jewel_socket_inconclusive_review_pending"
    assert itemopt.next_jewel_decision_for_state(engine, first["stateHash"]) == first


def test_invalid_correction_preserves_existing_review():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0
    first = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    rejected = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL + "\nnot a real modifier", goals={"Life": 1},
        protected_node_ids=[201],
    )
    assert rejected["errorCode"] == "candidate_jewel_unrecognized_affixes"
    assert itemopt.next_jewel_decision_for_state(engine, first["stateHash"]) == first


def test_candidate_correction_does_not_replace_an_incomplete_legacy_review():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0
    first = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    legacy = {key: value for key, value in first.items() if key != "socketEvaluations"}
    itemopt._record_next_jewel_decision(engine, first["stateHash"], legacy)
    rejected = itemopt.evaluate_next_jewel_socket(
        engine, raw=CORRECTED_JEWEL, goals={"Life": 1}, protected_node_ids=[201],
    )
    assert rejected["errorCode"] == "jewel_socket_inconclusive_review_pending"
    assert itemopt.next_jewel_decision_for_state(engine, first["stateHash"]) == legacy


def test_correction_restore_failure_preserves_old_review_and_requires_recovery(monkeypatch):
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0
    first = itemopt.evaluate_next_jewel_socket(
        engine, raw=VALID_JEWEL, goals={"Life": 1}, protected_node_ids=[201, 202],
    )

    def failed_restore(*_args, **_kwargs):
        raise RuntimeError("restore unavailable")

    monkeypatch.setattr(engine, "load_build_xml", failed_restore)
    rejected = itemopt.evaluate_next_jewel_socket(
        engine, raw=CORRECTED_JEWEL, goals={"Life": 1}, protected_node_ids=[201, 202],
    )
    assert rejected["errorCode"] == "jewel_socket_probe_restore_failed"
    assert rejected["rolledBack"] is False
    assert rejected["recoveryRequired"] is True
    assert itemopt.next_jewel_decision_for_state(engine, first["stateHash"]) == first
    blocked = itemopt.evaluate_next_jewel_socket(
        engine, raw=CORRECTED_JEWEL, goals={"Life": 1}, protected_node_ids=[201, 202],
    )
    assert blocked["errorCode"] == "build_state_recovery_required"


def test_evaluate_next_jewel_socket_is_marginal_bounded_and_read_only():
    engine = _JewelMarginalEngine()
    before = engine.get_xml()

    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    assert result["ok"] is True
    assert result["socket"] == 101
    assert result["pathPointCost"] == 2
    assert result["positiveNetBenefit"] is True
    assert result["decisionRef"].startswith("jewel-decision:")
    assert result["decision"] == "apply_best_socket"
    assert result["maxRounds"] is None
    assert result["socketFrontierComplete"] is True
    assert result["evaluatedSocketCount"] == 3
    assert engine.get_xml() == before
    assert engine.allocated is False and engine.equipped is False


def test_evaluate_next_jewel_socket_checks_all_sockets_and_selects_best():
    class PositionAwareEngine(_JewelMarginalEngine):
        def get_stats(self, _keys):
            root = ET.fromstring(self.xml)
            filled = {
                int(value.get("nodeId")) for value in root.findall("./Tree/Spec/Sockets/Socket")
            }
            gains = {101: 5, 102: 35, 103: 15}
            value = 100 - 5 * len(self.removed) + sum(gains.get(node, 0) for node in filled)
            return {"stats": {"Life": value}}

    engine = PositionAwareEngine()
    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )

    assert result["socket"] == 102
    assert [entry["socket"] for entry in result["socketEvaluations"]] == [101, 102, 103]
    assert result["evaluatedSocketCount"] == 3


def test_evaluate_next_jewel_socket_protects_agent_selected_nodes():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0

    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[201],
    )

    assert result["status"] == "inconclusive"
    assert result["positiveNetBenefit"] is None
    assert result["limitedSocketCount"] == 3
    assert all(entry["status"] == "policy_limited" for entry in result["socketEvaluations"])


def test_positive_jewel_decision_cannot_be_overwritten_by_another_candidate():
    engine = _JewelMarginalEngine()
    first = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nFirst Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    second = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nSecond Jewel\nSapphire\nItem Level: 95\n14% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )

    assert first["positiveNetBenefit"] is True
    assert second["errorCode"] == "jewel_socket_positive_decision_pending"
    current = itemopt.next_jewel_decision_for_state(engine, first["stateHash"])
    assert current is not None and current["decisionRef"] == first["decisionRef"]


def test_undeclared_jewel_protection_is_diagnostic_only():
    engine = _JewelMarginalEngine()
    diagnostic = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
    )

    assert diagnostic["positiveNetBenefit"] is True
    assert diagnostic["protectionDeclared"] is False
    assert diagnostic["decision"] == "declare_protection_before_apply"
    assert "decisionRef" not in diagnostic

    actionable = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    assert actionable["protectionDeclared"] is True
    assert actionable["decisionRef"].startswith("jewel-decision:")


def test_apply_rejects_a_decision_without_declared_protection():
    engine = _JewelMarginalEngine()
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    with itemopt._JEWEL_DECISION_LOCK:
        itemopt._JEWEL_APPLY_DECISIONS[engine][evaluated["decisionRef"]]["protectionDeclared"] = (
            False
        )

    rejected = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash=evaluated["stateHash"],
    )

    assert rejected["errorCode"] == "jewel_protection_not_declared"


def test_evaluate_next_jewel_socket_reports_restore_failure():
    class RestoreFailureEngine(_JewelMarginalEngine):
        def load_build_xml(self, xml, name=""):
            del xml, name
            raise RuntimeError("restore failed")

    engine = RestoreFailureEngine()
    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    assert result["ok"] is False
    assert result["errorCode"] == "jewel_socket_probe_restore_failed"
    assert result["rolledBack"] is False
    assert result["recoveryRequired"] is True
    assert itemopt.next_jewel_decision_for_state(engine, build_state_hash(engine.get_xml())) is None


def test_evaluate_next_jewel_socket_full_tree_measures_equal_point_reallocation():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 0

    result = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    assert result["ok"] is True
    assert result["status"] == "evaluated"
    assert result["pointsReallocated"] == 2
    assert result["nodesToRemove"] == [201, 202]
    assert result["positiveNetBenefit"] is True
    assert result["metricsBefore"]["Life"] == 100
    assert result["metricsAfter"]["Life"] == 110
    assert engine.removed == set()


def test_apply_next_jewel_socket_decision_is_atomic_and_marks_round_progress():
    engine = _JewelMarginalEngine()
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )

    applied = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash=evaluated["stateHash"],
    )

    assert applied["ok"] is True
    assert applied["reviewRequired"] is True
    assert applied["outputStateHash"] != evaluated["stateHash"]
    current = itemopt.next_jewel_decision_for_state(engine, applied["outputStateHash"])
    assert current is not None and current["status"] == "applied"


def test_apply_next_jewel_socket_decision_preserves_protected_nodes():
    engine = _JewelMarginalEngine()
    engine.unspent_points = 1
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[201],
    )

    applied = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash=evaluated["stateHash"],
    )

    assert applied["ok"] is True
    assert applied["protectedNodeIds"] == [201]
    assert engine.get_passive(201)["alloc"] is True


def test_apply_next_jewel_socket_decision_rejects_stale_state_without_mutation():
    engine = _JewelMarginalEngine()
    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=1,
    )
    before = engine.get_xml()

    rejected = itemopt.apply_next_jewel_socket_decision(
        engine,
        decision_ref=evaluated["decisionRef"],
        expected_state_hash="sha256:stale",
    )

    assert rejected["errorCode"] == "build_state_conflict"
    assert engine.get_xml() == before


def test_round_index_is_compatibility_only():
    engine = _JewelMarginalEngine()

    evaluated = itemopt.evaluate_next_jewel_socket(
        engine,
        raw="Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate",
        goals={"Life": 1.0},
        protected_node_ids=[],
        round_index=7,
    )

    assert evaluated["ok"] is True
    assert evaluated["roundIndex"] == 7


def test_jewel_review_can_apply_more_than_two_positive_sockets():
    engine = _JewelMarginalEngine()
    raw = "Rarity: Rare\nTest Jewel\nSapphire\nItem Level: 95\n15% increased Mana Regeneration Rate"
    applied = None
    for index in range(1, 4):
        evaluated = itemopt.evaluate_next_jewel_socket(
            engine,
            raw=raw,
            goals={"Life": 1.0},
            protected_node_ids=[],
            round_index=index,
        )
        applied = itemopt.apply_next_jewel_socket_decision(
            engine,
            decision_ref=evaluated["decisionRef"],
            expected_state_hash=evaluated["stateHash"],
        )
        assert applied["ok"] is True

    assert applied is not None and applied["reviewRequired"] is True
    terminal = itemopt.evaluate_next_jewel_socket(
        engine,
        raw=raw,
        goals={"Life": 1.0},
        protected_node_ids=[],
    )
    assert terminal["status"] == "not_applicable"
