"""Read-only seven-file checks against isolated local/remote trees."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import file_sync_status as status


class FileStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vasp-file-status-')
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name) / 'local'; self.local.mkdir()
        self.remote = Path(self.temp.name) / 'remote'; self.remote.mkdir()
        self.project = {'name': 'test', 'server': 'mock'}
        self.task = {'task_id': 'test', 'task_type': 'opt', 'remote_dir': '/task'}
        self.calls = 0

    def query(self, verify=True, fail=False):
        def run(server, command, timeout):
            self.calls += 1
            if fail: return {'exit_code': 1, 'stderr': 'network unavailable'}
            result = subprocess.run(['bash'], input=command, capture_output=True, text=True)
            return {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        with patch.object(status, 'task_files_dir', return_value=self.local), \
             patch.object(status, 'resolve_remote_path', return_value=str(self.remote)), \
             patch.object(status.ssh, 'run_remote', side_effect=run):
            return status.file_status(self.project, self.task, verify)

    def test_local_only_never_connects_and_seven_fixed_files(self):
        (self.local / 'INCAR').write_text('NSW=100')
        data = self.query(False)
        self.assertEqual(self.calls, 0)
        self.assertEqual([p['name'] for p in data['files']], list(status.NAMES))
        self.assertEqual(data['files'][0]['status'], 'local')

    def test_single_remote_call_and_all_synchronization_directions(self):
        for name in ('INCAR', 'KPOINTS'):
            (self.local / name).write_text('same'); (self.remote / name).write_text('same')
        (self.local / 'KPOINTS').write_text('different')
        (self.local / 'POSCAR').write_text('input')
        (self.remote / 'CONTCAR').write_text('result')
        (self.local / 'OUTCAR').write_text('old result')
        (self.remote / 'OSZICAR').write_text('')
        data = self.query()
        self.assertEqual(self.calls, 1)
        self.assertTrue(data['remote_checked'])
        self.assertEqual([p['status'] for p in data['files']],
                         ['synced', 'different', 'upload', 'missing', 'download', 'local_only', 'empty'])

    def test_current_con_and_neb_images_use_matching_relative_paths(self):
        self.task['task_type'] = 'neb'
        current = self.remote / 'con2'; current.mkdir()
        (self.remote / 'INCAR').write_text('old')
        for root in (self.local, current):
            (root / 'INCAR').write_text('current')
            images = root / 'neb_images' if root == self.local else root
            (images / '01').mkdir(parents=True)
            (images / '01' / 'POSCAR').write_text('structure')
        data = self.query()
        self.assertEqual(data['remote_dir'], str(current))
        self.assertEqual(data['files'][0]['status'], 'synced')
        self.assertEqual(data['files'][2]['status'], 'synced')
        self.assertEqual(data['files'][2]['local_count'], 1)

    def test_large_files_are_explicitly_sampled_and_failures_not_missing(self):
        for root in (self.local, self.remote):
            (root / 'OUTCAR').write_bytes(b'x' * (status.FULL_LIMIT + 1))
        self.assertEqual(self.query()['files'][5]['status'], 'sampled')
        with (self.remote / 'OUTCAR').open('r+b') as f: f.write(b'y')
        self.assertEqual(self.query()['files'][5]['status'], 'different')
        failed = self.query(fail=True)
        self.assertFalse(failed['remote_checked'])
        self.assertTrue(failed['error'])
        self.assertEqual(failed['files'][5]['status'], 'unknown')

    def test_unsafe_paths_and_changing_files_do_not_pass(self):
        (self.local / 'POSCAR').symlink_to(self.remote / 'POSCAR')
        (self.remote / 'POSCAR').write_text('input')
        self.assertEqual(self.query()['files'][2]['status'], 'unknown')
        item = {'paths': {'INCAR': {'size': 5, 'hash': 'same', 'stable': False, 'basis': 'full'}}}
        self.assertEqual(status.compare_file(item, item), 'changing')


if __name__ == '__main__':
    unittest.main()
