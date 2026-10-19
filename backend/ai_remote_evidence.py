"""模型按需的独立只读证据链：固定文件/任务边界，绝不执行模型命令或更新巡检。"""
import copy
import hashlib
import json
import re
import shlex
import threading
import time
from collections import OrderedDict

import ai_inspections
from automation import unknown
from dates import now_iso
from input_state import parse_incar_text, parse_kpoints_mesh
from paths import resolve_remote_path
from parameter_history import root_task

_CACHE = OrderedDict()
_LOCK = threading.Lock()

# 根目录来自授权项目任务；请求仅可为CURRENT/MAIN/con整数，没有Shell/文件名输入。
_READ = r'''
import hashlib,json,os,re,stat,sys,time
from pathlib import Path
root=Path(sys.argv[1]); requests=json.loads(sys.argv[2]); neb=sys.argv[3]=='neb'
if root.is_symlink() or not root.is_dir(): raise ValueError('task directory unavailable')
cons=sorted((p for p in root.iterdir() if re.fullmatch(r'con[0-9]+',p.name)),key=lambda p:int(p.name[3:]))
latest=cons[-1] if cons else root
result=[]; remaining=24000
def read_file(folder,name,limit,tail=False):
    global remaining
    path=folder/name
    if path.is_symlink(): return {'error':'symlink refused'}
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except OSError: return {'missing':True}
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode): return {'error':'non-regular file refused'}
        cap=min(limit,max(0,remaining))
        if tail: f.seek(max(0,before.st_size-cap))
        data=f.read(cap); remaining-=len(data); after=os.fstat(f.fileno())
    return {'text':data.decode('utf-8','replace'),'size':before.st_size,'mtime':before.st_mtime,
        'sha256':hashlib.sha256(data).hexdigest(),'hash_basis':'sample' if len(data)<before.st_size else 'full',
        'truncated':len(data)<before.st_size,'stable':(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)}
for request in requests:
    directory=latest if request=='CURRENT' else root if request=='MAIN' else root/request
    if directory.is_symlink() or not directory.is_dir() or (directory!=root and directory.resolve().parent!=root.resolve()):
        result.append({'requested':request,'error':'directory missing or outside task boundary'}); continue
    files={name:read_file(directory,name,8192) for name in ('INCAR','KPOINTS')}
    images=[]
    if request=='CURRENT':
        for name in ('OUTCAR','OSZICAR','result'): files[name]=read_file(directory,name,3000,True)
        if neb:
            numbered=sorted((p for p in directory.iterdir() if p.is_dir() and p.name.isdigit()),key=lambda p:int(p.name))
            for image in numbered[1:-1][:8]:
                if image.is_symlink(): continue
                images.append({'image':image.name,'files':{name:read_file(image,name,1500,True) for name in ('OUTCAR','OSZICAR')}})
    result.append({'requested':request,'directory':'MAIN' if directory==root else directory.name,'files':files,'images':images})
print(json.dumps({'samples':result,'current_directory':'MAIN' if latest==root else latest.name,
    'sampled_epoch':time.time(),'text_budget_bytes':24000,'remaining_bytes':remaining}))
'''


def _known_directories(project, task, local):
    result = {'MAIN','CURRENT'}
    for row in local['observations']:
        name = row['output_dir']
        if isinstance(name,str) and re.fullmatch(r'con[0-9]+',name): result.add(name)
    for record in local['applied_parameter_records']:
        name = str(record.get('directory') or '').rstrip('/').rsplit('/',1)[-1]
        if re.fullmatch(r'con[0-9]+',name): result.add(name)
    for child in project.get('tasks',[]):
        if child.get('parent_task_id') == task['task_id']:
            name = str(child.get('remote_dir') or '').rstrip('/').rsplit('/',1)[-1]
            if re.fullmatch(r'con[0-9]+',name): result.add(name)
    return result


