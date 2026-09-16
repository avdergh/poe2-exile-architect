"""Pure-Python tests for skill-text normalization and lever-template filling (no engine needed)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from server.compute import pob_code  # noqa: E402
from server.compute.skilltext import normalize_skill_text  # noqa: E402
from server.compute.solver import _apply_template  # noqa: E402


def test_slash_separated_becomes_one_gem_per_line():
    out = normalize_skill_text("Arc 20/20 1 / Lightning Penetration / Inspiration")
    assert out.splitlines() == [
        "Arc 20/20 1",
        "Lightning Penetration 20/20 1",
        "Inspiration 20/20 1",
    ]


def test_level_quality_slash_is_not_split():
    # "20/20" must survive — only a separator slash (not the digit/digit L/Q slash) is a boundary.
    assert "20/20" in normalize_skill_text("Fireball 20/20")
    assert normalize_skill_text("Fireball 20/20") == "Fireball 20/20  1"  # count appended


def test_spaceless_slash_separator_splits_without_dropping_supports():
    # Regression: a "/" with NO surrounding spaces ("Arc/Lightning Penetration") must still split
    # into separate gems — otherwise PoB parses only the first and silently drops the supports.
    assert normalize_skill_text("Arc/Lightning Penetration").splitlines() == [
        "Arc 20/20 1",
        "Lightning Penetration 20/20 1",
    ]
    # ...but a level/quality slash next to a real separator must still survive ("20/20" stays).
    assert normalize_skill_text("Comet 20/20 1/Cold Penetration").splitlines() == [
        "Comet 20/20 1",
        "Cold Penetration 20/20 1",
    ]


def test_mixed_separators_and_bare_names():
    out = normalize_skill_text("Arc, Rising Tempest | Inspiration")
    assert out.splitlines() == [
        "Arc 20/20 1",
        "Rising Tempest 20/20 1",
        "Inspiration 20/20 1",
    ]


def test_already_canonical_is_stable_idempotent():
    canonical = "Spark 20/0  1"
    assert normalize_skill_text(canonical) == canonical
    assert normalize_skill_text(normalize_skill_text(canonical)) == canonical


@pytest.mark.parametrize("name", ["Ice-Tipped Arrows", "Future-Past", "Uul-Netol's Embrace"])
def test_hyphenated_catalog_names_are_preserved(name):
    assert normalize_skill_text(name) == f"{name} 20/20 1"
    assert normalize_skill_text(name, default_level=None) == name
    assert normalize_skill_text(f"{name} 20/0") == f"{name} 20/0  1"


def test_apply_template_multiple_placeholders():
    # The crash case: two "{}" must both fill instead of raising "Replacement index out of range".
    assert _apply_template("Adds {} to {} Lightning Damage to Spells", 10) == (
        "Adds 10 to 10 Lightning Damage to Spells"
    )
    assert _apply_template("{}% increased Lightning Damage", 10) == "10% increased Lightning Damage"
    assert _apply_template("+{} to maximum Life", 25) == "+25 to maximum Life"


def test_import_link_rejects_webpage_hosts():
    # Build-archive pages aren't raw PoB codes — fail fast with a paste-the-code hint, not a
    # cryptic base64 error from decoding a web page.
    for url in (
        "https://maxroll.gg/poe2/pob/abc",
        "https://pobarchives.com/build/xyz",
        "https://poe.ninja/pob/123",
        "https://mobalytics.gg/poe-2/builds/whatever",
    ):
        with pytest.raises(pob_code.PobCodeError) as ei:
            pob_code.to_xml(url)
        assert "paste" in str(ei.value).lower()


def test_coerce_to_xml_html_vs_xml_vs_code():
    # An HTML page returns a friendly error; raw PoB XML passes through; a real code decodes.
    with pytest.raises(pob_code.PobCodeError):
        pob_code._coerce_to_xml("<!DOCTYPE html><html><head></head></html>", "x")
    xml = '<?xml version="1.0"?><PathOfBuilding2><Build/></PathOfBuilding2>'
    assert pob_code._coerce_to_xml(xml, "x") == xml
    code = pob_code.encode_code('<PathOfBuilding2><Build level="1"/></PathOfBuilding2>')
    assert "PathOfBuilding2" in pob_code._coerce_to_xml(code, "x")


def test_decode_recovers_corrupted_trailing_checksum():
    # Long codes pasted into chat commonly corrupt only the trailing Adler-32 checksum while the
    # deflate body is intact — decode must still recover the build (the real fix from the meta import).
    import base64
    import zlib

    xml = '<?xml version="1.0"?><PathOfBuilding2><Build level="1"/></PathOfBuilding2>'
    raw = bytearray(zlib.compress(xml.encode(), 9))
    raw[-1] ^= 0xFF  # corrupt the trailing checksum only
    code = base64.b64encode(bytes(raw)).decode().replace("+", "-").replace("/", "_")
    assert "PathOfBuilding2" in pob_code.decode_code(code)


def test_decode_rejects_unrecoverable_data():
    import base64

    junk = base64.b64encode(b"this is not a zlib stream at all, just plain bytes" * 4).decode()
    with pytest.raises(pob_code.PobCodeError):
        pob_code.decode_code(junk)
