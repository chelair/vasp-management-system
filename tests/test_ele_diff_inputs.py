"""Static fragment inputs; temporary data and mocked remote file uploads only."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-ele-diff-inputs-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name) / 'ai.key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import ele_diff
from input_state import parse_incar_text


class EleDiffInputsTests(unittest.TestCase):
    def test_static_parameters_replace_inherited_or_missing_nsw(self):
        for raw in ('NSW = 500\n', '', 'nsw = 100\nNSW = 200\n'):
            with self.subTest(raw=raw):
                updated, fixes, _ = ele_diff.check_incar(raw + 'IBRION=2\nEFIELD=0.05\nENCUT=520\n')
                params = parse_incar_text(updated)
                self.assertEqual(params['NSW'], '0')
                self.assertEqual(params['IBRION'], '-1')
                self.assertEqual(params['EFIELD'], '0.05')
                self.assertEqual(params['ENCUT'], '520')
                self.assertIn('NSW', fixes)

    def test_creation_writes_static_inputs_locally_and_uploads_same_content(self):
        project = {'name': 'P'}
        task = {'task_id': 'ele', 'model_name': 'Main', 'task_type': 'ele'}
        root = Path(_DATA.name) / 'fragments'
        raw = 'NSW=500\nIBRION=2\nLCHARG=.FALSE.\nISTART=1\nICHARG=11\nENCUT=520\n'
        plan = [{'index': i, 'label': f'分块{i}', 'atoms': [i], 'poscar': 'fixture\n'} for i in (1, 2)]
        uploads = {}
        with patch.object(ele_diff, 'read_main_incar', return_value=raw), \
             patch('paths.local_root', return_value=Path(_DATA.name)), \
             patch.object(ele_diff, 'task_remote_dir', return_value='/remote/ele'), \
             patch.object(ele_diff, 'diff_charge_root_local', return_value=root), \
             patch.object(ele_diff, 'run_pos2pot', return_value={}), \
             patch.object(ele_diff.ssh, 'run_remote', return_value={'stdout': 'POTCAR_OK 1 99\nPOTCAR_OK 2 99', 'exit_code': 0}), \
             patch.object(ele_diff.ssh, 'upload_file', side_effect=lambda server, source, target: uploads.update({target: Path(source).read_text()})):
            result = ele_diff.create_block_files('mock', project, task, plan)
        self.assertEqual(result['incar_fixes']['NSW'], '500→0')
        for i in (1, 2):
            text = (root / str(i) / 'INCAR').read_text()
            self.assertEqual(text, uploads[f'/remote/ele/{i}/INCAR'])
            params = parse_incar_text(text)
            self.assertEqual({k: params[k] for k in ('NSW', 'IBRION', 'ISTART', 'ICHARG')},
                             {'NSW': '0', 'IBRION': '-1', 'ISTART': '0', 'ICHARG': '2'})


if __name__ == '__main__':
    unittest.main()
