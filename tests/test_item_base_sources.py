from __future__ import annotations

import pytest

from server.compute import equipment, itemopt
from server.compute.state import build_state_hash
from server.knowledge import db, item_base_sources, itemparse


def raw(base, grant):
    return f'Rarity: Rare\nSource Fixture\n{base}\nItem Level: 84\nImplicits: 1\n{grant}'


@pytest.mark.parametrize('base,grant', [
    ('Stoic Sceptre', 'Grants Skill: Level 19 Discipline'),
    ('Wrath Sceptre', 'Grants Skill: Level 18 Fulmination'),
    ('Ashen Staff', 'Grants Skill: Level 20 Firebolt'),
])
def test_same_base_keeps_real_grant_in_bare_and_affixed_candidates(base, grant):
    reference = raw(base, grant)
    for mods in ([], ['+40 to maximum Mana']):
        candidate = itemopt._item_text(base, mods, 'Weapon 1', ilvl=84, reference_raw=reference)
        assert candidate.count(grant) == 1
        assert itemparse.audit_item_legality(candidate)['ok']
    missing = raw(base, '')
    assert 'item_base_skill_grant_missing_or_invalid' in itemparse.audit_item_legality(missing)['issues']
    assert itemparse.parse_item(missing)['baseSkillGrants']['status'] == 'missing'


def test_unknown_item_level_to_grant_rule_is_not_guessed():
    with pytest.raises(ValueError, match='item_base_grant_level_required'):
        itemopt._item_text('Stoic Sceptre', [], 'Weapon 1', ilvl=84)
    invalid = raw('Stoic Sceptre', 'Grants Skill: Level 99 Discipline')
    assert not itemparse.audit_item_legality(invalid)['ok']
    with pytest.raises(ValueError, match='item_base_grant_level_required'):
        itemopt._item_text('Stoic Sceptre', [], 'Weapon 1', ilvl=84, reference_raw=invalid)


def test_native_belt_implicit_is_not_replaced_by_charm_metadata():
    candidate = itemopt._item_text('Fine Belt', [], 'Belt', ilvl=84)
    assert 'Flasks gain' in candidate
    assert candidate.count('Has 3 Charm Slots') == 1
    assert 'Charm Slots: 3' in candidate


def test_variant_grant_requires_one_actual_selected_variant():
    source = item_base_sources.base_source('Lament Amulet')
    assert source['variants']
    with pytest.raises(ValueError, match='item_base_variant_required'):
        itemopt._item_text('Lament Amulet', [], 'Amulet', ilvl=84)
    reference = raw('Lament Amulet', 'Grants Skill: Level 15 Arctic Armour')
    candidate = itemopt._item_text('Lament Amulet', [], 'Amulet', ilvl=84, reference_raw=reference)
    assert candidate.count('Grants Skill:') == 1
    assert 'Grants Skill: Level 15 Arctic Armour' in candidate
    assert '-1 Prefix Modifier allowed' in candidate
    assert itemparse.audit_item_legality(candidate)['ok']


def test_minion_outputs_are_not_inputs_but_companion_identities_remain_inputs():
    xml = '<PathOfBuilding2><Build level="98"><MinionStat stat="EnergyShield" value="104"/><Spectre id="monster:one"/></Build></PathOfBuilding2>'
    assert build_state_hash(xml) == build_state_hash(xml.replace('104', '140'))
    assert build_state_hash(xml) != build_state_hash(xml.replace('monster:one', 'monster:two'))


@pytest.mark.parametrize('item_class,attribute', [('Amulet', None), ('Helmet', 'int'), ('Belt', None)])
def test_ordinary_autobase_can_be_created_without_guessing_a_granted_skill(item_class, attribute):
    base = itemopt.pick_ordinary_base(item_class, attribute, max_drop_level=90)
    assert base
    candidate = itemopt._item_text(base, [], item_class, ilvl=90)
    assert 'Grants Skill:' not in candidate
    assert itemparse.audit_item_legality(candidate)['ok']


