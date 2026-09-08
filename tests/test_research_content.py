"""Latest-season Research reuses historical content without changing its evidence."""

from copy import deepcopy
import sqlite3
import pytest

from server import main
from server.knowledge import mature_learning, patch_reviews, research_content, research_execution
from test_patch_reviews import seeded, query, review_payload


def latest_payload(payload, *, new_source=True):
    result = deepcopy(payload)
    record = result["deep_research_records"][0]
    record["game_patch"] = "0.5.5"
    if new_source:
        record["source_case_refs"] = ["case:latest-season"]
    return result


def test_latest_sample_shares_body_but_preserves_version_evidence(tmp_path):
    service, payload, old = seeded(tmp_path)
    new = service.propose_deep_research_records(latest_payload(payload))
    assert new["status"] == "accepted", new
    assert new["recordIds"] != old["recordIds"]
    con = mature_learning.connect(service.db_path)
    try:
        assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM deep_research_record_bindings").fetchone()[0] == 2
        fields = {
            row["name"] for row in con.execute("PRAGMA table_info(deep_research_record_bindings)")
        }
        assert not fields.intersection(research_content.CONTENT_FIELDS)
        assert {
            row[0] for row in con.execute("SELECT game_patch FROM deep_research_record_evidence")
        } == {"0.5.4", "0.5.5"}
    finally:
        con.close()
    family = old["buildFamilyKeys"][0]
    result = query(service, family, detail_level="record")
    assert [row["recordId"] for row in result["deepResearchRecords"]] == new["recordIds"]
    discovery = service.query_research_memory(
        "",
        detail_level="family",
        class_key="class:monk",
        game_patch="0.5.5",
        passive_tree_version="0_5",
    )["buildFamilies"][0]
    assert discovery["deepRecordCount"] == 1
    assert discovery["supportingRecordIds"] == new["recordIds"]
    assert discovery["evidenceCount"] == 2
    assert discovery["sourceGamePatches"] == ["0.5.4", "0.5.5"]
    historical = query(service, family, patch="0.5.4", detail_level="record")
    assert (
        historical["deepResearchRecords"][0]["contentRevisionRef"]
        == result["deepResearchRecords"][0]["contentRevisionRef"]
    )
    assert service.propose_deep_research_records(latest_payload(payload))["status"] == "accepted"
    with sqlite3.connect(service.db_path) as plain:
        assert (
            plain.execute("SELECT count(*) FROM deep_research_record_evidence").fetchone()[0] == 2
        )


def test_single_lane_coverage_execution_and_receipt_use_same_representative(tmp_path):
    service, payload, old = seeded(tmp_path)
    new = service.propose_deep_research_records(latest_payload(payload, new_source=False))
    family = old["buildFamilyKeys"][0]
    result = query(service, family, detail_level="record", response_profile="create_compact")
    assert len(result["deepResearchRecords"]) == 1
    assert result["familyRecordCoverage"][0]["eligibleRecordCount"] == 1
    assert result["familyRecordCoverage"][0]["excludedRecordCount"] == 0
    assert result["familyRecordCoverage"][0]["deduplicatedRecordCount"] == 1
    assert set(result["familyRecordCoverage"][0]["requiredDeepReadRecordIds"]) <= set(
        new["recordIds"]
    )
    assert {row["evidenceRef"] for row in result["familyPremiseCatalog"]} <= set(new["recordIds"])
    con = mature_learning.connect(service.db_path)
    try:
        rows = research_execution._fetch_lane_records(
            con,
            build_family_key=family,
            knowledge_scope="global_seed",
            source_case_ref="case:la-safe",
            game_patch="0.5.5",
            passive_tree_version="0_5",
        )
        assert [row["record_id"] for row in rows] == new["recordIds"]
    finally:
        con.close()
    page = service.start_retrieval_session(
        main._compact_create_research_response(result),
        response_profile="create_compact",
        run_ref=None,
        claim_ref=None,
    )
    receipt = service.read_query_receipt(page["dedupeQueryRef"])
    assert receipt is not None
    assert set(receipt["result"]["deepReadRecordIds"]) == set(new["recordIds"])


def test_changed_conditions_keep_distinct_content(tmp_path):
    service, payload, old = seeded(tmp_path)
    revised = latest_payload(payload)
    revised["deep_research_records"][0]["conditions"] = ["仅在最新补丁规定的条件满足时成立。"]
    assert service.propose_deep_research_records(revised)["status"] == "accepted"
    assert (
        len(query(service, old["buildFamilyKeys"][0], detail_level="record")["deepResearchRecords"])
        == 2
    )


