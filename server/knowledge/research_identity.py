"""Deterministic identities for Phase 4 build families and knowledge units."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from . import research_models


PRIMARY_ROLES = ("primary_damage",)
PRIMARY_FALLBACK_ROLES = ("boss_skill",)
SECONDARY_ROLES = ("clear_skill", "boss_skill", "triggered_payload")
FAMILY_IDENTITY_RECORD_KINDS = {"skill_package", "mechanic_chain"}
FAMILY_NON_AUTHORIZING_RECORD_KINDS = {
    "modelability_caveat",
    "failure_mode",
    "open_question",
}
_IDENTITY_TAG_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_KIND_IDENTITY_ROLES: dict[str, tuple[str, ...]] = {
    "skill_package": (
        "primary_damage",
        "clear_skill",
        "boss_skill",
        "secondary_skill",
        "triggered_payload",
    ),
    "mechanic_chain": (
        "generator",
        "trigger_host",
        "keystone_transformer",
        "resource_engine",
        "secondary_skill",
        "triggered_payload",
        "payoff",
        "primary_damage",
        "passive_anchor",
        "unique_enabler",
    ),
    "gear_synergy": (
        "gear_base",
        "weapon_base",
        "unique_enabler",
        "primary_damage",
        "secondary_skill",
        "keystone_transformer",
        "passive_anchor",
    ),
    "passive_package": (
        "ascendancy_shell",
        "keystone_transformer",
        "passive_anchor",
    ),
    "rotation": (
        "generator",
        "control_skill",
        "clear_skill",
        "secondary_skill",
        "primary_damage",
        "boss_skill",
        "triggered_payload",
        "payoff",
        "movement",
    ),
    "defense_engine": (
        "keystone_transformer",
        "defense_layer",
        "defensive_buff",
        "passive_anchor",
        "unique_enabler",
    ),
    "resource_engine": (
        "resource_engine",
        "generator",
        "reservation",
        "keystone_transformer",
        "payoff",
    ),
    "failure_mode": (
        "primary_damage",
        "secondary_skill",
        "resource_engine",
        "defense_layer",
        "unique_enabler",
        "keystone_transformer",
    ),
    "modelability_caveat": (
        "primary_damage",
        "clear_skill",
        "boss_skill",
        "secondary_skill",
        "triggered_payload",
        "unique_enabler",
        "gear_base",
        "weapon_base",
    ),
}

_KIND_ROLE_BUCKETS: dict[str, dict[str, str]] = {
    "gear_synergy": {
        "gear_base": "gear_enabler",
        "weapon_base": "gear_enabler",
        "unique_enabler": "gear_enabler",
    },
    "passive_package": {
        "ascendancy_shell": "passive_core",
        "keystone_transformer": "passive_core",
        "passive_anchor": "passive_core",
    },
    "defense_engine": {
        "keystone_transformer": "defense_core",
        "defense_layer": "defense_core",
        "defensive_buff": "defense_core",
        "passive_anchor": "defense_core",
    },
    "modelability_caveat": {
        "primary_damage": "modelled_skill",
        "clear_skill": "modelled_skill",
        "boss_skill": "modelled_skill",
        "secondary_skill": "modelled_skill",
        "triggered_payload": "modelled_skill",
        "unique_enabler": "state_enabler",
        "gear_base": "state_enabler",
        "weapon_base": "state_enabler",
    },
}


def kind_identity_roles() -> dict[str, dict[str, object]]:
    """Public identity-role contract for the research review-contract.

    Maps each explicit record kind to the component roles that can constitute its
    knowledge identity (single source of truth for acceptance), plus the fallback
    semantics applied to kinds without an explicit mapping and the role-bucket labels
    that determine how identity role components are labelled.
    """

    return {
        "explicitRoles": {kind: list(roles) for kind, roles in _KIND_IDENTITY_ROLES.items()},
        "fallback": {
            "kindsWithoutExplicitRoles": sorted(
                research_models.DEEP_RESEARCH_RECORD_KINDS - set(_KIND_IDENTITY_ROLES)
            ),
            "rule": (
                "kinds without an explicit identity-role mapping take any mention role "
                "except support_modifier / scaling_stat as identity"
            ),
        },
        "roleBuckets": {kind: dict(buckets) for kind, buckets in _KIND_ROLE_BUCKETS.items()},
    }


@dataclass(frozen=True)
class BuildFamilyIdentity:
    ascendancy_key: str
    primary_skill_keys: tuple[str, ...]
    secondary_skill_keys: tuple[str, ...] = ()
    authoritative_key: str | None = field(default=None, compare=False)

    @property
    def primary_skill_key(self) -> str:
        """Primary representative skill (first, for legacy single-value consumers)."""
        return self.primary_skill_keys[0] if self.primary_skill_keys else ""

    @property
    def key(self) -> str:
        """Identity key: ascendancy + the full primary-skill SET.

        Secondary skills and trigger hosts are deliberately excluded: they are knowledge
        inside the family, not identity. Two families compare equal when their canonical
        primary sets compare equal (see ``skill_equivalence``).

        A matched stored Family may carry a legacy key generated by an older identity
        version. In that join path the database key remains authoritative: recomputing the
        current hash would split one semantic Family into two rows.
        """
        if self.authoritative_key:
            return self.authoritative_key
        return (
            "bf-"
            + _stable_hash(
                {
                    "ascendancy_key": self.ascendancy_key,
                    "primary_skill_keys": list(self.primary_skill_keys),
                }
            )[:20]
        )


def infer_build_family(
    records: Iterable[Any],
    *,
    allow_dominant_primary: bool = False,
    allow_multi_primary: bool = True,
) -> BuildFamilyIdentity | None:
    """Infer a high-confidence family from one case/research group.

    Family identity is ``ascendancy + the SET of primary-damage skills``: every skill a
    researcher declares as primary damage participates (e.g. a CoC build may declare both
    Comet and Spark). Automatic secondary roles (clear/boss/triggered-payload) and trigger
    hosts never participate in identity; they are kept as metadata only. Ambiguous
    ascendancy or empty primary evidence is left unclassified instead of guessed.

    ``allow_multi_primary=False`` keeps the legacy fail-closed ambiguity semantics for
    lightweight identity evidence (e.g. Phase 7 blind-create profiles): more than one
    distinct primary skill there means the identity is ambiguous and must not be adopted.
    Durable research accepts keep the set semantics (``allow_multi_primary=True``).
    """

    rows = list(records)
    ascendancies = {
        key for row in rows for key in _ascendancy_candidates(row) if _is_stable_component_key(key)
    }
    identity_rows = [
        row
        for row in rows
        if str(_value(row, "record_kind", "") or "") in FAMILY_IDENTITY_RECORD_KINDS
    ]
    primary_rows = identity_rows or [
        row
        for row in rows
        if str(_value(row, "record_kind", "") or "") not in FAMILY_NON_AUTHORIZING_RECORD_KINDS
    ]
    primary_keys = {
        key
        for row in primary_rows
        for key in _role_component_keys(row, PRIMARY_ROLES)
        if _is_skill_key(key)
    }
    if not primary_keys:
        primary_keys = {
            key
            for row in primary_rows
            for key in _role_component_keys(row, PRIMARY_FALLBACK_ROLES)
            if _is_skill_key(key)
        }
    if len(ascendancies) != 1 or not primary_keys:
        return None
    if len(primary_keys) > 1 and not allow_multi_primary:
        return None
    secondary = set(automatic_family_skill_keys(identity_rows))
    secondary -= primary_keys
    secondary.update(
        key
        for row in identity_rows
        for key in family_core_skill_keys(row)
        if key not in primary_keys
    )
    return BuildFamilyIdentity(
        ascendancy_key=next(iter(ascendancies)),
        primary_skill_keys=tuple(sorted(primary_keys)),
        secondary_skill_keys=tuple(sorted(secondary)),
    )


def knowledge_identity(record: Any, family: BuildFamilyIdentity) -> dict[str, Any] | None:
    """Return the structured identity used for conservative canonical deduplication."""

    kind = str(_value(record, "record_kind", "") or "").strip()
    try:
        record_schema_version = int(_value(record, "record_schema_version", 1) or 1)
    except (TypeError, ValueError):
        record_schema_version = 1
    roles = _KIND_IDENTITY_ROLES.get(kind)
    if roles is None:
        roles = tuple(
            sorted(
                {
                    str(mention.get("role") or "")
                    for mention in _mentions(record)
                    if str(mention.get("role") or "") not in {"support_modifier", "scaling_stat"}
                }
            )
        )

    role_components: list[tuple[str, str]] = []
    if kind == "skill_package":
        for role in roles:
            keys = sorted(
                key for key in _role_component_keys(record, (role,)) if _is_skill_key(key)
            )
            if keys:
                role_components.append(("subject_skill", keys[0]))
                break
        packages = support_ownership_packages(record)
        if packages:
            role_components.extend(
                (
                    "support_package",
                    _stable_package_value(
                        skill_key,
                        support_keys,
                        delivery_role=(delivery_role if record_schema_version >= 2 else None),
                        host_skill_key=(host_skill_key if record_schema_version >= 2 else None),
                    ),
                )
                for skill_key, support_keys, delivery_role, host_skill_key in packages
            )
        else:
            # Legacy records did not declare socket ownership. Preserve their support set in the
            # identity so distinct variants no longer overwrite one another during backfill.
            role_components.extend(
                ("support_modifier", key)
                for key in sorted(set(_role_component_keys(record, ("support_modifier",))))
                if _is_stable_component_key(key)
            )
    else:
        role_buckets = _KIND_ROLE_BUCKETS.get(kind, {})
        for role in roles:
            for key in sorted(set(_role_component_keys(record, (role,)))):
                if _is_stable_component_key(key):
                    role_components.append((role_buckets.get(role, role), key))
        role_components = sorted(set(role_components))

        # Support ownership is meaningful outside ``skill_package`` too.  Earlier identity
        # versions ignored it on defense/resource records, which allowed distinct socket
        # packages to overwrite one another under the same Family/kind/component identity.
        if record_schema_version >= 2:
            role_components.extend(
                (
                    "support_package",
                    _stable_package_value(
                        skill_key,
                        support_keys,
                        delivery_role=delivery_role,
                        host_skill_key=host_skill_key,
                    ),
                )
                for skill_key, support_keys, delivery_role, host_skill_key in support_ownership_packages(
                    record
                )
            )
            role_components = sorted(set(role_components))

    if kind == "resource_engine":
        role_components.extend(
            ("resource_mechanism", tag) for tag in resource_mechanism_tags(record)
        )
        role_components = sorted(set(role_components))

    if kind == "gear_synergy" and record_schema_version >= 2:
        role_components.extend(
            ("gear_subject", subject)
            for subject in _typed_string_list(record, "gearSubjects", "gear_subjects")
        )
        role_components = sorted(set(role_components))

    if record_availability(record) == "source_specific_random":
        role_components.append(("availability", "source_specific_random"))
        role_components = sorted(set(role_components))

    if not role_components:
        return None
    return {
        "build_family_key": family.key,
        "record_kind": kind,
        "role_components": role_components,
    }


def knowledge_key(record: Any, family: BuildFamilyIdentity) -> str | None:
    identity = knowledge_identity(record, family)
    return "ku-" + _stable_hash(identity)[:20] if identity is not None else None


def record_quality(record: Any) -> tuple[int, int, int, int]:
    """Rank canonical representatives without treating prose similarity as identity."""

    mentions = _mentions(record)
    resolved = sum(
        1
        for mention in mentions
        if mention.get("component_key") and mention.get("resolution_status") == "resolved"
    )
    distinct_roles = len({str(item.get("role") or "") for item in mentions})
    conditions = len(_list_value(record, "conditions")) + len(
        _list_value(record, "failure_conditions")
    )
    content_length = len(re.sub(r"\s+", "", str(_value(record, "content", "") or "")))
    return resolved, distinct_roles, conditions, min(content_length, 2000)


def family_core_skill_keys(record: Any) -> tuple[str, ...]:
    """Return explicitly reviewed core secondary skills from the typed payload."""

    if str(_value(record, "record_kind", "") or "") not in FAMILY_IDENTITY_RECORD_KINDS:
        return ()
    values = _typed_string_list(record, "familyCoreSkillKeys", "family_core_skill_keys")
    return tuple(sorted({value for value in values if _is_skill_key(value)}))


def automatic_family_skill_keys(records: Iterable[Any]) -> tuple[str, ...]:
    """Return secondary Family skills that are determined by structured component roles.

    Only clear/boss/triggered_payload roles enter automatically. A trigger host is a delivery
    mechanism, not identity: swapping hosts is a variant, so hosts only participate when a
    researcher explicitly declares them in typed_payload.familyCoreSkillKeys.
    """

    rows = [
        row
        for row in records
        if str(_value(row, "record_kind", "") or "") in FAMILY_IDENTITY_RECORD_KINDS
    ]
    values = {
        key
        for row in rows
        for key in _role_component_keys(row, SECONDARY_ROLES)
        if _is_skill_key(key)
    }
    return tuple(sorted(values))


def support_packages(record: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return normalized root-skill socket packages from the typed payload."""

    payload = _typed_payload(record)
    raw = payload.get("supportPackages")
    if not isinstance(raw, list):
        return ()
    packages: set[tuple[str, tuple[str, ...]]] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        skill_key = str(item.get("skillKey") or "").strip()
        support_keys = item.get("supportKeys")
        if not _is_skill_key(skill_key) or not isinstance(support_keys, list):
            continue
        normalized_supports = tuple(
            sorted(
                {
                    str(value).strip()
                    for value in support_keys
                    if isinstance(value, str) and str(value).strip().startswith("support:")
                }
            )
        )
        if normalized_supports:
            packages.add((skill_key, normalized_supports))
    return tuple(sorted(packages))


