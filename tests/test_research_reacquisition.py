from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from threading import Barrier

import pytest

from server.knowledge import research_intake_ledger, research_reacquisition as reacquisition


def _binding(**changes):
    return {
        "league": "runesofaldur", "character_ref": "character-hash:" + "a" * 16,
        "parent_run_ref": "research-run:parent", "sample_id": "case:original-001",
        "origin_fingerprint": "b" * 64, "request_id": "request-001",
        "new_run_ref": "research-run:child-001", "origin_source_hash": "c" * 64,
        "origin_patch": "0.5.5", **changes,
    }


def _queue(db, **changes):
    return reacquisition.mark_queued(
        db, **{
            "request_id": "request-001", "new_run_ref": "research-run:child-001",
            "source_hash": "c" * 64, "source_patch": "0.5.5",
            "character_ref": "character-hash:" + "a" * 16, "league": "runesofaldur",
            **changes,
        }
    )


def test_two_concurrent_requests_cannot_own_the_same_character(tmp_path):
    db = tmp_path / "reacquisition.sqlite"
    barrier = Barrier(2)

    def attempt(number):
        barrier.wait()
        try:
            return reacquisition.reserve(db, **_binding(
                request_id=f"request-{number}", new_run_ref=f"research-run:child-{number}"
            ))
        except reacquisition.ReacquisitionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (1, 2)))
    assert outcomes.count("conflict") == 1
    assert [item["status"] for item in outcomes if isinstance(item, dict)] == ["reserved"]
    assert len(reacquisition.list_requests(db, parent_run_ref="research-run:parent")) == 1


def test_identical_request_is_idempotent_without_duplicate_events(tmp_path):
    db = tmp_path / "reacquisition.sqlite"
    first = reacquisition.reserve(db, **_binding())
    repeat = reacquisition.reserve(db, **_binding())
    assert first["status"] == "reserved" and first["idempotent"] is False
    assert repeat == {**first, "idempotent": True}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reservation_events").fetchone()[0] == 1


@pytest.mark.parametrize("changes", [
    {"origin_fingerprint": "d" * 64}, {"sample_id": "case:different"},
    {"parent_run_ref": "research-run:another"}, {"new_run_ref": "research-run:another"},
    {"character_ref": "character-hash:" + "d" * 16}, {"league": "standard"},
    {"origin_source_hash": "d" * 64}, {"origin_patch": "0.5.4"},
])
def test_request_id_cannot_be_rebound(tmp_path, changes):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    with pytest.raises(reacquisition.ReacquisitionConflict):
        reacquisition.reserve(db, **_binding(**changes))


def test_explicit_failed_release_retains_history_and_permits_new_request(tmp_path):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    released = reacquisition.release(db, request_id="request-001", new_run_ref="research-run:child-001",
                                     reason_code="target_not_found")
    assert released["status"] == "failed"
    assert reacquisition.reserve(db, **_binding())["status"] == "failed"
    with pytest.raises(reacquisition.ReacquisitionConflict):
        _queue(db)
    second = reacquisition.reserve(db, **_binding(request_id="request-002", new_run_ref="research-run:child-002"))
    assert second["status"] == "reserved"
    assert [row["status"] for row in reacquisition.list_requests(db, parent_run_ref="research-run:parent")] == ["failed", "reserved"]
    with sqlite3.connect(db) as conn:
        assert [row[0] for row in conn.execute("SELECT status FROM reservation_events ORDER BY event_id")] == ["reserved", "failed", "reserved"]


def test_age_never_automatically_releases_a_reservation(tmp_path):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE reservations SET created_at='2001-01-01',updated_at='2001-01-01'")
    with pytest.raises(reacquisition.ReacquisitionConflict):
        reacquisition.reserve(db, **_binding(request_id="request-002", new_run_ref="research-run:child-002"))


@pytest.mark.parametrize(("hash_value", "patch", "relation"), [
    ("c" * 64, "0.5.5", "exact_source"),
    ("d" * 64, "0.5.5", "successor_snapshot"),
    ("c" * 64, "0.5.6", "successor_snapshot"),
])
def test_collected_snapshot_identity_preserves_origin_version(tmp_path, hash_value, patch, relation):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    queued = _queue(db, source_hash=hash_value, source_patch=patch)
    assert queued["sourceRelation"] == relation
    assert queued["originPatch"] == "0.5.5"
    assert queued["sourcePatch"] == patch
    assert queued["originSourceHash"] == "c" * 64
    assert queued["sourceHash"] == hash_value
    assert _queue(db, source_hash=hash_value, source_patch=patch)["idempotent"] is True
    finished = reacquisition.finalize(db, request_id="request-001", new_run_ref="research-run:child-001")
    assert finished["status"] == "completed"
    assert reacquisition.finalize(db, request_id="request-001", new_run_ref="research-run:child-001")["idempotent"] is True
    # Child completion records no authority to close parent diagnostic gaps.
    assert "researchComplete" not in finished and "closedGapIds" not in finished


