"""所有兼容发布输入共享安全门槛；旧 schema 标记不能授予发布豁免。"""

from contextlib import closing
import sqlite3

import pytest

from scripts import build_bundle
from server.knowledge import mature_learning, research_claims
from test_research_seed_input_compat import _legacy_release_seed


def _release_seed(tmp_path, schema):
    seed = _legacy_release_seed(tmp_path)
    with closing(mature_learning.connect(seed)) as con:
        if schema in {4, 5}:
            # v4/v5's row storage can be accepted only when all safety facts already
            # exist. This conversion does not add scopes, evidence or projection hashes.
            record = dict(con.execute("SELECT * FROM deep_research_records").fetchone())
            con.execute("DROP VIEW deep_research_records")
            con.execute("DROP TABLE deep_research_record_bindings")
            con.execute("DROP TABLE research_content_revisions")
            con.executescript(mature_learning._PHASE4_SCHEMA_SQL)
            columns = ",".join(record)
            con.execute(
                f"INSERT INTO deep_research_records({columns}) VALUES ({','.join('?' for _ in record)})",
                tuple(record.values()),
            )
        elif schema == 7:
            research_claims.migrate(con, invalidate_receipts=False)
            con.execute("DELETE FROM meta WHERE key NOT IN ('schema_version', 'release_seed_kind', "
                        "'release_seed_version', 'release_seed_created_at')")
        con.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(schema),))
        con.commit()
    return seed


def _change(seed, sql, params=()):
    with closing(sqlite3.connect(seed)) as con:
        con.execute(sql, params)
        con.commit()


