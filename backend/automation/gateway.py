"""阶段1受控执行入口：复用现有ActionSpec、任务锁、SSH与审计。"""
import base64
import copy
import re
import os
import shlex
from contextvars import ContextVar

import auth
import permissions
from automation import actions, audit, budget, ledger, store, unknown
from dates import now_iso
from config import load_servers
from paths import resolve_remote_path
from storage import db_transaction, update_task_status
from task_paths import is_continuation_task

_CONTEXT = ContextVar('controlled_execution', default=None)
ALLOWED = {'task.submit', 'task.continuation', 'frac.create'}


def family_id(task_id):
    # 同一任务族的父/续算子任务必须共用锁和UNKNOWN闸门。
    project, task = actions.load_task(task_id)
    seen = set()
    while is_continuation_task(task) and task.get('parent_task_id'):
        if task['task_id'] in seen:
            raise ValueError('任务父子关系成环')
        seen.add(task['task_id'])
        parent = next((t for t in project.get('tasks', []) if t['task_id'] == task['parent_task_id']), None)
        if parent is None:
            raise ValueError('续算父任务不存在')
        task = parent
    return str(task['task_id'])


def live_actor(user, session=None):
    current = auth.find_user((user or {}).get('username'))
    if not current or not current.get('enabled', True) or current.get('user_id') != (user or {}).get('user_id'):
        raise permissions.PermissionDenied('执行身份已失效')
    if session is not None:
        current_session = auth.get_session(auth.session_key(session))
        if not current_session or auth.is_expired(current_session) or current_session.get('user_id') != current['user_id']:
            raise permissions.PermissionDenied('执行授权token已吊销或过期')
        if current.get('role') == 'agent':
            # 老agent无scope会话按只读处理。
            if not current_session.get('scope'):
                raise permissions.PermissionDenied('agent未获得write scope')
            permissions.ensure_scope(current_session, 'write')
    elif current.get('role') == 'agent':
        raise permissions.PermissionDenied('agent执行必须带有效session')
    return current


def server_signature(server):
    config = load_servers().get(server, {})
    return ledger.fingerprint({key: config.get(key) for key in ('host', 'port', 'user', 'remote_base', 'queue_system', 'lsf_profile')})


def create_grant(user, payload):
    if (user or {}).get('role') == 'agent':
        raise permissions.PermissionDenied('agent不能授权或修改预算')
    tasks = payload.get('task_ids')
    if not isinstance(tasks, list) or not tasks or len(tasks) > 100:
        raise ValueError('必须显式指定1至100个任务')
    project = None
    bindings = {}
    for tid in tasks:
        p, task = actions.load_task(str(tid))
        permissions.ensure_project_owner(p, user)
        if project and p['name'] != project['name']:
            raise ValueError('一个授权只能对应同一项目')
        if is_continuation_task(task):
            raise ValueError('请授权原始任务，不单独授权续算子任务')
        project = p
        bindings[str(tid)] = {'remote_dir': resolve_remote_path(p['server'], task['remote_dir']).rstrip('/'), 'task_type': task.get('task_type')}
    agent = auth.find_user(payload.get('agent_username'))
    if not agent or agent.get('role') != 'agent' or not agent.get('enabled', True):
        raise ValueError('必须指定有效agent账号')
    permissions.ensure_project_owner(project, agent)
    allowed = payload.get('allowed_actions')
    if not isinstance(allowed, list) or not allowed or not set(allowed) <= ALLOWED:
        raise ValueError('必须显式指定动作白名单')
    queue = str(payload.get('queue') or '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', queue):
        raise ValueError('必须显式指定单个CPU队列')
    grant = {'id': ledger.new_id('grant'), 'project': project['name'], 'server': project['server'],
             'owner': project.get('owner'), 'task_ids': sorted(set(map(str, tasks))),
             'task_bindings': bindings, 'server_signature': server_signature(project['server']),
             'agent_username': permissions.username_of(agent), 'allowed_actions': allowed,
             'queue': queue, 'limits': budget.limits(payload.get('limits') or {}),
             'enabled': False, 'managed': False, 'revoked': False, 'created_by': permissions.username_of(user),
             'created_at': now_iso()}
    with ledger.transaction() as doc:
        doc['grants'][grant['id']] = grant
    return grant


