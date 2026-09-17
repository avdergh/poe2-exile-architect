from contextlib import nullcontext
from pathlib import Path
import subprocess

import pytest

from server.compute import item_search
from server.compute.engine import _find_luajit
from server.runtime.compute_control import ComputeControl, ComputeStopped, use_compute_control


class Engine:
    info = {'runtimeContract': 15}

    def __init__(self, control=None):
        self.control = control
        self.batches = []
        self.calcs = 1
        self.restore_calcs = True

    def transaction_lock(self):
        return nullcontext()

    def get_xml(self):
        return '<PathOfBuilding2><Build level="98"/></PathOfBuilding2>'

    def load_build_xml(self, _xml):
        if self.restore_calcs:
            self.calcs = 1

    def call(self, name, **_kwargs):
        assert name == 'item_replacement_selection'
        return {'main': {'groupIndex': 1}, 'calcs': {'groupIndex': self.calcs}}

    def eval_items(self, slot, items, keys, **kwargs):
        self.batches.append(list(items))
        if self.control:
            self.control.cancel()
        return {'ok': True, 'contextVersion': 'item_replacement_context_v1', 'rolledBack': True,
                'results': [{'Life': int(item)} for item in items]}


def test_controlled_item_batches_preserve_order_and_candidate_set():
    items = [str(i) for i in range(35)]
    synchronous = Engine()
    expected = item_search.evaluate_items(synchronous, 'Helmet', items, ['Life'])
    controlled = Engine()
    with use_compute_control(ComputeControl(60)):
        actual = item_search.evaluate_items(controlled, 'Helmet', items, ['Life'])
    assert actual == expected
    assert [len(batch) for batch in synchronous.batches] == [35]
    assert [len(batch) for batch in controlled.batches] == [16, 16, 3]
    assert sum(controlled.batches, []) == items


def test_cancel_is_observed_after_first_bounded_native_batch():
    control = ComputeControl(60)
    engine = Engine(control)
    with use_compute_control(control), pytest.raises(ComputeStopped, match='cancelled'):
        item_search.evaluate_items(engine, 'Helmet', [str(i) for i in range(35)], ['Life'])
    assert [len(batch) for batch in engine.batches] == [16]


@pytest.mark.parametrize('restore_calcs', [True, False])
def test_cancel_restores_exact_selection_even_when_xml_hash_never_changed(restore_calcs):
    engine = Engine()
    engine.restore_calcs = restore_calcs

    @item_search.read_only_search
    def interrupted(eng):
        eng.calcs = 2
        raise ComputeStopped('cancelled')

    if restore_calcs:
        with pytest.raises(ComputeStopped):
            interrupted(engine)
        assert engine.calcs == 1
    else:
        result = interrupted(engine)
        assert result['errorCode'] == 'item_search_restore_failed'
        assert result['recoveryRequired'] is True


def test_native_utf8_prefix_rejects_surrogates_and_non_scalar_sequences(tmp_path):
    bridge = (Path(__file__).parents[1] / 'pob/pob_headless.lua').read_text(encoding='utf-8')
    helper = bridge[bridge.index('local function utf8Prefix'):bridge.index('function methods.set_skill_group_state')]
    script = tmp_path / 'utf8-prefix.lua'
    script.write_text(helper + '''
assert(utf8Prefix("中文😀", 2) == "中文")
for _, bytes in ipairs({{237,160,128}, {224,128,128}, {240,128,128,128}, {244,144,128,128}}) do
    assert(not pcall(utf8Prefix, string.char(unpack(bytes)), 50))
end
''', encoding='utf-8')
    subprocess.run([_find_luajit(), str(script)], check=True, capture_output=True, timeout=10)