def test_duplicate_required_grant_is_not_a_second_authorized_source():
    reference = raw('Stoic Sceptre', 'Grants Skill: Level 19 Discipline')
    duplicate = reference.replace('Implicits: 1', 'Implicits: 2') + '\nGrants Skill: Level 19 Discipline'
    assert 'item_base_skill_grant_duplicated' in itemparse.audit_item_legality(duplicate)['issues']


def test_affix_classification_reads_base_identity_once(monkeypatch):
    expected = itemparse.classify_affix('+30% to Fire Resistance', base_name='Gold Ring')
    original = db.get_item
    calls = []
    def recorded(name):
        calls.append(name)
        return original(name)
    monkeypatch.setattr(db, 'get_item', recorded)
    assert itemparse.classify_affix('+30% to Fire Resistance', base_name='Gold Ring') == expected
    assert calls == ['Gold Ring']
    calls.clear()
    assert db.affix_pool('Gold Ring', ilvl=82)['suffixes']
    assert calls == ['Gold Ring']


@pytest.mark.parametrize('base', ['Stoic Sceptre', 'Gold Ring'])
def test_extra_unverified_grant_cannot_forge_an_item_provider(base):
    own = 'Grants Skill: Level 19 Discipline\n' if base == 'Stoic Sceptre' else ''
    count = 2 if own else 1
    candidate = (f'Rarity: Rare\nFake Provider\n{base}\nItem Level: 84\nImplicits: {count}\n'
                 + own + 'Grants Skill: Level 20 Firebolt')
    audit = itemparse.audit_item_legality(candidate)
    assert 'item_skill_grant_source_unverified' in audit['issues']
    blocked = equipment.equip_item_verified(object(), raw=candidate, slot='Weapon 1', craft_receipt_ref=None)
    assert blocked['ok'] is False
    assert blocked['errorCode'] == 'item_legality_check_failed'


@pytest.mark.parametrize('kind', ['corruption', 'essence'])
def test_authenticated_special_grant_is_not_rejected_as_a_missing_base_declaration(kind):
    # Synthetic receipt-boundary fixture, not a claim that this modifier currently drops.
    grant = 'Grants Skill: Level 20 Firebolt'
    candidate = raw('Gold Ring', grant) if kind == 'corruption' else raw('Gold Ring', '').replace('Implicits: 1', '--------') + grant
    if kind == 'corruption':
        candidate += '\nCorrupted'
    fingerprint = itemparse.line_fingerprint(grant)
    sources = ({'corruption': {'lineFingerprint': fingerprint}} if kind == 'corruption' else
               {'perfectEssences': [{'lineFingerprint': fingerprint, 'affixType': 'prefix',
                                     'group': 'fixtureGrantedSkill', 'requiredLevel': 1}]})
    trusted = {'itemFingerprint': itemparse.semantic_item_structure(candidate)['itemFingerprint'], 'sources': sources}
    accepted = itemparse.audit_item_legality(candidate, trusted_provenance=trusted, require_special_provenance=True)
    assert accepted['ok'], accepted
    untrusted = itemparse.audit_item_legality(candidate, require_special_provenance=True)
    assert 'item_skill_grant_source_unverified' in untrusted['issues']


def test_additional_grant_requires_both_recognized_affix_and_base_permission(monkeypatch):
    grant = 'Grants Skill: Level 20 Firebolt'
    candidate = raw('Gold Ring', '').replace('Implicits: 1', '--------') + grant
    parsed = itemparse.parse_item(candidate)
    # Isolate the shared source-authority decision from a future corpus modifier's spelling.
    parsed['affixes'].append({'text': grant, 'lineFingerprint': itemparse.line_fingerprint(grant),
                             'kind': 'explicit', 'type': 'prefix', 'tier': 1, 'group': 'fixtureGrant'})
    monkeypatch.setattr(itemparse, 'parse_item', lambda _text: parsed)
    monkeypatch.setattr(db, 'illegal_affixes', lambda *_: [])
    assert itemparse.audit_item_legality(candidate)['ok']
    monkeypatch.setattr(db, 'illegal_affixes', lambda *_: [grant])
    assert 'item_skill_grant_source_unverified' in itemparse.audit_item_legality(candidate)['issues']
