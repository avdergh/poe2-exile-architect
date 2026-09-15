from pathlib import Path

import pytest

from server.knowledge import physical_graph as pg


SOURCE = pg.GraphSource("fixture:pinned", "pinned_pob_skill_payload_types", "fixture.lua")


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "skills.lua"
    path.write_text(text, encoding="utf-8", newline="")
    return path


def _support_block(skill_id: str, assignment: str = "", close: str = "}\n") -> str:
    return f'skills["{skill_id}"] = {{\n\tsupport = true,\n\t{assignment}\n{close}'


@pytest.mark.parametrize("close", ["}\n", "}\t\t\tend", "} end  \r\n"])
def test_pinned_generated_skill_close_preserves_exact_effect_facts(tmp_path: Path, close: str):
    text = _support_block("OrdinarySupport", "ignoreMinionTypes = true,")
    text += _support_block("LastSupport", close=close)
    support_path = _write(tmp_path, text)
    result = pg.ingest_pob_support_flags(
        [support_path], source=SOURCE,
        known_skill_keys={"skill:OrdinarySupport", "skill:LastSupport"},
    )
    assert {fact.component_key: fact.requirements for fact in result.requirement_facts} == {
        "skill:OrdinarySupport": {"ignore_minion_types": True},
        "skill:LastSupport": {"ignore_minion_types": False},
    }
    assert all(fact.source_refs == (SOURCE.source_id,) for fact in result.requirement_facts)

    minion_path = _write(tmp_path, 'skills["LastMinion"] = {\n'
        '\tminionSkillTypes = { [SkillType.Attack] = true, [SkillType.Area] = true, },\n'
        '\tlevels = {\n\t\t[1] = { levelRequirement = 1, },\n\t},\n' + close)
    result = pg.ingest_pob_minion_payload_types(
        [minion_path], source=SOURCE, known_skill_keys={"skill:LastMinion"},
    )
    assert len(result.requirement_facts) == 1
    assert result.requirement_facts[0].component_key == "skill:LastMinion"
    assert result.requirement_facts[0].requirements == {
        "endpoint_kind": "minion_payload", "skill_types": ["Area", "Attack"],
    }


@pytest.mark.parametrize("close", ["", "} ending\n", "} end();\n", "} -- unknown suffix\n"])
def test_malformed_block_cannot_borrow_the_next_effect_close(tmp_path: Path, close: str):
    path = _write(tmp_path, _support_block("Malformed", close=close)
        + _support_block("Independent", "ignoreMinionTypes = true,", "}\tend\n"))
    result = pg.ingest_pob_support_flags(
        [path], source=SOURCE, known_skill_keys={"skill:Malformed", "skill:Independent"},
    )
    assert {fact.component_key: fact.requirements for fact in result.requirement_facts} == {
        "skill:Independent": {"ignore_minion_types": True},
    }

    path = _write(tmp_path, 'skills["Malformed"] = {\n'
        '\tminionSkillTypes = { [SkillType.Attack] = true, },\n' + close
        + 'skills["Independent"] = {\n'
        '\tminionSkillTypes = { [SkillType.Spell] = true, },\n}\tend\n')
    result = pg.ingest_pob_minion_payload_types(
        [path], source=SOURCE, known_skill_keys={"skill:Malformed", "skill:Independent"},
    )
    assert {fact.component_key: fact.requirements["skill_types"]
            for fact in result.requirement_facts} == {"skill:Independent": ["Spell"]}


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(("assignment", "close", "expected"), [
    ("ignoreMinionTypes = false,", "}\tend\n", False),
    ("ignoreMinionTypes = true,", "}\tend\n", None),
    ("ignoreMinionTypes = dynamicFlag,", "}\tend\n", None),
    ("ignoreMinionTypes = false,", "} end_unknown\n", None),
    ("ignoreMinionTypes = false,", "", None),
])
def test_tail_duplicate_retains_consistent_or_unknown_semantics(
    tmp_path: Path, reverse: bool, assignment: str, close: str, expected: bool | None,
):
    blocks = [_support_block("Duplicate"), _support_block("Duplicate", assignment, close)]
    if reverse:
        blocks.reverse()
    result = pg.ingest_pob_support_flags(
        [_write(tmp_path, "".join(blocks))], source=SOURCE,
        known_skill_keys={"skill:Duplicate"},
    )
    if expected is None:
        assert result.requirement_facts == ()
    else:
        assert len(result.requirement_facts) == 1
        assert result.requirement_facts[0].requirements == {"ignore_minion_types": expected}


def test_support_compatibility_receipts_use_revised_contract():
    assert pg.SUPPORT_COMPATIBILITY_VERSION == "pob_support_type_compatibility_v3"
