"""已实际上传/应用/提交的参数证据；草稿不入账，任务族最多保留5次。"""
import copy
import hashlib
import json
import uuid

from dates import now_iso
from input_state import parse_incar_text, parse_kpoints_mesh
from task_paths import is_continuation_task

LIMIT = 5


def parameters(texts):
    result = {}
    if texts.get('INCAR') is not None:
        result['INCAR'] = parse_incar_text(texts['INCAR'])
    if texts.get('KPOINTS') is not None:
        text = texts['KPOINTS']
        mesh, mode = parse_kpoints_mesh(text)
        result['KPOINTS'] = {'mesh':mesh, 'mode':mode, 'text':text}
    return result


def diff(before, after):
    """缺少旧快照不当作参数新增；未采集的文件不当作参数删除。"""
    result = []
    for name in ('INCAR','KPOINTS'):
        if name not in after:
            continue
        old, new = before.get(name), after[name]
        if name == 'INCAR':
            for key in sorted(set(old or {}) | set(new or {})):
                if old is None or (old or {}).get(key) != (new or {}).get(key):
                    result.append({'file':name,'key':key,'before':(old or {}).get(key),
                                   'after':(new or {}).get(key),'baseline_known':old is not None})
        elif old is None or old != new:
            result.append({'file':name,'key':'KPOINTS','before':old,'after':new,'baseline_known':old is not None})
    return result


def append(state, *, event, directory, before, after, job_id=None, source_directory=None):
    if event not in ('upload','continuation','submit'):
        raise ValueError('仅记录实际上传、续算应用或成功提交，草稿不计入历史')
    if not after:
        return state
    state = copy.deepcopy(state or {})
    record = {'id':uuid.uuid4().hex,'at':now_iso(),'event':event,'directory':directory,
              'source_directory':source_directory,'job_id':str(job_id) if job_id else None,
              'before':copy.deepcopy(before),'after':copy.deepcopy(after),'changes':diff(before,after),
              'parameters_sha256':hashlib.sha256(json.dumps(after,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
              'semantics':'remote_inputs_written' if event != 'submit' else 'inputs_captured_before_accepted_submission',
              'note':'输入文件证据；上传/续算写入不代表运行中的VASP已重读，提交快照不证明收敛'}
    state['applied_history'] = (state.get('applied_history',[]) + [record])[-LIMIT:]
    return state


def root_task(project, task):
    seen = set()
    while is_continuation_task(task) and task.get('parent_task_id'):
        if task['task_id'] in seen:
            raise ValueError('任务续算关系成环')
        seen.add(task['task_id'])
        parent = next((t for t in project.get('tasks',[]) if t['task_id'] == task['parent_task_id']),None)
        if parent is None:
            raise ValueError('续算父任务不存在')
        task = parent
    return task


def record_in_db(db, task_id, **values):
    for project in db.get('projects',[]):
        task = next((t for t in project.get('tasks',[]) if t['task_id'] == task_id),None)
        if task is not None:
            parent = root_task(project,task)
            parent['input_state'] = append(parent.get('input_state') or {}, **values)
            from operation_audit import record
            record(project,parent,'parameters.'+values['event'],{
                'directory':values.get('directory'),'job_id':values.get('job_id'),
                'changes':diff(values.get('before',{}),values.get('after',{})),
                'semantics':'输入已写入/提交快照；不代表运行中的VASP已重读或已收敛'})
            return
    raise ValueError('参数历史对应任务不存在')


def records(project, task):
    return copy.deepcopy((root_task(project,task).get('input_state') or {}).get('applied_history',[])[-LIMIT:][::-1])


def summaries(values):
    def preview(value):
        if isinstance(value,str) and len(value)>500:
            return {'preview':value[:500],'truncated':True,'total_chars':len(value)}
        if isinstance(value,dict):
            return {k:preview(v) for k,v in value.items()}
        if isinstance(value,list):
            return [preview(v) for v in value]
        return value
    return [{**{k:r.get(k) for k in ('id','at','event','directory','source_directory','job_id','semantics','parameters_sha256','note')},
             'changed_count':len(r['changes']), 'changes':preview(r['changes'][:20]), 'changes_truncated':len(r['changes']) > 20}
            for r in values]


def query(project, task, record_id=None, offset=0):
    values = records(project,task)
    if record_id is None:
        return {'task_id':task['task_id'],'retention_limit':LIMIT,'records':summaries(values),
                'drafts_included':False, 'more':'指定record_id分页读取该次实际参数快照；旧记录缺失不补造'}
    record = next((r for r in values if r['id'] == record_id),None)
    if not record:
        raise ValueError('参数记录已超出最近5次范围或不属于当前任务')
    items = [{'file':name,'key':key,'value':value} for name, data in record['after'].items()
             for key,value in (data.items() if isinstance(data,dict) else [('value',data)])]
    selected, used = [], 0
    for item in items[offset:offset+40]:
        size = len(json.dumps(item,ensure_ascii=False))
        if used+size > 16000:
            if not selected:
                raise ValueError('该参数超过单页预算，请通过文件工具读取原文')
            break
        selected.append(item); used += size
    return {'task_id':task['task_id'],'record_id':record_id,'directory':record['directory'],'at':record['at'],
            'event':record['event'],'job_id':record.get('job_id'),'items':selected,'total':len(items),
            'next_offset':offset+len(selected) if offset+len(selected) < len(items) else None}
