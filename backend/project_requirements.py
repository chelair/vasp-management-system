"""Versioned project intent, semantic bindings and deterministic expectation checks.

Original project text remains authoritative. This derived document never creates or
submits calculations. Language extraction uses the editor's private model connection;
inspection events only run existing Python property functions.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from config import DATA_DIR
from dates import now_iso
import permissions
from property_science import digest, number
from task_paths import is_auxiliary_task

ROOT = DATA_DIR / 'project_requirements'
_LOCK = threading.RLock()
_PENDING: dict = {}
_WORKING = False
_DEFER_EXTRACTION = ContextVar('project_requirements_defer_extraction', default=False)
TEXT_FIELDS = ('description', 'calc_description', 'expected_results', 'original_request')


@contextmanager
def defer_extraction():
    token = _DEFER_EXTRACTION.set(True)
    try:
        yield
    finally:
        _DEFER_EXTRACTION.reset(token)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Quote(Strict):
    field: Literal['description', 'calc_description', 'expected_results', 'original_request']
    quote: str = Field(min_length=1, max_length=4000)


class ResearchModel(Strict):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    source: Quote


class EnergyInput(Strict):
    task_id: str | None = None
    energy_value: float | None = Field(default=None, strict=True, allow_inf_nan=False)
    energy_unit: Literal['eV', 'Ha', 'Hartree', 'Ry', 'kJ/mol'] = 'eV'
    source_quote: str = Field(default='', max_length=2000)


class Calculation(Strict):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    kind: Literal['opt', 'free_energy', 'neb', 'ele', 'adsorption', 'other']
    model_keys: list[str] = Field(default_factory=list, max_length=10)
    task_ids: list[str] = Field(default_factory=list, max_length=60)
    group_ids: list[str] = Field(default_factory=list, max_length=10)
    analyses: list[str] = Field(default_factory=list, max_length=12)
    details: str = Field(default='', max_length=2000)
    inputs: dict[str, EnergyInput] = Field(default_factory=dict)
    source: Quote


class Expectation(Strict):
    key: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=1000)
    calculation_keys: list[str] = Field(default_factory=list, max_length=20)
    property_id: str = Field(default='', max_length=80)
    left: str = Field(default='', max_length=80)
    right: str = Field(default='', max_length=80)
    operator: Literal['gt', 'lt', 'ge', 'le', 'eq', 'unspecified'] = 'unspecified'
    meaning: Literal['numeric', 'stronger_adsorption', 'lower_barrier', 'unspecified'] = 'unspecified'
    source: Quote


class ResearchMap(Strict):
    models: list[ResearchModel] = Field(default_factory=list, max_length=30)
    calculations: list[Calculation] = Field(default_factory=list, max_length=100)
    expectations: list[Expectation] = Field(default_factory=list, max_length=80)
    questions: list[str] = Field(default_factory=list, max_length=20)


def _path(project_id):
    return ROOT / (hashlib.sha256(project_id.encode()).hexdigest() + '.json')


def _load(project_id):
    path = _path(project_id)
    return json.loads(path.read_text()) if path.is_file() else {}


def _write(doc):
    ROOT.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=ROOT, prefix='.requirements-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(path, _path(doc['project_id']))
    finally:
        if os.path.exists(path):
            os.unlink(path)


def sources(project):
    return {key: str(project.get(key) or '') for key in TEXT_FIELDS}


def task_catalog(project):
    return [{k: t.get(k) for k in ('task_id', 'model_name', 'task_type', 'group', 'parent_task_id')}
            for t in project.get('tasks', []) if not is_auxiliary_task(t)]


def fingerprint(project):
    return digest({'sources': sources(project), 'tasks': task_catalog(project)})


def touch(project):
    """No model calls: detect changed text/task identity, retain previous mapping as history."""
    pid, stamp = project['project_id'], fingerprint(project)
    with _LOCK:
        doc = _load(pid)
        if doc.get('source_hash') == stamp:
            return doc
        history = doc.get('history', [])
        if doc.get('mapping') and doc.get('mapped_hash') == doc.get('source_hash'):
            history = (history + [{k: copy.deepcopy(doc.get(k)) for k in
                ('revision', 'source_hash', 'sources', 'mapping', 'mapped_hash', 'comparisons', 'mapped_at')}])[-5:]
        doc = {'schema_version': 'requirements.1', 'project_id': pid,
               'revision': doc.get('revision', 0) + 1, 'source_hash': stamp,
               'sources': sources(project), 'tasks': task_catalog(project),
               'status': 'pending' if any(sources(project).values()) else 'empty',
               'mapping': doc.get('mapping', {}), 'mapped_hash': doc.get('mapped_hash'),
               'comparisons': [], 'history': history, 'updated_at': now_iso()}
        _write(doc)
        return doc


def view(project):
    doc = copy.deepcopy(touch(project))
    for key in ('history', 'evaluation_hash', 'actor_id', 'connection_id'):
        doc.pop(key, None)
    if doc.get('mapped_hash') != doc['source_hash']:
        doc['mapping'] = {}
        doc['comparisons'] = []
    doc['binding_summary'] = binding_summary(doc.get('mapping', {}))
    doc['note'] = 'ready仅表示原文已整理，不代表任务全部关联或可执行；以binding_summary核对缺项。对应表为AI解释，名称匹配不是科学关系验证。预期不代表实际结论。'
    return doc


def binding_summary(mapping):
    calculations = mapping.get('calculations', [])
    missing = [{'key':c['key'], 'title':c['title']} for c in calculations
               if not (c.get('task_ids') or c.get('group_ids') or
                       any(i.get('task_id') or i.get('energy_value') is not None for i in c.get('inputs', {}).values()))]
    return {'total':len(calculations), 'bound':len(calculations)-len(missing), 'unbound':missing}


def summary(project):
    """Small chat context; full sources and role bindings are available via the tool."""
    doc = view(project)
    mapping = doc.get('mapping', {})
    return {'status': doc['status'], 'revision': doc['revision'], 'source_hash': doc['source_hash'],
            'binding_summary':doc['binding_summary'],
            'models': mapping.get('models', []),
            'calculations': [{k:c[k] for k in ('key','title','kind','model_keys','task_ids','analyses')} for c in mapping.get('calculations', [])],
            'expectations': mapping.get('expectations', []),
            'comparisons': [{k:v for k,v in c.items() if k != 'science'} for c in doc.get('comparisons', [])],
            'questions': mapping.get('questions', []),
            'note': 'pending时用get_project_requirements读取最新原文并save_project_requirements整理；旧解释不能用于新预期。'}


def _validate(project, mapping):
    model = ResearchMap.model_validate(mapping)
    raw = sources(project)
    task_map = {t['task_id']: t for t in project.get('tasks', [])}
    groups = {(t.get('group') or {}).get('group_id') for t in task_map.values()}
    model_keys = {m.key for m in model.models}
    calc_keys = {c.key for c in model.calculations}
    for collection in (model.models, model.calculations, model.expectations):
        if len({x.key for x in collection}) != len(collection):
            raise ValueError('对应表中的标识重复')
        for item in collection:
            if item.source.quote not in raw[item.source.field]:
                raise ValueError('对应表引用必须来自当前项目原文，不能改写来源')
    electronic_analyses = {'dos', 'pdos', 'diff_charge', 'charge_density_difference', 'bader', 'work_function'}
    for calc in model.calculations:
        if calc.source.field == 'original_request':
            raise ValueError('计算内容必须以当前描述为准，不能从历史原始请求恢复已删除内容')
        if not set(calc.model_keys) <= model_keys:
            raise ValueError('计算内容引用了不存在的模型')
        if not set(calc.task_ids) <= task_map.keys() or not set(calc.group_ids) <= groups:
            raise ValueError('对应表只能关联当前项目的真实任务和分组')
        if (calc.kind == 'ele' or set(calc.analyses) & electronic_analyses) and any(task_map[tid].get('task_type') != 'ele' for tid in calc.task_ids):
            raise ValueError('电子结构分析必须关联电子结构主任务，不能挂到优化或其他任务')
        if set(calc.inputs) - {'surface', 'adsorbate', 'complex'}:
            raise ValueError('吸附能只接受基底、吸附物和完整构型三个角色')
        for item in calc.inputs.values():
            if item.task_id:
                if item.task_id not in task_map or task_map[item.task_id].get('task_type') not in ('opt', 'ele'):
                    raise ValueError('能量输入必须关联当前项目的优化或电子结构任务')
            if item.energy_value is not None:
                number(item.energy_value)
                if not item.source_quote or not any(item.source_quote in raw[k] for k in TEXT_FIELDS[:3]):
                    raise ValueError('给定能量必须引用当前项目原文')
                literals = re.findall(r'[-+]?\d+(?:\.\d+)?(?:[eEdD][-+]?\d+)?', item.source_quote)
                if not any(abs(number(x) - item.energy_value) < 1e-8 for x in literals):
                    raise ValueError('给定能量与引用原文中的数值不一致')
    for exp in model.expectations:
        if exp.source.field == 'original_request':
            raise ValueError('预期必须来自当前描述或预期字段，不能用历史原始请求恢复已删除的预期')
        refs = set(exp.calculation_keys) | {s for s in (exp.left, exp.right) if s}
        if not refs <= calc_keys:
            raise ValueError('预期引用了不存在的计算内容')
        if exp.left and exp.left == exp.right:
            raise ValueError('预期比较的两项计算不能相同')
    # Reuse an explicitly bound electronic calculation for another analysis of
    # the exact same model set. Do not infer model identity from similar names.
    for calc in model.calculations:
        if calc.task_ids or calc.group_ids or not calc.model_keys or not (set(calc.analyses) & electronic_analyses):
            continue
        candidates = {tuple(sorted(other.task_ids)) for other in model.calculations
                      if other is not calc and set(other.model_keys) == set(calc.model_keys)
                      and other.task_ids and all(task_map[tid].get('task_type') == 'ele' for tid in other.task_ids)}
        if len(candidates) == 1:
            calc.task_ids = list(next(iter(candidates)))
            calc.kind = 'ele'
    return model.model_dump(exclude_none=True)


def save_mapping(project_id, user, source_hash, mapping, expected_revision=None):
    from storage import _db_lock, load_db
    with _db_lock, _LOCK:
        project = next((p for p in load_db()['projects'] if p['project_id'] == project_id), None)
        permissions.ensure_project_owner(project, user)
        if not project:
            raise ValueError('项目不存在')
        doc = touch(project)
        if doc['source_hash'] != source_hash:
            raise ValueError('项目资料已变化，请读取最新原文后更新对应表')
        if expected_revision is not None and doc['revision'] != expected_revision:
            raise ValueError('对应表已由其他请求更新，请读取最新版本')
        validated = _validate(project, mapping)
        if doc.get('mapped_hash') == source_hash and doc.get('mapping'):
            doc['history'] = (doc.get('history', []) + [{k:copy.deepcopy(doc.get(k)) for k in
                ('revision','source_hash','sources','mapping','comparisons','mapped_at')}])[-5:]
        doc.update(mapping=validated, mapped_hash=source_hash, status='ready',
                   actor_id=str(user['user_id']), mapped_at=now_iso(), last_error='', revision=doc['revision'] + 1)
        doc.pop('evaluation_hash', None)
        _write(doc)
    return evaluate(project_id, user)


def evaluate(project_id, user):
    """Existing adsorption arithmetic, no model/SSH/inspection/submission calls."""
    from storage import _db_lock, load_db
    from adsorption_minimum import evaluate as adsorption
    from checks_store import merged_results
    with _db_lock, _LOCK:
        project = next((p for p in load_db()['projects'] if p['project_id'] == project_id), None)
        permissions.ensure_project_owner(project, user)
        if not project:
            raise ValueError('项目不存在')
        doc = touch(project)
        if doc.get('status') != 'ready' or doc.get('mapped_hash') != doc['source_hash']:
            return view(project)
        tasks = {t['task_id']: t for t in project.get('tasks', [])}
        rows = merged_results()
        relevant = {tid for calc in doc['mapping'].get('calculations', []) for tid in
                    calc.get('task_ids', []) + [i['task_id'] for i in calc.get('inputs', {}).values() if i.get('task_id')]}
        files = {}
        from task_paths import task_files_dir
        from report_block_science import checked_path
        for tid in sorted(relevant):
            if tid not in tasks:
                continue
            for name in ('OUTCAR', 'OSZICAR'):
                try:
                    path = checked_path(project, tasks[tid], task_files_dir(project['name'], tasks[tid]) / name)
                    stat = path.stat()
                    files[tid + '/' + name] = [stat.st_size, stat.st_mtime_ns]
                except (ValueError, OSError):
                    pass
        stamp = digest({'mapping': doc['mapping'], 'files': files,
                        'data': {tid: {'task': tasks.get(tid), 'observation': rows.get(tid)} for tid in sorted(relevant)}})
        if stamp == doc.get('evaluation_hash'):
            return view(project)
        calcs = {c['key']: c for c in doc['mapping'].get('calculations', [])}
        comparisons = []
        for exp in doc['mapping'].get('expectations', []):
            row = {'expectation_key': exp['key'], 'expected_quote': exp['source']['quote'],
                   'property_id': exp['property_id'], 'status': 'unsupported', 'source_hash': doc['source_hash']}
            if exp['property_id'] not in ('adsorption.estimate', 'adsorption.simple'):
                row['detail'] = '已记录分析目标；尚未接通该性质的自动预期比较。'
            elif not exp['left'] or not exp['right'] or exp['operator'] == 'unspecified' or exp['meaning'] not in ('numeric', 'stronger_adsorption'):
                row.update(status='needs_clarification', detail='还需明确比较对象、数值大小或吸附强弱的含义。')
            else:
                targets = []
                for key in (exp['left'], exp['right']):
                    calc = calcs[key]
                    inputs = copy.deepcopy(calc.get('inputs', {}))
                    for item in inputs.values():
                        if item.get('energy_value') is not None:
                            item.update(_source_kind='user_provided', _quote_verified=True)
                    targets.append({'label': calc['title'], **inputs})
                try:
                    result = adsorption({'projects': [project]}, user, {'project_ids': [project_id], 'targets': targets})
                except (ValueError, OSError):
                    row.update(status='unknown', detail='对应关系已保存，相关能量来源暂不可读；稍后可重新读取，尚无比较结论。')
                    comparisons.append(row)
                    continue
                # Freeze numerical inputs/provenance, not entire force curves and raw observations.
                for item in result.get('inputs', []):
                    item.pop('row', None)
                row.update(science=result, detail='初步电子吸附能比较，不等同于自由能或正式科学验证。')
                if len(result['results']) != 2:
                    row.update(status='missing', gaps=result['gaps'])
                else:
                    left, right = (number(r['value']) for r in result['results'])
                    delta = number(left - right)
                    op = exp['operator']
                    if exp['meaning'] == 'stronger_adsorption':
                        op = {'gt':'lt', 'lt':'gt', 'ge':'le', 'le':'ge', 'eq':'eq'}[op]
                    matched = {'gt': delta > 0, 'lt': delta < 0, 'ge': delta >= 0,
                               'le': delta <= 0, 'eq': delta == 0}[op]
                    row.update(status='matches' if matched else 'differs', left_ev=left, right_ev=right,
                               left_label=calcs[exp['left']]['title'], right_label=calcs[exp['right']]['title'],
                               difference_ev=delta, numeric_operator=op, meaning=exp['meaning'],
                               conclusion='数值关系符合预期' if matched else '数值关系不符合预期',
                               interpretation='常用负值定义下，吸附能更负通常表示吸附更强；差值未经过误差或显著性检验。')
            comparisons.append(row)
        doc.update(comparisons=comparisons, evaluation_hash=stamp, evaluated_at=now_iso())
        _write(doc)
        return view(project)


EXTRACTION_PROMPT = '''你是VASP项目需求翻译器。只返回符合给定schema的JSON，不执行操作。
当前description/calc_description/expected_results是最新权威原文；original_request仅补充模型背景，不能恢复已删除预期。
提取模型/别名、计算内容、预期与真实task_id/group_id对应。一个模型一个电子结构主任务可含DOS/PDOS/差分等多个analyses；相同model_keys的这些分析复用同一组ele任务，不能只在回复中声称关联。无任务关联的条目需如实列为待关联，ready不是可执行状态。
每项source必须引用相应字段的原文连续子串，原文没写预期就不编造。AI推断仅记details/questions，不伪装原文。
尚未创建任务可保留空task_ids。多个候选/位点不随机选择，在questions说明。inputs仅绑定明确的surface/adsorbate/complex；缺项留空。
吸附能property_id用adsorption.estimate；其他性质可记录名称但不假定已支持自动计算。比较left/right引用计算key。
原文数值A>B使用operator=gt、meaning=numeric，不把数值大解释为吸附强；明确吸附强弱用meaning=stronger_adsorption。
只说性能更好但未指定指标时meaning=unspecified，提问确认；三模型排序可拆成两条比较，保留相同原文。
不给定/猜测能量或公式；只有当前原文明确写出的参考能量才能用energy_value/energy_unit/source_quote。'''


def refresh(project_id, user, connection_id=None):
    from storage import load_db
    from ai_chat_service import readonly_json_completion
    import ai_chat_store as store
    project = next((p for p in load_db()['projects'] if p['project_id'] == project_id), None)
    permissions.ensure_project_owner(project, user)
    if not project:
        raise ValueError('项目不存在')
    doc = touch(project)
    if doc['status'] in ('ready', 'empty'):
        return evaluate(project_id, user)
    if not connection_id:
        items = store.connections(str(user['user_id']))
        connection_id = next((c['id'] for c in items if c['is_default']), items[0]['id'] if items else None)
    if not connection_id:
        raise ValueError('尚无自己的模型连接；原文已保存，对应表待生成')
    payload = {'sources': doc['sources'], 'tasks': doc['tasks'],
               'previous_mapping_for_stable_ids_only': doc.get('mapping', {}),
               'schema': ResearchMap.model_json_schema()}
    if len(json.dumps(payload, ensure_ascii=False)) > 65000:
        raise ValueError('项目资料较多，请在工作台按需分项整理对应表')
    parsed, _ = readonly_json_completion(str(user['user_id']), connection_id, [
        {'role':'system', 'content': EXTRACTION_PROMPT},
        {'role':'user', 'content': json.dumps(payload, ensure_ascii=False)}], max_output_tokens=12000)
    # Revocation/disabled accounts and project transfers must take effect even mid-request.
    import auth
    current = auth.find_user_by_id(user['user_id'])
    if not current or not current.get('enabled', True):
        raise permissions.PermissionDenied('账号已失效，对应表未更新')
    return save_mapping(project_id, current, doc['source_hash'], parsed, expected_revision=doc['revision'])


def _worker():
    global _WORKING
    while True:
        with _LOCK:
            if not _PENDING:
                _WORKING = False
                return
            pid = next(iter(_PENDING))
            user, connection = _PENDING.pop(pid)
        try:
            import auth
            current = auth.find_user_by_id(user['user_id'])
            if current and current.get('enabled', True):
                refresh(pid, current, connection)
        except Exception:
            # Keep originals and the previous mapping; don't retry possibly paid requests.
            with _LOCK:
                doc = _load(pid)
                if doc and doc['status'] == 'pending' and pid not in _PENDING:
                    doc.update(status='pending', last_error='对应表尚未生成或资料已更新，可在AI工作台继续整理。')
                    _write(doc)


def schedule(project_id, user, connection_id=None):
    global _WORKING
    if not user or not user.get('user_id') or user.get('role') == 'agent':
        return
    with _LOCK:
        _PENDING[project_id] = (copy.deepcopy(user), connection_id)
        if not _WORKING:
            _WORKING = True
            threading.Thread(target=_worker, name='project-requirements', daemon=True).start()


def projects_saved(db, previous=None):
    """Called after a successful atomic project save. Ignore ordinary status polling."""
    user = permissions.current_user_from_context()
    if previous is None:
        return
    before = {p['project_id']: fingerprint(p) for p in previous.get('projects', []) if p.get('project_id')}
    for project in db.get('projects', []):
        if not project.get('project_id'):
            continue
        stamp = fingerprint(project)
        if before.get(project['project_id']) == stamp:
            continue
        if not any(sources(project).values()) and not _path(project['project_id']).exists():
            continue
        doc = touch(project)
        if doc['status'] == 'pending' and user and permissions.owned_by(project, user) and not _DEFER_EXTRACTION.get():
            schedule(project['project_id'], user)


def inspection_updated(task_id):
    """Inspection events never send a model request or create a report/job."""
    import auth
    from storage import load_db
    for project in load_db()['projects']:
        if not any(t['task_id'] == task_id for t in project.get('tasks', [])):
            continue
        with _LOCK:
            doc = _load(project['project_id'])
        if doc.get('status') == 'ready':
            user = auth.find_user_by_id(doc.get('actor_id'))
            if user and user.get('enabled', True) and permissions.owned_by(project, user):
                evaluate(project['project_id'], user)
        return


def report_snapshot(projects, user, task_ids, science=None):
    """Only relevant mapped expectations; returned facts are frozen by the existing report."""
    snapshots = []
    for project in projects:
        doc = evaluate(project['project_id'], user)
        calculations = doc.get('mapping', {}).get('calculations', [])
        keys = {c['key'] for c in calculations if set(c.get('task_ids', []) +
                [v['task_id'] for v in c.get('inputs', {}).values() if v.get('task_id')]) & set(task_ids)}
        expectations = [e for e in doc.get('mapping', {}).get('expectations', []) if
                        ({e.get('left'), e.get('right')} | set(e.get('calculation_keys', []))) & keys]
        if expectations:
            ids = {e['key'] for e in expectations}
            comparisons = [c for c in doc.get('comparisons', []) if c['expectation_key'] in ids]
            # Explicit historical observations in a report must not inherit a current comparison.
            def fact_key(result):
                return digest({'value': result['value'], 'inputs': result['inputs']})
            facts = {fact_key(r) for r in (science or {}).get('results', [])}
            comparisons = [c for c in comparisons if c.get('science') and
                           {fact_key(r) for r in c['science']['results']} <= facts and
                           len(c['science']['results']) == 2]
            snapshots.append({'project_id': project['project_id'], 'revision': doc['revision'],
                'source_hash': doc['source_hash'], 'expectations': expectations,
                'comparisons': comparisons})
    return snapshots
