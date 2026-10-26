"""Shared audit append/rotation. Existing consumers keep the original JSON fields."""
from collections import deque
from datetime import datetime, timedelta
import gzip
import json
import os
from pathlib import Path
import re
import threading
import uuid

from config import DATA_DIR
from dates import now_iso

FILE = DATA_DIR / 'audit' / 'actions.jsonl'
LOCK = threading.RLock()
MAX_FILE = 16 * 1024 * 1024


def cleaned(value, depth=0):
    if depth > 5:
        return '[省略]'
    if isinstance(value,dict):
        return {str(k)[:80]:cleaned(v,depth+1) for k,v in list(value.items())[:60]
                if not re.search(r'(?i)password|secret|token|credential|api.?key|cookie|authorization',str(k))}
    if isinstance(value,(tuple,list)):
        return [cleaned(v,depth+1) for v in value[:60]]
    if isinstance(value,str):
        value = re.sub(r'(?i)\bsk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._+/-]{8,}', '[已隐藏]',value)
        value = re.sub(r'(?i)((?:password|api.?key|secret|access_token)\s*[=:]\s*)[^\s,;]+',r'\1[已隐藏]',value)
        return value[:1500]
    return value if value is None or isinstance(value,(bool,int,float)) else str(value)[:200]


def _rotate(path):
    if path.exists() and path.stat().st_size:
        path.replace(path.with_name('actions.'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.jsonl'))


def append(record, *, path=None, strict=False):
    path = Path(path or FILE)
    row = {**record, 'id':record.get('id') or uuid.uuid4().hex}
    with LOCK:
        path.parent.mkdir(parents=True,exist_ok=True)
        if path == FILE and path.exists() and path.stat().st_size >= MAX_FILE:
            _rotate(path)
        with path.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            if strict:
                stream.flush();os.fsync(stream.fileno())
    return row


def files(path=None):
    path = Path(path or FILE)
    return sorted(path.parent.glob('actions.*.jsonl*')) + ([path] if path.exists() else [])


def recent(limit=200, *, path=None, predicate=None):
    result = []
    with LOCK:
        for file in reversed(files(path)):
            try:
                opener = gzip.open if file.suffix == '.gz' else open
                with opener(file,'rt',encoding='utf-8',errors='replace') as stream:
                    # Bound memory independently of the size of old pre-upgrade logs.
                    lines = deque(stream,maxlen=20000)
                for line in reversed(lines):
                    try:
                        row=json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(row,dict) or predicate and not predicate(row):
                        continue
                    result.append(row)
                    if len(result)>=limit:
                        return result
            except (OSError,EOFError):
                continue
    return result


def record(project, task, command, details=None, result='OK'):
    """Best effort human-operation evidence; never blocks a completed business action."""
    try:
        import permissions
        user=permissions.current_user_from_context() or {}
        append({'at':now_iso(),'username':user.get('username') or '-', 'actor_id':user.get('user_id'),
                'automation':user.get('role')=='agent' or not bool(user),
                'project':project['name'],'project_id':project.get('project_id'),
                'task_id':task.get('task_id'),'task_type':task.get('task_type'),
                'remote_dir':task.get('remote_dir'),'job_id':task.get('job_id'),
                'command':command,'result':result,'details':cleaned(details or {})})
    except Exception:
        pass


def request_target(path, user):
    match=re.match(r'^/api/jobs/tasks/([^/]+)(?:/|$)',path)
    if not match:return None
    from storage import load_db
    import permissions
    for project in permissions.visible_projects(load_db(),user):
        task=next((t for t in project.get('tasks',[]) if t.get('task_id')==match[1]),None)
        if task:
            return project,task
    return None


def request_result(target, path, method, status):
    if not target:return
    project,task=target
    record(project,task,'http.'+method+' '+path,{'http_status':status,
        'before':{'status':task.get('status'),'job_id':task.get('job_id')},
        'note':'HTTP请求结果，不证明远端执行成功；具体结果以业务动作记录为准'},
        'OK' if status<400 else 'FAILED')


def submission_counts(legacy=None):
    import hashlib
    legacy=Path(legacy or DATA_DIR/'audit_submit.log')
    rollup=legacy.parent/'audit'/'submission_counts.json'
    with LOCK:
        counts=json.loads(rollup.read_text()) if rollup.exists() else {}
        raw=legacy.read_bytes() if legacy.exists() else b''
        offset=int(counts.get('_bytes',0))
        if offset>len(raw) or hashlib.sha256(raw[:offset]).hexdigest()!=counts.get('_sha256'):
            offset=0
        for line in raw[offset:].decode('utf-8',errors='replace').splitlines():
            match=re.match(r'^\[(\d{4}-\d{2}-\d{2})T',line)
            if match and 'result=OK' in line and 'job=' in line:
                counts[match[1]]=counts.get(match[1],0)+1
        return {k:v for k,v in counts.items() if not k.startswith('_')}


def compact():
    """Weekly small-file retention; legacy submit counts survive truncation."""
    import tempfile
    with LOCK:
        FILE.parent.mkdir(parents=True,exist_ok=True)
        _rotate(FILE)
        cutoff=(datetime.now()-timedelta(days=28)).timestamp()
        for file in list(FILE.parent.glob('actions.*.jsonl')):
            target=file.with_suffix(file.suffix+'.gz')
            with file.open('rb') as source,gzip.open(target,'wb') as dest:
                import shutil
                shutil.copyfileobj(source,dest)
            os.utime(target,(file.stat().st_mtime,file.stat().st_mtime))
            file.unlink()
        retained=sorted(FILE.parent.glob('actions.*.jsonl.gz'),key=lambda p:p.stat().st_mtime,reverse=True)
        size=0
        for file in retained:
            size+=file.stat().st_size
            if file.stat().st_mtime<cutoff or size>64*1024*1024:
                file.unlink()
        legacy=DATA_DIR/'audit_submit.log'
        rollup=FILE.parent/'submission_counts.json'
        if legacy.exists() and legacy.stat().st_size:
            import hashlib
            raw=legacy.read_bytes()
            counts=submission_counts(legacy)
            counts.update(_bytes=len(raw),_sha256=hashlib.sha256(raw).hexdigest())
            fd,tmp=tempfile.mkstemp(dir=rollup.parent,prefix='.counts-')
            with os.fdopen(fd,'w') as stream:
                json.dump(counts,stream);stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,rollup)
            legacy.write_text('',encoding='utf-8')