def change_grant(user, grant_id, *, enabled):
    if (user or {}).get('role') == 'agent':
        raise permissions.PermissionDenied('agent不能改变授权、暂停状态或预算')
    with ledger.transaction() as doc:
        grant = doc['grants'].get(grant_id)
        if not grant:
            raise ValueError('授权不存在')
        project, _ = actions.load_task(grant['task_ids'][0])
        permissions.ensure_project_owner(project, user)
        if project.get('owner') != grant['owner']:
            raise permissions.PermissionDenied('项目归属已变化，需重新授权')
        grant['enabled'] = bool(enabled)
        if enabled:
            grant['managed'] = True
        grant['updated_at'] = now_iso()
    return copy.deepcopy(grant)


def check_grant(doc, grant_id, project, task, user, action):
    if not doc['enabled'] or not store.load_settings().get('enabled', True):
        raise ValueError('自主执行未开启或已暂停')
    grant = doc['grants'].get(grant_id)
    if not grant or not grant.get('enabled') or grant.get('revoked'):
        raise ValueError('授权未开启或已撤销')
    permissions.ensure_project_owner(project, user)
    if project['name'] != grant['project'] or project['server'] != grant['server'] or project.get('owner') != grant['owner']:
        raise permissions.PermissionDenied('项目/服务器/归属与授权不一致')
    if user.get('role') == 'agent' and permissions.username_of(user) != grant['agent_username']:
        raise permissions.PermissionDenied('授权不属于当前agent')
    family = family_id(task['task_id'])
    if family not in grant['task_ids'] or action not in grant['allowed_actions']:
        raise permissions.PermissionDenied('任务或动作不在授权白名单中')
    binding = (grant.get('task_bindings') or {}).get(family)
    root_task = next(t for t in project['tasks'] if t['task_id'] == family)
    root_dir = resolve_remote_path(project['server'], root_task['remote_dir']).rstrip('/')
    actual_dir = resolve_remote_path(project['server'], task['remote_dir']).rstrip('/')
    if (not binding or root_dir != binding['remote_dir'] or root_task.get('task_type') != binding['task_type']
            or server_signature(project['server']) != grant.get('server_signature')):
        raise permissions.PermissionDenied('服务器目标或任务目录/类型已变化，必须重新授权')
    if actual_dir != root_dir and not re.fullmatch(re.escape(root_dir) + r'/con[0-9]+', actual_dir):
        raise permissions.PermissionDenied('续算目录超出任务授权边界')
    return grant


def strict_audit(record, status, reason=''):
    return audit.write(action=record['action'], status=status, task_id=record['task_id'],
                       project=record['project'], username=record.get('actor', 'automation'),
                       trigger=record.get('trigger', 'agent'), trigger_id=record.get('trigger_id', ''),
                       run_id=record['id'], reason=reason, strict=True)


def execution_context():
    return _CONTEXT.get()


def _record(project, task, action, actor, **fields):
    aid = ledger.new_id()
    return {'id': aid, 'task_id': task['task_id'], 'family_id': family_id(task['task_id']),
            'project': project['name'], 'server': project['server'], 'action': action, 'actor': actor,
            'status': 'prepared', 'owner_pid': os.getpid(), 'owner_token': ledger.process_token(os.getpid()), 'created_at': now_iso(), 'updated_at': now_iso(), 'events': [],
            'execution_name': re.sub(r'[^A-Za-z0-9_.-]', '_', str(task.get('model_name') or 'task'))[:48] + '_vm_' + aid[4:], 'reservation': 0, 'attempted': False,
            'submission_attempted': False, **fields}


