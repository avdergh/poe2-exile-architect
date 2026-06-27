"""Sanitized mature-build learning store.

Phase 3N.1 owns only schema, fixture ingestion, and copy-safety boundaries. It intentionally does
not influence route synthesis or promote knowledge; later phases may read these tables after their
own visibility and provenance gates are implemented.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import paths

SCHEMA_VERSION = 1
SANITIZER_VERSION = "phase3n1-v1"

FORBIDDEN_COPYABLE_FIELDS = {
    "pobCode",
    "pastebinCode",
    "pobbInCode",
    "rawXml",
    "rawPob",
    "passiveTree",
    "passiveNodeIds",
    "fullPassiveNodeIds",
    "orderedPassiveNodes",
    "gear",
    "items",
    "itemSets",
    "affixes",
    "exactAffixes",
    "skillGroups",
    "supportGems",
    "fullGemLinks",
    "guideText",
    "copiedGuideText",
    "configTab",
}

VALID_VISIBILITY_SPLITS = {
    ("creator_visible", "train_context"),
    ("evaluator_only", "eval_holdout"),
    ("quarantined", "quarantine"),
}
VALID_KNOWLEDGE_SCOPES = {"global_seed", "local_user", "eval_ephemeral"}
VALID_MODELABILITY = {"full", "partial", "not_modelable", "unknown"}
VALID_LIFECYCLE_STAGES = {
    "campaign_early",
    "campaign_mid",
    "campaign_late",
    "maps_entry",
    "endgame_budget",
    "endgame_final",
    "unknown_lifecycle",
}
VALID_EVIDENCE_TYPES = {
    "poe_ninja_hot",
    "external_forum_guide",
    "pobb_in_import",
    "pob_archive",
    "reference_cohort",
    "engine_computed",
    "user_feedback_local",
    "generated_eval_gap",
    "multi_source_confirmed",
    "manual_fixture",
}
VALID_FRESHNESS = {
    "current_metadata_only",
    "verified_current",
    "stale",
    "needs_revalidation",
    "unknown",
}
VALID_COMPATIBILITY = {"current", "stale", "unknown", "quarantined"}
CURRENT_FRESHNESS_CLAIMS = {"verified_current", "current_metadata_only"}
REQUIRED_FIXTURE_MANIFEST_FIELDS = {
    "eligibility_basis",
    "popularity_signal",
    "currentness_basis",
    "diversity_policy",
}


class SchemaVersionError(RuntimeError):
    """Raised when the store is newer than this code can safely read."""


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_groups (
    source_group_id TEXT PRIMARY KEY,
    dedupe_hash TEXT NOT NULL UNIQUE,
    canonical_source_type TEXT NOT NULL,
    canonical_source_ref TEXT NOT NULL,
    league TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    id TEXT PRIMARY KEY,
    source_group_id TEXT NOT NULL REFERENCES source_groups(source_group_id),
    source_type TEXT NOT NULL,
    source_url TEXT,
    fetched_at TEXT NOT NULL,
    league TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    pob_version_or_commit TEXT,
    popularity_filter TEXT NOT NULL,
    diversity_bucket TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    sanitizer_version TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    attribution TEXT NOT NULL,
    usage_policy TEXT NOT NULL,
    fixture_manifest TEXT NOT NULL DEFAULT '{}',
    CHECK (source_type IN ('poe_ninja', 'forum', 'pobb_in', 'pob_archive', 'manual_fixture')),
    CHECK (freshness_status IN (
        'current_metadata_only', 'verified_current', 'stale', 'needs_revalidation', 'unknown'
    ))
);

CREATE TABLE IF NOT EXISTS mature_build_cases (
    case_id TEXT PRIMARY KEY,
    source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
    external_id_hash TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    class TEXT NOT NULL,
    ascendancy TEXT NOT NULL,
    main_skill TEXT NOT NULL,
    damage_types TEXT NOT NULL,
    delivery_tags TEXT NOT NULL,
    defense_tags TEXT NOT NULL,
    mechanic_tags TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    budget_band TEXT NOT NULL,
    popularity_rank INTEGER,
    sample_weight REAL NOT NULL,
    pob_modelability TEXT NOT NULL,
    sanitized_keypoints TEXT NOT NULL,
    numeric_ranges_or_metrics TEXT NOT NULL,
    redacted_fields_present TEXT NOT NULL,
    source_group_id TEXT NOT NULL REFERENCES source_groups(source_group_id),
    evidence_type TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    league TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    compatibility_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (pob_modelability IN ('full', 'partial', 'not_modelable', 'unknown')),
    CHECK (lifecycle_stage IN (
        'campaign_early', 'campaign_mid', 'campaign_late', 'maps_entry',
        'endgame_budget', 'endgame_final', 'unknown_lifecycle'
    )),
    CHECK (evidence_type IN (
        'poe_ninja_hot', 'external_forum_guide', 'pobb_in_import', 'pob_archive',
        'reference_cohort', 'engine_computed', 'user_feedback_local',
        'generated_eval_gap', 'multi_source_confirmed', 'manual_fixture'
    )),
    CHECK (freshness_status IN (
        'current_metadata_only', 'verified_current', 'stale', 'needs_revalidation', 'unknown'
    )),
    CHECK (compatibility_status IN ('current', 'stale', 'unknown', 'quarantined'))
);

CREATE TABLE IF NOT EXISTS technique_candidates (
    candidate_id TEXT PRIMARY KEY,
    knowledge_scope TEXT NOT NULL,
    statement TEXT NOT NULL,
    summary_for_llm TEXT NOT NULL,
    category_tags TEXT NOT NULL,
    lifecycle_stage TEXT NOT NULL,
    mechanism_role TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL,
    promotion_status TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    league TEXT NOT NULL,
    freshness_status TEXT NOT NULL,
    compatibility_status TEXT NOT NULL,
    budget_band TEXT NOT NULL,
    pob_modelability TEXT NOT NULL,
    required_prerequisites TEXT NOT NULL,
    starter_risk_reason TEXT NOT NULL,
    transition_gate_summary TEXT NOT NULL,
    unsafe_before_stage TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (promotion_status IN ('candidate', 'promoted', 'rejected', 'stale', 'quarantined')),
    CHECK (freshness_status IN (
        'current_metadata_only', 'verified_current', 'stale', 'needs_revalidation', 'unknown'
    )),
    CHECK (compatibility_status IN ('current', 'stale', 'unknown', 'quarantined')),
    CHECK (pob_modelability IN ('full', 'partial', 'not_modelable', 'unknown'))
);

CREATE TABLE IF NOT EXISTS candidate_evidence (
    evidence_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES technique_candidates(candidate_id),
    case_id TEXT NOT NULL REFERENCES mature_build_cases(case_id),
    source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id),
    source_group_id TEXT NOT NULL REFERENCES source_groups(source_group_id),
    relation TEXT NOT NULL,
    visibility TEXT NOT NULL,
    split TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence REAL NOT NULL,
    creator_visible INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    CHECK (relation IN ('supports', 'contradicts', 'mentions')),
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context')
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout')
        OR (visibility = 'quarantined' AND split = 'quarantine')
    ),
    CHECK (knowledge_scope IN ('global_seed', 'local_user', 'eval_ephemeral')),
    CHECK (creator_visible IN (0, 1)),
    CHECK (
        (visibility = 'creator_visible' AND split = 'train_context' AND creator_visible = 1)
        OR (visibility = 'evaluator_only' AND split = 'eval_holdout' AND creator_visible = 0)
        OR (visibility = 'quarantined' AND split = 'quarantine' AND creator_visible = 0)
    )
);

CREATE TABLE IF NOT EXISTS technique_edges (
    edge_id TEXT PRIMARY KEY,
    from_candidate_id TEXT NOT NULL REFERENCES technique_candidates(candidate_id),
    to_candidate_id TEXT NOT NULL REFERENCES technique_candidates(candidate_id),
    edge_type TEXT NOT NULL,
    candidate_evidence_ids TEXT NOT NULL,
    confidence REAL NOT NULL,
    league TEXT NOT NULL,
    game_patch TEXT NOT NULL,
    passive_tree_version TEXT NOT NULL,
    CHECK (edge_type IN (
        'requires', 'enables', 'conflicts_with', 'upgrades_to', 'replaces',
        'transition_from', 'transition_to', 'synergizes_with'
    ))
);

INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1');
"""


