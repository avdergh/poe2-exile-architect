"""资源明细的版本、来源绑定与公开分页必须保留完整证据。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import research_mature_builds as runs
from server.knowledge import research_packet, research_readback
from test_research_readback import _FakeEngine


def _packet(monkeypatch):
    monkeypatch.setattr(research_readback, "PobEngine", _FakeEngine)
    xml = "<PathOfBuilding/>"
    readback = research_readback.build_safe_readback(
        xml,
        source_hash_ref="source-hash:fixture",
        version_context={},
    )
    assert readback["status"] == "available", readback
    return {
        "rawContext": {"rawXml": xml},
        "safeMetadata": {"sourceRef": "source-hash:fixture"},
        "pobReadback": readback,
    }


@pytest.mark.parametrize(
    "change", ["old_version", "marker_only", "hash", "snapshot", "source", "read_only", "semantic_hash", "weapon_set", "missing_groups", "missing_effects", "missing_totals"]
)
def test_old_or_unbound_ledger_cannot_gain_new_readback_authority(monkeypatch, change):
    packet = _packet(monkeypatch)
    readback = packet["pobReadback"]
    assert research_packet.validated_pob_readback(packet)["status"] == "available"
    if change == "old_version":
        readback.update(schemaVersion="research_pob_readback_v4", metricSetVersion=2)
    elif change == "marker_only":
        readback.pop("reservationLedger")
    elif change == "semantic_hash":
        readback["stateBinding"]["semanticBuildStateHash"] = "different"
    elif change == "weapon_set":
        readback["reservationLedger"]["activeWeaponSet"] = 1
    elif change.startswith("missing_"):
        readback["reservationLedger"].pop(change.removeprefix("missing_"))
    else:
        key = {
            "hash": "buildStateHash",
            "snapshot": "snapshotRef",
            "source": "sourceHashRef",
            "read_only": "readOnlyVerified",
        }[change]
        readback["reservationLedger"][key] = False if change == "read_only" else "different"
    before = deepcopy(packet)
    result = research_packet.validated_pob_readback(packet)
    assert result["status"] == "unavailable"
    assert result["errorCode"] == "research_readback_contract_stale_or_unbound"
    assert "stats" not in result
    assert packet == before


def test_resource_rows_are_complete_and_large_rows_can_be_reassembled(monkeypatch):
    packet = _packet(monkeypatch)
    ledger = packet["pobReadback"]["reservationLedger"]
    ledger.update(
        identityScope="post_import_runtime",
        valueScope="native_calculated_reservation",
        sourceGroupMappingStatus="not_observed",
    )
    ledger["groups"] = [
        {"groupIndex": i, "sourceKind": "gem", "usingWeaponSet": 1} for i in range(1, 29)
    ]
    ledger["effects"] = [
        {
            "groupIndex": i,
            "effectId": f"Fixture{i}",
            "gemIndex": 1,
            "pools": {"Life": {"nativeReservedBase": None}, "Spirit": {"nativeReservedBase": i}},
            "diagnostic": "说明" * (3_000 if i == 5 else 50),
        }
        for i in range(1, 29)
    ]
    original = deepcopy(packet)
    rows, fragments, cursor = [], {}, 0
    while True:
        page = research_packet.read_packet_section(
            packet, section="pob-readback", cursor=cursor, limit=4
        )
        assert len(json.dumps(page, ensure_ascii=False)) <= research_packet.MAX_RESPONSE_CHARS
        for row in page["items"]:
            assert row.get("truncated") is not True
            if row.get("kind") == "evidence_fragment":
                fragments.setdefault(row["sourceItemIndex"], {})[row["fragmentIndex"]] = row[
                    "jsonFragment"
                ]
            else:
                rows.append(row)
        if page["complete"]:
            assert page["nextCursor"] is None
            break
        assert page["nextCursor"] > cursor
        cursor = page["nextCursor"]
    rows.extend(
        json.loads("".join(value[i] for i in sorted(value))) for value in fragments.values()
    )
    effects = [row for row in rows if row.get("kind") == "reservation_ledger_effect"]
    assert (
        sorted((row["entry"] for row in effects), key=lambda row: row["groupIndex"])
        == ledger["effects"]
    )
    assert all(row["sourceHashRef"] == "source-hash:fixture" for row in effects)
    assert all(row["buildStateHash"] == ledger["buildStateHash"] for row in effects)
    assert all(row["sourceGroupMappingStatus"] == "not_observed" for row in effects)
    summary = next(row for row in rows if row.get("kind") == "pob_readback_summary")
    assert summary["reservationLedger"]["effectCount"] == 28
    assert "effects" not in summary["reservationLedger"]
    assert packet == original


@pytest.mark.parametrize("kind, expected", [("current", True), ("old", False), ("queued", True)])
def test_resume_rebuilds_old_numeric_cache_without_mutating_it(
    monkeypatch, tmp_path, kind, expected
):
    packet = _packet(monkeypatch)
    if kind == "old":
        packet["pobReadback"].update(schemaVersion="research_pob_readback_v4", metricSetVersion=2)
    elif kind == "queued":
        packet.pop("pobReadback")
    now = datetime.now(timezone.utc)
    packet["safeHash"] = research_packet._safe_hash(packet)
    packet["expiresAt"] = (now + timedelta(hours=1)).isoformat()
    directory = tmp_path / (research_packet.PACKET_PREFIX + "fixture")
    directory.mkdir()
    path = directory / "packet.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    before = path.read_bytes()
    assert runs._resume_packet_is_current(tmp_path, packet["safeHash"], now) is expected
    assert path.read_bytes() == before
