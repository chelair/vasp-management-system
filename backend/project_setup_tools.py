"""Human AI workspace project registration; reuse the existing project/group cores."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Literal

from pydantic import Field

import permissions
from config import load_servers
from models import AddProjectPayload, ProjectIn, ProjectPatchIn
import project_requirements as requirements
from project_requirements import Strict
from property_science import digest
from storage import _db_lock, load_db


class Task(Strict):
    model_name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_@]*$')
    task_type: Literal['opt', 'ele']


class Group(Strict):
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_@]*$')
    group_type: Literal['free_energy', 'neb']
    structures: int | None = Field(default=None, ge=1, le=50)
    images: int | None = Field(default=None, ge=1, le=50)


class Contents(Strict):
    tasks: list[Task] = Field(default_factory=list, max_length=50)
    groups: list[Group] = Field(default_factory=list, max_length=20)


class Create(Contents):
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_]*$')
    deadline: str
    server: str
    original_request: str = Field(min_length=1, max_length=16000)
    description: str = Field(default='', max_length=16000)
    calc_description: str = Field(default='', max_length=16000)
    expected_results: str = Field(default='', max_length=16000)


def _inline_schema(schema, definitions=None):
    """Nested Pydantic schemas use document-root refs; inline them for tool providers."""
    if isinstance(schema, list):
        return [_inline_schema(item, definitions) for item in schema]
    if not isinstance(schema, dict):
        return schema
    definitions = {**(definitions or {}), **schema.get('$defs', {})}
    if '$ref' in schema:
        return _inline_schema(definitions[schema['$ref'].rsplit('/', 1)[-1]], definitions)
    return {k:_inline_schema(v, definitions) for k,v in schema.items() if k != '$defs'}


def tool(name, description, schema):
    return {'type':'function', 'function':{'name':name, 'description':description, 'parameters':_inline_schema(schema)}}


def simple(properties, required=()):
    return {'type':'object', 'properties':properties, 'required':list(required), 'additionalProperties':False}


TOOLS = [
    tool('get_project_setup_options', '创建前查询可选服务器名称和本人可见项目，避免重复创建；不连SSH。通用会话也可使用。', simple({})),
    tool('create_project_from_request', '按用户明确要求创建项目和计算任务登记。original_request必须引用本会话用户的真实原文；description/calc_description/expected_results逐行保留原文，几乎不改写。deadline/server不猜，先查可选服务器，缺信息在对话问。一个模型一个ele主任务可承载多个分析，勿按DOS/差分重复建ele。自由能structures指构型数，NEB images只指中间映像数，不确定则先不建该组并说明。只建本地登记和默认模板，不建模型、不访问SSH、不提交。通用会话创建成功后绑定新项目，失败可用相同参数继续补齐，勿改名重建。', Create.model_json_schema()),
    tool('create_calculation_contents', '在当前项目补建优化/电子结构任务或自由能/NEB组；复用现有登记，完全相同则返回已有任务，不重复建。数量/位点不确定先问。只登记本地，不提交、不上传、不修改原计算文件。', Contents.model_json_schema()),
    tool('update_project_details', '按用户明确要求修改当前项目说明/计算内容/预期/交付日期，文本逐行保留用户原话。先get_project_requirements取得source_hash防覆盖新编辑。只改传入字段；不根据描述变更自动创建或删除任务。', simple({'source_hash':{'type':'string'}, 'patch':ProjectPatchIn.model_json_schema()}, ('source_hash','patch'))),
    tool('get_project_requirements', '查看当前项目最新原文、计算内容与预期对应表及Python结果比较。未生成/待更新时，使用当前原文与任务表，通过save_project_requirements整理；无需用户填写任务ID。只读本地，不调用模型或SSH。', simple({})),
    tool('save_project_requirements', '将当前项目原文理解为模型/计算内容/预期对应表。先get_project_requirements，传其source_hash与revision作为expected_revision。source引用原文连续子串；预期只来自当前描述/预期字段，不从历史原始输入复活已删除预期。任务不唯一留空并提问。吸附能inputs绑定surface/adsorbate/complex；数值A>B用numeric/gt，不擅自翻成吸附更强。无预期不新增；不支持分析只记录。后端校验与Python运算，无HPC操作。', simple({'source_hash':{'type':'string'}, 'expected_revision':{'type':'integer'}, 'mapping':requirements.ResearchMap.model_json_schema()}, ('source_hash','expected_revision','mapping'))),
]
NAMES = {t['function']['name'] for t in TOOLS}
GENERAL_NAMES = {'get_project_setup_options', 'create_project_from_request'}


def _unwrap(result):
    if hasattr(result, 'body'):
        result = json.loads(result.body)
    if not result.get('success'):
        raise ValueError(result.get('message', '项目登记未完成'))
    return result['data']


def _request(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def _user_text(conversation, user):
    import ai_chat_store as store
    with store.database() as db:
        store.owned(db, 'conversations', conversation['id'], str(user['user_id']))
        return [r[0] for r in db.execute("SELECT content FROM messages WHERE conversation_id=? AND role='user'", (conversation['id'],))]


def _verbatim(value, texts):
    return all(any(line.strip() in text for text in texts) for line in value.splitlines() if line.strip())


def _validate_contents(contents):
    names = [t.model_name for t in contents.tasks] + [g.name for g in contents.groups]
    if len(set(names)) != len(names):
        raise ValueError('同次登记的任务/分组名称重复，请区分名称')
    for g in contents.groups:
        if g.group_type == 'free_energy' and (g.structures is None or g.images is not None):
            raise ValueError('自由能组需要明确构型数 structures')
        if g.group_type == 'neb' and (g.images is None or g.structures is not None):
            raise ValueError('NEB需要明确中间映像数 images（不含初末态）')


def _contents(project_id, user, contents):
    from routers.groups import core_create_independent_task, core_create_group, IndependentTaskPayload
    done = []
    for spec in list(contents.tasks) + list(contents.groups):
        project = next(p for p in load_db()['projects'] if p['project_id'] == project_id)
        permissions.ensure_project_owner(project, user)
        if isinstance(spec, Task):
            matches = [t for t in project['tasks'] if t['model_name'] == spec.model_name]
            if matches:
                if len(matches) != 1 or matches[0]['task_type'] != spec.task_type or matches[0].get('group'):
                    raise ValueError(f'{spec.model_name} 已存在，但计算类型不同；已完成登记保留')
                done.append({'task_id':matches[0]['task_id'], 'existing':True})
            else:
                done.append(_unwrap(core_create_independent_task(IndependentTaskPayload(
                    project=project['name'], **spec.model_dump()), _request(user), local_only=True)))
        else:
            matches = [t for t in project['tasks'] if (t.get('group') or {}).get('name') == spec.name]
            if matches:
                group = matches[0]['group']
                valid = group['group_type'] == spec.group_type
                if spec.group_type == 'free_energy':
                    valid = valid and sum(t['task_type'] == 'opt' for t in matches) == spec.structures
                else:
                    valid = valid and group.get('images') == spec.images
                if not valid:
                    raise ValueError(f'{spec.name} 已存在，但组类型或数量不同；不会覆盖或重复创建')
                done.append({'group_id':group['group_id'], 'tasks':[t['task_id'] for t in matches], 'existing':True})
            else:
                done.append(_unwrap(core_create_group({'project':project['name'], **spec.model_dump(exclude_none=True)}, _request(user), local_only=True)))
    return done


def dispatch(project, conversation, user, name, arguments, run_id=''):
    if not user or not user.get('user_id') or user.get('role') == 'agent':
        raise permissions.PermissionDenied('项目登记仅供已登录用户使用')
    if name not in NAMES or not isinstance(arguments, dict):
        raise ValueError('不支持的项目工具')
    if name == 'get_project_setup_options':
        if arguments:
            raise ValueError('查询选项不接受额外参数')
        return {'servers':list(load_servers()), 'projects':[
            {'project_id':p['project_id'], 'name':p['name']} for p in permissions.visible_projects(load_db(), user)][:100]}
    if name == 'create_project_from_request':
        data = Create.model_validate(arguments)
        _validate_contents(data)
        texts = _user_text(conversation, user)
        original = next((text for text in reversed(texts) if data.original_request in text), None)
        if original is None:
            raise ValueError('original_request必须引用本会话用户的真实原文')
        data.original_request = original
        for field in ('description', 'calc_description', 'expected_results'):
            if not _verbatim(getattr(data, field), texts):
                raise ValueError(f'{field}需要保留用户原文，AI解释请写入对应表')
        signature = digest(data.model_dump())
        with _db_lock:
            existing = next((p for p in load_db()['projects'] if p['name'] == data.name), None)
            if existing:
                permissions.ensure_project_owner(existing, user)
                if existing.get('ai_creation_signature') != signature:
                    raise ValueError('已有同名项目；请在该项目中补充，不覆盖原资料')
                pid = existing['project_id']
            else:
                if conversation.get('project_id'):
                    raise ValueError('请在通用会话中创建另一个项目，当前项目会话不能改绑')
                from routers.projects import core_create_project
                p = ProjectIn(**{k:getattr(data,k) for k in ('name','deadline','server','description','calc_description','expected_results','original_request')})
                pid = _unwrap(core_create_project(AddProjectPayload(action='add_project', project=p),
                    _request(user), local_only=True, creation_signature=signature))['project_id']
            if conversation.get('project_id') not in (None, pid):
                raise permissions.PermissionDenied('当前会话不能操作另一个项目')
            # General -> newly created project only; an existing project chat cannot be rebound.
            import ai_chat_store as store
            with store.database() as db:
                current = store.owned(db, 'conversations', conversation['id'], str(user['user_id']))
                if current.get('project_id') not in (None, pid):
                    raise ValueError('会话已绑定其他项目，请重新读取')
                db.execute('UPDATE conversations SET project_id=? WHERE id=?', (pid, conversation['id']))
            try:
                registered = _contents(pid, user, data)
            except Exception as exc:
                return {'project_id':pid, 'project_created':True, 'contents_complete':False,
                        'detail':str(exc), 'note':'已完成登记保留；相同请求可继续补齐，无需重新建项目。'}
            requirements.schedule(pid, user, conversation.get('connection_id'))
            return {'project_id':pid, 'contents':registered, 'contents_complete':True,
                    'note':'已完成本地登记，会话已绑定新项目；默认输入模板仍需按模型核对，没有上传或提交计算。'}
    if not project or not conversation.get('project_id') or project['project_id'] != conversation['project_id']:
        raise permissions.PermissionDenied('请在对应项目会话中使用此工具')
    permissions.ensure_project_owner(project, user)
    pid = project['project_id']
    if name == 'get_project_requirements':
        if arguments:
            raise ValueError('对应表查询不接受额外参数')
        return requirements.evaluate(pid, user)
    if name == 'save_project_requirements':
        if set(arguments) != {'source_hash','expected_revision','mapping'}:
            raise ValueError('请提供source_hash、expected_revision和mapping')
        return requirements.save_mapping(pid, user, arguments['source_hash'], arguments['mapping'], arguments['expected_revision'])
    if name == 'update_project_details':
        if set(arguments) != {'source_hash','patch'}:
            raise ValueError('请提供source_hash和patch')
        patch = ProjectPatchIn.model_validate(arguments['patch'])
        if set(patch.model_fields_set) - {'description','calc_description','expected_results','deadline'}:
            raise ValueError('AI项目资料工具仅修改描述、预期和交付日期')
        texts = _user_text(conversation, user)
        for field in ('description','calc_description','expected_results'):
            value = getattr(patch, field)
            if value and not _verbatim(value, texts):
                raise ValueError('项目资料请保留用户原文；解释单独记录')
        with _db_lock:
            project = next(p for p in load_db()['projects'] if p['project_id'] == pid)
            permissions.ensure_project_owner(project, user)
            if requirements.fingerprint(project) != arguments['source_hash']:
                raise ValueError('项目资料已变化，请读取最新对应表后再修改')
            from routers.projects import update_project
            _unwrap(update_project(pid, patch, _request(user)))
        requirements.schedule(pid, user, conversation.get('connection_id'))
        return requirements.view(next(p for p in load_db()['projects'] if p['project_id'] == pid))
    contents = Contents.model_validate(arguments)
    _validate_contents(contents)
    with _db_lock:
        result = _contents(pid, user, contents)
    requirements.schedule(pid, user, conversation.get('connection_id'))
    return {'contents':result, 'note':'只完成本地任务登记；未上传输入或提交计算。'}
