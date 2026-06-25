from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import sqlite3
import threading
from time import monotonic
from typing import Any

from server.freshness import (
    CacheState,
    ClaimDimension,
    Component,
    FreshnessDecision,
    FreshnessEvidence,
    ProviderResult,
    SourceStatus,
    VersionClaim,
)
from server.freshness import providers, service


NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


class StubProvider:
    def __init__(
        self,
        source: str,
        evidence: tuple[FreshnessEvidence, ...] = (),
        *,
        diagnostics: tuple[str, ...] = (),
        cache_state: CacheState = CacheState.FRESH,
        delay_seconds: float = 0.0,
        exc: Exception | None = None,
    ) -> None:
        self.source = source
        self.evidence = evidence
        self.diagnostics = diagnostics
        self.cache_state = cache_state
        self.delay_seconds = delay_seconds
        self.exc = exc
        self.calls: list[tuple[datetime, bool]] = []

    def collect(
        self,
        *,
        now: datetime,
        force_refresh: bool = False,
    ) -> ProviderResult:
        self.calls.append((now, force_refresh))
        if self.delay_seconds:
            threading.Event().wait(self.delay_seconds)
        if self.exc is not None:
            raise self.exc
        return ProviderResult(
            source=self.source,
            evidence=self.evidence,
            cache_state=self.cache_state,
            diagnostics=self.diagnostics,
            duration_ms=1,
        )


