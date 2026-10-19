"""受限Agent执行与人工授权；新能力默认关闭。"""
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
import permissions
from automation import actions, gateway, ledger
from envelope import ok, fail

router = APIRouter(prefix='/agent-execution', tags=['agent-execution'])


@router.post('/opt-runs')
def create_opt_run(request: Request, payload: dict = Body(...)):
    from automation import opt_loop
    try:
        return ok('单OPT循环已创建，等待推进或巡检；未直接提交作业', opt_loop.public(opt_loop.create(
            _user(request), getattr(request.state, 'session', None), payload)))
    except Exception as exc:
        return _failure(exc)


@router.get('/opt-runs/{run_id}')
def get_opt_run(run_id: str, request: Request):
    from automation import opt_loop
    try:
        return ok('查询成功', opt_loop.public(opt_loop.get(run_id, _user(request))))
    except Exception as exc:
        return _failure(exc)


@router.post('/opt-runs/{run_id}/step')
def step_opt_run(run_id: str, request: Request):
    from automation import opt_loop
    try:
        opt_loop._human(_user(request), opt_loop.get(run_id, _user(request)))
        return ok('已推进一个有限步骤；未收敛时继续等待巡检或暂停', opt_loop.public(opt_loop.step(run_id, _user(request))))
    except Exception as exc:
        return _failure(exc)


@router.post('/opt-runs/{run_id}/control')
def control_opt_run(run_id: str, request: Request, payload: dict = Body(...)):
    from automation import opt_loop
    try:
        if set(payload) != {'command'}:
            raise ValueError('仅支持command: pause/resume/close')
        return ok('状态已更新', opt_loop.public(opt_loop.control(_user(request), run_id, payload['command'])))
    except Exception as exc:
        return _failure(exc)


def _user(request):
    return getattr(request.state, 'user', None)


def _failure(exc):
    if isinstance(exc, permissions.PermissionDenied):
        raise exc
    from automation.scheduler import _TaskBusy
    return JSONResponse(status_code=409 if isinstance(exc, (ValueError, _TaskBusy)) else 503, content=fail(str(exc)))


@router.get('')
def status(request: Request):
    try:
        user = _user(request)
        doc = ledger.read()
        grants = []
        for grant in doc['grants'].values():
            project, _ = actions.load_task(grant['task_ids'][0])
            if permissions.owned_by(project, user):
                if user.get('role') != 'agent' or grant['agent_username'] == permissions.username_of(user):
                    grants.append(grant)
        allowed = {g['id'] for g in grants}
        records = [r for r in doc['actions'].values() if r.get('grant_id') in allowed]
        runs = [{k:r.get(k) for k in ('id','task_id','status','reason','steps','repairs','updated_at')}
                for r in doc.get('opt_runs',{}).values() if r['grant_id'] in allowed]
        return ok('查询成功', {'enabled': doc['enabled'], 'grants': grants, 'actions': records, 'opt_runs':runs})
    except Exception as exc:
        return _failure(exc)


@router.put('/settings')
def settings(request: Request, payload: dict = Body(...)):
    permissions.ensure_admin(_user(request))
    if set(payload) != {'enabled'} or not isinstance(payload['enabled'], bool):
        return JSONResponse(status_code=400, content=fail('只支持enabled布尔值'))
    try:
        with ledger.transaction() as doc:
            doc['enabled'] = payload['enabled']
        return ok('已更新；暂停只阻止新动作，不停止远端作业', {'enabled': payload['enabled']})
    except Exception as exc:
        return _failure(exc)


@router.post('/grants')
def create_grant(request: Request, payload: dict = Body(...)):
    try:
        return ok('授权已创建，默认暂停，需显式启用', gateway.create_grant(_user(request), payload))
    except Exception as exc:
        return _failure(exc)


@router.patch('/grants/{grant_id}')
def change_grant(grant_id: str, request: Request, payload: dict = Body(...)):
    if set(payload) != {'enabled'} or not isinstance(payload['enabled'], bool):
        return JSONResponse(status_code=400, content=fail('只支持enabled布尔值；修改预算需新建授权'))
    try:
        return ok('授权已更新；不会停止远端作业', gateway.change_grant(_user(request), grant_id, enabled=payload['enabled']))
    except Exception as exc:
        return _failure(exc)


@router.post('/actions')
def execute(request: Request, payload: dict = Body(...)):
    try:
        allowed = {'grant_id', 'action', 'task_id', 'params', 'follow_up', 'dry_run', 'idempotency_key'}
        if set(payload) - allowed:
            raise ValueError('存在不支持的执行字段')
        result = gateway.execute(user=_user(request), session=getattr(request.state, 'session', None),
                                 grant_id=str(payload.get('grant_id') or ''), action=str(payload.get('action') or ''),
                                 task_id=str(payload.get('task_id') or ''), params=payload.get('params'),
                                 follow_up=payload.get('follow_up'), dry_run=bool(payload.get('dry_run')),
                                 idempotency_key=request.headers.get('Idempotency-Key') or payload.get('idempotency_key'))
        return ok('动作已处理；不等于计算已收敛', result)
    except Exception as exc:
        return _failure(exc)


@router.post('/actions/{action_id}/reconcile')
def reconcile(action_id: str, request: Request):
    try:
        record = ledger.get(action_id)
        if not record:
            return JSONResponse(status_code=404, content=fail('动作不存在'))
        project, _ = actions.load_task(record['task_id'])
        permissions.ensure_project_owner(project, _user(request))
        if _user(request).get('role') == 'agent':
            raise permissions.PermissionDenied('请由人工发起对账')
        return ok('仅对账已有作业，没有重新提交', {'actions': gateway.reconcile(action_id)})
    except Exception as exc:
        return _failure(exc)


@router.post('/actions/{action_id}/resolve-not-submitted')
def resolve_not_submitted(action_id: str, request: Request, payload: dict = Body(...)):
    try:
        if payload.get('confirmed_no_submission') is not True:
            raise ValueError('需要明确确认已人工核实没有产生提交')
        return ok('已记录人工核实，未执行任何远端操作', gateway.resolve_not_submitted(
            _user(request), action_id, payload.get('evidence')))
    except Exception as exc:
        return _failure(exc)


@router.post('/actions/{action_id}/resolve-finished')
def resolve_finished(action_id: str, request: Request, payload: dict = Body(...)):
    try:
        if payload.get('confirmed_finished') is not True:
            raise ValueError('需要明确确认已人工核实作业结束')
        return ok('已记录人工核实；不代表计算收敛', gateway.resolve_finished(
            _user(request), action_id, payload.get('evidence')))
    except Exception as exc:
        return _failure(exc)
