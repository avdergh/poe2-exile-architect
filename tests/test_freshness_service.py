from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import sqlite3
import threading
from time import monotonic
from typing import Any

import pytest

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
from server.freshness.cache import TransportError


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


def ggg_tree_evidence_without_patch_claim() -> tuple[FreshnessEvidence, ...]:
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
            claims=(VersionClaim(ClaimDimension.PASSIVE_TREE, "0_5"),),
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


def test_service_uses_specified_timeout_budgets():
    assert service.DEFAULT_TOTAL_TIMEOUT_SECONDS == 8.0
    assert service._HTTP_TIMEOUT_SECONDS == 5.0


def test_github_api_requests_use_optional_token(monkeypatch):
    captured: dict[str, Any] = {}

    class FakeResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, *, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(service.urllib.request, "urlopen", fake_urlopen)

    service._http_transport(
        service.TransportRequest("https://api.github.com/repos/example/project/commits/main")
    )

    headers = {key.casefold(): value for key, value in captured["headers"].items()}
    assert headers["authorization"] == "Bearer test-token"
    assert headers["accept"] == "application/vnd.github+json"


def test_report_exposes_provider_status_alias(monkeypatch):
    install_matching_providers(monkeypatch)

    report = service.get_freshness_report(observed_at=NOW)

    assert report["provider_status"] == report["providers"]
    assert provider_sources(report) == ["local", "ggg-patch", "ggg-tree", "poe-ninja", "pob"]


def test_provider_factories_use_spec_cache_file_names(tmp_path, monkeypatch):
    monkeypatch.setattr(service.paths, "user_data_dir", lambda: tmp_path)

    ninja = service._ninja_provider()
    pob = service._pob_provider()

    assert ninja._index_store.path == tmp_path / "freshness" / "ninja-index.json"
    assert ninja._build_index_store.path == tmp_path / "freshness" / "ninja-build-index.json"
    assert pob._store.path == tmp_path / "freshness" / "pob-release.json"


def test_validated_release_is_shaped_as_local_component_evidence():
    records = providers.shape_validated_release(
        installed={
            "version": "v0.1.39",
            "app_version": "0.1.39",
            "pob_commit": "a82a33b4",
            "game_patch": "0.5.3",
            "passive_tree": "0_5",
        },
        corpus_info={"schema_version": 4, "built_at": "2026-06-23T04:00:00+00:00",
                     "certifiedCompatibility": {"game_patch": "0.5.3", "passive_tree": "0_5"}},
        observed_at=NOW,
        compatibility=providers.LocalCompatibility(
            game_patch="0.5.3",
            passive_tree="0_5",
        ),
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


def test_validated_release_requires_compatibility_before_emitting_claims():
    records = providers.shape_validated_release(
        installed={
            "version": "v0.1.40",
            "pob_commit": "future-tree",
            "game_patch": "0.6.0",
            "passive_tree": "0_6",
        },
        corpus_info={"schema_version": 4},
        observed_at=NOW,
        compatibility=providers.LocalCompatibility(
            game_patch="0.6.0",
            passive_tree="0_6",
        ),
    )

    by_component = {record.component: record for record in records}
    assert any(
        claim.key == ClaimDimension.PASSIVE_TREE and claim.value == "0_6"
        for claim in by_component[Component.POB_ENGINE].claims
    )

    unverified_records = providers.shape_validated_release(
        installed={
            "version": "v0.1.40",
            "pob_commit": "future-tree",
            "game_patch": "0.6.0",
            "passive_tree": "0_6",
        },
        corpus_info={"schema_version": 4},
        observed_at=NOW,
        compatibility=None,
    )
    assert all(record.claims == () for record in unverified_records)


def test_application_pob_version_enum_normalizes_unknown_version_and_commit():
    current = providers.current_local_compatibility()

    assert current is not None
    assert current.pob_version == "0.23.1-dev.20260910"
    assert current.pob_commit == "ce566eac45ea8a86477f513c7ee65a1ebe60014e"
    assert current.game_patch == "0.5.5"
    assert providers.resolve_pob_version_enum("unknown") == "0.23.1-dev.20260910"
    assert providers.resolve_pob_version_enum(current.pob_commit) == current.pob_version
    assert providers.resolve_pob_version_enum("0.23.1") == "0.23.1"
    assert providers.resolve_pob_version_enum("7d6f530cbdab20389ff8bc6ba97a37ac27f74e41") == "0.23.1"
    assert (
        providers.resolve_pob_version_enum("860f4268299739ce9df87c4f373abe35824101cf") == "0.22.0"
    )
    assert providers.resolve_pob_version_enum("99.99.99") is None


def test_all_required_live_and_local_evidence_matching_verifies_current(monkeypatch):
    install_matching_providers(monkeypatch)

    report = service.get_freshness_report(observed_at=NOW)

    assert report["decision"] == FreshnessDecision.VERIFIED_CURRENT.value
    assert report["blockers"] == []
    assert provider_sources(report) == ["local", "ggg-patch", "ggg-tree", "poe-ninja", "pob"]


def test_official_patch_and_tree_claims_can_be_split_across_sources(monkeypatch):
    monkeypatch.setattr(
        providers,
        "collect_local_evidence",
        lambda observed_at: local_validated_release(),
    )
    install_provider_stubs(
        monkeypatch,
        StubProvider("ggg-patch", ggg_patch_evidence()),
        StubProvider("ggg-tree", ggg_tree_evidence_without_patch_claim()),
        StubProvider("poe-ninja", ninja_evidence()),
        StubProvider("pob", pob_evidence()),
    )

    report = service.get_freshness_report(observed_at=NOW)

    assert report["decision"] == FreshnessDecision.VERIFIED_CURRENT.value
    assert report["blockers"] == []


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
        StubProvider("ggg-tree", exc=TransportError("boom")),
        StubProvider("poe-ninja", ninja_evidence()),
        StubProvider("pob", pob_evidence()),
    )

    report = service.get_freshness_report(observed_at=NOW)

    provider_rows = {provider["source"]: provider for provider in report["providers"]}
    assert provider_rows["ggg-tree"]["cache_state"] == CacheState.MISSING.value
    assert provider_rows["ggg-tree"]["diagnostics"] == ["provider unavailable"]
    assert any(item["source"] == "ggg-patch" for item in report["evidence"])
    assert any(item["source"] == "poe-ninja" for item in report["evidence"])
    assert report["decision"] == FreshnessDecision.BLOCKED_UNKNOWN.value


def test_unexpected_provider_bug_is_not_silently_converted(monkeypatch):
    install_provider_stubs(
        monkeypatch,
        StubProvider("buggy-provider", exc=RuntimeError("secret path C:/Users/name/token")),
    )

    with pytest.raises(RuntimeError, match="secret path"):
        service.get_freshness_report(observed_at=NOW)


def test_local_expected_failure_uses_sanitized_diagnostic(monkeypatch):
    monkeypatch.setattr(
        providers.live_update,
        "installed_meta",
        lambda: (_ for _ in ()).throw(OSError("C:/Users/name/token")),
    )
    monkeypatch.setattr(
        providers.db,
        "corpus_info",
        lambda: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")),
    )

    result = service._collect_local(now=NOW)

    assert result.cache_state is CacheState.MISSING
    assert result.diagnostics == ("local metadata unavailable",)


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

    evidence = {item.component: item for item in providers.collect_local_evidence(NOW)}
    assert evidence[Component.CORPUS].status is SourceStatus.UNKNOWN
    assert evidence[Component.CORPUS].claims == ()
    assert evidence[Component.POB_ENGINE].status is SourceStatus.CURRENT