def evidence(
    component: Component,
    source: str,
    *,
    version: str | None,
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


def matching_claims() -> tuple[VersionClaim, VersionClaim]:
    return (
        VersionClaim(ClaimDimension.GAME_PATCH, "0.5.3"),
        VersionClaim(ClaimDimension.PASSIVE_TREE, "0_5"),
    )


def local_validated_release() -> tuple[FreshnessEvidence, ...]:
    return (
        evidence(
            Component.POB_ENGINE,
            "validated-release-engine",
            version="1234567890abcdef1234567890abcdef12345678",
            claims=matching_claims(),
        ),
        evidence(
            Component.POB_DATA,
            "validated-release-pob-data",
            version="1234567890abcdef1234567890abcdef12345678",
            claims=matching_claims(),
        ),
        evidence(
            Component.CORPUS,
            "validated-release-corpus",
            version="v0.1.39",
            claims=matching_claims(),
        ),
    )


def ggg_patch_evidence() -> tuple[FreshnessEvidence, ...]:
    return (
        evidence(
            Component.GAME_PATCH,
            "ggg-patch",
            version="0.5.3 Hotfix 9",
            claims=(VersionClaim(ClaimDimension.GAME_PATCH, "0.5.3"),),
        ),
    )


def ggg_tree_evidence() -> tuple[FreshnessEvidence, ...]:
    return (
        evidence(
            Component.LEAGUE,
            "ggg-tree",
            version="Runes of Aldur",
            claims=(VersionClaim(ClaimDimension.LEAGUE, "Runes of Aldur"),),
        ),
        evidence(
            Component.PASSIVE_TREE,
            "ggg-tree",
            version="tree-sha",
            claims=matching_claims(),
        ),
    )


def ninja_evidence(passive_tree: str = "0_5") -> tuple[FreshnessEvidence, ...]:
    return (
        evidence(
            Component.META_SNAPSHOT,
            "poe-ninja",
            version="0137-20260624-38624",
            claims=(
                VersionClaim(ClaimDimension.LEAGUE, "Runes of Aldur"),
                VersionClaim(ClaimDimension.PASSIVE_TREE, passive_tree),
            ),
        ),
    )


def pob_evidence(
    *,
    status: SourceStatus = SourceStatus.CURRENT,
    claims: tuple[VersionClaim, ...] | None = None,
) -> tuple[FreshnessEvidence, ...]:
    pob_claims = matching_claims() if claims is None else claims
    return (
        evidence(
            Component.POB_ENGINE,
            "pob",
            version="1234567890abcdef1234567890abcdef12345678",
            status=status,
            claims=pob_claims,
        ),
        evidence(
            Component.POB_DATA,
            "pob",
            version="1234567890abcdef1234567890abcdef12345678",
            status=status,
            claims=pob_claims,
        ),
    )


def install_provider_stubs(
    monkeypatch,
    *providers_to_install: StubProvider,
) -> tuple[StubProvider, ...]:
    monkeypatch.setattr(
        service,
        "_provider_factories",
        tuple((lambda provider=provider: provider) for provider in providers_to_install),
        raising=False,
    )
    return providers_to_install


def install_matching_providers(monkeypatch) -> tuple[StubProvider, ...]:
    monkeypatch.setattr(
        providers,
        "collect_local_evidence",
        lambda observed_at: local_validated_release(),
    )
    return install_provider_stubs(
        monkeypatch,
        StubProvider("ggg-patch", ggg_patch_evidence(), diagnostics=("patch ok",)),
        StubProvider("ggg-tree", ggg_tree_evidence(), diagnostics=("tree ok",)),
        StubProvider("poe-ninja", ninja_evidence(), diagnostics=("ninja ok",)),
        StubProvider("pob", pob_evidence(), diagnostics=("pob ok",)),
    )


def provider_sources(report: dict[str, Any]) -> list[str]:
    return [provider["source"] for provider in report["providers"]]


def test_validated_release_is_shaped_as_local_component_evidence():
    records = providers.shape_validated_release(
        installed={
            "version": "v0.1.39",
            "app_version": "0.1.39",
            "pob_commit": "a82a33b4",
            "game_patch": "0.5.3",
        },
        corpus_info={"schema_version": 4, "built_at": "2026-06-23T04:00:00+00:00"},
        observed_at=NOW,
    )

    by_component = {record.component: record for record in records}
    assert set(by_component) == {
        Component.POB_ENGINE,
        Component.POB_DATA,
        Component.CORPUS,
    }
    assert by_component[Component.POB_ENGINE].version == "a82a33b4"
    assert by_component[Component.CORPUS].status is SourceStatus.CURRENT
    assert any(
        claim.key == ClaimDimension.PASSIVE_TREE and claim.value == "0_5"
        for claim in by_component[Component.POB_DATA].claims
    )
    assert any(
        claim.key == ClaimDimension.GAME_PATCH and claim.value == "0.5.3"
        for claim in by_component[Component.POB_DATA].claims
    )


def test_all_required_live_and_local_evidence_matching_verifies_current(monkeypatch):
    install_matching_providers(monkeypatch)

    report = service.get_freshness_report(observed_at=NOW)

    assert report["decision"] == FreshnessDecision.VERIFIED_CURRENT.value
    assert report["blockers"] == []
    assert provider_sources(report) == ["local", "ggg-patch", "ggg-tree", "poe-ninja", "pob"]


def test_stale_local_pob_evidence_blocks_current_verification(monkeypatch):
    monkeypatch.setattr(
        providers,
        "collect_local_evidence",
        lambda observed_at: local_validated_release(),
    )
    install_provider_stubs(
        monkeypatch,
        StubProvider("ggg-patch", ggg_patch_evidence()),
        StubProvider("ggg-tree", ggg_tree_evidence()),
        StubProvider("poe-ninja", ninja_evidence()),
        StubProvider("pob", pob_evidence(status=SourceStatus.STALE)),
    )

    report = service.get_freshness_report(observed_at=NOW)

    assert report["decision"] == FreshnessDecision.BLOCKED_STALE.value
    assert any("pob reports stale pob_engine" in blocker for blocker in report["blockers"])


def test_ninja_passive_tree_conflict_with_ggg_tree_blocks_verification(monkeypatch):
    monkeypatch.setattr(
        providers,
        "collect_local_evidence",
        lambda observed_at: local_validated_release(),
    )
    install_provider_stubs(
        monkeypatch,
        StubProvider("ggg-patch", ggg_patch_evidence()),
        StubProvider("ggg-tree", ggg_tree_evidence()),
        StubProvider("poe-ninja", ninja_evidence(passive_tree="0_6")),
        StubProvider("pob", pob_evidence()),
    )

    report = service.get_freshness_report(observed_at=NOW)

    assert report["decision"] == FreshnessDecision.BLOCKED_CONFLICT.value
    assert any("passive_tree claims conflict" in blocker for blocker in report["blockers"])


def test_provider_diagnostics_are_serialized_in_deterministic_order(monkeypatch):
    install_matching_providers(monkeypatch)

    report = service.get_freshness_report(observed_at=NOW)

    assert provider_sources(report) == ["local", "ggg-patch", "ggg-tree", "poe-ninja", "pob"]
    assert [provider["diagnostics"] for provider in report["providers"]] == [
        [],
        ["patch ok"],
        ["tree ok"],
        ["ninja ok"],
        ["pob ok"],
    ]


def test_positional_observed_at_remains_backward_compatible(monkeypatch):
    install_matching_providers(monkeypatch)

    report = service.get_freshness_report(NOW)

    assert report["evaluated_at"] == NOW.isoformat()


def test_force_refresh_is_forwarded_to_each_live_provider(monkeypatch):
    live_providers = install_matching_providers(monkeypatch)

    service.get_freshness_report(observed_at=NOW, force_refresh=True)

    assert [provider.calls for provider in live_providers] == [[(NOW, True)]] * 4


def test_service_reuses_bounded_executor_across_calls(monkeypatch):
    constructed: list[int] = []

    class CountingExecutor(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            constructed.append(kwargs.get("max_workers", args[0] if args else None))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(service, "ThreadPoolExecutor", CountingExecutor)
    old_executor = service._provider_executor_instance
    service._provider_executor_instance = None
    install_matching_providers(monkeypatch)

    try:
        service.get_freshness_report(observed_at=NOW)
        service.get_freshness_report(observed_at=NOW)

        assert constructed == [4]
    finally:
        executor = getattr(service, "_provider_executor_instance", None)
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)
        service._provider_executor_instance = old_executor


def test_provider_exception_becomes_missing_diagnostic_without_losing_other_evidence(monkeypatch):
    monkeypatch.setattr(
        providers,
        "collect_local_evidence",
        lambda observed_at: local_validated_release(),
    )
    install_provider_stubs(
        monkeypatch,
        StubProvider("ggg-patch", ggg_patch_evidence()),
        StubProvider("ggg-tree", exc=RuntimeError("boom")),
        StubProvider("poe-ninja", ninja_evidence()),
        StubProvider("pob", pob_evidence()),
    )

    report = service.get_freshness_report(observed_at=NOW)

    provider_rows = {provider["source"]: provider for provider in report["providers"]}
    assert provider_rows["ggg-tree"]["cache_state"] == CacheState.MISSING.value
    assert any(
        "RuntimeError" in item and "boom" in item
        for item in provider_rows["ggg-tree"]["diagnostics"]
    )
    assert any(item["source"] == "ggg-patch" for item in report["evidence"])
    assert any(item["source"] == "poe-ninja" for item in report["evidence"])
    assert report["decision"] == FreshnessDecision.BLOCKED_UNKNOWN.value


def test_total_timeout_returns_promptly_with_missing_provider_diagnostic(monkeypatch):
    monkeypatch.setattr(
        providers,
        "collect_local_evidence",
        lambda observed_at: local_validated_release(),
    )
    install_provider_stubs(
        monkeypatch,
        StubProvider("ggg-patch", ggg_patch_evidence()),
        StubProvider("ggg-tree", ggg_tree_evidence()),
        StubProvider("poe-ninja", ninja_evidence()),
        StubProvider("pob", pob_evidence(), delay_seconds=0.25),
    )

    started = monotonic()
    report = service.get_freshness_report(observed_at=NOW, total_timeout=0.02)
    elapsed = monotonic() - started

    provider_rows = {provider["source"]: provider for provider in report["providers"]}
    assert elapsed < 0.15
    assert provider_rows["pob"]["cache_state"] == CacheState.MISSING.value
    assert any(
        "did not finish within total service timeout" in item
        for item in provider_rows["pob"]["diagnostics"]
    )


def test_local_provider_degrades_on_sqlite_read_error(monkeypatch):
    monkeypatch.setattr(providers.live_update, "installed_meta", lambda: {})

    def fail_corpus_read():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(providers.db, "corpus_info", fail_corpus_read)

    assert providers.collect_local_evidence(NOW) == ()