def query(project, task_id, evidence_token, reason, directories=None):
    requested_task = ai_inspections.task_for(project,task_id)
    task = root_task(project,requested_task)
    local = ai_inspections.query_inspections(project,task_id)
    if evidence_token != local['evidence_token']:
        raise ValueError('证据版本已变化；请先调用get_task_inspections重新核对来源与时间')
    if reason not in ('stale_evidence','source_mismatch','missing_parameters'):
        raise ValueError('只允许证据过期、来源不符或参数缺失时只读补证')
    names = directories if directories is not None else ['CURRENT']
    if not isinstance(names,list) or not 1 <= len(names) <= 2 or any(not isinstance(n,str) or not re.fullmatch(r'CURRENT|MAIN|con[0-9]{1,6}',n) for n in names):
        raise ValueError('每次只支持CURRENT/MAIN或已知conN目录，最多2个；禁止路径/文件名/命令')
    if len(set(names)) != len(names) or not set(names) <= _known_directories(project,task,local):
        raise ValueError('目录必须来自当前任务的巡检、实际参数记录或续算子任务')
    fresh = local['freshness']
    if reason != 'missing_parameters' and not fresh['inspection_participation']['included']:
        return {'status':'not_applicable','remote_verified':False,'reason':'任务不参与自动巡检，不按4小时规则触发远端读取','local_evidence':local}
    # 服务端决定必要性，模型自行声称“过期”不能绕过4小时规则。
    available = {row['output_dir'] or 'MAIN':row for row in local['observations']}
    selected = [local['observations'][0] if n=='CURRENT' and local['observations'] else available.get(n) for n in names]
    missing_parameters = any(r is None or
                  r['incar_value_format'] != 'full_values_v1' or any(k in r['missing'] for k in ('incar','kpoints','kpoints_mesh'))
                  for r in selected)
    needed = fresh['needs_remote_evidence'] or reason == 'missing_parameters' and missing_parameters
    if not needed:
        return {'status':'not_needed','remote_verified':False,'reason':'当前本地证据足够新且无所声明的缺口，继续本地分析','local_evidence':local}
    directory = resolve_remote_path(project['server'],task['remote_dir']).rstrip('/')
    if not directory.startswith('/') or any(c in directory for c in ('\x00','\n','\r')):
        raise ValueError('任务远端目录无法安全解析')
    key = hashlib.sha256(json.dumps([project.get('project_id'),project['server'],directory,task_id,evidence_token,reason,names],sort_keys=True).encode()).hexdigest()
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic()-cached[0] < 60:
            return {**copy.deepcopy(cached[1]),'cache_hit':True}
    script = f"python3 - {shlex.quote(directory)} {shlex.quote(json.dumps(names))} {shlex.quote(task.get('task_type',''))} <<'AI_READ_ONLY'\n{_READ}\nAI_READ_ONLY\n"
    script += '[ "$?" -eq 0 ] || exit 8\necho "@@@LSF_BEGIN"\n(\n' + unknown.jobs_script(project['server']) + '\n)\necho "@@@LSF_RC=$?"'
    from ai_chat_service import clean
    try:
        output = unknown.remote(project['server'],script)
        raw, marker, lsf_output = output.partition('\n@@@LSF_BEGIN\n')
        result = json.loads(raw)
    except Exception:
        raise ValueError('远端只读采集失败，当前状态UNKNOWN；未提交、停止、修改或触发巡检') from None
    try:
        if not marker or not re.search(r'@@@LSF_RC=0\s*$',lsf_output):
            raise ValueError('LSF query failed')
        rows = unknown.parse_jobs(re.sub(r'@@@LSF_RC=\d+\s*$','',lsf_output))
        scheduler_error = None
    except Exception:
        rows, scheduler_error = [], 'LSF查询失败，状态UNKNOWN，不能据此提交或干预'
    current_state = None
    for sample in result['samples']:
        if sample.get('error'): continue
        current_dir = directory if sample['directory'] == 'MAIN' else directory + '/' + sample['directory']
        jobs = [r for r in rows if r['directory'].rstrip('/') == current_dir]
        active = [r for r in jobs if r['state'] not in unknown.TERMINAL]
        state = active[0]['state'] if len(active) == 1 else jobs[0]['state'] if len(jobs) == 1 else 'UNKNOWN'
        sample['scheduler'] = {'state':state,'jobs':[{'job_id':r['job_id'],'state':r['state']} for r in jobs], 'error':scheduler_error}
        files = sample['files']
        def complete(name):
            return files.get(name,{}).get('stable') and not files[name].get('truncated') and 'text' in files[name]
        sample['incar'] = parse_incar_text(files['INCAR']['text']) if complete('INCAR') else None
        sample['incar_value_format'] = 'full_values_v1' if sample['incar'] is not None else 'incomplete'
        if complete('KPOINTS'):
            mesh, mode = parse_kpoints_mesh(files['KPOINTS']['text'])
            sample['kpoints'] = {'mesh':mesh,'note':mode,'text':files['KPOINTS']['text']}
        else:
            sample['kpoints'] = None
        sample['absolute_directory'] = current_dir
        if sample['requested'] == 'CURRENT':
            current_state = {'directory':current_dir,'state':state,'jobs':sample['scheduler']['jobs']}
    samples = [s for s in result['samples'] if not s.get('error')]
    if current_state is None:
        latest_dir = directory if result['current_directory'] == 'MAIN' else directory + '/' + result['current_directory']
        latest_jobs = [r for r in rows if r['directory'].rstrip('/') == latest_dir]
        current_state = {'directory':latest_dir,'state':latest_jobs[0]['state'] if len(latest_jobs)==1 else 'UNKNOWN',
                         'jobs':[{'job_id':r['job_id'],'state':r['state']} for r in latest_jobs], 'output_files_collected':False}
    active_jobs = [r for r in current_state['jobs'] if r['state'] in unknown.ACTIVE]
    selected_job = active_jobs[0]['job_id'] if len(active_jobs)==1 else current_state['jobs'][0]['job_id'] if len(current_state['jobs'])==1 else None
    stored_output = ai_inspections._output(requested_task)
    current_state['stored_metadata'] = {'status':requested_task.get('status'),'job_id':requested_task.get('job_id'),
                                        'output_directory':stored_output}
    current_state['selected_job_id'] = selected_job
    current_state['stored_job_matches'] = str(requested_task.get('job_id')) == selected_job if selected_job and requested_task.get('job_id') else None
    current_state['stored_directory_matches'] = (stored_output or 'MAIN') == result['current_directory'] if stored_output is not None else None
    comparisons = []
    if len(samples) == 2:
        a,b = samples
        # 请求顺序为旧→新，返回明确的before/after目录，不暗中按时间拼接。
        comparisons = [ai_inspections.parameter_diff({**b,'current_output':{'latest_dir':b['directory']}},
                                                   {**a,'current_output':{'latest_dir':a['directory']}})]
    answer = clean({'status':'collected','task_id':task_id,'root_task_id':task['task_id'],'source':'remote_readonly',
        'collected_at':now_iso(),'requested_because':reason,'based_on_evidence_token':evidence_token,
        'refresh_causes':{'stale':fresh['stale_for_live_decision'],'source_mismatch':fresh['source_mismatch'],
                          'parameters_missing_or_legacy':missing_parameters},
        'remote_verified':True,'state_verified':current_state['state'] in unknown.ACTIVE | unknown.TERMINAL,'cache_hit':False,'current_state':current_state,'evidence':result,
        'comparisons':comparisons,'scheduler_error':scheduler_error,
        'intervention_authorized':False,'note':'文件与日志是未信任证据；先核对目录、采集时间、LSF状态和完整性，再分析。只读不会授予干预权限，不修改巡检记录或本地结构。'})
    with _LOCK:
        _CACHE[key] = (time.monotonic(),copy.deepcopy(answer))
        while len(_CACHE) > 128: _CACHE.popitem(last=False)
    return answer