def _unresolved(doc, family, exclude=None):
    return next((a for a in doc['actions'].values() if a['family_id'] == family and a['id'] != exclude
                 and (a['status'] in ledger.UNRESOLVED or a.get('reservation', 0) > 0 or (a.get('job_id') and not a.get('job_finished')))), None)


def snapshot_plan(project, task):
    # 现有preflight增加只读脚本/指纹，执行时固定该目录并再次比对。
    return actions._jobs()._core_submit(project, task, dry_run=True)


def assert_remote_idle(project, task, directory, rows):
    candidates = {str(t.get('job_id')) for t in project.get('tasks', [])
                  if family_id(t['task_id']) == family_id(task['task_id']) and t.get('job_id')}
    for row in rows:
        if row['state'] not in unknown.TERMINAL and row['directory'] in {'', '-'}:
            raise ValueError('LSF活跃作业目录未知，不能确认无冲突')
        if row['job_id'] in candidates or row['directory'].rstrip('/') == directory.rstrip('/'):
            if row['state'] not in unknown.TERMINAL:
                raise ValueError('LSF仍有活跃或未知作业，禁止新动作')
    job_id = str(task.get('job_id') or '')
    if job_id and not any(r['job_id'] == job_id and r['state'] in unknown.TERMINAL for r in rows):
        raise ValueError('原作业无法在LSF确认结束，暂停并要求人工核实')
    if not job_id and task.get('status') not in {'pending', 'completed', 'unconverged'}:
        raise ValueError('缺少可信作业身份，不能自动重试')


