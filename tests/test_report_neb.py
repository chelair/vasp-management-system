"""Frozen NEB structures across R2, full report export and reaction reports. No SSH."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_reaction_review as reaction_fixture
import report_blocks
import report_compositions
import report_export
import report_interactive
import topic_simple
from cif_convert import structure_report_dir

CIF = '''data_neb
_cell_length_a 10
_cell_length_b 10
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
C1 C 0.4 0.4 0.4
O1 O 0.52 0.4 0.4
'''


class ReportNebTests(unittest.TestCase):
    def setUp(self):
        self.fixture = reaction_fixture.ReactionReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.project = self.fixture.project
        self.task = self.project['tasks'][-1]
        self.folder = structure_report_dir(self.project, self.task) / 'images'
        self.folder.mkdir(parents=True, exist_ok=True)
        for path in self.folder.glob('*.cif'):
            path.unlink()
        (self.folder / '00.cif').write_text(CIF)
        (self.folder / '02.cif').write_text(CIF.replace('0.52', '0.56'))
        self.observations = {'path': {'task_id': 'path', 'status': 'unconverged',
            'checked_at': '2026-10-29T12:00:00+08:00', 'neb_barrier': {'images': [
                {'label': str(i), 'relative': r, 'energy': -10+r, 'max_force': 0.04}
                for i, r in enumerate([0, 1, 0.5])]}}}

    def composition(self):
        return report_compositions.save(self.project, {'title': 'NEB 结构',
            'blocks': [{'type': 'group.neb', 'group_id': 'g'}]}, merged=self.observations)

    def test_freeze_normalized_labels_missing_structure_and_html_export(self):
        doc = self.composition()
        evidence = next(iter(doc['evidence'].values()))
        images = evidence['payload']['items'][0]['images']
        self.assertEqual(images[0]['cif'], CIF)
        self.assertIsNone(images[1]['cif'])
        self.assertIn('0.56', images[2]['cif'])
        before = copy.deepcopy(doc['evidence'])
        (self.folder / '00.cif').write_text('changed after report was saved')
        with patch.object(report_interactive, 'runtime_js', return_value='/* runtime */'):
            html = report_compositions.render_html(doc)
            self.assertIn('data-report-widget="neb-3d"', html)
            self.assertIn('data_neb', html)
            self.assertNotIn('changed after report', html)
            self.assertIn('$3Dmol', html)
        self.assertEqual(doc['evidence'], before)
        newer = report_blocks.resolve_evidence(self.project, 'group.neb', group_id='g', merged=self.observations)
        self.assertNotEqual(newer['version'], evidence['version'])
        hidden = copy.deepcopy(doc)
        hidden['hidden_block_ids'] = [doc['blocks'][0]['block_id']]
        self.assertNotIn('data-report-widget="neb-3d"', report_compositions.render_html(hidden))

    def test_full_report_payload_and_no_structure_fallback(self):
        doc = self.composition()
        item = next(iter(doc['evidence'].values()))['payload']['items'][0]
        full = {'science': {'neb': [item]}}
        self.assertEqual(report_interactive.interactive_payload(full)['neb']['path'], [item])
        with patch.object(report_interactive, 'runtime_js', return_value='runtime'):
            self.assertTrue(report_interactive.interactive_kwargs(full, interactive=True)['mol_js'])
        self.assertIn('neb-3d', report_export.widget_renderer_for(full)('neb-3d', 'path'))
        for image in item['images']:
            image['cif'] = None
        body = report_compositions._block_body(doc['blocks'][0], {'payload': {'items': [item], 'charts': ['<svg/>']}})
        self.assertIn('<svg/>', body)
        self.assertNotIn('neb-3d', body)

    def test_reaction_report_answers_reuse_frozen_neb(self):
        with patch('reaction_review.merged_results', return_value=self.observations):
            doc = topic_simple.create(self.fixture.user, self.fixture.conversation, '诊断B-F断键路径',
                {'property_id': 'neb.barrier', 'model_queries': ['PATH'], 'objective': '研究B-F断键'})
        block = next(b for b in doc['blocks'] if b['renderer'] == 'neb_panel')
        frozen = copy.deepcopy(doc['data']['library']['evidence'][block['source_refs'][0]['evidence_id']])
        (self.folder / '00.cif').write_text('new live structure')
        with patch('report_neb.read_neb_image_cifs', side_effect=AssertionError('answers must not read live structures')):
            updated = topic_simple.answer(self.fixture.user, doc['topic_id'], {'expected_revision': doc['revision'],
                'answers': {'scope': 'isolate_bond', 'bond.path': 'A'}})
        self.assertEqual(updated['data']['library']['evidence'][block['source_refs'][0]['evidence_id']], frozen)
        html = topic_simple.render_html(updated)
        self.assertIn('neb-3d', html)
        if prefix := os.environ.get('NEB_PREVIEW_PREFIX'):
            runtime = Path(os.environ['NEB_RUNTIME'])
            with patch.object(report_interactive, 'RUNTIME_PATH', runtime):
                Path(prefix + '-reaction.html').write_text(topic_simple.render_html(updated))
                (self.folder / '00.cif').write_text(CIF)
                r2 = self.composition()
                Path(prefix + '-composition.html').write_text(report_compositions.render_html(r2))
            Path(prefix + '.json').write_text(json.dumps(frozen['payload']['items'][0]))


if __name__ == '__main__':
    unittest.main()
