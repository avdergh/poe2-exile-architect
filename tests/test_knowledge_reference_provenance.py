"""资料来源的聚焦回归；不读写运行态或 Research 数据库。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from pipeline import wiki
from pipeline.build_corpus import SCHEMA
from server.knowledge import db, mechanics


def test_wiki_text_and_revision_are_collected_in_one_response(monkeypatch):
    calls = []

    def api(params):
        calls.append(params)
        return {"query": {"pages": {"42": {
            "pageid": 42, "title": "Fixture", "extract": "Original mechanism text.",
            "revisions": [{"revid": 17, "timestamp": "2026-01-01T00:00:00Z"}],
        }}}}

    monkeypatch.setattr(wiki, "_api", api)
    result = wiki._fetch_extract("Fixture redirect")
    assert len(calls) == 1
    assert calls[0]["prop"] == "extracts|info|revisions"
    assert calls[0]["rvprop"] == "ids|timestamp"
    assert result["text"] == "Original mechanism text."
    assert result["sourceRef"] == "poe2wiki:page:42:rev:17"
    assert result["permanentUrl"].endswith("oldid=17")


@pytest.mark.parametrize("ids", [{}, {"pageId": 42}, {"pageId": True, "revisionId": 17},
                                  {"pageId": 42, "revisionId": 0}])
def test_legacy_cache_is_not_signed_with_a_current_revision(tmp_path, monkeypatch, ids):
    monkeypatch.setattr(wiki, "WIKI_RAW", tmp_path)
    monkeypatch.setattr(wiki, "_api", lambda _: pytest.fail("cache reads must not fetch revisions"))
    (tmp_path / "old.json").write_text(json.dumps({
        "title": "Old fixture", "text": "Historical text.",
        "url": "https://www.poe2wiki.net/index.php?oldid=999", **ids,
    }), encoding="utf-8")
    row = wiki.load_pages()[0]
    assert row["text"] == "Historical text."
    assert row["provenanceStatus"] == "revision_unknown"
    assert "sourceRef" not in row


@pytest.mark.parametrize("legacy", [False, True])
def test_explain_reads_new_and_old_corpus_without_migration(monkeypatch, legacy):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    if legacy:
        con.execute("CREATE TABLE mechanics(id,title,text,url,license,source)")
    else:
        con.executescript(SCHEMA)
    con.execute("INSERT INTO mechanics(id,title,text,url,license,source) VALUES(?,?,?,?,?,?)",
                ("fixture", "Fixture", "Reviewed mechanism text.", "https://www.poe2wiki.net/wiki/Fixture",
                 "CC BY-NC-SA 3.0", "PoE2 Wiki"))
    if not legacy:
        con.execute("UPDATE mechanics SET page_id=42,revision_id=17,revision_timestamp='then'")
    con.execute("PRAGMA query_only=ON")
    monkeypatch.setattr(db, "_conn", lambda: con)
    monkeypatch.setattr(db, "_has_mechanics", lambda: True)
    result = mechanics.explain("Fixture")
    assert result["wiki"]["text"] == "Reviewed mechanism text."
    if legacy:
        assert result["wiki"]["provenanceStatus"] == "revision_unknown"
        assert "sourceRef" not in result["wiki"]
        assert "lookup_mechanic" in result["note"]
    else:
        assert result["wiki"]["sourceRef"] == "poe2wiki:page:42:rev:17"
        assert result["wiki"]["matchKind"] == "local_corpus"
        assert "oldid=17" in result["attribution"]
    con.close()


def _static_runtime(tmp_path, monkeypatch, *, effect="SupportFixture", description="Supports a fixture.",
                    filename="sup_str.lua"):
    root = tmp_path / "PoB"
    data = root / "src" / "Data"
    (data / "Skills").mkdir(parents=True)
    (root / "manifest.xml").write_text('<PoBVersion><Version number="fixture-version" /></PoBVersion>')
    (data / "Gems.lua").write_text(
        'return {\n\t["Metadata/PoB/Fixture"] = {\n'
        '\t\tgameId = "Metadata/Source/Fixture",\n'
        f'\t\tgrantedEffectId = "{effect}",\n\t}},\n}}\n', encoding="utf-8")
    support = data / "Skills" / filename
    support.write_text(
        f'skills["{effect}"] = {{\n\tdescription = {json.dumps(description)},\n'
        '\tsupport = true,\n}\n', encoding="utf-8")
    monkeypatch.setattr(db.paths, "pob_runtime_pair", lambda: SimpleNamespace(src_dir=data.parent, source="fixture"))
    return support


@pytest.mark.parametrize("filename", ["sup_str.lua", "other.lua", "act_dex.lua"])
def test_get_gem_supplements_exact_effect_description_without_engine(tmp_path, monkeypatch, filename):
    support = _static_runtime(tmp_path, monkeypatch, filename=filename,
                              description='Supports "fixture" skills.\nRequires a condition.')
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("INSERT INTO gems VALUES(?,?,?,?,?,?,?,?,?,?)", (
        "Metadata/Source/Fixture", "Fixture", "r", "support", "[]", '["SupportFixture"]',
        "[]", "", "[]", "{}"))
    monkeypatch.setattr(db, "_conn", lambda: con)
    monkeypatch.setattr(db.gem_availability, "inspect_ids", lambda _: {})
    result = db.get_gem("Fixture")
    assert result["description"] == 'Supports "fixture" skills.\nRequires a condition.'
    assert result["descriptionSource"]["effectId"] == "SupportFixture"
    assert result["descriptionSource"]["pobVersion"] == "fixture-version"
    assert result["descriptionSource"]["sourceRef"] == (
        "pob-static:sha256:" + hashlib.sha256(support.read_bytes()).hexdigest())
    con.close()


@pytest.mark.parametrize("gem_id,effects,reason", [
    ("Metadata/Other/SameName", ["SupportFixture"], "gem_effect_binding_missing_or_ambiguous"),
    ("Metadata/Source/Fixture", ["DifferentEffect"], "gem_effect_binding_missing_or_ambiguous"),
    ("Metadata/Source/Fixture", ["SupportFixture", "Payload"], "ambiguous_or_missing_granted_effect"),
])
def test_description_never_guesses_identity(tmp_path, monkeypatch, gem_id, effects, reason):
    _static_runtime(tmp_path, monkeypatch)
    text, source = db._pob_support_description(gem_id, effects)
    assert text == ""
    assert source["status"] == "unavailable"
    assert source["reason"] == reason


def test_replaced_source_changes_description_and_fingerprint(tmp_path, monkeypatch):
    support = _static_runtime(tmp_path, monkeypatch)
    before = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    support.write_text(support.read_text().replace("Supports a fixture.", "Changed static description."))
    after = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert before[0] != after[0]
    assert before[1]["sourceRef"] != after[1]["sourceRef"]


def test_duplicate_effect_definitions_fail_closed(tmp_path, monkeypatch):
    support = _static_runtime(tmp_path, monkeypatch)
    (support.parent / "sup_int.lua").write_text(support.read_text())
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert not text
    assert source["reason"] == "effect_description_missing_or_ambiguous"


@pytest.mark.parametrize("invalid_fields", [
    '\tdescription = "Not a support.",\n\tsupport = false,\n',
    '\tdescription = "Unknown support flag.",\n\tsupport = readFlag(),\n',
    '\tsupport = true,\n',
    '\tdescription = readDescription(),\n\tsupport = true,\n',
    '\tdescription = "Conflicting flag.",\n\tsupport = true,\n\tsupport = false,\n',
    '\tdescription = "Known literal.",\n\tdescription = readDescription(),\n\tsupport = true,\n',
])
@pytest.mark.parametrize("valid_sibling", [False, True])
def test_invalid_effect_declaration_cannot_be_hidden(tmp_path, monkeypatch, invalid_fields,
                                                    valid_sibling):
    support = _static_runtime(tmp_path, monkeypatch)
    target = support.parent / "other.lua" if valid_sibling else support
    target.write_text('skills["SupportFixture"] = {\n' + invalid_fields + '}\n', encoding="utf-8")
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert not text
    assert source["reason"] == "effect_description_missing_or_ambiguous"


@pytest.mark.parametrize("invalid_effect_fields", [
    '\t\tgrantedEffectId = "SupportFixture",\n\t\tadditionalGrantedEffectId1 = "Payload",\n',
    '\t\tgrantedEffectId = readEffect(),\n',
    '',
    '\t\tgrantedEffectId = "SupportFixture",\n\t\tgrantedEffectId = readEffect(),\n',
])
@pytest.mark.parametrize("same_primary_id", [False, True])
def test_invalid_gem_binding_cannot_be_hidden_by_valid_sibling(
    tmp_path, monkeypatch, invalid_effect_fields, same_primary_id,
):
    support = _static_runtime(tmp_path, monkeypatch)
    gems = support.parent.parent / "Gems.lua"
    primary_id = "Metadata/PoB/Fixture" if same_primary_id else "Metadata/PoB/Other"
    extra = (f'\t["{primary_id}"] = {{\n\t\tgameId = "Metadata/Source/Fixture",\n'
             + invalid_effect_fields + '\t},\n')
    gems.write_text(gems.read_text().removesuffix('}\n') + extra + '}\n', encoding="utf-8")
    query_ids = ["Metadata/Source/Fixture"]
    if same_primary_id:
        query_ids.append(primary_id)
    for query_id in query_ids:
        text, source = db._pob_support_description(query_id, ["SupportFixture"])
        assert not text
        assert source["reason"] == "gem_effect_binding_missing_or_ambiguous"


@pytest.mark.parametrize("other_game_id", ['"Metadata/Source/Other"', 'readGameId()'])
def test_repeated_primary_id_invalidates_its_recognized_aliases(tmp_path, monkeypatch, other_game_id):
    support = _static_runtime(tmp_path, monkeypatch)
    gems = support.parent.parent / "Gems.lua"
    extra = ('\t["Metadata/PoB/Fixture"] = {\n'
             f'\t\tgameId = {other_game_id},\n\t\tgrantedEffectId = "SupportFixture",\n\t}},\n')
    gems.write_text(gems.read_text().removesuffix('}\n') + extra + '}\n', encoding="utf-8")
    for query_id in ("Metadata/PoB/Fixture", "Metadata/Source/Fixture", "Metadata/Source/Other"):
        text, source = db._pob_support_description(query_id, ["SupportFixture"])
        assert not text
        assert source["reason"] == "gem_effect_binding_missing_or_ambiguous"


@pytest.mark.parametrize("other_alias", ['readGameId()', '"Metadata/Source/Other"'])
@pytest.mark.parametrize("reverse", [False, True])
def test_invalid_alias_fields_preserve_every_observed_literal(tmp_path, monkeypatch, other_alias,
                                                            reverse):
    support = _static_runtime(tmp_path, monkeypatch)
    gems = support.parent.parent / "Gems.lua"
    aliases = ['\t\tgameId = "Metadata/Source/Fixture",\n', f'\t\tgameId = {other_alias},\n']
    if reverse:
        aliases.reverse()
    extra = ('\t["Metadata/PoB/Other"] = {\n' + ''.join(aliases)
             + '\t\tgrantedEffectId = "SupportFixture",\n\t},\n')
    gems.write_text(gems.read_text().removesuffix('}\n') + extra + '}\n', encoding="utf-8")
    for query_id in ("Metadata/Source/Fixture", "Metadata/Source/Other", "Metadata/PoB/Other"):
        text, source = db._pob_support_description(query_id, ["SupportFixture"])
        assert not text
        assert source["reason"] == "gem_effect_binding_missing_or_ambiguous"
    # The unrelated, unique primary ID remains valid; alias ambiguity is not global poisoning.
    text, source = db._pob_support_description("Metadata/PoB/Fixture", ["SupportFixture"])
    assert text == "Supports a fixture." and source["status"] == "available"


@pytest.mark.parametrize("description", ["", " \t\n ", "  Supports a fixture.\n\t"])
def test_description_requires_content_without_rewriting_it(tmp_path, monkeypatch, description):
    _static_runtime(tmp_path, monkeypatch, description=description)
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    if description.strip():
        assert text == description
        assert source["status"] == "available"
    else:
        assert not text
        assert source["reason"] == "effect_description_missing_or_ambiguous"


@pytest.mark.parametrize("close", ["", "} unknown_suffix\n"])
@pytest.mark.parametrize("valid_sibling", [False, True])
def test_incomplete_effect_does_not_authorize_description(tmp_path, monkeypatch, close, valid_sibling):
    support = _static_runtime(tmp_path, monkeypatch)
    target = support.parent / "other.lua" if valid_sibling else support
    target.write_text(support.read_text().removesuffix('}\n') + close, encoding="utf-8")
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert not text
    assert source["reason"] == "effect_description_missing_or_ambiguous"


@pytest.mark.parametrize("close", ["}\t\tend", "} end  \r\n"])
def test_generated_inline_end_keeps_description_source(tmp_path, monkeypatch, close):
    support = _static_runtime(tmp_path, monkeypatch, filename="other.lua")
    support.write_text(support.read_text().removesuffix('}\n') + close, encoding="utf-8", newline="")
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert text == "Supports a fixture." and source["status"] == "available"
    assert source["sourceRef"] == "pob-static:sha256:" + hashlib.sha256(support.read_bytes()).hexdigest()


def test_runtime_extra_effect_is_not_hidden_by_single_effect_corpus(tmp_path, monkeypatch):
    support = _static_runtime(tmp_path, monkeypatch)
    gems = support.parent.parent / "Gems.lua"
    gems.write_text(gems.read_text().replace(
        '\t\tgrantedEffectId = "SupportFixture",',
        '\t\tgrantedEffectId = "SupportFixture",\n\t\tadditionalGrantedEffectId1 = "Payload",',
    ))
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert not text
    assert source["reason"] == "gem_effect_binding_missing_or_ambiguous"


def test_unrecognized_lua_description_expression_stays_unknown(tmp_path, monkeypatch):
    support = _static_runtime(tmp_path, monkeypatch)
    support.write_text(support.read_text().replace('"Supports a fixture."', 'makeDescription()'))
    text, source = db._pob_support_description("Metadata/Source/Fixture", ["SupportFixture"])
    assert not text
    assert source["reason"] == "effect_description_missing_or_ambiguous"