def execute(*, user, session, grant_id, action, task_id, idempotency_key, params=None,
            follow_up=None, dry_run=False, trigger='agent', trigger_id='', opt_run_id=None):
    from automation import scheduler
    params = dict(params or {})
    if set(params) - {'task_id'} or (params.get('task_id') and params['task_id'] != task_id):
        raise ValueError('阶段1不允许任意参数或结构修改')
    if action not in ALLOWED or follow_up not in (None, 'task.submit') or (follow_up and action != 'task.continuation'):
        raise ValueError('动作链不在白名单中')
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
        raise ValueError('必须提供1至128字符Idempotency-Key')
    actor = live_actor(user, session)
    project, task = actions.load_task(task_id)
    permissions.ensure_project_owner(project, actor)
    family = family_id(task_id)
    key = ledger.fingerprint([grant_id, idempotency_key])
    signature = ledger.fingerprint([task_id, action, params, follow_up])
    # 新动作到来时先只读对账授权内旧作业；不增加后台轮询或自动重放。
    current = ledger.read()
    check_grant(current, grant_id, project, task, actor, action)
    if not dry_run and not store.load_settings().get('dry_run', False) and not any(a.get('idempotency') == key for a in current['actions'].values()):
        for previous in list(current['actions'].values()):
            if previous.get('grant_id') == grant_id and not previous.get('job_finished'):
                reconcile(previous['id'])
    lock = scheduler._acquire_task_lock(family)
    record = None
    try:
        actor = live_actor(user, session)
        project, task = actions.load_task(task_id)
        with ledger.transaction() as doc:
            grant = check_grant(doc, grant_id, project, task, actor, action)
            if follow_up and follow_up not in grant['allowed_actions']:
                raise permissions.PermissionDenied('后续提交未获授权')
            previous = next((a for a in doc['actions'].values() if a.get('idempotency') == key), None)
            if previous:
                if previous.get('signature') != signature:
                    raise ValueError('同一幂等键的动作参数已变化')
                return copy.deepcopy(previous)
            if not opt_run_id and any(r['task_id'] == family and r['status'] != 'FINISHED' for r in doc.get('opt_runs', {}).values()):
                raise ValueError('任务已由OPT循环托管（含暂停）；禁止绕过科学检查，需人工结束循环后重新授权处置')
            if _unresolved(doc, family):
                raise ValueError('任务族已有活跃或未对账动作，禁止重放')
        takeover = scheduler._manual_takeover(family)
        if takeover:
            raise ValueError('近期有人工作业操作，暂停自动执行：' + takeover)
        repair_snapshot = None
        if opt_run_id:
            from automation import opt_loop
            run = opt_loop.get(opt_run_id)
            if run['grant_id'] != grant_id or trigger != 'opt_loop':
                raise ValueError('OPT授权/触发来源不一致')
            repair_snapshot = opt_loop.prepare_action(opt_run_id, actor, project, task, action, trigger_id)
        spec = actions.get(action)
        preflight = spec.preflight(task_id, params)
        submitting = action == 'task.submit' or bool(follow_up)
        planning_task = task
        if repair_snapshot and action == 'task.continuation':
            # OPT已在锁内交叉验证当前远端作业结束；本地状态可能尚未同步。
            # 只修正只读preflight视图，不把数据库状态冒充科学收敛。
            planning_task = {**task, 'status':'unconverged'}
        plan = snapshot_plan(project, planning_task)
        rows = unknown.jobs(project['server'])
        directory = plan['work_dir']
        assert_remote_idle(project, task, directory, rows)
        resources = budget.parse_lsf(plan['script_text']) if submitting else None
        with ledger.transaction() as doc:
            actor = live_actor(user, session)
            project, task = actions.load_task(task_id)
            grant = check_grant(doc, grant_id, project, task, actor, action)
            reservation = budget.reserve_check(doc, grant, resources, family_id=family, action=action, submitting=submitting)
            if dry_run or store.load_settings().get('dry_run', False):
                return {'status': 'dry_run', 'preflight': preflight, 'resources': resources, 'will_reserve': reservation}
            # 最后一次检查：锁覆盖所有实际执行，账本锁同时覆盖预算和动作创建。
            if _unresolved(doc, family):
                raise ValueError('任务存在未对账动作')
            record = _record(project, task, action, permissions.username_of(actor),
                             grant_id=grant_id, idempotency=key, signature=signature, params=params,
                             follow_up=follow_up, resources=resources, reservation=reservation,
                             plan=plan, trigger=trigger, trigger_id=trigger_id,
                             repair_snapshot=repair_snapshot,
                             session_id=auth.session_key(session) if session else None)
            doc['actions'][record['id']] = record
        strict_audit(record, 'running', '已持久化动作与预算，准备执行')
        # 复核暂停/权限/token，随后将attempt标记写入磁盘，才可产生副作用。
        actor = live_actor(user, session)
        with ledger.transaction() as doc:
            check_grant(doc, grant_id, *actions.load_task(task_id), actor, action)
            doc['actions'][record['id']].update(status='running', attempted=True, updated_at=now_iso())
        token = _CONTEXT.set(record['id'])
        try:
            if repair_snapshot:
                # 快照和预算先落盘；只应用已验证的NSW草稿，续算仍复用原入口。
                from automation import opt_loop
                opt_loop.prepare_action(opt_run_id, actor, *actions.load_task(task_id), action, trigger_id)
                opt_loop.apply_draft(repair_snapshot, task_id)
            result = spec.execute(task_id, params)
            if action == 'task.continuation' and result.get('action') != 'created':
                return ledger.update(record['id'], status='skipped', result=result, reservation=0)
            if follow_up:
                child_id = str(result['task_id'])
                ledger.update(record['id'], continuation_task_id=child_id)
                # 后续submit继承同一授权/预算/台账和父任务族锁，不重新排一个无预算动作。
                actor = live_actor(user, session)
                with ledger.transaction() as doc:
                    check_grant(doc, grant_id, *actions.load_task(child_id), actor, 'task.submit')
                result = {'continuation': result, 'submit': actions.get('task.submit').execute(child_id, {})}
            current = ledger.get(record['id'])
            record = ledger.update(record['id'], status='succeeded', result=result,
                                   reservation=current['reservation'] if submitting else 0)
            strict_audit(record, 'success', '动作完成；计算结果仍需巡检验证')
            return record
        finally:
            _CONTEXT.reset(token)
    except Exception as exc:
        if record:
            current = ledger.get(record['id'])
            if current and current['status'] in {'prepared', 'running'}:
                # 只要进入业务副作用区，就保守保留UNKNOWN。preflight/审计失败不执行。
                uncertain = current.get('attempted', False)
                current = ledger.update(record['id'], status='unknown' if uncertain else 'failed',
                                        reason=str(exc), reservation=current['reservation'] if uncertain else 0)
                try:
                    strict_audit(current, current['status'], str(exc))
                except OSError:
                    pass  # 台账已持久化，不掩盖原始异常，也不重放。
        raise
    finally:
        scheduler._release_task_lock(lock)


