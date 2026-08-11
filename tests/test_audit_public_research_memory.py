from __future__ import annotations

import json

from scripts import audit_public_research_memory as audit
from server.knowledge import mature_learning


def test_empty_research_store_is_not_publishable(tmp_path):
    db_path = tmp_path / "memory.sqlite"
    mature_learning.initialize_store(db_path)

    report = audit.audit_database(db_path)

    assert report["status"] == "blocked"
    assert report["blockers"] == ["no_public_deep_research_records"]
    assert report["counts"] == {
        "deepResearchRecords": 0,
        "buildPatterns": 0,
        "globalSeedRecords": 0,
        "localUserRecords": 0,
    }
    assert report["noRawKnowledgeReturned"] is True


def test_row_audit_rejects_raw_urls_and_copyable_fields():
    assert audit._row_blockers({"content": "safe mechanism summary"}) == []
    assert "raw_url" in audit._row_blockers({"content": "https://example.com/build"})
    assert "forbidden_field" in audit._row_blockers({"rawXml": "<PathOfBuilding>"})


def test_row_audit_decodes_long_structured_json_before_copy_safety_check():
    structured = [{"stableKey": f"skill:{index}", "role": "support"} for index in range(100)]
    encoded = json.dumps(structured)

    assert len(encoded) > 1200
    assert audit._row_blockers({"component_mentions": encoded}) == []
