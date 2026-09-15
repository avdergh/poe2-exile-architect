from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.knowledge import physical_graph as pg


def _snapshot(
    *,
    host=("Minion", "Persistent"),
    minion=("Spell", "Area", "Duration"),
    allowed=("Spell",),
    excluded=(),
    ignore=False,
    added=(),
    added_minion=(),
    second_support=False,
):
    source = pg.GraphSource("fixture:types", "test_fixture", "synthetic")
    pinned = pg.GraphSource("fixture:pinned", "pinned_pob_skill_payload_types", "synthetic.lua")
    refs = (source.source_id,)
    keys = {"skill:Root": "active_skill", "support:Test": "support_gem", "skill:Contract": "active_skill"}
    keys.update({f"skill_type:{name.lower()}": "skill_type" for name in host})
    edges = [pg.GraphEdge("grants_skill", "support:Test", "skill:Contract", refs)]
    edges += [pg.GraphEdge("has_type", "skill:Root", f"skill_type:{name.lower()}", refs) for name in host]
    facts = [pg.RequirementFact(
        "skill:Contract", "support_contract",
        {"allowed_types_expr": list(allowed), "excluded_types_expr": list(excluded),
         "added_types": list(added), "added_minion_types": list(added_minion)}, refs,
    )]
    if minion is not None:
        facts.append(pg.RequirementFact(
            "skill:Root", "minion_payload_types", {"skill_types": list(minion)}, (pinned.source_id,),
        ))
    if ignore is not None:
        facts.append(pg.RequirementFact(
            "skill:Contract", "pob_support_flags", {"ignore_minion_types": ignore}, (pinned.source_id,),
        ))
    if second_support:
        keys.update({"support:Need": "support_gem", "skill:NeedContract": "active_skill"})
        edges.append(pg.GraphEdge("grants_skill", "support:Need", "skill:NeedContract", refs))
        facts.extend([
            pg.RequirementFact("skill:NeedContract", "support_contract", {"allowed_types_expr": ["Spell"]}, refs),
            pg.RequirementFact("skill:NeedContract", "pob_support_flags", {"ignore_minion_types": True}, (pinned.source_id,)),
        ])
    return pg.GraphSnapshot(
        snapshot_id="snapshot:types", created_at=datetime(2026, 9, 14, tzinfo=UTC),
        sources=(source, pinned),
        nodes=tuple(pg.GraphNode(key, kind, key, refs) for key, kind in keys.items()),
        edges=tuple(edges), aliases=(), requirement_facts=tuple(facts),
    )


@pytest.mark.parametrize("endpoint_kind", ["active_skill", "minion_payload"])
@pytest.mark.parametrize(("allowed", "excluded", "ignore", "expected"), [
    (("Spell",), (), False, "known"),
    (("Minion", "Spell", "AND"), (), False, "known"),
    (("Spell",), ("Persistent",), False, "unsupported"),
    (("Spell",), ("Area",), False, "known"),
    (("Spell",), (), True, "unsupported"),
    (("Spell", "NOT"), (), True, "known"),
    (("Spell", "NOT"), (), False, "unsupported"),
])
def test_native_host_minion_type_predicate(allowed, excluded, ignore, expected, endpoint_kind):
    snapshot = _snapshot(allowed=allowed, excluded=excluded, ignore=ignore)
    result = pg.support_skill_group_candidates(
        snapshot=snapshot, support_keys=["support:Test"], skill_key="skill:Root",
        endpoint_kind=endpoint_kind,
    )[0]
    assert result.status == expected
    assert result.facts["host_skill_types"] == ["minion", "persistent"]
    assert result.facts["minion_skill_types"] == ["area", "duration", "spell"]
    assert "fixture:pinned" in result.source_refs
    assert result.facts["contract_version"] == pg.SUPPORT_COMPATIBILITY_VERSION
    assert result.facts["evaluation_scope"] == "static_type_compatibility"
    assert result.facts["application_verified"] is False
    assert "spell" not in pg._skill_types_for(snapshot, "skill:Root")


