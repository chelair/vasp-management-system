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
            'submission_attempted': False, 'source_binding': _completion_binding(project, task, job_id=''), **fields}


def _unresolved(doc, family, exclude=None, directory=None, in_flight_only=False):
    """同族里尚未收尾的动作；给了 directory 时只拦同一作业目录。

    2026-10-21 用户口径：并发冲突只认“同一目录”，root 运行中不应阻止 conN 续算。
    `in_flight_only=True` 时只看“提交正在进行中”（prepared/running），
    不再把历史 UNKNOWN / 旧作业号当作人工复核门槛（用户无法人工复核）。
    """
    target = str(directory or '').rstrip('/')
    for action in doc['actions'].values():
        if action['family_id'] != family or action['id'] == exclude:
            continue
        if target:
            work_dir = str((action.get('plan') or {}).get('work_dir') or '').rstrip('/')
            if work_dir and work_dir != target:
                continue
        if action.get('released'):
            continue
        if in_flight_only:
            if action['status'] in {'prepared', 'running'}:
                return action
            continue
        if (action['status'] in ledger.UNRESOLVED or action.get('reservation', 0) > 0
                or (action.get('job_id') and not action.get('job_finished'))):
            return action
    return None


def snapshot_plan(project, task):
    # 现有preflight增加只读脚本/指纹，执行时固定该目录并再次比对。
    return actions._jobs()._core_submit(project, task, dry_run=True)


def _completion_binding(project, task, job_id=None):
    family = family_id(task['task_id'])
    root = next(t for t in project['tasks'] if t['task_id'] == family)
    return {'family_id': family, 'project': project['name'], 'owner': project.get('owner'),
            'server': project['server'], 'server_signature': server_signature(project['server']),
            'root_directory': resolve_remote_path(project['server'], root['remote_dir']).rstrip('/'),
            'job_id': str(job_id if job_id is not None else task.get('job_id') or '')}


def _confirmed_finished(binding):
    return next((a for a in ledger.read()['actions'].values()
                 if a.get('job_finished') and a.get('resolved_by') and a.get('resolution_evidence')
                 and a.get('finished_confirmation') == binding), None)


def _receipt_confirmation_summary(binding, receipts):
    """Suggested human attestation only. Never used to authorize execution by itself."""
    for receipt in receipts:
        text = receipt.get('text', '')
        subject = re.search(r'^Subject: Job ' + re.escape(binding['job_id']) + r': .* (Done|Exited)\s*$', text, re.M)
        ended = re.search(r'^Terminated at (.+)$', text, re.M)
        cwd = re.search(r'^<([^\n]+)> was used as the working directory\.', text, re.M)
        if subject and ended and cwd and cwd[1].rstrip('/') == receipt.get('directory', '').rstrip('/'):
            return (f"用户在报错窗口确认：旧作业{binding['job_id']}的LSF回执状态为{subject[1]}，"
                    f"工作目录{cwd[1]}，结束时间{ended[1]}。已核对本次LSF查询未发现任务族活跃作业；"
                    '仅确认旧调度作业结束，不认定VASP收敛，不自动提交新作业。')
    return ''


def assert_remote_idle(project, task, directory, rows, *, allow_unconfirmed=False):
    """唯一的并发约束：同一作业目录（精确匹配，不含子目录）不能同时运行两个作业。

    2026-10-21 用户口径：不再按任务族（root / conN）扩散，也不要求旧作业身份先确认，
    只看 bjobs 的 exec_cwd 是否等于本次目标目录。`allow_unconfirmed` 仅为调用方兼容保留。
    """
    target = str(directory or '').rstrip('/')
    if not target:
        raise ValueError('缺少目标作业目录，无法确认并发冲突')
    for row in rows:
        if row['state'] in unknown.TERMINAL:
            continue
        cwd = str(row.get('directory') or '').rstrip('/')
        if cwd and cwd == target:
            raise ValueError(
                f"目录 {target} 已有活跃作业（{row['job_id']} {row['state']}）；"
                '同一作业目录下不能同时运行两个作业'
            )


def active_job_in(directory, rows):
    """返回目标目录（精确匹配）里的活跃作业行；没有就返回 None。"""
    target = str(directory or '').rstrip('/')
    for row in rows:
        if row['state'] in unknown.TERMINAL:
            continue
        cwd = str(row.get('directory') or '').rstrip('/')
        if cwd and cwd == target:
            return row
    return None