def test_normal_sql_update_does_not_change_other_version_and_gcs_unreferenced_content(tmp_path):
    service, payload, old = seeded(tmp_path)
    new = service.propose_deep_research_records(latest_payload(payload))
    # Plain sqlite clients have no registered custom SQL functions.
    with sqlite3.connect(service.db_path) as con:
        con.execute(
            "UPDATE deep_research_records SET content=? WHERE record_id=?",
            ("最新版本的修订结论。", new["recordIds"][0]),
        )
        assert (
            con.execute(
                "SELECT content FROM deep_research_records WHERE record_id=?",
                (old["recordIds"][0],),
            ).fetchone()[0]
            == payload["deep_research_records"][0]["content"]
        )
        assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 2
        con.execute("DELETE FROM deep_research_records WHERE record_id=?", (new["recordIds"][0],))
        assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 1
        con.execute("DELETE FROM deep_research_records")
        assert con.execute("SELECT count(*) FROM research_content_revisions").fetchone()[0] == 0


def test_migration_preserves_every_legacy_field_and_patch_review(tmp_path):
    service, _, accepted = seeded(tmp_path / "source")
    source = mature_learning.connect(service.db_path)
    row = dict(source.execute("SELECT * FROM deep_research_records").fetchone())
    payload = review_payload(service)
    source.close()
    path = tmp_path / "legacy.sqlite"
    con = mature_learning.connect(path)
    con.executescript(mature_learning._SCHEMA_SQL)
    con.executescript(mature_learning._PHASE4_SCHEMA_SQL)
    mature_learning._migrate_phase4_additive_schema(con)
    mature_learning._migrate_research_memory_v5(con)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('schema_version','5')")
    con.execute(
        f"INSERT INTO deep_research_records({','.join(row)}) VALUES ({','.join('?' for _ in row)})",
        tuple(row.values()),
    )
    patch_reviews.submit(con, payload)
    before = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
    revision = int(
        con.execute("SELECT value FROM meta WHERE key='research_memory_revision'").fetchone()[0]
    )
    con.commit()
    con.close()
    mature_learning.initialize_store(path)

    con = mature_learning.connect(path)
    try:
        after = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
        assert after == before
        assert patch_reviews.fingerprint(after) == payload["source_fingerprint"]
        assert patch_reviews.applicability(con, after, "0.5.5")["adoptionAllowed"] is False
        assert (
            con.execute(
                "SELECT research_patch_adoptable(record_id,projection_hash,'0.5.5') FROM deep_research_records"
            ).fetchone()[0]
            == 0
        )
        assert (
            int(
                con.execute(
                    "SELECT value FROM meta WHERE key='research_memory_revision'"
                ).fetchone()[0]
            )
            > revision
        )
        assert after["record_id"] == accepted["recordIds"][0]
        research_content.validate_storage(con)
    finally:
        con.close()
    mature_learning.initialize_store(path)


@pytest.mark.parametrize(
    "missing",
    ["research_content_gc_delete", "research_content_gc_update", "idx_research_content_binding"],
)
def test_missing_gc_or_content_index_is_rejected(tmp_path, missing):
    service, _, _ = seeded(tmp_path)
    with sqlite3.connect(service.db_path) as con:
        con.execute(f"DROP {'INDEX' if missing.startswith('idx_') else 'TRIGGER'} {missing}")
    with pytest.raises(mature_learning.SchemaVersionError):
        mature_learning.initialize_store(service.db_path)


def test_raw_content_hash_matches_exact_storage_comparison(tmp_path):
    service, payload, old = seeded(tmp_path)
    new = service.propose_deep_research_records(latest_payload(payload, new_source=False))
    with sqlite3.connect(service.db_path) as con:
        con.execute(
            "UPDATE deep_research_records SET typed_payload=' { } ' WHERE record_id=?",
            (new["recordIds"][0],),
        )
        con.execute(
            "UPDATE deep_research_records SET typed_payload='{}' WHERE record_id=?",
            (old["recordIds"][0],),
        )
    rows = query(service, old["buildFamilyKeys"][0], detail_level="record")["deepResearchRecords"]
    assert len(rows) == 2
    assert len({row["contentRevisionRef"] for row in rows}) == 2


def test_existing_schema_backup_is_preserved_and_fresh_snapshot_is_created(tmp_path):
    service, _, _ = seeded(tmp_path)
    con = mature_learning.connect(service.db_path)
    try:
        mature_learning._backup_before_schema_upgrade(con, path=service.db_path, existing=5)
        original = service.db_path.with_name(service.db_path.name + ".pre-schema-5.sqlite")
        original_bytes = original.read_bytes()
        con.execute("INSERT INTO meta(key,value) VALUES ('new_user_state','preserved')")
        con.commit()
        mature_learning._backup_before_schema_upgrade(con, path=service.db_path, existing=5)
        fresh = list(service.db_path.parent.glob(service.db_path.name + '.pre-schema-5-*.sqlite'))
        assert len(fresh) == 1
        assert original.read_bytes() == original_bytes
        with sqlite3.connect(fresh[0]) as backup:
            assert backup.execute("SELECT value FROM meta WHERE key='new_user_state'").fetchone()[0] == 'preserved'
    finally:
        con.close()
