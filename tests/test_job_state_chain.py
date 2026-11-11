"""Current LSF facts, empty/failed queries and file-write guards; isolated only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-state-chain-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name) / 'ai.key')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import batch_check as check
import continuation
import lsf_state


class StateChainTests(unittest.TestCase):
    def setUp(self):
        check._BJOBS_DETAIL_CACHE.clear()
        check._BJOBS_CWD_TABLE = None
        check._BJOBS_CWD_QUERIED = False

    def test_detail_uses_current_status_and_does_not_read_script_or_history_tokens(self):
        for state, expected in [('EXIT','EXIT'),('RU\n  N','RUN'),('PSUSP','SSUSP'),('WAIT','PEND')]:
            text=f'Job <352424>, Status <{state}>, Command <echo RUN PEND>\nPreviously RUN\n'
            self.assertEqual(check._parse_bjobs_detail(text,0),expected)
        for text in ('Permission denied', 'bjobs: command not found', 'connection failed RUN', 'history: RUN then EXIT'):
            self.assertEqual(check._parse_bjobs_detail(text,1),'UNKNOWN')
        self.assertEqual(check._parse_bjobs_detail('Job <352424> is not found',255),'NOT_FOUND')

    def test_empty_query_is_known_and_cached_but_query_error_stays_unknown(self):
        with patch.object(lsf_state,'query_jobs',return_value=[]) as query:
            self.assertEqual(check.match_job_id_by_cwd('/work','/work'),('',True))
            self.assertEqual(check.match_job_id_by_cwd('/work','/work'),('',True))
            self.assertEqual(check.run_bjobs('352424'),'NOT_FOUND')
            query.assert_called_once()
        self.setUp()
        with patch.object(lsf_state,'query_jobs',side_effect=RuntimeError('unavailable')) as query:
            self.assertEqual(check.match_job_id_by_cwd('/work','/work'),('',False))
            self.assertEqual(check.run_bjobs('352424'),'UNKNOWN')
            query.assert_called_once()

    def test_current_table_filters_terminal_jobs_and_normalizes_suspension(self):
        rows=lsf_state.parse_jobs('1|EXIT|/old|RUN in name\n2|PSUSP|/work|job\n3|WAIT|/waiting|job\n')
        with patch.object(lsf_state,'query_jobs',return_value=rows):
            self.assertEqual(check.match_job_id_by_cwd('/old','/old'),('',True))
            self.assertEqual(check.match_job_id_by_cwd('/work','/work'),('2',True))
            self.assertEqual(check.run_bjobs('1'),'EXIT')
            self.assertEqual(check.run_bjobs('2'),'SSUSP')
            self.assertEqual(check.run_bjobs('3'),'PEND')

    def test_scheduler_query_failure_preserves_task_status_instead_of_inventing_running_or_ended(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'OUTCAR').write_text('free energy TOTEN = -10.0 eV\n')
            for state in ('pending','running','unconverged'):
                with self.subTest(state=state),patch.object(check,'match_job_id_by_cwd',return_value=('',False)):
                    result=check.check_task({'task_id':'x','task_type':'opt','remote_dir':tmp,'status':state},check.DEFAULT_THRESHOLDS)
                    self.assertEqual(result['status'],state)
                    self.assertFalse(result['scheduler_query_ok'])

    def test_active_registered_job_in_other_directory_is_not_bound_to_current_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'OUTCAR').write_text('free energy TOTEN = -10.0 eV\n')
            row={'job_id':'42','state':'RUN','directory':'/different/con1','name':'job'}
            with patch.object(lsf_state,'query_jobs',return_value=[row]):
                result=check.check_task({'task_id':'x','task_type':'opt','remote_dir':tmp,'job_id':'42','status':'unconverged'},check.DEFAULT_THRESHOLDS)
            self.assertEqual(result['status'],'unconverged')
            self.assertFalse(result['scheduler_query_ok'])
            self.assertFalse(result.get('job_id'))

    def test_uncertain_registered_job_without_matching_directory_is_not_reported_absent(self):
        for state in ('UNKWN', 'ZOMBI'):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                self.setUp()
                Path(tmp, 'OUTCAR').write_text('free energy TOTEN = -10.0 eV\n')
                row = {'job_id': '42', 'state': state, 'directory': '-', 'name': 'job'}
                with patch.object(lsf_state, 'query_jobs', return_value=[row]):
                    result = check.check_task({'task_id': 'x', 'task_type': 'opt', 'remote_dir': tmp,
                                               'job_id': '42', 'status': 'running'}, check.DEFAULT_THRESHOLDS)
                self.assertEqual(result['status'], 'running')
                self.assertEqual(result['queue_status'], 'UNKNOWN')
                self.assertFalse(result['scheduler_query_ok'])

    def test_continuation_checks_actual_current_directory_before_any_file_write(self):
        for kind in ('opt','neb'):
            for state in ('RUN','PEND','PSUSP','WAIT','UNKWN','EXIT','empty','error','other_directory','unknown_cwd'):
                with self.subTest(kind=kind,state=state),tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);work=root/'task';work.mkdir();bin_dir=root/'bin';bin_dir.mkdir()
                    for name in ('OUTCAR','CONTCAR','POSCAR','INCAR','KPOINTS','POTCAR','vasp.lsf','WAVECAR'):
                        (work/name).write_text('ISTART=0\n' if name=='INCAR' else 'saved output\n')
                    if kind=='neb':
                        for label in ('00','01','02'):
                            image=work/label;image.mkdir()
                            for name in ('POSCAR','CONTCAR','OUTCAR'): (image/name).write_text('saved output\n')
                    row=[] if state in ('empty','error') else [{'job_id':'999' if state=='unknown_cwd' else '352424','state':'RUN' if state in ('other_directory','unknown_cwd') else state,
                           'directory':'-' if state=='unknown_cwd' else str(root/'other') if state=='other_directory' else str(work),'name':'history RUN PEND'}]
                    data=root/'rows';data.write_text(''.join('|'.join(r.values())+'\n' for r in row))
                    bjobs=bin_dir/'bjobs'
                    bjobs.write_text('#!/bin/sh\n'+('echo "scheduler unavailable" >&2\nexit 2\n' if state=='error' else f'cat "{data}"\n'))
                    bjobs.chmod(0o755)
                    with patch.object(continuation,'load_servers',return_value={'test':{'lsf_profile':'/nonexistent-profile'}}):
                        builder=continuation._neb_continuation_script if kind=='neb' else continuation._opt_continuation_script
                        script=builder('test',str(work),{'job_id':'999'})
                    result=subprocess.run(['bash','-c',script],env={**os.environ,'PATH':str(bin_dir)+os.pathsep+os.environ['PATH']},capture_output=True,text=True)
                    blocked=state not in ('EXIT','empty','other_directory')
                    self.assertEqual((work/'con1').exists(),not blocked,result.stderr+result.stdout)
                    if blocked:
                        self.assertTrue((work/'WAVECAR').exists())
                    if state in ('error','unknown_cwd'):self.assertNotEqual(result.returncode,0)
                    else:self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