def sync_running_from_lsf(project, task, row):
    """提交前发现同目录仍有活跃作业：把本地任务同步回运行中，界面即可禁止再次提交。

    作业号按任务族登记在主任务上（与提交/对账同一口径）。
    """
    owner_id = family_id(task['task_id'])
    status = 'queued' if row['state'] == 'PEND' else 'running'
    with db_transaction() as db:
        current = next(t for p in db['projects'] if p['name'] == project['name']
                       for t in p['tasks'] if t['task_id'] == owner_id)
        if current.get('status') == 'archived':
            return False
        update_task_status(db, project['name'], owner_id, status,
                           {'job_id': str(row['job_id']), 'stop_requested_at': None, 'stop_requested_job_id': None})
    return True


def check_idle_or_sync(project, task, directory, rows):
    """提交前的目录互斥检查；命中活跃作业时先同步本地状态，再拒绝提交。"""
    row = active_job_in(directory, rows)
    if row is None:
        return
    synced = False
    try:
        synced = sync_running_from_lsf(project, task, row)
    except Exception:  # noqa: BLE001 - 同步失败不改变拒绝提交的事实
        synced = False
    state = '排队中' if row['state'] == 'PEND' else '运行中'
    raise ValueError(
        f"目录 {str(directory or '').rstrip('/')} 仍有活跃作业（{row['job_id']} {row['state']}）"
        + (f"，已把任务同步为{state}" if synced else '')
        + '；请先停止作业再提交'
    )


def prior_job_review(user, task_id):
    project, task = actions.load_task(task_id)
    permissions.ensure_project_owner(project, user)
    binding = _completion_binding(project, task)
    rows = unknown.jobs(project['server'])  # A failed query never becomes an empty queue.
    blocker = ''
    try:
        assert_remote_idle(project, task, binding['root_directory'], rows, allow_unconfirmed=True)
    except ValueError as exc:
        blocker = str(exc)
    unresolved = _unresolved(ledger.read(), binding['family_id'])
    if unresolved:
        blocker = '任务族有未完成/UNKNOWN动作，请先对账原动作：' + unresolved['id']
    matches = [r for r in rows if r['job_id'] == binding['job_id']]
    confirmation = _confirmed_finished(binding)
    receipts, receipt_error = [], ''
    if binding['job_id']:
        try:
            receipts = unknown.prior_job_receipts(project['server'], binding['root_directory'], binding['job_id'])
        except (ValueError, OSError) as exc:
            receipt_error = str(exc)
    return {'task_id': task_id, 'job_id': binding['job_id'], 'server': project['server'],
            'directory': binding['root_directory'], 'checked_at': now_iso(),
            'review_fingerprint': ledger.fingerprint(binding),
            'lsf_status': matches[0]['state'] if matches else 'NOT_FOUND',
            'already_confirmed': bool(confirmation), 'blocker': blocker,
            'receipts': receipts, 'receipt_error': receipt_error,
            'confirmation_summary': _receipt_confirmation_summary(binding, receipts),
            'can_confirm': bool(binding['job_id'] and not matches and not blocker and not confirmation),
            'note': 'LSF查不到不代表已结束。请人工核对旧作业回执、工作目录及结束时间；确认只解除该旧作业身份阻塞，不提交作业，也不认定VASP收敛。'}


