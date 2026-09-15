"""Read-only memory, official term fallback, source parsing."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from server.knowledge import mature_learning, research_memory
from server.study import intake, localization, storage


def test_readonly_research_query_does_not_write_dedupe_or_revision(tmp_path):
    path = tmp_path / "memory.sqlite"
    mature_learning.initialize_store(path)
    before = path.read_bytes()
    service = research_memory.ResearchMemoryService(db_path=path, read_only=True)
    result = service.query_research_memory("test", response_profile="full")
    assert result["dedupeQueryRef"] is None
    assert path.read_bytes() == before
    with service._connect() as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE study_forbidden(value TEXT)")
    assert (
        service.query_research_memory("test", response_profile="create_compact")["status"]
        != "known"
    )


def test_readonly_missing_store_is_never_initialized(tmp_path):
    path = tmp_path / "missing" / "memory.sqlite"
    service = research_memory.ResearchMemoryService(db_path=path, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        service.query_research_memory("test")
    assert not path.parent.exists()


def test_readonly_legacy_detail_preserves_content_without_claim_authority(tmp_path):
    from tests.test_research_memory import _deep_record_payload, _graph_service

    path = tmp_path / "legacy.sqlite"
    writer = research_memory.ResearchMemoryService(db_path=path, graph_service=_graph_service())
    accepted = writer.propose_deep_research_records(_deep_record_payload())
    record_id = accepted["recordIds"][0]
    with writer._connect() as con:
        # Simulate the old published seed's evidence table, preserving all other data.
        con.execute("ALTER TABLE deep_research_record_evidence RENAME TO evidence_current_fixture")
        con.execute(
            "CREATE TABLE deep_research_record_evidence AS SELECT record_id, knowledge_scope, source_case_ref, accepted_projection_hash FROM evidence_current_fixture"
        )
        con.commit()
    before = path.read_bytes()
    reader = research_memory.ResearchMemoryService(
        db_path=path, graph_service=_graph_service(), read_only=True
    )
    result = reader.query_research_memory("", detail_level="record", record_ids=[record_id])
    detail = result["deepResearchRecords"][0]
    assert detail["content"].startswith("投射物覆盖")
    assert detail["sourceClaims"] == []
    assert detail["sourceClaimsStatus"] == "legacy_binding_unavailable"
    assert result["dedupeQueryRef"] is None
    assert path.read_bytes() == before


def test_official_translation_requires_exact_identity_patch_and_provenance(tmp_path):
    catalog = tmp_path / "terms.json"
    entry = {
        "identity": "fixture:component",
        "en": "Fixture",
        "zh": "官方测试词",
        "locale": "zh-CN",
        "patches": ["0.5.5"],
        "provenance": "official_page",
        "sourceUrl": "https://www.pathofexile2.com/test-fixture",
        "sourceHash": "a" * 64,
        "reviewedAt": "2026-09-15",
    }

    def write(entries):
        catalog.write_text(
            json.dumps({"schemaVersion": "official_terms_v1", "entries": entries}), encoding="utf-8"
        )

    write([entry])
    assert (
        localization.resolve_name("Fixture", "fixture:component", "0.5.5", catalog=catalog)["zh"]
        == "官方测试词"
    )
    for name, identity, patch in [
        ("Other", "fixture:component", "0.5.5"),
        ("Fixture", "fixture:other", "0.5.5"),
        ("Fixture", "fixture:component", "unknown"),
    ]:
        assert localization.resolve_name(name, identity, patch, catalog=catalog)["zh"] == name
    for field, value in [
        ("sourceUrl", "https://poe2db.tw/cn/Fixture"),
        ("sourceHash", ""),
        ("locale", "zh-TW"),
    ]:
        write([{**entry, field: value}])
        assert (
            localization.resolve_name("Fixture", "fixture:component", "0.5.5", catalog=catalog)[
                "translationStatus"
            ]
            == "english_fallback"
        )
    write([entry, entry])
    assert (
        localization.resolve_name("Fixture", "fixture:component", "0.5.5", catalog=catalog)["zh"]
        == "Fixture"
    )


def test_normal_item_header_is_base_not_item_level():
    from server.knowledge.research_packet import _parse_item_text

    parsed = _parse_item_text(
        "Rarity: NORMAL\nWithered Wand\nItem Level: 80\n10% increased Spell Damage"
    )
    assert parsed["base"] == "Withered Wand"
    assert parsed["itemLevel"] == 80
    assert parsed["modifiers"] == ["10% increased Spell Damage"]


def test_input_rejects_ambiguous_sources_and_corrupt_xml(tmp_path):
    from server.compute.pob_code import encode_code
    from tests.test_study_workflow import SYNTHETIC_XML

    assert intake.decode_input(encode_code(SYNTHETIC_XML)) == SYNTHETIC_XML
    modern = SYNTHETIC_XML.replace("PathOfBuilding", "PathOfBuilding2")
    assert intake.decode_input(encode_code(modern)) == modern
    with pytest.raises(storage.StudyError):
        intake.decode_input("<PathOfBuilding><broken>")
    with pytest.raises(storage.StudyError):
        intake.decode_input("<!DOCTYPE x><PathOfBuilding><Build/></PathOfBuilding>")
    with pytest.raises(storage.StudyError):
        intake.read_source(None, "https://poe.ninja/poe2/builds/example")
    with pytest.raises(storage.StudyError):
        intake.read_source("relative.xml", None)
    assert not Path(tmp_path / "memory.sqlite").exists()


def test_magic_single_header_does_not_promote_metadata_to_name():
    from server.knowledge.research_packet import _parse_item_text

    item = _parse_item_text(
        "Rarity: MAGIC\nSeething Ultimate Life Flask of the Distiller\nUnique ID: fixture\nItem Level: 80\n50% reduced Amount Recovered"
    )
    assert item["name"] == "Seething Ultimate Life Flask of the Distiller"
    assert item["base"] == ""
    assert item["itemLevel"] == 80
