from __future__ import annotations

import pytest

from server.knowledge.research_memory import ResearchMemoryService


@pytest.mark.parametrize("profile", ["full", ""])
@pytest.mark.parametrize("record_ids", [None, ["drr-fixture"]])
def test_full_source_filter_is_rejected_before_any_memory_read(profile, record_ids):
    # No database or graph is initialized: unsupported filters must fail before a
    # broad query can return records from unrelated sources or issue a receipt.
    service = object.__new__(ResearchMemoryService)
    result = service.query_research_memory(
        "",
        response_profile=profile,
        source_case_ref=" source-hash:fixture ",
        record_ids=record_ids,
    )

    assert result["status"] == "error"
    assert result["errorCode"] == "source_case_filter_requires_compact_profile"
    assert "record_ids" in " ".join(result["caveats"])
    assert "dedupeQueryRef" not in result
