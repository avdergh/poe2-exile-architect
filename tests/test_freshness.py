from __future__ import annotations

from datetime import UTC, datetime

import pytest

from server.freshness import (
    ClaimDimension,
    Component,
    FreshnessDecision,
    FreshnessEvidence,
    FreshnessManifest,
    SourceStatus,
    VersionClaim,
    evaluate_freshness,
)


NOW = datetime(2026, 6, 23, 8, 0, tzinfo=UTC)


def evidence(
    component: Component,
    source: str,
    *,
    version: str,
    status: SourceStatus = SourceStatus.CURRENT,
    claims: tuple[VersionClaim, ...] = (),
) -> FreshnessEvidence:
    return FreshnessEvidence(
        component=component,
        source=source,
        source_url=f"https://example.test/{source}",
        observed_at=NOW,
        version=version,
        status=status,
        claims=claims,
    )


def current_manifest(*extra: FreshnessEvidence) -> FreshnessManifest:
    patch = VersionClaim("game_patch", "0.5.3")
    league = VersionClaim("league", "Runes of Aldur")
    tree = VersionClaim("passive_tree", "0_5")
    records = (
        evidence(Component.GAME_PATCH, "ggg-patch", version="0.5.3", claims=(patch,)),
        evidence(Component.LEAGUE, "ggg-league", version="Runes of Aldur", claims=(league,)),
        evidence(Component.PASSIVE_TREE, "ggg-tree", version="0_5", claims=(patch, tree)),
        evidence(
            Component.POB_ENGINE,
            "pob-release",
            version="0.21.1",
            claims=(patch, tree),
        ),
        evidence(
            Component.POB_DATA,
            "pob-data",
            version="pob-commit",
            claims=(patch, tree),
        ),
        evidence(
            Component.CORPUS,
            "release-corpus",
            version="v0.1.39",
            claims=(patch, tree),
        ),
        evidence(
            Component.META_SNAPSHOT,
            "ninja",
            version="2026-06-22",
            claims=(league, tree),
        ),
        *extra,
    )
    return FreshnessManifest(evidence=records, evaluated_at=NOW)


def replace_component(
    manifest: FreshnessManifest,
    replacement: FreshnessEvidence | None,
    component: Component,
) -> FreshnessManifest:
    records = tuple(item for item in manifest.evidence if item.component != component)
    if replacement is not None:
        records += (replacement,)
    return FreshnessManifest(
        evidence=records,
        evaluated_at=manifest.evaluated_at,
        unmodelled_mechanics=manifest.unmodelled_mechanics,
    )


def test_all_required_sources_current_and_compatible():
    report = evaluate_freshness(current_manifest())

    assert report.decision is FreshnessDecision.VERIFIED_CURRENT
    assert report.blockers == ()


def test_stale_pob_blocks_current_verification():
    manifest = current_manifest()
    stale = evidence(
        Component.POB_ENGINE,
        "pob-release",
        version="0.20.0",
        status=SourceStatus.STALE,
        claims=(
            VersionClaim("game_patch", "0.5.3"),
            VersionClaim("passive_tree", "0_5"),
        ),
    )

    report = evaluate_freshness(replace_component(manifest, stale, Component.POB_ENGINE))

    assert report.decision is FreshnessDecision.BLOCKED_STALE
    assert any("pob-release" in reason for reason in report.blockers)


def test_conflict_has_priority_but_report_keeps_stale_blocker():
    manifest = current_manifest()
    stale_conflict = evidence(
        Component.POB_ENGINE,
        "pob-release",
        version="0.20.0",
        status=SourceStatus.STALE,
        claims=(
            VersionClaim("game_patch", "0.5.2"),
            VersionClaim("passive_tree", "0_5"),
        ),
    )

    report = evaluate_freshness(replace_component(manifest, stale_conflict, Component.POB_ENGINE))

    assert report.decision is FreshnessDecision.BLOCKED_CONFLICT
    assert any("claims conflict" in reason for reason in report.blockers)
    assert any("reports stale" in reason for reason in report.blockers)


