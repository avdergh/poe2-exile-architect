from __future__ import annotations

from server.knowledge import research_readback
import pytest


class _FakeEngine:
    def __init__(self, **_kwargs):
        self.xml = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def load_build_xml(self, xml: str, name: str = ""):
        self.xml = xml
        return {"name": name}

    def get_stats(self, _keys):
        return {
            "stats": {
                "Mana": 10597,
                "ManaPerSecondCost": 5968,
                "ManaRegen": 4201.5,
                "Spirit": 251,
                "SpiritReserved": 259,
                "SpiritUnreserved": -8,
            }
        }

    def get_build(self):
        return {
            "spiritAvailable": 251,
            "spiritReservedCapped": 251,
            "spiritUnreserved": -8,
            "spiritRequested": 259,
            "spiritOverBy": 8,
            "spiritUsed": 259,
            "activeWeaponSet": 2,
            "pointsUsed": 146,
            "normalPassivePointsUsed": 124,
            "pointsAvailable": 124,
            "unspentPoints": 0,
            "ascendancyPointsUsed": 8,
            "ascendancyPointsMax": 8,
            "secondaryAscendancyPointsUsed": 0,
            "weaponSet1PointsUsed": 22,
            "weaponSet2PointsUsed": 22,
            "weaponSetPointsAvailable": 24,
        }

    def get_xml(self):
        return '<PathOfBuilding><Build level="98"/></PathOfBuilding>'

    def inspect_reservation_ledger(self):
        from server.compute.state import build_state_hash

        return {
            "schemaVersion": "pob_reservation_ledger_v1",
            "status": "available",
            "effects": [], "groups": [],
            "totals": {pool: {} for pool in ("Life", "Mana", "Spirit")},
            "activeWeaponSet": self.get_build().get("activeWeaponSet"),
            "readOnlyVerified": True,
            "buildStateHash": build_state_hash(self.get_xml()),
        }


@pytest.mark.parametrize("model, status", [("0.5.4", "source_patch_model_mismatch"),
    ("0.5.5", "certified_local_runtime"), ("", "model_version_unknown")])
def test_readback_preserves_source_and_model_patch_without_numerical_promotion(monkeypatch, model, status):
    monkeypatch.setattr(research_readback, "PobEngine", _FakeEngine)
    context = {"gamePatch": "0.5.5", "modelGamePatch": model,
               "passiveTreeVersion": "0_5", "pobVersionOrCommit": "0.23.1"}
    result = research_readback.build_safe_readback("<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context=context)
    assert result["versionContext"]["gamePatch"] == "0.5.5"
    assert result["versionContext"]["modelGamePatch"] == model
    assert result["versionContext"]["status"] == status
    assert result["modelability"]["status"] == "partial"
    if model == "0.5.4":
        assert any("model patch 0.5.4" in warning for warning in result["modelability"]["caveats"])
    unavailable = research_readback.build_safe_readback("", source_hash_ref="source-hash:test", version_context=context)
    assert unavailable["versionContext"] == result["versionContext"]


def test_packet_and_readback_share_version_context_and_bind_it_into_safe_hash(tmp_path, monkeypatch):
    from scripts import research_mature_builds as mature
    from server.knowledge import research_packet
    monkeypatch.setattr(research_readback, "PobEngine", _FakeEngine)
    monkeypatch.setenv("POE2_RESEARCH_POB_READBACK", "1")
    captured = []
    original = research_packet.build_research_packet
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result["packet"])
        return result
    monkeypatch.setattr(research_packet, "build_research_packet", capture)
    case = {"sampleId": "case:test", "sourceType": "local_pob_file", "sourceHashRef": "source-hash:test",
            "sourceHash": "test", "_rawImportCode": "synthetic", "_rawXml": "<PathOfBuilding/>"}
    for model in ("0.5.4", "0.5.5"):
        mature._prepare_packet(case, temp_root=tmp_path, ttl_seconds=60, current_patch="0.5.5",
            passive_tree_version="0_5", pob_version_or_commit="0.23.1", include_pob_readback=True,
            version_context={"modelGamePatch": model})
    first = captured[0]
    assert first["safeMetadata"]["modelGamePatch"] == "0.5.4"
    assert first["safeMetadata"]["versionContextStatus"] == "source_patch_model_mismatch"
    assert first["pobReadback"]["versionContext"]["modelGamePatch"] == "0.5.4"
    assert captured[0]["safeHash"] != captured[1]["safeHash"]