def safe_submit(project, task, *, dry_run=False):
    """所有既有提交路径共用的安全接缝；普通人工操作不要求Agent预算。"""
    core = actions._jobs()._core_submit
    if dry_run:
        return core(project, task, dry_run=True)
    controlled = _CONTEXT.get()
    family = family_id(task['task_id'])
    # HTTP/调度器外层已持有同一任务族锁。core_submit内部调用也有台账闸门。
    if controlled:
        record = ledger.get(controlled)
        if record.get('repair_snapshot'):
            from automation import opt_loop
            if opt_loop.get(record['repair_snapshot']['run_id'])['status'] != 'ACTING':
                raise ValueError('OPT循环已暂停，禁止提交后续作业')
            opt_loop.verify_submission(record, project, task)
        plan = snapshot_plan(project, task)
        if record.get('grant_id'):
            resources = budget.parse_lsf(plan['script_text'])
            if resources != record['resources']:
                raise ValueError('续算后LSF资源与预算预留不一致，禁止提交')
            current_actor = auth.find_user(record['actor'])
            current_session = auth.get_session(record['session_id']) if record.get('session_id') else None
            current_actor = live_actor(current_actor, current_session)
            check_grant(ledger.read(), record['grant_id'], project, task, current_actor, 'task.submit')
            if store.load_settings().get('dry_run', False):
                raise ValueError('全局dry_run已开启')
        else:
            assert_remote_idle(project, task, plan['work_dir'], unknown.jobs(project['server']))
    else:
        with ledger.transaction() as doc:
            if _unresolved(doc, family):
                raise ValueError('任务族存在活跃/UNKNOWN提交记录，请先对账')
            record = _record(project, task, 'task.submit', permissions.context_username() or 'automation')
            doc['actions'][record['id']] = record
        try:
            strict_audit(record, 'running', '提交前记录，防止响应丢失后重复提交')
            plan = snapshot_plan(project, task)
            assert_remote_idle(project, task, plan['work_dir'], unknown.jobs(project['server']))
        except Exception:
            ledger.update(record['id'], status='failed', reservation=0)
            raise
    ledger.update(record['id'], plan=plan, status='running', attempted=True, submission_attempted=True)
    try:
        result = core(project, task, execution={**plan, 'execution_name': record['execution_name']})
    except Exception as exc:
        data = getattr(exc, 'data', {})
        rejected = bool(data.get('not_submitted') or (data.get('bsub_rc') and str(data['bsub_rc']) != '0'))
        # 只有明确的非零bsub退出码才释放预留；空输出/超时/写库失败仍为UNKNOWN。
        ledger.update(record['id'], status='failed' if rejected else 'unknown', reason=str(exc),
                      job_id=data.get('job_id'), reservation=0 if rejected else record.get('reservation', 0))
        if hasattr(exc, 'data'):
            exc.data = {**data, 'action_id': record['id'], 'execution_status': 'failed' if rejected else 'unknown'}
        raise
    job_id = result.get('job_id')
    # 记录早于后续审计、项目库错误及HTTP响应。
    ledger.update(record['id'], status='succeeded', job_id=job_id, result=result)
    if not controlled:
        strict_audit(record, 'success', f'已提交作业 {job_id}')
    return result


