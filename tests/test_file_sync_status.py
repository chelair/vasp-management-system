"""Read-only seven-file checks against isolated local/remote trees."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import threading

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
        status._presence_entries.clear()

    def query(self, verify=True, fail=False, presence_only=False, force=False):
        def run(server, command, timeout):
            self.calls += 1
            if fail: return {'exit_code': 1, 'stderr': 'network unavailable'}
            result = subprocess.run(['bash'], input=command, capture_output=True, text=True)
            return {'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        with patch.object(status, 'task_files_dir', return_value=self.local) as local_dir, \
             patch.object(status, 'resolve_remote_path', return_value=str(self.remote)), \
             patch.object(status.ssh, 'run_remote', side_effect=run):
            result = status.file_status(self.project, self.task, verify, presence_only, force)
            if presence_only:
                local_dir.assert_not_called()
            return result

    def test_presence_query_skips_local_scan_and_remote_contents(self):
        (self.remote / 'INCAR').write_text('EDIFF=1E-6')
        (self.remote / 'OUTCAR').write_bytes(b'x' * (status.FULL_LIMIT + 1))
        (self.remote / 'OSZICAR').write_text('')
        data = self.query(presence_only=True)
        self.assertTrue(data['remote_checked'])
        self.assertEqual(self.calls, 1)
        files = {f['name']: f for f in data['files']}
        self.assertEqual(files['INCAR']['remote_status'], 'present')
        self.assertEqual(files['OUTCAR']['remote_status'], 'present')
        self.assertEqual(files['OSZICAR']['remote_status'], 'empty')
        self.assertEqual(files['CONTCAR']['remote_status'], 'missing')
        self.assertTrue(all(f['status'] == 'unknown' and f['local_size'] is None
                            and f['local_count'] is None for f in data['files']))
        with patch.object(Path, 'open', side_effect=AssertionError('content read forbidden')):
            scanned = status.scan_files(self.remote, metadata_only=True)
        self.assertIsNone(scanned['files']['OUTCAR']['paths']['OUTCAR']['hash'])
        failed = self.query(fail=True, presence_only=True, force=True)
        self.assertFalse(failed['remote_checked'])
        self.assertTrue(all(f['remote_status'] == 'unknown' for f in failed['files']))

    def test_presence_cache_expires_without_extending_read_time_and_manual_refresh_bypasses(self):
        (self.remote / 'INCAR').write_text('NSW=100')
        with patch.object(status.time, 'monotonic', return_value=100):
            first = self.query(presence_only=True)
        self.assertFalse(first['cached'])
        (self.remote / 'INCAR').unlink()
        with patch.object(status.time, 'monotonic', return_value=159):
            cached = self.query(presence_only=True)
        self.assertEqual(self.calls, 1)
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['checked_at'], first['checked_at'])
        self.assertEqual(cached['files'][0]['remote_status'], 'present')
        with patch.object(status.time, 'monotonic', return_value=160):
            expired = self.query(presence_only=True)
        self.assertEqual(self.calls, 2)
        self.assertFalse(expired['cached'])
        self.assertEqual(expired['files'][0]['remote_status'], 'missing')
        forced = self.query(presence_only=True, force=True)
        self.assertFalse(forced['cached'])
        self.assertEqual(self.calls, 3)

    def test_presence_cache_invalidated_by_task_changes_and_failures_not_reused(self):
        self.query(presence_only=True)
        for key, value in [('job_id', 'new'), ('status', 'running'),
                           ('remote_dir', '/next'), ('current_output', {'latest_dir': 'con2'})]:
            self.task[key] = value
            self.assertFalse(self.query(presence_only=True)['cached'])
        self.assertEqual(self.calls, 5)
        failed = self.query(presence_only=True, fail=True, force=True)
        self.assertFalse(failed['remote_checked'])
        self.assertFalse(self.query(presence_only=True)['cached'])
        self.assertEqual(self.calls, 7)

    def test_concurrent_presence_requests_share_one_scan(self):
        entered, release = threading.Event(), threading.Event()
        original = status._read_file_status
        def blocked(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return original(*args)
        with patch.object(status, '_read_file_status', side_effect=blocked), \
             patch.object(status, 'resolve_remote_path', return_value=str(self.remote)), \
             patch.object(status.ssh, 'run_remote') as remote, \
             ThreadPoolExecutor(max_workers=2) as pool:
            remote.return_value = {'exit_code': 0, 'stdout': json.dumps(status.scan_files(self.remote))}
            first = pool.submit(status.file_status, self.project, self.task, True, True)
            self.assertTrue(entered.wait(3))
            second = pool.submit(status.file_status, self.project, self.task, True, True)
            release.set()
            self.assertFalse(first.result()['cached'])
            self.assertTrue(second.result()['cached'])
            self.assertEqual(remote.call_count, 1)

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
        self.assertTrue(all(f['remote_status'] == 'unknown' for f in failed['files']))

    def test_remote_presence_is_independent_of_local_files(self):
        (self.local / 'INCAR').write_text('')
        (self.remote / 'INCAR').write_text('EDIFF=1E-6')
        (self.local / 'CONTCAR').write_text('old local result')
        (self.remote / 'OUTCAR').write_text('current remote result')
        (self.remote / 'OSZICAR').write_text('')
        data = self.query()
        files = {f['name']: f for f in data['files']}
        self.assertEqual(files['INCAR']['status'], 'empty')
        self.assertEqual(files['INCAR']['remote_status'], 'present')
        self.assertEqual(files['CONTCAR']['remote_status'], 'missing')
        self.assertEqual(files['OUTCAR']['local_count'], 0)
        self.assertEqual(files['OUTCAR']['remote_status'], 'present')
        self.assertEqual(files['OSZICAR']['remote_status'], 'empty')

    def test_neb_partial_empty_image_is_not_present_even_when_total_size_is_positive(self):
        self.task['task_type'] = 'neb'
        for label, text in [('01', 'structure'), ('02', '')]:
            image = self.remote / label
            image.mkdir()
            (image / 'CONTCAR').write_text(text)
        contcar = next(f for f in self.query()['files'] if f['name'] == 'CONTCAR')
        self.assertEqual(contcar['remote_count'], 2)
        self.assertGreater(contcar['remote_size'], 0)
        self.assertEqual(contcar['remote_status'], 'empty')

    def test_unsafe_paths_and_changing_files_do_not_pass(self):
        (self.local / 'POSCAR').symlink_to(self.remote / 'POSCAR')
        (self.remote / 'POSCAR').write_text('input')
        self.assertEqual(self.query()['files'][2]['status'], 'unknown')
        item = {'paths': {'INCAR': {'size': 5, 'hash': 'same', 'stable': False, 'basis': 'full'}}}
        self.assertEqual(status.compare_file(item, item), 'changing')


if __name__ == '__main__':
    unittest.main()
