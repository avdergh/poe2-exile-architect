from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from server.knowledge import research_retention as retention


CREATED = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
EXPIRED = CREATED + timedelta(days=7)


def test_default_policy_is_locked_to_creation_and_reads_do_not_refresh_it():
    policy = retention.create_policy(now=CREATED)
    original = dict(policy)
    assert policy == {
        "policyVersion": 1,
        "createdAt": CREATED.isoformat(),
        "expiresAt": EXPIRED.isoformat(),
        "retentionDays": 7,
    }
    assert retention.inspect_policy(policy, now=EXPIRED - timedelta(seconds=1))["status"] == "active"
    result = retention.inspect_policy(policy, now=EXPIRED)
    assert result["status"] == "expired"
    assert not result["newClaimAllowed"]
    assert result["expiredCleanupAllowed"]
    assert policy == original
    assert retention.inspect_policy(policy, now=EXPIRED + timedelta(days=60))["policy"] == original


@pytest.mark.parametrize("days", [1, 7, 30])
def test_configurable_bounded_policy(days):
    policy = retention.create_policy(now=CREATED, retention_days=days)
    assert policy["expiresAt"] == (CREATED + timedelta(days=days)).isoformat()
    assert retention.inspect_policy(policy, now=CREATED)["newClaimAllowed"]


@pytest.mark.parametrize("days", [0, -1, 31, True, False, 7.0, "7", None])
def test_retention_days_cannot_be_coerced(days):
    with pytest.raises(ValueError, match="retention_days"):
        retention.create_policy(now=CREATED, retention_days=days)


@pytest.mark.parametrize("metadata", [None, {}, {"createdAt": CREATED.isoformat()}])
def test_legacy_and_incomplete_policy_are_distinct(metadata):
    result = retention.inspect_policy(metadata, now=EXPIRED)
    assert result["status"] == "unconfigured"
    assert not result["expiredCleanupAllowed"]
    assert result["newClaimAllowed"] is (metadata is None or metadata == {})


def test_metadata_created_at_does_not_configure_retention():
    # Runs already have creation metadata. It cannot become an implicit policy.
    result = retention.inspect_policy({"runId": "legacy", "created_at": "2020-01-01"}, now=EXPIRED)
    assert result["policy"] is None
    assert result["blockers"] == ["retention_policy_unconfigured"]


@pytest.mark.parametrize("encoded", [False, True])
def test_policy_may_be_stored_as_json_metadata(encoded):
    policy = retention.create_policy(now=CREATED)
    value = json.dumps(policy) if encoded else policy
    result = retention.inspect_policy({"runId": "safe-id", "retentionPolicy": value}, now=EXPIRED)
    assert result["policy"] == policy
    assert result["expiredCleanupAllowed"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("policyVersion", True), ("policyVersion", 2), ("retentionDays", True),
        ("retentionDays", "7"), ("retentionDays", 0), ("retentionDays", 31),
        ("createdAt", True), ("createdAt", "2026-09-06"),
        ("createdAt", "2026-09-06T12:00:00"),
        ("createdAt", "2026-09-06T12:00:00+08:00"),
        ("createdAt", "9999-12-31T12:00:00+00:00"),
        ("expiresAt", "2026-09-14T12:00:00+00:00"),
        ("expiresAt", "2026-09-05T12:00:00+00:00"),
    ],
)
def test_invalid_or_mutated_policy_fails_closed_without_echoing_data(field, value):
    policy = {**retention.create_policy(now=CREATED), field: value}
    result = retention.inspect_policy(policy, now=EXPIRED)
    assert result["policy"] is None
    assert result["policyErrorCode"] == "invalid_retention_policy"
    assert not result["newClaimAllowed"]
    assert not result["expiredCleanupAllowed"]


@pytest.mark.parametrize("value", [None, "", [], True, "[1]", "{", "x" * 2049])
def test_explicit_invalid_metadata_does_not_fall_back_to_legacy(value):
    result = retention.inspect_policy({"retentionPolicy": value}, now=EXPIRED)
    assert result["policyErrorCode"] == "invalid_retention_policy"
    assert not result["newClaimAllowed"]


def test_duplicate_json_policy_key_is_rejected():
    value = json.dumps(retention.create_policy(now=CREATED))
    value = value[:-1] + ', "retentionDays": 7}'
    result = retention.inspect_policy({"retentionPolicy": value}, now=EXPIRED)
    assert result["policyErrorCode"] == "invalid_retention_policy"


@pytest.mark.parametrize(
    "row,blocker",
    [
        ({"status": "accepting"}, "research_acceptance_recovery_required"),
        ({"status": "accepted", "finalizationStatus": "ledger_conflict"},
         "research_acceptance_recovery_required"),
        ({"status": "accepted", "finalization_status": "memory_not_committed"},
         "research_acceptance_recovery_required"),
        ({"status": "claimed", "leaseExpiresAt": (EXPIRED + timedelta(seconds=1)).isoformat()},
         "research_active_claim_lease"),
        ({"status": "claimed", "lease_expires_at": (EXPIRED + timedelta(days=1)).isoformat()},
         "research_active_claim_lease"),
        ({"status": "claimed"}, "invalid_research_claim_lease"),
        ({"status": "claimed", "leaseExpiresAt": True}, "invalid_research_claim_lease"),
        ({"status": "claimed", "leaseExpiresAt": "2020-01-01"}, "invalid_research_claim_lease"),
    ],
)
def test_expiry_never_interrupts_acceptance_recovery_or_live_claim(row, blocker):
    policy = retention.create_policy(now=CREATED)
    result = retention.inspect_policy(policy, [row], now=EXPIRED)
    assert result["status"] == "expired"
    assert blocker in result["blockers"]
    assert not retention.expired_cleanup_allowed(policy, [row], now=EXPIRED)


def test_expired_lease_is_releasable_but_does_not_allow_a_new_claim():
    policy = retention.create_policy(now=CREATED)
    row = {"status": "claimed", "leaseExpiresAt": EXPIRED.isoformat()}
    result = retention.inspect_policy(policy, [row], now=EXPIRED)
    assert result["expiredCleanupAllowed"]
    assert not result["newClaimAllowed"]


def test_expiry_does_not_claim_case_completion_or_mutate_cases():
    rows = [
        {"status": "queued"},
        {"status": "accepted", "finalizationStatus": "complete", "researchCompletion": "needs_followup"},
        {"status": "accepted", "researchCompletion": "unknown"},
        {"status": "acceptance_rejected"},
    ]
    original = json.loads(json.dumps(rows))
    result = retention.inspect_policy(retention.create_policy(now=CREATED), rows, now=EXPIRED)
    assert result["expiredCleanupAllowed"]
    assert "researchCompletion" not in result
    assert rows == original


def test_now_requires_timezone_awareness_and_normalizes_offsets():
    with pytest.raises(ValueError, match="timezone-aware"):
        retention.inspect_policy({}, now=datetime(2026, 9, 6))
    local = CREATED.astimezone(timezone(timedelta(hours=8)))
    assert retention.create_policy(now=local) == retention.create_policy(now=CREATED)


def test_utc_z_policy_is_normalized_without_changing_deadline():
    policy = retention.create_policy(now=CREATED)
    policy["createdAt"] = policy["createdAt"].replace("+00:00", "Z")
    policy["expiresAt"] = policy["expiresAt"].replace("+00:00", "Z")
    assert retention.inspect_policy(policy, now=EXPIRED)["expiredCleanupAllowed"]
