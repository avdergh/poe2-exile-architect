"""Prepare one-case-at-a-time Phase 4.5 Deep Researcher batch queues.

The script fetches or accepts mature PoB samples, writes a safe queue state, and
prepares exactly one transient packet/prompt for the next external Researcher
turn. It does not call an LLM provider and does not write durable memory by
itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus, urlencode

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

NINJA_LIST_MAX_RETRIES = 2

from scripts import run_judge_ninja_samples  # noqa: E402
from server.compute import pob_code  # noqa: E402
from server.freshness import ninja as freshness_ninja  # noqa: E402
from server.knowledge import (  # noqa: E402
    copy_safety,
    pob_xml_meta,
    research_intake_ledger,
    research_packet,
    research_prompt,
)

DEFAULT_OUTPUT_DIR = REPO_ROOT / "phase45_researcher_batch"
STATE_FILENAME = "phase45_researcher_batch_state.json"
JSON_OUTPUT = REPO_ROOT / "phase45_researcher_batch_report.json"
MD_OUTPUT = REPO_ROOT / "phase45_researcher_batch_report.md"

# Bounded pagination: poe.ninja list pages are sampled highest level first, so
# filling a limit with fresh (not-yet-researched) characters can require walking
# several pages. The cap prevents an unbounded crawl when a league is exhausted.
NINJA_LIST_MAX_PAGES = 15

RAW_MARKERS = (
    "eNrt",
    "rawXml",
    "rawImportCode",
    "PathOfBuilding",
    "<Build",
    "<Skills",
    "nameSpec",
    "transientPacketPath",
    "transientPromptPath",
    "pobb.in/",
    "poe.ninja/",
)

POE_NINJA_JSON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36 poe2-build-mcp"
    ),
    "Accept": "application/json",
    "Referer": "https://poe.ninja/poe2/builds",
}

_BUILD_ATTR = re.compile(r"<Build\b([^>]*)>", re.IGNORECASE)
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def build_researcher_batch_report(
    *,
    league_url: str = "current",
    limit: int = 50,
    worker_count: int = 5,
    level_min: int = 90,
    level_max: int = 100,
    ascendancies: list[str] | None = None,
    ninja_classes: list[str] | None = None,
    source_files: list[str | Path] | None = None,
    source_batch_files: list[str | Path] | None = None,
    sample_start_index: int = 1,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    temp_root: str | Path | None = None,
    ttl_seconds: int = 24 * 60 * 60,
    current_patch: str = "unknown",
    passive_tree_version: str = "unknown",
    browser_driver: Any | None = None,
    resume: bool = False,
    dry_run: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Path]]]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    effective_temp_root = _effective_temp_root(temp_root, output_root=output_root)
    effective_temp_root.mkdir(parents=True, exist_ok=True)
    research_packet.cleanup_expired_packets(temp_root=effective_temp_root)
    state_path = output_root / STATE_FILENAME
    previous_state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if resume and state_path.exists()
        else None
    )
    normalized_ninja_classes = _normalize_ninja_classes(ninja_classes or [])
    local_sources = _local_sources(source_files or [], source_batch_files or [])
    cases = (
        _cases_from_sources(local_sources, sample_start_index=sample_start_index)
        if local_sources
        else _cases_from_ninja(
            league_url=league_url,
            limit=limit,
            level_min=level_min,
            level_max=level_max,
            ascendancies=ascendancies or [],
            browser_driver=browser_driver,
            ninja_classes=normalized_ninja_classes,
        )
    )
    state = _new_state(
        cases=cases,
        league_url=league_url,
        limit=limit,
        level_min=level_min,
        level_max=level_max,
        ascendancies=ascendancies or [],
        ninja_classes=normalized_ninja_classes,
    )
    if previous_state is not None:
        _merge_previous_state(state, previous_state)
    runtime_cases = {str(case.get("sourceHash")): case for case in cases}

    transient: list[dict[str, Path]] = []
    prepared_case_ids: list[str] = []
    if not dry_run:
        for next_case in _next_pending_cases(state, worker_count=worker_count):
            runtime_case = runtime_cases.get(str(next_case.get("sourceHash")))
            if runtime_case is None:
                next_case["status"] = "raw_source_unavailable"
                next_case["safeError"] = "raw source must be recollected before packet preparation"
                continue
            packet_input = {**next_case, **runtime_case}
            packet_paths = _prepare_case_packet(
                packet_input,
                output_root=output_root,
                temp_root=effective_temp_root,
                ttl_seconds=ttl_seconds,
                current_patch=current_patch,
                passive_tree_version=passive_tree_version,
            )
            transient.append(packet_paths)
            next_case["status"] = "packet_ready"
            next_case["packetId"] = packet_paths["packetId"]
            next_case["packetSafeHash"] = packet_paths["packetSafeHash"]
            prepared_case_ids.append(str(next_case["sampleId"]))

    safe_state = _safe_state_for_persistence(state)
    _assert_safe_state(safe_state)
    state_path.write_text(
        json.dumps(safe_state, ensure_ascii=False, indent=2, sort_keys=True),
        "utf-8",
    )
    report = _safe_report_from_state(
        safe_state,
        prepared_case_ids=prepared_case_ids,
        dry_run=dry_run,
        output_dir=output_root,
    )
    _assert_safe_report(report)
    return report, transient


def write_researcher_batch_report(
    *,
    json_output: str | Path = JSON_OUTPUT,
    md_output: str | Path = MD_OUTPUT,
    **kwargs: Any,
) -> dict[str, Any]:
    report, _transient = build_researcher_batch_report(**kwargs)
    Path(json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(md_output).write_text(
        _markdown(report, output_dir=kwargs.get("output_dir", DEFAULT_OUTPUT_DIR)),
        encoding="utf-8",
    )
    return report


def mark_case_accepted(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    sample_id: str | None = None,
    packet_safe_hash: str | None = None,
) -> dict[str, Any]:
    output_root = Path(output_dir)
    state_path = output_root / STATE_FILENAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    matched = 0
    for case in state.get("cases") or []:
        sample_match = sample_id is not None and str(case.get("sampleId")) == str(sample_id)
        packet_match = packet_safe_hash is not None and str(case.get("packetSafeHash")) == str(
            packet_safe_hash
        )
        if sample_match or packet_match:
            case["status"] = "accepted"
            matched += 1
    if matched != 1:
        raise ValueError("exactly one queued case must match --mark-accepted")
    safe_state = _safe_state_for_persistence(state)
    _assert_safe_state(safe_state)
    state_path.write_text(
        json.dumps(safe_state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report = _safe_report_from_state(
        safe_state,
        prepared_case_ids=[],
        dry_run=False,
        output_dir=output_root,
    )
    report["status"] = "case_marked_accepted"
    _assert_safe_report(report)
    return report


def build_next_action(report: dict[str, Any], *, output_dir: str | Path) -> dict[str, Any]:
    """Build safe, cross-platform next-step instructions without local temp paths."""
    next_case = report.get("nextCase") if isinstance(report.get("nextCase"), dict) else {}
    return _worker_action(next_case, output_dir=output_dir)


def _worker_action(case: dict[str, Any], *, output_dir: str | Path) -> dict[str, Any]:
    sample_id = _safe_text(case.get("sampleId"))
    packet_safe_hash = _safe_text(case.get("packetSafeHash"))
    output_arg = "<queue-dir>"
    if output_dir == DEFAULT_OUTPUT_DIR or str(output_dir) == str(DEFAULT_OUTPUT_DIR):
        output_arg = "phase45_researcher_batch"
    hash_arg = f" --packet-safe-hash {packet_safe_hash}" if packet_safe_hash else ""
    return {
        "sampleId": sample_id,
        "packetSafeHash": packet_safe_hash,
        "windowsCommand": (
            ".\\.tools\\uv\\uv.exe run python scripts\\run_phase45_researcher_batch.py "
            f"--output-dir {output_arg}{hash_arg} --print-next-prompt"
        ),
        "posixCommand": (
            "./.tools/uv/uv run python scripts/run_phase45_researcher_batch.py "
            f"--output-dir {output_arg}{hash_arg} --print-next-prompt"
        ),
        "notes": [
            "This prints the current transient prompt to stdout for the local external agent.",
            "The prompt/packet path is intentionally not persisted in queue reports.",
        ],
    }


def load_next_prompt(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    temp_root: str | Path | None = None,
    packet_safe_hash: str | None = None,
) -> str:
    """Load the next transient prompt by safe hash without relying on durable path storage."""
    output_root = Path(output_dir)
    state_path = output_root / STATE_FILENAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    target_hash = packet_safe_hash or _next_packet_safe_hash(state)
    if not target_hash:
        raise ValueError("no packet_ready case with packetSafeHash found")
    root = _effective_temp_root(temp_root, output_root=output_root)
    for packet_path in root.glob(f"{research_packet.PACKET_PREFIX}*/packet.json"):
        try:
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(packet.get("safeHash")) != str(target_hash):
            continue
        prompt_path = packet_path.parent / "researcher_prompt.txt"
        if not prompt_path.exists():
            prompt_text = research_prompt.render_researcher_prompt(
                packet,
                current_patch=None,
                passive_tree_version=None,
                user_language="zh-CN",
            )
            prompt_path.write_text(prompt_text, encoding="utf-8")
        return prompt_path.read_text(encoding="utf-8")
    raise FileNotFoundError("transient prompt not found; prepare or resume the queue again")


def _next_packet_safe_hash(state: dict[str, Any]) -> str:
    for case in state.get("cases") or []:
        if case.get("status") == "packet_ready" and case.get("packetSafeHash"):
            return str(case.get("packetSafeHash"))
    return ""


def _cases_from_ninja(
    *,
    league_url: str,
    limit: int,
    level_min: int,
    level_max: int,
    ascendancies: list[str],
    browser_driver: Any | None,
    ninja_classes: list[str] | None = None,
    intake_ledger_path: str | Path | None = None,
    collector_stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Collect cases from poe.ninja, paginating until the requested limit of
    *new* characters is reached.

    ``intake_ledger_path`` (when provided) enables cross-run dedup: characters
    already queued for this league are skipped before their detail pages are
    fetched, and the collector keeps fetching list pages until ``limit`` fresh
    cases exist or the list is exhausted (bounded by NINJA_LIST_MAX_PAGES).
    ``collector_stats`` (when provided) receives safe counts for queue reports.
    """
    resolved_league = _resolve_league_url(league_url)
    browser = browser_driver or run_judge_ninja_samples.PlaywrightHtmlDriver()
    normalized_ninja_classes = _normalize_ninja_classes(ninja_classes or [])
    wanted_ascendancies = {item.casefold() for item in ascendancies if item.strip()}
    wanted_ninja_classes = {item.casefold() for item in normalized_ninja_classes}
    ledger_seen = (
        research_intake_ledger.seen_character_refs(intake_ledger_path, resolved_league)
        if intake_ledger_path is not None
        else set()
    )
    stats = collector_stats if collector_stats is not None else {}
    stats["resolvedLeague"] = resolved_league
    stats.setdefault("pagesFetched", 0)
    stats.setdefault("pageRowsSeen", 0)
    stats.setdefault("skippedAlreadyResearched", 0)
    target = None if limit is None else max(0, int(limit))
    if target == 0:
        return []
    cases: list[dict[str, Any]] = []
    seen_characters: set[tuple[str, str]] = set()
    seen_identity_hashes: set[str] = set()
    for page in range(1, NINJA_LIST_MAX_PAGES + 1):
        if target is not None and len(cases) >= target:
            break
        query: list[tuple[str, str]] = [
            ("min-level", str(level_min)),
            ("max-level", str(level_max)),
        ]
        query.extend(("class", value) for value in normalized_ninja_classes)
        if page > 1:
            query.append(("page", str(page)))
        list_url = f"https://poe.ninja/poe2/builds/{resolved_league}?{urlencode(query)}"
        rows: list[dict[str, Any]] = []
        for _attempt in range(NINJA_LIST_MAX_RETRIES + 1):
            try:
                list_html = browser.fetch_html(list_url)
                rows = run_judge_ninja_samples.extract_character_links_from_rendered_html(
                    list_html,
                    league_url=resolved_league,
                )
            except run_judge_ninja_samples.NinjaSampleError:
                rows = []
            if rows:
                break
        stats["pagesFetched"] = int(stats.get("pagesFetched") or 0) + 1
        if not rows:
            break
        stats["pageRowsSeen"] = int(stats.get("pageRowsSeen") or 0) + len(rows)
        filtered: list[dict[str, Any]] = []
        passed_filters = 0
        in_run_duplicates = 0
        for row in rows:
            level = int(row.get("level") or 0)
            ascendancy = _normalize_ninja_class(row.get("ascendancy"))
            if level < level_min or level > level_max:
                continue
            if wanted_ascendancies and ascendancy.casefold() not in wanted_ascendancies:
                continue
            if wanted_ninja_classes and ascendancy.casefold() not in wanted_ninja_classes:
                continue
            passed_filters += 1
            key = (str(row.get("account") or ""), str(row.get("name") or ""))
            if not key[0] or not key[1] or key in seen_characters:
                if key[0] and key[1] and key in seen_characters:
                    in_run_duplicates += 1
                continue
            seen_characters.add(key)
            ref = research_intake_ledger.character_ref(key[0], key[1])
            if ref in ledger_seen:
                stats["skippedAlreadyResearched"] = (
                    int(stats.get("skippedAlreadyResearched") or 0) + 1
                )
                continue
            filtered.append(row)
        if passed_filters and in_run_duplicates == passed_filters:
            # Every filter-passing row was already seen this run: poe.ninja
            # ignored the page parameter and returned identical content.
            break
        if not filtered:
            continue
        sampled = run_judge_ninja_samples.sample_rows(
            filtered,
            target_count=len(filtered),
            minimum_per_ascendancy=1,
        )
        cases.extend(
            _payload_cases_from_rows(
                sampled,
                league_url=resolved_league,
                browser_driver=browser,
                target_count=(None if target is None else max(0, target - len(cases))),
                seen_identity_hashes=seen_identity_hashes,
                case_start_index=len(cases) + 1,
            )
        )
    return cases


