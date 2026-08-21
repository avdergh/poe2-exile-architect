"""Phase 4 semantic research memory service."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import copy_safety
from . import graph_tools
from . import mature_learning
from . import research_identity
from . import research_models
from . import skill_equivalence
from ..freshness import providers as freshness_providers

SHORT_CYCLE_MAX_DEPTH = 3
DIRECTIONAL_EDGE_TYPES = {
    "enables_mechanic",
    "scales_with",
    "mitigates_weakness_of",
    "requires_transition_gate",
    "has_modelability_caveat",
    "creates_failure_risk_for",
}
VALID_REVALIDATION_TARGET_KINDS = {"fragment", "semantic_edge", "build_pattern"}
VALID_REVALIDATION_OUTCOMES = {"still_valid", "invalidated", "changed_scope", "needs_review"}
BUILD_FAMILY_BACKFILL_VERSION = "7"
RESEARCH_MEMORY_SCOPE_WEIGHTS = {
    "exact_family": 1.0,
    "same_primary_skill": 0.9,
    "component": 0.8,
    "global": 0.7,
}
TRANSFER_CONFIDENCE_WEIGHTS = {
    "case_observation": 0.4,
    "recurring_observation": 0.65,
    "likely_pattern": 1.0,
}
PREMISE_AUDIT_VERSION = 1
MECHANISM_RECORD_KINDS = {
    "mechanic_chain",
    "rotation",
    "resource_engine",
    "failure_mode",
}
MECHANISM_RECORD_KIND_PRIORITY = (
    "mechanic_chain",
    "rotation",
    "resource_engine",
    "failure_mode",
)


def _normalize_deep_record_version_context(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("deep_research_records")
    if not isinstance(records, list) or not records:
        return payload
    compatibility = freshness_providers.current_local_compatibility()
    if compatibility is None:
        return payload
    normalized = dict(payload)
    normalized_records: list[Any] = []
    for record in records:
        if not isinstance(record, dict):
            normalized_records.append(record)
            continue
        item = dict(record)
        submitted_raw = _known_version(item.get("pob_version_or_commit"))
        submitted_pob = freshness_providers.resolve_pob_version_enum(submitted_raw)
        if submitted_raw and submitted_pob is None:
            return {
                **payload,
                "__unsupported_pob_version__": submitted_raw,
            }
        item["game_patch"] = _known_version(item.get("game_patch")) or compatibility.game_patch
        item["passive_tree_version"] = (
            _known_version(item.get("passive_tree_version")) or compatibility.passive_tree
        )
        item["pob_version_or_commit"] = submitted_pob or compatibility.pob_version
        normalized_records.append(item)
    normalized["deep_research_records"] = normalized_records
    return normalized


def _known_version(value: Any) -> str:
    normalized = str(value or "").strip()
    return "" if normalized.casefold() in {"", "unknown", "none", "null"} else normalized


def _follow_supersession_head(con: sqlite3.Connection, start_record_id: str) -> sqlite3.Row | None:
    """Walk a deprecated row's ``superseded_by_id`` chain to its live head.

    Returns the first row whose supersession chain terminates at a live
    (valid/needs_revalidation, not superseded) row, or ``None`` when the chain
    is dangling (head missing) or ends in another deprecated row. A ``seen``
    guard protects against deprecated cycles.
    """
    seen: set[str] = set()
    current_id = start_record_id
    while current_id and current_id not in seen:
        seen.add(current_id)
        current = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id = ?", (current_id,)
        ).fetchone()
        if current is None:
            return None
        if str(current["superseded_by_id"] or ""):
            current_id = str(current["superseded_by_id"])
            continue
        if str(current["status"] or "") in {"valid", "needs_revalidation"}:
            return current
        return None
    return None


class ResearchMemoryService:
    def __init__(
        self,
        *,
        db_path: Path | None = None,
        graph_service: graph_tools.GraphQueryService | None = None,
        initialize_store: bool = True,
    ) -> None:
        self.db_path = db_path
        self.graph_service = graph_service
        self.last_build_family_backfill: dict[str, Any] = {"status": "not_run"}
        if initialize_store:
            mature_learning.initialize_store(db_path)
            self.last_build_family_backfill = self.backfill_deep_research_knowledge()

    def backfill_deep_research_knowledge(self, *, force: bool = False) -> dict[str, Any]:
        """Assign high-confidence historical records to families and canonical knowledge units."""
        con = mature_learning.connect(self.db_path)
        try:
            marker = con.execute(
                "SELECT value FROM meta WHERE key = 'phase4_build_family_backfill_version'"
            ).fetchone()
            if not force and marker and str(marker[0]) == BUILD_FAMILY_BACKFILL_VERSION:
                return {
                    "status": "already_applied",
                    "version": BUILD_FAMILY_BACKFILL_VERSION,
                }

            rows = con.execute(
                """
                SELECT * FROM deep_research_records
                WHERE status IN ('valid', 'needs_revalidation')
                  AND superseded_by_id IS NULL
                ORDER BY research_group_id, record_id
                """
            ).fetchall()
            stored_family_keys = {
                str(row[0])
                for row in con.execute(
                    "SELECT build_family_key FROM research_build_families"
                ).fetchall()
                if str(row[0] or "")
            }
            stored_knowledge_keys = {
                str(row[0])
                for row in con.execute(
                    "SELECT DISTINCT knowledge_key FROM deep_research_record_evidence"
                ).fetchall()
                if str(row[0] or "")
            }
            groups: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                groups.setdefault(str(row["research_group_id"]), []).append(row)

            now = _now()
            historical_hints = _historical_family_hints(con)
            family_by_group: dict[str, research_identity.BuildFamilyIdentity] = {}
            family_evidence_added_count = 0
            for group_id, group_rows in groups.items():
                source_refs = sorted(
                    {
                        source_ref
                        for row in group_rows
                        for source_ref in _loads(row["source_case_refs"], [])
                    }
                )
                hint_mentions = sorted(
                    {
                        (role, component_key)
                        for source_ref in source_refs
                        for role, component_key in historical_hints.get(source_ref, set())
                    }
                )
                identity_rows: list[Any] = list(group_rows)
                if hint_mentions:
                    identity_rows.append(
                        {
                            "component_mentions": [
                                {"role": role, "component_key": component_key}
                                for role, component_key in hint_mentions
                            ]
                        }
                    )
                family = research_identity.infer_build_family(
                    identity_rows, allow_dominant_primary=True
                )
                if family is None:
                    continue
                family_by_group[group_id] = family
                family_evidence_added_count += self._upsert_build_family(
                    con,
                    family=family,
                    source_case_refs=source_refs,
                    now=now,
                )

            clusters: dict[
                str, list[tuple[sqlite3.Row, research_identity.BuildFamilyIdentity]]
            ] = {}
            unclassified_record_count = 0
            unkeyed_record_count = 0
            for row in rows:
                family = family_by_group.get(str(row["research_group_id"]))
                if family is None:
                    unclassified_record_count += 1
                    continue
                key = research_identity.knowledge_key(row, family)
                if key is None:
                    unkeyed_record_count += 1
                    con.execute(
                        """
                        UPDATE deep_research_records
                        SET build_family_key = ?, knowledge_key = NULL, evidence_count = 0,
                            status = CASE WHEN status = 'valid' THEN 'needs_revalidation' ELSE status END,
                            last_seen_at = ?
                        WHERE record_id = ?
                        """,
                        (family.key, now, row["record_id"]),
                    )
                    continue
                clusters.setdefault(key, []).append((row, family))

            superseded_record_count = 0
            evidence_added_count = 0
            canonical_record_count = 0
            skipped_invalid_record_count = 0
            relocated_record_count = 0
            occupied_anchor_target_count = 0
            # record_id is a deterministic function of knowledge_key, so assigning a new
            # key to a row whose id no longer hashes to it would decouple id from key and
            # turn future identical accepts into UNIQUE record_id collisions. Phase 1
            # inserts relocated canonical copies (or updates the id-canonical occupant);
            # Phase 2 (after every insert) deprecates displaced rows, so no UPDATE by id
            # can clobber a row another cluster already moved.
            deprecations: list[
                tuple[str, str, str, str]
            ] = []  # (old id, final id, family key, key)
            for key, candidates in sorted(clusters.items()):
                canonical_row, canonical_family = max(
                    candidates,
                    key=lambda item: (
                        research_identity.record_quality(item[0]),
                        str(item[0]["last_validated_at"] or ""),
                        str(item[0]["record_id"]),
                    ),
                )
                canonical_id = str(canonical_row["record_id"])
                target_id = "drr-" + _stable_hash({"knowledge_key": key})[:16]
                displace_canonical = False
                adopt_canonical_id: str | None = None
                occupant = None
                if canonical_id != target_id:
                    occupant = con.execute(
                        "SELECT * FROM deep_research_records WHERE record_id = ?",
                        (target_id,),
                    ).fetchone()
                    if occupant is None:
                        displace_canonical = True
                    elif str(occupant["knowledge_key"] or "") == key:
                        if str(occupant["superseded_by_id"] or ""):
                            # Deprecated husk occupies the anchor id for this key. Follow its
                            # supersession chain: a live head adopts the cluster (re-point its
                            # dependents, delete the husk); a dangling chain is left for the
                            # write path to revive, so the canonical row stays at its own id.
                            head = _follow_supersession_head(con, target_id)
                            if head is not None:
                                head_id = str(head["record_id"])
                                con.execute(
                                    """
                                    UPDATE deep_research_records
                                    SET superseded_by_id = ?
                                    WHERE superseded_by_id = ?
                                    """,
                                    (head_id, target_id),
                                )
                                con.execute(
                                    "DELETE FROM deep_research_records WHERE record_id = ?",
                                    (target_id,),
                                )
                                adopt_canonical_id = head_id
                                occupant = None
                            else:
                                occupied_anchor_target_count += 1
                        elif str(occupant["status"] or "") == "quarantined":
                            # A quarantined row at the anchor id cannot be canonical; drop it
                            # and relocate the drifted canonical row onto the anchor.
                            con.execute(
                                "DELETE FROM deep_research_records WHERE record_id = ?",
                                (target_id,),
                            )
                            occupant = None
                            displace_canonical = True
                        elif str(occupant["status"] or "") == "deprecated":
                            # Bare deprecated row (no supersession target): leave it for the
                            # write path; keeping the canonical at its own id avoids cycles.
                            occupied_anchor_target_count += 1
                        else:
                            # The id-canonical for this key already exists and is live; the
                            # drifted canonical row is superseded toward it.
                            displace_canonical = True
                    else:
                        # Anchor id occupied by a different unit (drift cycle/conflict):
                        # keep the canonical row at its id; the write-path adoption in
                        # _persist_deep_record keeps future accepts safe.
                        occupied_anchor_target_count += 1
                final_canonical_id = adopt_canonical_id or (
                    target_id if displace_canonical else canonical_id
                )
                duplicates = [
                    row for row, _family in candidates if row["record_id"] != final_canonical_id
                ]
                for duplicate in duplicates:
                    deprecations.append(
                        (
                            str(duplicate["record_id"]),
                            final_canonical_id,
                            canonical_family.key,
                            key,
                        )
                    )

                source_refs: set[str] = set()
                safe_refs: set[str] = set()
                # Lower-quality rows are written first so the best representative wins per source.
                for row, _family in sorted(
                    candidates, key=lambda item: research_identity.record_quality(item[0])
                ):
                    proposal = _deep_record_proposal_from_row(row)
                    if proposal is None:
                        skipped_invalid_record_count += 1
                        continue
                    source_refs.update(proposal.source_case_refs)
                    safe_refs.update(proposal.safe_evidence_refs)
                    evidence_added_count += self._upsert_deep_record_evidence(
                        con,
                        knowledge_key=key,
                        record=proposal,
                        now=now,
                    )
                evidence_count = int(
                    con.execute(
                        """
                        SELECT count(*) FROM deep_research_record_evidence
                        WHERE knowledge_key = ?
                        """,
                        (key,),
                    ).fetchone()[0]
                )
                if displace_canonical and occupant is None:
                    # Relocate the canonical to its anchor id (Phase 1 insert). The copy
                    # is built directly from the stored row so it never depends on the
                    # proposal parser; created_at is preserved for tombstone semantics.
                    # Blank the displaced row's key first: when its stored key already
                    # equals the recomputed key (drift), the copy would otherwise collide
                    # with the canonical knowledge-key index until Phase 2 deprecates it.
                    con.execute(
                        "UPDATE deep_research_records SET knowledge_key = NULL WHERE record_id = ?",
                        (canonical_id,),
                    )
                    # Release the unique canonical-key index for every other live same-key
                    # row too: a live duplicate (e.g. a cluster head on a legacy id) would
                    # otherwise collide with the relocated anchor until Phase 2 deprecates
                    # it, and backfill has no rollback for an IntegrityError here.
                    for duplicate in duplicates:
                        con.execute(
                            "UPDATE deep_research_records SET knowledge_key = NULL "
                            "WHERE record_id = ?",
                            (str(duplicate["record_id"]),),
                        )
                    values = {column: canonical_row[column] for column in canonical_row.keys()}
                    values["record_id"] = target_id
                    values["knowledge_key"] = key
                    values["build_family_key"] = canonical_family.key
                    values["evidence_count"] = evidence_count
                    values["source_case_refs"] = _json(sorted(source_refs))
                    values["safe_evidence_refs"] = _json(sorted(safe_refs))
                    values["last_seen_at"] = now
                    values["superseded_by_id"] = None
                    columns = tuple(values)
                    con.execute(
                        f"INSERT INTO deep_research_records({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)})",
                        tuple(values[column] for column in columns),
                    )
                    relocated_record_count += 1
                elif displace_canonical and occupant is not None:
                    con.execute(
                        """
                        UPDATE deep_research_records
                        SET build_family_key = ?, knowledge_key = ?, evidence_count = ?,
                            source_case_refs = ?, safe_evidence_refs = ?, last_seen_at = ?
                        WHERE record_id = ?
                        """,
                        (
                            canonical_family.key,
                            key,
                            evidence_count,
                            _json(sorted(source_refs)),
                            _json(sorted(safe_refs)),
                            now,
                            str(occupant["record_id"]),
                        ),
                    )
                else:
                    if adopt_canonical_id is None:
                        con.execute(
                            """
                            UPDATE deep_research_records
                            SET build_family_key = ?, knowledge_key = ?, evidence_count = ?,
                                source_case_refs = ?, safe_evidence_refs = ?, last_seen_at = ?
                            WHERE record_id = ?
                            """,
                            (
                                canonical_family.key,
                                key,
                                evidence_count,
                                _json(sorted(source_refs)),
                                _json(sorted(safe_refs)),
                                now,
                                canonical_id,
                            ),
                        )
                    # With a live head adopted (adopt_canonical_id set) the canonical row is a
                    # duplicate that Phase 2 deprecates toward the head; writing its key here
                    # would collide with the head's unique canonical-key index.
                canonical_record_count += 1

            # Phase 2: deprecate displaced rows only after every insert is complete, so no
            # UPDATE by id can clobber a row another cluster already relocated into.
            new_ids = {final_id for _old_id, final_id, _family_key, _key in deprecations}
            for old_id, final_id, family_key, key in deprecations:
                if old_id in new_ids:
                    continue
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET build_family_key = ?,
                        knowledge_key = ?,
                        status = 'deprecated',
                        superseded_by_id = ?,
                        last_seen_at = ?
                    WHERE record_id = ?
                    """,
                    (family_key, key, final_id, now, old_id),
                )
                superseded_record_count += 1

            # Keep audit rows aligned with their active canonical representative after identities
            # change, then remove evidence/families made obsolete by the new deterministic keys.
            deprecated_rows = con.execute(
                """
                SELECT record_id, superseded_by_id FROM deep_research_records
                WHERE superseded_by_id IS NOT NULL
                """
            ).fetchall()
            for deprecated in deprecated_rows:
                target = con.execute(
                    """
                    SELECT build_family_key, knowledge_key FROM deep_research_records
                    WHERE record_id = ?
                    """,
                    (deprecated["superseded_by_id"],),
                ).fetchone()
                if target is None:
                    continue
                con.execute(
                    """
                    UPDATE deep_research_records
                    SET build_family_key = ?, knowledge_key = ?, last_seen_at = ?
                    WHERE record_id = ?
                    """,
                    (
                        target["build_family_key"],
                        target["knowledge_key"],
                        now,
                        deprecated["record_id"],
                    ),
                )

            active_knowledge_keys = set(clusters)
            for stale_key in sorted(stored_knowledge_keys - active_knowledge_keys):
                still_referenced = con.execute(
                    """
                    SELECT 1 FROM deep_research_records
                    WHERE knowledge_key = ? AND superseded_by_id IS NULL
                      AND status != 'deprecated'
                    LIMIT 1
                    """,
                    (stale_key,),
                ).fetchone()
                if still_referenced is None:
                    con.execute(
                        "DELETE FROM deep_research_record_evidence WHERE knowledge_key = ?",
                        (stale_key,),
                    )

            active_family_keys = {family.key for family in family_by_group.values()}
            for stale_key in sorted(stored_family_keys - active_family_keys):
                still_referenced = con.execute(
                    """
                    SELECT 1 FROM deep_research_records
                    WHERE build_family_key = ? AND superseded_by_id IS NULL
                      AND status != 'deprecated'
                    LIMIT 1
                    """,
                    (stale_key,),
                ).fetchone()
                if still_referenced is None:
                    con.execute(
                        "DELETE FROM research_build_family_evidence WHERE build_family_key = ?",
                        (stale_key,),
                    )
                    con.execute(
                        "DELETE FROM research_build_families WHERE build_family_key = ?",
                        (stale_key,),
                    )

            family_by_source: dict[str, str] = {}
            for group_id, family in family_by_group.items():
                for row in groups[group_id]:
                    for source_ref in _loads(row["source_case_refs"], []):
                        family_by_source[str(source_ref)] = family.key
            updated_pattern_origin_count = 0
            pattern_rows = con.execute(
                """
                SELECT pattern_id, transfer_scope, source_case_refs, origin_family_keys
                FROM research_build_patterns
                WHERE status IN ('valid', 'needs_revalidation')
                  AND superseded_by_id IS NULL
                """
            ).fetchall()
            for pattern_row in pattern_rows:
                origin_family_keys = sorted(
                    {
                        family_by_source[source_ref]
                        for source_ref in _loads(pattern_row["source_case_refs"], [])
                        if source_ref in family_by_source
                    }
                )
                if not origin_family_keys or origin_family_keys == sorted(
                    _loads(pattern_row["origin_family_keys"], [])
                ):
                    continue
                family_count = (
                    len(origin_family_keys)
                    if str(pattern_row["transfer_scope"]) == "component"
                    else None
                )
                con.execute(
                    """
                    UPDATE research_build_patterns
                    SET origin_family_keys = ?,
                        family_count = CASE WHEN ? IS NULL THEN family_count ELSE ? END,
                        last_seen_at = ?
                    WHERE pattern_id = ?
                    """,
                    (
                        _json(origin_family_keys),
                        family_count,
                        family_count,
                        now,
                        pattern_row["pattern_id"],
                    ),
                )
                updated_pattern_origin_count += 1

            con.execute(
                """
                INSERT INTO meta(key, value) VALUES ('phase4_build_family_backfill_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (BUILD_FAMILY_BACKFILL_VERSION,),
            )
            con.commit()
            return {
                "status": "applied",
                "version": BUILD_FAMILY_BACKFILL_VERSION,
                "scannedRecordCount": len(rows),
                "classifiedFamilyCount": len({family.key for family in family_by_group.values()}),
                "classifiedResearchGroupCount": len(family_by_group),
                "canonicalRecordCount": canonical_record_count,
                "supersededRecordCount": superseded_record_count,
                "relocatedRecordCount": relocated_record_count,
                "occupiedAnchorTargetCount": occupied_anchor_target_count,
                "unclassifiedRecordCount": unclassified_record_count,
                "unkeyedRecordCount": unkeyed_record_count,
                "skippedInvalidRecordCount": skipped_invalid_record_count,
                "evidenceAddedCount": evidence_added_count,
                "familyEvidenceAddedCount": family_evidence_added_count,
                "updatedPatternOriginCount": updated_pattern_origin_count,
            }
        finally:
            con.close()

    def query_research_memory(
        self,
        query: str,
        *,
        component_keys: list[str] | None = None,
        limit: int = 10,
        detail_level: str = "summary",
        record_ids: list[str] | None = None,
        include_transferable: bool = False,
        research_axes: list[str] | None = None,
        ascendancy_key: str | None = None,
        primary_skill_key: str | None = None,
        build_family_keys: list[str] | None = None,
        record_kinds: list[str] | None = None,
        class_key: str | None = None,
        game_patch: str | None = None,
        passive_tree_version: str | None = None,
    ) -> dict[str, Any]:
        if detail_level not in {"summary", "record", "family"}:
            return research_models.public_error(
                "invalid_detail_level", ["detail_level must be summary, record or family"]
            )
        component_keys = sorted({str(key) for key in component_keys or [] if str(key).strip()})
        research_axes = sorted({str(axis) for axis in research_axes or [] if str(axis).strip()})
        ascendancy_key = str(ascendancy_key or "").strip() or None
        primary_skill_key = str(primary_skill_key or "").strip() or None
        class_key = str(class_key or "").strip() or None
        game_patch = str(game_patch or "").strip() or None
        passive_tree_version = str(passive_tree_version or "").strip() or None
        if ascendancy_key and not ascendancy_key.startswith("ascendancy:"):
            return research_models.public_error(
                "invalid_identity_parameter",
                [
                    "ascendancy_key must use the stable form 'ascendancy:<class>:<ascendancy>' "
                    f"(got '{ascendancy_key}'); a bare display name cannot match stored keys."
                ],
            )
        if primary_skill_key:
            if not primary_skill_key.startswith(("skill:", "gem:")):
                return research_models.public_error(
                    "invalid_identity_parameter",
                    [
                        "primary_skill_key must use a stable form 'skill:<InternalSkillId>' "
                        f"or a gem component key (got '{primary_skill_key}'); display names "
                        "cannot match stored keys."
                    ],
                )
            if any(char.isspace() for char in primary_skill_key):
                return research_models.public_error(
                    "invalid_identity_parameter",
                    [
                        "primary_skill_key must not contain spaces; use the engine stable key "
                        f"like 'skill:DetonateDeadPlayer' (got '{primary_skill_key}')."
                    ],
                )
        if detail_level == "family" and not (class_key and game_patch and passive_tree_version):
            return research_models.public_error(
                "family_discovery_requires_exact_context",
                ["detail_level=family requires class_key, game_patch and passive_tree_version"],
            )
        build_family_keys = sorted(
            {str(key).strip() for key in build_family_keys or [] if str(key).strip()}
        )
        record_kinds = sorted(
            {
                str(record_kind).strip()
                for record_kind in record_kinds or []
                if str(record_kind).strip()
            }
        )
        invalid_axes = sorted(set(research_axes) - research_models.OBSERVATION_AXES)
        if invalid_axes:
            return research_models.public_error(
                "invalid_research_axes",
                ["research_axes must use canonical observation axes: " + ", ".join(invalid_axes)],
            )
        invalid_record_kinds = sorted(
            set(record_kinds) - research_models.DEEP_RESEARCH_RECORD_KINDS
        )
        if invalid_record_kinds:
            return research_models.public_error(
                "invalid_record_kinds",
                [
                    "record_kinds must use canonical deep research record kinds: "
                    + ", ".join(invalid_record_kinds)
                ],
            )
        component_key_groups = self._component_key_groups(component_keys)
        primary_skill_keys = (
            sorted(
                {key for group in self._component_key_groups([primary_skill_key]) for key in group}
            )
            if primary_skill_key
            else []
        )
        record_ids = sorted({str(item) for item in record_ids or [] if str(item).strip()})
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            family_discovery = detail_level == "family"
            rows = (
                []
                if family_discovery or (record_ids and not query.strip() and not component_keys)
                else self._query_rows(con, query, component_key_groups, limit)
            )
            results = [self._fragment_result(row) for row in rows]
            explicit_family_filter = bool(ascendancy_key or primary_skill_key or build_family_keys)
            family_rows = (
                self._query_discovery_family_rows(
                    con,
                    class_key=class_key or "",
                    game_patch=game_patch or "",
                    passive_tree_version=passive_tree_version or "",
                    ascendancy_key=ascendancy_key,
                    primary_skill_keys=primary_skill_keys,
                    build_family_keys=build_family_keys,
                    limit=10,
                )
                if family_discovery
                else self._query_build_family_rows(
                    con,
                    ascendancy_key=ascendancy_key,
                    primary_skill_keys=primary_skill_keys,
                    build_family_keys=build_family_keys,
                    limit=max(1, limit),
                )
                if explicit_family_filter
                else []
            )
            selected_family_keys = [str(row["build_family_key"]) for row in family_rows]
            record_rows = (
                []
                if family_discovery
                else self._query_deep_record_rows(
                    con,
                    query=query,
                    component_key_groups=component_key_groups,
                    limit=max(1, limit),
                    record_ids=record_ids,
                    build_family_keys=selected_family_keys,
                    record_kinds=record_kinds,
                    query_is_preference=explicit_family_filter,
                    game_patch=game_patch,
                    passive_tree_version=passive_tree_version,
                )
            )
            deep_records = [
                self._deep_record_result(row, include_content=detail_level == "record")
                for row in record_rows
            ]
            if not explicit_family_filter and not family_discovery:
                selected_family_keys = sorted(
                    {str(row["build_family_key"]) for row in record_rows if row["build_family_key"]}
                )
                # Natural-language queries that name a skill/gem should also surface the
                # families whose primary set contains that skill, even when their record
                # text (often Chinese) does not contain the query term verbatim.
                gem_family_keys = self._query_family_keys_by_gem_name(con, query)
                selected_family_keys = sorted(set(selected_family_keys) | gem_family_keys)
                family_rows = self._query_build_family_rows(
                    con,
                    ascendancy_key=None,
                    primary_skill_keys=[],
                    build_family_keys=selected_family_keys,
                    limit=max(1, limit),
                )
            build_families = (
                self._build_discovery_family_results(
                    con,
                    family_rows,
                    class_key=class_key or "",
                    game_patch=game_patch or "",
                    passive_tree_version=passive_tree_version or "",
                )
                if family_discovery
                else self._build_family_results(con, family_rows)
            )
            family_record_coverage: list[dict[str, Any]] = []
            family_record_index: list[dict[str, Any]] = []
            family_premise_catalog: list[dict[str, Any]] = []
            if not family_discovery and selected_family_keys:
                (
                    family_record_coverage,
                    family_record_index,
                    family_premise_catalog,
                ) = self._build_family_record_context(
                    con,
                    family_keys=selected_family_keys,
                    returned_record_ids={
                        str(row["record_id"]) for row in record_rows if row["record_id"]
                    },
                    game_patch=game_patch,
                    passive_tree_version=passive_tree_version,
                )
            family_keys = [str(row["buildFamilyKey"]) for row in build_families]
            scope_component_keys = {key for group in component_key_groups for key in group}
            for row in rows:
                scope_component_keys.update(_loads(row["component_keys"], []))
                scope_component_keys.update(_loads(row["affected_component_keys"], []))
            for row in record_rows:
                scope_component_keys.update(_loads(row["component_keys"], []))
            for family in build_families:
                scope_component_keys.update(
                    [
                        family["ascendancyKey"],
                        family["primarySkillKey"],
                        *family["secondarySkillKeys"],
                    ]
                )
            context_limit = max(1, limit)
            semantic_edges = (
                []
                if family_discovery
                else self._query_creator_semantic_edges(
                    con,
                    component_keys=sorted(str(key) for key in scope_component_keys if str(key)),
                    limit=context_limit,
                )
            )
            build_patterns = (
                []
                if family_discovery
                else self._query_creator_build_patterns(
                    con,
                    component_keys=sorted(str(key) for key in scope_component_keys if str(key)),
                    family_keys=family_keys,
                    limit=context_limit,
                )
            )
            transferable_patterns = (
                self._query_creator_transferable_patterns(
                    con,
                    query=query,
                    component_keys=sorted(str(key) for key in scope_component_keys if str(key)),
                    research_axes=research_axes,
                    exclude_origin_family_keys=family_keys,
                    limit=min(4, max(1, limit)),
                )
                if include_transferable and not family_discovery
                else []
            )
            request_contract = {
                "componentKeys": component_keys,
                # Family discovery has one stable contract: compare up to ten exact-version
                # Families. A caller-provided ordinary query limit must not silently shrink it.
                "limit": 10 if family_discovery else limit,
                "detailLevel": detail_level,
                "recordIds": record_ids,
                "includeTransferable": include_transferable,
                "researchAxes": research_axes,
                "ascendancyKey": ascendancy_key,
                "primarySkillKey": primary_skill_key,
                **({"primarySkillKeys": primary_skill_keys} if primary_skill_key else {}),
                "buildFamilyKeys": build_family_keys,
                "recordKinds": record_kinds,
                "classKey": class_key,
                "gamePatch": game_patch,
                "passiveTreeVersion": passive_tree_version,
            }
            result_contract = {
                "buildFamilies": sorted(
                    [
                        {
                            "buildFamilyKey": item["buildFamilyKey"],
                            "ascendancyKey": item["ascendancyKey"],
                            "primarySkillKey": item["primarySkillKey"],
                            "secondarySkillKeys": sorted(item["secondarySkillKeys"]),
                        }
                        for item in build_families
                    ],
                    key=lambda item: item["buildFamilyKey"],
                ),
                "deepRecordIds": sorted(item["recordId"] for item in deep_records),
                "deepReadRecordIds": (
                    sorted(item["recordId"] for item in deep_records)
                    if detail_level == "record"
                    else []
                ),
                "patternIds": sorted(
                    {str(item["patternId"]) for item in [*build_patterns, *transferable_patterns]}
                ),
                "semanticEdgeIds": sorted(item["edgeId"] for item in semantic_edges),
                "memoryItemIds": sorted(item["memoryItemId"] for item in results),
                "familyRecordCoverage": family_record_coverage,
                "familyPremiseCatalog": family_premise_catalog,
                "premiseAuditVersion": (PREMISE_AUDIT_VERSION if family_record_coverage else None),
            }
            dedupe_ref = (
                "dq-"
                + _stable_hash(
                    {
                        "query": _normalize_text(query),
                        "request": request_contract,
                        "result": result_contract,
                    }
                )[:16]
            )
            self._record_dedupe_query(
                con,
                dedupe_ref=dedupe_ref,
                query=query,
                component_keys=component_keys,
                request_contract=request_contract,
                result_contract=result_contract,
                now=now,
            )
            con.commit()
        finally:
            con.close()
        return {
            "status": "known",
            "dedupeQueryRef": dedupe_ref,
            "results": results,
            "deepResearchRecords": deep_records,
            "buildFamilies": build_families,
            "semanticEdges": semantic_edges,
            "buildPatterns": build_patterns,
            "transferablePatterns": transferable_patterns,
            "familyRecordCoverage": family_record_coverage,
            "familyRecordIndex": family_record_index,
            "familyPremiseCatalog": family_premise_catalog,
            "premiseAuditVersion": (PREMISE_AUDIT_VERSION if family_record_coverage else None),
            "requestedComponentKeys": component_keys,
            "requestedResearchAxes": research_axes,
            "requestedAscendancyKey": ascendancy_key,
            "requestedPrimarySkillKey": primary_skill_key,
            "requestedBuildFamilyKeys": build_family_keys,
            "requestedRecordKinds": record_kinds,
            "requestedClassKey": class_key,
            "requestedGamePatch": game_patch,
            "requestedPassiveTreeVersion": passive_tree_version,
            "includeTransferable": include_transferable,
            "retrievalPolicy": {
                "familyKnowledgePriority": "higher",
                "separateLanes": True,
                "scopeWeights": RESEARCH_MEMORY_SCOPE_WEIGHTS,
                "transferableConfidenceWeights": TRANSFER_CONFIDENCE_WEIGHTS,
                "transferableResultLimit": min(4, max(1, limit)),
                "originFamilyTransferablePatternsUseFamilyWeight": True,
                "transferableKnowledgeNeverOutranksEquivalentFamilyKnowledge": True,
            },
            "componentKeyGroups": component_key_groups,
            "detailLevel": detail_level,
            **(
                {
                    "familyDiscovery": {
                        "requestedCandidateCount": 10,
                        "returnedCandidateCount": len(build_families),
                        "coverage": (
                            "sufficient"
                            if len(build_families) >= 5
                            else "limited"
                            if len(build_families) >= 2
                            else "insufficient"
                        ),
                        "exactVersionOnly": True,
                        "didNotBackfillWithStaleFamilies": True,
                    }
                }
                if detail_level == "family"
                else {}
            ),
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def read_query_receipt(self, dedupe_query_ref: str) -> dict[str, Any] | None:
        """Read one copy-safe typed query/result receipt for Create provenance checks."""

        if not re.fullmatch(r"dq-[A-Fa-f0-9]{16}", str(dedupe_query_ref or "")):
            return None
        con = mature_learning.connect(self.db_path)
        try:
            row = con.execute(
                """
                SELECT dedupe_query_ref, query_hash, component_keys, request_contract,
                       result_contract, created_at, last_seen_at
                FROM research_dedupe_queries
                WHERE dedupe_query_ref = ?
                  AND visibility = 'creator_visible'
                  AND split = 'train_context'
                LIMIT 1
                """,
                (dedupe_query_ref,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        finally:
            con.close()
        if row is None:
            return None
        request = _loads(row["request_contract"], {})
        result = _loads(row["result_contract"], {})
        if not isinstance(request, dict) or not isinstance(result, dict) or not request:
            # Historical receipts remain valid for query-before-propose dedupe, but they cannot
            # authorize a new Create target.
            return None
        receipt = {
            "dedupeQueryRef": row["dedupe_query_ref"],
            "queryHash": row["query_hash"],
            "componentKeys": _loads(row["component_keys"], []),
            "request": request,
            "result": result,
            "createdAt": row["created_at"],
            "lastSeenAt": row["last_seen_at"],
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }
        if (
            copy_safety.find_forbidden_paths(receipt)
            or copy_safety.durable_knowledge_flags(receipt)
            or copy_safety.contains_raw_url(receipt)
        ):
            return None
        return receipt

    def _component_key_groups(self, component_keys: list[str]) -> list[list[str]]:
        """Expand graph-backed gem/active-skill identities without fuzzy matching."""

        adjacency: dict[str, set[str]] = {}
        if self.graph_service is not None:
            nodes_by_key = {node.stable_key: node for node in self.graph_service.snapshot.nodes}
            for edge in self.graph_service.snapshot.edges:
                if edge.status != "valid" or edge.edge_type not in {"grants_skill", "granted_by"}:
                    continue
                source = nodes_by_key.get(edge.source_key)
                target = nodes_by_key.get(edge.target_key)
                if source is None or target is None:
                    continue
                if {source.node_type, target.node_type} != {"skill_gem", "active_skill"}:
                    continue
                adjacency.setdefault(source.stable_key, set()).add(target.stable_key)
                adjacency.setdefault(target.stable_key, set()).add(source.stable_key)

        groups: set[tuple[str, ...]] = set()
        for component_key in component_keys:
            equivalents = {component_key}
            pending = [component_key]
            while pending:
                current = pending.pop()
                for candidate in adjacency.get(current, set()):
                    if candidate not in equivalents:
                        equivalents.add(candidate)
                        pending.append(candidate)
            groups.add(tuple(sorted(equivalents)))
        return [list(group) for group in sorted(groups)]

    def validate_deep_research_records(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate deep records for a safe review without persisting proposal data."""
        payload = _normalize_deep_record_version_context(payload)
        unsupported_pob_version = str(payload.pop("__unsupported_pob_version__", "") or "")
        if unsupported_pob_version:
            return research_models.rejection(
                "unsupported_pob_version",
                caveats=[
                    "PoB version must be one of the application-managed compatibility values."
                ],
                facts={"submittedPobVersion": unsupported_pob_version},
            )
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            return copy_error
        output = research_models.ResearcherOutput.model_validate(payload)
        records_by_group: dict[str, list[research_models.DeepResearchRecordProposal]] = {}
        for record in output.deep_research_records:
            records_by_group.setdefault(record.research_group_id, []).append(record)
        families_by_group = {
            group_id: research_identity.infer_build_family(records)
            for group_id, records in records_by_group.items()
        }
        for record in output.deep_research_records:
            scope_keys = [key for key in (record.class_key, record.ascendancy_key) if key]
            endpoint_error = self._component_endpoint_error([*record.component_keys, *scope_keys])
            if endpoint_error is not None:
                return endpoint_error
        unkeyed_records = [
            record.title
            for record in output.deep_research_records
            if families_by_group.get(record.research_group_id) is not None
            and research_identity.knowledge_key(record, families_by_group[record.research_group_id])
            is None
        ]
        family_keys = sorted(
            {family.key for family in families_by_group.values() if family is not None}
        )
        sibling_hints: list[dict[str, Any]] = []
        if family_keys and self.db_path and os.path.exists(self.db_path):
            try:
                con = mature_learning.connect(self.db_path)
                try:
                    sibling_hints = _sibling_family_hints(con, set(family_keys))
                finally:
                    con.close()
            except sqlite3.Error:
                # Sibling hints are an enhancement; a missing/uninitialized store must not
                # turn an otherwise valid validation into a failure.
                sibling_hints = []
        return {
            "status": "accepted",
            "validationOnly": True,
            "candidateRecordIds": [
                _deep_record_id(record) for record in output.deep_research_records
            ],
            "deepResearchRecordCount": len(output.deep_research_records),
            "unkeyedRecordCount": len(unkeyed_records),
            "unkeyedRecordTitles": unkeyed_records,
            "buildFamilyKeys": family_keys,
            "siblingFamilyHints": sibling_hints,
            "nextStep": "Write the validated candidates to the leased safe review and run accept.",
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def validate_research_fragments(
        self,
        payload: dict[str, Any],
        *,
        dedupe_query_ref: str | None = None,
    ) -> dict[str, Any]:
        """Validate fragment proposals and dedupe state without writing memory."""
        if not dedupe_query_ref:
            return research_models.rejection(
                "missing_dedupe_query",
                suggested_repair="Call query_research_memory before proposing a new fragment.",
            )
        if not self._dedupe_query_ref_exists(dedupe_query_ref):
            return research_models.rejection(
                "invalid_dedupe_query_ref",
                suggested_repair="Call query_research_memory in this memory store first.",
            )
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            return copy_error
        output = research_models.ResearcherOutput.model_validate(payload)
        con = mature_learning.connect(self.db_path)
        try:
            for fragment in output.fragments:
                duplicate = self._duplicate_fragment(con, fragment)
                if duplicate is not None:
                    return research_models.rejection(
                        "duplicate_fragment_candidate",
                        proposal_id=duplicate,
                        suggested_repair="Reference the existing fragment in the safe review.",
                        facts={"existingFragmentIds": [duplicate]},
                    )
        finally:
            con.close()
        return {
            "status": "accepted",
            "validationOnly": True,
            "candidateFragmentIds": [_fragment_id(fragment) for fragment in output.fragments],
            "fragmentCount": len(output.fragments),
            "nextStep": "Write the validated candidates to the leased safe review and run accept.",
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def validate_semantic_edges(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate semantic edges against graph and memory state without persisting them."""
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            return copy_error
        output = research_models.ResearcherOutput.model_validate(payload)
        con = mature_learning.connect(self.db_path)
        try:
            candidate_ids: list[str] = []
            for edge in output.semantic_edges:
                error = self._endpoint_resolution_error(edge)
                if error is None:
                    error = self._endpoint_error(edge.source_key, edge.target_key)
                if error is None:
                    error = self._semantic_conflict(con, edge)
                if error is not None:
                    return error
                candidate_ids.append(_edge_identity(edge)[0])
        finally:
            con.close()
        return {
            "status": "accepted",
            "validationOnly": True,
            "candidateEdgeIds": candidate_ids,
            "semanticEdgeCount": len(candidate_ids),
            "nextStep": "Write the validated candidates to the leased safe review and run accept.",
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def validate_build_patterns(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate observations and patterns without persisting proposal data."""
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            return copy_error
        output = research_models.ResearcherOutput.model_validate(payload)
        link_error = _pattern_observation_link_error(output)
        if link_error is not None:
            return link_error
        for observation in output.build_design_observations:
            error = self._observation_resolution_error(observation)
            if error is None:
                error = self._component_endpoint_error(
                    [component.component_key for component in observation.components]
                )
            if error is not None:
                return error
        for pattern in output.patterns:
            endpoint_error = self._component_endpoint_error(pattern.component_keys)
            if endpoint_error is not None:
                return endpoint_error
        return {
            "status": "accepted",
            "validationOnly": True,
            "candidateObservationIds": [
                _observation_id(observation) for observation in output.build_design_observations
            ],
            "candidatePatternIds": [_pattern_id(pattern) for pattern in output.patterns],
            "observationCount": len(output.build_design_observations),
            "patternCount": len(output.patterns),
            "nextStep": "Write the validated candidates to the leased safe review and run accept.",
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def propose_deep_research_records(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = _normalize_deep_record_version_context(payload)
        unsupported_pob_version = str(payload.pop("__unsupported_pob_version__", "") or "")
        if unsupported_pob_version:
            result = research_models.rejection(
                "unsupported_pob_version",
                caveats=[
                    "PoB version must be one of the application-managed compatibility values."
                ],
                facts={"submittedPobVersion": unsupported_pob_version},
            )
            self._record_rejection(payload, result)
            return result
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        for record in output.deep_research_records:
            scope_keys = [key for key in (record.class_key, record.ascendancy_key) if key]
            endpoint_error = self._component_endpoint_error([*record.component_keys, *scope_keys])
            if endpoint_error is not None:
                self._record_rejection(payload, endpoint_error)
                return endpoint_error

        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            record_ids: list[str] = []
            record_writes: list[dict[str, Any]] = []
            knowledge_keys: set[str] = set()
            build_family_keys: set[str] = set()
            created_record_count = 0
            updated_record_count = 0
            evidence_added_count = 0
            family_evidence_added_count = 0
            created_build_family_count = 0
            unkeyed_record_titles: list[str] = []
            records_by_group: dict[str, list[research_models.DeepResearchRecordProposal]] = {}
            for record in output.deep_research_records:
                records_by_group.setdefault(record.research_group_id, []).append(record)
            families_by_group = {
                group_id: research_identity.infer_build_family(records)
                for group_id, records in records_by_group.items()
            }
            family_relations: dict[str, tuple[str, str | None]] = {}
            for group_id, family in families_by_group.items():
                if family is None:
                    continue
                target, relation, src_key = self._resolve_family_target(con, family=family)
                if relation == "expand" and src_key is not None:
                    if (
                        con.execute(
                            "SELECT 1 FROM research_build_families WHERE build_family_key = ?",
                            (src_key,),
                        ).fetchone()
                        is None
                    ):
                        # The source family was already relocated by an earlier group in
                        # this payload; joining the expanded target directly is equivalent
                        # (records are keyed by knowledge key, not by family mount).
                        relation = "join"
                        src_key = None
                    else:
                        merge_result = self._merge_family_records(
                            con,
                            src_family_key=src_key,
                            dst_identity=target,
                            now=now,
                        )
                        con.execute(
                            """
                            INSERT INTO family_merge_log(
                                src_family_key, dst_family_key, dst_primary_skill_keys,
                                relation, moved, deprecated, merged_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                src_key,
                                merge_result["dst_family_key"],
                                _json(list(target.primary_skill_keys)),
                                "expand",
                                merge_result["moved"],
                                merge_result["deprecated"],
                                now,
                            ),
                        )
                families_by_group[group_id] = target
                family_relations[group_id] = (relation, src_key)
            for group_id, family in families_by_group.items():
                if family is None:
                    continue
                relation, _src_key = family_relations.get(group_id, ("new", None))
                if relation != "expand":
                    created_build_family_count += int(
                        con.execute(
                            "SELECT 1 FROM research_build_families WHERE build_family_key = ?",
                            (family.key,),
                        ).fetchone()
                        is None
                    )
                sources = sorted(
                    {
                        source
                        for record in records_by_group[group_id]
                        for source in record.source_case_refs
                    }
                )
                family_evidence_added_count += self._upsert_build_family(
                    con,
                    family=family,
                    source_case_refs=sources,
                    now=now,
                )
                build_family_keys.add(family.key)
            for record in output.deep_research_records:
                persisted = self._persist_deep_record(
                    con,
                    record=record,
                    family=families_by_group.get(record.research_group_id),
                    now=now,
                )
                canonical = con.execute(
                    """
                    SELECT record_id, research_group_id, build_family_key, knowledge_key,
                           evidence_count, record_kind, title, summary, content,
                           component_keys, source_case_refs, safe_evidence_refs
                    FROM deep_research_records
                    WHERE record_id = ?
                    """,
                    (persisted["record_id"],),
                ).fetchone()
                if canonical is None:
                    raise RuntimeError(
                        f"persisted deep research record missing: {persisted['record_id']}"
                    )
                record_ids.append(persisted["record_id"])
                record_writes.append(
                    {
                        "recordId": persisted["record_id"],
                        "researchGroupId": record.research_group_id,
                        "recordKind": record.record_kind,
                        "title": record.title,
                        "submittedTitle": record.title,
                        "canonicalRecord": {
                            "recordId": canonical["record_id"],
                            "researchGroupId": canonical["research_group_id"],
                            "buildFamilyKey": canonical["build_family_key"],
                            "knowledgeKey": canonical["knowledge_key"],
                            "evidenceCount": int(canonical["evidence_count"]),
                            "recordKind": canonical["record_kind"],
                            "title": canonical["title"],
                            "summary": canonical["summary"],
                            "componentKeys": _loads(canonical["component_keys"], []),
                            "sourceCaseRefs": _loads(canonical["source_case_refs"], []),
                            "safeEvidenceRefs": _loads(canonical["safe_evidence_refs"], []),
                        },
                        "canonicalContentMatchesSubmitted": (
                            canonical["title"] == record.title
                            and canonical["summary"] == record.summary
                            and canonical["content"] == record.content
                        ),
                        "created": bool(persisted["created"]),
                        "evidenceAddedCount": int(persisted["evidence_added_count"]),
                        "crossFamilyDuplicateAdvisories": list(
                            persisted.get("crossFamilyDuplicateAdvisories") or []
                        ),
                    }
                )
                if persisted["knowledge_key"]:
                    knowledge_keys.add(persisted["knowledge_key"])
                elif families_by_group.get(record.research_group_id) is not None:
                    unkeyed_record_titles.append(record.title)
                created_record_count += int(persisted["created"])
                updated_record_count += int(not persisted["created"])
                evidence_added_count += int(persisted["evidence_added_count"])
            sibling_hints = _sibling_family_hints(con, build_family_keys)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
        return {
            "status": "accepted",
            "recordIds": sorted(set(record_ids)),
            "recordWrites": record_writes,
            "knowledgeKeys": sorted(knowledge_keys),
            "buildFamilyKeys": sorted(build_family_keys),
            "siblingFamilyHints": sibling_hints,
            "createdRecordCount": created_record_count,
            "updatedRecordCount": updated_record_count,
            "evidenceAddedCount": evidence_added_count,
            "familyEvidenceAddedCount": family_evidence_added_count,
            "createdBuildFamilyCount": created_build_family_count,
            "unkeyedRecordCount": len(unkeyed_record_titles),
            "unkeyedRecordTitles": unkeyed_record_titles,
            "researchGroupIds": sorted(
                {record.research_group_id for record in output.deep_research_records}
            ),
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def _persist_deep_record(
        self,
        con: sqlite3.Connection,
        *,
        record: research_models.DeepResearchRecordProposal,
        family: research_identity.BuildFamilyIdentity | None,
        now: str,
    ) -> dict[str, Any]:
        knowledge_key = research_identity.knowledge_key(record, family) if family else None
        existing = None
        if knowledge_key:
            existing = con.execute(
                """
                SELECT * FROM deep_research_records
                WHERE knowledge_key = ? AND superseded_by_id IS NULL
                LIMIT 1
                """,
                (knowledge_key,),
            ).fetchone()
        adopted_by_id = False
        if existing is None and knowledge_key:
            # record_id is a deterministic function of knowledge_key, so the row occupying
            # hash(knowledge_key) is the same knowledge unit even when its stored key
            # drifted (historical backfill decoupling). Adopt it instead of INSERTing into
            # a taken primary key; the update path below reconciles the key and evidence.
            anchor_id = "drr-" + _stable_hash({"knowledge_key": knowledge_key})[:16]
            occupant = con.execute(
                "SELECT * FROM deep_research_records WHERE record_id = ?",
                (anchor_id,),
            ).fetchone()
            if occupant is not None:
                occupant_superseded_by = occupant["superseded_by_id"]
                occupant_status = str(occupant["status"] or "")
                if occupant_superseded_by is not None:
                    head = None
                    head_id = occupant_superseded_by
                    seen = {anchor_id}
                    while head_id is not None and head_id not in seen:
                        seen.add(head_id)
                        head = con.execute(
                            "SELECT * FROM deep_research_records WHERE record_id = ?",
                            (head_id,),
                        ).fetchone()
                        if head is None:
                            break
                        head_id = head["superseded_by_id"]
                    if head is not None and str(head["status"] or "") != "deprecated":
                        # The anchor id is a deprecated husk whose superseding chain head
                        # is still active: the unit lives on under the head. Re-point any
                        # husks that chained through this tombstone toward the active head
                        # (mirroring the reconciliation migration), then drop the husk so
                        # the fresh INSERT below recreates the anchor row from this case's
                        # content; reviving a calibration husk in place would leak
                        # uncalibrated content into queries.
                        con.execute(
                            """
                            UPDATE deep_research_records
                            SET superseded_by_id = ?
                            WHERE superseded_by_id = ?
                            """,
                            (head["record_id"], anchor_id),
                        )
                        con.execute(
                            "DELETE FROM deep_research_records WHERE record_id = ?",
                            (anchor_id,),
                        )
                    else:
                        # Dangling supersession chain: the husk is the only row for this
                        # anchor. Adopt it and let the update path revive it.
                        existing = occupant
                        adopted_by_id = True
                elif occupant_status == "quarantined":
                    # Quarantined material is never adopted; replace it with a fresh row.
                    con.execute(
                        "DELETE FROM deep_research_records WHERE record_id = ?",
                        (anchor_id,),
                    )
                else:
                    existing = occupant
                    adopted_by_id = True
        if existing is None:
            existing_id = self._existing_deep_record_id(con, record)
            if existing_id:
                existing = con.execute(
                    "SELECT * FROM deep_research_records WHERE record_id = ?",
                    (existing_id,),
                ).fetchone()

        cross_family_advisories = self._cross_family_duplicate_advisories(con, record, family)

        evidence_added_count = 0
        if knowledge_key:
            evidence_added_count = self._upsert_deep_record_evidence(
                con,
                knowledge_key=knowledge_key,
                record=record,
                now=now,
            )
        evidence_count = (
            int(
                con.execute(
                    "SELECT count(*) FROM deep_research_record_evidence WHERE knowledge_key = ?",
                    (knowledge_key,),
                ).fetchone()[0]
            )
            if knowledge_key
            else 0
        )

        if existing is None:
            record_id = (
                "drr-" + _stable_hash({"knowledge_key": knowledge_key})[:16]
                if knowledge_key
                else _deep_record_id(record)
            )
            values = self._deep_record_values(
                record,
                record_id=record_id,
                build_family_key=family.key if family else None,
                knowledge_key=knowledge_key,
                evidence_count=evidence_count,
                now=now,
            )
            columns = tuple(values)
            con.execute(
                f"INSERT INTO deep_research_records({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )
            return {
                "record_id": record_id,
                "knowledge_key": knowledge_key,
                "created": True,
                "evidence_added_count": evidence_added_count,
                "crossFamilyDuplicateAdvisories": cross_family_advisories,
            }

        record_id = str(existing["record_id"])
        old_knowledge_key = str(existing["knowledge_key"] or "")
        merged_sources = sorted(
            set(_loads(existing["source_case_refs"], [])) | set(record.source_case_refs)
        )
        merged_evidence = sorted(
            set(_loads(existing["safe_evidence_refs"], [])) | set(record.safe_evidence_refs)
        )
        identity_changed = bool(
            (knowledge_key and str(existing["knowledge_key"] or "") != knowledge_key)
            or (family and str(existing["build_family_key"] or "") != family.key)
        )
        stored_typed_payload = _loads(existing["typed_payload"], {})
        typed_identity_changed = any(
            key in record.typed_payload
            and stored_typed_payload.get(key) != record.typed_payload.get(key)
            for key in ("familyCoreSkillKeys", "resourceMechanisms")
        )
        same_source_revision = set(_loads(existing["source_case_refs"], [])) == set(
            record.source_case_refs
        )
        use_incoming = (
            identity_changed
            or adopted_by_id
            or typed_identity_changed
            # Quality ranking selects a representative across different sources. A newly
            # accepted review of the exact same source set is instead a revision and must
            # be able to correct shorter prose without being blocked by content length.
            or same_source_revision
            or (
                research_identity.record_quality(record)
                > research_identity.record_quality(existing)
            )
        )
        if use_incoming:
            values = self._deep_record_values(
                record,
                record_id=record_id,
                build_family_key=family.key if family else existing["build_family_key"],
                knowledge_key=knowledge_key or existing["knowledge_key"],
                evidence_count=evidence_count,
                now=now,
            )
            values["created_at"] = existing["created_at"]
            values["source_case_refs"] = _json(merged_sources)
            values["safe_evidence_refs"] = _json(merged_evidence)
            assignments = ", ".join(f"{column} = ?" for column in values if column != "record_id")
            con.execute(
                f"UPDATE deep_research_records SET {assignments} WHERE record_id = ?",
                tuple(values[column] for column in values if column != "record_id") + (record_id,),
            )
            if identity_changed and old_knowledge_key and old_knowledge_key != knowledge_key:
                # A same-source revision can legitimately correct the structured roles that form
                # its knowledge identity. The replacement evidence was written under the new key
                # above; retain no orphan evidence under the superseded identity once no record
                # references it.
                still_referenced = con.execute(
                    "SELECT 1 FROM deep_research_records WHERE knowledge_key = ? LIMIT 1",
                    (old_knowledge_key,),
                ).fetchone()
                if still_referenced is None:
                    con.execute(
                        "DELETE FROM deep_research_record_evidence WHERE knowledge_key = ?",
                        (old_knowledge_key,),
                    )
        else:
            con.execute(
                """
                UPDATE deep_research_records
                SET build_family_key = COALESCE(?, build_family_key),
                    knowledge_key = COALESCE(?, knowledge_key),
                    evidence_count = ?,
                    source_case_refs = ?,
                    safe_evidence_refs = ?,
                    last_seen_at = ?,
                    last_validated_at = ?
                WHERE record_id = ?
                """,
                (
                    family.key if family else None,
                    knowledge_key,
                    evidence_count,
                    _json(merged_sources),
                    _json(merged_evidence),
                    now,
                    now,
                    record_id,
                ),
            )
        return {
            "record_id": record_id,
            "knowledge_key": knowledge_key,
            "created": False,
            "evidence_added_count": evidence_added_count,
            "crossFamilyDuplicateAdvisories": cross_family_advisories,
        }

    def _cross_family_duplicate_advisories(
        self,
        con: sqlite3.Connection,
        record: research_models.DeepResearchRecordProposal,
        family: research_identity.BuildFamilyIdentity | None,
    ) -> list[str]:
        """Advisory-only cross-Family duplicate hint (never blocks, never rewrites).

        Flags only when another Build Family already holds a live record with the SAME
        recordKind and the SAME skill component-key set. Same-conclusion knowledge across
        families is otherwise a legitimate transferable pattern (transferablePatterns), so
        this hint is intentionally narrow and never prevents writing.
        """
        if family is None or not record.component_keys:
            return []
        current_keys = sorted(
            {str(key) for key in record.component_keys if str(key).startswith("skill:")}
        )
        if not current_keys:
            return []
        rows = con.execute(
            """
            SELECT record_id, build_family_key, title, component_keys
            FROM deep_research_records
            WHERE record_kind = ? AND superseded_by_id IS NULL AND status = 'valid'
              AND build_family_key IS NOT NULL AND build_family_key != ?
            """,
            (str(record.record_kind), family.key),
        ).fetchall()
        advisories: list[str] = []
        for row in rows:
            stored_keys = sorted(
                {
                    str(key)
                    for key in _loads(row["component_keys"], [])
                    if str(key).startswith("skill:")
                }
            )
            if stored_keys == current_keys:
                advisories.append(
                    f"同 recordKind + 完全相同 skill 组件集已存在于其他 Build Family "
                    f"({row['build_family_key']} / {row['title']})。若属同一知识的跨 Family 变体，"
                    f"这是合法可迁移记录（由 transferablePatterns 承载）；若为重复归档请复核。"
                )
        return advisories

    def _deep_record_values(
        self,
        record: research_models.DeepResearchRecordProposal,
        *,
        record_id: str,
        build_family_key: str | None,
        knowledge_key: str | None,
        evidence_count: int,
        now: str,
    ) -> dict[str, Any]:
        return {
            "record_id": record_id,
            "research_group_id": record.research_group_id,
            "build_family_key": build_family_key,
            "knowledge_key": knowledge_key,
            "evidence_count": evidence_count,
            "record_kind": record.record_kind,
            "title": record.title,
            "summary": record.summary,
            "content": record.content,
            "content_language": record.content_language,
            "length_exception_reason": record.length_exception_reason,
            "component_keys": _json(sorted(set(record.component_keys))),
            "component_mentions": _json(
                [mention.model_dump(mode="json") for mention in record.component_mentions]
            ),
            "source_case_refs": _json(sorted(set(record.source_case_refs))),
            "safe_evidence_refs": _json(sorted(set(record.safe_evidence_refs))),
            "conditions": _json(record.conditions),
            "failure_conditions": _json(record.failure_conditions),
            "typed_payload": _json(record.typed_payload),
            "class_key": record.class_key,
            "ascendancy_key": record.ascendancy_key,
            "extraction_method_version": record.extraction_method_version,
            "record_schema_version": record.record_schema_version,
            "game_patch": record.game_patch,
            "passive_tree_version": record.passive_tree_version,
            "pob_version_or_commit": record.pob_version_or_commit,
            "visibility": record.visibility,
            "split": record.split,
            "knowledge_scope": record.knowledge_scope,
            "status": record.status,
            "copy_safety_state": record.copy_safety_state,
            "current_version_context": _json(
                {
                    "game_patch": record.game_patch,
                    "passive_tree_version": record.passive_tree_version,
                    "pob_version_or_commit": record.pob_version_or_commit,
                }
            ),
            "created_at": now,
            "last_seen_at": now,
            "last_validated_at": now,
            "superseded_by_id": None,
        }

    def _resolve_family_target(
        self,
        con: sqlite3.Connection,
        *,
        family: research_identity.BuildFamilyIdentity,
    ) -> tuple[research_identity.BuildFamilyIdentity, str, str | None]:
        """Decide where a newly inferred identity belongs among existing families.

        Comparison happens on canonical primary-skill SETS (gem-equivalence expanded,
        plus model-confirmed equivalences from the ``skill_equivalence`` table).
        Returns ``(target_identity, relation, src_family_key)`` with relation in
        ``{"join", "expand", "new"}``:

        - ``join``: an existing family with an identical or superset canonical primary
          set already exists; the new knowledge joins it (no new family is created).
        - ``expand``: the new identity is a strict superset of an existing family's
          primary set; the existing family's records must be relocated into the expanded
          identity first (``_merge_family_records``), then the new knowledge joins.
        - ``new``: no containment relationship; a new family is created.
        """
        idx = skill_equivalence.SkillEquivalenceIndex.shared()
        canon_new = self._canonical_identity_set(con, family.primary_skill_keys, idx=idx)
        rows = con.execute(
            """
            SELECT build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys,
                   secondary_skill_keys, evidence_count
            FROM research_build_families
            WHERE ascendancy_key = ?
            ORDER BY evidence_count DESC, build_family_key
            """,
            (family.ascendancy_key,),
        ).fetchall()
        for row in rows:
            existing_keys = _loads(row["primary_skill_keys"], None)
            if not existing_keys:
                existing_keys = (
                    [str(row["primary_skill_key"] or "")] if row["primary_skill_key"] else []
                )
            if not existing_keys:
                continue
            existing_identity = research_identity.BuildFamilyIdentity(
                ascendancy_key=str(row["ascendancy_key"]),
                primary_skill_keys=tuple(sorted(existing_keys)),
                secondary_skill_keys=tuple(sorted(_loads(row["secondary_skill_keys"], []))),
                authoritative_key=str(row["build_family_key"]),
            )
            canon_existing = self._canonical_identity_set(con, existing_keys, idx=idx)
            if canon_new == canon_existing or canon_new <= canon_existing:
                return existing_identity, "join", None
            if canon_existing <= canon_new:
                merged = sorted(set(existing_keys) | set(family.primary_skill_keys))
                expanded = research_identity.BuildFamilyIdentity(
                    ascendancy_key=family.ascendancy_key,
                    primary_skill_keys=tuple(merged),
                    secondary_skill_keys=tuple(
                        sorted(
                            set(existing_identity.secondary_skill_keys)
                            | set(family.secondary_skill_keys)
                        )
                    ),
                )
                return expanded, "expand", str(row["build_family_key"])
        return family, "new", None

    @staticmethod
    def _canonical_identity_set(
        con: sqlite3.Connection,
        skill_keys: Iterable[str],
        *,
        idx: skill_equivalence.SkillEquivalenceIndex | None = None,
    ) -> frozenset[str]:
        """Canonical primary-set token with gem AND model-confirmed equivalence applied.

        Deterministic gem equivalence (same granting gem -> same token) is applied first;
        then any ``skill_equivalence`` rows (model-confirmed renames/aliases) union their
        canonical tokens into one equivalence class. Unresolvable ``key:`` tokens are
        skipped by the model layer (they cannot be trusted as aliases).

        Unique-gem variants deliberately share the canonical token with their ordinary
        version (``skill:UniqueBreachLightningBoltPlayer`` -> ``gem:lightningbolt`` like
        ``skill:LightningBoltPlayer``): same-name skill variants are one family identity.
        Their mechanical differences (cooldown/triggered) are preserved at the record/
        evidence layer via the exact component key, never by splitting the identity.
        Variants whose granting gem has no display name in the index stay on a distinct
        ``key:`` token until a model-confirmed ``skill_equivalence`` row unions them.
        """
        index = idx or skill_equivalence.SkillEquivalenceIndex.shared()
        canon = index.canonical_set(skill_keys)
        if not canon:
            return canon
        rows = con.execute(
            "SELECT key_a, key_b FROM skill_equivalence WHERE status = 'valid'"
        ).fetchall()
        if not rows:
            return canon
        parent: dict[str, str] = {}

        def find(token: str) -> str:
            while parent.get(token, token) != token:
                token = parent[token]
            return token

        def union(a: str, b: str) -> None:
            root_a, root_b = find(a), find(b)
            if root_a != root_b:
                parent[max(root_a, root_b)] = min(root_a, root_b)

        for key_a, key_b in rows:
            token_a = index.canonical_key(str(key_a))
            token_b = index.canonical_key(str(key_b))
            if token_a.startswith("key:") or token_b.startswith("key:"):
                continue
            union(token_a, token_b)
        return frozenset({find(token) for token in canon})

    def _merge_family_records(
        self,
        con: sqlite3.Connection,
        *,
        src_family_key: str,
        dst_identity: research_identity.BuildFamilyIdentity,
        now: str,
        merge_log: list[dict[str, Any]] | None = None,
        dst_key: str | None = None,
    ) -> dict[str, Any]:
        """Relocate every record of ``src_family_key`` under ``dst_identity``.

        Knowledge keys are preserved (knowledge identity is stable across family
        relocation); only the family mount point changes. When the destination already
        holds a live record with the same knowledge key, the richer record survives and
        the other is deprecated (``superseded_by_id``) with its evidence re-hung.

        ``dst_key`` pins the destination family key (used when joining an existing family
        whose stored key is authoritative); when omitted the identity key is used (the
        expand path, where the primary set changed and a new key is required).

        Returns ``{"moved": n, "deprecated": n, "dst_family_key": key}``.
        """
        dst_key = str(dst_key or dst_identity.key)
        src_key = str(src_family_key)
        if src_key == dst_key:
            raise ValueError(f"family merge requires distinct families (src == dst == {src_key})")
        src_sources = sorted(
            {
                str(row[0])
                for row in con.execute(
                    "SELECT DISTINCT source_case_ref FROM research_build_family_evidence "
                    "WHERE build_family_key = ?",
                    (src_key,),
                ).fetchall()
            }
        )
        dst_exists = (
            con.execute(
                "SELECT 1 FROM research_build_families WHERE build_family_key = ?",
                (dst_key,),
            ).fetchone()
            is not None
        )
        if not dst_exists:
            con.execute(
                """
                INSERT INTO research_build_families(
                    build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys,
                    secondary_skill_keys, evidence_count, created_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    dst_key,
                    dst_identity.ascendancy_key,
                    dst_identity.primary_skill_key,
                    _json(list(dst_identity.primary_skill_keys)),
                    _json(list(dst_identity.secondary_skill_keys)),
                    now,
                    now,
                ),
            )
        for source_ref in src_sources:
            con.execute(
                """
                INSERT INTO research_build_family_evidence(
                    build_family_key, source_case_ref, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(build_family_key, source_case_ref) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at
                """,
                (dst_key, source_ref, now, now),
            )
        moved = 0
        deprecated = 0
        rows = con.execute(
            "SELECT * FROM deep_research_records WHERE build_family_key = ?",
            (src_key,),
        ).fetchall()
        for row in rows:
            record_id = str(row["record_id"])
            knowledge_key = row["knowledge_key"]
            if knowledge_key:
                occupant = con.execute(
                    """
                    SELECT record_id, status FROM deep_research_records
                    WHERE knowledge_key = ? AND build_family_key = ?
                      AND status IN ('valid', 'needs_revalidation')
                    LIMIT 1
                    """,
                    (knowledge_key, dst_key),
                ).fetchone()
                if occupant is not None and str(occupant["record_id"]) != record_id:
                    occupant_row = con.execute(
                        "SELECT * FROM deep_research_records WHERE record_id = ?",
                        (str(occupant["record_id"]),),
                    ).fetchone()
                    candidate = research_identity.record_quality(row)
                    incumbent = research_identity.record_quality(occupant_row)
                    if candidate > incumbent:
                        con.execute(
                            """
                            UPDATE deep_research_records
                            SET status = 'deprecated', superseded_by_id = ?
                            WHERE record_id = ?
                            """,
                            (record_id, str(occupant["record_id"])),
                        )
                        con.execute(
                            "UPDATE deep_research_records SET build_family_key = ? WHERE record_id = ?",
                            (dst_key, record_id),
                        )
                        deprecated += 1
                        moved += 1
                    else:
                        con.execute(
                            """
                            UPDATE deep_research_records
                            SET status = 'deprecated', superseded_by_id = ?, build_family_key = ?
                            WHERE record_id = ?
                            """,
                            (record_id, str(occupant["record_id"]), dst_key),
                        )
                        deprecated += 1
                    continue
            con.execute(
                "UPDATE deep_research_records SET build_family_key = ? WHERE record_id = ?",
                (dst_key, record_id),
            )
            moved += 1
        con.execute(
            """
            UPDATE research_build_families
            SET evidence_count = (
                SELECT count(*) FROM research_build_family_evidence
                WHERE build_family_key = ?
            ), last_seen_at = ?
            WHERE build_family_key = ?
            """,
            (dst_key, now, dst_key),
        )
        con.execute(
            "DELETE FROM research_build_families WHERE build_family_key = ?",
            (src_key,),
        )
        pattern_rows = con.execute(
            "SELECT pattern_id, origin_family_keys FROM research_build_patterns "
            "WHERE origin_family_keys LIKE ?",
            (f"%{src_key}%",),
        ).fetchall()
        for pattern_row in pattern_rows:
            origin = _loads(pattern_row["origin_family_keys"], [])
            if src_key in origin:
                origin = [dst_key if key == src_key else key for key in origin]
                con.execute(
                    "UPDATE research_build_patterns SET origin_family_keys = ? WHERE pattern_id = ?",
                    (_json(origin), str(pattern_row["pattern_id"])),
                )
        if merge_log is not None:
            merge_log.append(
                {
                    "src_family_key": src_key,
                    "dst_family_key": dst_key,
                    "dst_primary_skill_keys": list(dst_identity.primary_skill_keys),
                    "moved": moved,
                    "deprecated": deprecated,
                    "at": now,
                }
            )
        return {"moved": moved, "deprecated": deprecated, "dst_family_key": dst_key}

    def _upsert_build_family(
        self,
        con: sqlite3.Connection,
        *,
        family: research_identity.BuildFamilyIdentity,
        source_case_refs: list[str],
        now: str,
    ) -> int:
        con.execute(
            """
            INSERT INTO research_build_families(
                build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys,
                secondary_skill_keys, evidence_count, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(build_family_key) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (
                family.key,
                family.ascendancy_key,
                family.primary_skill_key,
                _json(list(family.primary_skill_keys)),
                _json(list(family.secondary_skill_keys)),
                now,
                now,
            ),
        )
        added = 0
        for source_ref in sorted(set(source_case_refs)):
            exists = con.execute(
                """
                SELECT 1 FROM research_build_family_evidence
                WHERE build_family_key = ? AND source_case_ref = ?
                """,
                (family.key, source_ref),
            ).fetchone()
            added += int(exists is None)
            con.execute(
                """
                INSERT INTO research_build_family_evidence(
                    build_family_key, source_case_ref, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(build_family_key, source_case_ref) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at
                """,
                (family.key, source_ref, now, now),
            )
        con.execute(
            """
            UPDATE research_build_families
            SET evidence_count = (
                SELECT count(*) FROM research_build_family_evidence
                WHERE build_family_key = ?
            ), last_seen_at = ?
            WHERE build_family_key = ?
            """,
            (family.key, now, family.key),
        )
        return added

    def _upsert_deep_record_evidence(
        self,
        con: sqlite3.Connection,
        *,
        knowledge_key: str,
        record: research_models.DeepResearchRecordProposal,
        now: str,
    ) -> int:
        added = 0
        for source_ref in sorted(set(record.source_case_refs)):
            existing = con.execute(
                """
                SELECT safe_evidence_refs FROM deep_research_record_evidence
                WHERE knowledge_key = ? AND source_case_ref = ?
                """,
                (knowledge_key, source_ref),
            ).fetchone()
            added += int(existing is None)
            safe_refs = sorted(
                set(record.safe_evidence_refs)
                | (set(_loads(existing["safe_evidence_refs"], [])) if existing else set())
            )
            con.execute(
                """
                INSERT INTO deep_research_record_evidence(
                    knowledge_key, source_case_ref, safe_evidence_refs,
                    observed_component_keys, observed_component_mentions, conditions,
                    failure_conditions, game_patch, passive_tree_version,
                    pob_version_or_commit, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(knowledge_key, source_case_ref) DO UPDATE SET
                    safe_evidence_refs = excluded.safe_evidence_refs,
                    observed_component_keys = excluded.observed_component_keys,
                    observed_component_mentions = excluded.observed_component_mentions,
                    conditions = excluded.conditions,
                    failure_conditions = excluded.failure_conditions,
                    game_patch = excluded.game_patch,
                    passive_tree_version = excluded.passive_tree_version,
                    pob_version_or_commit = excluded.pob_version_or_commit,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    knowledge_key,
                    source_ref,
                    _json(safe_refs),
                    _json(sorted(set(record.component_keys))),
                    _json(
                        [mention.model_dump(mode="json") for mention in record.component_mentions]
                    ),
                    _json(record.conditions),
                    _json(record.failure_conditions),
                    record.game_patch,
                    record.passive_tree_version,
                    record.pob_version_or_commit,
                    now,
                    now,
                ),
            )
        return added

    def _existing_deep_record_id(
        self,
        con: sqlite3.Connection,
        record: research_models.DeepResearchRecordProposal,
    ) -> str | None:
        rows = con.execute(
            """
            SELECT record_id, title, source_case_refs
            FROM deep_research_records
            WHERE research_group_id = ? AND record_kind = ?
            """,
            (record.research_group_id, record.record_kind),
        ).fetchall()
        wanted_title = _normalize_text(record.title)
        wanted_sources = sorted(set(record.source_case_refs))
        for row in rows:
            try:
                stored_sources = sorted(set(json.loads(str(row["source_case_refs"]))))
            except (json.JSONDecodeError, TypeError):
                continue
            if (
                _normalize_text(str(row["title"])) == wanted_title
                and stored_sources == wanted_sources
            ):
                return str(row["record_id"])
        return None

    def propose_research_fragments(
        self,
        payload: dict[str, Any],
        *,
        dedupe_query_ref: str | None = None,
    ) -> dict[str, Any]:
        if not dedupe_query_ref:
            result = research_models.rejection(
                "missing_dedupe_query",
                suggested_repair="Call query_research_memory before proposing a new fragment.",
            )
            self._record_rejection(payload, result)
            return result
        if not self._dedupe_query_ref_exists(dedupe_query_ref):
            result = research_models.rejection(
                "invalid_dedupe_query_ref",
                suggested_repair=(
                    "Call query_research_memory in this memory store before proposing a new "
                    "fragment, then pass back the returned dedupeQueryRef."
                ),
            )
            self._record_rejection(payload, result)
            return result

        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            fragment_ids: list[str] = []
            for fragment in output.fragments:
                duplicate = self._duplicate_fragment(con, fragment)
                if duplicate is not None:
                    result = research_models.rejection(
                        "duplicate_fragment_candidate",
                        proposal_id=duplicate,
                        suggested_repair="Call append_evidence_to_fragment for the existing fragment.",
                        facts={"existingFragmentIds": [duplicate]},
                    )
                    self._record_rejection(payload, result, con=con)
                    con.commit()
                    return result
                fragment_id = _fragment_id(fragment)
                self._insert_fragment(con, fragment_id, fragment, now)
                self._insert_fragment_evidence(
                    con,
                    fragment_id=fragment_id,
                    source_case_refs=fragment.source_case_refs,
                    safe_evidence_refs=fragment.safe_evidence_refs,
                    game_patch=fragment.game_patch,
                    passive_tree_version=fragment.passive_tree_version,
                    pob_version_or_commit=fragment.pob_version_or_commit,
                    visibility=fragment.visibility,
                    split=fragment.split,
                    knowledge_scope=fragment.knowledge_scope,
                    confidence=fragment.confidence,
                    now=now,
                )
                fragment_ids.append(fragment_id)
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "fragmentIds": fragment_ids,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def append_evidence_to_fragment(
        self,
        *,
        fragment_id: str,
        source_case_refs: list[str],
        safe_evidence_refs: list[str],
        game_patch: str,
        passive_tree_version: str,
        pob_version_or_commit: str,
        visibility: str,
        split: str,
        knowledge_scope: str,
        confidence: str,
    ) -> dict[str, Any]:
        copy_error = _copy_safety_error(
            {
                "source_case_refs": source_case_refs,
                "safe_evidence_refs": safe_evidence_refs,
                "game_patch": game_patch,
                "passive_tree_version": passive_tree_version,
                "pob_version_or_commit": pob_version_or_commit,
                "visibility": visibility,
                "split": split,
                "knowledge_scope": knowledge_scope,
                "confidence": confidence,
            }
        )
        if copy_error is not None:
            return copy_error
        con = mature_learning.connect(self.db_path)
        try:
            row = con.execute(
                "SELECT * FROM research_fragments WHERE fragment_id = ?",
                (fragment_id,),
            ).fetchone()
            if row is None:
                return research_models.rejection("missing_fragment")
            if (
                row["visibility"] != visibility
                or row["split"] != split
                or row["knowledge_scope"] != knowledge_scope
            ):
                return research_models.rejection("holdout_boundary_violation")
            now = _now()
            self._insert_fragment_evidence(
                con,
                fragment_id=fragment_id,
                source_case_refs=source_case_refs,
                safe_evidence_refs=safe_evidence_refs,
                game_patch=game_patch,
                passive_tree_version=passive_tree_version,
                pob_version_or_commit=pob_version_or_commit,
                visibility=visibility,
                split=split,
                knowledge_scope=knowledge_scope,
                confidence=confidence,
                now=now,
            )
            con.commit()
            count = con.execute(
                "SELECT evidence_count FROM research_fragments WHERE fragment_id = ?",
                (fragment_id,),
            ).fetchone()["evidence_count"]
        finally:
            con.close()
        return {
            "status": "accepted",
            "fragmentId": fragment_id,
            "evidenceCount": count,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def propose_semantic_edges(self, payload: dict[str, Any]) -> dict[str, Any]:
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            edge_ids: list[str] = []
            for edge in output.semantic_edges:
                resolution_error = self._endpoint_resolution_error(edge)
                if resolution_error is not None:
                    self._record_rejection(payload, resolution_error, con=con)
                    con.commit()
                    return resolution_error
                endpoint_error = self._endpoint_error(edge.source_key, edge.target_key)
                if endpoint_error is not None:
                    self._record_rejection(payload, endpoint_error, con=con)
                    con.commit()
                    return endpoint_error
                conflict = self._semantic_conflict(con, edge)
                if conflict is not None:
                    self._record_rejection(payload, conflict, con=con)
                    con.commit()
                    return conflict
                edge_id, source_key, target_key = _edge_identity(edge)
                planner_visible = _planner_visible(edge.status, edge.copy_safety_state)
                con.execute(
                    """
                    INSERT INTO research_semantic_edges(
                        edge_id, source_key, target_key, canonical_source_key, canonical_target_key,
                        edge_type, rationale, source_case_refs, safe_evidence_refs, game_patch,
                        passive_tree_version, pob_version_or_commit, status, confidence,
                        modelability, copy_safety_state, context_requirements,
                        affected_component_keys, visibility, split, knowledge_scope,
                        directionality, planner_visible, current_version_context,
                        created_at, last_seen_at, last_validated_at, superseded_by_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(edge_id) DO UPDATE SET
                        rationale = excluded.rationale,
                        safe_evidence_refs = excluded.safe_evidence_refs,
                        status = excluded.status,
                        confidence = excluded.confidence,
                        copy_safety_state = excluded.copy_safety_state,
                        context_requirements = excluded.context_requirements,
                        affected_component_keys = excluded.affected_component_keys,
                        planner_visible = excluded.planner_visible,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        edge_id,
                        edge.source_key,
                        edge.target_key,
                        source_key,
                        target_key,
                        edge.edge_type,
                        edge.rationale,
                        _json(edge.source_case_refs),
                        _json(edge.safe_evidence_refs),
                        edge.game_patch,
                        edge.passive_tree_version,
                        edge.pob_version_or_commit,
                        edge.status,
                        edge.confidence,
                        edge.modelability,
                        edge.copy_safety_state,
                        _json(
                            [
                                item.model_dump(exclude_none=True, exclude_defaults=True)
                                for item in edge.context_requirements
                            ]
                        ),
                        _json(sorted(set(edge.affected_component_keys))),
                        edge.visibility,
                        edge.split,
                        edge.knowledge_scope,
                        edge.directionality,
                        planner_visible,
                        _json(
                            {
                                "game_patch": edge.game_patch,
                                "passive_tree_version": edge.passive_tree_version,
                                "pob_version_or_commit": edge.pob_version_or_commit,
                            }
                        ),
                        now,
                        now,
                        now,
                    ),
                )
                edge_ids.append(edge_id)
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "edgeIds": edge_ids,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def propose_build_patterns(self, payload: dict[str, Any]) -> dict[str, Any]:
        validation = research_models.validate_researcher_output(payload)
        if validation["status"] == "error":
            self._record_rejection(payload, validation)
            return validation
        copy_error = _copy_safety_error(payload)
        if copy_error is not None:
            self._record_rejection(payload, copy_error)
            return copy_error

        output = research_models.ResearcherOutput.model_validate(payload)
        observation_link_error = _pattern_observation_link_error(output)
        if observation_link_error is not None:
            self._record_rejection(payload, observation_link_error)
            return observation_link_error
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            observation_ids: list[str] = []
            pattern_ids: list[str] = []
            transfer_candidate_ids: list[str] = []
            promoted_pattern_ids: list[str] = []
            for observation in output.build_design_observations:
                resolution_error = self._observation_resolution_error(observation)
                if resolution_error is not None:
                    self._record_rejection(payload, resolution_error, con=con)
                    con.commit()
                    return resolution_error
                endpoint_error = self._component_endpoint_error(
                    [component.component_key for component in observation.components]
                )
                if endpoint_error is not None:
                    self._record_rejection(payload, endpoint_error, con=con)
                    con.commit()
                    return endpoint_error
                observation_id = _observation_id(observation)
                con.execute(
                    """
                    INSERT INTO research_build_design_observations(
                        observation_id, observation_type, title, summary, axes, components,
                        component_keys, source_case_refs, safe_evidence_refs, game_patch,
                        passive_tree_version, pob_version_or_commit, visibility, split,
                        knowledge_scope, copy_safety_state, created_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'passed', ?, ?)
                    ON CONFLICT(observation_id) DO UPDATE SET
                        observation_type = excluded.observation_type,
                        title = excluded.title,
                        summary = excluded.summary,
                        axes = excluded.axes,
                        components = excluded.components,
                        component_keys = excluded.component_keys,
                        source_case_refs = excluded.source_case_refs,
                        safe_evidence_refs = excluded.safe_evidence_refs,
                        game_patch = excluded.game_patch,
                        passive_tree_version = excluded.passive_tree_version,
                        pob_version_or_commit = excluded.pob_version_or_commit,
                        visibility = excluded.visibility,
                        split = excluded.split,
                        knowledge_scope = excluded.knowledge_scope,
                        copy_safety_state = excluded.copy_safety_state,
                        last_seen_at = excluded.last_seen_at
                    """,
                    (
                        observation_id,
                        observation.observation_type,
                        observation.title,
                        observation.summary,
                        _json(sorted(set(observation.axes))),
                        _json(
                            [
                                component.model_dump(exclude_none=True, exclude_defaults=True)
                                for component in observation.components
                            ]
                        ),
                        _json(
                            sorted(
                                {component.component_key for component in observation.components}
                            )
                        ),
                        _json(observation.source_case_refs),
                        _json(observation.safe_evidence_refs),
                        observation.game_patch,
                        observation.passive_tree_version,
                        observation.pob_version_or_commit,
                        observation.visibility,
                        observation.split,
                        observation.knowledge_scope,
                        now,
                        now,
                    ),
                )
                observation_ids.append(observation_id)

            for pattern in output.patterns:
                endpoint_error = self._component_endpoint_error(pattern.component_keys)
                if endpoint_error is not None:
                    self._record_rejection(payload, endpoint_error, con=con)
                    con.commit()
                    return endpoint_error
                pattern, pattern_id, transfer_key, promoted = _prepare_pattern_for_persistence(
                    con, pattern
                )
                planner_visible = _pattern_planner_visible(pattern)
                con.execute(
                    """
                    INSERT INTO research_build_patterns(
                        pattern_id, pattern_type, title, summary, component_keys,
                        component_roles, confidence_tier, transfer_scope, transfer_key,
                        applicability_axes, applicability_requirements, exclusion_conditions,
                        transfer_rationale, origin_family_keys, sample_count, family_count,
                        source_diversity_count, denominator, source_case_refs,
                        safe_evidence_refs, context_requirements, planner_hint,
                        verification_tasks, game_patch, passive_tree_version,
                        pob_version_or_commit, visibility, split, knowledge_scope,
                        status, copy_safety_state, current_version_context, planner_visible,
                        created_at, last_seen_at, last_validated_at, superseded_by_id
                    ) VALUES (
                        :pattern_id, :pattern_type, :title, :summary, :component_keys,
                        :component_roles, :confidence_tier, :transfer_scope, :transfer_key,
                        :applicability_axes, :applicability_requirements, :exclusion_conditions,
                        :transfer_rationale, :origin_family_keys, :sample_count, :family_count,
                        :source_diversity_count, :denominator, :source_case_refs,
                        :safe_evidence_refs, :context_requirements, :planner_hint,
                        :verification_tasks, :game_patch, :passive_tree_version,
                        :pob_version_or_commit, :visibility, :split, :knowledge_scope,
                        'valid', 'passed', :current_version_context, :planner_visible,
                        :created_at, :last_seen_at, :last_validated_at, NULL
                    )
                    ON CONFLICT(pattern_id) DO UPDATE SET
                        title = excluded.title,
                        summary = excluded.summary,
                        component_keys = excluded.component_keys,
                        component_roles = excluded.component_roles,
                        source_case_refs = excluded.source_case_refs,
                        safe_evidence_refs = excluded.safe_evidence_refs,
                        context_requirements = excluded.context_requirements,
                        planner_hint = excluded.planner_hint,
                        verification_tasks = excluded.verification_tasks,
                        confidence_tier = excluded.confidence_tier,
                        transfer_scope = excluded.transfer_scope,
                        transfer_key = excluded.transfer_key,
                        applicability_axes = excluded.applicability_axes,
                        applicability_requirements = excluded.applicability_requirements,
                        exclusion_conditions = excluded.exclusion_conditions,
                        transfer_rationale = excluded.transfer_rationale,
                        origin_family_keys = excluded.origin_family_keys,
                        sample_count = excluded.sample_count,
                        family_count = excluded.family_count,
                        source_diversity_count = excluded.source_diversity_count,
                        denominator = excluded.denominator,
                        pob_version_or_commit = excluded.pob_version_or_commit,
                        status = excluded.status,
                        copy_safety_state = excluded.copy_safety_state,
                        current_version_context = excluded.current_version_context,
                        planner_visible = excluded.planner_visible,
                        last_seen_at = excluded.last_seen_at,
                        last_validated_at = excluded.last_validated_at
                    """,
                    {
                        "pattern_id": pattern_id,
                        "pattern_type": pattern.pattern_type,
                        "title": pattern.title,
                        "summary": pattern.summary,
                        "component_keys": _json(sorted(set(pattern.component_keys))),
                        "component_roles": _json(dict(sorted(pattern.component_roles.items()))),
                        "confidence_tier": pattern.confidence_tier,
                        "transfer_scope": pattern.transfer_scope,
                        "transfer_key": transfer_key,
                        "applicability_axes": _json(sorted(set(pattern.applicability_axes))),
                        "applicability_requirements": _json(pattern.applicability_requirements),
                        "exclusion_conditions": _json(pattern.exclusion_conditions),
                        "transfer_rationale": pattern.transfer_rationale,
                        "origin_family_keys": _json(sorted(set(pattern.origin_family_keys))),
                        "sample_count": pattern.sample_count,
                        "family_count": pattern.family_count,
                        "source_diversity_count": pattern.source_diversity_count,
                        "denominator": pattern.denominator,
                        "source_case_refs": _json(pattern.source_case_refs),
                        "safe_evidence_refs": _json(pattern.safe_evidence_refs),
                        "context_requirements": _json(
                            [
                                item.model_dump(exclude_none=True, exclude_defaults=True)
                                for item in pattern.context_requirements
                            ]
                        ),
                        "planner_hint": pattern.planner_hint,
                        "verification_tasks": _json(pattern.verification_tasks),
                        "game_patch": pattern.game_patch,
                        "passive_tree_version": pattern.passive_tree_version,
                        "pob_version_or_commit": pattern.pob_version_or_commit,
                        "visibility": pattern.visibility,
                        "split": pattern.split,
                        "knowledge_scope": pattern.knowledge_scope,
                        "current_version_context": _json(
                            {
                                "game_patch": pattern.game_patch,
                                "passive_tree_version": pattern.passive_tree_version,
                                "pob_version_or_commit": pattern.pob_version_or_commit,
                            }
                        ),
                        "planner_visible": planner_visible,
                        "created_at": now,
                        "last_seen_at": now,
                        "last_validated_at": now,
                    },
                )
                pattern_ids.append(pattern_id)
                if pattern.transfer_scope != "family":
                    transfer_candidate_ids.append(pattern_id)
                if promoted:
                    promoted_pattern_ids.append(pattern_id)
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "observationIds": observation_ids,
            "patternIds": pattern_ids,
            "transferCandidateIds": transfer_candidate_ids,
            "promotedPatternIds": promoted_pattern_ids,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def apply_patch_decay(
        self,
        *,
        changed_component_keys: list[str],
        new_version_context: dict[str, str],
    ) -> dict[str, Any]:
        changed = set(changed_component_keys)
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            fragment_rows = con.execute(
                "SELECT fragment_id, affected_component_keys, status FROM research_fragments"
            ).fetchall()
            fragments_updated = 0
            for row in fragment_rows:
                affected = set(_loads(row["affected_component_keys"], []))
                if not (changed & affected):
                    continue
                con.execute(
                    """
                    UPDATE research_fragments
                    SET status = 'needs_revalidation',
                        current_version_context = ?,
                        last_seen_at = ?
                    WHERE fragment_id = ?
                    """,
                    (_json(new_version_context), now, row["fragment_id"]),
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO research_decay_events(
                        event_id, target_kind, target_id, decay_scope, old_status, new_status,
                        changed_component_keys, new_version_context, created_at
                    ) VALUES (?, 'fragment', ?, 'component_scoped', ?, 'needs_revalidation', ?, ?, ?)
                    """,
                    (
                        "decay-" + _stable_hash([row["fragment_id"], changed_component_keys])[:16],
                        row["fragment_id"],
                        row["status"],
                        _json(sorted(changed)),
                        _json(new_version_context),
                        now,
                    ),
                )
                fragments_updated += 1
            edge_rows = con.execute(
                "SELECT edge_id, affected_component_keys, status FROM research_semantic_edges"
            ).fetchall()
            edges_updated = 0
            for row in edge_rows:
                affected = set(_loads(row["affected_component_keys"], []))
                if not (changed & affected):
                    continue
                con.execute(
                    """
                    UPDATE research_semantic_edges
                    SET status = 'needs_revalidation',
                        planner_visible = 0,
                        current_version_context = ?,
                        last_seen_at = ?
                    WHERE edge_id = ?
                    """,
                    (_json(new_version_context), now, row["edge_id"]),
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO research_decay_events(
                        event_id, target_kind, target_id, decay_scope, old_status, new_status,
                        changed_component_keys, new_version_context, created_at
                    ) VALUES (?, 'semantic_edge', ?, 'component_scoped', ?, 'needs_revalidation', ?, ?, ?)
                    """,
                    (
                        "decay-"
                        + _stable_hash(["edge", row["edge_id"], changed_component_keys])[:16],
                        row["edge_id"],
                        row["status"],
                        _json(sorted(changed)),
                        _json(new_version_context),
                        now,
                    ),
                )
                edges_updated += 1
            pattern_rows = con.execute(
                "SELECT pattern_id, component_keys, status FROM research_build_patterns"
            ).fetchall()
            patterns_updated = 0
            for row in pattern_rows:
                affected = set(_loads(row["component_keys"], []))
                if not (changed & affected):
                    continue
                con.execute(
                    """
                    UPDATE research_build_patterns
                    SET status = 'needs_revalidation',
                        planner_visible = 0,
                        current_version_context = ?,
                        last_seen_at = ?
                    WHERE pattern_id = ?
                    """,
                    (_json(new_version_context), now, row["pattern_id"]),
                )
                con.execute(
                    """
                    INSERT OR REPLACE INTO research_decay_events(
                        event_id, target_kind, target_id, decay_scope, old_status, new_status,
                        changed_component_keys, new_version_context, created_at
                    ) VALUES (?, 'build_pattern', ?, 'component_scoped', ?, 'needs_revalidation', ?, ?, ?)
                    """,
                    (
                        "decay-"
                        + _stable_hash(["pattern", row["pattern_id"], changed_component_keys])[:16],
                        row["pattern_id"],
                        row["status"],
                        _json(sorted(changed)),
                        _json(new_version_context),
                        now,
                    ),
                )
                patterns_updated += 1
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "itemsUpdated": fragments_updated,
            "edgesUpdated": edges_updated,
            "patternsUpdated": patterns_updated,
        }

    def submit_revalidation_result(
        self,
        *,
        target_kind: str,
        target_id: str,
        outcome: str,
        new_version_context: dict[str, str],
        safe_evidence_refs: list[str],
        affected_component_keys: list[str],
    ) -> dict[str, Any]:
        if target_kind not in VALID_REVALIDATION_TARGET_KINDS:
            return research_models.rejection("invalid_revalidation_target_kind")
        if outcome not in VALID_REVALIDATION_OUTCOMES:
            return research_models.rejection("invalid_revalidation_outcome")
        copy_error = _copy_safety_error(
            {
                "target_kind": target_kind,
                "target_id": target_id,
                "outcome": outcome,
                "new_version_context": new_version_context,
                "safe_evidence_refs": safe_evidence_refs,
                "affected_component_keys": affected_component_keys,
            }
        )
        if copy_error is not None:
            return copy_error
        con = mature_learning.connect(self.db_path)
        try:
            now = _now()
            table, id_column = _revalidation_target_table(target_kind)
            row = con.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?", (target_id,)
            ).fetchone()
            if row is None:
                return research_models.rejection("missing_revalidation_target")
            event_id = (
                "rev-" + _stable_hash([target_kind, target_id, outcome, new_version_context])[:16]
            )
            if outcome == "still_valid":
                planner_visible_update = ""
                planner_visible_params: tuple[int, ...] = ()
                if target_kind in {"semantic_edge", "build_pattern"}:
                    planner_visible_update = ", planner_visible = ?"
                    planner_visible_params = (
                        _planner_visible("valid", str(row["copy_safety_state"])),
                    )
                con.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'valid',
                        game_patch = ?,
                        passive_tree_version = ?,
                        current_version_context = ?,
                        last_validated_at = ?,
                        last_seen_at = ?
                        {planner_visible_update}
                    WHERE {id_column} = ?
                    """,
                    (
                        new_version_context.get("game_patch", row["game_patch"]),
                        new_version_context.get(
                            "passive_tree_version", row["passive_tree_version"]
                        ),
                        _json(new_version_context),
                        now,
                        now,
                        *planner_visible_params,
                        target_id,
                    ),
                )
                successor_id = None
            elif outcome == "changed_scope":
                successor_id = target_id + "-successor-" + _stable_hash(new_version_context)[:8]
                planner_visible_update = (
                    ", planner_visible = 0"
                    if target_kind in {"semantic_edge", "build_pattern"}
                    else ""
                )
                con.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'deprecated',
                        superseded_by_id = ?
                        {planner_visible_update}
                    WHERE {id_column} = ?
                    """,
                    (successor_id, target_id),
                )
            else:
                successor_id = None
                planner_visible_update = (
                    ", planner_visible = 0"
                    if target_kind in {"semantic_edge", "build_pattern"}
                    else ""
                )
                con.execute(
                    f"""
                    UPDATE {table}
                    SET status = 'needs_revalidation'
                        {planner_visible_update}
                    WHERE {id_column} = ?
                    """,
                    (target_id,),
                )
            con.execute(
                """
                INSERT OR REPLACE INTO research_revalidation_events(
                    event_id, target_kind, target_id, outcome, old_version_context,
                    new_version_context, safe_evidence_refs, affected_component_keys, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    target_kind,
                    target_id,
                    outcome,
                    row["current_version_context"],
                    _json(new_version_context),
                    _json(safe_evidence_refs),
                    _json(affected_component_keys),
                    now,
                ),
            )
            con.commit()
        finally:
            con.close()
        return {
            "status": "accepted",
            "targetId": target_id,
            "successorId": successor_id,
            "noRawQuery": True,
            "noRawMatureBuildMaterial": True,
        }

    def _query_rows(
        self,
        con: sqlite3.Connection,
        query: str,
        component_key_groups: list[list[str]],
        limit: int,
    ) -> list[sqlite3.Row]:
        params: list[Any] = []
        where = [
            "visibility = 'creator_visible'",
            "split = 'train_context'",
            "copy_safety_state = 'passed'",
            "status IN ('valid', 'needs_revalidation')",
        ]
        ids: list[str] | None = None
        if query.strip():
            fts_query = _fts_query(query)
            fts_rows = con.execute(
                """
                SELECT fragment_id
                FROM research_fragment_fts
                WHERE research_fragment_fts MATCH ?
                ORDER BY bm25(research_fragment_fts)
                LIMIT ?
                """,
                (fts_query, max(limit * 4, limit)),
            ).fetchall()
            ids = [str(row["fragment_id"]) for row in fts_rows]
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            where.append(f"fragment_id IN ({placeholders})")
            params.extend(ids)
        if component_key_groups:
            for group in component_key_groups:
                placeholders = ",".join("?" for _ in group)
                where.append(
                    f"""
                    EXISTS (
                        SELECT 1 FROM json_each(research_fragments.component_keys)
                        WHERE json_each.value IN ({placeholders})
                    )
                    """
                )
                params.extend(group)
        sql = "SELECT * FROM research_fragments WHERE " + " AND ".join(where)
        sql += " ORDER BY evidence_count DESC, fragment_id LIMIT ?"
        params.append(limit)
        return list(con.execute(sql, params).fetchall())

    def _query_family_keys_by_gem_name(
        self,
        con: sqlite3.Connection,
        query: str,
    ) -> set[str]:
        """Return family keys whose primary set matches a gem named in ``query``.

        Uses the deterministic gem index: the query is normalized and compared against gem
        display names; the granting gem's skills are then matched against stored
        ``primary_skill_keys``. This fixes recall for queries like "detonate dead" whose
        stored record text is Chinese and would otherwise never match.
        """
        if not query or not query.strip():
            return set()
        idx = skill_equivalence.SkillEquivalenceIndex.shared()
        normalized = skill_equivalence.normalize_name(query)
        if not normalized:
            return set()
        candidate_skills: set[str] = set()
        for skill_id, display in idx.display_names_by_skill().items():
            canon_display = skill_equivalence.normalize_name(display)
            if canon_display and (normalized in canon_display or canon_display in normalized):
                candidate_skills.add(skill_id)
        for gem_name, granted in idx.granted_skills_by_gem().items():
            if normalized in skill_equivalence.normalize_name(gem_name):
                candidate_skills.update(granted)
        if not candidate_skills:
            return set()
        result: set[str] = set()
        for row in con.execute(
            "SELECT build_family_key, primary_skill_keys FROM research_build_families"
        ).fetchall():
            stored = _loads(row["primary_skill_keys"], None)
            if not stored:
                continue
            if any(str(item).split(":", 1)[-1] in candidate_skills for item in stored):
                result.add(str(row["build_family_key"]))
        return result

    def _query_build_family_rows(
        self,
        con: sqlite3.Connection,
        *,
        ascendancy_key: str | None,
        primary_skill_keys: list[str],
        build_family_keys: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        where = ["1 = 1"]
        params: list[Any] = []
        if ascendancy_key:
            where.append("ascendancy_key = ?")
            params.append(ascendancy_key)
        if primary_skill_keys:
            placeholders = ",".join("?" for _ in primary_skill_keys)
            where.append(
                "("
                "EXISTS (SELECT 1 FROM json_each("
                "CASE WHEN json_valid(primary_skill_keys) THEN primary_skill_keys ELSE '[]' END) "
                f"WHERE json_each.value IN ({placeholders})) "
                f"OR primary_skill_key IN ({placeholders})"
                ")"
            )
            params.extend(primary_skill_keys)
            params.extend(primary_skill_keys)
        if build_family_keys:
            placeholders = ",".join("?" for _ in build_family_keys)
            where.append(f"build_family_key IN ({placeholders})")
            params.extend(build_family_keys)
        sql = "SELECT * FROM research_build_families WHERE " + " AND ".join(where)
        sql += " ORDER BY evidence_count DESC, build_family_key LIMIT ?"
        params.append(limit)
        return list(con.execute(sql, params).fetchall())

    def _query_discovery_family_rows(
        self,
        con: sqlite3.Connection,
        *,
        class_key: str,
        game_patch: str,
        passive_tree_version: str,
        ascendancy_key: str | None,
        primary_skill_keys: list[str],
        build_family_keys: list[str],
        limit: int,
    ) -> list[sqlite3.Row]:
        """Return only exact-version Families backed by eligible mature Research records."""

        class_token = re.sub(
            r"[^a-z0-9_]+",
            "_",
            class_key.split(":", 1)[-1].strip().casefold().replace(" ", "_"),
        ).strip("_")
        where = [
            "(records.class_key = ? OR "
            "(records.class_key IS NULL AND families.ascendancy_key LIKE ?))",
            "records.game_patch = ?",
            "records.passive_tree_version = ?",
            "records.visibility = 'creator_visible'",
            "records.split = 'train_context'",
            "records.copy_safety_state = 'passed'",
            "records.status = 'valid'",
            "COALESCE(json_extract(records.typed_payload, '$.availability'), 'standard') "
            "!= 'source_specific_random'",
        ]
        params: list[Any] = [
            class_key,
            f"ascendancy:{class_token}:%",
            game_patch,
            passive_tree_version,
        ]
        if ascendancy_key:
            where.append("families.ascendancy_key = ?")
            params.append(ascendancy_key)
        if primary_skill_keys:
            placeholders = ",".join("?" for _ in primary_skill_keys)
            where.append(
                "(EXISTS (SELECT 1 FROM json_each("
                "CASE WHEN json_valid(families.primary_skill_keys) "
                "THEN families.primary_skill_keys ELSE '[]' END) "
                f"WHERE json_each.value IN ({placeholders})) "
                f"OR families.primary_skill_key IN ({placeholders}))"
            )
            params.extend(primary_skill_keys)
            params.extend(primary_skill_keys)
        if build_family_keys:
            placeholders = ",".join("?" for _ in build_family_keys)
            where.append(f"families.build_family_key IN ({placeholders})")
            params.extend(build_family_keys)
        sql = f"""
            SELECT families.*,
                   COUNT(records.record_id) AS eligible_record_count,
                   COUNT(DISTINCT records.record_kind) AS eligible_record_kind_count,
                   COALESCE(SUM(records.evidence_count), 0) AS eligible_evidence_count
            FROM research_build_families AS families
            JOIN deep_research_records AS records
              ON records.build_family_key = families.build_family_key
            WHERE {" AND ".join(where)}
            GROUP BY families.build_family_key
            ORDER BY eligible_evidence_count DESC,
                     eligible_record_kind_count DESC,
                     eligible_record_count DESC,
                     families.build_family_key
            LIMIT ?
        """
        params.append(min(max(1, limit), 10))
        return list(con.execute(sql, params).fetchall())

    def _build_discovery_family_results(
        self,
        con: sqlite3.Connection,
        family_rows: list[sqlite3.Row],
        *,
        class_key: str,
        game_patch: str,
        passive_tree_version: str,
    ) -> list[dict[str, Any]]:
        """Build compact comparison summaries without exposing record content."""

        if not family_rows:
            return []
        family_keys = [str(row["build_family_key"]) for row in family_rows]
        placeholders = ",".join("?" for _ in family_keys)
        class_token = re.sub(
            r"[^a-z0-9_]+",
            "_",
            class_key.split(":", 1)[-1].strip().casefold().replace(" ", "_"),
        ).strip("_")
        record_rows = con.execute(
            f"""
            SELECT records.record_id, records.build_family_key, records.record_kind,
                   records.summary, records.conditions, records.failure_conditions,
                   records.evidence_count
            FROM deep_research_records AS records
            JOIN research_build_families AS families
              ON families.build_family_key = records.build_family_key
            WHERE records.build_family_key IN ({placeholders})
              AND (
                    records.class_key = ?
                    OR (
                        records.class_key IS NULL
                        AND families.ascendancy_key LIKE ?
                    )
                  )
              AND records.game_patch = ?
              AND records.passive_tree_version = ?
              AND records.visibility = 'creator_visible'
              AND records.split = 'train_context'
              AND records.copy_safety_state = 'passed'
              AND records.status = 'valid'
              AND COALESCE(json_extract(records.typed_payload, '$.availability'), 'standard')
                  != 'source_specific_random'
            ORDER BY records.build_family_key, records.evidence_count DESC,
                     records.last_validated_at DESC, records.record_id
            """,
            [
                *family_keys,
                class_key,
                f"ascendancy:{class_token}:%",
                game_patch,
                passive_tree_version,
            ],
        ).fetchall()
        grouped: dict[str, list[sqlite3.Row]] = {key: [] for key in family_keys}
        for row in record_rows:
            grouped[str(row["build_family_key"])].append(row)
        results: list[dict[str, Any]] = []
        for family in family_rows:
            family_key = str(family["build_family_key"])
            records = grouped.get(family_key, [])
            representative_records = self._representative_family_records(records)
            kind_counts: dict[str, int] = {}
            premises: list[str] = []
            failure_conditions: list[str] = []
            for record in records:
                kind = str(record["record_kind"])
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            for record in representative_records:
                for premise in _loads(record["conditions"], []):
                    text = str(premise).strip()
                    if text and text not in premises and len(premises) < 4:
                        premises.append(text)
                for failure in _loads(record["failure_conditions"], []):
                    text = str(failure).strip()
                    if text and text not in failure_conditions and len(failure_conditions) < 4:
                        failure_conditions.append(text)
            results.append(
                {
                    "buildFamilyKey": family_key,
                    "ascendancyKey": family["ascendancy_key"],
                    "primarySkillKey": family["primary_skill_key"],
                    "secondarySkillKeys": _loads(family["secondary_skill_keys"], []),
                    "classKey": class_key,
                    "gamePatch": game_patch,
                    "passiveTreeVersion": passive_tree_version,
                    "evidenceCount": int(family["eligible_evidence_count"] or 0),
                    "deepRecordCount": int(family["eligible_record_count"] or 0),
                    "recordKindCounts": kind_counts,
                    "availableRecordKinds": sorted(kind_counts),
                    "keyPremises": premises,
                    "failureConditions": failure_conditions,
                    "supportingRecordIds": [
                        str(row["record_id"]) for row in representative_records[:4]
                    ],
                    "eligibility": {
                        "exactVersion": True,
                        "creatorVisible": True,
                        "trainContext": True,
                        "copySafetyPassed": True,
                        "status": "valid",
                    },
                }
            )
        return results

    @staticmethod
    def _representative_family_records(
        records: list[sqlite3.Row],
    ) -> list[sqlite3.Row]:
        """Prefer one mechanism-duty record per kind before filling by evidence order."""

        selected: list[sqlite3.Row] = []
        selected_ids: set[str] = set()
        for record_kind in MECHANISM_RECORD_KIND_PRIORITY:
            match = next(
                (row for row in records if str(row["record_kind"]) == record_kind),
                None,
            )
            if match is None:
                continue
            selected.append(match)
            selected_ids.add(str(match["record_id"]))
        selected.extend(row for row in records if str(row["record_id"]) not in selected_ids)
        return selected

    def _build_family_results(
        self,
        con: sqlite3.Connection,
        family_rows: list[sqlite3.Row],
    ) -> list[dict[str, Any]]:
        if not family_rows:
            return []
        family_keys = [str(row["build_family_key"]) for row in family_rows]
        placeholders = ",".join("?" for _ in family_keys)
        count_rows = con.execute(
            f"""
            SELECT build_family_key, record_kind, COUNT(*) AS record_count
            FROM deep_research_records
            WHERE build_family_key IN ({placeholders})
              AND visibility = 'creator_visible'
              AND split = 'train_context'
              AND copy_safety_state = 'passed'
              AND status IN ('valid', 'needs_revalidation')
              AND COALESCE(json_extract(typed_payload, '$.availability'), 'standard')
                  != 'source_specific_random'
            GROUP BY build_family_key, record_kind
            ORDER BY build_family_key, record_kind
            """,
            family_keys,
        ).fetchall()
        counts_by_family: dict[str, dict[str, int]] = {key: {} for key in family_keys}
        for row in count_rows:
            counts_by_family[str(row["build_family_key"])][str(row["record_kind"])] = int(
                row["record_count"] or 0
            )
        results: list[dict[str, Any]] = []
        for row in family_rows:
            family_key = str(row["build_family_key"])
            record_kind_counts = counts_by_family.get(family_key, {})
            primary_keys = _loads(row["primary_skill_keys"], None)
            if not primary_keys:
                primary_keys = (
                    [str(row["primary_skill_key"] or "")] if row["primary_skill_key"] else []
                )
            results.append(
                {
                    "buildFamilyKey": family_key,
                    "ascendancyKey": row["ascendancy_key"],
                    "primarySkillKey": (
                        primary_keys[0] if primary_keys else str(row["primary_skill_key"] or "")
                    ),
                    "primarySkillKeys": primary_keys,
                    "secondarySkillKeys": _loads(row["secondary_skill_keys"], []),
                    "evidenceCount": int(row["evidence_count"] or 0),
                    "deepRecordCount": sum(record_kind_counts.values()),
                    "recordKindCounts": record_kind_counts,
                    "availableRecordKinds": sorted(record_kind_counts),
                }
            )
        return results

    def _build_family_record_context(
        self,
        con: sqlite3.Connection,
        *,
        family_keys: list[str],
        returned_record_ids: set[str],
        game_patch: str | None,
        passive_tree_version: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Expose a complete safe index even when the first content page is intentionally small."""

        if not family_keys:
            return [], [], []
        placeholders = ",".join("?" for _ in family_keys)
        where = [
            f"build_family_key IN ({placeholders})",
            "visibility = 'creator_visible'",
            "split = 'train_context'",
            "copy_safety_state = 'passed'",
            "status IN ('valid', 'needs_revalidation')",
            (
                "COALESCE(json_extract(typed_payload, '$.availability'), 'standard') "
                "!= 'source_specific_random'"
            ),
        ]
        params: list[Any] = [*family_keys]
        if game_patch:
            where.append("game_patch = ?")
            params.append(game_patch)
        if passive_tree_version:
            where.append("passive_tree_version = ?")
            params.append(passive_tree_version)
        rows = list(
            con.execute(
                """
                SELECT record_id, build_family_key, record_kind, title, summary,
                       component_keys, conditions, failure_conditions, evidence_count
                FROM deep_research_records
                WHERE """
                + " AND ".join(where)
                + """
                ORDER BY build_family_key, evidence_count DESC, last_validated_at DESC, record_id
                """,
                params,
            ).fetchall()
        )
        grouped: dict[str, list[sqlite3.Row]] = {key: [] for key in family_keys}
        for row in rows:
            grouped.setdefault(str(row["build_family_key"]), []).append(row)

        coverage: list[dict[str, Any]] = []
        record_index: list[dict[str, Any]] = []
        premise_catalog: list[dict[str, Any]] = []
        for family_key in family_keys:
            family_rows = grouped.get(family_key, [])
            kind_counts: dict[str, int] = {}
            returned_count = 0
            for row in family_rows:
                record_id = str(row["record_id"])
                record_kind = str(row["record_kind"])
                component_keys = _loads(row["component_keys"], [])
                returned = record_id in returned_record_ids
                returned_count += int(returned)
                kind_counts[record_kind] = kind_counts.get(record_kind, 0) + 1
                if not returned:
                    record_index.append(
                        {
                            "recordId": record_id,
                            "buildFamilyKey": family_key,
                            "recordKind": record_kind,
                            "title": row["title"],
                            "summary": row["summary"],
                            "componentKeys": component_keys,
                            "returnedInThisResponse": False,
                        }
                    )
                if record_kind not in MECHANISM_RECORD_KINDS:
                    continue
                for premise_type, values in (
                    ("condition", _loads(row["conditions"], [])),
                    ("failure_condition", _loads(row["failure_conditions"], [])),
                ):
                    for value in values:
                        text = str(value).strip()
                        if not text:
                            continue
                        premise_catalog.append(
                            {
                                "premiseId": _research_premise_id(
                                    record_id,
                                    premise_type,
                                    text,
                                ),
                                "buildFamilyKey": family_key,
                                "evidenceRef": record_id,
                                "recordKind": record_kind,
                                "premiseType": premise_type,
                                "text": text,
                                "componentKeys": component_keys,
                            }
                        )
            eligible_count = len(family_rows)
            coverage.append(
                {
                    "buildFamilyKey": family_key,
                    "eligibleRecordCount": eligible_count,
                    "returnedRecordCount": returned_count,
                    "unreturnedRecordCount": eligible_count - returned_count,
                    "recordKindCounts": kind_counts,
                    "responseComplete": returned_count == eligible_count,
                }
            )
        return coverage, record_index, premise_catalog

    def _query_deep_record_rows(
        self,
        con: sqlite3.Connection,
        *,
        query: str,
        component_key_groups: list[list[str]],
        limit: int,
        record_ids: list[str],
        build_family_keys: list[str],
        record_kinds: list[str],
        query_is_preference: bool,
        game_patch: str | None,
        passive_tree_version: str | None,
    ) -> list[sqlite3.Row]:
        where = [
            "visibility = 'creator_visible'",
            "split = 'train_context'",
            "copy_safety_state = 'passed'",
            "status IN ('valid', 'needs_revalidation')",
        ]
        if record_ids:
            # Explicit record IDs are deep-read anchors that may have been issued before a
            # relocation (backfill/migration moves a unit to id = hash(knowledge_key) and
            # deprecates the old id). Resolve each id to its active superseding chain head
            # so stored receipts and caller-held ids keep resolving; the status filter keeps
            # the deprecated husks themselves out of the result.
            resolved_ids: list[str] = []
            for record_id in record_ids:
                resolved_ids.append(record_id)
                head = con.execute(
                    "SELECT superseded_by_id FROM deep_research_records WHERE record_id = ?",
                    (record_id,),
                ).fetchone()
                head_id = head["superseded_by_id"] if head is not None else None
                seen = {record_id}
                while head_id is not None and head_id not in seen:
                    seen.add(head_id)
                    resolved_ids.append(head_id)
                    head = con.execute(
                        "SELECT superseded_by_id FROM deep_research_records WHERE record_id = ?",
                        (head_id,),
                    ).fetchone()
                    head_id = head["superseded_by_id"] if head is not None else None
            record_ids = resolved_ids
        if not record_ids:
            where.append(
                "COALESCE(json_extract(typed_payload, '$.availability'), 'standard') "
                "!= 'source_specific_random'"
            )
        params: list[Any] = []
        if record_ids:
            placeholders = ",".join("?" for _ in record_ids)
            where.append(f"record_id IN ({placeholders})")
            params.extend(record_ids)
        if build_family_keys:
            placeholders = ",".join("?" for _ in build_family_keys)
            where.append(f"build_family_key IN ({placeholders})")
            params.extend(build_family_keys)
        elif query_is_preference:
            return []
        if record_kinds:
            placeholders = ",".join("?" for _ in record_kinds)
            where.append(f"record_kind IN ({placeholders})")
            params.extend(record_kinds)
        if game_patch:
            where.append("game_patch = ?")
            params.append(game_patch)
        if passive_tree_version:
            where.append("passive_tree_version = ?")
            params.append(passive_tree_version)
        if not record_ids and query.strip() and not query_is_preference:
            terms = [term.casefold() for term in _search_terms(query)]
            if terms:
                clauses: list[str] = []
                for term in terms:
                    clauses.append(
                        "("
                        "lower(title) LIKE ? OR lower(summary) LIKE ? "
                        "OR lower(record_kind) LIKE ? OR lower(conditions) LIKE ? "
                        "OR lower(failure_conditions) LIKE ?"
                        ")"
                    )
                    token = f"%{term}%"
                    params.extend([token, token, token, token, token])
                where.append("(" + " OR ".join(clauses) + ")")
        if component_key_groups:
            for group in component_key_groups:
                placeholders = ",".join("?" for _ in group)
                where.append(
                    f"""
                    (
                        EXISTS (
                            SELECT 1 FROM json_each(deep_research_records.component_keys)
                            WHERE json_each.value IN ({placeholders})
                        )
                        OR EXISTS (
                            SELECT 1 FROM research_build_families
                            WHERE research_build_families.build_family_key =
                                  deep_research_records.build_family_key
                              AND (
                                  research_build_families.ascendancy_key IN ({placeholders})
                                  OR EXISTS (
                                      SELECT 1
                                      FROM json_each(
                                          CASE WHEN json_valid(
                                              research_build_families.primary_skill_keys
                                          ) THEN research_build_families.primary_skill_keys
                                          ELSE '[]' END
                                      )
                                      WHERE json_each.value IN ({placeholders})
                                  )
                                  OR research_build_families.primary_skill_key IN ({placeholders})
                                  OR EXISTS (
                                      SELECT 1
                                      FROM json_each(research_build_families.secondary_skill_keys)
                                      WHERE json_each.value IN ({placeholders})
                                  )
                              )
                        )
                    )
                    """
                )
                params.extend([*group, *group, *group, *group, *group])
        sql = "SELECT * FROM deep_research_records WHERE " + " AND ".join(where)
        sql += " ORDER BY evidence_count DESC, last_validated_at DESC, record_id"
        if not query_is_preference:
            sql += " LIMIT ?"
            params.append(limit)
        rows = list(con.execute(sql, params).fetchall())
        if query_is_preference:
            # Explicit record IDs are a caller-authored deep-read set.  Never silently discard
            # one because an ordinary summary limit is smaller than that exact set.
            if record_ids:
                return rows
            terms = [term.casefold() for term in _search_terms(query)]
            if terms:
                rows.sort(
                    key=lambda row: (
                        0
                        if any(
                            term
                            in " ".join(
                                [
                                    str(row["title"] or ""),
                                    str(row["summary"] or ""),
                                    str(row["record_kind"] or ""),
                                    str(row["conditions"] or ""),
                                    str(row["failure_conditions"] or ""),
                                ]
                            ).casefold()
                            for term in terms
                        )
                        else 1
                    )
                )
            return self._balanced_deep_record_rows(rows, limit=limit)
        if record_ids or not query.strip() or len(rows) >= limit:
            return rows
        family_keys = sorted(
            {str(row["build_family_key"]) for row in rows if row["build_family_key"]}
        )
        if not family_keys:
            return rows
        existing_ids = {str(row["record_id"]) for row in rows}
        family_placeholders = ",".join("?" for _ in family_keys)
        id_placeholders = ",".join("?" for _ in existing_ids)
        expanded = con.execute(
            f"""
            SELECT * FROM deep_research_records
            WHERE build_family_key IN ({family_placeholders})
              AND record_id NOT IN ({id_placeholders})
              AND visibility = 'creator_visible'
              AND split = 'train_context'
              AND copy_safety_state = 'passed'
              AND status IN ('valid', 'needs_revalidation')
              AND COALESCE(json_extract(typed_payload, '$.availability'), 'standard') != 'source_specific_random'
            ORDER BY evidence_count DESC, last_validated_at DESC, record_id
            LIMIT ?
            """,
            [*family_keys, *sorted(existing_ids), limit - len(rows)],
        ).fetchall()
        return [*rows, *expanded]

    @staticmethod
    def _balanced_deep_record_rows(
        rows: list[sqlite3.Row],
        *,
        limit: int,
    ) -> list[sqlite3.Row]:
        """Return a bounded cross-Family preview without letting one Family consume every slot."""

        queues: dict[str, list[sqlite3.Row]] = {}
        family_order: list[str] = []
        for row in rows:
            family_key = str(row["build_family_key"] or "unclassified")
            if family_key not in queues:
                queues[family_key] = []
                family_order.append(family_key)
            queues[family_key].append(row)

        selected: list[sqlite3.Row] = []
        seen_kinds: dict[str, set[str]] = {key: set() for key in family_order}
        while len(selected) < limit:
            made_progress = False
            for family_key in family_order:
                queue = queues[family_key]
                next_index = next(
                    (
                        index
                        for index, row in enumerate(queue)
                        if str(row["record_kind"]) not in seen_kinds[family_key]
                    ),
                    0 if queue else None,
                )
                if next_index is None:
                    continue
                row = queue.pop(next_index)
                selected.append(row)
                seen_kinds[family_key].add(str(row["record_kind"]))
                made_progress = True
                if len(selected) >= limit:
                    break
            if not made_progress:
                break
        return selected

    def _query_creator_semantic_edges(
        self,
        con: sqlite3.Connection,
        *,
        component_keys: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not component_keys:
            return []
        placeholders = ",".join("?" for _ in component_keys)
        rows = con.execute(
            f"""
            SELECT * FROM research_semantic_edges
            WHERE visibility = 'creator_visible'
              AND split = 'train_context'
              AND status = 'valid'
              AND copy_safety_state = 'passed'
              AND planner_visible = 1
              AND (
                  source_key IN ({placeholders})
                  OR target_key IN ({placeholders})
                  OR EXISTS (
                      SELECT 1 FROM json_each(research_semantic_edges.affected_component_keys)
                      WHERE json_each.value IN ({placeholders})
                  )
              )
            ORDER BY edge_id
            LIMIT ?
            """,
            [*component_keys, *component_keys, *component_keys, limit],
        ).fetchall()
        return [
            {
                "edgeId": row["edge_id"],
                "sourceKey": row["source_key"],
                "targetKey": row["target_key"],
                "edgeType": row["edge_type"],
                "rationale": row["rationale"],
                "confidence": row["confidence"],
                "modelability": row["modelability"],
                "contextRequirements": _loads(row["context_requirements"], []),
                "affectedComponentKeys": _loads(row["affected_component_keys"], []),
                "gamePatch": row["game_patch"],
                "passiveTreeVersion": row["passive_tree_version"],
                "pobVersionOrCommit": row["pob_version_or_commit"],
                "status": row["status"],
                "copySafetyState": row["copy_safety_state"],
                "noRawMatureBuildMaterial": True,
            }
            for row in rows
        ]

    def _query_creator_build_patterns(
        self,
        con: sqlite3.Connection,
        *,
        component_keys: list[str],
        family_keys: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not component_keys and not family_keys:
            return []
        base_where = """
            visibility = 'creator_visible'
            AND split = 'train_context'
            AND status = 'valid'
            AND copy_safety_state = 'passed'
            AND planner_visible = 1
        """

        def fetch_rows(extra_where: str, params: list[Any]) -> list[sqlite3.Row]:
            return list(
                con.execute(
                    f"""
                    SELECT * FROM research_build_patterns
                    WHERE {base_where} AND ({extra_where})
                    ORDER BY sample_count DESC, source_diversity_count DESC, pattern_id
                    LIMIT ?
                    """,
                    [*params, limit],
                ).fetchall()
            )

        lanes: list[tuple[list[sqlite3.Row], str]] = []
        if family_keys:
            placeholders = ",".join("?" for _ in family_keys)
            origin_match = f"""
                EXISTS (
                    SELECT 1 FROM json_each(research_build_patterns.origin_family_keys)
                    WHERE json_each.value IN ({placeholders})
                )
            """
            lanes.append(
                (
                    fetch_rows(f"transfer_scope = 'component' AND {origin_match}", family_keys),
                    "origin_family",
                )
            )
            lanes.append(
                (
                    fetch_rows(f"transfer_scope = 'family' AND {origin_match}", family_keys),
                    "exact_family",
                )
            )
        if component_keys:
            placeholders = ",".join("?" for _ in component_keys)
            lanes.append(
                (
                    fetch_rows(
                        f"""
                        transfer_scope = 'family' AND EXISTS (
                            SELECT 1 FROM json_each(research_build_patterns.component_keys)
                            WHERE json_each.value IN ({placeholders})
                        )
                        """,
                        component_keys,
                    ),
                    "shared_component",
                )
            )

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rows, match_scope in lanes:
            for row in rows:
                pattern_id = str(row["pattern_id"])
                if pattern_id in seen:
                    continue
                seen.add(pattern_id)
                results.append(self._build_pattern_result(row, match_scope=match_scope))
                if len(results) >= limit:
                    return results
        return results

    def _query_creator_transferable_patterns(
        self,
        con: sqlite3.Connection,
        *,
        query: str,
        component_keys: list[str],
        research_axes: list[str],
        exclude_origin_family_keys: list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        where = [
            "visibility = 'creator_visible'",
            "split = 'train_context'",
            "status = 'valid'",
            "copy_safety_state = 'passed'",
            "planner_visible = 1",
            "transfer_scope IN ('component', 'global')",
            "confidence_tier IN ('case_observation', 'recurring_observation', 'likely_pattern')",
        ]
        params: list[Any] = []
        if exclude_origin_family_keys:
            placeholders = ",".join("?" for _ in exclude_origin_family_keys)
            where.append(
                "NOT EXISTS ("
                "SELECT 1 FROM json_each(research_build_patterns.origin_family_keys) "
                f"WHERE json_each.value IN ({placeholders})"
                ")"
            )
            params.extend(exclude_origin_family_keys)
        if research_axes:
            placeholders = ",".join("?" for _ in research_axes)
            where.append(
                "EXISTS (SELECT 1 FROM json_each(research_build_patterns.applicability_axes) "
                f"WHERE json_each.value IN ({placeholders}))"
            )
            params.extend(research_axes)
        else:
            terms = [term.casefold() for term in _search_terms(query)]
            if terms:
                term_clauses: list[str] = []
                for term in terms:
                    token = f"%{term}%"
                    term_clauses.append(
                        "(lower(title) LIKE ? OR lower(summary) LIKE ? "
                        "OR lower(COALESCE(planner_hint, '')) LIKE ?)"
                    )
                    params.extend([token, token, token])
                where.append("(" + " OR ".join(term_clauses) + ")")

        sql = "SELECT * FROM research_build_patterns WHERE " + " AND ".join(where)
        sql += " ORDER BY sample_count DESC, source_diversity_count DESC, pattern_id LIMIT ?"
        params.append(max(limit * 4, limit))
        rows = list(con.execute(sql, params).fetchall())
        requested = set(component_keys)
        rows.sort(
            key=lambda row: (
                -len(requested.intersection(_loads(row["component_keys"], []))),
                -TRANSFER_CONFIDENCE_WEIGHTS.get(str(row["confidence_tier"]), 0.0),
                -int(row["family_count"] or 0),
                -int(row["sample_count"] or 0),
                str(row["pattern_id"]),
            )
        )
        return [
            self._build_pattern_result(row, match_scope=str(row["transfer_scope"]))
            for row in rows[:limit]
        ]

    @staticmethod
    def _build_pattern_result(row: sqlite3.Row, *, match_scope: str) -> dict[str, Any]:
        transfer_scope = str(row["transfer_scope"] or "family")
        if match_scope in {"family", "exact_family", "origin_family"}:
            weight_scope = "exact_family"
        elif match_scope == "shared_component":
            weight_scope = "same_primary_skill"
        else:
            weight_scope = transfer_scope
        result = {
            "patternId": row["pattern_id"],
            "patternType": row["pattern_type"],
            "title": row["title"],
            "summary": row["summary"],
            "componentKeys": _loads(row["component_keys"], []),
            "componentRoles": _loads(row["component_roles"], {}),
            "confidenceTier": row["confidence_tier"],
            "sampleCount": int(row["sample_count"]),
            "familyCount": int(row["family_count"]),
            "sourceDiversityCount": int(row["source_diversity_count"]),
            "denominator": row["denominator"],
            "transferScope": transfer_scope,
            "matchScope": match_scope,
            "applicabilityAxes": _loads(row["applicability_axes"], []),
            "applicabilityRequirements": _loads(row["applicability_requirements"], []),
            "exclusionConditions": _loads(row["exclusion_conditions"], []),
            "transferRationale": row["transfer_rationale"],
            "originFamilyKeys": _loads(row["origin_family_keys"], []),
            "scopeWeightCap": RESEARCH_MEMORY_SCOPE_WEIGHTS.get(weight_scope, 1.0),
            "confidenceWeight": TRANSFER_CONFIDENCE_WEIGHTS.get(str(row["confidence_tier"]), 1.0),
            "contextRequirements": _loads(row["context_requirements"], []),
            "plannerHint": row["planner_hint"],
            "verificationTasks": _loads(row["verification_tasks"], []),
            "gamePatch": row["game_patch"],
            "passiveTreeVersion": row["passive_tree_version"],
            "pobVersionOrCommit": row["pob_version_or_commit"],
            "status": row["status"],
            "copySafetyState": row["copy_safety_state"],
            "noRawMatureBuildMaterial": True,
        }
        return result

    def _record_dedupe_query(
        self,
        con: sqlite3.Connection,
        *,
        dedupe_ref: str,
        query: str,
        component_keys: list[str],
        request_contract: dict[str, Any],
        result_contract: dict[str, Any],
        now: str,
    ) -> None:
        con.execute(
            """
            INSERT INTO research_dedupe_queries(
                dedupe_query_ref, query_hash, query_text_preview, component_keys,
                request_contract, result_contract, visibility, split, knowledge_scope,
                created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'creator_visible', 'train_context', 'global_seed', ?, ?)
            ON CONFLICT(dedupe_query_ref) DO UPDATE SET
                query_text_preview = excluded.query_text_preview,
                component_keys = excluded.component_keys,
                request_contract = excluded.request_contract,
                result_contract = excluded.result_contract,
                last_seen_at = excluded.last_seen_at
            """,
            (
                dedupe_ref,
                _stable_hash({"query": _normalize_text(query), "component_keys": component_keys}),
                _normalize_text(query)[:240],
                _json(component_keys),
                _json(request_contract),
                _json(result_contract),
                now,
                now,
            ),
        )

    def _dedupe_query_ref_exists(self, dedupe_query_ref: str) -> bool:
        if not re.fullmatch(r"dq-[A-Fa-f0-9]{16}", str(dedupe_query_ref or "")):
            return False
        con = mature_learning.connect(self.db_path)
        try:
            row = con.execute(
                "SELECT 1 FROM research_dedupe_queries WHERE dedupe_query_ref = ? LIMIT 1",
                (dedupe_query_ref,),
            ).fetchone()
            return row is not None
        finally:
            con.close()

    def _fragment_result(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "memoryItemId": row["fragment_id"],
            "fragmentId": row["fragment_id"],
            "matchedFragmentIds": [row["fragment_id"]],
            "matchedSemanticEdgeIds": [],
            "sourceCaseRefs": _loads(row["source_case_refs"], []),
            "safeEvidenceRefs": _loads(row["safe_evidence_refs"], []),
            "fragmentType": row["fragment_type"],
            "title": row["title"],
            "summary": row["summary"],
            "reusablePrinciple": row["reusable_principle"],
            "componentKeys": _loads(row["component_keys"], []),
            "conditions": _loads(row["conditions"], []),
            "risks": _loads(row["risks"], []),
            "verificationTasks": _loads(row["verification_tasks"], []),
            "confidence": row["confidence"],
            "modelability": row["modelability"],
            "gamePatch": row["game_patch"],
            "passiveTreeVersion": row["passive_tree_version"],
            "status": row["status"],
            "copySafetyState": row["copy_safety_state"],
            "contextCaveats": ["needs_revalidation"]
            if row["status"] == "needs_revalidation"
            else [],
            "noRawMatureBuildMaterial": True,
        }

    def _deep_record_result(self, row: sqlite3.Row, *, include_content: bool) -> dict[str, Any]:
        result = {
            "recordId": row["record_id"],
            "researchGroupId": row["research_group_id"],
            "buildFamilyKey": row["build_family_key"],
            "knowledgeKey": row["knowledge_key"],
            "evidenceCount": int(row["evidence_count"] or 0),
            "recordKind": row["record_kind"],
            "title": row["title"],
            "summary": row["summary"],
            "componentKeys": _loads(row["component_keys"], []),
            "componentMentions": _loads(row["component_mentions"], []),
            "sourceCaseRefs": _loads(row["source_case_refs"], []),
            "safeEvidenceRefs": _loads(row["safe_evidence_refs"], []),
            "conditions": _loads(row["conditions"], []),
            "failureConditions": _loads(row["failure_conditions"], []),
            "classKey": row["class_key"],
            "ascendancyKey": row["ascendancy_key"],
            "gamePatch": row["game_patch"],
            "passiveTreeVersion": row["passive_tree_version"],
            "status": row["status"],
            "copySafetyState": row["copy_safety_state"],
            "noRawMatureBuildMaterial": True,
        }
        if include_content:
            result["content"] = row["content"]
            result["typedPayload"] = _loads(row["typed_payload"], {})
        return result

    def _duplicate_fragment(
        self,
        con: sqlite3.Connection,
        fragment: research_models.CleanFragmentProposal,
    ) -> str | None:
        row = con.execute(
            """
            SELECT fragment_id FROM research_fragments
            WHERE dedupe_key = ?
              AND visibility = ?
              AND split = ?
              AND knowledge_scope = ?
            LIMIT 1
            """,
            (
                _fragment_dedupe_key(fragment),
                fragment.visibility,
                fragment.split,
                fragment.knowledge_scope,
            ),
        ).fetchone()
        return str(row["fragment_id"]) if row else None

    def _insert_fragment(
        self,
        con: sqlite3.Connection,
        fragment_id: str,
        fragment: research_models.CleanFragmentProposal,
        now: str,
    ) -> None:
        chunk_text = _chunk_text(fragment)
        version = {
            "game_patch": fragment.game_patch,
            "passive_tree_version": fragment.passive_tree_version,
            "pob_version_or_commit": fragment.pob_version_or_commit,
        }
        con.execute(
            """
            INSERT INTO research_fragments(
                fragment_id, dedupe_key, fragment_type, title, summary, reusable_principle,
                chunk_text, component_keys, source_case_refs, safe_evidence_refs, confidence,
                copyability_risk, lifecycle_stages, modelability, verification_tasks,
                conditions, risks, game_patch, passive_tree_version, pob_version_or_commit,
                visibility, split, knowledge_scope, status, copy_safety_state,
                current_version_context, affected_component_keys, evidence_count,
                created_at, last_seen_at, last_validated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'valid',
                      'passed', ?, ?, 0, ?, ?, ?)
            ON CONFLICT(fragment_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                chunk_text = excluded.chunk_text
            """,
            (
                fragment_id,
                _fragment_dedupe_key(fragment),
                fragment.fragment_type,
                fragment.title,
                fragment.summary,
                fragment.reusable_principle,
                chunk_text,
                _json(sorted(set(fragment.component_keys))),
                _json(fragment.source_case_refs),
                _json(fragment.safe_evidence_refs),
                fragment.confidence,
                fragment.copyability_risk,
                _json(fragment.lifecycle_stages),
                fragment.modelability,
                _json(fragment.verification_tasks),
                _json(fragment.conditions),
                _json(fragment.risks),
                fragment.game_patch,
                fragment.passive_tree_version,
                fragment.pob_version_or_commit,
                fragment.visibility,
                fragment.split,
                fragment.knowledge_scope,
                _json(version),
                _json(sorted(set(fragment.component_keys))),
                now,
                now,
                now,
            ),
        )

    def _insert_fragment_evidence(
        self,
        con: sqlite3.Connection,
        *,
        fragment_id: str,
        source_case_refs: list[str],
        safe_evidence_refs: list[str],
        game_patch: str,
        passive_tree_version: str,
        pob_version_or_commit: str,
        visibility: str,
        split: str,
        knowledge_scope: str,
        confidence: str,
        now: str,
    ) -> str:
        evidence_id = (
            "rfe-"
            + _stable_hash(
                {
                    "fragment_id": fragment_id,
                    "source_case_refs": sorted(source_case_refs),
                    "safe_evidence_refs": sorted(safe_evidence_refs),
                    "visibility": visibility,
                    "split": split,
                    "knowledge_scope": knowledge_scope,
                }
            )[:16]
        )
        con.execute(
            """
            INSERT INTO research_fragment_evidence(
                evidence_id, fragment_id, source_case_refs, safe_evidence_refs, game_patch,
                passive_tree_version, pob_version_or_commit, visibility, split, knowledge_scope,
                confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(evidence_id) DO UPDATE SET
                safe_evidence_refs = excluded.safe_evidence_refs,
                confidence = excluded.confidence
            """,
            (
                evidence_id,
                fragment_id,
                _json(source_case_refs),
                _json(safe_evidence_refs),
                game_patch,
                passive_tree_version,
                pob_version_or_commit,
                visibility,
                split,
                knowledge_scope,
                confidence,
                now,
            ),
        )
        con.execute(
            """
            UPDATE research_fragments
            SET evidence_count = (
                SELECT count(*) FROM research_fragment_evidence
                WHERE fragment_id = research_fragments.fragment_id
            ),
                last_seen_at = ?
            WHERE fragment_id = ?
            """,
            (now, fragment_id),
        )
        return evidence_id

    def _endpoint_error(self, source_key: str, target_key: str) -> dict[str, Any] | None:
        if self.graph_service is None:
            return research_models.rejection(
                "graph_service_unavailable",
                caveats=["semantic edge endpoint validation requires a graph service"],
                facts={
                    "endpointAssessment": _endpoint_assessment(
                        "graph_snapshot_unavailable",
                        [],
                    )
                },
            )
        keys = getattr(self.graph_service, "_nodes_by_key", {})
        missing = [key for key in (source_key, target_key) if key not in keys]
        if missing:
            return research_models.rejection(
                "missing_endpoint",
                caveats=[
                    "endpoint is not present in the current physical graph snapshot",
                    "treat as source coverage gap until static source ingestion proves otherwise",
                ],
                suggested_repair=(
                    "Do not classify this as hallucination from this rejection alone. "
                    "First verify whether the component exists in current game data, then add or "
                    "refresh the Phase 2/3 static-source graph snapshot."
                ),
                facts={
                    "missingEndpointKeys": missing,
                    "endpointAssessment": _endpoint_assessment(
                        "source_coverage_gap",
                        missing,
                    ),
                },
            )
        return None

    def _component_endpoint_error(self, component_keys: list[str]) -> dict[str, Any] | None:
        if not component_keys:
            return None
        if self.graph_service is None:
            return research_models.rejection(
                "graph_service_unavailable",
                caveats=["pattern endpoint validation requires a graph service"],
                facts={
                    "endpointAssessment": _endpoint_assessment("graph_snapshot_unavailable", [])
                },
            )
        keys = getattr(self.graph_service, "_nodes_by_key", {})
        missing = sorted({key for key in component_keys if key and key not in keys})
        if missing:
            return research_models.rejection(
                "missing_endpoint",
                caveats=[
                    "pattern component endpoint is not present in the current physical graph snapshot",
                    "treat as source coverage gap until static source ingestion proves otherwise",
                ],
                facts={
                    "missingEndpointKeys": missing,
                    "endpointAssessment": _endpoint_assessment("source_coverage_gap", missing),
                },
            )
        return None

    def _observation_resolution_error(
        self,
        observation: research_models.BuildDesignObservation,
    ) -> dict[str, Any] | None:
        if self.graph_service is None:
            return None
        snapshot_id = getattr(getattr(self.graph_service, "snapshot", None), "snapshot_id", None)
        nodes_by_key = getattr(self.graph_service, "_nodes_by_key", {})
        for component in observation.components:
            evidence = component.resolution
            expected_key = component.component_key
            if evidence is None:
                return research_models.rejection(
                    "missing_endpoint_resolution",
                    caveats=[
                        f"pattern component {expected_key} must include resolve_graph_component evidence"
                    ],
                )
            if (
                evidence.stable_key != expected_key
                or expected_key not in evidence.evidence_path_nodes
            ):
                return research_models.rejection(
                    "endpoint_resolution_mismatch",
                    caveats=["pattern component resolution does not match component_key"],
                )
            if snapshot_id is not None and evidence.snapshot_id != snapshot_id:
                return research_models.rejection("stale_endpoint_resolution")
            node = nodes_by_key.get(expected_key)
            if node is not None and set(getattr(node, "source_refs", ())) != set(
                evidence.source_refs
            ):
                return research_models.rejection(
                    "endpoint_resolution_mismatch",
                    caveats=["pattern component resolver source refs do not match graph evidence"],
                )
        return None

    def _endpoint_resolution_error(
        self,
        edge: research_models.SemanticEdgeProposal,
    ) -> dict[str, Any] | None:
        if self.graph_service is None:
            return None
        snapshot_id = getattr(getattr(self.graph_service, "snapshot", None), "snapshot_id", None)
        nodes_by_key = getattr(self.graph_service, "_nodes_by_key", {})
        checks = (
            ("source", edge.source_key, edge.source_resolution),
            ("target", edge.target_key, edge.target_resolution),
        )
        for role, expected_key, evidence in checks:
            if evidence is None:
                return research_models.rejection(
                    "missing_endpoint_resolution",
                    caveats=[f"{role} endpoint must include resolve_graph_component evidence"],
                    suggested_repair=(
                        "Call graph_tool_query with tool_name='resolve_graph_component' for each "
                        "semantic edge endpoint and include the resolved evidence."
                    ),
                )
            if (
                evidence.stable_key != expected_key
                or expected_key not in evidence.evidence_path_nodes
            ):
                return research_models.rejection(
                    "endpoint_resolution_mismatch",
                    caveats=[f"{role} endpoint resolution does not match the proposed stable key"],
                    suggested_repair="Use the stable_key returned by resolve_graph_component.",
                )
            if snapshot_id is not None and evidence.snapshot_id != snapshot_id:
                return research_models.rejection(
                    "stale_endpoint_resolution",
                    caveats=[f"{role} endpoint was resolved against a different graph snapshot"],
                    suggested_repair="Re-run resolve_graph_component against the current graph snapshot.",
                )
            node = nodes_by_key.get(expected_key)
            if node is not None:
                expected_source_refs = set(getattr(node, "source_refs", ()))
                supplied_source_refs = set(evidence.source_refs)
                if expected_source_refs != supplied_source_refs:
                    return research_models.rejection(
                        "endpoint_resolution_mismatch",
                        caveats=[
                            f"{role} endpoint resolver source refs do not match graph evidence"
                        ],
                        suggested_repair=(
                            "Use the sourceRefs returned by graph_tool_query "
                            "resolve_graph_component for this endpoint."
                        ),
                    )
        return None

    def _semantic_conflict(
        self,
        con: sqlite3.Connection,
        edge: research_models.SemanticEdgeProposal,
    ) -> dict[str, Any] | None:
        if edge.edge_type not in DIRECTIONAL_EDGE_TYPES:
            return None
        inverse = con.execute(
            """
            SELECT edge_id, source_key, target_key FROM research_semantic_edges
            WHERE source_key = ?
              AND target_key = ?
              AND edge_type = ?
              AND visibility = ?
              AND split = ?
              AND knowledge_scope = ?
              AND directionality = 'directional'
              AND planner_visible = 1
            LIMIT 1
            """,
            (
                edge.target_key,
                edge.source_key,
                edge.edge_type,
                edge.visibility,
                edge.split,
                edge.knowledge_scope,
            ),
        ).fetchone()
        if inverse:
            return research_models.rejection(
                "semantic_cycle_or_conflict",
                facts={
                    "maxDepthChecked": SHORT_CYCLE_MAX_DEPTH,
                    "conflictKind": "inverse_edge",
                    "conflictEdgeType": edge.edge_type,
                    "conflictSourceKey": edge.source_key,
                    "conflictTargetKey": edge.target_key,
                    "conflictingExistingEdgeId": str(inverse["edge_id"]),
                    "conflictingExistingSourceKey": str(inverse["source_key"]),
                    "conflictingExistingTargetKey": str(inverse["target_key"]),
                },
            )

        cycle = con.execute(
            """
            WITH RECURSIVE walk(node, depth, path) AS (
                SELECT target_key, 1, source_key || '>' || target_key
                FROM research_semantic_edges
                WHERE source_key = ?
                  AND edge_type = ?
                  AND visibility = ?
                  AND split = ?
                  AND knowledge_scope = ?
                  AND directionality = 'directional'
                  AND planner_visible = 1
                UNION ALL
                SELECT e.target_key, walk.depth + 1, walk.path || '>' || e.target_key
                FROM research_semantic_edges e
                JOIN walk ON e.source_key = walk.node
                WHERE walk.depth < ?
                  AND e.edge_type = ?
                  AND e.visibility = ?
                  AND e.split = ?
                  AND e.knowledge_scope = ?
                  AND e.directionality = 'directional'
                  AND e.planner_visible = 1
            )
            SELECT path, depth FROM walk WHERE node = ? ORDER BY depth ASC LIMIT 1
            """,
            (
                edge.target_key,
                edge.edge_type,
                edge.visibility,
                edge.split,
                edge.knowledge_scope,
                SHORT_CYCLE_MAX_DEPTH,
                edge.edge_type,
                edge.visibility,
                edge.split,
                edge.knowledge_scope,
                edge.source_key,
            ),
        ).fetchone()
        if cycle:
            return research_models.rejection(
                "semantic_cycle_or_conflict",
                facts={
                    "maxDepthChecked": SHORT_CYCLE_MAX_DEPTH,
                    "conflictKind": "short_cycle",
                    "conflictEdgeType": edge.edge_type,
                    "conflictSourceKey": edge.source_key,
                    "conflictTargetKey": edge.target_key,
                    "cyclePath": str(cycle["path"]),
                    "cycleDepth": int(cycle["depth"]),
                },
            )
        return None

    def _record_rejection(
        self,
        payload: dict[str, Any],
        result: dict[str, Any],
        *,
        con: sqlite3.Connection | None = None,
    ) -> None:
        owned = con is None
        connection = con or mature_learning.connect(self.db_path)
        try:
            proposal_hash = _stable_hash(_safe_projection(payload))
            visibility, split, scope = _proposal_bucket(payload)
            rejection_id = (
                "rj-"
                + _stable_hash(
                    {
                        "proposal_hash": proposal_hash,
                        "error_code": result.get("errorCode"),
                        "visibility": visibility,
                        "split": split,
                        "knowledge_scope": scope,
                    }
                )[:16]
            )
            now = _now()
            connection.execute(
                """
                INSERT INTO research_rejected_proposals(
                    rejection_id, proposal_hash, error_code, visibility, split, knowledge_scope,
                    retry_count, caveats, suggested_repair, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                ON CONFLICT(rejection_id) DO UPDATE SET
                    retry_count = retry_count + 1,
                    caveats = excluded.caveats,
                    suggested_repair = excluded.suggested_repair,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    rejection_id,
                    proposal_hash,
                    str(result.get("errorCode") or "unknown"),
                    visibility,
                    split,
                    scope,
                    _json(result.get("caveats") or []),
                    str(result.get("suggestedRepair") or ""),
                    now,
                    now,
                ),
            )
            if owned:
                connection.commit()
        finally:
            if owned:
                connection.close()


def _copy_safety_error(payload: Any) -> dict[str, Any] | None:
    paths = copy_safety.find_forbidden_paths(payload)
    if paths:
        return research_models.rejection("copy_safety_violation", caveats=["forbidden raw field"])
    flags = copy_safety.durable_knowledge_flags(payload)
    if flags:
        return research_models.rejection("copy_safety_violation", caveats=flags)
    return None


def _endpoint_assessment(
    classification: str,
    missing_endpoint_keys: list[str],
) -> dict[str, Any]:
    reason = {
        "graph_snapshot_unavailable": (
            "No physical graph snapshot was available, so endpoint reality could not be assessed."
        ),
        "source_coverage_gap": (
            "The current physical graph snapshot lacks the proposed endpoint. This can be a static "
            "source coverage gap for a real game entity, so it is not evidence of hallucination by itself."
        ),
    }.get(classification, "Endpoint reality was not assessed.")
    return {
        "classification": classification,
        "hallucinationVerdict": "not_assessed",
        "candidateEndpointKeys": sorted(set(missing_endpoint_keys)),
        "missingEndpointKeys": sorted(set(missing_endpoint_keys)),
        "reason": reason,
        "requiresStaticSourceReview": True,
    }


def _pattern_observation_link_error(
    output: research_models.ResearcherOutput,
) -> dict[str, Any] | None:
    if not output.patterns:
        return None
    if not output.build_design_observations:
        return research_models.rejection(
            "missing_build_design_observation",
            caveats=[
                "Build pattern proposals must be submitted with same-batch BuildDesignObservation evidence."
            ],
            suggested_repair=(
                "First extract BuildDesignObservation components with resolver evidence, then submit "
                "the pattern in the same propose_build_patterns payload."
            ),
        )
    for pattern in output.patterns:
        pattern_keys = set(pattern.component_keys)
        supporting_observations = [
            observation
            for observation in output.build_design_observations
            if _observation_matches_pattern_bucket(observation, pattern)
            and pattern_keys.issubset(
                {component.component_key for component in observation.components}
            )
        ]
        if not supporting_observations:
            observed_keys = {
                component.component_key
                for observation in output.build_design_observations
                if _observation_matches_pattern_bucket(observation, pattern)
                for component in observation.components
            }
            return research_models.rejection(
                "missing_build_design_observation",
                caveats=[
                    "Each pattern must be covered by at least one same-bucket same-version BuildDesignObservation containing all pattern component keys."
                ],
                facts={
                    "missingObservationComponentKeys": sorted(pattern_keys - observed_keys),
                    "requiredComponentKeys": sorted(pattern_keys),
                },
            )
    return None


def _observation_matches_pattern_bucket(
    observation: research_models.BuildDesignObservation,
    pattern: research_models.BuildPatternProposal,
) -> bool:
    return (
        observation.visibility == pattern.visibility
        and observation.split == pattern.split
        and observation.knowledge_scope == pattern.knowledge_scope
        and observation.game_patch == pattern.game_patch
        and observation.passive_tree_version == pattern.passive_tree_version
        and observation.pob_version_or_commit == pattern.pob_version_or_commit
    )


def _revalidation_target_table(target_kind: str) -> tuple[str, str]:
    if target_kind == "fragment":
        return "research_fragments", "fragment_id"
    if target_kind == "semantic_edge":
        return "research_semantic_edges", "edge_id"
    if target_kind == "build_pattern":
        return "research_build_patterns", "pattern_id"
    raise ValueError(f"unsupported revalidation target kind: {target_kind}")


def _planner_visible(status: str, copy_safety_state: str) -> int:
    return 1 if status == "valid" and copy_safety_state == "passed" else 0


def _fragment_id(fragment: research_models.CleanFragmentProposal) -> str:
    return (
        "rf-"
        + _stable_hash(
            {
                "dedupe_key": _fragment_dedupe_key(fragment),
                "visibility": fragment.visibility,
                "split": fragment.split,
                "knowledge_scope": fragment.knowledge_scope,
                "version": {
                    "game_patch": fragment.game_patch,
                    "passive_tree_version": fragment.passive_tree_version,
                },
            }
        )[:16]
    )


def _fragment_dedupe_key(fragment: research_models.CleanFragmentProposal) -> str:
    return _stable_hash(
        {
            "fragment_type": fragment.fragment_type,
            "title": _normalize_text(fragment.title),
            "summary": _normalize_text(fragment.summary),
            "principle": _normalize_text(fragment.reusable_principle),
            "component_keys": sorted(set(fragment.component_keys)),
            "lifecycle_stages": sorted(set(fragment.lifecycle_stages)),
            "modelability": fragment.modelability,
        }
    )


def _chunk_text(fragment: research_models.CleanFragmentProposal) -> str:
    parts = [
        fragment.title,
        fragment.summary,
        fragment.reusable_principle,
        " ".join(fragment.component_keys),
        " ".join(fragment.conditions),
        " ".join(fragment.risks),
        " ".join(fragment.verification_tasks),
    ]
    return "\n".join(part for part in parts if part)


def _edge_identity(edge: research_models.SemanticEdgeProposal) -> tuple[str, str, str]:
    if edge.edge_type == "synergizes_with":
        endpoints = sorted([edge.source_key, edge.target_key])
        source_key, target_key = endpoints[0], endpoints[1]
    else:
        source_key, target_key = edge.source_key, edge.target_key
    payload = {
        "edge_type": edge.edge_type,
        "endpoints": [source_key, target_key],
        "visibility": edge.visibility,
        "split": edge.split,
        "knowledge_scope": edge.knowledge_scope,
        "version": {
            "game_patch": edge.game_patch,
            "passive_tree_version": edge.passive_tree_version,
            "pob_version_or_commit": edge.pob_version_or_commit,
        },
    }
    return "rse-" + _stable_hash(payload)[:16], source_key, target_key


def _observation_id(observation: research_models.BuildDesignObservation) -> str:
    return (
        "bdo-"
        + _stable_hash(
            {
                "observation_type": observation.observation_type,
                "title": _normalize_text(observation.title),
                "axes": sorted(set(observation.axes)),
                "component_keys": sorted(
                    {component.component_key for component in observation.components}
                ),
                "visibility": observation.visibility,
                "split": observation.split,
                "knowledge_scope": observation.knowledge_scope,
                "version": {
                    "game_patch": observation.game_patch,
                    "passive_tree_version": observation.passive_tree_version,
                },
            }
        )[:16]
    )


def _prepare_pattern_for_persistence(
    con: sqlite3.Connection,
    pattern: research_models.BuildPatternProposal,
) -> tuple[research_models.BuildPatternProposal, str, str | None, bool]:
    transfer_key = _pattern_transfer_key(pattern)
    if transfer_key is None:
        return pattern, _pattern_id(pattern), None, False

    existing = con.execute(
        """
        SELECT * FROM research_build_patterns
        WHERE transfer_key = ?
          AND transfer_scope = ?
          AND visibility = ?
          AND split = ?
          AND knowledge_scope = ?
          AND game_patch = ?
          AND passive_tree_version = ?
          AND status IN ('valid', 'needs_revalidation')
        ORDER BY last_seen_at DESC, pattern_id
        LIMIT 1
        """,
        (
            transfer_key,
            pattern.transfer_scope,
            pattern.visibility,
            pattern.split,
            pattern.knowledge_scope,
            pattern.game_patch,
            pattern.passive_tree_version,
        ),
    ).fetchone()
    if existing is None:
        return pattern, _pattern_id(pattern), transfer_key, False

    source_case_refs = sorted(
        set(_loads(existing["source_case_refs"], [])) | set(pattern.source_case_refs)
    )
    safe_evidence_refs = sorted(
        set(_loads(existing["safe_evidence_refs"], [])) | set(pattern.safe_evidence_refs)
    )
    origin_family_keys = sorted(
        set(_loads(existing["origin_family_keys"], [])) | set(pattern.origin_family_keys)
    )
    sample_count = max(
        len(source_case_refs), int(existing["sample_count"] or 0), pattern.sample_count
    )
    family_count = (
        len(origin_family_keys)
        if pattern.transfer_scope == "component"
        else max(int(existing["family_count"] or 0), pattern.family_count)
    )
    source_diversity_count = max(
        int(existing["source_diversity_count"] or 0), pattern.source_diversity_count
    )
    confidence_tier = _transfer_confidence_tier(
        sample_count=sample_count,
        family_count=family_count,
        source_diversity_count=source_diversity_count,
    )
    existing_tier = str(existing["confidence_tier"] or "case_observation")
    promoted = _transfer_confidence_rank(confidence_tier) > _transfer_confidence_rank(existing_tier)
    denominator_values = [
        value
        for value in (existing["denominator"], pattern.denominator, sample_count)
        if value is not None
    ]
    merged = pattern.model_copy(
        update={
            "confidence_tier": confidence_tier,
            "sample_count": sample_count,
            "family_count": family_count,
            "source_diversity_count": source_diversity_count,
            "denominator": max(int(value) for value in denominator_values),
            "source_case_refs": source_case_refs,
            "safe_evidence_refs": safe_evidence_refs,
            "origin_family_keys": origin_family_keys,
        }
    )
    return merged, str(existing["pattern_id"]), transfer_key, promoted


def _pattern_transfer_key(pattern: research_models.BuildPatternProposal) -> str | None:
    if pattern.transfer_scope == "family":
        return None
    return (
        "tpk-"
        + _stable_hash(
            {
                "transfer_scope": pattern.transfer_scope,
                "pattern_type": pattern.pattern_type,
                "component_roles": sorted(pattern.component_roles.items()),
                "applicability_axes": sorted(set(pattern.applicability_axes)),
                "visibility": pattern.visibility,
                "split": pattern.split,
                "knowledge_scope": pattern.knowledge_scope,
                "version": {
                    "game_patch": pattern.game_patch,
                    "passive_tree_version": pattern.passive_tree_version,
                },
            }
        )[:20]
    )


def _transfer_confidence_tier(
    *, sample_count: int, family_count: int, source_diversity_count: int
) -> str:
    if sample_count >= 4 and family_count >= 2 and source_diversity_count >= 2:
        return "likely_pattern"
    if sample_count >= 2 and family_count >= 2:
        return "recurring_observation"
    return "case_observation"


def _transfer_confidence_rank(value: str) -> int:
    return {
        "case_observation": 0,
        "recurring_observation": 1,
        "likely_pattern": 2,
    }.get(value, 0)


def _pattern_id(pattern: research_models.BuildPatternProposal) -> str:
    transfer_key = _pattern_transfer_key(pattern)
    if transfer_key is not None:
        return "bdp-" + _stable_hash({"transfer_key": transfer_key})[:16]
    return (
        "bdp-"
        + _stable_hash(
            {
                "pattern_type": pattern.pattern_type,
                "title": _normalize_text(pattern.title),
                "component_keys": sorted(set(pattern.component_keys)),
                "visibility": pattern.visibility,
                "split": pattern.split,
                "knowledge_scope": pattern.knowledge_scope,
                "version": {
                    "game_patch": pattern.game_patch,
                    "passive_tree_version": pattern.passive_tree_version,
                },
            }
        )[:16]
    )


def _deep_record_proposal_from_row(
    row: sqlite3.Row,
) -> research_models.DeepResearchRecordProposal | None:
    try:
        return research_models.DeepResearchRecordProposal.model_validate(
            {
                "research_group_id": row["research_group_id"],
                "record_kind": row["record_kind"],
                "title": row["title"],
                "summary": row["summary"],
                "content": row["content"],
                "content_language": row["content_language"],
                "length_exception_reason": row["length_exception_reason"],
                "component_keys": _loads(row["component_keys"], []),
                "component_mentions": _loads(row["component_mentions"], []),
                "source_case_refs": _loads(row["source_case_refs"], []),
                "safe_evidence_refs": _loads(row["safe_evidence_refs"], []),
                "conditions": _loads(row["conditions"], []),
                "failure_conditions": _loads(row["failure_conditions"], []),
                "typed_payload": _loads(row["typed_payload"], {}),
                "class_key": row["class_key"],
                "ascendancy_key": row["ascendancy_key"],
                "extraction_method_version": row["extraction_method_version"],
                "record_schema_version": int(row["record_schema_version"]),
                "game_patch": row["game_patch"],
                "passive_tree_version": row["passive_tree_version"],
                "pob_version_or_commit": row["pob_version_or_commit"],
                "visibility": row["visibility"],
                "split": row["split"],
                "knowledge_scope": row["knowledge_scope"],
                "status": row["status"],
                "copy_safety_state": row["copy_safety_state"],
            }
        )
    except (KeyError, TypeError, ValueError):
        return None


def _historical_family_hints(
    con: sqlite3.Connection,
) -> dict[str, set[tuple[str, str]]]:
    """Reuse safe, resolved observation/pattern roles to repair older record scope metadata."""

    hints: dict[str, set[tuple[str, str]]] = {}
    observation_rows = con.execute(
        """
        SELECT source_case_refs, components
        FROM research_build_design_observations
        WHERE copy_safety_state = 'passed'
        """
    ).fetchall()
    for row in observation_rows:
        pairs = {
            (str(item.get("role") or ""), str(item.get("component_key") or ""))
            for item in _loads(row["components"], [])
            if isinstance(item, dict)
            and str(item.get("role") or "")
            and str(item.get("component_key") or "")
        }
        for source_ref in _loads(row["source_case_refs"], []):
            hints.setdefault(str(source_ref), set()).update(pairs)

    pattern_rows = con.execute(
        """
        SELECT source_case_refs, component_roles
        FROM research_build_patterns
        WHERE copy_safety_state = 'passed'
          AND status IN ('valid', 'needs_revalidation')
        """
    ).fetchall()
    for row in pattern_rows:
        roles = _loads(row["component_roles"], {})
        pairs = (
            {(str(role), str(component_key)) for component_key, role in roles.items()}
            if isinstance(roles, dict)
            else set()
        )
        for source_ref in _loads(row["source_case_refs"], []):
            hints.setdefault(str(source_ref), set()).update(pairs)
    return hints


def _sibling_family_hints(
    con: sqlite3.Connection, build_family_keys: set[str]
) -> list[dict[str, Any]]:
    """Advisory hints when a written family overlaps an existing family's identity.

    Identity is the canonical primary-skill SET (gem-equivalence expanded), so hints
    compare sets rather than the legacy single ``primary_skill_key``: a new family whose
    canonical set equals, contains, or is contained by an existing family's set is
    flagged with the relationship so the researcher can confirm the automatic join
    behaviour (accept already joins; these hints are the visibility layer).
    Advisory-only and never gates acceptance.
    """
    hints: list[dict[str, Any]] = []
    idx = skill_equivalence.SkillEquivalenceIndex.shared()
    for family_key in sorted(build_family_keys):
        row = con.execute(
            """
            SELECT build_family_key, ascendancy_key, primary_skill_key, primary_skill_keys
            FROM research_build_families
            WHERE build_family_key = ?
            """,
            (family_key,),
        ).fetchone()
        if row is None:
            continue
        new_keys = _loads(row["primary_skill_keys"], None)
        if not new_keys:
            new_keys = [str(row["primary_skill_key"] or "")] if row["primary_skill_key"] else []
        if not new_keys:
            continue
        canon_new = idx.canonical_set(new_keys)
        siblings = con.execute(
            """
            SELECT build_family_key, primary_skill_key, primary_skill_keys, secondary_skill_keys
            FROM research_build_families
            WHERE ascendancy_key = ?
              AND build_family_key != ?
            ORDER BY evidence_count DESC, build_family_key
            LIMIT 10
            """,
            (row["ascendancy_key"], family_key),
        ).fetchall()
        for sibling in siblings:
            sibling_keys = _loads(sibling["primary_skill_keys"], None)
            if not sibling_keys:
                sibling_keys = (
                    [str(sibling["primary_skill_key"] or "")]
                    if sibling["primary_skill_key"]
                    else []
                )
            if not sibling_keys:
                continue
            canon_existing = idx.canonical_set(sibling_keys)
            if not (canon_new & canon_existing):
                continue
            if canon_new == canon_existing:
                relation = "identical"
            elif canon_new < canon_existing:
                relation = "subset_of_existing"
            elif canon_existing < canon_new:
                relation = "superset_of_existing"
            else:
                relation = "overlap"
            hints.append(
                {
                    "familyKey": family_key,
                    "ascendancyKey": row["ascendancy_key"],
                    "primarySkillKeys": new_keys,
                    "relation": relation,
                    "siblingFamilyKey": str(sibling["build_family_key"]),
                    "siblingPrimarySkillKeys": sibling_keys,
                }
            )
    return hints


def _deep_record_id(record: research_models.DeepResearchRecordProposal) -> str:
    return (
        "drr-"
        + _stable_hash(
            {
                "research_group_id": record.research_group_id,
                "record_kind": record.record_kind,
                "title": _normalize_text(record.title),
                "component_keys": sorted(set(record.component_keys)),
                "component_mentions": [
                    mention.model_dump(mode="json") for mention in record.component_mentions
                ],
                "source_case_refs": sorted(set(record.source_case_refs)),
                "visibility": record.visibility,
                "split": record.split,
                "knowledge_scope": record.knowledge_scope,
            }
        )[:16]
    )


def _pattern_planner_visible(pattern: research_models.BuildPatternProposal) -> int:
    return 1 if pattern.visibility == "creator_visible" and pattern.split == "train_context" else 0


def _proposal_bucket(payload: Any) -> tuple[str, str, str]:
    if not isinstance(payload, dict):
        return "unknown", "unknown", "unknown"
    for key in (
        "fragments",
        "semantic_edges",
        "build_design_observations",
        "patterns",
        "deep_research_records",
    ):
        values = payload.get(key)
        if isinstance(values, list) and values and isinstance(values[0], dict):
            row = values[0]
            return (
                str(row.get("visibility") or "unknown"),
                str(row.get("split") or "unknown"),
                str(row.get("knowledge_scope") or "unknown"),
            )
    return "unknown", "unknown", "unknown"


def _safe_projection(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            str(key): _safe_projection(value)
            for key, value in payload.items()
            if not copy_safety.find_forbidden_paths({key: value})
        }
    if isinstance(payload, list):
        return [_safe_projection(item) for item in payload]
    if isinstance(payload, str):
        if copy_safety.copyability_flags(payload):
            return "redacted-copyable-text"
        return payload[:240]
    return payload


def _stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _research_premise_id(record_id: str, premise_type: str, text: str) -> str:
    return (
        "rp-"
        + _stable_hash(
            {
                "recordId": record_id,
                "premiseType": premise_type,
                "text": _normalize_text(text),
            }
        )[:16]
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def _search_terms(value: str) -> list[str]:
    return [term for term in re.findall(r"[\w:.-]+", value, flags=re.UNICODE) if len(term) >= 2]


def _fts_query(value: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_:]+", value)
    return " ".join(f'"{term}"' for term in terms) if terms else '""'
