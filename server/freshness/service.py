"""Application service shared by MCP, CLI and future background jobs."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from functools import partial
import math
import os
from threading import Lock
from time import monotonic
from typing import Any
import urllib.error
import urllib.request

from .. import paths
from . import providers
from .cache import (
    CacheError,
    FileCacheStore,
    PayloadParseError,
    RefreshAttemptThrottle,
    RefreshCoordinator,
    TransportError,
    TransportRequest,
    TransportResponse,
)
from .evaluator import evaluate_freshness
from .ggg import GGGPatchProvider, GGGOfficialTreeProvider
from .models import FreshnessManifest
from .ninja import NinjaSnapshotProvider
from .pob import PobProvider
from .provider_models import CacheState, EvidenceProvider, ProviderResult


DEFAULT_TOTAL_TIMEOUT_SECONDS = 8.0
_MAX_PROVIDER_WORKERS = 4
_HTTP_TIMEOUT_SECONDS = 5.0
_LOCAL_SOURCE = "local"
_USER_AGENT = {"User-Agent": "poe2-build-mcp freshness/0.1"}
_EXPECTED_PROVIDER_EXCEPTIONS = (CacheError, PayloadParseError, TransportError)

_attempt_throttle = RefreshAttemptThrottle()
_refresh_coordinator = RefreshCoordinator()
_provider_executor_instance: ThreadPoolExecutor | None = None
_provider_executor_lock = Lock()

ProviderFactory = Callable[[], EvidenceProvider]
ProviderTask = Callable[[], ProviderResult]


def _cache_store(name: str) -> FileCacheStore:
    return FileCacheStore(paths.user_data_dir() / "freshness" / f"{name}.json")


def _http_transport(request: TransportRequest) -> TransportResponse:
    headers = {**_USER_AGENT, **dict(request.headers)}
    if request.url.startswith("https://api.github.com/"):
        github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        headers.setdefault("Accept", "application/vnd.github+json")
    http_request = urllib.request.Request(request.url, headers=headers)
    try:
        with urllib.request.urlopen(  # noqa: S310 - freshness providers use fixed HTTPS URLs.
            http_request,
            timeout=_HTTP_TIMEOUT_SECONDS,
        ) as response:
            return TransportResponse(
                status_code=response.status,
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return TransportResponse(
            status_code=exc.code,
            body=exc.read(),
            headers=dict(exc.headers.items()),
        )
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        raise TransportError(str(exc)) from exc


def _ggg_patch_provider() -> EvidenceProvider:
    return GGGPatchProvider(
        store=_cache_store("ggg-patch"),
        transport=_http_transport,
        attempt_throttle=_attempt_throttle,
        refresh_coordinator=_refresh_coordinator,
    )


def _ggg_tree_provider() -> EvidenceProvider:
    return GGGOfficialTreeProvider(
        store=_cache_store("ggg-tree"),
        transport=_http_transport,
        attempt_throttle=_attempt_throttle,
        refresh_coordinator=_refresh_coordinator,
    )


def _ninja_provider() -> EvidenceProvider:
    return NinjaSnapshotProvider(
        index_store=_cache_store("ninja-index"),
        build_index_store=_cache_store("ninja-build-index"),
        transport=_http_transport,
        attempt_throttle=_attempt_throttle,
        refresh_coordinator=_refresh_coordinator,
    )


def _pob_provider() -> EvidenceProvider:
    return PobProvider(
        store=_cache_store("pob-release"),
        transport=_http_transport,
        attempt_throttle=_attempt_throttle,
        refresh_coordinator=_refresh_coordinator,
    )


_provider_factories: tuple[ProviderFactory, ...] = (
    _ggg_patch_provider,
    _ggg_tree_provider,
    _ninja_provider,
    _pob_provider,
)


def get_freshness_report(
    observed_at: datetime | None = None,
    *,
    force_refresh: bool = False,
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Return the strict cross-source freshness report plus provider diagnostics."""

    if (
        not isinstance(total_timeout, (int, float))
        or isinstance(total_timeout, bool)
        or not math.isfinite(total_timeout)
        or total_timeout <= 0
    ):
        raise ValueError("total_timeout must be a positive finite number")

    now = observed_at or datetime.now(UTC)
    results = _collect_provider_results(
        now=now,
        force_refresh=force_refresh,
        total_timeout=float(total_timeout),
    )
    manifest = FreshnessManifest(
        evidence=tuple(evidence for result in results for evidence in result.evidence),
        evaluated_at=now,
    )
    report = evaluate_freshness(manifest).to_dict()
    provider_status = [_provider_result_to_dict(result) for result in results]
    # `provider_status` is the public MCP contract. Keep `providers` as a compatibility alias
    # for older callers and the human-readable smoke script.
    report["provider_status"] = provider_status
    report["providers"] = provider_status
    return report