def support_ownership_packages(
    record: Any,
) -> tuple[tuple[str, tuple[str, ...], str, str], ...]:
    """Return stable support topology used by identity v2.

    Source-local group/root references are deliberately excluded. They prove physical socket
    placement for one accepted case but are not durable cross-case identity.
    """

    payload = _typed_payload(record)
    raw = payload.get("supportPackages")
    if not isinstance(raw, list):
        return ()
    packages: set[tuple[str, tuple[str, ...], str, str]] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        skill_key = str(item.get("skillKey") or "").strip()
        support_keys = item.get("supportKeys")
        if not _is_skill_key(skill_key) or not isinstance(support_keys, list):
            continue
        normalized_supports = tuple(
            sorted(
                {
                    str(value).strip()
                    for value in support_keys
                    if isinstance(value, str) and str(value).strip().startswith("support:")
                }
            )
        )
        if not normalized_supports:
            continue
        delivery_role = str(item.get("deliveryRole") or "direct").strip()
        host_skill_key = str(item.get("hostSkillKey") or "").strip()
        packages.add((skill_key, normalized_supports, delivery_role, host_skill_key))
    return tuple(sorted(packages))


def resource_mechanism_tags(record: Any) -> tuple[str, ...]:
    """Return stable semantic tags for resource mechanisms without physical graph nodes."""

    values = _typed_string_list(record, "resourceMechanisms", "resource_mechanisms")
    return tuple(sorted({value for value in values if _IDENTITY_TAG_RE.fullmatch(value)}))