def test_cross_source_tree_claim_conflict_blocks_verification():
    manifest = current_manifest()
    incompatible_ninja = evidence(
        Component.META_SNAPSHOT,
        "ninja",
        version="2026-06-22",
        claims=(
            VersionClaim("league", "Runes of Aldur"),
            VersionClaim("passive_tree", "0_4"),
        ),
    )

    report = evaluate_freshness(
        replace_component(manifest, incompatible_ninja, Component.META_SNAPSHOT)
    )

    assert report.decision is FreshnessDecision.BLOCKED_CONFLICT
    assert any("passive_tree" in reason for reason in report.blockers)


def test_missing_required_game_patch_is_unknown():
    manifest = replace_component(current_manifest(), None, Component.GAME_PATCH)

    report = evaluate_freshness(manifest)

    assert report.decision is FreshnessDecision.BLOCKED_UNKNOWN
    assert any("game_patch" in reason for reason in report.blockers)


def test_current_but_unmodelled_mechanic_is_not_verified():
    base = current_manifest()
    manifest = FreshnessManifest(
        evidence=base.evidence,
        evaluated_at=base.evaluated_at,
        unmodelled_mechanics=("new threshold conversion",),
    )

    report = evaluate_freshness(manifest)

    assert report.decision is FreshnessDecision.CURRENT_UNMODELLED
    assert "new threshold conversion" in report.warnings[0]


def test_optional_stale_source_does_not_block():
    wiki = evidence(
        Component.WIKI,
        "poe2-wiki",
        version="old-revision",
        status=SourceStatus.STALE,
    )

    report = evaluate_freshness(current_manifest(wiki))

    assert report.decision is FreshnessDecision.VERIFIED_CURRENT
    assert any("poe2-wiki" in warning for warning in report.warnings)


def test_missing_required_compatibility_claim_is_unknown():
    patch_without_claim = evidence(
        Component.GAME_PATCH,
        "ggg-patch",
        version="0.5.3",
    )
    manifest = replace_component(
        current_manifest(),
        patch_without_claim,
        Component.GAME_PATCH,
    )

    report = evaluate_freshness(manifest)

    assert report.decision is FreshnessDecision.BLOCKED_UNKNOWN
    assert any("missing required claim game_patch" in reason for reason in report.blockers)


def test_claims_are_normalized_and_restricted_to_known_dimensions():
    claim = VersionClaim(" game_patch ", " 0.5.3 ")

    assert claim.key is ClaimDimension.GAME_PATCH
    assert claim.value == "0.5.3"
    assert VersionClaim("game_patch", "v0.5.3").value == "0.5.3"
    assert VersionClaim("passive_tree", "0.5").value == "0_5"
    assert VersionClaim("league", "  Runes   of ALDUR ").value == "runes-of-aldur"
    assert VersionClaim("league", "runes-of-aldur").value == "runes-of-aldur"
    with pytest.raises(ValueError, match="claim dimension"):
        VersionClaim("generic_version", "1")
    with pytest.raises(ValueError, match="non-empty"):
        VersionClaim("game_patch", "v")


def test_evidence_rejects_non_enum_component_or_status():
    with pytest.raises(TypeError, match="component"):
        FreshnessEvidence(
            component="game_patch",  # type: ignore[arg-type]
            source="invalid",
            source_url="https://example.test/invalid",
            observed_at=NOW,
            version="0.5.3",
            status=SourceStatus.CURRENT,
        )
    with pytest.raises(TypeError, match="status"):
        FreshnessEvidence(
            component=Component.GAME_PATCH,
            source="invalid",
            source_url="https://example.test/invalid",
            observed_at=NOW,
            version="0.5.3",
            status="current",  # type: ignore[arg-type]
        )


def test_manifest_rejects_empty_required_component_set():
    with pytest.raises(ValueError, match="required_components"):
        FreshnessManifest(
            evidence=(),
            evaluated_at=NOW,
            required_components=frozenset(),
        )


def test_manifest_freezes_mutable_inputs_and_validates_unmodelled_mechanics():
    required = set(current_manifest().required_components)
    mechanics = ["threshold conversion"]
    manifest = FreshnessManifest(
        evidence=current_manifest().evidence,
        evaluated_at=NOW,
        required_components=required,  # type: ignore[arg-type]
        unmodelled_mechanics=mechanics,  # type: ignore[arg-type]
    )
    required.remove(Component.GAME_PATCH)
    mechanics.append("late mutation")

    assert Component.GAME_PATCH in manifest.required_components
    assert manifest.unmodelled_mechanics == ("threshold conversion",)

    with pytest.raises(TypeError, match="unmodelled_mechanics"):
        FreshnessManifest(
            evidence=current_manifest().evidence,
            evaluated_at=NOW,
            unmodelled_mechanics="not-a-sequence-of-mechanics",  # type: ignore[arg-type]
        )