def test_complete_type_diagnostics_are_not_the_matched_requirement_subset():
    result = pg.support_skill_candidate(snapshot=_snapshot(), support_key="support:Test", skill_key="skill:Root")
    assert result.facts["matched_skill_types"] == ["spell"]
    assert result.facts["effective_required_skill_types"] == ["area", "duration", "minion", "persistent", "spell"]


@pytest.mark.parametrize(("kwargs", "status", "reason"), [
    ({"ignore": None}, "unknown", "minion_support_flags_unavailable"),
    ({"minion": None}, "unknown", "minion_skill_types_unavailable"),
    ({"ignore": None, "excluded": ("Persistent",)}, "unsupported", "excluded_types_matched"),
    ({"minion": None, "ignore": True}, "unsupported", "required_types_not_matched"),
    ({"minion": None, "ignore": None, "allowed": ("Minion",)}, "known", None),
    ({"minion": None, "ignore": None, "allowed": ("Spell", "NOT")}, "unknown", "minion_skill_types_unavailable"),
    ({"host": ("Attack",), "minion": None, "ignore": None, "allowed": ("Attack",)}, "known", None),
    ({"host": (), "allowed": ("Spell",)}, "unknown", "host_skill_types_unavailable"),
])
def test_missing_context_is_unknown_only_when_needed(kwargs, status, reason):
    result = pg.support_skill_candidate(snapshot=_snapshot(**kwargs), support_key="support:Test", skill_key="skill:Root")
    assert result.status == status
    assert result.facts.get("excluded_reason") == reason


@pytest.mark.parametrize("order", [("support:Need", "support:Test"), ("support:Test", "support:Need")])
def test_fixed_point_adds_only_host_types_and_preserves_order_independence(order):
    snapshot = _snapshot(allowed=(), minion=("Area",), added=("Spell",), second_support=True)
    results = pg.support_skill_group_candidates(snapshot=snapshot, support_keys=order, skill_key="skill:Root")
    assert all(result.status == "known" for result in results)
    assert all(result.facts["host_skill_types"] == ["minion", "persistent", "spell"] for result in results)
    assert all(result.facts["minion_skill_types"] == ["area"] for result in results)


def test_added_minion_types_do_not_invent_native_fixed_point_behavior():
    snapshot = _snapshot(allowed=(), minion=("Area",), added_minion=("Spell",), second_support=True)
    results = pg.support_skill_group_candidates(snapshot=snapshot, support_keys=["support:Need", "support:Test"], skill_key="skill:Root")
    assert results[0].status == "unsupported"
    assert results[0].facts["host_skill_types"] == ["minion", "persistent"]
    assert results[0].facts["minion_skill_types"] == ["area"]


def test_rejected_support_cannot_authorize_itself_with_added_types():
    result = pg.support_skill_group_candidates(
        snapshot=_snapshot(allowed=("Attack",), added=("Attack",)),
        support_keys=["support:Test"], skill_key="skill:Root",
    )[0]
    assert result.status == "unsupported"
    assert "attack" not in result.facts["host_skill_types"]


def test_pinned_support_flags_bind_exact_effect_and_only_observed_defaults(tmp_path: Path):
    source = pg.GraphSource("fixture:pinned", "pinned_pob_skill_payload_types", "fixture.lua")
    path = tmp_path / "fixture.lua"
    path.write_text('''skills["Ignore"] = {
    name = "Same display name",
    support = true,
    ignoreMinionTypes = true,
}
skills["Default"] = {
    name = "Same display name",
    support = true,
}
skills["Expression"] = {
    support = true,
    ignoreMinionTypes = someFlag,
}
skills["NotSupport"] = {
    ignoreMinionTypes = true,
}
''', encoding="utf-8")
    result = pg.ingest_pob_support_flags(
        [path], source=source,
        known_skill_keys={"skill:Ignore", "skill:Default", "skill:Expression", "skill:NotSupport", "skill:Missing"},
    )
    assert {fact.component_key: fact.requirements for fact in result.requirement_facts} == {
        "skill:Ignore": {"ignore_minion_types": True},
        "skill:Default": {"ignore_minion_types": False},
    }
    assert all(fact.source_refs == (source.source_id,) for fact in result.requirement_facts)


