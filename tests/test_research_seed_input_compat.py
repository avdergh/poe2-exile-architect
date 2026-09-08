"""允许经校验的旧种子作为打包输入，新生成发布库仍必须是当前 schema。"""

from contextlib import closing
import json

import pytest

from scripts import build_bundle, build_research_release_seed, smoke_research_release_seed
from server import paths
from server.knowledge import mature_learning, research_claims
from test_research_claim_migration import legacy_store


def _legacy_release_seed(tmp_path):
    seed = legacy_store(tmp_path)
    with closing(mature_learning.connect(seed)) as con:
        record = con.execute("SELECT * FROM deep_research_records").fetchone()
        con.execute(
            "INSERT INTO research_build_families(knowledge_scope,build_family_key,ascendancy_key,"
            "primary_skill_key,primary_skill_keys,secondary_skill_keys,evidence_count,created_at,last_seen_at) "
            "VALUES (?,?,?,?,?,'[]',2,?,?)",
            (record["knowledge_scope"], record["build_family_key"], record["ascendancy_key"],
             "skill:LightningArrowPlayer", '["skill:LightningArrowPlayer"]',
             record["created_at"], record["last_seen_at"]),
        )
        for source in json.loads(record["source_case_refs"]):
            con.execute(
                "INSERT INTO research_source_provenance VALUES (?,?,'test',?,?)",
                (source, record["knowledge_scope"], record["created_at"], record["last_seen_at"]),
            )
            con.execute(
                "INSERT INTO research_build_family_evidence VALUES (?,?,?,?,?)",
                (record["knowledge_scope"], record["build_family_key"], source,
                 record["created_at"], record["last_seen_at"]),
            )
        con.execute("DELETE FROM meta WHERE key != 'schema_version'")
        con.executemany(
            "INSERT INTO meta(key,value) VALUES (?,?)",
            [("release_seed_kind", mature_learning.RELEASE_SEED_KIND),
             ("release_seed_version", "legacy-fixture"),
             ("release_seed_created_at", record["created_at"])],
        )
        con.commit()
    return seed


def test_validated_schema6_bundle_input_migrates_only_installed_copy_and_new_output_is_schema7(tmp_path, monkeypatch):
    seed = _legacy_release_seed(tmp_path)
    original = seed.read_bytes()
    bundle_root = tmp_path / "bundle"
    bundled_seed = bundle_root / "data" / "mature_build_learning" / "release.sqlite"
    build_bundle._copy_research_seed(seed, bundled_seed)
    assert bundled_seed.read_bytes() == original
    with pytest.raises(ValueError, match="schema version mismatch"):
        mature_learning.validate_release_seed(bundled_seed)
    mature_learning.validate_release_seed(bundled_seed, allow_legacy_schema=True)

    target = tmp_path / "user" / "memory.sqlite"
    monkeypatch.setattr(paths, "BUNDLE_ROOT", bundle_root)
    monkeypatch.setattr(mature_learning, "mature_learning_path", lambda: target)
    assert mature_learning.initialize_store() == target
    with closing(mature_learning.connect(target)) as con:
        assert mature_learning.schema_version(con) == 7
        assert con.execute("SELECT count(*) FROM deep_research_records").fetchone()[0] == 1
        assert con.execute(
            "SELECT count(*) FROM deep_research_record_evidence WHERE record_id IS NOT NULL "
            "AND binding_issue IS NULL"
        ).fetchone()[0] == 2
        research_claims.validate_storage(con)
    assert seed.read_bytes() == bundled_seed.read_bytes() == original

    published = tmp_path / "current-release.sqlite"
    build_research_release_seed.build_release_seed(source=target, output=published, release_version="current-test")
    mature_learning.validate_release_seed(published)
    with closing(mature_learning.connect(published)) as con:
        assert mature_learning.schema_version(con) == 7
    # The fixture deliberately differs from the real release corpus. Do not overwrite
    # the pinned release expectations merely to test the two read paths.
    legacy_smoke = smoke_research_release_seed.validate_release_content(bundled_seed)
    current_smoke = smoke_research_release_seed.validate_release_content(published)
    assert legacy_smoke["status"] == current_smoke["status"] == "error"
    assert legacy_smoke["actualGlobalLanes"] == current_smoke["actualGlobalLanes"] == {
        "case:source-a": 1, "case:source-b": 1,
    }
    assert legacy_smoke["expectedLaneCountsHash"] == current_smoke["expectedLaneCountsHash"]


def test_bundle_input_compatibility_still_rejects_unsafe_legacy_data(tmp_path):
    seed = _legacy_release_seed(tmp_path)
    with closing(mature_learning.connect(seed)) as con:
        con.execute("UPDATE deep_research_records SET status='quarantined'")
        con.commit()
    target = tmp_path / "bundle" / "release.sqlite"
    with pytest.raises(ValueError, match="non-creator-safe"):
        build_bundle._copy_research_seed(seed, target)
    assert not target.exists()