def test_latest_record_from_same_source_replaces_history():
    old = evidence(
        Component.POB_ENGINE,
        "pob-release",
        version="0.20.0",
        status=SourceStatus.STALE,
        claims=(
            VersionClaim("game_patch", "0.5.2"),
            VersionClaim("passive_tree", "0_4"),
        ),
    )
    current = next(
        item for item in current_manifest().evidence if item.component is Component.POB_ENGINE
    )
    newer = FreshnessEvidence(
        component=current.component,
        source=current.source,
        source_url=current.source_url,
        observed_at=NOW.replace(hour=9),
        version=current.version,
        status=current.status,
        claims=current.claims,
    )
    manifest = current_manifest(old, newer)

    report = evaluate_freshness(manifest)

    assert report.decision is FreshnessDecision.VERIFIED_CURRENT
    assert (
        len(
            [
                item
                for item in report.active_evidence
                if item.component is Component.POB_ENGINE and item.source == "pob-release"
            ]
        )
        == 1
    )
    assert len(report.evidence) == len(manifest.evidence)


def test_blank_version_is_treated_as_unknown():
    blank = evidence(
        Component.GAME_PATCH,
        "ggg-patch",
        version="   ",
        claims=(VersionClaim("game_patch", "0.5.3"),),
    )

    report = evaluate_freshness(replace_component(current_manifest(), blank, Component.GAME_PATCH))

    assert report.decision is FreshnessDecision.BLOCKED_UNKNOWN
    assert any("cannot verify game_patch" in reason for reason in report.blockers)


def test_conflicting_records_with_same_latest_timestamp_are_blocked():
    base = current_manifest()
    tied_stale = evidence(
        Component.POB_ENGINE,
        "pob-release",
        version="0.20.0",
        status=SourceStatus.STALE,
        claims=(
            VersionClaim("game_patch", "0.5.2"),
            VersionClaim("passive_tree", "0_4"),
        ),
    )
    manifest = FreshnessManifest(
        evidence=base.evidence + (tied_stale,),
        evaluated_at=NOW,
    )

    report = evaluate_freshness(manifest)

    assert report.decision is FreshnessDecision.BLOCKED_CONFLICT
    assert any("tied latest records" in reason for reason in report.blockers)


def test_optional_tied_records_warn_without_blocking():
    wiki_current = evidence(
        Component.WIKI,
        "poe2-wiki",
        version="revision-a",
    )
    wiki_stale = evidence(
        Component.WIKI,
        "poe2-wiki",
        version="revision-b",
        status=SourceStatus.STALE,
    )
    manifest = current_manifest(wiki_current, wiki_stale)

    report = evaluate_freshness(manifest)

    assert report.decision is FreshnessDecision.VERIFIED_CURRENT
    assert any("tied latest records" in warning for warning in report.warnings)


def test_unknown_source_claim_does_not_override_unknown_decision():
    unknown = evidence(
        Component.POB_ENGINE,
        "pob-release",
        version="unverified",
        status=SourceStatus.UNKNOWN,
        claims=(
            VersionClaim("game_patch", "0.5.2"),
            VersionClaim("passive_tree", "0_4"),
        ),
    )

    report = evaluate_freshness(
        replace_component(current_manifest(), unknown, Component.POB_ENGINE)
    )

    assert report.decision is FreshnessDecision.BLOCKED_UNKNOWN


def test_manifest_normalizes_evidence_container_and_rejects_invalid_elements():
    base = current_manifest()
    normalized = FreshnessManifest(
        evidence=list(base.evidence),  # type: ignore[arg-type]
        evaluated_at=NOW,
    )
    assert isinstance(normalized.evidence, tuple)

    with pytest.raises(TypeError, match="evidence"):
        FreshnessManifest(
            evidence=(object(),),  # type: ignore[arg-type]
            evaluated_at=NOW,
        )