def reconcile(action_id=None):
    """只查询/绑定已有作业，绝不调用execute或bsub。启动和显式请求共用。"""
    from automation import scheduler
    results = []
    for record in list(ledger.read()['actions'].values()):
        if action_id and record['id'] != action_id:
            continue
        if record.get('job_finished') or (record['status'] not in ledger.UNRESOLVED and not record.get('job_id')):
            continue
        if record['status'] in {'prepared', 'running'} and ledger.owner_alive(record):
            continue
        try:
            lock = scheduler._acquire_task_lock(record['family_id'])
        except scheduler._TaskBusy:
            continue
        try:
            record = ledger.get(record['id'])
            if not record.get('attempted'):
                results.append(ledger.update(record['id'], status='failed', reservation=0, reason='执行前中断，没有产生远端动作'))
                continue
            if record['status'] in {'prepared', 'running'}:
                record = ledger.update(record['id'], status='interrupted', reason='原执行进程已退出，先对账，不重放')
            match = unknown.find(record, unknown.jobs(record['server']))
            if not match:
                results.append(ledger.update(record['id'], status='unknown', reason='LSF未能唯一识别作业，暂停并要求人工核实'))
                continue
            if match['state'] not in unknown.ACTIVE | unknown.TERMINAL:
                results.append(ledger.update(record['id'], status='unknown', reason='LSF状态未知'))
                continue
            project, task = actions.load_task(record.get('continuation_task_id') or record['task_id'])
            with db_transaction() as db:
                current_task = next(t for p in db['projects'] if p['name'] == project['name']
                                    for t in p['tasks'] if t['task_id'] == task['task_id'])
                status = current_task['status']
                if match['state'] in unknown.ACTIVE and status != 'archived':
                    status = 'queued' if match['state'] == 'PEND' else 'running'
                update_task_status(db, project['name'], task['task_id'], status, {'job_id': match['job_id']})
            fields = {'status': 'succeeded', 'job_id': match['job_id'], 'scheduler_state': match['state']}
            if match['state'] in unknown.TERMINAL:
                # LSF未提供可信实际核时：采用申请上界计入消耗，不伪装实际计费。
                fields.update(reservation=0, consumed_core_hours=record.get('reservation', 0) + record.get('consumed_core_hours', 0),
                              consumption_basis='reserved_upper_bound', job_finished=True)
            results.append(ledger.update(record['id'], **fields))
            strict_audit(record, 'success', '只读LSF对账：' + match['state'])
        except Exception as exc:
            results.append(ledger.update(record['id'], status='unknown', reason='对账失败：' + str(exc)))
        finally:
            scheduler._release_task_lock(lock)
    return results


def prepare_legacy(job):
    """为已有规则建立可恢复记录；不授予预算或新增自动权限。"""
    project, task = actions.load_task(job['task_id'])
    record = _record(project, task, job['action'], 'automation', trigger=job.get('trigger', ''),
                     trigger_id=job.get('trigger_id', ''), params=job.get('params') or {}, legacy=True)
    record['id'] = job['run_id']
    record['idempotency'] = job.get('fingerprint') or None
    with ledger.transaction() as doc:
        # 已授权Agent任务只能走受控入口，旧规则不能成为同一任务的预算旁路。
        if any(g.get('managed') and record['family_id'] in g['task_ids'] for g in doc['grants'].values()):
            raise ValueError('该任务已纳入受控授权，请经Agent执行入口操作')
        if record['idempotency'] and any(a.get('idempotency') == record['idempotency'] for a in doc['actions'].values()):
            raise ValueError('动作事件/幂等键已处理，不重复入队')
        if _unresolved(doc, record['family_id']):
            raise ValueError('已有未完成/UNKNOWN动作，请先对账')
        doc['actions'][record['id']] = record
    return record