def mature_learning_path() -> Path:
    return paths.mature_learning_path()


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or mature_learning_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def initialize_store(db_path: Path | None = None) -> Path:
    path = db_path or mature_learning_path()
    con = connect(path)
    try:
        existing = schema_version(con)
        if existing > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"mature learning DB schema {existing} is newer than supported {SCHEMA_VERSION}"
            )
        con.executescript(_SCHEMA_SQL)
    finally:
        con.close()
    return path


def schema_version(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0]) if row else 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _as_string_list(value: Any, *, max_items: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:max_items]:
        text = str(item).strip()
        if text:
            out.append(text[:240])
    return out


def _normalize_field_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _find_forbidden_paths(value: Any, *, path: str = "") -> list[str]:
    """Find forbidden raw-build fields anywhere inside a fixture payload."""
    forbidden_normalized = {_normalize_field_name(field) for field in FORBIDDEN_COPYABLE_FIELDS}
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _normalize_field_name(key_text) in forbidden_normalized:
                found.append(child_path)
            found.extend(_find_forbidden_paths(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            found.extend(_find_forbidden_paths(child, path=child_path))
    return found


def _all_text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        fragments: list[str] = []
        for child in value.values():
            fragments.extend(_all_text_fragments(child))
        return fragments
    if isinstance(value, list):
        fragments = []
        for child in value:
            fragments.extend(_all_text_fragments(child))
        return fragments
    return []


def _copyability_flags(raw: dict[str, Any]) -> list[str]:
    text = "\n".join(_all_text_fragments(raw))
    lower = text.lower()
    flags: list[str] = []
    unique_mentions = len(re.findall(r"\bunique\s*:", lower))
    if unique_mentions >= 3:
        flags.append("too_many_named_uniques")
    if re.search(r"(passive path|node\s+\d+).{0,80}(->|,|\bthen\b).{0,80}node\s+\d+", lower):
        flags.append("ordered_passive_path")
    if re.search(r"supports?\s*:\s*[^.\n,]+(?:,\s*[^.\n,]+){4,}", lower):
        flags.append("full_support_link_like")
    if re.search(r"(ring 1|ring 2|helmet|body armour|gloves|boots|weapon)\s*:", lower):
        flags.append("slot_exact_gear_like")
    if len(text) > 1200:
        flags.append("long_guide_prose_like")
    if re.search(r"\b(?:eNrt|pobb\.in/|pastebin\.com/)[A-Za-z0-9+/_=-]{80,}", text):
        flags.append("pob_code_like_blob")
    return flags


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_numeric_ranges(value: Any) -> tuple[dict[str, Any], str | None]:
    """Allow only aggregate metric ranges, never raw stat dumps."""
    if value in (None, {}):
        return {}, None
    if not isinstance(value, dict):
        return {}, "invalid_numeric_ranges_or_metrics"
    normalized: dict[str, Any] = {}
    allowed_keys = {"min", "median", "max", "n", "p10", "p25", "p75", "p90", "p95"}
    for metric, range_value in value.items():
        if not isinstance(metric, str) or not isinstance(range_value, dict):
            return {}, "invalid_numeric_ranges_or_metrics"
        extra = set(range_value) - allowed_keys
        if extra:
            return {}, "invalid_numeric_ranges_or_metrics"
        if not {"min", "max", "n"} <= set(range_value):
            return {}, "invalid_numeric_ranges_or_metrics"
        for cell in range_value.values():
            if not _is_number(cell):
                return {}, "invalid_numeric_ranges_or_metrics"
        if float(range_value["min"]) > float(range_value["max"]):
            return {}, "invalid_numeric_ranges_or_metrics"
        if int(range_value["n"]) != range_value["n"] or int(range_value["n"]) <= 0:
            return {}, "invalid_numeric_ranges_or_metrics"
        min_value = float(range_value["min"])
        max_value = float(range_value["max"])
        ordered_percentiles = [
            key for key in ("p10", "p25", "median", "p75", "p90", "p95") if key in range_value
        ]
        previous = min_value
        for key in ordered_percentiles:
            current = float(range_value[key])
            if current < min_value or current > max_value or current < previous:
                return {}, "invalid_numeric_ranges_or_metrics"
            previous = current
        normalized[metric] = dict(range_value)
    return normalized, None


def _validate_visibility_scope(raw: dict[str, Any]) -> str | None:
    visibility = str(raw.get("visibility") or "")
    split = str(raw.get("split") or "")
    if (visibility, split) not in VALID_VISIBILITY_SPLITS:
        return "invalid_visibility_split"
    scope = str(raw.get("knowledgeScope") or raw.get("knowledge_scope") or "")
    if scope not in VALID_KNOWLEDGE_SCOPES:
        return "invalid_knowledge_scope"
    evidence_type = str(raw.get("evidenceType") or raw.get("evidence_type") or "")
    if evidence_type == "user_feedback_local" and scope != "local_user":
        return "local_feedback_must_stay_local"
    return None


def _raw_value(raw: dict[str, Any], camel: str, snake: str, default: Any = "") -> Any:
    value = raw.get(camel)
    if value in (None, "") and snake in raw:
        return raw.get(snake)
    return default if value is None else value


def _sample_weight(value: Any) -> tuple[float, str | None]:
    try:
        sample_weight = float(value if value not in (None, "") else 1.0)
    except (TypeError, ValueError):
        return 0.0, "invalid_sample_weight"
    if not math.isfinite(sample_weight) or sample_weight <= 0:
        return 0.0, "invalid_sample_weight"
    return sample_weight, None


def sanitize_mature_case(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized mature-case dict or an explicit rejection result.

    This is intentionally allowlist-first: raw build fields are rejected recursively before any
    summary text is persisted, and the remaining text is checked for reconstructable build details.
    """
    if not isinstance(raw, dict):
        return {"ok": False, "error": "case_must_be_object"}

    forbidden_present = sorted(_find_forbidden_paths(raw))
    if forbidden_present:
        return {
            "ok": False,
            "error": "forbidden_copyable_fields",
            "redactedFieldsPresent": forbidden_present,
        }

    boundary_error = _validate_visibility_scope(raw)
    if boundary_error:
        return {"ok": False, "error": boundary_error}

    copyability = _copyability_flags(raw)
    if copyability:
        return {
            "ok": False,
            "error": "copyability_guard_failed",
            "copyabilityFlags": copyability,
        }

    freshness = str(raw.get("freshnessStatus") or "unknown")
    compatibility = str(raw.get("compatibilityStatus") or "unknown")
    modelability = str(raw.get("pobModelability") or "unknown")
    if freshness not in VALID_FRESHNESS:
        return {"ok": False, "error": "invalid_freshness_status"}
    if compatibility not in VALID_COMPATIBILITY:
        return {"ok": False, "error": "invalid_compatibility_status"}
    if modelability not in VALID_MODELABILITY:
        return {"ok": False, "error": "invalid_pob_modelability"}
    lifecycle_stage = str(
        raw.get("lifecycleStage") or raw.get("lifecycle_stage") or "unknown_lifecycle"
    )
    evidence_type = str(raw.get("evidenceType") or raw.get("evidence_type") or "manual_fixture")
    if lifecycle_stage not in VALID_LIFECYCLE_STAGES:
        return {"ok": False, "error": "invalid_lifecycle_stage"}
    if evidence_type not in VALID_EVIDENCE_TYPES:
        return {"ok": False, "error": "invalid_evidence_type"}
    if freshness in CURRENT_FRESHNESS_CLAIMS and (
        str(raw.get("league") or "").lower() == "unknown"
        or str(raw.get("gamePatch") or "").lower() == "unknown"
        or str(raw.get("passiveTreeVersion") or "").lower() == "unknown"
        or not str(raw.get("league") or "").strip()
        or not str(raw.get("gamePatch") or "").strip()
        or not str(raw.get("passiveTreeVersion") or "").strip()
    ):
        return {"ok": False, "error": "current_claim_missing_version_metadata"}

    numeric_ranges, numeric_error = _validate_numeric_ranges(
        raw.get("numericRangesOrMetrics") or {}
    )
    if numeric_error:
        return {"ok": False, "error": numeric_error}
    sample_weight, sample_error = _sample_weight(raw.get("sampleWeight"))
    if sample_error:
        return {"ok": False, "error": sample_error}

    keypoints = _as_string_list(raw.get("keypoints"), max_items=8)
    now = _now()
    source_ref = str(raw.get("sourceRef") or raw.get("sourceUrl") or "")
    external_hash = _stable_hash(
        {
            "sourceRef": source_ref,
            "class": raw.get("class"),
            "ascendancy": raw.get("ascendancy"),
            "mainSkill": raw.get("mainSkill"),
            "keypoints": keypoints,
        }
    )

    return {
        "ok": True,
        "external_id_hash": external_hash,
        "class": str(raw.get("class") or ""),
        "ascendancy": str(raw.get("ascendancy") or ""),
        "main_skill": str(raw.get("mainSkill") or ""),
        "damage_types": _as_string_list(raw.get("damageTypes")),
        "delivery_tags": _as_string_list(raw.get("deliveryTags")),
        "defense_tags": _as_string_list(raw.get("defenseTags")),
        "mechanic_tags": _as_string_list(raw.get("mechanicTags")),
        "lifecycle_stage": lifecycle_stage,
        "budget_band": str(raw.get("budgetBand") or "unknown"),
        "popularity_rank": raw.get("popularityRank"),
        "sample_weight": sample_weight,
        "pob_modelability": modelability,
        "sanitized_keypoints": keypoints,
        "numeric_ranges_or_metrics": numeric_ranges,
        "redacted_fields_present": [],
        "visibility": str(raw.get("visibility")),
        "split": str(raw.get("split")),
        "knowledge_scope": str(_raw_value(raw, "knowledgeScope", "knowledge_scope")),
        "evidence_type": evidence_type,
        "game_patch": str(raw.get("gamePatch") or "unknown"),
        "passive_tree_version": str(raw.get("passiveTreeVersion") or "unknown"),
        "league": str(raw.get("league") or "unknown"),
        "freshness_status": freshness,
        "compatibility_status": compatibility,
        "created_at": now,
        "last_seen_at": now,
    }


def validate_fixture_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    manifest = raw.get("fixtureManifest") or raw.get("fixture_manifest")
    if not isinstance(manifest, dict):
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": sorted(REQUIRED_FIXTURE_MANIFEST_FIELDS),
        }
    missing = sorted(key for key in REQUIRED_FIXTURE_MANIFEST_FIELDS if key not in manifest)
    if missing:
        return {"ok": False, "error": "fixture_manifest_incomplete", "missing": missing}
    if not str(manifest.get("eligibility_basis") or "").strip():
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["eligibility_basis"],
        }
    popularity_signal = manifest.get("popularity_signal")
    if not isinstance(popularity_signal, dict) or not popularity_signal:
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["popularity_signal"],
        }

    structured_missing: list[str] = []
    if not str(popularity_signal.get("kind") or "").strip():
        structured_missing.append("popularity_signal.kind")
    if (
        popularity_signal.get("kind") == "rank"
        and not str(popularity_signal.get("rank") or "").strip()
    ):
        structured_missing.append("popularity_signal.rank")

    currentness = manifest.get("currentness_basis")
    if not isinstance(currentness, dict) or not currentness:
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["currentness_basis"],
        }
    if not str(currentness.get("snapshot_date") or "").strip():
        structured_missing.append("currentness_basis.snapshot_date")
    if not str(manifest.get("diversity_policy") or "").strip():
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": ["diversity_policy"],
        }
    if structured_missing:
        return {
            "ok": False,
            "error": "fixture_manifest_incomplete",
            "missing": structured_missing,
        }
    if not str(raw.get("popularityRank") or "").strip():
        return {"ok": False, "error": "fixture_popularity_missing", "missing": ["popularityRank"]}
    if not str(raw.get("diversityBucket") or "").strip():
        return {"ok": False, "error": "fixture_diversity_missing", "missing": ["diversityBucket"]}
    if str(raw.get("freshnessStatus") or "") in CURRENT_FRESHNESS_CLAIMS:
        required_currentness = {"league", "game_patch", "passive_tree_version"}
        currentness_missing = sorted(
            key
            for key in required_currentness
            if not str(currentness.get(key) or "").strip()
            or str(currentness.get(key) or "").lower() == "unknown"
        )
        if currentness_missing:
            return {
                "ok": False,
                "error": "fixture_currentness_incomplete",
                "missing": currentness_missing,
            }
    return {"ok": True, "manifest": manifest}


def import_fixture_file(
    fixture_path: Path | None = None, *, db_path: Path | None = None
) -> dict[str, Any]:
    path = fixture_path or paths.mature_learning_seed_fixtures_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"fixture_file_unreadable: {exc}"}
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        return {"ok": False, "error": "fixture_cases_must_be_list"}

    initialize_store(db_path)
    pending: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    rejected: list[dict[str, Any]] = []
    for raw in cases:
        if str(raw.get("evidenceType") or raw.get("evidence_type") or "") == "user_feedback_local":
            rejected.append({"ok": False, "error": "seed_fixture_cannot_use_user_feedback"})
            continue
        manifest_result = validate_fixture_manifest(raw)
        if not manifest_result.get("ok"):
            rejected.append(manifest_result)
            continue
        sanitized = sanitize_mature_case(raw)
        if not sanitized.get("ok"):
            rejected.append(sanitized)
            continue
        pending.append((raw, sanitized, manifest_result["manifest"]))

    if rejected:
        return {"ok": False, "importedCases": 0, "rejected": rejected}

    con = connect(db_path)
    try:
        for raw, sanitized, manifest in pending:
            _insert_sanitized_fixture(con, raw, sanitized, manifest)
        con.commit()
    finally:
        con.close()
    return {"ok": True, "importedCases": len(pending), "rejected": []}


def _insert_sanitized_fixture(
    con: sqlite3.Connection,
    raw: dict[str, Any],
    sanitized: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    now = _now()
    source_ref = str(raw.get("sourceRef") or "")
    dedupe_hash = _stable_hash(
        {
            "sourceType": raw.get("sourceType"),
            "sourceRef": source_ref,
            "class": raw.get("class"),
            "ascendancy": raw.get("ascendancy"),
            "mainSkill": raw.get("mainSkill"),
        }
    )
    source_group_id = f"sg-{dedupe_hash[:12]}"
    snapshot_id = f"ss-{dedupe_hash[:12]}"
    case_id = f"case-{sanitized['external_id_hash'][:12]}"

    con.execute(
        """
        INSERT OR REPLACE INTO source_groups(
            source_group_id, dedupe_hash, canonical_source_type, canonical_source_ref,
            league, game_patch, passive_tree_version, created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_group_id,
            dedupe_hash,
            str(raw.get("sourceType") or "manual_fixture"),
            source_ref,
            sanitized["league"],
            sanitized["game_patch"],
            sanitized["passive_tree_version"],
            now,
            now,
        ),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO source_snapshots(
            id, source_group_id, source_type, source_url, fetched_at, league, game_patch,
            passive_tree_version, pob_version_or_commit, popularity_filter, diversity_bucket,
            raw_hash, sanitizer_version, freshness_status, attribution, usage_policy,
            fixture_manifest
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            source_group_id,
            str(raw.get("sourceType") or "manual_fixture"),
            source_ref,
            now,
            sanitized["league"],
            sanitized["game_patch"],
            sanitized["passive_tree_version"],
            str(raw.get("pobVersionOrCommit") or "unknown"),
            str(raw.get("popularityFilter") or "fixture-structured-popularity-required"),
            str(raw.get("diversityBucket") or "unknown"),
            _stable_hash(raw),
            SANITIZER_VERSION,
            sanitized["freshness_status"],
            str(raw.get("attribution") or source_ref),
            str(raw.get("usagePolicy") or "sanitized_fixture_only"),
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        ),
    )
    con.execute(
        """
        INSERT OR REPLACE INTO mature_build_cases(
            case_id, source_snapshot_id, external_id_hash, visibility, split, knowledge_scope,
            class, ascendancy, main_skill, damage_types, delivery_tags, defense_tags,
            mechanic_tags, lifecycle_stage, budget_band, popularity_rank, sample_weight,
            pob_modelability, sanitized_keypoints, numeric_ranges_or_metrics,
            redacted_fields_present, source_group_id, evidence_type, game_patch,
            passive_tree_version, league, freshness_status, compatibility_status,
            created_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            case_id,
            snapshot_id,
            sanitized["external_id_hash"],
            sanitized["visibility"],
            sanitized["split"],
            sanitized["knowledge_scope"],
            sanitized["class"],
            sanitized["ascendancy"],
            sanitized["main_skill"],
            json.dumps(sanitized["damage_types"], ensure_ascii=False),
            json.dumps(sanitized["delivery_tags"], ensure_ascii=False),
            json.dumps(sanitized["defense_tags"], ensure_ascii=False),
            json.dumps(sanitized["mechanic_tags"], ensure_ascii=False),
            sanitized["lifecycle_stage"],
            sanitized["budget_band"],
            sanitized["popularity_rank"],
            sanitized["sample_weight"],
            sanitized["pob_modelability"],
            json.dumps(sanitized["sanitized_keypoints"], ensure_ascii=False),
            json.dumps(sanitized["numeric_ranges_or_metrics"], ensure_ascii=False),
            json.dumps(sanitized["redacted_fields_present"], ensure_ascii=False),
            source_group_id,
            sanitized["evidence_type"],
            sanitized["game_patch"],
            sanitized["passive_tree_version"],
            sanitized["league"],
            sanitized["freshness_status"],
            sanitized["compatibility_status"],
            sanitized["created_at"],
            sanitized["last_seen_at"],
        ),
    )
