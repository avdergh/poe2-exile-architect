"""Typed product workflow for mature-build Research queues.

The external Agent never edits queue/review/database files directly.  Product runtime lives under
the application's per-user data root, while this module exposes only opaque run references and
copy-safe payloads.  The legacy CLI remains available for repository development and explicit old
run recovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
from typing import Any

from scripts import research_mature_builds
from server import paths


RUN_REF_PREFIX = "research-run:"
RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")
_PRIVATE_PATH_KEYS = {
    "ledgerpath",
    "lockedfiles",
    "nextcommandargs",
    "outputdir",
    "queuedbpath",
    "reresearchrundir",
    "reviewfile",
    "rundir",
    "transientpacketpath",
    "transientpromptpath",
}


def start_run(
    *,
    league: str = "current",
    limit: int = 50,
    worker_count: int = 5,
    level_min: int = 90,
    level_max: int = 100,
    ascendancies: list[str] | None = None,
    classes: list[str] | None = None,
    source_files: list[str] | None = None,
    source_batch_files: list[str] | None = None,
    expected_source_count: int | None = None,
    sample_start_index: int = 1,
    dry_run: bool = False,
    re_research_run_ref: str | None = None,
    supplement_focus: str = "",
) -> dict[str, Any]:
    """Create one user-data-backed queue and return an opaque run reference."""

    prior_run = _run_dir(re_research_run_ref) if re_research_run_ref else None
    if dry_run:
        report = research_mature_builds.queue_cases(
            league_url=league,
            limit=limit,
            worker_count=worker_count,
            level_min=level_min,
            level_max=level_max,
            ascendancies=ascendancies,
            ninja_classes=classes,
            source_files=source_files,
            source_batch_files=source_batch_files,
            expected_source_count=expected_source_count,
            sample_start_index=sample_start_index,
            output_dir=paths.research_runtime_dir(),
            dry_run=True,
            re_research_run_dir=prior_run,
            supplement_focus=supplement_focus,
        )
        return _without_paths(report)

    run_id, run_dir = research_mature_builds._allocate_run_output_dir(paths.research_runtime_dir())
    report = research_mature_builds.queue_cases(
        league_url=league,
        limit=limit,
        worker_count=worker_count,
        level_min=level_min,
        level_max=level_max,
        ascendancies=ascendancies,
        ninja_classes=classes,
        source_files=source_files,
        source_batch_files=source_batch_files,
        expected_source_count=expected_source_count,
        sample_start_index=sample_start_index,
        output_dir=run_dir,
        re_research_run_dir=prior_run,
        supplement_focus=supplement_focus,
    )
    public = _without_paths(report)
    public.update({"runId": run_id, "runRef": _run_ref(run_id)})
    return public


def run_status(*, run_ref: str) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    result = _without_paths(research_mature_builds.queue_status(output_dir=run_dir))
    result.update({"runId": run_dir.name, "runRef": _run_ref(run_dir.name)})
    return result


def claim_case(*, run_ref: str, lease_seconds: int = 7200) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    result = research_mature_builds.claim_case(
        output_dir=run_dir,
        lease_seconds=lease_seconds,
        lease_owner="typed_research_worker",
    )
    public = _without_paths(result)
    public.pop("workerPrompt", None)
    public.update({"runRef": _run_ref(run_dir.name)})
    if public.get("status") == "claimed":
        public["nextAction"] = "Inspect the leased case with inspect_research_case."
    return public


def inspect_case(*, run_ref: str, lease_token: str) -> dict[str, Any]:
    return research_mature_builds.inspect_case(
        output_dir=_run_dir(run_ref),
        lease_token=lease_token,
    )


def read_case(
    *,
    run_ref: str,
    lease_token: str,
    section: str,
    cursor: int = 0,
    limit: int = 24,
    node_type: str | None = None,
    exclude_routing: bool = False,
) -> dict[str, Any]:
    return research_mature_builds.read_case_section(
        output_dir=_run_dir(run_ref),
        lease_token=lease_token,
        section=section,
        cursor=cursor,
        limit=limit,
        node_type=node_type,
        exclude_routing=exclude_routing,
    )


def search_case(
    *,
    run_ref: str,
    lease_token: str,
    query: str,
    section: str | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    return research_mature_builds.search_case(
        output_dir=_run_dir(run_ref),
        lease_token=lease_token,
        query=query,
        section=section,
        limit=limit,
    )


def review_contract(*, run_ref: str, lease_token: str) -> dict[str, Any]:
    result = research_mature_builds.render_review_contract(
        output_dir=_run_dir(run_ref),
        lease_token=lease_token,
    )
    public = _without_paths(result)
    public["nextActions"] = [
        "initialize_research_review",
        "validate_research_review",
        "accept_research_review",
    ]
    return public


def initialize_review(*, run_ref: str, lease_token: str) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    initialized = research_mature_builds.init_review(
        output_dir=run_dir,
        lease_token=lease_token,
    )
    loaded = research_mature_builds.load_review_payload(
        output_dir=run_dir,
        lease_token=lease_token,
    )
    return {
        "status": initialized["status"],
        "sampleId": initialized["sampleId"],
        "created": initialized["created"],
        "reviewHash": loaded["reviewHash"],
        "review": loaded["review"],
        "nextAction": "Fill the safe review object, then call validate_research_review.",
        "noRawMatureBuildMaterial": True,
    }


def validate_review(
    *,
    run_ref: str,
    lease_token: str,
    review: dict[str, Any],
    only_record: int | None = None,
) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    saved = research_mature_builds.save_review_payload(
        output_dir=run_dir,
        lease_token=lease_token,
        review_payload=review,
    )
    review_path = _lease_review_path(run_dir, lease_token)
    result = research_mature_builds.accept_case(
        output_dir=run_dir,
        lease_token=lease_token,
        review_file=review_path,
        memory_db_path=paths.mature_learning_path(),
        validation_only=True,
        only_record=only_record,
    )
    result["reviewHash"] = saved["reviewHash"]
    if research_mature_builds._should_compact_report(result):
        result = research_mature_builds._compact_accept_result(result)
    return result


def accept_review(
    *,
    run_ref: str,
    lease_token: str,
    expected_review_hash: str,
) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    loaded = research_mature_builds.load_review_payload(
        output_dir=run_dir,
        lease_token=lease_token,
    )
    if loaded["reviewHash"] != expected_review_hash:
        return {
            "status": "acceptance_rejected",
            "errorCode": "review_changed_after_validation",
            "expectedReviewHash": expected_review_hash,
            "currentReviewHash": loaded["reviewHash"],
            "noRawMatureBuildMaterial": True,
        }
    result = research_mature_builds.accept_case(
        output_dir=run_dir,
        lease_token=lease_token,
        review_file=_lease_review_path(run_dir, lease_token),
        memory_db_path=paths.mature_learning_path(),
    )
    result["reviewHash"] = loaded["reviewHash"]
    if research_mature_builds._should_compact_report(result):
        result = research_mature_builds._compact_accept_result(result)
    return result


def retry_review(
    *,
    run_ref: str,
    sample_id: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    saved = research_mature_builds.save_rejected_review_payload(
        output_dir=run_dir,
        sample_id=sample_id,
        review_payload=review,
    )
    result = research_mature_builds.retry_accept_case(
        output_dir=run_dir,
        sample_id=sample_id,
        review_file=saved["reviewFile"],
        memory_db_path=paths.mature_learning_path(),
    )
    result["reviewHash"] = saved["reviewHash"]
    if research_mature_builds._should_compact_report(result):
        result = research_mature_builds._compact_accept_result(result)
    return result


def cleanup_run(
    *,
    run_ref: str,
    allow_rejected: bool = False,
    abandon_incomplete: bool = False,
) -> dict[str, Any]:
    """Remove one private run runtime without exposing or accepting a filesystem path."""

    run_dir = _run_dir(run_ref)
    result = research_mature_builds.cleanup_completed_run(
        run_id=run_dir.name,
        output_dir=paths.research_runtime_dir(),
        allow_rejected=allow_rejected,
        abandon_incomplete=abandon_incomplete,
    )
    public = _without_paths(result)
    public.update({"runId": run_dir.name, "runRef": _run_ref(run_dir.name)})
    return public


def adopt_legacy_run(*, legacy_run_dir: str) -> dict[str, Any]:
    """Copy an inactive legacy run out of a checkout/plugin cache into user-data runtime."""

    source = Path(legacy_run_dir).resolve()
    queue_db = source / research_mature_builds.QUEUE_DB_FILENAME
    if not RUN_ID_RE.fullmatch(source.name) or not queue_db.is_file():
        return _error("invalid_legacy_research_run")
    if source.parent.name != research_mature_builds.RUNS_DIRNAME:
        return _error("invalid_legacy_research_run")
    active = _active_lease_summary(queue_db)
    if active["activeLeaseCount"]:
        return {
            "status": "legacy_run_active",
            "activeLeaseCount": active["activeLeaseCount"],
            "nextLeaseExpiry": active["nextLeaseExpiry"],
            "sourcePreserved": True,
            "noRawMatureBuildMaterial": True,
        }

    runs_root = (paths.research_runtime_dir() / research_mature_builds.RUNS_DIRNAME).resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    destination = (runs_root / source.name).resolve()
    destination.relative_to(runs_root)
    if destination.exists():
        if (destination / research_mature_builds.QUEUE_DB_FILENAME).is_file():
            return {
                "status": "already_adopted",
                "runId": destination.name,
                "runRef": _run_ref(destination.name),
                "sourcePreserved": True,
                "noRawMatureBuildMaterial": True,
            }
        return _error("legacy_run_destination_conflict")

    staging = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.adopting")
    expected_hashes = _runtime_hashes(source)
    try:
        # Lease packets are transient and can contain stale expiry metadata. Rebuild them from the
        # copied quarantine on the next claim instead of migrating their long, process-local paths.
        shutil.copytree(
            source,
            staging,
            ignore=shutil.ignore_patterns(research_mature_builds.DEFAULT_TEMP_DIRNAME),
        )
        if _runtime_hashes(staging) != expected_hashes:
            raise ValueError("legacy run copy verification failed")
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "adopted",
        "runId": destination.name,
        "runRef": _run_ref(destination.name),
        "sourcePreserved": True,
        "noRawMatureBuildMaterial": True,
    }


def _lease_review_path(run_dir: Path, lease_token: str) -> Path:
    db_path = research_mature_builds._queue_db_path(run_dir, None)
    row = research_mature_builds._case_for_valid_lease(db_path, lease_token)
    return run_dir / research_mature_builds._suggested_review_file(
        output_dir=run_dir,
        sample_id=str(row["sample_id"]),
        lease_token=lease_token,
    )


def _run_ref(run_id: str) -> str:
    return RUN_REF_PREFIX + run_id


def _run_dir(run_ref: str | None) -> Path:
    value = str(run_ref or "").strip()
    if not value.startswith(RUN_REF_PREFIX):
        raise ValueError("run_ref must be an opaque research-run reference")
    run_id = value[len(RUN_REF_PREFIX) :]
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("invalid research run reference")
    runs_root = (paths.research_runtime_dir() / research_mature_builds.RUNS_DIRNAME).resolve()
    candidate = (runs_root / run_id).resolve()
    candidate.relative_to(runs_root)
    if not (candidate / research_mature_builds.QUEUE_DB_FILENAME).is_file():
        raise ValueError("research run was not found")
    return candidate


def _without_paths(payload: dict[str, Any]) -> dict[str, Any]:
    result = _scrub_private_paths(json.loads(json.dumps(payload)))
    result["noRawMatureBuildMaterial"] = True
    return result


def _scrub_private_paths(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            child_key: _scrub_private_paths(child_value, key=child_key)
            for child_key, child_value in value.items()
            if child_key.lower() not in _PRIVATE_PATH_KEYS
        }
    if isinstance(value, list):
        return [_scrub_private_paths(item, key=key) for item in value]
    if isinstance(value, str) and key.lower() == "hint":
        lowered = value.lower()
        if "staging directory is preserved at " in lowered or re.search(
            r"[a-z]:[\\/]", value, flags=re.IGNORECASE
        ):
            return (
                "Close processes holding the private Research runtime and retry cleanup; "
                "the resumable runtime remains preserved."
            )
    return value


def _active_lease_summary(queue_db: Path) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    uri = queue_db.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        rows = con.execute(
            """
            SELECT status, lease_expires_at
            FROM cases
            WHERE status = 'accepting'
               OR (status = 'claimed' AND lease_expires_at > ?)
            """,
            (now,),
        ).fetchall()
    expiries = sorted(str(row[1]) for row in rows if row[1])
    return {
        "activeLeaseCount": len(rows),
        "nextLeaseExpiry": expiries[0] if expiries else None,
    }


def _runtime_hashes(root: Path) -> dict[str, str]:
    files = [root / research_mature_builds.QUEUE_DB_FILENAME]
    quarantine = root / "quarantine"
    if quarantine.is_dir():
        files.extend(sorted(path for path in quarantine.glob("*.json") if path.is_file()))
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def _error(code: str) -> dict[str, Any]:
    return {
        "status": "error",
        "errorCode": code,
        "noRawMatureBuildMaterial": True,
    }
