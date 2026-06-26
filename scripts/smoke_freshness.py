"""Live freshness smoke diagnostic.

Run from the repo root:

    .\\.tools\\uv\\uv.exe run python scripts/smoke_freshness.py
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.freshness import service  # noqa: E402


_MAX_FIELD_CHARS = 180
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_AUTH_HEADER_RE = re.compile(
    r"\b(authorization|proxy-authorization)\s*[:=]\s*(bearer|basic)?\s*[^\s,;]+",
    flags=re.IGNORECASE,
)
_SENSITIVE_QUERY_RE = re.compile(
    r"([?&](?:access_token|api_key|apikey|auth|key|password|secret|signature|sig|token)=)[^&#\s]+",
    flags=re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", flags=re.IGNORECASE)


def main() -> int:
    try:
        report = service.get_freshness_report(force_refresh=True)
    except Exception as exc:
        print(
            f"SMOKE ERROR: {type(exc).__name__}: {_sanitize(exc)}",
            file=sys.stderr,
        )
        return 1

    _print_report(report)
    # blocked_* decisions are valid safety outcomes for this diagnostic: live sources may be
    # stale, missing, throttled, or offline, and the freshness gate should fail closed without
    # turning ordinary network/source state into a broken smoke command.
    return 0


def _print_report(report: Mapping[str, Any]) -> None:
    print(f"decision: {_sanitize(report.get('decision'))}")
    print(f"evaluated_at: {_sanitize(report.get('evaluated_at'))}")
    _print_items("blockers", _as_iterable(report.get("blockers")))
    _print_items("warnings", _as_iterable(report.get("warnings")))
    _print_providers(_as_iterable(report.get("provider_status") or report.get("providers")))
    _print_evidence(_as_iterable(report.get("evidence")))


def _print_items(label: str, items: Iterable[Any]) -> None:
    values = list(items)
    print(f"{label}:")
    if not values:
        print("  - none")
        return
    for item in values:
        print(f"  - {_sanitize(item)}")


def _print_providers(providers: Iterable[Any]) -> None:
    print("providers:")
    values = list(providers)
    if not values:
        print("  - none")
        return
    for provider in values:
        if not isinstance(provider, Mapping):
            print(f"  - {_sanitize(provider)}")
            continue
        source = _sanitize(provider.get("source"))
        cache_state = _sanitize(provider.get("cache_state"))
        duration_ms = _sanitize(provider.get("duration_ms"))
        print(f"  - source={source} cache_state={cache_state} duration_ms={duration_ms}")
        diagnostics = list(_as_iterable(provider.get("diagnostics")))
        if diagnostics:
            print("    diagnostics:")
            for diagnostic in diagnostics:
                # Diagnostics can include exception text, URLs, or upstream snippets. Keep them
                # useful for triage while avoiding full response bodies or very long URLs in logs.
                print(f"      - {_sanitize(diagnostic)}")
        else:
            print("    diagnostics: none")


def _print_evidence(evidence: Iterable[Any]) -> None:
    print("evidence:")
    values = list(evidence)
    if not values:
        print("  - none")
        return
    for item in values:
        if not isinstance(item, Mapping):
            print(f"  - {_sanitize(item)}")
            continue
        component = _sanitize(item.get("component"))
        source = _sanitize(item.get("source"))
        status = _sanitize(item.get("status"))
        version = _sanitize(item.get("version"))
        claims = _format_claims(_as_iterable(item.get("claims")))
        print(
            f"  - component={component} source={source} "
            f"status={status} version={version} claims=[{claims}]"
        )


def _format_claims(claims: Iterable[Any]) -> str:
    rendered: list[str] = []
    for claim in claims:
        if isinstance(claim, Mapping):
            rendered.append(f"{_sanitize(claim.get('key'))}={_sanitize(claim.get('value'))}")
        else:
            rendered.append(_sanitize(claim))
    return ", ".join(rendered) if rendered else "none"


def _as_iterable(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _sanitize(value: Any, *, max_chars: int = _MAX_FIELD_CHARS) -> str:
    text = "" if value is None else str(value)
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_RE.sub(" ", text)
    text = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}: [redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _SENSITIVE_QUERY_RE.sub(lambda match: f"{match.group(1)}[redacted]", text)
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    suffix = " [truncated]"
    return f"{text[: max_chars - len(suffix)].rstrip()}{suffix}"


if __name__ == "__main__":
    raise SystemExit(main())
