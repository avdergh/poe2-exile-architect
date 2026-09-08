"""Append-only, target-patch applicability reviews. Source knowledge is never relabelled."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import copy_safety, research_runtime

# An explicit recall policy, not a numerical/model compatibility certificate.
RECALL_PREDECESSORS = {"0.5.5": ("0.5.4",)}
TARGETS = {
    "deep_research_record": ("deep_research_records", "record_id"),
    "fragment": ("research_fragments", "fragment_id"),
    "semantic_edge": ("research_semantic_edges", "edge_id"),
    "build_pattern": ("research_build_patterns", "pattern_id"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_patch_reviews (
    review_id TEXT PRIMARY KEY,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    knowledge_scope TEXT NOT NULL,
    source_game_patch TEXT NOT NULL,
    target_game_patch TEXT NOT NULL,
    source_fingerprint TEXT NOT NULL,
    source_claim_fingerprint TEXT,
    source_projection_hash TEXT,
    outcome TEXT NOT NULL,
    rationale TEXT NOT NULL,
    correction_summary TEXT NOT NULL,
    verification_tasks TEXT NOT NULL,
    patch_evidence_refs TEXT NOT NULL,
    review_evidence_refs TEXT NOT NULL,
    author_ref TEXT NOT NULL,
    reviewer_ref TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


class PatchReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target_kind: Literal["deep_research_record", "fragment", "semantic_edge", "build_pattern"]
    target_id: str = Field(min_length=1)
    knowledge_scope: Literal["global_seed", "local_user"]
    target_game_patch: str = Field(pattern=r"^\d+\.\d+\.\d+[a-z]*$")
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["still_valid", "changed_scope", "invalid", "uncertain"]
    rationale: str = Field(min_length=12, max_length=1600)
    correction_summary: str = Field(default="", max_length=1600)
    verification_tasks: list[str] = Field(default_factory=list, max_length=20)
    patch_evidence_refs: list[str] = Field(min_length=1, max_length=20)
    review_evidence_refs: list[str] = Field(min_length=1, max_length=20)
    author_ref: str = Field(min_length=1, max_length=160)
    reviewer_ref: str = Field(min_length=1, max_length=160)


def install_schema(con: sqlite3.Connection) -> None:
    con.execute(SCHEMA)
    columns = {row[1] for row in con.execute("PRAGMA table_info(research_patch_reviews)")}
    if "source_claim_fingerprint" not in columns:
        con.execute("ALTER TABLE research_patch_reviews ADD COLUMN source_claim_fingerprint TEXT")
    for review in con.execute(
        "SELECT * FROM research_patch_reviews WHERE source_claim_fingerprint IS NULL"
    ).fetchall():
        table, id_column = TARGETS[review["target_kind"]]
        row = con.execute(
            f"SELECT * FROM {table} WHERE {id_column}=?", (review["target_id"],)
        ).fetchone()
        if row is not None and review["source_fingerprint"] == fingerprint(row):
            con.execute(
                "UPDATE research_patch_reviews SET source_claim_fingerprint=? WHERE review_id=?",
                (claim_fingerprint(row), review["review_id"]),
            )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_research_patch_reviews_target "
        "ON research_patch_reviews(target_kind, target_id, target_game_patch)"
    )


def recall_patches(target_patch: str) -> tuple[str, ...]:
    return (target_patch, *RECALL_PREDECESSORS.get(target_patch, ()))


def register_sql(con: sqlite3.Connection) -> None:
    con.create_function(
        "research_patch_matches",
        2,
        lambda source, target: int(source in recall_patches(str(target))),
        deterministic=True,
    )

    def adoptable(record_id: str, projection_hash: str | None, target_patch: str) -> int:
        review = latest(con, "deep_research_record", record_id, target_patch)
        if review is None:
            return 1
        row = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id=?", (record_id,)
        ).fetchone()
        if row is None or not review_matches(review, row):
            return 1
        return int(review["outcome"] not in {"invalid", "changed_scope"})

    con.create_function("research_patch_adoptable", 3, adoptable)

    def semantic_adoptable(edge_id: str, target_patch: str, target_tree: str) -> int:
        row = con.execute("SELECT * FROM research_semantic_edges WHERE edge_id=?", (edge_id,)).fetchone()
        if row is None or row["game_patch"] not in recall_patches(target_patch) or row["passive_tree_version"] != target_tree:
            return 0
        return int(applicability(con, row, target_patch, kind="semantic_edge")["adoptionAllowed"])

    con.create_function("research_semantic_patch_adoptable", 3, semantic_adoptable)


def fingerprint(row: Any) -> str:
    values = dict(row)
    # IDs, original version, scope and all substantive content are bound. Operational timestamps
    # and evidence counters may change without altering the reviewed claim.
    ignored = {"created_at", "last_seen_at", "last_validated_at", "evidence_count"}
    return research_runtime.stable_hash({k: v for k, v in values.items() if k not in ignored})


def claim_fingerprint(row: Any) -> str:
    ignored = {
        "created_at",
        "last_seen_at",
        "last_validated_at",
        "evidence_count",
        "source_case_refs",
        "safe_evidence_refs",
        "source_diversity_count",
        "sample_count",
        "family_count",
    }
    return research_runtime.stable_hash({k: v for k, v in dict(row).items() if k not in ignored})


def review_matches(review: Any, row: Any) -> bool:
    claim = dict(review).get("source_claim_fingerprint")
    return (
        (claim == claim_fingerprint(row))
        if claim
        else (review["source_fingerprint"] == fingerprint(row))
    )


def latest(con: sqlite3.Connection, kind: str, target_id: str, patch: str) -> sqlite3.Row | None:
    try:
        return con.execute(
            "SELECT * FROM research_patch_reviews WHERE target_kind=? AND target_id=? "
            "AND target_game_patch=? ORDER BY rowid DESC LIMIT 1",
            (kind, target_id, patch),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc):
            raise
        return None


def applicability(
    con: sqlite3.Connection, row: Any, target_patch: str, *, kind: str = "deep_research_record"
) -> dict[str, Any]:
    record = dict(row)
    _, id_column = TARGETS[kind]
    source_patch = str(record["game_patch"])
    review = latest(con, kind, str(record[id_column]), target_patch)
    if review is not None and not review_matches(review, row):
        review = None
    status = "current_evidence" if source_patch == target_patch else "historical_unreviewed"
    if source_patch not in recall_patches(target_patch):
        status = "unsupported_version"
    if review is not None:
        status = {
            "still_valid": "reviewed_compatible",
            "changed_scope": "changed_scope",
            "invalid": "incompatible",
            "uncertain": "historical_unreviewed",
        }[review["outcome"]]
    return {
        "sourceGamePatch": source_patch,
        "targetGamePatch": target_patch,
        "status": status,
        "adoptionAllowed": status not in {"incompatible", "changed_scope", "unsupported_version"},
        "currentPatchSample": source_patch == target_patch,
        "reviewRef": review["review_id"] if review is not None else None,
        "reviewScope": "patch_delta_only",
        "reviewRationale": review["rationale"] if review is not None else "",
        "correctionSummary": review["correction_summary"] if review is not None else "",
        "verificationTasks": json.loads(review["verification_tasks"])
        if review is not None
        else (
            []
            if source_patch == target_patch
            else ["按目标补丁复核机制；数值与合法性须由适用 PoB 验证"]
        ),
    }


def submit(con: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    review = PatchReview.model_validate(payload)
    if review.author_ref == review.reviewer_ref:
        raise ValueError("independent_patch_review_required")
    if any(
        not value.strip()
        for value in [
            *review.patch_evidence_refs,
            *review.review_evidence_refs,
            *review.verification_tasks,
        ]
    ):
        raise ValueError("empty_patch_review_evidence")
    if review.outcome in {"changed_scope", "invalid"} and not review.correction_summary:
        raise ValueError("patch_correction_summary_required")
    if (
        copy_safety.find_forbidden_paths(payload)
        or copy_safety.durable_knowledge_flags(payload)
        or copy_safety.contains_raw_url(payload)
    ):
        raise ValueError("unsafe_patch_review")
    table, id_column = TARGETS[review.target_kind]
    row = con.execute(f"SELECT * FROM {table} WHERE {id_column}=?", (review.target_id,)).fetchone()
    if row is None or row["knowledge_scope"] != review.knowledge_scope:
        raise ValueError("patch_review_target_missing")
    if row["copy_safety_state"] != "passed" or row["visibility"] != "creator_visible":
        raise ValueError("patch_review_target_not_safe")
    if fingerprint(row) != review.source_fingerprint:
        raise ValueError("patch_review_source_changed")
    if row["game_patch"] not in recall_patches(review.target_game_patch):
        raise ValueError("patch_review_unsupported_transition")
    canonical = review.model_dump(mode="json")
    review_id = (
        "prv-" + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:24]
    )
    if con.execute(
        "SELECT 1 FROM research_patch_reviews WHERE review_id=?", (review_id,)
    ).fetchone():
        return {"status": "accepted", "reviewRef": review_id, "idempotentReplay": True}
    values = {
        "review_id": review_id,
        **canonical,
        "source_game_patch": row["game_patch"],
        "source_claim_fingerprint": claim_fingerprint(row),
        "source_projection_hash": dict(row).get("projection_hash"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for key in ("verification_tasks", "patch_evidence_refs", "review_evidence_refs"):
        values[key] = json.dumps(values[key], ensure_ascii=False)
    con.execute(
        f"INSERT INTO research_patch_reviews ({','.join(values)}) VALUES "
        f"({','.join('?' for _ in values)})",
        tuple(values.values()),
    )
    research_runtime.bump_memory_revision(con)
    return {
        "status": "accepted",
        "reviewRef": review_id,
        "sourcePreserved": True,
        "targetApplicability": applicability(
            con, row, review.target_game_patch, kind=review.target_kind
        ),
    }


def family_corrections(
    con: sqlite3.Connection, family_refs: list[tuple[str, str]], patch: str
) -> list[dict[str, Any]]:
    """Expose do-not-repeat corrections without authorizing the old claim as evidence."""
    result = []
    for scope, family in sorted(set(family_refs)):
        rows = con.execute(
            "SELECT * FROM deep_research_records WHERE knowledge_scope=? AND build_family_key=? "
            "AND visibility='creator_visible' AND split='train_context' AND copy_safety_state='passed' "
            "AND status IN ('valid','needs_revalidation') AND research_patch_matches(game_patch, ?)",
            (scope, family, patch),
        ).fetchall()
        for row in rows:
            decision = applicability(con, row, patch)
            if decision["adoptionAllowed"]:
                continue
            result.append(
                {
                    "recordId": row["record_id"],
                    "buildFamilyKey": family,
                    "knowledgeScope": scope,
                    **decision,
                    "createAuthorizing": False,
                }
            )
    return result


def inspect_targets(
    con: sqlite3.Connection,
    *,
    target_game_patch: str,
    target_kind: str = "deep_research_record",
    target_ids: list[str] | None = None,
    after_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Page safe source knowledge for explicit Agent review; discovery does not decide validity."""
    if target_kind not in TARGETS or target_game_patch not in RECALL_PREDECESSORS:
        raise ValueError("unsupported_patch_review_scope")
    if not 1 <= limit <= 100:
        raise ValueError("invalid_patch_review_page_size")
    table, id_column = TARGETS[target_kind]
    where = [
        "visibility='creator_visible'",
        "split='train_context'",
        "copy_safety_state='passed'",
        "status IN ('valid','needs_revalidation')",
        "research_patch_matches(game_patch, ?)",
        f"{id_column}>?",
    ]
    params: list[Any] = [target_game_patch, after_id]
    if target_ids:
        where.append(f"{id_column} IN ({','.join('?' for _ in target_ids)})")
        params.extend(target_ids)
    rows = con.execute(
        f"SELECT * FROM {table} WHERE {' AND '.join(where)} ORDER BY {id_column} LIMIT ?",
        [*params, limit + 1],
    ).fetchall()
    public = []
    for row in rows[:limit]:
        value = dict(row)
        item = {
            key: value[key]
            for key in (
                "record_kind",
                "title",
                "summary",
                "content",
                "conditions",
                "failure_conditions",
                "component_keys",
                "affected_component_keys",
                "typed_payload",
                "rationale",
                "reusable_principle",
                "chunk_text",
                "risks",
                "verification_tasks",
                "source_key",
                "target_key",
                "edge_type",
                "context_requirements",
                "applicability_requirements",
                "exclusion_conditions",
                "planner_hint",
                "game_patch",
                "passive_tree_version",
                "pob_version_or_commit",
                "knowledge_scope",
                "status",
            )
            if key in value
        }
        item.update(
            targetId=value[id_column],
            sourceFingerprint=fingerprint(row),
            targetApplicability=applicability(con, row, target_game_patch, kind=target_kind),
        )
        public.append(item)
    return {
        "status": "known",
        "targets": public,
        "nextAfterId": rows[limit - 1][id_column] if len(rows) > limit else None,
        "targetGamePatch": target_game_patch,
        "targetKind": target_kind,
        "reviewRequired": True,
        "noRawMatureBuildMaterial": True,
    }


