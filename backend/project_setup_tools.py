"""Human AI workspace project registration; reuse the existing project/group cores."""
from __future__ import annotations

import json
import re
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
    model_name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_@]*$', max_length=32,
        description='短名保留模型之间的结构差别，如M1_Alloy_opt、M2_Hetero_opt、M3_Ru_Cu_opt。共享基底/元素不反复堆入名称；完整模型含义写description。')
    task_type: Literal['opt', 'ele']


class Group(Strict):
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_@]*$', max_length=32,
        description='沿用模型特征短名加研究对象，如Alloy_NO3RR、Hetero_H；不展开整段模型描述。')
    group_type: Literal['free_energy', 'neb']
    structures: int | None = Field(default=None, ge=1, le=50)
    images: int | None = Field(default=None, ge=1, le=50)
    quantity_source: str = Field(default='', max_length=1000,
        description='连续引用用户明确指定本组数量的原话。自由能如“合金六个构型”或“每个模型6个中间体”；NEB须明确“5个中间映像”或“含初末态共5个点”。“共6个中间体”不能自行均分，“5个点”不能猜口径；无明确依据则不建本组，返回待确认。')


class Contents(Strict):
    tasks: list[Task] = Field(default_factory=list, max_length=50)
    groups: list[Group] = Field(default_factory=list, max_length=20)


class Create(Contents):
    name: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_]*$')
    deadline: str
    server: str = Field(min_length=1)
    original_request: str = Field(min_length=1, max_length=16000)
    description: str = Field(default='', max_length=16000)
    calc_description: str = Field(default='', max_length=16000, description='逐行复制计算内容完整原文，保留行内预期，不删除括号中的预期文字。')
    expected_results: str = Field(default='', max_length=16000, description='复制含预期的完整原文行，保留所属计算内容，不能只留脱离主题的排序；交付日期仅填deadline。留空时从计算内容中提取含预期的原文行。')


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
    tool('create_project_from_request', '按用户明确要求创建项目和计算任务登记。original_request引用本会话真实用户原文；计算内容整行复制，保留行内预期。名称简短且体现模型结构差别，如M1_Alloy_opt/M2_Hetero_opt/M3_Ru_Cu_opt，不堆共有基底和元素。服务器须用户选定，即使只有一个选项也不能擅自指定。组数量须quantity_source明确引文；含糊数量先留待确认，不能均分中间体或猜映像数。返回pending_contents不代表全部登记完成。一个模型一个ele主任务承载多种分析。只登记本地和默认模板，不建模型、不访问SSH、不提交。成功后绑定新项目，使用get/save_project_requirements继续整理并核对实际关联；勿重复建项目。', Create.model_json_schema()),
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
    # The same model can have OPT and ELE calculations without forcing the model
    # to discover the core's global task-name constraint through failed writes.
    counts = {t.model_name: {x.task_type for x in contents.tasks if x.model_name == t.model_name}
              for t in contents.tasks}
    contents.tasks = [Task(model_name=f'{t.model_name}_{t.task_type}' if len(counts[t.model_name]) > 1 else t.model_name,
                           task_type=t.task_type) for t in contents.tasks]
    names = [t.model_name for t in contents.tasks] + [g.name for g in contents.groups]
    if len(set(names)) != len(names):
        raise ValueError('同次登记的任务/分组名称重复，请区分名称')


def _count(value):
    if value.isdigit():
        return int(value)
    digits = {'一':1, '二':2, '两':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9}
    if '十' in value:
        left, right = value.split('十', 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, 0)


def _quantity_problem(group, texts):
    quote = group.quantity_source.strip()
    prefix = r'(?<![\d.\-一二两三四五六七八九十])' if re.match(r'[0-9一二两三四五六七八九十]', quote) else ''
    contexts = [line for text in texts for line in re.split(r'[\n；;。]', text)
                if quote and re.search(prefix + re.escape(quote), line)]
    if not contexts:
        return '数量依据须引用用户原话，请先确认本组构型数或中间映像数。'
    number = r'(?<![\d.\-])([0-9]{1,2}|[一二两三四五六七八九十]{1,3})(?![\d.])\s*个?\s*'
    if group.group_type == 'free_energy':
        matches = re.findall(number + r'(?:构型|中间体)', quote)
        if not matches or group.structures is None or group.images is not None:
            return '请明确本组有几个构型/中间体，并在structures填写相同数量。'
        # Inspect the source clause as well: trimming “共6个” to “6个” must not
        # make an aggregate count into a per-model authorization.
        if any(re.search(r'共|合计|总计', line) and not re.search(r'每|各', line)
               and len(set(re.findall(r'模型\s*([0-9]+)', line))) != 1 for line in contexts):
            return '原文为合计数量，不能自行均分；请确认每个模型/分组的构型数。'
        if len(matches) != 1 or _count(matches[0]) != group.structures:
            return '本组structures与用户明确的构型数量不一致。'
    else:
        matches = re.findall(number + r'(?:中间映像|中间图像|中间点)', quote)
        images = _count(matches[0]) if len(matches) == 1 else None
        if images is None and re.search(r'含|包括', quote) and re.search(r'初末态|两端|端点|IS.*FS', quote, re.I):
            totals = re.findall(number + r'(?:点|映像|图像)', quote)
            images = _count(totals[-1]) - 2 if len(totals) == 1 else None
        if group.images is None or group.structures is not None or images != group.images:
            return '请确认是几个中间映像，还是包含初末态共几个点；不能将“5个点”直接当作images=5。'
    return ''


