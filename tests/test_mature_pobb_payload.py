from __future__ import annotations

from server.knowledge import mature_pobb_payload


def test_build_payload_row_from_pobb_uses_existing_import_path(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="95" className="Sorceress" ascendClassName="Stormweaver" />
  <Skills>
    <Skill mainActiveSkillCalcs="Spark">
      <Gem nameSpec="Spark" />
      <Gem nameSpec="Spell Echo" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""

    monkeypatch.setattr(mature_pobb_payload.pob_code, "to_xml", lambda url: xml)

    result = mature_pobb_payload.build_payload_row_from_pobb("https://pobb.in/htLxuXrVMVlX")

    assert result["ok"] is True
    row = result["payloadRow"]
    assert row["payloadSource"] == "pobb_in"
    assert row["sourceType"] == "pobb_in"
    assert row["sourceRef"] == "https://pobb.in/htLxuXrVMVlX"
    assert row["class"] == "Sorceress"
    assert row["ascendancy"] == "Stormweaver"
    assert row["mainSkill"] == "Spark"
    assert row["rawXml"] == xml


def test_build_payload_row_from_build_source_accepts_raw_import_code(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="89" className="Ranger" ascendClassName="Deadeye" />
  <Skills>
    <Skill mainActiveSkillCalcs="Lightning Arrow">
      <Gem nameSpec="Lightning Arrow" />
    </Skill>
  </Skills>
</PathOfBuilding2>
"""

    monkeypatch.setattr(mature_pobb_payload.pob_code, "to_xml", lambda src: xml)
    monkeypatch.setattr(mature_pobb_payload.pob_code, "is_link", lambda src: False)

    result = mature_pobb_payload.build_payload_row_from_build_source(
        source_ref="https://poe.ninja/poe2/builds/.../Isoartist",
        build_source="eNrtExampleImportCode123",
        payload_source="poe_ninja_page_import_code",
        source_type="poe_ninja",
        payload_kind="poe_ninja_import_code",
    )

    assert result["ok"] is True
    row = result["payloadRow"]
    assert row["payloadSource"] == "poe_ninja_page_import_code"
    assert row["sourceType"] == "poe_ninja"
    assert row["mainSkill"] == "Lightning Arrow"
    assert row["rawImportCode"] == "eNrtExampleImportCode123"


def test_build_payload_row_from_pobb_returns_safe_error_when_import_fails(monkeypatch):
    def _boom(url: str):
        raise mature_pobb_payload.pob_code.PobCodeError("could not fetch raw build")

    monkeypatch.setattr(mature_pobb_payload.pob_code, "to_xml", _boom)

    result = mature_pobb_payload.build_payload_row_from_pobb("https://pobb.in/does-not-exist")

    assert result["ok"] is False
    assert result["error"] == "pobb_import_failed"
