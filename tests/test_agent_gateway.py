"""阶段1离线集成：临时项目库/真实HTTP鉴权/Mock SSH和LSF。独立进程运行。"""
import copy
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'backend'), str(Path(__file__).resolve().parent)]
from mock_hpc import MockHpc


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='vasp-gateway-')
        cls.root = Path(cls.temp.name)
        os.environ['VASP_WEB_DATA_DIR'] = str(cls.root / 'data')
        os.environ['VASP_SSH_MOCK'] = '1'
        os.environ['VASP_MOCK_REMOTE_ROOT'] = str(cls.root / 'remote')
        os.environ.pop('VASP_SYNC_REMOTE_DIRS', None)
        import config
        if config.DATA_DIR.resolve() != (cls.root / 'data').resolve():
            raise unittest.SkipTest('需独立进程运行test_agent_gateway.py')
        import auth, storage, paths, permissions
        from automation import gateway, ledger, store, budget, unknown, scheduler
        from routers import jobs
        cls.auth, cls.storage, cls.paths, cls.permissions = auth, storage, paths, permissions
        cls.gateway, cls.ledger, cls.store, cls.budget, cls.unknown, cls.scheduler = gateway, ledger, store, budget, unknown, scheduler
        cls.jobs = jobs
        config.ensure_data_dirs()
        cls.hpc = MockHpc(cls.root / 'remote', paths.remote_root('server1'))
        cls.owner, _ = auth.create_user('owner', 'MockPassword123!', role='user')
        cls.admin, _ = auth.create_user('admin', 'MockPassword123!', role='admin')
        cls.agent, _ = auth.create_user('agent', 'MockPassword123!', role='agent', delegate_to='owner')
        cls.other, _ = auth.create_user('other', 'MockPassword123!', role='user')

    @classmethod
    def tearDownClass(cls):
        cls.scheduler.stop()
        cls.temp.cleanup()

    def setUp(self):
        self.hpc.reset()
        from automation import audit
        audit.AUDIT_FILE.unlink(missing_ok=True)
        os.environ.pop('MOCK_BJOBS_ERROR', None)
        self.remote = self.hpc.write_inputs('STAGE1/T1', {'vasp.lsf': '#!/bin/bash\n#BSUB -n 24\n#BSUB -W 01:00\n#BSUB -q normal\nmpirun vasp_std\n'})
        self.db = {'projects': [{'name': 'STAGE1', 'server': 'server1', 'owner': 'owner', 'tasks': [
            {'task_id': 't1', 'task_type': 'opt', 'status': 'pending', 'model_name': 'T1',
             'remote_dir': 'STAGE1/T1', 'dir_path': 'STAGE1/T1', 'input_state': {}}]}]}
        self.storage.save_db(self.db, backup=False)
        for file in (self.ledger.FILE, self.store.HISTORY_FILE, self.store.RUNS_FILE, self.store.AUTOMATION_FILE):
            file.unlink(missing_ok=True)
        self.store.save_settings({'enabled': True, 'dry_run': False, 'schedules_enabled': False})
        self.token, self.session = self.auth.create_session(self.agent, scope=['write'])
        self.grant = self.gateway.create_grant(self.owner, {
            'agent_username': 'agent', 'task_ids': ['t1'], 'allowed_actions': ['task.submit', 'task.continuation'],
            'queue': 'normal', 'limits': {'max_core_hours': 100, 'max_walltime_hours': 2, 'max_cores': 24},
        })
        with self.ledger.transaction() as doc:
            doc['enabled'] = True
        self.gateway.change_grant(self.owner, self.grant['id'], enabled=True)
        self.sync_patch = patch.object(self.jobs, '_schedule_input_sync')
        self.sync_patch.start()
        self.addCleanup(self.sync_patch.stop)

    def execute(self, **changes):
        args = dict(user=self.agent, session=self.session, grant_id=self.grant['id'], action='task.submit',
                    task_id='t1', idempotency_key='once')
        args.update(changes)
        return self.gateway.execute(**args)

    def test_normal_and_ten_identical_requests(self):
        first = self.execute()
        self.assertEqual(first['status'], 'succeeded')
        for _ in range(10):
            self.assertEqual(self.execute()['id'], first['id'])
        self.assertEqual(self.hpc.submit_count(), 1)
        self.assertEqual(self.ledger.get(first['id'])['reservation'], 24)

    def test_two_concurrent_workers_submit_once(self):
        def run():
            try:
                return self.execute()
            except self.scheduler._TaskBusy:
                return {'status': 'busy'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertGreaterEqual(sum(r['status'] == 'succeeded' for r in results), 1)
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_lost_bsub_response_reconcile_never_resubmits(self):
        self.hpc.install_bsub('lost')
        with self.assertRaises(self.jobs.ActionError):
            self.execute()
        record = list(self.ledger.read()['actions'].values())[0]
        self.assertEqual(record['status'], 'unknown')
        self.assertEqual(self.hpc.submit_count(), 1)
        self.assertEqual(self.execute()['id'], record['id'])
        self.assertEqual(self.ledger.read()['actions'][record['id']]['reservation'], 24)
        recovered = self.gateway.reconcile(record['id'])[0]
        self.assertEqual(recovered['job_id'], '230001')
        self.assertEqual(recovered['scheduler_state'], 'RUN')
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_unknown_cannot_use_new_key(self):
        self.hpc.install_bsub('lost')
        with self.assertRaises(self.jobs.ActionError): self.execute()
        self.hpc.set_jobs([])
        self.gateway.reconcile()
        with self.assertRaises(ValueError): self.execute(idempotency_key='another')
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_budget_limits_missing_and_invalid_resources(self):
        for field, value in [('max_core_hours', 23), ('max_cores', 23), ('max_walltime_hours', .5)]:
            with self.subTest(field=field):
                with self.ledger.transaction() as doc:
                    doc['grants'][self.grant['id']]['limits'][field] = value
                with self.assertRaises(ValueError): self.execute()
                with self.ledger.transaction() as doc:
                    doc['grants'][self.grant['id']]['limits'] = self.grant['limits']
        self.assertEqual(self.hpc.submit_count(), 0)
        for script in ('#BSUB -n 24\n', '#BSUB -n 24\n#BSUB -W 01:00\n#BSUB -q normal\n#BSUB -J jobs[1-9]\n'):
            (self.remote/'vasp.lsf').write_text(script)
            with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_dry_run_no_ledger_or_remote_changes(self):
        before = self.ledger.FILE.read_bytes()
        result = self.execute(dry_run=True)
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(self.ledger.FILE.read_bytes(), before)
        self.assertEqual(self.hpc.submit_count(), 0)
        self.store.save_settings({'dry_run': True})
        self.assertEqual(self.execute(dry_run=False)['status'], 'dry_run')
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_pause_revocation_and_cross_project_denied(self):
        self.gateway.change_grant(self.owner, self.grant['id'], enabled=False)
        with self.assertRaises(ValueError): self.execute()
        self.gateway.change_grant(self.owner, self.grant['id'], enabled=True)
        self.auth.delete_session(self.auth.session_key(self.session))
        with self.assertRaises(self.permissions.PermissionDenied): self.execute()
        with self.assertRaises(self.permissions.PermissionDenied): self.execute(user=self.other, session=None)
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_audit_and_storage_failure_before_execution(self):
        from automation import audit
        with patch.object(audit, 'write', side_effect=OSError('audit disk full')):
            with self.assertRaises(OSError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)
        self.ledger.FILE.unlink()
        with self.ledger.transaction() as doc:
            doc['enabled'] = True
            doc['grants'][self.grant['id']] = {**self.grant, 'enabled': True}
        with patch.object(self.ledger, 'write', side_effect=OSError('ledger disk full')):
            with self.assertRaises(OSError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_corrupt_ledger_fails_closed(self):
        self.ledger.FILE.write_text('{broken')
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_changed_idempotent_payload_rejected(self):
        self.execute()
        with self.assertRaises(ValueError): self.execute(action='task.continuation')
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_foreign_active_lsf_job_blocks_pending_task(self):
        self.hpc.set_jobs([['999', 'RUN', self.paths.remote_root('server1')+'/STAGE1/T1', 'other']])
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_finished_reservation_consumed_conservatively(self):
        record = self.execute()
        self.hpc.set_jobs([['230001', 'DONE', self.paths.remote_root('server1')+'/STAGE1/T1', record['execution_name']]])
        settled = self.gateway.reconcile(record['id'])[0]
        self.assertEqual(settled['reservation'], 0)
        self.assertEqual(settled['consumed_core_hours'], 24)
        self.assertEqual(settled['consumption_basis'], 'reserved_upper_bound')
        self.assertEqual(self.gateway.reconcile(record['id']), [])

    def _grant_limit(self, **limits):
        with self.ledger.transaction() as doc:
            doc['grants'][self.grant['id']]['limits'].update(limits)

    def test_active_jobs_and_submission_count_and_retry_limit(self):
        first = self.execute()
        # 同一项目第二个任务，验证预算并发上限不是仅靠任务锁。
        db = self.storage.load_db()
        t2 = copy.deepcopy(db['projects'][0]['tasks'][0])
        t2.update(task_id='t2', remote_dir='STAGE1/T2', dir_path='STAGE1/T2', status='pending', job_id=None)
        db['projects'][0]['tasks'].append(t2)
        self.storage.save_db(db, backup=False)
        self.hpc.write_inputs('STAGE1/T2', {'vasp.lsf': (self.remote/'vasp.lsf').read_text()})
        with self.ledger.transaction() as doc:
            grant = doc['grants'][self.grant['id']]
            grant['task_ids'].append('t2')
            grant['task_bindings']['t2'] = {'remote_dir': self.paths.remote_root('server1')+'/STAGE1/T2', 'task_type': 'opt'}
        with self.assertRaisesRegex(ValueError, '活跃'): self.execute(task_id='t2', idempotency_key='t2')
        self.hpc.set_jobs([['230001', 'DONE', self.paths.remote_root('server1')+'/STAGE1/T1', first['execution_name']]])
        self.gateway.reconcile(first['id'])
        self._grant_limit(max_submissions=1)
        with self.assertRaisesRegex(ValueError, '提交次数'): self.execute(task_id='t2', idempotency_key='t2')
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_explicit_reject_counts_toward_retry_limit(self):
        self.hpc.install_bsub('reject')
        for key in ('first', 'retry'):
            with self.assertRaises(self.jobs.ActionError): self.execute(idempotency_key=key)
        with self.assertRaisesRegex(ValueError, '尝试'): self.execute(idempotency_key='third')
        self.assertEqual(self.hpc.submit_count(), 2)
        self.assertTrue(all(r['reservation'] == 0 for r in self.ledger.read()['actions'].values()))

    def test_unknown_lsf_output_refuses_execution(self):
        os.environ['MOCK_BJOBS_ERROR'] = '1'
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_resource_change_after_preflight_prevents_bsub(self):
        original = self.jobs._core_submit
        def changed(project, task, **kwargs):
            if kwargs.get('execution'):
                (self.remote/'vasp.lsf').write_text('#BSUB -n 240\n#BSUB -W 10:00\n#BSUB -q normal\n')
            return original(project, task, **kwargs)
        with patch.object(self.jobs, '_core_submit', side_effect=changed):
            with self.assertRaises(self.jobs.ActionError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_restart_subprocess_recovers_job_without_replay(self):
        self.hpc.install_bsub('lost')
        with self.assertRaises(self.jobs.ActionError): self.execute()
        action_id = next(iter(self.ledger.read()['actions']))
        command = ('import sys;sys.path.insert(0,"backend");'
                   'from automation.gateway import reconcile;'
                   f'assert reconcile({action_id!r})[0]["job_id"]=="230001"')
        run = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_continuation_follow_up_uses_same_budget_and_child_lock(self):
        # 续算业务仍复用现有实现，模拟其远端复制+子任务登记接缝。
        def continuation(project, task):
            child = copy.deepcopy(task)
            child.update(task_id='child', parent_task_id='t1', dir_path='STAGE1/T1/con1', remote_dir='STAGE1/T1/con1')
            import shutil
            shutil.copytree(self.remote, self.remote/'con1', ignore=shutil.ignore_patterns('con1'))
            db = self.storage.load_db(); db['projects'][0]['tasks'].append(child); self.storage.save_db(db, backup=False)
            return {'action': 'created', 'task_id': 'child'}
        with patch.object(self.jobs, 'core_continuation', side_effect=continuation):
            result = self.execute(action='task.continuation', follow_up='task.submit')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.hpc.submit_count(), 1)
        self.assertEqual(len(self.ledger.read()['actions']), 1)
        self.assertEqual(result['reservation'], 24)
        lock = self.scheduler._acquire_task_lock('t1')
        try:
            with self.assertRaises(self.scheduler._TaskBusy): self.scheduler._acquire_task_lock('child')
        finally: self.scheduler._release_task_lock(lock)

    def test_approval_owner_claim_and_parameter_binding(self):
        import pending_actions
        pending_actions.STORE.unlink(missing_ok=True)
        item = pending_actions.create(action='task.submit', payload={'task_id': 't1', 'grant_id': self.grant['id']},
                                      reason='test', requested_by='agent', requested_kind='agent')
        with self.assertRaises(self.permissions.PermissionDenied): pending_actions.approve(item['id'], decided_by='other')
        approved = pending_actions.approve(item['id'], decided_by='owner')
        self.assertEqual(approved['status'], 'approved', approved)
        with self.assertRaises(ValueError): pending_actions.approve(item['id'], decided_by='owner')
        self.assertEqual(self.hpc.submit_count(), 1)
        item2 = pending_actions.create(action='task.submit', payload={'task_id': 't1', 'grant_id': self.grant['id']},
                                       reason='test', requested_by='agent', requested_kind='agent')
        doc = pending_actions._load(); doc['items'][-1]['payload']['follow_up'] = 'task.submit'; pending_actions._save(doc)
        with self.assertRaises(ValueError): pending_actions.approve(item2['id'], decided_by='owner')

    def test_full_app_auth_lifespan_and_no_agent_bypass(self):
        from mock_hpc import ApplicationClient
        import main
        from config import save_settings
        save_settings({'auto_inspection_enabled': False, 'auto_report_enabled': False})
        with ApplicationClient(main.app) as client:
            headers = {'Authorization': 'Bearer '+self.token}
            for path in ('/api/jobs/tasks/t1/submit', '/api/jobs/tasks/t1/continuation', '/api/jobs/tasks/t1/create-frac',
                         '/api/agent-execution/grants', '/api/agent-execution/settings'):
                self.assertEqual(client.post(path, headers=headers, json={}).status_code, 403, path)
            self.assertEqual(client.get('/api/ssh/config', headers=headers).status_code, 403)
            admin_token, _ = self.auth.create_session(self.admin)
            from routers import ssh as ssh_router
            with patch.object(ssh_router, 'load_servers', return_value={'fixture': {'password': 'fixture-secret'}}):
                public = client.get('/api/ssh/config', headers={'Authorization': 'Bearer '+admin_token})
            self.assertEqual(public.status_code, 200)
            self.assertNotIn('fixture-secret', public.text)
            self.assertTrue(public.json()['data']['servers'][0]['password_configured'])

            response = client.post('/api/agent-execution/actions', headers=headers, json={
                'grant_id': self.grant['id'], 'task_id': 't1', 'action': 'task.submit', 'idempotency_key': 'http',
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['data']['status'], 'succeeded')
            _, empty = self.auth.create_session(self.agent, scope=[])
            self.assertFalse(self.permissions.has_scope(empty, 'write'))
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_two_processes_same_request_never_duplicate(self):
        command = f'''
import sys
sys.path.insert(0, 'backend')
import auth
from automation import gateway, scheduler
from routers import jobs
jobs._schedule_input_sync = lambda *a: None
try:
    result=gateway.execute(user=auth.find_user('agent'), session=auth.get_session({self.session['session_id']!r}),
        grant_id={self.grant['id']!r}, action='task.submit', task_id='t1', idempotency_key='process')
    assert result['status']=='succeeded', result
except scheduler._TaskBusy:
    pass
'''
        workers = [subprocess.Popen([sys.executable, '-c', command], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in workers:
            _, error = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, error)
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_project_write_failure_after_bsub_retains_job_identity(self):
        from contextlib import contextmanager
        @contextmanager
        def failing_db():
            raise OSError('projects write failed')
            yield
        with patch.object(self.jobs, 'db_transaction', failing_db):
            with self.assertRaises(self.jobs.ActionError): self.execute()
        record = next(iter(self.ledger.read()['actions'].values()))
        self.assertEqual(record['status'], 'unknown')
        self.assertEqual(record['job_id'], '230001')
        self.assertEqual(self.hpc.submit_count(), 1)
        self.gateway.reconcile(record['id'])
        self.assertEqual(self.storage.load_db()['projects'][0]['tasks'][0]['job_id'], '230001')
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_pending_and_exit_lsf_states_and_wrong_marker(self):
        record = self.execute()
        root = self.paths.remote_root('server1')+'/STAGE1/T1'
        self.hpc.set_jobs([['230001', 'PEND', root, record['execution_name']]])
        self.assertEqual(self.gateway.reconcile(record['id'])[0]['scheduler_state'], 'PEND')
        self.hpc.set_jobs([['230001', 'EXIT', root, 'different-execution']])
        self.assertEqual(self.gateway.reconcile(record['id'])[0]['status'], 'unknown')
        self.hpc.set_jobs([['230001', 'EXIT', root, record['execution_name']]])
        self.assertTrue(self.gateway.reconcile(record['id'])[0]['job_finished'])
        # 调度器退出没有被当作VASP科学收敛。
        self.assertNotEqual(self.storage.load_db()['projects'][0]['tasks'][0]['status'], 'completed')

    def test_missing_budget_or_agent_grant_change_denied(self):
        for payload in ({}, {'max_cores': 24}, {'max_core_hours': float('nan'), 'max_cores': 24, 'max_walltime_hours': 1}):
            with self.assertRaises(ValueError): self.budget.limits(payload)
        base = '#BSUB -n 24\n#BSUB -W 01:00\n#BSUB -q normal\n'
        with self.assertRaises(ValueError): self.budget.parse_lsf(base + '#BSUB -R "affinity[core(8)]"\n')
        self.assertEqual(self.budget.parse_lsf(base + '#BSUB -R "span[ptile=24]"\n')['cores'], 24)
        with self.assertRaises(self.permissions.PermissionDenied):
            self.gateway.change_grant(self.agent, self.grant['id'], enabled=True)
        with self.ledger.transaction() as doc: doc['enabled'] = False
        with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_manual_takeover_and_pause_between_preflight_and_execute(self):
        from automation import audit
        audit.AUDIT_FILE.unlink(missing_ok=True)
        with patch.object(self.scheduler, '_manual_takeover', return_value='owner submitted manually'):
            with self.assertRaises(ValueError): self.execute()
        original = self.gateway.strict_audit
        def pause(record, status, reason=''):
            original(record, status, reason)
            if status == 'running': self.gateway.change_grant(self.owner, self.grant['id'], enabled=False)
        with patch.object(self.gateway, 'strict_audit', side_effect=pause):
            with self.assertRaises(ValueError): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_legacy_rule_cannot_bypass_managed_task(self):
        self.scheduler.start()
        result = self.scheduler.submit('task.submit', task_id='t1', wait=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_real_continuation_business_then_submit_in_mock_hpc(self):
        (self.remote/'CONTCAR').write_text((self.remote/'POSCAR').read_text())
        (self.remote/'OUTCAR').write_text('mock VASP output, optimization not yet converged\n')
        result = self.execute(action='task.continuation', follow_up='task.submit')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.hpc.submit_count(), 1)
        self.assertTrue((self.remote/'con1/POSCAR').is_file())
        self.assertEqual((self.remote/'con1/POSCAR').read_text(), (self.remote/'CONTCAR').read_text())
        child = self.storage.load_db()['projects'][0]['tasks'][-1]
        self.assertEqual(child['parent_task_id'], 't1')
        self.assertEqual(child['job_id'], '230001')
        self.assertEqual(result['reservation'], 24)

    def test_process_crash_after_bsub_before_ledger_completion(self):
        command = f'''
import sys,os
sys.path.insert(0,'backend')
import auth
from automation import gateway
from routers import jobs
jobs._schedule_input_sync=lambda *a:None
original=jobs._core_submit
def crash(project, task, **kw):
    result=original(project,task,**kw)
    if kw.get('execution'): os._exit(17)
    return result
jobs._core_submit=crash
gateway.execute(user=auth.find_user('agent'),session=auth.get_session({self.session['session_id']!r}),
    grant_id={self.grant['id']!r}, action='task.submit',task_id='t1',idempotency_key='crash')
'''
        process = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 17, process.stderr)
        record = next(iter(self.ledger.read()['actions'].values()))
        self.assertEqual(record['status'], 'running')
        recovered = self.gateway.reconcile(record['id'])[0]
        self.assertIn('interrupted', [e['status'] for e in recovered['events']])
        self.assertEqual(recovered['job_id'], '230001')
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_human_confirmation_can_release_unknown_but_agent_cannot(self):
        self.hpc.install_bsub('lost')
        with self.assertRaises(self.jobs.ActionError): self.execute()
        record = next(iter(self.ledger.read()['actions'].values()))
        evidence = '人工核实：已检查调度历史和远端目录，该次没有产生任何作业提交。'
        with self.assertRaises(self.permissions.PermissionDenied):
            self.gateway.resolve_not_submitted(self.agent, record['id'], evidence)
        with self.assertRaises(ValueError):
            self.gateway.resolve_not_submitted(self.owner, record['id'], evidence)
        self.hpc.set_jobs([])  # 模拟由人工外部核实；程序自身不会仅凭查不到自动解除。
        resolved = self.gateway.resolve_not_submitted(self.owner, record['id'], evidence)
        self.assertEqual(resolved['status'], 'failed')
        self.assertEqual(resolved['reservation'], 0)
        self.assertEqual(resolved['resolved_by'], 'owner')

    def test_concurrent_tasks_cannot_overreserve_shared_budget(self):
        db = self.storage.load_db()
        t2 = copy.deepcopy(db['projects'][0]['tasks'][0]);t2.update(task_id='t2', remote_dir='STAGE1/T2', dir_path='STAGE1/T2')
        db['projects'][0]['tasks'].append(t2);self.storage.save_db(db, backup=False)
        self.hpc.write_inputs('STAGE1/T2', {'vasp.lsf': (self.remote/'vasp.lsf').read_text()})
        with self.ledger.transaction() as doc:
            grant = doc['grants'][self.grant['id']];grant['task_ids'].append('t2')
            grant['task_bindings']['t2'] = {'remote_dir': self.paths.remote_root('server1')+'/STAGE1/T2', 'task_type': 'opt'}
            grant['limits'].update(max_active_jobs=2, max_core_hours=24)
        def submit(tid):
            try: return self.execute(task_id=tid, idempotency_key=tid)['status']
            except ValueError: return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, ['t1', 't2']))
        self.assertEqual(statuses.count('succeeded'), 1)
        self.assertEqual(self.hpc.submit_count(), 1)
        self.assertEqual(sum(a['reservation'] for a in self.ledger.read()['actions'].values()), 24)

    def test_global_dry_run_not_overridden_by_legacy_request(self):
        self.store.save_settings({'dry_run': True})
        result = self.scheduler.submit('task.submit', task_id='t1', dry_run=False)
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_abandoned_prepared_action_not_replayed(self):
        with self.ledger.transaction() as doc: doc['grants'] = {}
        record = self.gateway.prepare_legacy({'task_id': 't1', 'action': 'task.submit', 'run_id': 'queued-before-crash'})
        self.ledger.update(record['id'], owner_pid=0, owner_token=None)
        recovered = self.gateway.reconcile(record['id'])[0]
        self.assertEqual(recovered['status'], 'failed')
        self.assertFalse(recovered['attempted'])
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_event_id_deduplicates_same_event_not_future_schedule(self):
        from automation import events
        self.assertEqual(events._event_id({'run_id': 'inspection-1'}), 'inspection-1')
        first = events._event_id({'schedule_id': 'daily', 'fired_at': 'day1'})
        second = events._event_id({'schedule_id': 'daily', 'fired_at': 'day2'})
        self.assertNotEqual(first, second)

    def test_purged_lsf_history_needs_human_confirmation_of_finished_job(self):
        record = self.execute()
        self.hpc.set_jobs([])
        uncertain = self.gateway.reconcile(record['id'])[0]
        self.assertEqual(uncertain['status'], 'unknown')
        self.assertEqual(uncertain['reservation'], 24)
        evidence = '人工核实：已核对LSF归档日志和远端输出时间，原作业确实已结束。'
        with self.assertRaises(self.permissions.PermissionDenied):
            self.gateway.resolve_finished(self.agent, record['id'], evidence)
        resolved = self.gateway.resolve_finished(self.owner, record['id'], evidence)
        self.assertTrue(resolved['job_finished'])
        self.assertEqual(resolved['consumed_core_hours'], 24)
        self.assertEqual(resolved['reservation'], 0)
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_bsub_receives_immutable_budgeted_script(self):
        original = (self.remote/'vasp.lsf').read_text()
        with patch.dict(os.environ, {'MOCK_CHANGE_SCRIPT_ON_BSUB': '1'}):
            result = self.execute()
        received = (self.hpc.root/'_mock_bsub_stdin').read_text()
        self.assertEqual(received, original)
        self.assertIn('-n 240', (self.remote/'vasp.lsf').read_text())
        self.assertEqual(result['resources']['cores'], 24)
        self.assertEqual(self.hpc.submit_count(), 1)

    def test_short_action_run_visible_after_scheduler_restart(self):
        # 新受控动作也可通过旧管理员run查询接口读取，历史记录保留兼容。
        record = self.execute()
        visible = self.scheduler.get_run(record['id'])
        self.assertEqual(visible['status'], 'success')
        self.assertEqual(visible['result']['job_id'], '230001')
        self.assertTrue(any(r['run_id'] == record['id'] for r in self.scheduler.list_runs()))

    def test_inactive_new_grant_does_not_change_legacy_automation(self):
        grant = self.gateway.create_grant(self.owner, {
            'agent_username': 'agent', 'task_ids': ['t1'], 'allowed_actions': ['task.submit'], 'queue': 'normal',
            'limits': {'max_cores': 24, 'max_core_hours': 24, 'max_walltime_hours': 1},
        })
        self.assertFalse(grant['enabled'])
        self.assertFalse(grant['managed'])
        with self.ledger.transaction() as doc: doc['grants'] = {grant['id']: grant}
        record = self.gateway.prepare_legacy({'task_id': 't1', 'action': 'task.submit', 'run_id': 'unmanaged-rule'})
        self.assertTrue(record['legacy'])
        self.assertEqual(self.hpc.submit_count(), 0)

    def test_changed_server_or_task_target_invalidates_grant(self):
        with patch.object(self.gateway, 'load_servers', return_value={'server1': {'host': 'different-cluster'}}):
            with self.assertRaises(self.permissions.PermissionDenied): self.execute()
        db = self.storage.load_db();db['projects'][0]['tasks'][0]['remote_dir'] = 'STAGE1/elsewhere'
        self.storage.save_db(db, backup=False)
        with self.assertRaises(self.permissions.PermissionDenied): self.execute()
        self.assertEqual(self.hpc.submit_count(), 0)
