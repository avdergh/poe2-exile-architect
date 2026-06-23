"""Conservative freshness gate evaluation."""

from __future__ import annotations

from collections import defaultdict

from .models import (
    ClaimDimension,
    Component,
    FreshnessDecision,
    FreshnessEvidence,
    FreshnessManifest,
    FreshnessReport,
    REQUIRED_CLAIMS,
    SourceStatus,
)


def _latest_evidence(
    manifest: FreshnessManifest,
) -> tuple[tuple[FreshnessEvidence, ...], tuple[tuple[Component, str], ...]]:
    """Keep latest records and surface ambiguous tied observations as conflicts."""

    grouped: dict[tuple[Component, str], list[FreshnessEvidence]] = defaultdict(list)
    for item in manifest.evidence:
        grouped[(item.component, item.source)].append(item)

    active: list[FreshnessEvidence] = []
    conflicts: list[tuple[Component, str]] = []
    for (component, source), records in grouped.items():
        newest_at = max(item.observed_at for item in records)
        newest = tuple(dict.fromkeys(item for item in records if item.observed_at == newest_at))
        active.extend(newest)
        if len(newest) > 1:
            conflicts.append(
                (
                    component,
                    f"{source} has conflicting tied latest records for {component.value} "
                    f"at {newest_at.isoformat()}",
                )
            )
    return tuple(active), tuple(conflicts)


def evaluate_freshness(manifest: FreshnessManifest) -> FreshnessReport:
    """Evaluate source evidence without making network calls.

    The precedence is intentionally conservative. A conflict wins over staleness, while
    unmodelled mechanics can only downgrade a manifest whose required versions are current.
    """

    required = manifest.required_components
    active_evidence, tied_conflicts = _latest_evidence(manifest)
    required_evidence = tuple(item for item in active_evidence if item.component in required)
    warnings: list[str] = []

    present = {item.component for item in required_evidence}
    missing = sorted(required - present, key=lambda component: component.value)
    unknown_reasons: list[str] = [
        f"required component {component.value} has no evidence" for component in missing
    ]

    explicit_conflicts = [reason for component, reason in tied_conflicts if component in required]
    warnings.extend(reason for component, reason in tied_conflicts if component not in required)
    explicit_conflicts.extend(
        f"{item.source} reports conflicted {item.component.value} evidence"
        for item in required_evidence
        if item.status is SourceStatus.CONFLICTED
    )

    # Claims from stale evidence still describe a known incompatibility. We report both the
    # conflict and the stale source, then let conflict precedence choose the top-level decision.
    claim_values: dict[ClaimDimension, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in required_evidence:
        if item.status is SourceStatus.UNKNOWN:
            continue
        for claim in item.claims:
            claim_values[claim.key][claim.value].append(item.source)

    claim_conflicts: list[str] = []
    for key, values in sorted(claim_values.items()):
        if len(values) <= 1:
            continue
        rendered = ", ".join(
            f"{value} ({', '.join(sorted(sources))})" for value, sources in sorted(values.items())
        )
        claim_conflicts.append(f"{key.value} claims conflict: {rendered}")

    stale_reasons = [
        f"{item.source} reports stale {item.component.value} version {item.version or 'unknown'}"
        for item in required_evidence
        if item.status is SourceStatus.STALE
    ]
    unknown_reasons.extend(
        f"{item.source} cannot verify {item.component.value}"
        for item in required_evidence
        if item.status is SourceStatus.UNKNOWN or not item.version
    )
    for item in required_evidence:
        present_claims = {claim.key for claim in item.claims}
        for missing_claim in sorted(
            REQUIRED_CLAIMS.get(item.component, frozenset()) - present_claims,
            key=lambda claim: claim.value,
        ):
            unknown_reasons.append(
                f"{item.source} is missing required claim {missing_claim.value} "
                f"for {item.component.value}"
            )

    blockers = explicit_conflicts + claim_conflicts + stale_reasons + unknown_reasons
    if explicit_conflicts or claim_conflicts:
        decision = FreshnessDecision.BLOCKED_CONFLICT
    elif stale_reasons:
        decision = FreshnessDecision.BLOCKED_STALE
    elif unknown_reasons:
        decision = FreshnessDecision.BLOCKED_UNKNOWN
    elif manifest.unmodelled_mechanics:
        warnings.extend(
            f"current data, but key mechanic is unmodelled: {mechanic}"
            for mechanic in manifest.unmodelled_mechanics
        )
        decision = FreshnessDecision.CURRENT_UNMODELLED
    else:
        decision = FreshnessDecision.VERIFIED_CURRENT

    # Optional sources are useful context, but they cannot revoke a current verdict.
    warnings.extend(
        f"optional source {item.source} is {item.status.value}"
        for item in active_evidence
        if item.component not in required and item.status is not SourceStatus.CURRENT
    )

    return FreshnessReport(
        decision=decision,
        evidence=manifest.evidence,
        active_evidence=active_evidence,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        evaluated_at=manifest.evaluated_at,
    )