def resolve_not_submitted(user, action_id, evidence):
    """仅人工在外部核实后解除UNKNOWN；无自动“查不到就失败”的降级。"""
    from automation import scheduler
    if not user or user.get('role') == 'agent':
        raise permissions.PermissionDenied('需要人工确认')
    if not isinstance(evidence, str) or len(evidence.strip()) < 20:
        raise ValueError('必须记录至少20字的人工核实依据（如LSF历史和远端目录核对）')
    record = ledger.get(action_id)
    if not record:
        raise ValueError('动作不存在')
    project, _ = actions.load_task(record['task_id'])
    permissions.ensure_project_owner(project, user)
    lock = scheduler._acquire_task_lock(record['family_id'])
    try:
        record = ledger.get(action_id)
        if record['status'] not in {'unknown', 'interrupted'} or record.get('job_id'):
            raise ValueError('只允许解除没有作业ID的UNKNOWN动作；已有作业请继续对账')
        rows = unknown.jobs(record['server'])
        if unknown.find(record, rows):
            raise ValueError('LSF仍能识别该动作，请对账绑定作业，不得解除')
        directory = (record.get('plan') or {}).get('work_dir')
        if any(r['state'] not in unknown.TERMINAL and r['directory'] in {directory, '', '-'} for r in rows):
            raise ValueError('仍有活跃/未知作业，不能解除')
        strict_audit({**record, 'actor': permissions.username_of(user), 'trigger': 'human_resolution'}, 'resolved_not_submitted', '人工核实：' + evidence.strip())
        return ledger.update(action_id, status='failed', reservation=0, job_finished=True,
                             resolved_by=permissions.username_of(user), resolution_evidence=evidence.strip(),
                             reason='人工确认没有产生提交；允许在剩余次数/预算内重新提案')
    finally:
        scheduler._release_task_lock(lock)


def resolve_finished(user, action_id, evidence):
    """LSF历史被清理后，只能由人工核实已结束；核时仍按申请上界记账。"""
    from automation import scheduler
    if not user or user.get('role') == 'agent':
        raise permissions.PermissionDenied('需要人工确认')
    if not isinstance(evidence, str) or len(evidence.strip()) < 20:
        raise ValueError('必须记录至少20字的人工核实依据')
    record = ledger.get(action_id)
    if not record:
        raise ValueError('动作不存在')
    project, _ = actions.load_task(record['task_id'])
    permissions.ensure_project_owner(project, user)
    lock = scheduler._acquire_task_lock(record['family_id'])
    try:
        record = ledger.get(action_id)
        if not record.get('job_id') or record.get('job_finished'):
            raise ValueError('仅用于已知job_id但未能自动确认结束的动作')
        rows = unknown.jobs(record['server'])
        match = unknown.find(record, rows)
        directory = (record.get('plan') or {}).get('work_dir')
        if (match and match['state'] not in unknown.TERMINAL) or any(
                row['state'] not in unknown.TERMINAL and (row['job_id'] == record['job_id'] or row['directory'] in {directory, '', '-'})
                for row in rows):
            raise ValueError('LSF仍显示活跃/未知作业，不能确认结束')
        strict_audit({**record, 'actor': permissions.username_of(user), 'trigger': 'human_resolution'}, 'human_confirmed_finished', evidence.strip())
        return ledger.update(action_id, status='succeeded', job_finished=True,
                             consumed_core_hours=record.get('reservation', 0) + record.get('consumed_core_hours', 0),
                             reservation=0, consumption_basis='reserved_upper_bound',
                             resolved_by=permissions.username_of(user), resolution_evidence=evidence.strip(),
                             reason='人工确认调度作业已结束；不代表VASP收敛或科学通过')
    finally:
        scheduler._release_task_lock(lock)