@pytest.mark.parametrize("changes", [
    {"character_ref": "character-hash:" + "e" * 16}, {"league": "standard"},
    {"new_run_ref": "research-run:other"}, {"request_id": "other"},
])
def test_collection_cannot_bind_another_character_or_run(tmp_path, changes):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    with pytest.raises(reacquisition.ReacquisitionConflict):
        _queue(db, **changes)
    assert reacquisition.get_request(db, request_id="request-001")["status"] == "reserved"


def test_bound_snapshot_and_terminal_reason_are_immutable(tmp_path):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    with pytest.raises(reacquisition.ReacquisitionConflict):
        reacquisition.finalize(db, request_id="request-001", new_run_ref="research-run:child-001")
    _queue(db)
    with pytest.raises(reacquisition.ReacquisitionConflict):
        _queue(db, source_hash="e" * 64)
    args = dict(request_id="request-001", new_run_ref="research-run:child-001", reason_code="child_abandoned")
    reacquisition.release(db, **args)
    assert reacquisition.release(db, **args)["idempotent"] is True
    with pytest.raises(reacquisition.ReacquisitionConflict):
        reacquisition.release(db, **{**args, "reason_code": "different_reason"})
    with pytest.raises(reacquisition.ReacquisitionConflict):
        reacquisition.finalize(db, request_id="request-001", new_run_ref="research-run:child-001")


def test_reacquisition_never_rewrites_accepted_intake_history(tmp_path):
    intake = tmp_path / "research_intake.sqlite"
    identity = _binding()
    research_intake_ledger.record_case(intake, league=identity["league"], character_ref=identity["character_ref"],
                                      source_hash=identity["origin_source_hash"], sample_id=identity["sample_id"])
    research_intake_ledger.mark_accepted(intake, league=identity["league"], character_ref=identity["character_ref"])
    before = intake.read_bytes()
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **identity)
    _queue(db, source_hash="f" * 64)
    reacquisition.finalize(db, request_id="request-001", new_run_ref="research-run:child-001")
    assert intake.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"character_ref": "raw-account/raw-character"}, {"origin_source_hash": "eNrtCODE"},
    {"origin_patch": "unknown"}, {"new_run_ref": "https://poe.ninja/character/account"},
    {"origin_fingerprint": "<Build level=95>"}, {"sample_id": "raw character name"},
    {"request_id": "../outside"}, {"league": "https://poe.ninja/poe2/builds/standard"},
    {"league": "current"}, {"league": "RunesOfAldur"},
    {"new_run_ref": "research-run:parent"},
])
def test_only_safe_typed_bindings_can_be_persisted(tmp_path, changes):
    db = tmp_path / "reacquisition.sqlite"
    with pytest.raises(ValueError):
        reacquisition.reserve(db, **_binding(**changes))
    assert not db.exists()


def test_missing_queries_do_not_create_a_database(tmp_path):
    db = tmp_path / "missing.sqlite"
    assert reacquisition.get_request(db, request_id="request-001") is None
    assert reacquisition.list_requests(db, parent_run_ref="research-run:parent") == []
    assert not db.exists()


def test_missing_transition_does_not_create_a_database(tmp_path):
    db = tmp_path / "missing.sqlite"
    with pytest.raises(reacquisition.ReacquisitionConflict):
        _queue(db)
    with pytest.raises(reacquisition.ReacquisitionConflict):
        reacquisition.release(db, request_id="request-001", new_run_ref="research-run:child-001",
                              reason_code="target_not_found")
    assert not db.exists()


def test_safe_projection_contains_only_refs_versions_and_diagnostics(tmp_path):
    db = tmp_path / "reacquisition.sqlite"
    reacquisition.reserve(db, **_binding())
    _queue(db)
    serialized = json.dumps(reacquisition.list_requests(db, parent_run_ref="research-run:parent", sample_id="case:original-001"))
    for marker in ("rawXml", "rawImportCode", "account", "poe.ninja/", "<Build", "transient"):
        assert marker not in serialized