def _normalize_ninja_classes(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        class_name = _normalize_ninja_class(value)
        key = class_name.casefold()
        if not class_name or key in seen:
            continue
        seen.add(key)
        normalized.append(class_name)
    return normalized


def _normalize_ninja_class(value: Any) -> str:
    decoded = unquote_plus(str(value or "").strip()).replace("+", " ")
    return re.sub(r"\s+", " ", decoded).strip()


def _payload_cases_from_rows(
    rows: list[dict[str, Any]],
    *,
    league_url: str,
    browser_driver: Any,
    target_count: int | None = None,
    seen_identity_hashes: set[str] | None = None,
    case_start_index: int = 1,
) -> list[dict[str, Any]]:
    target = None if target_count is None else max(0, int(target_count))
    if target == 0:
        return []
    cases: list[dict[str, Any]] = []
    identity_hashes = set() if seen_identity_hashes is None else seen_identity_hashes
    next_index = max(1, int(case_start_index))
    for row in rows:
        if target is not None and len(cases) >= target:
            break
        account = str(row.get("account") or "")
        name = str(row.get("name") or "")
        character_url = str(
            row.get("url") or run_judge_ninja_samples.build_character_url(league_url, row)
        )
        try:
            page_html = browser_driver.fetch_html(character_url)
        except run_judge_ninja_samples.NinjaSampleError:
            continue
        extracted = run_judge_ninja_samples.extract_import_code_from_rendered_build_page(page_html)
        if not extracted.get("ok"):
            continue
        source = str(extracted["importCode"]).strip()
        identity_hash = _identity_hash(source)
        if identity_hash in identity_hashes:
            continue
        identity_hashes.add(identity_hash)
        source_hash = _safe_hash(source)
        cases.append(
            _case_from_source(
                source,
                source_hash=source_hash,
                sample_id=f"case:phase45-researcher-{next_index + len(cases):03d}",
                source_type="poe_ninja_import_code",
                league=league_url,
                row=row,
                character_ref=(
                    research_intake_ledger.character_ref(account, name) if account and name else ""
                ),
            )
        )
    return cases


def _effective_temp_root(temp_root: str | Path | None, *, output_root: Path) -> Path:
    root = (
        Path(temp_root)
        if temp_root is not None
        else Path(tempfile.gettempdir()) / ("poe-bd-creator-phase45-researcher-packets")
    )
    resolved_root = root.resolve()
    if _is_relative_to(resolved_root, output_root.resolve()):
        raise ValueError("temp_root must not be inside the durable output_dir")
    if _is_relative_to(resolved_root, REPO_ROOT.resolve()):
        raise ValueError("temp_root must not be inside the repository workspace")
    system_temp = Path(tempfile.gettempdir()).resolve()
    if not _is_relative_to(resolved_root, system_temp):
        raise ValueError("temp_root must be inside the operating system temporary directory")
    return resolved_root


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _local_sources(
    source_files: list[str | Path],
    source_batch_files: list[str | Path],
) -> list[str]:
    sources: list[str] = []
    for source_file in source_files:
        source = Path(source_file).read_text(encoding="utf-8").strip()
        if source:
            sources.append(source)
    for batch_file in source_batch_files:
        sources.extend(_parse_source_batch(Path(batch_file).read_text(encoding="utf-8")))
    return sources


def _parse_source_batch(content: str) -> list[str]:
    text = (content or "").strip()
    if not text:
        return []
    if "\n---POB-SAMPLE---\n" in text:
        return [part.strip() for part in text.split("\n---POB-SAMPLE---\n") if part.strip()]
    if _looks_like_xml(text):
        return [text]
    loaded = _parse_json_sources(text)
    if loaded is not None:
        return loaded
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_json_sources(text: str) -> list[str] | None:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, list):
        return [source for item in loaded if (source := _source_from_json_item(item))]
    if isinstance(loaded, dict):
        rows = loaded.get("samples")
        if isinstance(rows, list):
            return [source for item in rows if (source := _source_from_json_item(item))]
        source = _source_from_json_item(loaded)
        return [source] if source else []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not all(line.startswith("{") for line in lines):
        return None
    out: list[str] = []
    try:
        for line in lines:
            source = _source_from_json_item(json.loads(line))
            if source:
                out.append(source)
    except json.JSONDecodeError:
        return None
    return out


