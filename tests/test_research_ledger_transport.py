"""资源明细的版本、来源绑定与公开分页必须保留完整证据。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts import research_mature_builds as runs
from server import main
from server.compute import pob_code
from server.knowledge import research_packet, research_readback, research_workflow
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


@pytest.mark.parametrize("page_limit", [1, 4, 24, 50])
def test_resource_rows_are_complete_and_large_rows_can_be_reassembled(
    monkeypatch, tmp_path, page_limit
):
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
            "diagnostics": [
                {"code": f"fixture_{n}", "note": "逐项资源诊断" * 10}
                for n in range(60 if i == 5 else 1)
            ],
        }
        for i in range(1, 29)
    ]
    original = deepcopy(packet)
    monkeypatch.setattr(research_workflow, "_run_dir", lambda _ref: tmp_path)
    monkeypatch.setattr(runs, "_case_for_valid_lease", lambda *_args: {"sample_id": "case:fixture"})
    monkeypatch.setattr(runs, "_packet_for_valid_lease", lambda **_kwargs: packet)
    rows, fragments, cursor = [], {}, 0
    while True:
        # Exercise the public transport guard too, not just the packet paginator.
        page = main.read_research_case(
            run_ref="research-run:fixture", lease_token="fixture-lease",
            section="pob-readback", cursor=cursor, limit=page_limit,
        )
        assert page["sampleId"] == "case:fixture"
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


@pytest.mark.parametrize("unsafe_text", [
    "<PathOfBuilding><Build/></PathOfBuilding>",
    pob_code.encode_code("<PathOfBuilding><Build level='99'/></PathOfBuilding>"),
    "https://poe.ninja/poe2/builds/fixture/character/private/account",
    "https://pobb.in/private-fixture",
    "攻略正文" * 400,
], ids=["xml", "import-code", "character-url", "share-url", "long-prose"])
def test_fragment_transport_keeps_raw_material_and_long_prose_guards(unsafe_text):
    with pytest.raises(ValueError, match="unsafe transient research"):
        runs._assert_transient_view_payload({
            "items": [{"kind": "evidence_fragment", "jsonFragment": unsafe_text}],
        })


@pytest.mark.parametrize("unsafe_text", [
    "<PathOfBuilding><Build/></PathOfBuilding>",
    pob_code.encode_code("<PathOfBuilding><Build level='99'/></PathOfBuilding>"),
    "https://poe.ninja/poe2/builds/fixture/character/private/account",
    "https://pobb.in/private-fixture",
    "攻略正文" * 2_000,
], ids=["xml", "import-code", "character-url", "share-url", "long-prose"])
def test_fragmentation_cannot_launder_unsafe_source_strings(unsafe_text):
    item = {
        "diagnostics": [{"index": n, "note": "bounded explanation" * 10} for n in range(50)],
        "untrustedText": unsafe_text,
    }
    with pytest.raises(ValueError, match="unsafe transient research"):
        research_packet._fragment_configuration_items([item])


@pytest.mark.parametrize("marker", runs.RAW_MARKERS)
def test_source_guard_rejects_raw_markers_across_fragment_boundaries(marker):
    item = {
        "a": "x" * (research_packet.JSON_FRAGMENT_CHARS - len('{"a":"') - 1) + marker,
        "z": [{"note": "bounded explanation" * 10} for _ in range(30)],
    }
    serialized = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert serialized.index(marker) == research_packet.JSON_FRAGMENT_CHARS - 1
    with pytest.raises(ValueError, match="unsafe transient research"):
        research_packet._fragment_configuration_items([item])


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
