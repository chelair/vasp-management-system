"""Ionic total energy versus unfinished SCF TOTEN; isolated data, no SSH/job actions."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-ionic-energy-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name) / 'ai.key')
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'backend'), str(Path(__file__).resolve().parent)]
import batch_check as check
import checks_store as store

IONIC = -819.90785191
ELECTRONIC = -803.03211069
FORCE = ' POSITION TOTAL-FORCE (eV/Angst)\n ---------\n 0 0 0 .01 0 0\n ---------\n'
# Reproduces the retained FS@Kaolin con8 step 54 / step 55 SCF energy ordering.
OUT = (FORCE + ' Edisp (eV) -16.87654\n'
       ' FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)\n ---------\n'
       ' free  energy   TOTEN  = -819.90785191 eV\n'
       ' Iteration 55( 1)\n free energy    TOTEN = -803.02833910 eV\n'
       ' Iteration 55( 7)\n free energy    TOTEN = -803.03211069 eV\n')
OSZ = (' 54 F= -.81990785E+03 E0= -.81981355E+03 d E= -.799786E-02\n'
       'DAV: 7 -0.803032110694E+03 0.13925E-03 -0.75271E-04\n')
POSCAR = 'H\n1\n5 0 0\n0 5 0\n0 0 5\nH\n1\nDirect\n0 0 0\n'


class IonicEnergyTests(unittest.TestCase):
    def test_running_dispersion_total_matches_last_ionic_curve(self):
        self.assertEqual(check.extract_toten(OUT), IONIC)
        self.assertEqual(check.parse_total_force_blocks(OUT)[-1]['energy'], IONIC)
        self.assertIsNone(check.extract_toten(' free energy TOTEN = -803.03211069 eV\n'))

    def test_header_and_legacy_samples_scientific_notation_and_finite_values(self):
        compact = ' FREE ENERGIE OF THE ION-ELECTRON SYSTEM (eV)\n ----\n free energy TOTEN = -.81990785191D+03 eV\n'
        self.assertEqual(check.extract_toten(compact), IONIC)
        self.assertEqual(check.extract_toten(' free  energy   TOTEN = -8.1990785191E2 eV\n'), IONIC)
        self.assertIsNone(check.extract_toten(' free  energy TOTEN = 1e999 eV\n'))
        self.assertIsNone(check.extract_toten(' free  energy TOTEN = -819.9'))
        self.assertIsNone(check.extract_toten(' energy without entropy = -2\n energy(sigma->0) = -3\n'))

    def test_incomplete_force_block_cannot_borrow_next_scf_energy(self):
        text = OUT + FORCE + ' Iteration 56( 1)\n free energy TOTEN = -803 eV\n'
        blocks = check.parse_total_force_blocks(text)
        self.assertEqual(blocks[0]['energy'], IONIC)
        self.assertIsNone(blocks[1]['energy'])
        self.assertEqual(check.extract_toten(text), IONIC)

    def test_running_suspended_and_ended_inspection_keep_status_and_energy(self):
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)
            (run / 'POSCAR').write_text(POSCAR)
            (run / 'INCAR').write_text('EDIFFG=-0.02\nEDIFF=1E-6\nIVDW=11\n')
            (run / 'KPOINTS').write_text('mesh\n0\nGamma\n5 5 5\n0 0 0\n')
            (run / 'OSZICAR').write_text(OSZ)
            for queue, status in [('RUN', 'running'), ('SSUSP', 'running'), ('DONE', 'completed')]:
                with self.subTest(queue=queue):
                    (run / 'OUTCAR').write_text(OUT + ('General timing and accounting informations for this job\n' if queue == 'DONE' else ''))
                    with patch.object(check, 'match_job_id_by_cwd', return_value=('42', True)), \
                         patch.object(check, 'run_bjobs', return_value=queue):
                        result = check.check_task({'task_id':'fixture', 'task_type':'opt', 'remote_dir':root, 'job_id':'42'}, check.DEFAULT_THRESHOLDS)
                    self.assertEqual(result['status'], status, result)
                    self.assertEqual(result['last_energy'], IONIC)
                    self.assertEqual(result['force_history'][-1]['energy'], IONIC)

    def record(self):
        return {'task_id':'fixture', 'task_type':'opt', 'remote_dir':'/project/FS',
                'current_output':{'latest_dir':'con8'}, 'last_energy':ELECTRONIC,
                'checked_at':'2026-10-21T21:50:00', 'force_history':[{'step':54, 'energy':IONIC}],
                'property_evidence':{'schema_version':'r3.evidence.1', 'directory':'/project/FS/con8',
                    'files':{'OUTCAR':{'stable':True, 'text':OUT}, 'OSZICAR':{'stable':True, 'text':OSZ}}}}

    def test_legacy_views_correct_same_observation_without_rewriting_archive_or_id(self):
        from ai_inspections import _summary
        with tempfile.TemporaryDirectory() as root, patch.object(store, 'CHECKS_DIR', Path(root)):
            row = self.record()
            archive = Path(root) / 'check_results_fixture.json'
            archive.write_text(json.dumps([row]))
            raw = archive.read_bytes()
            canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
            expected_id = hashlib.sha256((archive.name + '\n' + canonical).encode()).hexdigest()[:24]
            observation = store.collect_task_observations('fixture')[0]
            self.assertEqual(observation['observation_id'], expected_id)
            self.assertEqual(observation['data']['last_energy'], IONIC)
            self.assertEqual(store.collect_results()['fixture']['last_energy'], IONIC)
            summary = _summary(observation)
            self.assertEqual(summary['energy_ev'], IONIC)
            self.assertEqual(summary['energy_correction']['recorded_energy_ev'], ELECTRONIC)
            self.assertEqual(archive.read_bytes(), raw)
            self.assertEqual(row['last_energy'], ELECTRONIC)

    def test_legacy_correction_requires_same_directory_stable_corroborated_evidence(self):
        row = self.record()
        cases = [copy.deepcopy(row) for _ in range(5)]
        cases[0]['property_evidence']['directory'] = '/project/FS/con7'
        cases[1]['property_evidence']['files']['OUTCAR']['stable'] = False
        cases[2]['property_evidence']['files']['OSZICAR']['stable'] = False
        cases[3]['property_evidence']['files']['OSZICAR']['text'] = ' 54 F= -900 E0= -900\n'
        del cases[4]['property_evidence']
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertEqual(store._energy_view(candidate)['last_energy'], ELECTRONIC)
                self.assertNotIn('energy_correction', candidate)

    def test_scientific_validation_and_capture_use_completed_ionic_summary(self):
        import r3_fixtures
        from property_science import normalize
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)
            r3_fixtures.write_run(run, r3_fixtures.poscar(), IONIC)
            with (run / 'OUTCAR').open('a') as stream:
                stream.write(' Iteration 55( 7)\n free energy TOTEN = -803.03211069 eV\n')
            evidence = check.capture_property_evidence(str(run))
            data, checks = normalize(evidence, {'last_energy':IONIC})
            self.assertEqual(data['energy_ev'], IONIC)
            self.assertEqual(next(c['status'] for c in checks if c['check'] == 'energy'), 'AVAILABLE')

    def test_report_outcar_fallback_uses_same_total_definition(self):
        from routers.reports import last_energy
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)
            (run / 'files').mkdir()
            (run / 'files/OUTCAR').write_text(OUT)
            self.assertEqual(last_energy(run), IONIC)


if __name__ == '__main__':
    unittest.main()
