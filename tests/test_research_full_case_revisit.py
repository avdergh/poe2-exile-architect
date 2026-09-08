from __future__ import annotations

from contextlib import closing
from datetime import timedelta
import json
import sqlite3

import pytest

from scripts import research_mature_builds as research
from server import paths
from server.knowledge import research_workflow
from tests.test_research_retention_workflow import CREATED, _partial_summary, _sample_code


@pytest.fixture
def parent_run(tmp_path, monkeypatch):
    runtime = tmp_path / "user-data" / "research"
    monkeypatch.setattr(paths, "research_runtime_dir", lambda: runtime)
    monkeypatch.setattr(paths, "mature_learning_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(research, "DEFAULT_INTAKE_LEDGER_PATH", tmp_path / "intake.sqlite")
    monkeypatch.setattr(research, "_now", lambda: CREATED)
    monkeypatch.setattr(research, "_identity_resolvability_hint", lambda **_: {})
    source = tmp_path / "synthetic-full-case-source.txt"
    source.write_text(_sample_code(), encoding="utf-8")
    parent = research_workflow.start_run(
        source_files=[str(source)], source_game_patch="0.5.4", expected_source_count=1, limit=1
    )
    assert parent["status"] == "queued", parent
    directory = runtime / "runs" / parent["runId"]
    db_path = directory / research.QUEUE_DB_FILENAME
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute(
            "UPDATE cases SET status='accepted', accepted_deep_record_count=1, "
            "research_quality_summary=?, write_receipt_ref='research-write:parent-synthetic', "
            "finalization_status='complete'",
            (json.dumps(_partial_summary()),),
        )
    return {
        "runtime": runtime, "report": parent, "directory": directory, "db": db_path,
        "row": research._fetch_cases(db_path)[0], "metadata": research._read_metadata(db_path),
    }


def _start_revisit(parent_run, **options):
    return research_workflow.start_run(
        re_research_run_ref=parent_run["report"]["runRef"],
        supplement_sample_ids=[parent_run["row"]["sampleId"]],
        **options,
    )


@pytest.mark.parametrize("scope", ["full_case", "supplement"])
def test_selected_revisit_retains_exact_source_authority_and_parent_deadline(
    parent_run, monkeypatch, scope
):
    monkeypatch.setattr(research, "_now", lambda: CREATED + timedelta(hours=1))
    child = _start_revisit(parent_run, re_research_scope=scope)

    assert child["status"] == "queued", child
    assert child["selectedSupplementSampleIds"] == [parent_run["row"]["sampleId"]]
    child_dir = parent_run["runtime"] / "runs" / child["runId"]
    child_db = child_dir / research.QUEUE_DB_FILENAME
    row = research._fetch_cases(child_db)[0]
    for key in ("sampleId", "sourceType", "sourceHash", "sourceHashRef", "characterRef", "league"):
        assert row[key] == parent_run["row"][key]
    assert row["supplement"] is (scope == "supplement")
    metadata = research._read_metadata(child_db)
    assert metadata["reResearchScope"] == scope
    assert metadata["supplementParentRunRef"] == parent_run["report"]["runRef"]
    assert research._queue_version_context(child_db) == research._queue_version_context(parent_run["db"])
    assert research._read_metadata(parent_run["db"])["retentionPolicy"] == (
        parent_run["metadata"]["retentionPolicy"]
    )
    assert research._fetch_cases(parent_run["db"]) == [parent_run["row"]]
    # Verify source reuse by semantic identity without exposing quarantine bytes.
    parent_raw = next((parent_run["directory"] / "quarantine").glob("*.json"))
    child_raw = next((child_dir / "quarantine").glob("*.json"))
    assert json.loads(child_raw.read_text(encoding="utf-8")) == json.loads(
        parent_raw.read_text(encoding="utf-8")
    )
    claim = research_workflow.claim_case(run_ref=child["runRef"])
    assert claim["supplement"] is (scope == "supplement")
    review = research_workflow.initialize_review(
        run_ref=child["runRef"], lease_token=claim["leaseToken"]
    )["review"]
    assert review["knowledgeScope"] == "local_user"
    assert review["artifactIdentity"]["sampleId"] == parent_run["row"]["sampleId"]


def test_default_revisit_keeps_supplement_mode(parent_run):
    child = _start_revisit(parent_run)
    child_db = parent_run["runtime"] / "runs" / child["runId"] / research.QUEUE_DB_FILENAME
    assert research._fetch_cases(child_db)[0]["supplement"] is True
    assert research._read_metadata(child_db)["reResearchScope"] == "supplement"


@pytest.mark.parametrize("missing", ["parent", "selection", "empty_selection"])
def test_full_case_revisit_requires_explicit_parent_and_nonempty_selection(parent_run, missing):
    options = {"re_research_scope": "full_case"}
    if missing != "parent":
        options["re_research_run_ref"] = parent_run["report"]["runRef"]
    if missing != "selection":
        options["supplement_sample_ids"] = [] if missing == "empty_selection" else [
            parent_run["row"]["sampleId"]
        ]
    before = set((parent_run["runtime"] / "runs").iterdir())

    result = research_workflow.start_run(**options)

    assert result["errorCode"] == "full_case_revisit_requires_selected_source_cases"
    assert set((parent_run["runtime"] / "runs").iterdir()) == before


def test_full_case_revisit_refuses_source_patch_relabelling(parent_run):
    before = set((parent_run["runtime"] / "runs").iterdir())

    with pytest.raises(ValueError, match="source_patch_is_locked"):
        _start_revisit(parent_run, re_research_scope="full_case", source_game_patch="0.5.5")

    assert set((parent_run["runtime"] / "runs").iterdir()) == before
    assert research._queue_version_context(parent_run["db"])["gamePatch"] == "0.5.4"


def test_full_case_revisit_requires_fresh_full_review_before_any_new_acceptance(parent_run):
    child = _start_revisit(parent_run, re_research_scope="full_case")
    claim = research_workflow.claim_case(run_ref=child["runRef"])
    initialized = research_workflow.initialize_review(
        run_ref=child["runRef"], lease_token=claim["leaseToken"]
    )
    review = initialized["review"]
    assert initialized["created"] is True
    assert review["deepResearchRecords"] == []
    assert review["caseCoverage"] == {
        "supports": "evidence_missing", "rotation": "evidence_missing",
        "passiveAscendancy": "evidence_missing", "gearRoles": "evidence_missing",
        "resourceDefense": "evidence_missing",
    }
    child_db = parent_run["runtime"] / "runs" / child["runId"] / research.QUEUE_DB_FILENAME
    before = research._fetch_cases(child_db)[0]
    assert before["writeReceiptRef"] == ""
    assert before["acceptedDeepRecordCount"] == 0

    with pytest.raises(ValueError, match="at least one record or candidate"):
        research_workflow.validate_review(
            run_ref=child["runRef"], lease_token=claim["leaseToken"], review=review
        )
    after = research._fetch_cases(child_db)[0]
    assert after["status"] == "claimed"
    assert after["writeReceiptRef"] == ""
    assert after["acceptedDeepRecordCount"] == 0
    assert research._fetch_cases(parent_run["db"]) == [parent_run["row"]]
