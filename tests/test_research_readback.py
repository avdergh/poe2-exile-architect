from __future__ import annotations

from server.knowledge import research_readback


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
        }

    def get_xml(self):
        return '<PathOfBuilding><Build level="98"/></PathOfBuilding>'


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
    assert result["stats"]["ManaPerSecondCost"] == 5968
    assert "xml" not in str(result).casefold()
    assert result["stateBinding"]["weaponSetState"] == "active"
    assert result["stateBinding"]["activeWeaponSet"] == 2
    assert result["schemaVersion"] == "research_pob_readback_v3"
    assert "supportOwnerEvidence" not in result


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
