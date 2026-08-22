"""Typed product workflow for mature-build Research queues.

The external Agent never edits queue/review/database files directly.  Product runtime lives under
the application's per-user data root, while this module exposes only opaque run references and
copy-safe payloads.  The legacy CLI remains available for repository development.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
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
    supplement_sample_ids: list[str] | None = None,
    supplement_focus: str = "",
) -> dict[str, Any]:
    """Create one user-data-backed queue and return an opaque run reference."""

    runtime_root = _product_runtime_root()
    source_files = _absolute_local_sources(source_files, option_name="source_files")
    source_batch_files = _absolute_local_sources(
        source_batch_files, option_name="source_batch_files"
    )
    prior_run = _run_dir(re_research_run_ref) if re_research_run_ref else None
    if prior_run is not None and (source_files or source_batch_files):
        return {
            "status": "invalid_request",
            "errorCode": "re_research_source_input_conflict",
            "noRawMatureBuildMaterial": True,
        }
    if prior_run is not None and expected_source_count is not None:
        return {
            "status": "invalid_request",
            "errorCode": "re_research_expected_source_count_conflict",
            "noRawMatureBuildMaterial": True,
        }
    if supplement_sample_ids is not None and prior_run is None:
        return {
            "status": "supplement_selection_invalid",
            "errorCode": "supplement_sample_ids_require_re_research_run_ref",
            "requestedSupplementSampleCount": len(supplement_sample_ids),
            "selectedSupplementSampleCount": 0,
            "selectedSupplementSampleIds": [],
            "missingSupplementSampleCount": 0,
            "missingSupplementSampleIds": [],
            "notAcceptedSupplementSampleCount": 0,
            "notAcceptedSupplementSampleIds": [],
            "unrecoverableSupplementSampleCount": 0,
            "unrecoverableSupplementSampleIds": [],
            "noRawMatureBuildMaterial": True,
        }
    if supplement_sample_ids is not None:
        try:
            selection = research_mature_builds.inspect_supplement_selection(
                prior_run, supplement_sample_ids
            )
        except ValueError as exc:
            return {
                "status": "supplement_selection_invalid",
                "errorCode": "invalid_supplement_sample_ids",
                "safeError": str(exc),
                "requestedSupplementSampleCount": len(supplement_sample_ids),
                "selectedSupplementSampleCount": 0,
                "selectedSupplementSampleIds": [],
                "missingSupplementSampleCount": 0,
                "missingSupplementSampleIds": [],
                "notAcceptedSupplementSampleCount": 0,
                "notAcceptedSupplementSampleIds": [],
                "unrecoverableSupplementSampleCount": 0,
                "unrecoverableSupplementSampleIds": [],
                "noRawMatureBuildMaterial": True,
            }
        if selection["status"] != "ok":
            return {
                **selection,
                "status": "supplement_selection_invalid",
                "errorCode": "supplement_selection_failed",
            }
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
            output_dir=runtime_root,
            dry_run=True,
            re_research_run_dir=prior_run,
            supplement_sample_ids=supplement_sample_ids,
            supplement_focus=supplement_focus,
        )
        return _without_paths(report)

    run_id, run_dir = research_mature_builds._allocate_run_output_dir(runtime_root)
    try:
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
            supplement_sample_ids=supplement_sample_ids,
            supplement_focus=supplement_focus,
        )
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
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
    research_mature_builds.save_review_payload(
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
    if research_mature_builds._should_compact_report(result):
        result = research_mature_builds._compact_accept_result(result)
    return result


def accept_review(
    *,
    run_ref: str,
    lease_token: str,
    review: dict[str, Any],
) -> dict[str, Any]:
    run_dir = _run_dir(run_ref)
    research_mature_builds.save_review_payload(
        output_dir=run_dir,
        lease_token=lease_token,
        review_payload=review,
    )
    result = research_mature_builds.accept_case(
        output_dir=run_dir,
        lease_token=lease_token,
        review_file=_lease_review_path(run_dir, lease_token),
        memory_db_path=paths.mature_learning_path(),
    )
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
        review_file=run_dir / saved["reviewFile"],
        memory_db_path=paths.mature_learning_path(),
    )
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
        output_dir=_product_runtime_root(),
        allow_rejected=allow_rejected,
        abandon_incomplete=abandon_incomplete,
    )
    public = _without_paths(result)
    public.update({"runId": run_dir.name, "runRef": _run_ref(run_dir.name)})
    return public


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
    runs_root = (_product_runtime_root() / research_mature_builds.RUNS_DIRNAME).resolve()
    candidate = (runs_root / run_id).resolve()
    candidate.relative_to(runs_root)
    if not (candidate / research_mature_builds.QUEUE_DB_FILENAME).is_file():
        raise ValueError("research run was not found")
    return candidate


def _product_runtime_root() -> Path:
    root = paths.research_runtime_dir()
    if not root.is_absolute():
        raise ValueError("Research user-data runtime root must be an absolute path")
    return root


def _absolute_local_sources(
    values: list[str] | None,
    *,
    option_name: str,
) -> list[str] | None:
    if values is None:
        return None
    normalized: list[str] = []
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError(f"{option_name} entries must be absolute paths")
        normalized.append(str(path))
    return normalized


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