def _ready_contents(contents, texts):
    groups, pending = [], []
    for group in contents.groups:
        problem = _quantity_problem(group, texts)
        if problem:
            pending.append({'name':group.name, 'group_type':group.group_type, 'question':problem})
        else:
            groups.append(group)
    return Contents(tasks=contents.tasks, groups=groups), pending


def _server_selected(server, texts):
    servers = load_servers()
    if server not in servers:
        return False
    name = r'(?<![A-Za-z0-9_])' + re.escape(server) + r'(?![A-Za-z0-9_])'
    if any(re.search(name, text) for text in texts):
        return True
    # A human can select the sole configured server in ordinary language.
    return len(servers) == 1 and any(re.fullmatch(
        r'\s*(?:服务器)?(?:就)?(?:用|选|使用)(?:默认|唯一|这台|那台|这个|那个)(?:的)?(?:那台|这台|服务器)?[。！!\s]*', line)
        for text in texts for line in text.splitlines())


def _expectation_text(data):
    lines = [line.strip() for field in (data.description, data.calc_description) for line in field.splitlines() if line.strip()]
    selected = [line for line in lines if re.search(r'预期|期望', line)]
    for line in data.expected_results.splitlines():
        line = line.strip()
        if not line or re.search(r'交付|截止|交期', line):
            continue
        candidates = [source for source in lines if line in source]
        selected.append(candidates[0] if len(candidates) == 1 else line)
    return '\n'.join(dict.fromkeys(selected))


def _mapping_receipt(doc):
    # Return the actual saved associations, without resending all original text
    # and task metadata after every mapping save.
    return {k:doc[k] for k in ('project_id','revision','source_hash','status','mapping','binding_summary','comparisons','note') if k in doc}


def _contents(project_id, user, contents):
    from routers.groups import core_create_independent_task, core_create_group, IndependentTaskPayload
    done = []
    for spec in list(contents.tasks) + list(contents.groups):
        project = next(p for p in load_db()['projects'] if p['project_id'] == project_id)
        permissions.ensure_project_owner(project, user)
        if isinstance(spec, Task):
            matches = [t for t in project['tasks'] if t['model_name'] == spec.model_name]
            suffixed = f'{spec.model_name}_{spec.task_type}'
            canonical = [t for t in project['tasks'] if t['model_name'] == suffixed]
            other_type = len(matches) == 1 and matches[0]['task_type'] != spec.task_type and not matches[0].get('group')
            if other_type or (not matches and canonical):
                spec = Task(model_name=suffixed, task_type=spec.task_type)
                matches = canonical
            if matches:
                if len(matches) != 1 or matches[0]['task_type'] != spec.task_type or matches[0].get('group'):
                    raise ValueError(f'{spec.model_name} 已存在，但计算类型不同；已完成登记保留')
                done.append({'task_id':matches[0]['task_id'], 'model_name':matches[0]['model_name'], 'existing':True})
            else:
                done.append({**_unwrap(core_create_independent_task(IndependentTaskPayload(
                    project=project['name'], **spec.model_dump()), _request(user), local_only=True)), 'model_name':spec.model_name})
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
                done.append(_unwrap(core_create_group({'project':project['name'], **spec.model_dump(exclude_none=True, exclude={'quantity_source'})}, _request(user), local_only=True)))
    return done


def dispatch(project, conversation, user, name, arguments, run_id=''):
    # The current AI run will translate its own writes; do not launch a second
    # paid model extraction concurrently for each item in the batch.
    with requirements.defer_extraction():
        return _dispatch(project, conversation, user, name, arguments, run_id)


def _dispatch(project, conversation, user, name, arguments, run_id=''):
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
        texts = _user_text(conversation, user)
        original = next((text for text in reversed(texts) if data.original_request in text), None)
        if original is None:
            raise ValueError('original_request必须引用本会话用户的真实原文')
        data.original_request = original
        for field in ('description', 'calc_description', 'expected_results'):
            if not _verbatim(getattr(data, field), texts):
                raise ValueError(f'{field}需要保留用户原文，AI解释请写入对应表')
        # Keep the original signature contract for retries of previously created projects.
        signature = digest(data.model_dump(exclude={'groups':{'__all__':{'quantity_source'}}}))
        _validate_contents(data)
        ready, pending = _ready_contents(data, texts)
        if not _server_selected(data.server, texts):
            return {'project_created':False, 'contents_complete':False, 'pending_contents':pending,
                    'questions':[f'请选择服务器（可用：{", ".join(load_servers())}）。'],
                    'note':'尚未创建项目或任务；服务器须由用户选定，不能代填。'}
        data.expected_results = _expectation_text(data)
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
                registered = _contents(pid, user, ready)
            except Exception as exc:
                return {'project_id':pid, 'project_created':True, 'contents_complete':False,
                        'detail':str(exc), 'note':'已完成登记保留；相同请求可继续补齐，无需重新建项目。'}
            return {'project_id':pid, 'contents':registered, 'contents_complete':not pending, 'pending_contents':pending,
                    'note':'已完成明确部分的本地登记；待确认分组尚未创建。请整理对应表并向用户询问待确认项，不要猜数量重调创建。未上传或提交计算。'}
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
        return _mapping_receipt(requirements.save_mapping(pid, user, arguments['source_hash'], arguments['mapping'], arguments['expected_revision']))
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
        return requirements.view(next(p for p in load_db()['projects'] if p['project_id'] == pid))
    contents = Contents.model_validate(arguments)
    _validate_contents(contents)
    ready, pending = _ready_contents(contents, _user_text(conversation, user))
    with _db_lock:
        result = _contents(pid, user, ready)
    return {'contents':result, 'contents_complete':not pending, 'pending_contents':pending,
            'note':'明确部分已登记；待确认分组未创建。请继续整理对应表；未上传输入或提交计算。'}
