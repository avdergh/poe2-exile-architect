"""Filled sockets do not waive an outstanding measured upgrade."""

import pytest

from server.compute import craftopt
from server.compute.state import build_state_hash
from test_socket_measurement_contract import (
    SocketEngine,
    direct_plan,
    safe_audits as safe_audits,
    socket_check,
)


@pytest.mark.parametrize("count", [1, 2])
def test_filled_slot_pending_upgrade_blocks_until_trusted_equip(count, safe_audits):
    engine = SocketEngine(responses=[{"results": [{"TotalEHP": 120}]}, {"results": [{"TotalEHP": 120}]}])
    result = direct_plan(engine, count)
    assert result["decision"] in {"socketed", "partial_socketed"}
    pending = socket_check(engine, result["stateHash"], full=True)
    assert pending["status"] == "failed"
    assert "planned_socket_not_applied:Body Armour" in pending["reasons"]
    engine.add_item(result["item"])
    after = build_state_hash(engine.get_xml())
    assert craftopt.carry_socket_decision_to_equipped_state(
        engine, input_state_hash=result["stateHash"], output_state_hash=after,
        slot="Body Armour", item_fingerprint="sha256:test",
    ) in {"socketed", "partial_no_positive"}
    assert craftopt.socket_pending_slots_for_state(engine, after) == []
    assert socket_check(engine, after, full=True)["status"] == "passed"