def confirm_prior_job_finished(user, task_id, expected_job_id, review_fingerprint, evidence):
    """Explicit human resolution for a pre-ledger job; no remote mutation or resubmission."""
    from automation import scheduler
    if not user or user.get('role') == 'agent':
        raise permissions.PermissionDenied('需要人工确认，Agent不能解除旧作业身份阻塞')
    if not isinstance(evidence, str) or not 20 <= len(evidence.strip()) <= 4000:
        raise ValueError('请填写20至4000字的人工核实依据（作业回执、目录与结束时间）')
    project, task = actions.load_task(task_id)
    permissions.ensure_project_owner(project, user)
    lock = scheduler._acquire_task_lock(family_id(task_id))
    try:
        review = prior_job_review(user, task_id)
        if not expected_job_id or str(expected_job_id) != review['job_id'] or review_fingerprint != review['review_fingerprint']:
            raise ValueError('作业身份或服务器/目录已变化，请重新核实')
        if not review['can_confirm']:
            raise ValueError(review['blocker'] or '当前无需或不能人工确认，请重新核对LSF状态')
        project, task = actions.load_task(task_id)
        binding = _completion_binding(project, task)
        if ledger.fingerprint(binding) != review_fingerprint:
            raise ValueError('作业身份发生变化，请重新核实')
        record = _record(project, task, 'task.prior_job_confirmation', permissions.username_of(user),
                         status='succeeded', job_id=review['job_id'], job_finished=True,
                         resolved_by=permissions.username_of(user), resolution_evidence=evidence.strip(),
                         finished_confirmation=binding, trigger='human_resolution',
                         reason='人工确认旧调度作业已结束；未提交作业，不代表VASP收敛')
        strict_audit(record, 'human_confirmed_finished', evidence.strip())
        with ledger.transaction() as doc:
            doc['actions'][record['id']] = record
        return {'action_id': record['id'], 'job_id': review['job_id'], 'job_finished': True,
                'message': record['reason']}
    finally:
        scheduler._release_task_lock(lock)


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
        check_idle_or_sync(project, task, directory, rows)
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
            check_idle_or_sync(project, task, plan['work_dir'], unknown.jobs(project['server']))
    else:
        # 调用方已持有任务族锁；只读核实历史记录，不重放提交。
        reconcile(task_id=task['task_id'], _lock_held=True)
        project, task = actions.load_task(task['task_id'])
        target_dir = resolve_remote_path(project['server'], task.get('remote_dir') or '').rstrip('/')
        with ledger.transaction() as doc:
            # 只拦“另一个提交正在进行中”，历史 UNKNOWN/旧作业号不再要求人工复核；
            # 同目录的真实并发由提交前的实时 bjobs 检查负责。
            if _unresolved(doc, family, directory=target_dir, in_flight_only=True):
                raise ValueError('该作业目录有一个正在进行的提交，请稍候再试')
            record = _record(project, task, 'task.submit', permissions.context_username() or 'automation')
            doc['actions'][record['id']] = record
        try:
            strict_audit(record, 'running', '提交前记录，防止响应丢失后重复提交')
            plan = snapshot_plan(project, task)
            check_idle_or_sync(project, task, plan['work_dir'], unknown.jobs(project['server']))
        except Exception as exc:
            ledger.update(record['id'], status='failed', reservation=0, reason=str(exc))
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


def _verify_record_source(record, project, task):
    binding = _completion_binding(project, task, job_id='')
    if record.get('project') != project['name'] or record.get('server') != project['server']:
        raise ValueError('作业来源项目/服务器已变化，需人工核实')
    if record.get('source_binding') and record['source_binding'] != binding:
        raise ValueError('作业来源绑定已变化，需人工核实')
    directory = (record.get('plan') or {}).get('work_dir', '').rstrip('/')
    root = binding['root_directory']
    if directory and directory != root and not re.fullmatch(re.escape(root) + r'/con[0-9]+', directory):
        raise ValueError('作业目录与任务族不符，需人工核实')


