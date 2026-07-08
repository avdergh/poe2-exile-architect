from __future__ import annotations

from server.compute import pob_code
from server.knowledge import mature_ninja_payload


def test_extract_import_code_from_rendered_html_reads_dom_injected_input_value():
    page_html = """
<html>
  <head><title>Builds - Isoartist - Path of Exile 2 - poe.ninja</title></head>
  <body>
    <input aria-label="Import code for Path of Building" type="text" value="eNrtExampleImportCode123" />
    <a href="pob2://poeninja/overview/code?account=pepukang-0090&name=Isoartist&overview=ssf-runes-of-aldur"></a>
  </body>
</html>
"""

    result = mature_ninja_payload.extract_import_code_from_rendered_html(page_html)

    assert result["ok"] is True
    assert result["importCode"] == "eNrtExampleImportCode123"
    assert result["pob2DeepLinkRef"].startswith("pob2-hash:")
    assert "pob2DeepLink" not in result
    assert "account=pepukang" not in str(result)


def test_extract_import_code_from_rendered_html_accepts_valid_non_enrt_pob_code():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
    <Build level="95" className="Ranger" ascendClassName="Deadeye" />
</PathOfBuilding2>
"""
    code = pob_code.encode_code(xml)
    assert not code.startswith("eNrt")
    page_html = f"""
<html>
  <head><title>Builds - Isoartist - Path of Exile 2 - poe.ninja</title></head>
  <body>
    <input aria-label="Import code for Path of Building" type="text" value="{code}" />
  </body>
</html>
"""

    result = mature_ninja_payload.extract_import_code_from_rendered_html(page_html)

    assert result["ok"] is True
    assert result["importCode"] == code


def test_extract_import_code_from_dom_snapshot_reads_visible_input_value():
    snapshot = """
heading "Isoartist" [level=1]
generic: Level 100 Martial Artist
input aria-label="Import code for Path of Building" type="text" value="eNrtExampleImportCode123"
link:
  /url: pob2://poeninja/overview/code?account=pepukang-0090&name=Isoartist&overview=ssf-runes-of-aldur
"""

    result = mature_ninja_payload.extract_import_code_from_dom_snapshot(snapshot)

    assert result["ok"] is True
    assert result["importCode"] == "eNrtExampleImportCode123"
    assert result["pob2DeepLinkRef"].startswith("pob2-hash:")
    assert "pob2DeepLink" not in result
    assert "account=pepukang" not in str(result)
    assert result["profileSummary"]["characterRef"].startswith("character-hash:")
    assert "Isoartist" not in str(result)


def test_extract_import_code_from_rendered_html_rejects_non_build_page_or_missing_code():
    bad_title = mature_ninja_payload.extract_import_code_from_rendered_html(
        "<html><title>not it</title></html>"
    )
    missing_code = mature_ninja_payload.extract_import_code_from_rendered_html(
        "<html><title>Builds - X - Path of Exile 2 - poe.ninja</title></html>"
    )

    assert bad_title["ok"] is False
    assert bad_title["error"] == "not_a_poe_ninja_build_page"
    assert missing_code["ok"] is False
    assert missing_code["error"] == "import_code_not_found"


def test_build_payload_row_from_import_code_reuses_existing_pob_codec(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build level="100" className="Monk" ascendClassName="Acolyte" />
</PathOfBuilding2>
"""

    monkeypatch.setattr(mature_ninja_payload.pob_code, "to_xml", lambda code: xml)

    result = mature_ninja_payload.build_payload_row_from_import_code(
        source_ref="https://poe.ninja/poe2/builds/.../Isoartist",
        import_code="eNrtExampleImportCode123",
        quarantine_pob2_deep_link="pob2://poeninja/overview/code?...",
    )

    assert result["ok"] is True
    row = result["payloadRow"]
    assert row["payloadSource"] == "poe_ninja_page_import_code"
    assert row["sourceType"] == "poe_ninja"
    assert row["rawImportCode"] == "eNrtExampleImportCode123"
    assert row["rawXml"] == xml
    assert row["sourcePayload"]["quarantinePob2DeepLink"].startswith("pob2://")
    assert row["sourcePayload"]["pob2DeepLinkRef"].startswith("pob2-hash:")


def test_build_payload_row_from_import_code_returns_safe_error_on_codec_failure(monkeypatch):
    def _boom(code: str):
        raise mature_ninja_payload.pob_code.PobCodeError("bad import code")

    monkeypatch.setattr(mature_ninja_payload.pob_code, "to_xml", _boom)

    result = mature_ninja_payload.build_payload_row_from_import_code(
        source_ref="https://poe.ninja/poe2/builds/.../Isoartist",
        import_code="eNrtBadCode",
    )

    assert result["ok"] is False
    assert result["error"] == "ninja_import_failed"