@pytest.mark.parametrize("assignments", [
    ("", "ignoreMinionTypes = someFlag,"),
    ("ignoreMinionTypes = someFlag,", "ignoreMinionTypes = false,"),
    ("ignoreMinionTypes = true,", "ignoreMinionTypes = false,"),
    ("ignoreMinionTypes = false,", "ignoreMinionTypes = true,"),
    ("", "ignoreMinionTypes = someFlag,", "ignoreMinionTypes = true,"),
])
@pytest.mark.parametrize("separate_files", [False, True])
def test_conflicting_pinned_support_effects_never_produce_known_flags(
    tmp_path: Path, assignments, separate_files,
):
    source = pg.GraphSource("fixture:pinned", "pinned_pob_skill_payload_types", "fixture.lua")
    blocks = [f'''skills["Duplicate"] = {{
    support = true,
    {assignment}
}}
''' for assignment in assignments]
    paths = []
    for index, text in enumerate(blocks if separate_files else ["".join(blocks)]):
        path = tmp_path / f"fixture-{index}.lua"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    # An unrelated, uniquely declared effect must remain available.
    unrelated = tmp_path / "unique.lua"
    unrelated.write_text('''skills["Unique"] = {
    support = true,
    ignoreMinionTypes = true,
}
''', encoding="utf-8")
    result = pg.ingest_pob_support_flags(
        [unrelated, *reversed(paths)], source=source,
        known_skill_keys={"skill:Duplicate", "skill:Unique"},
    )
    assert {fact.component_key: fact.requirements for fact in result.requirement_facts} == {
        "skill:Unique": {"ignore_minion_types": True},
    }


@pytest.mark.parametrize(("assignments", "expected"), [
    (("ignoreMinionTypes = true,", "ignoreMinionTypes = true,"), True),
    (("ignoreMinionTypes = false,", "ignoreMinionTypes = false,"), False),
    (("", "ignoreMinionTypes = false,"), False),
    (("ignoreMinionTypes = false,", ""), False),
    (("", ""), False),
])
@pytest.mark.parametrize("separate_files", [False, True])
def test_consistent_pinned_support_flags_allow_duplicate_effect_declarations(
    tmp_path: Path, assignments, expected, separate_files,
):
    source = pg.GraphSource("fixture:pinned", "pinned_pob_skill_payload_types", "fixture.lua")
    blocks = [f'''skills["Duplicate"] = {{
    name = "Description variant {index}",
    support = true,
    {assignment}
}}
''' for index, assignment in enumerate(assignments)]
    paths = []
    for index, text in enumerate(blocks if separate_files else ["".join(blocks)]):
        path = tmp_path / f"fixture-{index}.lua"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    result = pg.ingest_pob_support_flags(
        list(reversed(paths)), source=source, known_skill_keys={"skill:Duplicate"},
    )
    assert len(result.requirement_facts) == 1
    assert result.requirement_facts[0].requirements == {"ignore_minion_types": expected}


@pytest.mark.parametrize("non_support_first", [False, True])
@pytest.mark.parametrize("separate_files", [False, True])
def test_non_support_declaration_invalidates_duplicate_support_flag(
    tmp_path: Path, non_support_first, separate_files,
):
    source = pg.GraphSource("fixture:pinned", "pinned_pob_skill_payload_types", "fixture.lua")
    valid = '''skills["Duplicate"] = {
    support = true,
    ignoreMinionTypes = false,
}
'''
    invalid = valid.replace("support = true,", "support = false,")
    blocks = [invalid, valid] if non_support_first else [valid, invalid]
    blocks.append(valid)
    paths = []
    for index, text in enumerate(blocks if separate_files else ["".join(blocks)]):
        path = tmp_path / f"fixture-{index}.lua"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    result = pg.ingest_pob_support_flags(
        list(reversed(paths)), source=source, known_skill_keys={"skill:Duplicate"},
    )
    assert result.requirement_facts == ()
