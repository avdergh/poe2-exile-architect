"""Source-local revisions of shared, exact Research conclusions.

Knowledge keys identify topics, not a single mutable winning paragraph.  A current source claim
points at an exact record and projection; another source never follows a revision implicitly.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import research_runtime


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def variant_record_id(scope: str, key: str, projection_hash: str) -> str:
    return (
        "drr-"
        + research_runtime.stable_hash(
            {"knowledge_scope": scope, "knowledge_key": key, "projection_hash": projection_hash}
        )[:16]
    )


def source_claim_identity(record: Any, source_ref: str, key: str) -> tuple[str, ...]:
    return (
        record.knowledge_scope,
        key,
        source_ref,
        record.source_claim_key,
        record.game_patch,
        record.passive_tree_version,
    )


def has_source_claim_collision(records: list[Any], key: str) -> bool:
    seen: set[tuple[str, ...]] = set()
    for record in records:
        identities = {
            source_claim_identity(record, source, key) for source in record.source_case_refs
        }
        if seen & identities:
            return True
        seen.update(identities)
    return False


def validate_source_claim_revisions(
    con: sqlite3.Connection | None, records: list[tuple[Any, str | None]]
) -> str | None:
    """Validate all retractions against the pre-write snapshot, never an earlier batch row."""
    targets = {
        source_claim_identity(record, source, key)
        for record, key in records if key
        for source in record.source_case_refs
    }
    retractions: set[tuple[str, ...]] = set()
    for record, key in records:
        revision = record.source_claim_revision
        if revision is None:
            continue
        if key is None:
            return "source_claim_revision_target_unkeyed"
        old_identities = {
            source_claim_identity(record, source, revision.knowledge_key)
            for source in record.source_case_refs
        }
        if old_identities & (targets | retractions):
            return "source_claim_revision_batch_conflict"
        retractions.update(old_identities)
        if con is None:
            return "source_claim_revision_binding_missing"
        old = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id=?", (revision.record_id,)
        ).fetchone()
        if (
            old is None
            or old["knowledge_scope"] != record.knowledge_scope
            or old["knowledge_key"] != revision.knowledge_key
            or old["projection_hash"] != revision.projection_hash
            or research_runtime.projection_hash(old) != revision.projection_hash
            or old["game_patch"] != record.game_patch
            or old["passive_tree_version"] != record.passive_tree_version
            or old["pob_version_or_commit"] != record.pob_version_or_commit
            or old["source_state_scope"] != record.source_state_scope
            or old["record_schema_version"] < 2
            or old["source_state_scope"] == "unknown"
            or old["superseded_by_id"] is not None
        ):
            return "source_claim_revision_binding_mismatch"
        for identity in old_identities:
            claim = con.execute(
                "SELECT * FROM deep_research_record_evidence WHERE knowledge_scope=? "
                "AND knowledge_key=? AND source_case_ref=? AND source_claim_key=? "
                "AND game_patch=? AND passive_tree_version=?", identity,
            ).fetchone()
            if claim is None:
                return "source_claim_revision_binding_missing"
            if (
                claim["record_id"] != revision.record_id
                or claim["accepted_projection_hash"] != revision.projection_hash
                or claim["binding_issue"] is not None
                or claim["source_state_scope"] != record.source_state_scope
                or claim["pob_version_or_commit"] != record.pob_version_or_commit
            ):
                return "source_claim_revision_binding_mismatch"
            target_identity = source_claim_identity(record, identity[2], key)
            if con.execute(
                "SELECT 1 FROM deep_research_record_evidence WHERE knowledge_scope=? "
                "AND knowledge_key=? AND source_case_ref=? AND source_claim_key=? "
                "AND game_patch=? AND passive_tree_version=?", target_identity,
            ).fetchone() is not None:
                return "source_claim_revision_target_already_claimed"
    return None


def refresh_record_evidence(con: sqlite3.Connection, record_id: str, now: str) -> None:
    """Count independent current sources, not repeated claims or historical mentions."""
    row = con.execute(
        "SELECT * FROM deep_research_records WHERE record_id=?", (record_id,)
    ).fetchone()
    if row is None:
        return
    evidence = con.execute(
        "SELECT source_case_ref,safe_evidence_refs FROM deep_research_record_evidence "
        "WHERE record_id=? AND knowledge_scope=? AND knowledge_key=? "
        "AND accepted_projection_hash=? "
        "AND (binding_issue IS NULL OR binding_issue IN ('legacy_record_schema','source_state_unknown')) "
        "AND game_patch=? AND passive_tree_version=? AND source_state_scope=?",
        (
            record_id,
            row["knowledge_scope"],
            row["knowledge_key"],
            row["projection_hash"],
            row["game_patch"],
            row["passive_tree_version"],
            row["source_state_scope"],
        ),
    ).fetchall()
    sources = sorted({item["source_case_ref"] for item in evidence})
    refs = sorted({ref for item in evidence for ref in json.loads(item["safe_evidence_refs"])})
    # Retain unsupported old content for traceability, but do not expose it as a current conclusion.
    status = str(row["status"]) if sources else "deprecated"
    con.execute(
        "UPDATE deep_research_records SET source_case_refs=?,safe_evidence_refs=?,"
        "evidence_count=?,status=?,last_seen_at=? WHERE record_id=?",
        (_json(sources), _json(refs), len(sources), status, now, record_id),
    )


def persist_record(
    service: Any, con: sqlite3.Connection, *, record: Any, family: Any, now: str
) -> dict[str, Any]:
    """Persist one validated logical statement and move only its explicit source claims."""
    from . import research_identity

    # Match the existing storage normalization before hashing or selecting a shared conclusion.
    record = record.model_copy(update={"component_keys": sorted(set(record.component_keys))})
    key = research_identity.knowledge_key(record, family)
    scope = record.knowledge_scope
    projection = research_runtime.projection_hash(record.model_dump(mode="json"))
    identities = {source_claim_identity(record, source, key) for source in record.source_case_refs}
    claim_where = (
        "knowledge_scope=? AND knowledge_key=? AND source_case_ref=? AND source_claim_key=? "
        "AND game_patch=? AND passive_tree_version=?"
    )
    previous_claims = [
        row
        for identity in sorted(identities)
        if (
            row := con.execute(
                "SELECT * FROM deep_research_record_evidence WHERE " + claim_where, identity
            ).fetchone()
        )
        is not None
    ]
    obsolete_claims = [
        source_claim_identity(record, source, record.source_claim_revision.knowledge_key)
        for source in sorted(set(record.source_case_refs))
    ] if record.source_claim_revision is not None else []
    previous_claims.extend(
        con.execute(
            "SELECT * FROM deep_research_record_evidence WHERE " + claim_where, identity
        ).fetchone()
        for identity in obsolete_claims
    )
    previous_ids = {str(row["record_id"]) for row in previous_claims if row["record_id"]}
    target = con.execute(
        "SELECT * FROM deep_research_records WHERE knowledge_scope=? AND knowledge_key=? "
        "AND projection_hash=? AND superseded_by_id IS NULL AND status=? "
        "ORDER BY record_id LIMIT 1",
        (scope, key, projection, record.status),
    ).fetchone()
    if target is not None and research_runtime.projection_hash(target) != projection:
        target = None
    changed_in_place = False
    identity_changed = False
    before_hash: str | None = None
    previous_family: str | None = None
    # New topics coexist even if their display titles match. Only an explicit validated
    # source_claim_revision can retract a different topic; legacy/unbound rows stay diagnostic.
    if len(previous_ids) == 1:
        old_id = next(iter(previous_ids))
        old = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id=?", (old_id,)
        ).fetchone()
        owners = con.execute(
            "SELECT knowledge_scope,knowledge_key,source_case_ref,source_claim_key,game_patch,"
            "passive_tree_version FROM deep_research_record_evidence WHERE record_id=?",
            (old_id,),
        ).fetchall()
        # An exclusively owned record can retain its legacy ID. Shared records use copy-on-write.
        owned = all(
            tuple(owner) in identities | set(obsolete_claims)
            for owner in owners
        )
        if old is not None and obsolete_claims:
            previous_family = old["build_family_key"]
        legacy_owned = (
            old is not None
            and not owners
            and (set(json.loads(old["source_case_refs"])) == set(record.source_case_refs))
        )
        is_variant = old is not None and old_id == variant_record_id(
            scope, str(old["knowledge_key"] or ""), str(old["projection_hash"] or "")
        )
        if (
            target is None
            and old is not None
            and not is_variant
            and ((owners and owned) or legacy_owned)
        ):
            if old["knowledge_scope"] == scope:
                target = old
                changed_in_place = True
                before_hash = research_runtime.projection_hash(old)
                previous_family = old["build_family_key"]
                identity_changed = (
                    old["knowledge_key"] != key
                    or old["build_family_key"] != family.key
                    or old["status"] != record.status
                    or old["superseded_by_id"] is not None
                )
                head_id = old["superseded_by_id"]
                seen = {old_id}
                head = None
                while head_id and head_id not in seen:
                    seen.add(head_id)
                    head = con.execute(
                        "SELECT * FROM deep_research_records WHERE record_id=?", (head_id,)
                    ).fetchone()
                    if head is None:
                        break
                    head_id = head["superseded_by_id"]
                if head is not None and head["status"] != "deprecated" and not head_id:
                    # Keep aliases on their old active head, not on the fresh acceptance below.
                    con.execute(
                        "UPDATE deep_research_records SET superseded_by_id=? WHERE superseded_by_id=?",
                        (head["record_id"], old_id),
                    )
                    con.execute("DELETE FROM deep_research_records WHERE record_id=?", (old_id,))
                    target = None
                    changed_in_place = False
    created = target is None
    if created:
        anchor = research_runtime.canonical_record_id(scope, key)
        occupied = con.execute(
            "SELECT 1 FROM deep_research_records WHERE record_id=?", (anchor,)
        ).fetchone()
        record_id = variant_record_id(scope, key, projection) if occupied else anchor
        collision = con.execute(
            "SELECT * FROM deep_research_records WHERE record_id=?", (record_id,)
        ).fetchone()
        if collision is not None:
            owners = con.execute(
                "SELECT 1 FROM deep_research_record_evidence WHERE record_id=? LIMIT 1",
                (record_id,),
            ).fetchone()
            if owners or collision["knowledge_scope"] != scope or collision["knowledge_key"] != key:
                raise ValueError("research_claim_record_id_collision")
            # A retired exact variant can be explicitly re-accepted; never infer another source's approval.
            target = collision
            created = False
            changed_in_place = True
            before_hash = research_runtime.projection_hash(collision)
    else:
        record_id = str(target["record_id"])
    if created or changed_in_place:
        values = service._deep_record_values(
            record,
            record_id=record_id,
            build_family_key=family.key,
            knowledge_key=key,
            evidence_count=0,
            now=now,
        )
        if created:
            columns = list(values)
            con.execute(
                f"INSERT INTO deep_research_records({','.join(columns)}) "
                f"VALUES ({','.join('?' for _ in columns)})",
                tuple(values.values()),
            )
        else:
            values["created_at"] = target["created_at"]
            fields = [name for name in values if name != "record_id"]
            con.execute(
                "UPDATE deep_research_records SET "
                + ",".join(f"{name}=?" for name in fields)
                + " WHERE record_id=?",
                (*(values[name] for name in fields), record_id),
            )
    else:
        before_hash = str(target["projection_hash"] or "") or None
    evidence_added = 0
    binding_issue = (
        "legacy_record_schema"
        if record.record_schema_version < 2
        else "source_state_unknown"
        if record.source_state_scope == "unknown"
        else None
    )
    for identity in sorted(identities):
        source = identity[2]
        already_supported = con.execute(
            "SELECT 1 FROM deep_research_record_evidence WHERE knowledge_scope=? AND knowledge_key=? "
            "AND source_case_ref=? AND game_patch=? AND passive_tree_version=? LIMIT 1",
            (scope, key, source, record.game_patch, record.passive_tree_version),
        ).fetchone()
        evidence_added += int(already_supported is None)
        old_claim = con.execute(
            "SELECT * FROM deep_research_record_evidence WHERE " + claim_where, identity
        ).fetchone()
        refs = set(record.safe_evidence_refs)
        if old_claim is not None and old_claim["accepted_projection_hash"] == projection:
            refs.update(json.loads(old_claim["safe_evidence_refs"]))
        con.execute(
            "INSERT INTO deep_research_record_evidence(knowledge_scope,knowledge_key,source_case_ref,"
            "source_claim_key,game_patch,passive_tree_version,safe_evidence_refs,observed_component_keys,"
            "observed_component_mentions,conditions,failure_conditions,pob_version_or_commit,"
            "accepted_projection_hash,source_state_scope,first_seen_at,last_seen_at,record_id,binding_issue) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(knowledge_scope,knowledge_key,source_case_ref,source_claim_key,game_patch,passive_tree_version) "
            "DO UPDATE SET safe_evidence_refs=excluded.safe_evidence_refs,"
            "observed_component_keys=excluded.observed_component_keys,"
            "observed_component_mentions=excluded.observed_component_mentions,conditions=excluded.conditions,"
            "failure_conditions=excluded.failure_conditions,pob_version_or_commit=excluded.pob_version_or_commit,"
            "accepted_projection_hash=excluded.accepted_projection_hash,source_state_scope=excluded.source_state_scope,"
            "last_seen_at=excluded.last_seen_at,record_id=excluded.record_id,binding_issue=excluded.binding_issue",
            (
                *identity,
                _json(sorted(refs)),
                _json(sorted(set(record.component_keys))),
                _json([mention.model_dump(mode="json") for mention in record.component_mentions]),
                _json(record.conditions),
                _json(record.failure_conditions),
                record.pob_version_or_commit,
                projection,
                record.source_state_scope,
                now,
                now,
                record_id,
                binding_issue,
            ),
        )
    for identity in obsolete_claims:
        con.execute("DELETE FROM deep_research_record_evidence WHERE " + claim_where, identity)
    for affected_id in sorted(previous_ids | {record_id}):
        refresh_record_evidence(con, affected_id, now)
    revised_binding = any(
        claim["record_id"] != record_id
        or claim["accepted_projection_hash"] != projection
        or claim["binding_issue"] != binding_issue
        for claim in previous_claims
    )
    return {
        "record_id": record_id,
        "knowledge_key": key,
        "previous_build_family_key": previous_family,
        "created": created,
        "semantic_changed": created
        or revised_binding
        or bool(obsolete_claims)
        or (changed_in_place and (before_hash != projection or identity_changed)),
        "before_projection_hash": before_hash,
        "evidence_added_count": evidence_added,
        "crossFamilyDuplicateAdvisories": service._cross_family_duplicate_advisories(
            con, record, family
        ),
    }