def test_safe_readback_recomputes_bounded_active_snapshot(monkeypatch):
    monkeypatch.setattr(research_readback, "PobEngine", _FakeEngine)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>",
        source_hash_ref="source-hash:test",
        version_context={"gamePatch": "0.5.4", "pobVersionOrCommit": "pinned"},
    )
    assert result["status"] == "available"
    assert result["resources"]["spiritOverBy"] == 8
    assert result["resources"]["spiritRequested"] == 259
    assert result["resources"]["spiritReservedCapped"] == 251
    assert result["resources"]["ledgerStatus"] == "consistent"
    assert result["resources"]["ledgerScope"] == "model_snapshot_arithmetic"
    assert any("does not establish source completeness or real-character legality" in caveat
               for caveat in result["modelability"]["caveats"])
    assert not any("DPS" in caveat for caveat in result["modelability"]["caveats"])
    assert result["stats"]["ManaPerSecondCost"] == 5968
    serialized = str(result).casefold()
    assert "rawxml" not in serialized and "<pathofbuilding" not in serialized
    assert result["stateBinding"]["weaponSetState"] == "active"
    assert result["stateBinding"]["activeWeaponSet"] == 2
    assert result["schemaVersion"] == "research_pob_readback_v5"
    assert result["metricSetVersion"] == 3
    assert result["reservationLedger"]["buildStateHash"] == result["stateBinding"]["observedBuildStateHash"]
    assert "supportOwnerEvidence" not in result


def test_safe_readback_preserves_separate_passive_point_pools(monkeypatch):
    monkeypatch.setattr(research_readback, "PobEngine", _FakeEngine)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context={}
    )

    assert result["passivePoints"] == {
        "normalPassivePointsUsed": 124,
        "pointsAvailable": 124,
        "unspentPoints": 0,
        "ascendancyPointsUsed": 8,
        "ascendancyPointsMax": 8,
        "secondaryAscendancyPointsUsed": 0,
        "weaponSet1PointsUsed": 22,
        "weaponSet2PointsUsed": 22,
        "weaponSetPointsAvailable": 24,
        "pointsAvailableBasis": "wrapper_level_progress_estimate_plus_ExtraPoints",
    }
    assert any("does not certify the source character's quest completion" in caveat
               for caveat in result["modelability"]["caveats"])


@pytest.mark.parametrize("invalid", [None, "24", True, -1, 1.5, float("nan"), float("inf")])
def test_safe_readback_does_not_invent_missing_or_invalid_point_counts(monkeypatch, invalid):
    class MissingPoints(_FakeEngine):
        def get_build(self):
            return {"pointsUsed": 146, "pointsAvailable": invalid}

    monkeypatch.setattr(research_readback, "PobEngine", MissingPoints)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context={}
    )

    assert all(result["passivePoints"][key] is None
               for key in research_readback.PASSIVE_POINT_KEYS)


def test_safe_readback_rejects_string_and_boolean_spirit_fields(monkeypatch):
    class WrongTypes(_FakeEngine):
        def get_build(self):
            return {
                "spiritAvailable": "251",
                "spiritReservedCapped": 251,
                "spiritUnreserved": -8,
                "spiritRequested": 259,
                "spiritOverBy": False,
                "spiritUsed": 259,
                "activeWeaponSet": "2",
            }

    monkeypatch.setattr(research_readback, "PobEngine", WrongTypes)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context={}
    )

    assert result["resources"]["ledgerStatus"] == "unavailable"
    assert result["resources"]["spiritAvailable"] is None
    assert result["resources"]["spiritOverBy"] is None
    assert result["stateBinding"]["activeWeaponSet"] is None


def test_safe_readback_never_reconstructs_requested_from_capped_used(monkeypatch):
    class LegacyCapped(_FakeEngine):
        def get_build(self):
            return {
                "spiritAvailable": 150,
                "spiritUsed": 150,
                "spiritUnreserved": -200,
            }

    monkeypatch.setattr(research_readback, "PobEngine", LegacyCapped)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context={}
    )

    assert result["resources"]["ledgerStatus"] == "unavailable"
    assert result["resources"]["spiritRequested"] is None
    assert result["resources"]["spiritOverBy"] is None


def test_safe_readback_failure_is_raw_free(monkeypatch):
    class Broken(_FakeEngine):
        def __enter__(self):
            raise RuntimeError("private source material")

    monkeypatch.setattr(research_readback, "PobEngine", Broken)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context={}
    )
    assert result["status"] == "unavailable"
    assert result["errorKind"] == "RuntimeError"
    assert "private source material" not in str(result)


@pytest.mark.parametrize("field,value,error", [
    ("schemaVersion", "legacy", "reservation_ledger_contract_mismatch"),
    ("status", "unavailable", "reservation_ledger_unavailable"),
    ("buildStateHash", "old-state", "reservation_ledger_state_mismatch"),
    ("readOnlyVerified", False, "reservation_ledger_state_mismatch"),
])
def test_readback_rejects_old_or_unbound_ledger(monkeypatch, field, value, error):
    class BadLedger(_FakeEngine):
        def inspect_reservation_ledger(self):
            return {**super().inspect_reservation_ledger(), field: value}

    monkeypatch.setattr(research_readback, "PobEngine", BadLedger)
    result = research_readback.build_safe_readback(
        "<PathOfBuilding/>", source_hash_ref="source-hash:test", version_context={},
    )
    assert result["status"] == "unavailable"
    assert result["errorCode"] == error