def reconcile(action_id=None, *, task_id=None, _lock_held=False, _rows=None):
    """只查询已有作业；支持锁内提交/停止及巡检事件复用，不重放远端动作。"""
    from automation import scheduler
    results = []
    family = family_id(task_id) if task_id else None
    rows_by_server = {} if _rows is None else dict(_rows)
    for record in list(ledger.read()['actions'].values()):
        if action_id and record['id'] != action_id:
            continue
        if family and record['family_id'] != family:
            continue
        if (record.get('job_finished') and not record.get('sync_error')) or (record['status'] not in ledger.UNRESOLVED and not record.get('job_id')):
            continue
        if record['status'] in {'prepared', 'running'} and ledger.owner_alive(record):
            continue
        lock = None
        try:
            if not _lock_held:
                lock = scheduler._acquire_task_lock(record['family_id'])
        except scheduler._TaskBusy:
            continue
        try:
            record = ledger.get(record['id'])
            if record.get('job_finished') and not record.get('sync_error'):
                continue
            if not record.get('attempted'):
                results.append(ledger.update(record['id'], status='failed', reservation=0, reason='执行前中断，没有产生远端动作'))
                continue
            project, task = actions.load_task(record.get('continuation_task_id') or record['task_id'])
            _verify_record_source(record, project, task)
            if record['status'] in {'prepared', 'running'}:
                record = ledger.update(record['id'], status='interrupted', reason='原执行进程已退出，先对账，不重放')
            if record.get('job_finished') and record.get('scheduler_state') in unknown.TERMINAL:
                # 已持久化终态后仅重试本地同步，LSF历史被清理也不撤销结束事实。
                match = {'job_id': record['job_id'], 'state': record['scheduler_state'],
                         'directory': (record.get('plan') or {}).get('work_dir', '')}
            else:
                if record['server'] not in rows_by_server:
                    rows_by_server[record['server']] = unknown.jobs(record['server'])
                rows = rows_by_server[record['server']]
                if record.get('job_id'):
                    same_job = [row for row in rows if row['job_id'] == str(record['job_id'])]
                    matches = [row for row in same_job if row['name'] == record.get('execution_name')]
                else:
                    matches = [row for row in rows if row['name'] == record.get('execution_name')]
                    same_job = matches
                match = matches[0] if len(matches) == 1 else None
            if not match:
                if not same_job:
                    # bjobs 查询成功却完全没有这个作业：说明未提交成功或早已结束/清理。
                    # 只按目录互斥的规则，它不再占用该目录，直接释放，避免永久卡住提交。
                    results.append(ledger.update(
                        record['id'], status='failed', reservation=0, released=True,
                        reason='LSF 已无该作业（未提交或已清理），释放目录占用'))
                else:
                    results.append(ledger.update(record['id'], status='unknown',
                                                 reason='LSF 作业身份不唯一或与提交记录不符，暂停并要求人工核实'))
                continue
            directory = (record.get('plan') or {}).get('work_dir')
            if directory and match['directory'].rstrip('/') != directory.rstrip('/'):
                raise ValueError('LSF作业目录与提交快照不符，需人工核实')
            if match['state'] not in unknown.ACTIVE | unknown.TERMINAL:
                results.append(ledger.update(record['id'], status='unknown', reason='LSF状态未知'))
                continue
            fields = {'status': 'succeeded', 'reason': None, 'job_id': match['job_id'], 'scheduler_state': match['state'], 'sync_error': None}
            if match['state'] in unknown.TERMINAL:
                fields.update(reservation=0, consumed_core_hours=record.get('reservation', 0) + record.get('consumed_core_hours', 0),
                              consumption_basis='reserved_upper_bound', job_finished=True)
            # 先持久化远端事实；项目库失败可继续恢复，不把已结束再标成UNKNOWN。
            result = ledger.update(record['id'], **fields)
            results.append(result)
            # 仅恢复当前活跃作业；终态不覆盖科学结论、不复活已停止/归档任务。
            records = list(ledger.read()['actions'].values())
            position = next(i for i, a in enumerate(records) if a['id'] == record['id'])
            newer = any(a['family_id'] == record['family_id'] and a.get('submission_attempted')
                        for a in records[position + 1:])
            with db_transaction() as db:
                fresh_project = next(p for p in db['projects'] if p['name'] == project['name'])
                current_task = next(t for t in fresh_project['tasks'] if t['task_id'] == task['task_id'])
                _verify_record_source(record, fresh_project, current_task)
                # 作业号/状态登记在主任务（续算子任务只是工作目录）。
                owner_id = family_id(task['task_id'])
                owner_task = next((t for t in fresh_project['tasks'] if t['task_id'] == owner_id), current_task)
                current_id = str(owner_task.get('job_id') or '')
                same_job = current_id == str(match['job_id'])
                if result.get('job_finished') and record.get('stop_requested_at') and same_job and not newer:
                    if owner_task['status'] in {'queued', 'running'}:
                        update_task_status(db, project['name'], owner_id, 'pending', {'job_id': None, 'stop_requested_at': None, 'stop_requested_job_id': None})
                    else:
                        owner_task.update(stop_requested_at=None, stop_requested_job_id=None)
                elif match['state'] in unknown.ACTIVE and not newer and owner_task['status'] != 'archived':
                    if not current_id or same_job:
                        status = 'queued' if match['state'] == 'PEND' else 'running'
                        update_task_status(db, project['name'], owner_id, status, {'job_id': match['job_id']})
            strict_audit(record, 'success', '只读LSF对账：' + match['state'])
        except Exception as exc:
            current = ledger.get(record['id'])
            if current.get('job_finished'):
                # 科学状态/审计落库故障不能撤销已经核实的LSF结束事实。
                ledger.update(record['id'], sync_error=str(exc))
            else:
                results.append(ledger.update(record['id'], status='unknown', reason='对账失败：' + str(exc)))
        finally:
            if lock is not None:
                scheduler._release_task_lock(lock)
    if task_id:
        lock = None
        try:
            if not _lock_held:
                lock = scheduler._acquire_task_lock(task_id)
            project, task = actions.load_task(task_id)
            if (task.get('stop_requested_at') and task.get('job_id')
                    and str(task.get('stop_requested_job_id') or '') == str(task['job_id'])):
                if project['server'] not in rows_by_server:
                    rows_by_server[project['server']] = unknown.jobs(project['server'])
                _sync_stop_metadata(project, task, rows_by_server[project['server']])
        except scheduler._TaskBusy:
            pass
        finally:
            if lock is not None:
                scheduler._release_task_lock(lock)
    return results