def record_availability(record: Any) -> str:
    value = str(_typed_payload(record).get("availability") or "standard").strip()
    return value if value in {"standard", "source_specific_random"} else "standard"


def _ascendancy_candidates(record: Any) -> set[str]:
    values: set[str] = set()
    direct = str(_value(record, "ascendancy_key", "") or "").strip()
    if direct:
        values.add(direct)
    values.update(_role_component_keys(record, ("ascendancy_shell",)))
    return values


def _role_component_keys(record: Any, roles: tuple[str, ...]) -> list[str]:
    wanted = set(roles)
    return [
        str(mention.get("component_key") or "").strip()
        for mention in _mentions(record)
        if str(mention.get("role") or "") in wanted
        and str(mention.get("component_key") or "").strip()
    ]


def _mentions(record: Any) -> list[dict[str, Any]]:
    raw = _value(record, "component_mentions", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            raw = []
    values: list[dict[str, Any]] = []
    for item in raw or []:
        if isinstance(item, Mapping):
            values.append(dict(item))
        elif hasattr(item, "model_dump"):
            values.append(item.model_dump(mode="json"))
    return values


def _typed_string_list(record: Any, *keys: str) -> list[str]:
    payload = _typed_payload(record)
    if not isinstance(payload, Mapping):
        return []
    raw: Any = []
    for key in keys:
        if key in payload:
            raw = payload[key]
            break
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if isinstance(value, str) and value.strip()]


def _typed_payload(record: Any) -> Mapping[str, Any]:
    payload = _value(record, "typed_payload", {})
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            payload = {}
    if not isinstance(payload, Mapping):
        return {}
    return payload


def _list_value(record: Any, field: str) -> list[Any]:
    raw = _value(record, field, [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
    return list(raw) if isinstance(raw, list) else []


def _value(record: Any, field: str, default: Any) -> Any:
    if isinstance(record, Mapping):
        return record.get(field, default)
    try:
        return record[field]
    except (KeyError, IndexError, TypeError):
        return getattr(record, field, default)


def _is_stable_component_key(value: str) -> bool:
    return bool(value and ":" in value and not any(char.isspace() for char in value))


def _is_skill_key(value: str) -> bool:
    return value.startswith("skill:")


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_package_value(
    skill_key: str,
    support_keys: tuple[str, ...],
    *,
    delivery_role: str | None = "direct",
    host_skill_key: str | None = "",
) -> str:
    payload: dict[str, Any] = {
        "skill_key": skill_key,
        "support_keys": list(support_keys),
    }
    if delivery_role is not None:
        payload["delivery_role"] = delivery_role
    if host_skill_key is not None:
        payload["host_skill_key"] = host_skill_key
    return _stable_hash(payload)
