"""Electronic inspection status; temporary files and mocked scheduler only."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-ele-check-data-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name) / 'ai.key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import batch_check as check
import checks_store

FINISHED = '\nGeneral timing and accounting informations for this job\n'


class ElectronicConvergenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vasp-ele-check-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {'task_id': 'ele', 'task_type': 'ele', 'remote_dir': str(self.root)}

    def output(self, de='1E-8', deps='-2E-8', step=12, nsw=0, ended=True):
        out = f' EDIFF = 1E-6 NELM = 60 NSW = {nsw}\n Iteration 1( {step})\n'
        out += ' free  energy   TOTEN = -10.0 eV\n'
        (self.root / 'OUTCAR').write_text(out + (FINISHED if ended else ''))
        (self.root / 'OSZICAR').write_text(f'DAV: {step} -10 {de} {deps} 100 1E-5\n 1 F= -10 E0= -10 d E= 0\n')
        # A later edited input must not replace the actual output threshold.
        (self.root / 'INCAR').write_text('EDIFF=1\n')

    def run_check(self, queue=None):
        with patch.object(check, 'match_job_id_by_cwd', return_value=('42' if queue else '', True)), \
             patch.object(check, 'run_bjobs', return_value=queue):
            return check.check_task(self.task, check.DEFAULT_THRESHOLDS)

    def test_finished_electronic_failures_are_unconverged_and_displayed_correctly(self):
        for de, deps in [('2E-4', '-1E-8'), ('-1E-8', '-2E-4'), ('1E-6', '-1E-8')]:
            with self.subTest(de=de, deps=deps):
                self.output(de, deps, step=60)
                result = self.run_check()
                self.assertEqual(result['status'], 'unconverged')
                self.assertIsNone(result['force_converged'])
                row = checks_store._to_row({'name': 'fixture'}, {**self.task, 'status': result['status']}, result)
                self.assertEqual(row['status'], 'warning')
                self.assertIn('电子步未收敛', row['message'])
                self.assertNotIn('力未收敛', row['message'])

    def test_converged_at_final_allowed_step_and_independent_of_nsw(self):
        for nsw in (0, 1, 50):
            with self.subTest(nsw=nsw):
                self.output(de='-1D-8', deps='2d-8', step=60, nsw=nsw)
                self.assertEqual(self.run_check()['status'], 'completed')

    def test_algo_all_final_cga_or_sda_step_overrides_initial_dav(self):
        for algorithm in ('CGA', 'SDA'):
            for de, deps, expected in (
                ('-0.86392E-06', '-0.89144E-06', 'completed'),
                ('-0.10921E-05', '-0.10891E-05', 'unconverged'),
            ):
                with self.subTest(algorithm=algorithm, expected=expected):
                    self.output(step=122)
                    # FS_Kaolin/model1: a DAV warmup followed by direct minimization.
                    (self.root / 'OSZICAR').write_text(
                        'DAV: 5 -327.415760750 -0.18916E+01 -0.18429E+01 1008 1.1\n'
                        'SDA: 6 23.1673353490 350.58 -1.8429 1008 4700\n'
                        f'{algorithm}: 122 -285.217571052 {de} {deps} 1008 0.893E-05 0.396E-06\n'
                        ' 1 F= -295.90602546 E0= -295.87527 d E= -.615175E-01\n')
                    self.assertEqual(self.run_check()['status'], expected)

    def test_converged_dav_cannot_hide_final_cga_or_sda_failure(self):
        for algorithm in ('CGA', 'SDA'):
            with self.subTest(algorithm=algorithm):
                self.output()
                (self.root / 'OSZICAR').write_text(
                    'DAV: 5 -10 1E-8 1E-8\n'
                    f'{algorithm}: 60 -10 2E-3 -1E-8\n 1 F= -10 E0= -10\n')
                self.assertEqual(self.run_check()['status'], 'unconverged')

    def test_old_cycle_cannot_hide_final_failure(self):
        self.output(de='2E-3', step=60)
        path = self.root / 'OSZICAR'
        path.write_text('DAV: 5 -9 1E-8 1E-8\n 1 F= -9 E0= -9\n' + path.read_text().replace(' 1 F=', ' 2 F='))
        out = self.root / 'OUTCAR'
        out.write_text(' Iteration 1( 5)\n aborting loop because EDIFF is reached\n' + out.read_text())
        self.assertEqual(self.run_check()['status'], 'unconverged')

    def test_missing_or_incomplete_evidence_does_not_invent_failure(self):
        for data in ('', 'DAV: 60 -10 NaN 1E-8\n 1 F= -10 E0= -10\n',
                     'DAV: 8 -10 1E-8 1E-8\n 1 F= -10 E0= -10\nDAV: 1 -9 1E-2 1E-2\n'):
            with self.subTest(data=data):
                self.output()
                (self.root / 'OSZICAR').write_text(data)
                self.assertEqual(self.run_check()['status'], 'completed')

    def test_running_suspended_and_abnormal_states_are_not_overwritten(self):
        self.output(de='1E-2', step=60, ended=False)
        for queue in ('RUN', 'SSUSP'):
            with self.subTest(queue=queue):self.assertEqual(self.run_check(queue)['status'], 'running')
        self.assertEqual(self.run_check('DONE')['status'], 'zombied')

    def test_other_task_types_keep_existing_judgment(self):
        self.output(de='1E-2', step=60)
        for kind in ('opt', 'frac'):
            with self.subTest(kind=kind):
                self.task['task_type'] = kind
                self.assertIn(self.run_check()['status'], ('completed', 'low_precision'))

    def test_latest_continuation_is_checked_instead_of_old_converged_output(self):
        self.output()
        parent = self.root
        self.root = parent / 'con1'
        self.root.mkdir()
        self.output(de='2E-3', step=60)
        self.assertEqual(self.run_check()['status'], 'unconverged')


if __name__ == '__main__':
    unittest.main()