def sync_stopped_job(project, task):
    """bkill已接受后锁内调用；只有LSF终态允许清号，查询失败保留阻塞。"""
    job_id = str(task['job_id'])
    family = family_id(task['task_id'])
    requested_at = now_iso()
    records = [a for a in ledger.read()['actions'].values()
               if a['family_id'] == family and str(a.get('job_id') or '') == job_id and not a.get('job_finished')]
    for record in records:
        ledger.update(record['id'], stop_requested_at=requested_at)
    with db_transaction() as db:
        current = next(t for p in db['projects'] if p['name'] == project['name']
                       for t in p['tasks'] if t['task_id'] == task['task_id'])
        if str(current.get('job_id') or '') != job_id:
            raise ValueError('停止期间任务作业号变化，保留原状态并要求对账')
        current.update(stop_requested_at=requested_at, stop_requested_job_id=job_id)
    rows = unknown.jobs(project['server'])
    reconcile(task_id=task['task_id'], _lock_held=True, _rows={project['server']: rows})
    return _sync_stop_metadata(project, task, rows)


def _sync_stop_metadata(project, task, rows):
    job_id = str(task['job_id'])
    family = family_id(task['task_id'])
    records = [a for a in ledger.read()['actions'].values()
               if a['family_id'] == family and str(a.get('job_id') or '') == job_id]
    matches = [r for r in rows if r['job_id'] == job_id]
    root = _completion_binding(project, task)['root_directory']
    terminal = len(matches) == 1 and matches[0]['state'] in unknown.TERMINAL
    directory = matches[0]['directory'].rstrip('/') if len(matches) == 1 else ''
    terminal = terminal and (directory == root or bool(re.fullmatch(re.escape(root) + r'/con[0-9]+', directory)))
    # 有台账时还必须通过唯一执行名、目录和来源校验。
    terminal = terminal and all(ledger.get(a['id']).get('job_finished') for a in records)
    if terminal:
        with db_transaction() as db:
            current = next(t for p in db['projects'] if p['name'] == project['name']
                           for t in p['tasks'] if t['task_id'] == task['task_id'])
            if str(current.get('job_id') or '') == job_id:
                if current['status'] in {'queued', 'running'}:
                    update_task_status(db, project['name'], task['task_id'], 'pending', {'job_id': None, 'stop_requested_at': None, 'stop_requested_job_id': None})
                else:
                    current.update(stop_requested_at=None, stop_requested_job_id=None)
    return terminal


def confirm_killed(project, task, job_id, raw='', *, not_found=False):
    """bkill 明确返回终止/已结束/无匹配作业后收尾本地状态。

    用户口径（2026-10-21）：拿到 bkill 的 killed 结果就刷新，不再一直停在"等待确认"。
    LSF 终态通常几秒后才反映到 bjobs；同目录并发仍由 assert_remote_idle 用实时 bjobs 兜底。
    无匹配仅记录 NOT_FOUND，原结束原因未知，不表示 VASP 正常完成或收敛。
    """
    requested = now_iso()
    family = family_id(task['task_id'])
    for record in ledger.read()['actions'].values():
        if (record['family_id'] == family and str(record.get('job_id') or '') == str(job_id)
                and not record.get('job_finished')):
            # 与 LSF 终态路径同一记账口径：释放预留，核时按最坏情况计入。
            ledger.update(record['id'], job_finished=True, scheduler_state='NOT_FOUND' if not_found else 'EXIT',
                          stop_confirmed_by='bkill_not_found' if not_found else 'bkill', stop_requested_at=requested,
                          reservation=0,
                          consumed_core_hours=record.get('reservation', 0) + record.get('consumed_core_hours', 0),
                          consumption_basis='reserved_upper_bound',
                          reason=('bkill 明确无匹配作业，原结束原因未知' if not_found else 'bkill 已确认终止')
                                 + (f'：{raw[:200]}' if raw else ''))
    with db_transaction() as db:
        current = next(t for p in db['projects'] if p['name'] == project['name']
                       for t in p['tasks'] if t['task_id'] == task['task_id'])
        if str(current.get('job_id') or '') != str(job_id):
            raise ValueError('停止期间任务作业号变化，保留原状态并要求对账')
        if current['status'] in {'queued', 'running'}:
            update_task_status(db, project['name'], task['task_id'], 'pending',
                               {'job_id': None, 'stop_requested_at': None, 'stop_requested_job_id': None})
        else:
            current.update(job_id=None, stop_requested_at=None, stop_requested_job_id=None)
    return True


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
                             finished_confirmation=_completion_binding(project, actions.load_task(record['task_id'])[1], job_id=record['job_id']),
                             reason='人工确认调度作业已结束；不代表VASP收敛或科学通过')
    finally:
        scheduler._release_task_lock(lock)
