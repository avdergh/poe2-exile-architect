"""Pure, bounded retention decisions for quarantined Research material.

The caller persists a policy once when creating a run. Reading it never renews
the deadline. These helpers do not delete files or schedule background work;
callers must preserve safe diagnostics and serialize cleanup with acceptance.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
import json
from typing import Any


POLICY_VERSION = 1
DEFAULT_RETENTION_DAYS = 7
MAX_RETENTION_DAYS = 30
_POLICY_FIELDS = {"policyVersion", "createdAt", "expiresAt", "retentionDays"}


def _now(value: datetime | None) -> datetime:
    value = datetime.now(timezone.utc) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retention now must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _days(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_RETENTION_DAYS:
        raise ValueError("retention_days must be an integer between 1 and 30")
    return value


def _utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40 or "T" not in value:
        raise ValueError("invalid UTC timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("timestamp must specify UTC")
    return parsed.astimezone(timezone.utc)


def create_policy(
    *, now: datetime | None = None, retention_days: int = DEFAULT_RETENTION_DAYS
) -> dict[str, Any]:
    """Create the immutable deadline to persist alongside a new run."""
    days = _days(retention_days)
    created = _now(now)
    return {
        "policyVersion": POLICY_VERSION,
        "createdAt": created.isoformat(),
        "expiresAt": (created + timedelta(days=days)).isoformat(),
        "retentionDays": days,
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate retention policy key")
        result[key] = value
    return result


def _policy(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, Mapping):
        return None, "invalid_retention_policy"
    if "retentionPolicy" in value:
        value = value["retentionPolicy"]
        if isinstance(value, str):
            if len(value) > 2048:
                return None, "invalid_retention_policy"
            try:
                value = json.loads(value, object_pairs_hook=_unique_object)
            except (ValueError, TypeError):
                return None, "invalid_retention_policy"
    elif not _POLICY_FIELDS.intersection(value):
        return None, None
    if not isinstance(value, Mapping) or set(value) != _POLICY_FIELDS:
        return None, "invalid_retention_policy"
    try:
        if type(value["policyVersion"]) is not int or value["policyVersion"] != POLICY_VERSION:
            raise ValueError("unsupported retention policy")
        days = _days(value["retentionDays"])
        created = _utc_timestamp(value["createdAt"])
        expires = _utc_timestamp(value["expiresAt"])
        if expires != created + timedelta(days=days):
            raise ValueError("retention deadline does not match locked policy")
    except (ValueError, TypeError, OverflowError):
        return None, "invalid_retention_policy"
    return {
        "policyVersion": POLICY_VERSION,
        "createdAt": created.isoformat(),
        "expiresAt": expires.isoformat(),
        "retentionDays": days,
    }, None


def inspect_policy(
    policy_or_metadata: Mapping[str, Any] | None,
    rows: Iterable[Mapping[str, Any]] = (),
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Inspect a stored policy and active leases without changing either.

    Rows accept the queue's public camelCase keys or internal snake_case keys.
    A missing legacy policy remains unconfigured, never inferred from file ages.
    Malformed policy or claimed-lease data fails closed and is not echoed.
    """
    current = _now(now)
    policy, error = _policy(policy_or_metadata)
    status = (
        "expired" if policy and current >= _utc_timestamp(policy["expiresAt"])
        else "active" if policy else "unconfigured"
    )
    blockers = []
    if error:
        blockers.append(error)
    elif policy is None:
        blockers.append("retention_policy_unconfigured")
    elif status != "expired":
        blockers.append("retention_not_expired")
    active_leases = 0
    invalid_leases = 0
    recoveries = 0
    for row in rows:
        state = row.get("status")
        finalization = row.get("finalizationStatus", row.get("finalization_status"))
        if state == "accepting" or (
            state == "accepted" and finalization not in (None, "", "complete")
        ):
            recoveries += 1
        if state == "claimed":
            try:
                expires = _utc_timestamp(row.get("leaseExpiresAt", row.get("lease_expires_at")))
            except (ValueError, TypeError, OverflowError):
                invalid_leases += 1
            else:
                if expires > current:
                    active_leases += 1
    if recoveries:
        blockers.append("research_acceptance_recovery_required")
    if active_leases:
        blockers.append("research_active_claim_lease")
    if invalid_leases:
        blockers.append("invalid_research_claim_lease")
    return {
        "status": status,
        "policy": policy,
        "policyErrorCode": error,
        "newClaimAllowed": status != "expired" and error is None,
        "expiredCleanupAllowed": status == "expired" and not blockers,
        "blockers": blockers,
        "activeLeaseCount": active_leases,
        "invalidLeaseCount": invalid_leases,
        "acceptanceRecoveryCount": recoveries,
    }


def expired_cleanup_allowed(
    policy_or_metadata: Mapping[str, Any] | None,
    rows: Iterable[Mapping[str, Any]] = (),
    *,
    now: datetime | None = None,
) -> bool:
    """Whether expiry alone permits the caller's audited cleanup transaction."""
    return inspect_policy(policy_or_metadata, rows, now=now)["expiredCleanupAllowed"]
