"""Small native regressions; no combinatorial optimizer is run by this file."""
from __future__ import annotations

import pytest

from server.compute import item_search, skillgroups, socket_probe
from server.compute.state import build_state_hash

RAW = ('Rarity: Rare\nSource Probe\nStoic Sceptre\nItem Level: 84\nQuality: 20\n'
       'Implicits: 1\nGrants Skill: Level 19 Discipline\n60% increased Spirit\n'
       '+4 to Level of all Minion Skills')
RUNE = RAW.replace('Implicits: 1', 'Sockets: S\nRune: Perfect Resolve Rune\nImplicits: 2').replace(
    'Grants Skill: Level 19 Discipline', 'Grants Skill: Level 19 Discipline\n{rune}+15 to Intelligence')


@pytest.mark.parametrize('main_kind', ['tree', 'item'])
@pytest.mark.parametrize('clarity', [False, True])
@pytest.mark.parametrize('extra_int', [40, 500])
def test_item_rune_projection_retains_sources_across_attribute_threshold(engine, main_kind, clarity, extra_int):
    engine.new_build()
    engine.set_class('Sorceress', 'Disciple of Varashta')
    engine.set_level(98)
    engine.set_config(custom_mods=f'+500 to Strength\n+500 to Dexterity\n+{extra_int} to Intelligence')
    assert engine.alloc_passive(32705)['ok']
    assert engine.alloc_passive(13289)['ok']
    engine.add_skill_group('Spark 1/0 1')
    assert engine.add_item(RAW, slot='Weapon 1')['ok']
    listed = skillgroups.list_skill_groups(engine)
    item = next(g for g in listed['groups'] if g.get('rootSkillId') == 'DisciplinePlayer')
    configured = skillgroups.configure_source_skill_supports(
        engine, source_group_index=item['index'], supports=['Clarity II'] if clarity else [],
        expected_fingerprint=item['fingerprint'], expected_state_hash=listed['stateHash'])
    assert configured['ok'], configured
    group = next(g for g in skillgroups.list_skill_groups(engine)['groups'] if g.get('sourceKind') == main_kind)
    engine.call('set_main_socket_group', index=group['index'], activeIndex=1)
    snapshot, selection = engine.get_xml(), item_search.capture_selection(engine)
    context = item_search.capture_context(engine)
    for candidate in (RAW, RUNE):
        try:
            socket_probe.load_candidate(engine, snapshot, 'Weapon 1', candidate)
            item_search.verify_context(engine, context, slot='Weapon 1')
            current = engine.call('list_skill_groups')
            actual = next(g for g in current['groups'] if g.get('rootSkillId') == 'DisciplinePlayer')
            assert [g['name'] for g in actual['gems'] if g['isSupport']] == (['Clarity II'] if clarity else [])
            assert current['mainGroupIndex'] == group['index']
            assert current['calcsGroupIndex'] == group['index']
        finally:
            engine.load_build_xml(snapshot)
        assert build_state_hash(engine.get_xml()) == build_state_hash(snapshot)
        assert item_search.selection_matches(engine, selection)


def test_precise_noop_and_unicode_label_roundtrip(engine):
    engine.new_build()
    engine.set_class('Warrior')
    engine.paste_skill('Rolling Slam 1/0 1')
    context = item_search.capture_context(engine)
    calls = []
    original = engine.call
    def tracked(method, **kwargs):
        calls.append(method)
        return original(method, **kwargs)
    engine.call = tracked
    try:
        item_search.verify_context(engine, context, slot='Helmet')
    finally:
        engine.call = original
    assert 'set_skill_group_state' not in calls
    label = ('水系召唤😀ABC' * 10)
    result = engine.call('set_skill_group_state', index=1, label=label)
    assert result['state']['groups'][0]['label'] == label[:50]
    engine.load_build_xml(engine.get_xml())
    assert engine.call('list_skill_groups')['groups'][0]['label'] == label[:50]


def test_semantic_diff_names_fields_without_leaking_item_bodies():
    old = '<PathOfBuilding2><Skills><SkillSet><Skill><Gem level="10"/></Skill></SkillSet></Skills></PathOfBuilding2>'
    diff = socket_probe.semantic_input_diff(old, old.replace('10', '12'))
    assert diff == [{'path': '/PathOfBuilding2/Skills[1]/SkillSet[1]/Skill[1]/Gem[1]/@level', 'expected': '10', 'observed': '12'}]