def _assert_rejected(seed, tmp_path, message=None):
    original = seed.read_bytes()
    target = tmp_path / "bundle" / "release.sqlite"
    with pytest.raises(ValueError, match=message):
        build_bundle._copy_research_seed(seed, target)
    assert not target.exists()
    assert seed.read_bytes() == original


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
def test_complete_legacy_and_current_safety_contracts_are_read_only_bundle_inputs(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    original = seed.read_bytes()
    target = tmp_path / "bundle" / "release.sqlite"
    build_bundle._copy_research_seed(seed, target)
    assert seed.read_bytes() == target.read_bytes() == original
    if schema != 7:
        with pytest.raises(ValueError, match="schema version mismatch"):
            mature_learning.validate_release_seed(seed)


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
@pytest.mark.parametrize("empty", [False, True])
def test_operational_source_rows_never_ship_even_without_knowledge_records(tmp_path, schema, empty):
    seed = _release_seed(tmp_path, schema)
    if empty:
        for table in ("deep_research_record_evidence", "deep_research_records",
                      "research_build_family_evidence", "research_build_families",
                      "research_source_provenance"):
            _change(seed, f"DELETE FROM {table}")
    _change(seed, "INSERT INTO source_groups VALUES (?,?,?,?,?,?,?,?,?)",
            ("group:test", "hash", "pobb_in", "private source", "league", "0.5.4", "0_5", "now", "now"))
    _assert_rejected(seed, tmp_path, "forbidden table rows")


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
@pytest.mark.parametrize("assignment", ["knowledge_scope='local_user'", "knowledge_scope='eval_ephemeral'",
                                        "copy_safety_state='needs_review'", "status='quarantined'",
                                        "visibility='evaluator_only', split='eval_holdout'"])
def test_seed_version_does_not_exempt_non_creator_safe_records(tmp_path, schema, assignment):
    seed = _release_seed(tmp_path, schema)
    _change(seed, f"UPDATE deep_research_records SET {assignment}")
    _assert_rejected(seed, tmp_path, "non-creator-safe")


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
def test_unknown_private_table_is_not_an_unchecked_publication_channel(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    _change(seed, 'CREATE TABLE "private-source-copy"(payload TEXT)')
    _change(seed, 'INSERT INTO "private-source-copy" VALUES (?)', ("private account data",))
    _assert_rejected(seed, tmp_path, "unsupported data tables")


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
def test_runtime_metadata_is_not_exempted_by_old_release_kind(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    _change(seed, "INSERT INTO meta VALUES ('local_marker', 'private data')")
    _assert_rejected(seed, tmp_path, "runtime/backfill metadata")


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
@pytest.mark.parametrize("scope", ["local_user", "eval_ephemeral"])
def test_source_provenance_cannot_borrow_global_authority(tmp_path, schema, scope):
    seed = _release_seed(tmp_path, schema)
    _change(seed, "UPDATE research_source_provenance SET knowledge_scope=?", (scope,))
    _assert_rejected(seed, tmp_path)


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
def test_missing_or_unscoped_source_provenance_is_never_inferred(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    with closing(sqlite3.connect(seed)) as con:
        con.executescript("ALTER TABLE research_source_provenance RENAME TO old_provenance; "
                          "CREATE TABLE research_source_provenance(source_case_ref TEXT PRIMARY KEY, "
                          "knowledge_scope TEXT, provenance TEXT, created_at TEXT, last_seen_at TEXT); "
                          "INSERT INTO research_source_provenance SELECT * FROM old_provenance; "
                          "DROP TABLE old_provenance;")
    _assert_rejected(seed, tmp_path, "not scope-separated")


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
def test_scope_separated_provenance_still_requires_public_rows_and_safe_text(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    _change(seed, "UPDATE research_source_provenance SET provenance=?", ("https://pobb.in/private",))
    _assert_rejected(seed, tmp_path, "forbidden text marker")


@pytest.mark.parametrize("schema", [4, 5])
def test_empty_old_family_table_without_scope_is_not_a_safety_shortcut(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    for table in ("deep_research_record_evidence", "deep_research_records",
                  "research_build_family_evidence", "research_build_families"):
        _change(seed, f"DELETE FROM {table}")
    _change(seed, "DROP TABLE research_build_families")
    _change(seed, "CREATE TABLE research_build_families(build_family_key TEXT PRIMARY KEY)")
    _assert_rejected(seed, tmp_path, "safety contract is incomplete")


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
@pytest.mark.parametrize("assignment", ["accepted_projection_hash=NULL", "source_state_scope='unknown'",
                                        "game_patch='0.5.5'", "passive_tree_version='0_6'",
                                        "pob_version_or_commit='other'"])
def test_one_valid_lane_does_not_hide_another_unproven_source_claim(tmp_path, schema, assignment):
    seed = _release_seed(tmp_path, schema)
    _change(seed, f"UPDATE deep_research_record_evidence SET {assignment} WHERE source_case_ref='case:source-a'")
    _assert_rejected(seed, tmp_path)


@pytest.mark.parametrize("schema", [4, 5, 6, 7])
def test_missing_one_source_provenance_cannot_borrow_another_sources_lane(tmp_path, schema):
    seed = _release_seed(tmp_path, schema)
    _change(seed, "DELETE FROM research_source_provenance WHERE source_case_ref='case:source-a'")
    _assert_rejected(seed, tmp_path, "without global provenance")


@pytest.mark.parametrize("schema", [4, 5])
def test_legacy_version_label_does_not_hide_unbound_shared_content(tmp_path, schema):
    seed = _legacy_release_seed(tmp_path)
    _change(seed, "UPDATE meta SET value=? WHERE key='schema_version'", (str(schema),))
    _change(seed, "INSERT INTO research_content_revisions SELECT revision_id+100, title, summary, content, "
            "component_keys, component_mentions, conditions, failure_conditions, typed_payload "
            "FROM research_content_revisions LIMIT 1")
    _assert_rejected(seed, tmp_path, "research_content_orphan_revision")


def test_changed_source_during_copy_is_rejected_before_replacing_destination(tmp_path, monkeypatch):
    seed = _release_seed(tmp_path, 6)
    target = tmp_path / "bundle" / "release.sqlite"
    target.parent.mkdir()
    target.write_bytes(b"previous validated destination")
    real_copy = build_bundle._copy

    def copy_changed_input(source, destination):
        _change(source, "UPDATE deep_research_records SET copy_safety_state='needs_review'")
        real_copy(source, destination)

    monkeypatch.setattr(build_bundle, "_copy", copy_changed_input)
    with pytest.raises(ValueError, match="non-creator-safe"):
        build_bundle._copy_research_seed(seed, target)
    assert target.read_bytes() == b"previous validated destination"
    assert list(target.parent.iterdir()) == [target]
