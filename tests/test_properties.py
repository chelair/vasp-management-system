"""R3 acceptance A–L, real local capture, authenticated HTTP and tool boundaries.

Run in an independent process; never use production data, a model or SSH.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_DATA = tempfile.TemporaryDirectory(prefix='vasp-r3-')
os.environ['VASP_WEB_DATA_DIR'] = _DATA.name
os.environ['VASP_AI_KEY_FILE'] = str(Path(_DATA.name)/'ai.key')
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'backend'),str(Path(__file__).resolve().parent)]


class PropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config
        if str(config.DATA_DIR) != _DATA.name: raise unittest.SkipTest('R3 tests require isolated process')
        config.ensure_data_dirs()

    def setUp(self):
        import properties
        import r3_fixtures
        import storage
        self.service,self.fixture,self.storage = properties,r3_fixtures,storage
        self.root = Path(_DATA.name)
        self.project,self.rows = r3_fixtures.seed(self.root)
        self.db = {'projects':[self.project]}
        self.payload = r3_fixtures.request()
        self.user = {'username':'tester','role':'user'}
        self.ssh = patch('ssh._get_client',side_effect=AssertionError('R3 must not use SSH'))
        self.ssh.start(); self.addCleanup(self.ssh.stop)
        # Restore only the fixture archive; tests are independent of mtime/order.
        for p in (self.root/'checks').glob('check_results_*.json'):
            if p.name != 'check_results_r3.json': p.unlink()

    def save(self):
        (self.root/'checks/check_results_r3.json').write_text(json.dumps(self.rows))
        (self.root/'projects.json').write_text(json.dumps(self.db))

    def evaluate(self,payload=None):
        self.save()
        return self.service.evaluate(self.db,self.user,payload or self.payload)

    def mutate_run(self,index,**kwargs):
        r = self.rows[index]
        old = r['property_evidence']['files']['POSCAR']['text']
        r['property_evidence'] = self.fixture.write_run(Path(r['current_output']['dir']),kwargs.pop('text',old),r['last_energy'],**kwargs)

    def test_A_four_energies_and_reference(self):
        result = self.evaluate()
        self.assertEqual(result['status'],'AVAILABLE',result['gaps'])
        self.assertEqual([r['value'] for r in result['results']],[3,4,1])
        self.assertTrue(all(r['validation_status'] == 'PASS' for r in result['results']))
        self.assertEqual(result['targets'][0]['site']['removed_oxygen_index'],4)

    def test_B_missing_oxygen_reference_only_conditional_difference(self):
        del self.payload['mu_O']
        result = self.evaluate()
        self.assertEqual(result['results'],[])
        self.assertIn('absolute_formation_energy',result['not_calculable'])
        self.assertTrue(any(g['check'] == 'mu_O' and g['status'] == 'MISSING' for g in result['gaps']))

    def test_C_one_defect_missing_retains_valid_absolute(self):
        self.payload['targets'][1]['defect'] = {'query':'missing-vacancy'}
        result = self.evaluate()
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual([r['value'] for r in result['results']],[3])
        self.assertEqual(result['inputs'][-1]['status'],'MISSING')

    def test_D_wrong_defect_stoichiometry(self):
        self.mutate_run(1,text=self.fixture.poscar())
        result = self.evaluate()
        self.assertEqual(result['targets'][0]['status'],'INVALID')
        self.assertFalse(any('difference' in r['key'] for r in result['results']))

    def test_E_unconverged_electrons(self):
        self.mutate_run(1,scf=False)
        result = self.evaluate()
        self.assertEqual(result['inputs'][1]['status'],'INCOMPLETE')
        self.assertTrue(any(g['check'] == 'electronic_convergence' for g in result['gaps']))

    def test_E_unconverged_ions(self):
        self.rows[1]['force_converged'] = False
        self.mutate_run(1,ionic=False)
        result = self.evaluate()
        self.assertEqual(result['inputs'][1]['status'],'INCOMPLETE')

    def test_F_incompatible_encut(self):
        self.mutate_run(1,encut=600)
        result = self.evaluate()
        self.assertEqual(result['targets'][0]['status'],'INVALID')
        self.assertTrue(any(g['check'] == 'compatibility.ENCUT' for g in result['gaps']))

    def test_G_same_name_candidates_never_bind(self):
        self.project['tasks'][1]['model_name'] = 'LMR'
        self.payload['targets'][0]['pristine'] = {'query':'LMR'}
        result = self.evaluate()
        item = result['inputs'][0]
        self.assertEqual(item['status'],'AMBIGUOUS')
        self.assertGreater(len(item['candidates']),1)
        self.assertNotIn('source',item)

    def test_H_multiple_sites_distinguished_and_binding_explicit(self):
        original = self.rows[1]
        alternate = copy.deepcopy(original); alternate['task_id'] = 'a_d2'; alternate['job_id'] = 'a_d2'
        root = self.root/'runs/a_d2/con1'
        alternate['current_output']['dir'] = str(root); alternate['remote_dir'] = str(root.parent)
        alternate['property_evidence'] = self.fixture.write_run(root,self.fixture.poscar(defect=True,site=3),-92)
        self.rows.append(alternate)
        self.project['tasks'].append({**self.project['tasks'][1],'task_id':'a_d2','job_id':'a_d2','remote_dir':str(root.parent)})
        self.payload['targets'][0]['defect'] = {'query':'LMR_vac'}
        self.assertEqual(self.evaluate()['inputs'][1]['status'],'AMBIGUOUS')
        self.payload['targets'][0]['defect'] = {'task_id':'a_d2'}
        self.assertEqual(self.evaluate()['targets'][0]['site']['removed_oxygen_index'],3)

    def test_I_charged_defect_requires_other_recipe(self):
        self.mutate_run(1,charge=1)
        result = self.evaluate()
        self.assertEqual(result['inputs'][1]['status'],'INVALID')
        self.assertTrue(any('费米能级' in g['detail'] for g in result['gaps']))

    def test_J_shared_reference_cancelled_exact_difference(self):
        del self.payload['mu_O']; self.payload['common_oxygen_reference'] = True
        result = self.evaluate()
        self.assertEqual(result['status'],'PARTIAL')
        self.assertEqual([r['value'] for r in result['results']],[1])
        self.assertEqual(result['results'][0]['reference_state']['type'],'shared_oxygen_reference_cancelled')
        self.assertIn('mu_O精确消去',''.join(result['results'][0]['conditions']))

    def test_K_two_con_directories_require_observation_choice(self):
        old = copy.deepcopy(self.rows[1]); old['current_output'] = {'latest_dir':'con2','dir':str(self.root/'runs/a_d/con2')}
        old['checked_at'] = (datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
        self.rows.append(old)
        result = self.evaluate()
        self.assertEqual(result['inputs'][1]['status'],'AMBIGUOUS')
        observation = next(o for o in result['inputs'][1]['observations'] if o['directory']['path'].endswith('con1'))
        self.payload['targets'][0]['defect']['observation_id'] = observation['observation_id']
        self.assertEqual(self.evaluate()['inputs'][1]['status'],'AVAILABLE')

    def test_K_mixed_directory_evidence_is_not_accepted(self):
        self.rows[1]['property_evidence']['directory'] += '/con2'
        self.assertNotEqual(self.evaluate()['inputs'][1]['status'],'AVAILABLE')

    def test_L_custom_formula_and_fake_energy_rejected(self):
        for field,value in [('formula','E_defect + E_pristine'),('energy_ev',42),('calculation_function','eval')]:
            payload = {**self.payload,field:value}
            with self.assertRaises(ValueError): self.evaluate(payload)
        self.payload['targets'][0]['defect']['energy_ev'] = 42
        with self.assertRaises(ValueError): self.evaluate()

    def test_L_missing_energy_not_filled_from_task_db(self):
        f = self.rows[1]['property_evidence']['files']['OUTCAR']
        f['text'] = f['text'].replace('free  energy   TOTEN','missing energy')
        self.project['tasks'][1]['last_energy'] = -92
        result = self.evaluate()
        self.assertIsNone(result['inputs'][1]['data']['energy_ev'])
        self.assertFalse(any('difference' in r['key'] for r in result['results']))

    def test_unsupported_recipe(self):
        self.assertEqual(self.service.evaluate({},None,{'property_id':'charged_vacancy'})['status'],'UNSUPPORTED')

    def test_stale_and_unknown_times(self):
        self.rows[1]['checked_at'] = (datetime.now(timezone.utc)-timedelta(hours=5)).isoformat()
        self.assertEqual(self.evaluate()['inputs'][1]['status'],'STALE')
        self.rows[1]['checked_at'] = None
        self.assertEqual(self.evaluate()['inputs'][1]['status'],'UNKNOWN')

    def test_legacy_snapshot_no_current_structure_backfill(self):
        del self.rows[1]['property_evidence']
        result = self.evaluate()
        self.assertIsNone(result['inputs'][1]['data']['structure'])
        self.assertFalse(any('difference' in r['key'] for r in result['results']))

    def test_cross_project_permissions_before_data_read(self):
        other = copy.deepcopy(self.project); other.update(project_id='private',name='private',owner='someone')
        self.db['projects'].append(other)
        self.payload['project_ids'].append('private')
        with patch.object(self.service,'collect_task_observations',side_effect=AssertionError('must authorize before read')):
            with self.assertRaises(self.service.permissions.PermissionDenied): self.evaluate()

    def test_reference_validation_and_nan(self):
        for mu in ({'value_ev':-5}, {'value_ev':'nan','source':'x','conditions':'x'}, {'value_ev':True,'source':'x','conditions':'x'}):
            self.payload['mu_O'] = mu
            with self.assertRaises(ValueError): self.evaluate()

    def test_save_freezes_inputs_results_and_authorization(self):
        self.save()
        result = self.service.evaluate(self.db,self.user,self.payload,persist=True)
        self.rows[1]['last_energy'] = 999; self.save()
        stored = self.service.read_report(self.db,self.user,result['report_id'])
        self.assertEqual([r['value'] for r in stored['results']],[3,4,1])
        self.assertEqual(stored['evidence_sha256'],result['evidence_sha256'])
        with self.assertRaises(self.service.permissions.PermissionDenied):
            self.service.read_report(self.db,{'username':'stranger'},result['report_id'])

    def test_relative_energy_same_composition(self):
        self.payload = {'property_id':'relative_energy','project_ids':['r3p'],'targets':[{'reference':{'task_id':'a_p'},'model':{'task_id':'a_p'}}]}
        self.assertEqual(self.evaluate()['results'][0]['value'],0)
        self.payload['targets'][0]['model']['task_id'] = 'a_d'
        self.assertEqual(self.evaluate()['results'],[])

    def test_source_files_unchanged_by_discovery_and_evaluation(self):
        self.save()
        paths = list((self.root/'runs').rglob('*'))
        before = {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in paths if p.is_file()}
        self.service.discover(self.db,self.user,['r3p'],'LMR')
        self.service.evaluate(self.db,self.user,self.payload)
        self.assertEqual(before,{str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in paths if p.is_file()})

    def test_model_tool_disallows_formula_mu_and_cross_project(self):
        import property_tools
        self.save()
        args = {k:v for k,v in self.payload.items() if k not in ('project_ids','mu_O')}
        args['common_oxygen_reference'] = True
        result = property_tools.dispatch(self.project,self.user,'evaluate_property',args)
        self.assertEqual(result['results'][0]['value'],1)
        for key,value in [('formula','wrong'),('mu_O',self.payload['mu_O']),('project_ids',['private'])]:
            with self.assertRaises(ValueError): property_tools.dispatch(self.project,self.user,'evaluate_property',{**args,key:value})


    def test_simple_adsorption_balanced_and_unbalanced(self):
        # Host + neutral H as one adsorbate; all evidence is produced by real capture.
        for tid,text,energy in [('surf','host\n1\n5 0 0\n0 5 0\n0 0 5\nLi\n1\nDirect\n0 0 0\n',-10),
                                ('mol','atom\n1\n5 0 0\n0 5 0\n0 0 5\nH\n1\nDirect\n.5 .5 .5\n',-2),
                                ('complex','complex\n1\n5 0 0\n0 5 0\n0 0 5\nLi H\n1 1\nDirect\n0 0 0\n.5 .5 .5\n',-13)]:
            self.add_task(tid,text,energy)
        self.payload = {'property_id':'adsorption.simple','project_ids':['r3p'],'targets':[{'complex':{'task_id':'complex'},'surface':{'task_id':'surf'},'adsorbate':{'task_id':'mol'}}]}
        result = self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[-1],result['gaps'])
        self.payload['targets'][0]['complex']['task_id'] = 'surf'
        self.assertEqual(self.evaluate()['results'],[])

    def add_task(self,tid,text,energy,task_type='opt'):
        root = self.root/'runs'/tid/'con1'
        row = copy.deepcopy(self.rows[0]); row.update(task_id=tid,job_id=tid,task_type=task_type,remote_dir=str(root.parent),last_energy=energy)
        row['current_output'] = {'latest_dir':'con1','dir':str(root)}
        row['property_evidence'] = self.fixture.write_run(root,text,energy)
        self.rows.append(row)
        self.project['tasks'].append({**self.project['tasks'][0],'task_id':tid,'job_id':tid,'model_name':tid,'task_type':task_type,'remote_dir':str(root.parent),'dir_path':f'R3P/{task_type}/{tid}'})
        return row,root

    def test_existing_neb_barrier_and_comparison(self):
        for tid,values in [('neb1',[-10,-9,-10.2]),('neb2',[-10,-8.5,-10.2])]:
            row,root = self.add_task(tid,self.fixture.poscar(),-10,task_type='neb')
            row['incar']['IMAGES'] = 1
            row['neb_barrier'] = {'images':[{'label':str(i),'energy':e} for i,e in enumerate(values)]}
            row['property_evidence']['neb_images'] = [{'label':f'{i:02}','evidence':self.fixture.write_run(root/f'{i:02}',self.fixture.poscar(),e)} for i,e in enumerate(values)]
        self.payload = {'property_id':'neb.barrier','project_ids':['r3p'],'targets':[{'label':'path A','path':{'task_id':'neb1'}},{'label':'path B','path':{'task_id':'neb2'}}], 'reaction_correspondence':'synthetic same reaction/direction/endpoints'}
        result = self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[1,1.5,.5],result['gaps'])
        del self.rows[-1]['property_evidence']['neb_images'][1]
        result = self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[1])

    def test_work_function_difference_uses_existing_curve(self):
        import work_function
        for tid,value in [('wf1',5),('wf2',5.5)]:
            row,root = self.add_task(tid,self.fixture.poscar(),-10,task_type='ele')
            task = next(t for t in self.project['tasks'] if t['task_id'] == tid)
            meta_path = work_function.meta_path('R3P',task); meta_path.parent.mkdir(parents=True,exist_ok=True)
            data_path = work_function.data_path('R3P',task)
            # Start is flat; end is sloped, so existing plateau parser selects start.
            points = [(i,float(value)+1 if i<25 else float(value)+1+(i-25)*.1) for i in range(100)]
            data_path.write_text('\n'.join(f'{z} {v}' for z,v in points))
            from dates import now_iso
            meta_path.write_text(json.dumps({'status':'done','finished_at':now_iso(),'remote':{'remote_dir':str(root)},'result':{'work_function':value,'vacuum_level':value+1,'efermi':1,'axis':'c'}}))
        self.payload = {'property_id':'work_function.difference','project_ids':['r3p'],'targets':[{'reference':{'task_id':'wf1'},'model':{'task_id':'wf2'}}], 'surface_side':'start'}
        result = self.evaluate()
        self.assertEqual([r['value'] for r in result['results']],[.5],result['gaps'])
        self.payload['surface_side'] = 'end'
        self.assertEqual(self.evaluate()['results'],[])

    def test_capture_rejects_symlink_and_unstable_input(self):
        from batch_check import capture_property_evidence
        root = self.root/'capture_symlink'; root.mkdir(exist_ok=True)
        path = root/'POSCAR'; path.unlink(missing_ok=True); path.symlink_to(self.root/'projects.json')
        self.assertIn('error',capture_property_evidence(str(root))['files']['POSCAR'])
        self.rows[1]['property_evidence']['files']['POSCAR']['stable'] = False
        self.assertEqual(self.evaluate()['inputs'][1]['status'],'INCOMPLETE')

    def test_F_full_hubbard_arrays_compared_per_element(self):
        from batch_check import capture_property_evidence
        for index,u in [(0,'4 0 0'),(1,'5 0 0')]:
            root = Path(self.rows[index]['current_output']['dir'])
            root.joinpath('INCAR').write_text(root.joinpath('INCAR').read_text()+f'LDAU = .TRUE.\nLDAUL = 2 -1 -1\nLDAUU = {u}\nLDAUJ = 0 0 0\n')
            root.joinpath('OUTCAR').write_text(root.joinpath('OUTCAR').read_text()+f'LDAU = T\nLDAUL = 2 -1 -1\nLDAUU = {u}\nLDAUJ = 0 0 0\n')
            self.rows[index]['property_evidence'] = capture_property_evidence(str(root))
        result = self.evaluate()
        self.assertTrue(any(g['check']=='compatibility.LDAUU' and g['status']=='INVALID' for g in result['gaps']))
        self.assertFalse(any(r['key']=='0.formation_energy' for r in result['results']))

    def test_duplicate_element_species_are_not_collapsed(self):
        text = self.fixture.poscar(defect=True).replace('Li Mn O\n1 1 1','Li Li O\n1 1 1')
        self.rows[1]['property_evidence']['files']['POSCAR']['text'] = text
        result = self.evaluate()
        self.assertEqual(result['inputs'][1]['status'],'INVALID')
        self.assertTrue(any('重复元素物种' in g['detail'] for g in result['gaps']))

    def test_runtime_accuracy_mismatch_does_not_validate_new_draft(self):
        self.rows[1]['property_evidence']['files']['INCAR']['text'] = self.rows[1]['property_evidence']['files']['INCAR']['text'].replace('EDIFF = 1E-6','EDIFF = 1E-8')
        result = self.evaluate()
        self.assertEqual(result['inputs'][1]['status'],'INVALID')
        self.assertTrue(any(g['check']=='runtime.EDIFF' for g in result['gaps']))

    def test_F_potential_hash_and_kpoint_shift_mismatch(self):
        self.rows[1]['property_evidence']['potcar']['datasets'][0]['sha256'] = 'changed'
        result = self.evaluate()
        self.assertTrue(any(g['check']=='compatibility.POTCAR' and g['status']=='INVALID' for g in result['gaps']))
        self.mutate_run(1)
        self.rows[1]['property_evidence']['files']['KPOINTS']['text'] = 'fixture\n0\nGamma\n2 2 1\n.5 0 0\n'
        self.rows[1]['property_evidence']['files']['OUTCAR']['text'] = self.rows[1]['property_evidence']['files']['OUTCAR']['text'].replace('shift: 0 0 0','shift: .5 0 0')
        self.assertTrue(any(g['check']=='compatibility.kpoints' and g['status']=='INVALID' for g in self.evaluate()['gaps']))

    def test_batch_check_keeps_scientific_metadata_without_status_override(self):
        import batch_check
        row = self.rows[0]
        with patch.dict(os.environ,{'VASP_BATCH_NO_BJOBS':'1'}), patch.object(batch_check,'_local_remote_dir',side_effect=lambda x:x), patch.object(batch_check,'_analyze_outcar',side_effect=lambda result,*a,**k:result.update(status='completed',last_energy=-100)):
            with patch.object(batch_check,'capture_property_evidence',return_value={}):
                baseline = batch_check.check_task({**self.project['tasks'][0],'project_name':'R3P'},batch_check.DEFAULT_THRESHOLDS)
            result = batch_check.check_task({**self.project['tasks'][0],'project_name':'R3P'},batch_check.DEFAULT_THRESHOLDS)
        self.assertEqual(result['status'],baseline['status'])
        self.assertEqual(result['property_evidence']['schema_version'],'r3.evidence.1')
        self.assertTrue(result['property_evidence']['files']['POSCAR']['text'])

    def test_structure_lattice_and_nonoxygen_changes_fail(self):
        self.mutate_run(1,text=self.fixture.poscar(defect=True).replace('5 0 0','6 0 0'))
        result = self.evaluate()
        self.assertTrue(any(g['check']=='cell' and g['status']=='INVALID' for g in result['gaps']))
        self.mutate_run(1,text=self.fixture.poscar(defect=True).replace('Li Mn O','Li Cl O'))
        self.assertFalse(any('0.formation_energy' == r['key'] for r in self.evaluate()['results']))

    def test_http_auth_owner_bad_payload_and_saved_report(self):
        import auth
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        import socket
        import threading
        import time
        import urllib.request
        import urllib.error
        import uvicorn
        from middleware.auth import install
        from routers.properties import router
        from permissions import PermissionDenied
        self.save()
        try: user,_ = auth.create_user('tester')
        except ValueError: user = auth.find_user('tester')
        token,_ = auth.create_session(user)
        app = FastAPI(); install(app); app.include_router(router,prefix='/api')
        @app.exception_handler(PermissionDenied)
        async def denied(req,exc): return JSONResponse(status_code=403,content={'message':str(exc)})
        sock = socket.socket(); sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app,log_level='error'))
        thread = threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True); thread.start()
        def cleanup():
            server.should_exit = True; thread.join(5)
        self.addCleanup(cleanup)
        deadline = time.monotonic()+5
        while not server.started and time.monotonic()<deadline: time.sleep(.01)
        class Client:
            def request(self,path,method='GET',headers=None,json=None):
                raw = None if json is None else __import__('json').dumps(json).encode()
                req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=raw,method=method,headers={**(headers or {}),'Content-Type':'application/json'})
                try: response = urllib.request.urlopen(req,timeout=5)
                except urllib.error.HTTPError as exc: response = exc
                text = response.read().decode(); response.close()
                from types import SimpleNamespace
                return SimpleNamespace(status_code=response.code,text=text,json=lambda:__import__('json').loads(text))
            def get(self,path,**kwargs): return self.request(path,**kwargs)
            def post(self,path,**kwargs): return self.request(path,method='POST',**kwargs)
        client = Client()
        self.assertEqual(client.get('/api/properties/recipes').status_code,401)
        headers = {'Authorization':'Bearer '+token}
        response = client.post('/api/properties/evaluate',headers=headers,json=self.payload)
        self.assertEqual(response.status_code,200,response.text)
        report = response.json()['data']
        self.assertEqual(report['results'][0]['value'],3)
        self.assertEqual(client.get('/api/properties/reports/'+report['report_id'],headers=headers).status_code,200)
        self.assertEqual(client.post('/api/properties/evaluate',headers=headers,json={**self.payload,'formula':'bad'}).status_code,400)


if __name__ == '__main__': unittest.main()