def validate_release_reviews(con: sqlite3.Connection, *, prune: bool = False) -> None:
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='research_patch_reviews'"
    ).fetchone():
        return
    previous_factory = con.row_factory
    con.row_factory = sqlite3.Row
    try:
        for review in con.execute("SELECT * FROM research_patch_reviews").fetchall():
            target = TARGETS.get(review["target_kind"])
            row = (
                con.execute(
                    f"SELECT * FROM {target[0]} WHERE {target[1]}=?", (review["target_id"],)
                ).fetchone()
                if target
                else None
            )
            private_or_missing = (
                review["knowledge_scope"] != "global_seed"
                or row is None
                or row["knowledge_scope"] != "global_seed"
            )
            stale = row is not None and not review_matches(review, row)
            if prune and (private_or_missing or stale):
                con.execute(
                    "DELETE FROM research_patch_reviews WHERE review_id=?", (review["review_id"],)
                )
                continue
            if private_or_missing or stale:
                raise ValueError("release_patch_review_binding_invalid")
            payload = dict(review)
            if (
                copy_safety.find_forbidden_paths(payload)
                or copy_safety.durable_knowledge_flags(payload)
                or copy_safety.contains_raw_url(payload)
            ):
                raise ValueError("release_patch_review_not_safe")
    finally:
        con.row_factory = previous_factory
