"""Creation/archive regressions; isolated data and mocked remote files, no HPC jobs."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-created-inputs-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name)/'ai.key')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import config
import input_state
import storage
from routers import jobs
from task_paths import completed_optimization

POSCAR = 'fixture\n1\n10 0 0\n0 10 0\n0 0 10\nH\n1\nDirect\n0 0 0\n'


class CreatedInputsTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(config.DATA_DIR,Path(_DATA.name))
        self.temp = tempfile.TemporaryDirectory(dir=_DATA.name)
        self.addCleanup(self.temp.cleanup)
        self.remote = Path(self.temp.name)/'remote'
        self.project = {'name':'P','project_id':'p','server':'mock','owner':'alice','tasks':[
            self.task('initial','opt','archived',archived_from='completed'),
            self.task('final','opt','completed'), self.task('neb','neb','pending'),
            self.task('frac','frac','pending',parent_task_id='initial',dir_path='P/initial/frac'),
            self.task('ele','ele','pending')]}
        storage.save_db({'projects':[self.project]},backup=False)
        for target, value in [('neb',99),('frac',99),('ele',99)]:
            self.inputs(self.remote/target, {'IBRION':value})
            self.inputs(self.remote/target/'con99', {'IBRION':999})
        self.requests = []
        patches = [patch('ssh.run_remote',side_effect=AssertionError('No real SSH')),
                   patch.object(input_state,'_download_text',side_effect=self.download),
                   patch.object(input_state,'_newest_dir_with_file',side_effect=AssertionError('Creation must pin source directory')),
                   patch.object(input_state,'_convert_to_cif'),patch.object(jobs,'read_or_convert_cif',return_value=None),
                   patch.object(jobs,'_schedule_archive_outputs'),
                   patch.object(jobs,'_resolve_task',side_effect=self.resolve),
                   patch('paths.load_path_mapping',return_value={'local_root':str(Path(_DATA.name)/'projects'),'remote_roots':{}})]
        for p in patches:
            p.start();self.addCleanup(p.stop)

    def task(self,name,kind,status,**extra):
        return {'task_id':name,'model_name':name,'task_type':kind,'status':status,
                'dir_path':'P/'+name,'remote_dir':str(self.remote/name),'input_state':{},**extra}

    def resolve(self,task_id):
        project = storage.load_db()['projects'][0]
        return project,next(t for t in project['tasks'] if t['task_id']==task_id)

    def download(self,server,path):
        self.requests.append(path)
        return Path(path).read_text() if Path(path).is_file() else None

    def inputs(self,path,params):
        path.mkdir(parents=True,exist_ok=True)
        (path/'INCAR').write_text('\n'.join(f'{k} = {v}' for k,v in params.items())+'\n')
        (path/'KPOINTS').write_text('mesh\n0\nGamma\n2 3 1\n0 0 0\n')
        (path/'POSCAR').write_text(POSCAR)

    def create_neb(self,*args,**kwargs):
        self.inputs(self.remote/'neb',{'IBRION':3,'IMAGES':5,'IOPT':7,'POTIM':0})
        return {'neb_dir':str(self.remote/'neb'),'source_is':'initial','source_fs':'final','images':['00','01'], 'warnings':[]}

    def test_archived_completed_opt_is_usable_but_unknown_or_unconverged_is_not(self):
        for previous in ('completed','pending','running','unconverged',None):
            task = {'task_type':'opt','status':'archived','archived_from':previous}
            self.assertEqual(completed_optimization(task),previous=='completed')
        p,t = self.resolve('neb')
        payload = {'initial_opt_task_id':'initial','final_opt_task_id':'final'}
        result = jobs.core_create_neb(p,t,payload,dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertEqual(self.requests,[])
        p['tasks'][0]['archived_from']='unconverged'
        with self.assertRaises(jobs.ActionError):jobs.core_create_neb(p,t,payload,dry_run=True)

    def test_archive_reopen_restores_actual_status_and_frac_own_status(self):
        for status in ('pending','queued','running','completed','unconverged','zombied'):
            with self.subTest(status=status):
                with storage.db_transaction() as db:
                    task=db['projects'][0]['tasks'][1];task['status']=status
                jobs.archive_task('final')
                self.assertEqual(self.resolve('final')[1]['archived_from'],status)
                response=jobs.unarchive_task('final')
                self.assertEqual(response['data']['new_status'],status)
                self.assertEqual(self.resolve('final')[1]['status'],status)
        with storage.db_transaction() as db:
            db['projects'][0]['tasks'][0].update(status='completed',group={'group_type':'free_energy','group_id':'g','group_role':'main_structure','structure_label':'1'})
            db['projects'][0]['tasks'][3].update(status='unconverged',group={'group_type':'free_energy','group_id':'g','group_role':'main_structure','structure_label':'1'})
        jobs.archive_task('initial');jobs.unarchive_task('initial')
        self.assertEqual(self.resolve('initial')[1]['status'],'completed')
        self.assertEqual(self.resolve('frac')[1]['status'],'unconverged')

    def test_neb_mirrors_created_directory_and_keeps_new_draft(self):
        p,t = self.resolve('neb')
        def create(*args,**kwargs):
            result=self.create_neb(*args,**kwargs)
            with storage.db_transaction() as db:
                current=next(row for row in db['projects'][0]['tasks'] if row['task_id']=='neb')
                current['input_state']={'draft':{'KPOINTS':{'mesh':[9,9,9]}},'changes':[{'file':'KPOINTS','key':'mesh','to':'9 9 9'}]}
            return result
        with patch.object(jobs,'create_neb_files',side_effect=create):
            result=jobs.core_create_neb(p,t,{'initial_opt_task_id':'initial','final_opt_task_id':'final','num_images':5})
        current=self.resolve('neb')[1]
        state=current['input_state']
        self.assertTrue(result['input_synced'])
        self.assertEqual(state['files']['INCAR']['params']['IOPT'],'7')
        self.assertEqual(state['source']['remote_dir'],str(self.remote/'neb'))
        self.assertEqual(state['draft']['KPOINTS']['mesh'],[9,9,9])
        self.assertTrue(state['files']['KPOINTS']['protected'])
        self.assertTrue(all('/con99/' not in path for path in self.requests))
        self.assertEqual(jobs.read_task_input('neb')['data']['files']['INCAR']['params']['IMAGES'],'5')

    def test_frac_and_electronic_creation_refresh_exact_input_snapshots(self):
        def create_frac(*args,**kwargs):
            self.inputs(self.remote/'frac',{'IBRION':5,'NSW':1,'POTIM':.015})
            return {'frac_dir':str(self.remote/'frac'),'source_dir':'initial','latest_dir':None,'warnings':[]}
        p,t=self.resolve('initial')
        with patch.object(jobs,'create_frac_files',side_effect=create_frac):
            jobs.core_create_frac(p,t)
        self.assertEqual(self.resolve('frac')[1]['input_state']['files']['INCAR']['params']['IBRION'],'5')
        def create_ele(*args,**kwargs):
            self.inputs(self.remote/'ele',{'IBRION':-1,'LORBIT':11})
            return {'ele_dir':str(self.remote/'ele'),'source_dir':'initial','warnings':[]}
        with patch.object(jobs,'build_ele_inputs',side_effect=create_ele):
            response=jobs.build_ele('ele',{'source_type':'opt','source_task_id':'initial','ele_types':['pdos']})
        self.assertTrue(response['success'],response)
        self.assertEqual(self.resolve('ele')[1]['input_state']['files']['INCAR']['params']['IBRION'],'-1')

    def test_failed_mirror_does_not_report_remote_creation_failed(self):
        p,t=self.resolve('neb')
        with patch.object(jobs,'create_neb_files',side_effect=self.create_neb),patch.object(input_state,'_download_text',side_effect=OSError('mock read failed')):
            result=jobs.core_create_neb(p,t,{'initial_opt_task_id':'initial','final_opt_task_id':'final'})
        self.assertFalse(result['input_synced'])
        self.assertIn('计算文件已生成',result['warnings'][0])
        self.assertTrue((self.remote/'neb/INCAR').is_file())
        self.assertEqual(self.resolve('neb')[1]['status'],'pending')


if __name__=='__main__':unittest.main()