def _collect_provider_results(
    *,
    now: datetime,
    force_refresh: bool,
    total_timeout: float,
) -> tuple[ProviderResult, ...]:
    tasks = _provider_tasks(now=now, force_refresh=force_refresh)
    deadline = monotonic() + total_timeout
    results: dict[str, ProviderResult] = {}
    submitted_at: dict[Future[ProviderResult], float] = {}
    future_sources: dict[Future[ProviderResult], str] = {}
    executor = _provider_executor()
    pending: set[Future[ProviderResult]] = set()
    for source, task in tasks:
        started = monotonic()
        future = executor.submit(task)
        submitted_at[future] = started
        future_sources[future] = source
        pending.add(future)

    while pending:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
        if not done:
            break
        for future in done:
            source = future_sources[future]
            try:
                results[source] = future.result()
            except _EXPECTED_PROVIDER_EXCEPTIONS:
                results[source] = _missing_result(
                    source=source,
                    started=submitted_at[future],
                    diagnostic="provider unavailable",
                )

    for future in pending:
        # Cancellation is best-effort for already-running provider calls. A shared bounded
        # executor keeps those stragglers inside a global worker cap while this response fails
        # closed and treats the missing source as unavailable evidence.
        future.cancel()
        source = future_sources[future]
        # Freshness is a safety gate: a source that misses the shared budget is reported
        # as missing so the evaluator fails closed instead of silently blessing stale data.
        results[source] = _missing_result(
            source=source,
            started=submitted_at[future],
            diagnostic="provider did not finish within total service timeout",
        )

    return tuple(results.get(source) or _missing_result(source=source) for source, _task in tasks)


def _provider_executor() -> ThreadPoolExecutor:
    global _provider_executor_instance
    with _provider_executor_lock:
        if _provider_executor_instance is None:
            _provider_executor_instance = ThreadPoolExecutor(max_workers=_MAX_PROVIDER_WORKERS)
        return _provider_executor_instance


def _provider_tasks(
    *,
    now: datetime,
    force_refresh: bool,
) -> tuple[tuple[str, ProviderTask], ...]:
    tasks: list[tuple[str, ProviderTask]] = [
        (_LOCAL_SOURCE, partial(_collect_local, now=now)),
    ]
    for factory in _provider_factories:
        provider = factory()
        source = _provider_source(provider)
        tasks.append(
            (
                source,
                partial(
                    _collect_live_provider,
                    provider=provider,
                    source=source,
                    now=now,
                    force_refresh=force_refresh,
                ),
            )
        )
    return tuple(tasks)


def _collect_local(*, now: datetime) -> ProviderResult:
    started = monotonic()
    evidence = providers.collect_local_evidence(now)
    diagnostics: tuple[str, ...] = () if evidence else ("local metadata unavailable",)
    return ProviderResult(
        source=_LOCAL_SOURCE,
        evidence=tuple(evidence),
        cache_state=CacheState.FRESH if evidence else CacheState.MISSING,
        diagnostics=diagnostics,
        duration_ms=_duration_ms(started),
    )


def _collect_live_provider(
    *,
    provider: EvidenceProvider,
    source: str,
    now: datetime,
    force_refresh: bool,
) -> ProviderResult:
    started = monotonic()
    try:
        return provider.collect(now=now, force_refresh=force_refresh)
    except _EXPECTED_PROVIDER_EXCEPTIONS:
        # Provider failures are source diagnostics, not report failures. Missing evidence must
        # remain visible to the evaluator so a live outage blocks current-season verification.
        return _missing_result(
            source=source,
            started=started,
            diagnostic="provider unavailable",
        )


def _missing_result(
    *,
    source: str,
    started: float | None = None,
    diagnostic: str = "provider did not return evidence",
) -> ProviderResult:
    return ProviderResult(
        source=source,
        evidence=(),
        cache_state=CacheState.MISSING,
        diagnostics=(diagnostic,),
        duration_ms=_duration_ms(started) if started is not None else 0,
    )


def _provider_source(provider: EvidenceProvider) -> str:
    return str(getattr(provider, "name", getattr(provider, "source", provider.__class__.__name__)))


def _provider_result_to_dict(result: ProviderResult) -> dict[str, Any]:
    return {
        "source": result.source,
        "cache_state": result.cache_state.value,
        "duration_ms": result.duration_ms,
        "diagnostics": list(result.diagnostics),
    }


def _duration_ms(started: float) -> int:
    return int(max(0.0, monotonic() - started) * 1000)