def _source_from_json_item(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        for key in ("code", "source", "xml", "url", "link"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _looks_like_xml(text: str) -> bool:
    return text.lstrip().startswith("<") and "PathOfBuilding" in text[:500]


def _cases_from_sources(sources: list[str], *, sample_start_index: int = 1) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen_identity_hashes: set[str] = set()
    next_index = max(1, int(sample_start_index))
    for source in sources:
        identity_hash = _identity_hash(source)
        if identity_hash in seen_identity_hashes:
            continue
        seen_identity_hashes.add(identity_hash)
        source_hash = _safe_hash(source)
        cases.append(
            _case_from_source(
                source,
                source_hash=source_hash,
                sample_id=f"case:phase45-researcher-{next_index:03d}",
                source_type="local_pob_code_file",
                league="unknown",
                row={},
            )
        )
        next_index += 1
    return cases


def _case_from_source(
    source: str,
    *,
    source_hash: str,
    sample_id: str,
    source_type: str,
    league: str,
    row: dict[str, Any],
    character_ref: str = "",
) -> dict[str, Any]:
    try:
        xml = _source_to_xml(source)
        attrs = _build_attributes(xml)
        status = "pending"
        safe_error = ""
    except Exception as exc:  # noqa: BLE001 - queue should keep safe failure rows.
        xml = ""
        attrs = {}
        status = "import_failed"
        safe_error = _safe_error(str(exc))
    level = _safe_int(attrs.get("level") or row.get("level"))
    ascendancy = _safe_text(attrs.get("ascendClassName") or row.get("ascendancy") or "")
    class_name = _safe_text(attrs.get("className") or "")
    main_skill = _safe_text(_main_skill(xml) or "")
    return {
        "sampleId": sample_id,
        "status": status,
        "sourceType": source_type,
        "sourceHash": source_hash,
        "sourceHashRef": f"source-hash:{source_hash[:16]}",
        "characterRef": _safe_text(character_ref or ""),
        "league": _safe_text(league),
        "level": level,
        "className": class_name,
        "ascendancy": ascendancy,
        "mainSkill": main_skill,
        "safeError": safe_error,
        "_rawImportCode": source,
        "_rawXml": xml,
    }


def _new_state(
    *,
    cases: list[dict[str, Any]],
    league_url: str,
    limit: int,
    level_min: int,
    level_max: int,
    ascendancies: list[str],
    ninja_classes: list[str],
) -> dict[str, Any]:
    return {
        "stateVersion": 1,
        "queueKind": "phase45_external_researcher_batch",
        "leagueUrl": _safe_text(league_url),
        "limit": limit,
        "levelMin": level_min,
        "levelMax": level_max,
        "ascendancies": [_safe_text(item) for item in ascendancies],
        "ninjaClasses": [_safe_text(item) for item in ninja_classes],
        "cases": cases,
    }


def _merge_previous_state(state: dict[str, Any], previous_state: dict[str, Any]) -> None:
    previous_by_hash = {
        str(case.get("sourceHash")): case
        for case in previous_state.get("cases") or []
        if case.get("sourceHash")
    }
    for case in state.get("cases") or []:
        previous = previous_by_hash.get(str(case.get("sourceHash")))
        if not previous:
            continue
        previous_status = str(previous.get("status") or "")
        if previous_status in {"accepted", "rejected", "needs_manual_review", "packet_ready"}:
            case["status"] = previous_status
        if previous.get("packetSafeHash"):
            case["packetSafeHash"] = previous.get("packetSafeHash")
        if previous.get("packetId"):
            case["packetId"] = previous.get("packetId")


def _safe_state_for_persistence(state: dict[str, Any]) -> dict[str, Any]:
    safe_state = {key: value for key, value in state.items() if key != "cases"}
    safe_cases: list[dict[str, Any]] = []
    for case in state.get("cases") or []:
        safe_cases.append(
            {
                "sampleId": _safe_text(case.get("sampleId")),
                "status": _safe_text(case.get("status")),
                "sourceType": _safe_text(case.get("sourceType")),
                "sourceHash": _safe_text(case.get("sourceHash")),
                "sourceHashRef": _safe_text(case.get("sourceHashRef")),
                "league": _safe_text(case.get("league")),
                "level": int(case.get("level") or 0),
                "className": _safe_text(case.get("className")),
                "ascendancy": _safe_text(case.get("ascendancy")),
                "mainSkill": _safe_text(case.get("mainSkill")),
                "safeError": _safe_text(case.get("safeError")),
                "packetId": _safe_text(case.get("packetId")),
                "packetSafeHash": _safe_text(case.get("packetSafeHash")),
            }
        )
    safe_state["cases"] = safe_cases
    return safe_state


def _next_pending_cases(state: dict[str, Any], *, worker_count: int) -> list[dict[str, Any]]:
    limit = max(1, int(worker_count or 1))
    in_flight = sum(1 for case in state.get("cases") or [] if case.get("status") == "packet_ready")
    available_slots = max(0, limit - in_flight)
    out: list[dict[str, Any]] = []
    if available_slots <= 0:
        return out
    for case in state.get("cases") or []:
        if case.get("status") == "pending":
            out.append(case)
            if len(out) >= available_slots:
                break
    return out


def _prepare_case_packet(
    case: dict[str, Any],
    *,
    output_root: Path,
    temp_root: str | Path | None,
    ttl_seconds: int,
    current_patch: str,
    passive_tree_version: str,
) -> dict[str, Any]:
    transient_root = Path(temp_root) if temp_root is not None else Path(tempfile.gettempdir())
    packet_case = {
        "safeMetadata": {
            "case_id": case["sampleId"],
            "sourceType": case["sourceType"],
            "sourceRef": case["sourceHashRef"],
            "sourceHash": case["sourceHash"],
            "league": case.get("league") or "unknown",
            "class": case.get("className") or "",
            "ascendancy": case.get("ascendancy") or "",
            "level": str(case.get("level") or ""),
            "mainSkill": case.get("mainSkill") or "",
            "gamePatch": current_patch,
            "passiveTreeVersion": passive_tree_version,
            "visibility": "creator_visible",
            "split": "train_context",
            "knowledgeScope": (
                "global_seed"
                if str(case.get("sourceType") or "").casefold() == "poe_ninja_import_code"
                else "local_user"
            ),
            "evidenceType": case["sourceType"],
            "freshnessStatus": "current_metadata_only"
            if case["sourceType"] == "poe_ninja_import_code"
            else "unknown",
            "compatibilityStatus": "unknown",
        },
        "rawContext": {
            "rawImportCode": case["_rawImportCode"],
            "rawXml": case["_rawXml"],
            "programmaticDiagnostics": {
                "authority": "non_authoritative",
                "rawImportedMainSkill": case.get("mainSkill") or "",
                "judgeProbeStatus": "not_run",
                "judgeSelectedSkillCandidate": "",
                "selectionCaveats": [
                    "Programmatic diagnostics are snapshot-trap warnings, not ground truth."
                ],
            },
            "sourcePayload": {
                "kind": case["sourceType"],
                "sourceHash": case["sourceHash"],
            },
        },
    }
    packet_result = research_packet.build_research_packet(
        packet_case,
        persist_for_transport=True,
        ttl_seconds=ttl_seconds,
        temp_root=transient_root,
    )
    packet = packet_result["packet"]
    prompt_text = research_prompt.render_researcher_prompt(
        packet,
        current_patch=current_patch,
        passive_tree_version=passive_tree_version,
        user_language="zh-CN",
    )
    packet_path = Path(packet_result["packetPath"])
    prompt_path = packet_path.parent / "researcher_prompt.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")
    return {
        "packetPath": packet_path,
        "promptPath": prompt_path,
        "packetId": packet["packetId"],
        "packetSafeHash": packet["safeHash"],
    }


def _safe_report_from_state(
    state: dict[str, Any],
    *,
    prepared_case_ids: list[str],
    dry_run: bool,
    output_dir: str | Path,
) -> dict[str, Any]:
    safe_samples = []
    completed = 0
    pending = 0
    for case in state.get("cases") or []:
        status = str(case.get("status") or "")
        if status == "accepted":
            completed += 1
        elif status in {"pending", "packet_ready"}:
            pending += 1
        safe_samples.append(
            {
                "sampleId": _safe_text(case.get("sampleId")),
                "status": _safe_text(status),
                "sourceType": _safe_text(case.get("sourceType")),
                "sourceHashRef": _safe_text(case.get("sourceHashRef")),
                "packetSafeHash": _safe_text(case.get("packetSafeHash")),
                "className": _safe_text(case.get("className")),
                "ascendancy": _safe_text(case.get("ascendancy")),
                "level": int(case.get("level") or 0),
                "mainSkill": _safe_text(case.get("mainSkill")),
                "safeError": _safe_text(case.get("safeError")),
            }
        )
    prepared_set = set(prepared_case_ids)
    prepared_cases = [sample for sample in safe_samples if sample["sampleId"] in prepared_set]
    next_case = prepared_cases[0] if prepared_cases else None
    report = {
        "reportId": "phase45-researcher-batch-v1",
        "status": "dry_run"
        if dry_run
        else "ready_for_external_researcher"
        if next_case is not None
        else "no_pending_cases",
        "safeArtifactOnly": True,
        "queueKind": "external_agent_one_case_per_turn",
        "sampleCount": len(safe_samples),
        "completedCount": completed,
        "pendingCount": pending,
        "preparedCount": len(prepared_cases),
        "nextCase": next_case or {},
        "preparedCases": prepared_cases,
        "workerActions": [
            _worker_action(sample, output_dir=output_dir) for sample in prepared_cases
        ],
        "samples": safe_samples,
        "caveats": [
            "Project code prepares queue, packets, prompts, and acceptance gates only.",
            "External mature agents must analyze one complete build per turn.",
            "No project-internal LLM provider loop is used.",
            "Use --print-next-prompt to print the current transient Researcher prompt; durable reports intentionally do not store local packet paths.",
            "Programmatic summaries and diagnostics are non-authoritative hints for the external Researcher; they must not suppress raw-evidence analysis.",
        ],
        "noRawMatureBuildMaterial": True,
    }
    return report


def _resolve_league_url(league_url: str) -> str:
    if league_url != "current":
        return _league_url_token(league_url)
    snapshot = freshness_ninja.parse_ninja_snapshot(
        _fetch_json(freshness_ninja.NINJA_INDEX_URL),
        _fetch_json(freshness_ninja.NINJA_BUILD_INDEX_URL),
    )
    return _league_url_token(snapshot.league_url)


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=POE_NINJA_JSON_HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed public API URL.
        return json.loads(response.read().decode("utf-8"))


def _league_url_token(value: str) -> str:
    token = str(value or "").strip().casefold()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", token):
        raise ValueError("invalid poe.ninja league URL token")
    return token


def _identity_hash(source: str) -> str:
    try:
        xml = _source_to_xml(source)
    except Exception:  # noqa: BLE001
        return _safe_hash(source)
    return _safe_hash(xml)


def _source_to_xml(source: str) -> str:
    text = (source or "").strip()
    if _looks_like_xml(text):
        return text
    return pob_code.to_xml(text)


def _build_attributes(xml: str) -> dict[str, str]:
    match = _BUILD_ATTR.search(xml)
    if not match:
        return {}
    return {key: value for key, value in _ATTR.findall(match.group(1))}


def _main_skill(xml: str) -> str | None:
    return pob_xml_meta.main_skill_from_pob_xml(xml)


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_text(value: Any) -> str:
    text = " ".join(str(value or "").split())[:320]
    lower = text.casefold()
    if any(marker.casefold() in lower for marker in RAW_MARKERS):
        raise ValueError("copy-safety marker detected in safe report")
    if re.search(r"(?:https?://|www\.|pobb\.in|poe\.ninja|pastebin\.com)", lower):
        raise ValueError("copy-safety URL detected in safe report")
    return text


def _safe_error(value: str) -> str:
    if copy_safety.copyability_flags(value):
        return "copyable_input_redacted"
    return re.sub(r"[A-Za-z0-9_+/\-=]{80,}", "[redacted-long-token]", value)[:240]


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _assert_safe_report(report: dict[str, Any]) -> None:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe batch report markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(report):
        raise ValueError("unsafe batch report contains forbidden raw fields")
    flags: set[str] = set()
    for text in _human_text(report):
        flags.update(copy_safety.copyability_flags(text))
    if flags:
        raise ValueError(f"unsafe batch report failed copy-safety: {sorted(flags)}")


def _assert_safe_state(state: dict[str, Any]) -> None:
    serialized = json.dumps(state, ensure_ascii=False, sort_keys=True)
    leaks = [marker for marker in RAW_MARKERS if marker in serialized]
    if leaks:
        raise ValueError(f"unsafe batch state markers detected: {', '.join(leaks)}")
    if copy_safety.find_forbidden_paths(state):
        raise ValueError("unsafe batch state contains forbidden raw fields")
    flags: set[str] = set()
    for text in _human_text(state):
        flags.update(copy_safety.copyability_flags(text))
    if flags:
        raise ValueError(f"unsafe batch state failed copy-safety: {sorted(flags)}")


def _human_text(value: Any, *, key: str = "") -> list[str]:
    scan_keys = {"caveats", "safeError"}
    if isinstance(value, dict):
        out: list[str] = []
        for child_key, child in value.items():
            out.extend(_human_text(child, key=str(child_key)))
        return out
    if isinstance(value, list):
        out = []
        for child in value:
            out.extend(_human_text(child, key=key))
        return out
    if isinstance(value, str) and key in scan_keys:
        return [value]
    return []


def _markdown(report: dict[str, Any], *, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> str:
    lines = [
        "# Phase 4.5 Researcher Batch Queue",
        "",
        f"- Status: `{report['status']}`",
        f"- Samples: `{report['sampleCount']}`",
        f"- Pending: `{report['pendingCount']}`",
        f"- Prepared: `{report['preparedCount']}`",
        "",
        "## Next Case",
        "",
    ]
    next_case = report.get("nextCase") or {}
    if next_case:
        lines.append(f"- `{next_case.get('sampleId')}`: `{next_case.get('status')}`")
        action = build_next_action(report, output_dir=output_dir)
        lines.extend(
            [
                "",
                "## Print Next Prompt",
                "",
                "Windows:",
                "",
                f"```powershell\n{action['windowsCommand']}\n```",
                "",
                "macOS/Linux:",
                "",
                f"```bash\n{action['posixCommand']}\n```",
            ]
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Caveats", ""])
    lines.extend(f"- {item}" for item in report.get("caveats", []))
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    print(
        "deprecated: use `python scripts/research_mature_builds.py queue|claim|prompt|accept|status` "
        "or the /poe-bd-research skill instead of run_phase45_researcher_batch.py",
        file=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        prog="run_phase45_researcher_batch.py",
        description=(
            "Development-only compatibility entry. Product research runs use "
            "scripts/research_mature_builds.py via the /poe-bd-research skill; this script is "
            "kept only for legacy dev workflows and always prints a deprecation notice."
        ),
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--worker-count", type=int, default=5)
    parser.add_argument("--league", default="current")
    parser.add_argument("--level-min", type=int, default=90)
    parser.add_argument("--level-max", type=int, default=100)
    parser.add_argument("--ascendancy", action="append", default=[])
    parser.add_argument("--class", dest="ninja_classes", action="append", default=[])
    parser.add_argument("--source-file", action="append", default=[])
    parser.add_argument("--source-batch-file", action="append", default=[])
    parser.add_argument("--sample-start-index", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--print-next-prompt",
        action="store_true",
        help="Print the current transient one-case Researcher prompt to stdout and exit.",
    )
    parser.add_argument("--packet-safe-hash")
    parser.add_argument("--mark-accepted")
    parser.add_argument("--mark-accepted-packet-safe-hash")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--temp-root")
    parser.add_argument("--ttl-seconds", type=int, default=24 * 60 * 60)
    parser.add_argument("--current-patch", default="unknown")
    parser.add_argument("--passive-tree-version", default="unknown")
    parser.add_argument("--json-output", default=str(JSON_OUTPUT))
    parser.add_argument("--md-output", default=str(MD_OUTPUT))
    args = parser.parse_args(argv)

    if args.print_next_prompt:
        print(
            load_next_prompt(
                output_dir=args.output_dir,
                temp_root=args.temp_root,
                packet_safe_hash=args.packet_safe_hash or args.mark_accepted_packet_safe_hash,
            )
        )
        return 0

    if args.mark_accepted or args.mark_accepted_packet_safe_hash:
        report = mark_case_accepted(
            output_dir=args.output_dir,
            sample_id=args.mark_accepted,
            packet_safe_hash=args.mark_accepted_packet_safe_hash,
        )
        Path(args.json_output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        Path(args.md_output).write_text(
            _markdown(report, output_dir=args.output_dir), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "sampleCount": report["sampleCount"],
                    "preparedCount": report["preparedCount"],
                    "transientCount": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    report, transient = build_researcher_batch_report(
        league_url=args.league,
        limit=args.limit,
        worker_count=args.worker_count,
        level_min=args.level_min,
        level_max=args.level_max,
        ascendancies=list(args.ascendancy or []),
        ninja_classes=list(args.ninja_classes or []),
        source_files=[Path(item) for item in args.source_file],
        sample_start_index=args.sample_start_index,
        output_dir=args.output_dir,
        temp_root=args.temp_root,
        ttl_seconds=args.ttl_seconds,
        current_patch=args.current_patch,
        passive_tree_version=args.passive_tree_version,
        resume=args.resume,
        dry_run=args.dry_run,
        source_batch_files=[Path(item) for item in args.source_batch_file],
    )
    Path(args.json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.md_output).write_text(_markdown(report, output_dir=args.output_dir), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "sampleCount": report["sampleCount"],
                "preparedCount": report["preparedCount"],
                "transientCount": len(transient),
                "nextAction": build_next_action(report, output_dir=args.output_dir)
                if report.get("nextCase")
                else {},
                "workerActions": report.get("workerActions", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return (
        0
        if report["status"] in {"ready_for_external_researcher", "no_pending_cases", "dry_run"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
