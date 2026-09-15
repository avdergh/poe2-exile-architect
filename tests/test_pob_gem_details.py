"""精确宝石静态详情：只用临时/固定源，不接触用户 Research 库。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.knowledge import db, pob_gem_details as details
from pipeline.build_corpus import SCHEMA


def _runtime(tmp_path, monkeypatch, *, extra_effects=(), description=None, stat_sets=None):
    data = tmp_path / "src" / "Data"
    (data / "Skills").mkdir(parents=True)
    (data / "StatDescriptions").mkdir()
    (tmp_path / "manifest.xml").write_text('<PoBVersion><Version number="fixture" /></PoBVersion>')
    bindings = '\t\tgrantedEffectId = "FixtureEffect",\n'
    bindings += "".join(
        f"\t\tadditionalGrantedEffectId{i} = {json.dumps(v)},\n"
        for i, v in enumerate(extra_effects, 1)
    )
    (data / "Gems.lua").write_text(
        'return {\n\t["Metadata/Gem/Fixture"] = {\n'
        '\t\tgameId = "Metadata/Game/Fixture",\n' + bindings + "\t},\n}\n"
    )
    if stat_sets is None:
        stat_sets = (
            '\tstatSets = {\n\t\t[1] = {\n\t\t\tlabel = "Fixture",\n'
            '\t\t\tstatDescriptionScope = "gem_stat_descriptions",\n'
            '\t\t\tconstantStats = {\n\t\t\t\t{ "fixture_damage", 30 },\n\t\t\t},\n'
            "\t\t\tstats = {\n\t\t\t},\n\t\t},\n\t}\n"
        )
    desc = f"\tdescription = {json.dumps(description)},\n" if description is not None else ""
    effect = data / "Skills" / "fixture.lua"
    effect.write_text(
        'skills["FixtureEffect"] = {\n\tname = "Different display",\n'
        "\tsupport = true,\n\trequireSkillTypes = { SkillType.CreatesMinion, },\n"
        "\texcludeSkillTypes = { SkillType.MinionsAreUndamagable, },\n" + desc + stat_sets + "}\n"
    )
    translation = data / "StatDescriptions" / "gem_stat_descriptions.lua"
    translation.write_text(
        "return {\n\t[1]={\n\t\t[1]={\n\t\t\t[1]={"
        '\n\t\t\t\tlimit={[1]={[1]=1,[2]="#"}},\n'
        '\t\t\t\ttext="Supported Minions deal {0}% more Damage"\n'
        '\t\t\t}\n\t\t},\n\t\tstats={[1]="fixture_damage"}\n\t},\n'
        '\t["fixture_damage"]=1\n}\n'
    )
    monkeypatch.setattr(
        details.paths,
        "pob_runtime_pair",
        lambda: SimpleNamespace(src_dir=data.parent, source="fixture"),
    )
    return data, effect, translation


def test_missing_prose_uses_own_exact_stat_template_and_preserves_constraints(
    tmp_path, monkeypatch
):
    data, effect, translation = _runtime(tmp_path, monkeypatch)
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert result["status"] == "available"
    row = result["effects"][0]
    assert row["description"] == "Supported Minions deal 30% more Damage"
    assert row["descriptionOrigin"] == "stat_text_projection"
    assert row["descriptionStatus"] == "source_field_missing"
    assert row["supportConstraints"]["excludeSkillTypes"]["values"] == ["MinionsAreUndamagable"]
    stat = row["statSets"][0]["stats"][0]
    assert (
        stat["textSourceRef"]
        == "pob-static:sha256:" + hashlib.sha256(translation.read_bytes()).hexdigest()
    )
    assert (
        row["sourceRef"] == "pob-static:sha256:" + hashlib.sha256(effect.read_bytes()).hexdigest()
    )
    assert (
        result["gemSourceRef"]
        == "pob-static:sha256:" + hashlib.sha256((data / "Gems.lua").read_bytes()).hexdigest()
    )
    assert result["mechanismCompleteness"] == "not_certified"
    text, provenance = db._pob_support_description("Metadata/Game/Fixture", ["FixtureEffect"])
    assert text == row["description"]
    assert provenance["descriptionOrigin"] == "stat_text_projection"


def test_missing_value_keeps_template_and_does_not_invent_buff_parameters(tmp_path, monkeypatch):
    _, effect, translation = _runtime(
        tmp_path, monkeypatch, description="Collect a remnant to gain a buff."
    )
    effect.write_text(
        effect.read_text()
        .replace('\t\t\tconstantStats = {\n\t\t\t\t{ "fixture_damage", 30 },\n\t\t\t},\n', "")
        .replace("\t\t\tstats = {\n", '\t\t\tstats = {\n\t\t\t\t"fixture_damage",\n')
    )
    translation.write_text(
        translation.read_text().replace(
            "Supported Minions deal {0}% more Damage", "Collecting remnants grants a buff"
        )
    )
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    stat = result["effects"][0]["statSets"][0]["stats"][0]
    assert stat["value"] is None and stat["valueStatus"] == "not_explicit"
    assert stat["textStatus"] == "translation_unresolved"
    assert stat["textTemplates"][0]["text"] == "Collecting remnants grants a buff"
    assert "duration" not in stat and "recovery" not in stat
    assert result["mechanismCompleteness"] == "not_certified"


def test_multiple_exact_grants_stay_separate_and_do_not_select_by_display_name(
    tmp_path, monkeypatch
):
    _, effect, _ = _runtime(
        tmp_path, monkeypatch, extra_effects=["ChildEffect"], description="Root text."
    )
    effect.write_text(
        effect.read_text() + 'skills["ChildEffect"] = {\n'
        '\tname = "Different display",\n\tdescription = "Child text.",\n\tsupport = false,\n}\n'
    )
    result = details.get_details("Metadata/Game/Fixture", ["ChildEffect", "FixtureEffect"])
    assert result["descriptionSelection"] == "multiple_granted_effects"
    assert [(e["effectId"], e["description"]) for e in result["effects"]] == [
        ("FixtureEffect", "Root text."),
        ("ChildEffect", "Child text."),
    ]
    stale = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert stale["reason"] == "corpus_runtime_granted_effects_mismatch" and stale["effects"] == []


@pytest.mark.parametrize(
    "change,reason",
    [
        ("missing", "effect_missing"),
        ("duplicate", "effect_ambiguous"),
        ("malformed", "effect_parse_failed"),
    ],
)
def test_effect_failures_are_distinct_and_cannot_borrow_other_effects(
    tmp_path, monkeypatch, change, reason
):
    _, effect, _ = _runtime(tmp_path, monkeypatch, description="Only this effect.")
    original = effect.read_text()
    if change == "missing":
        effect.write_text(original.replace('skills["FixtureEffect"]', 'skills["OtherEffect"]'))
    elif change == "duplicate":
        effect.write_text(original + original)
    else:
        effect.write_text(original.removesuffix("}\n") + "} unknown_suffix\n")
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert result["effects"][0]["reason"] == reason
    text, source = db._pob_support_description("Metadata/Game/Fixture", ["FixtureEffect"])
    assert text == "" and source["detailReason"] == reason


@pytest.mark.parametrize("replacement", ["readValue()", '"not a number"'])
def test_stat_expression_or_invalid_value_does_not_authorize_fallback(
    tmp_path, monkeypatch, replacement
):
    _, effect, _ = _runtime(tmp_path, monkeypatch)
    effect.write_text(
        effect.read_text().replace('"fixture_damage", 30', '"fixture_damage", ' + replacement)
    )
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert result["effects"][0]["description"] == ""
    assert "constantStats_parse_failed" in result["effects"][0]["issues"]


def test_multi_stat_sets_do_not_collapse_to_one_unqualified_description(tmp_path, monkeypatch):
    _, effect, _ = _runtime(tmp_path, monkeypatch)
    text = effect.read_text()
    stat_set = text[text.index("\t\t[1] = {") : text.index("\t}\n")]
    effect.write_text(text.replace("\t}\n", stat_set.replace("[1] = {", "[2] = {", 1) + "\t}\n"))
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert len(result["effects"][0]["statSets"]) == 2
    assert result["effects"][0]["description"] == ""


def test_translation_replacement_updates_text_and_evidence(tmp_path, monkeypatch):
    _, _, translation = _runtime(tmp_path, monkeypatch)
    before = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    translation.write_text(translation.read_text().replace("more Damage", "more Fixture Damage"))
    after = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    first = before["effects"][0]["statSets"][0]["stats"][0]
    second = after["effects"][0]["statSets"][0]["stats"][0]
    assert first["text"] != second["text"] and first["textSourceRef"] != second["textSourceRef"]


def test_source_missing_and_parse_failure_are_distinct(tmp_path, monkeypatch):
    data, _, _ = _runtime(tmp_path, monkeypatch)
    (data.parent.parent / "manifest.xml").write_text("not xml")
    assert (
        details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])["reason"]
        == "static_source_parse_failed"
    )
    (data / "Gems.lua").unlink()
    assert (
        details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])["reason"]
        == "static_source_missing"
    )


@pytest.mark.parametrize(
    "replacement,expected",
    [
        ("readText()", "translation_source_parse_failed"),
        ('"Unsupported {0:+d} format"', "translation_unresolved"),
    ],
)
def test_unhandled_template_is_diagnostic_not_a_guessed_description(
    tmp_path, monkeypatch, replacement, expected
):
    _, _, translation = _runtime(tmp_path, monkeypatch)
    translation.write_text(
        translation.read_text().replace('"Supported Minions deal {0}% more Damage"', replacement)
    )
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert result["effects"][0]["description"] == ""
    assert result["effects"][0]["statSets"][0]["stats"][0]["textStatus"] == expected


def test_incomplete_stat_set_is_not_silently_omitted(tmp_path, monkeypatch):
    _, effect, _ = _runtime(tmp_path, monkeypatch)
    effect.write_text(
        effect.read_text().replace("\t}\n", '\t\t[2] = {\n\t\t\tlabel = "broken",\n\t}\n')
    )
    result = details.get_details("Metadata/Game/Fixture", ["FixtureEffect"])
    assert result["effects"][0]["statSets"] == []
    assert result["effects"][0]["description"] == ""
    assert "stat_sets_parse_failed" in result["effects"][0]["issues"]


def test_get_gem_exposes_details_even_when_corpus_description_exists(tmp_path, monkeypatch):
    _runtime(tmp_path, monkeypatch, description="Exact effect description.")
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute(
        "INSERT INTO gems VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            "Metadata/Game/Fixture",
            "Fixture gem",
            "r",
            "support",
            "[]",
            '["FixtureEffect"]',
            "[]",
            "Original corpus description.",
            "[]",
            "{}",
        ),
    )
    monkeypatch.setattr(db, "_conn", lambda: con)
    monkeypatch.setattr(db.gem_availability, "inspect_ids", lambda _: {})
    result = db.get_gem("Fixture gem")
    assert result["description"] == "Original corpus description."
    assert result["effectDetails"]["effects"][0]["description"] == "Exact effect description."
    assert "descriptionSource" not in result  # Do not give corpus prose another file's provenance.
    con.close()


def test_repository_pinned_regressions(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "pob" / "PathOfBuilding-PoE2"
    if not (root / "src" / "Data" / "Gems.lua").is_file():
        pytest.skip("pinned repository runtime unavailable")
    monkeypatch.setattr(
        details.paths,
        "pob_runtime_pair",
        lambda: SimpleNamespace(src_dir=root / "src", source="fixture-pinned"),
    )
    frenzy = details.get_details(
        "Metadata/Items/Gems/SupportGemFeedingFrenzyTwo", ["SupportFeedingFrenzyPlayerTwo"]
    )
    assert frenzy["effects"][0]["description"] == (
        "Minions from Supported Skills take 15% more Damage\n"
        "Minions from Supported Skills deal 30% more Damage"
    )
    rejuvenation = details.get_details(
        "Metadata/Items/Gem/SupportGemKhatalsRejuvenation", ["SupportKhatalsRejuvenationPlayer"]
    )
    row = rejuvenation["effects"][0]
    assert row["descriptionOrigin"] == "effect_description"
    assert (
        row["statSets"][0]["stats"][0]["statId"]
        == "support_lineage_remnants_grant_cdr_buff_on_collection"
    )
    assert row["statSets"][0]["stats"][0]["value"] is None
    assert row["statSets"][0]["stats"][0]["textTemplates"]
    assert rejuvenation["mechanismCompleteness"] == "not_certified"
