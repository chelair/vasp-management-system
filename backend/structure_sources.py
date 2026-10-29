"""Project-scoped, bounded structure readers. Never sync, mutate, inspect or submit."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat

from ai_inspections import task_for
from dates import now_iso
from task_paths import task_files_dir, task_remote_dir

MAX_BYTES = 1024 * 1024
SELECTOR_KEYS = {'task_id','file','source','directory','image','expected_sha256'}


def selector(value):
    if not isinstance(value,dict) or set(value)-SELECTOR_KEYS:
        raise ValueError('结构选择只接受任务、POSCAR/CONTCAR、来源、目录、映像与文件指纹')
    value = {'file':'CONTCAR','source':'local',**value}
    if not isinstance(value.get('task_id'),str) or not 1 <= len(value['task_id']) <= 200:
        raise ValueError('请先在当前项目定位结构任务')
    if value['file'] not in ('POSCAR','CONTCAR') or value['source'] not in ('local','remote'):
        raise ValueError('仅支持本地镜像或受限远端POSCAR/CONTCAR')
    if 'image' in value and (not isinstance(value['image'],str) or not re.fullmatch(r'[0-9]{2,3}',value['image'])):
        raise ValueError('NEB映像必须是00、01等数字目录')
    if 'expected_sha256' in value and (not isinstance(value['expected_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',value['expected_sha256'])):
        raise ValueError('结构指纹无效，请使用概览返回的完整sha256')
    if value['source'] == 'local':
        if 'directory' in value:
            raise ValueError('本地仅保存当前镜像，不含完整con历史；指定con目录请选remote')
    else:
        value.setdefault('directory','CURRENT')
        if not isinstance(value['directory'],str) or not re.fullmatch(r'CURRENT|MAIN|con[0-9]{1,6}',value['directory']):
            raise ValueError('远端目录仅支持CURRENT、MAIN或conN')
    return value


def _local(project,task,selection):
    from ai_workspace import directory, project_root
    root = project_root(project)
    base = task_files_dir(project['name'],task)
    try:
        relative = base.relative_to(root)
    except ValueError:
        raise ValueError('结构文件不在当前项目目录内') from None
    if '..' in relative.parts:
        raise ValueError('结构文件不能越过项目目录')
    if selection.get('image'):
        image = selection['image']
        base = base / ('neb_images' if (base/'neb_images'/image).is_dir() else '') / image
    try:
        with directory(base) as fd:
            file_fd = os.open(selection['file'],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
            with os.fdopen(file_fd,'rb') as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
                    raise ValueError('结构文件必须是非空普通文件，且不超过1 MiB')
                raw = stream.read(MAX_BYTES+1)
                after = os.fstat(stream.fileno())
            current = os.stat(selection['file'],dir_fd=fd,follow_symlinks=False)
    except OSError:
        raise ValueError('本地结构不存在或路径不可安全读取；可选择POSCAR或按需读取远端结构') from None
    identity = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if identity(before) != identity(after) or identity(before) != identity(current) or len(raw) != before.st_size:
        raise ValueError('结构文件正在变化，请稍后重新读取')
    snapshot = (task.get('input_state') or {}).get('source') or {}
    recorded = (task.get('last_structure_dirs') or {}).get(selection['file'])
    return raw, {'local_path':str(base/selection['file']), 'bytes':len(raw),'mtime_ns':before.st_mtime_ns,
        'modified_at':datetime.fromtimestamp(before.st_mtime).astimezone().isoformat(timespec='seconds'),
        'recorded_structure_directory': recorded, 'snapshot_directory':snapshot.get('remote_dir'),
        'remote_verified':False, 'directory_verified':False,
        'note':'本地最近镜像；登记目录不证明文件仍与远端一致，也不代表指定con历史快照。'}


# Fixed program only: model arguments never become Python or shell source.
_REMOTE_READ = r'''
import os,sys,json,re,stat,hashlib
from pathlib import Path
root=Path(sys.argv[1]); requests=json.loads(sys.argv[2]); limit=1048576

def open_dir(path):
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for name in path.absolute().parts[1:]:
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        return fd
    except BaseException:
        os.close(fd);raise

def read(folder,name):
    directory_fd=open_dir(folder)
    try:
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory_fd)
        with os.fdopen(fd,'rb') as f:
            before=os.fstat(f.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=limit:raise ValueError('structure must be a nonempty regular file <=1 MiB')
            raw=f.read(limit+1);after=os.fstat(f.fileno())
        current=os.stat(name,dir_fd=directory_fd,follow_symlinks=False)
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        if identity(before)!=identity(after) or identity(before)!=identity(current) or len(raw)!=before.st_size:raise ValueError('structure changed during read')
        return {'text':raw.decode('utf-8'),'bytes':len(raw),'mtime_ns':before.st_mtime_ns,'sha256':hashlib.sha256(raw).hexdigest()}
    finally:os.close(directory_fd)

# Resolve CURRENT once per task/batch, not separately for POSCAR and CONTCAR.
fd=open_dir(root);os.close(fd)
cons=sorted((p for p in root.iterdir() if re.fullmatch(r'con[0-9]{1,6}',p.name) and p.is_dir() and not p.is_symlink()),key=lambda p:int(p.name[3:]))
latest=cons[-1] if cons else root
rows=[]
for request in requests:
    try:
        folder=latest if request['directory']=='CURRENT' else root if request['directory']=='MAIN' else root/request['directory']
        resolved='MAIN' if folder==root else folder.name
        if request.get('image'):folder=folder/request['image']
        row=read(folder,request['file']);row.update(directory=resolved,remote_path=str(folder/request['file']))
        rows.append(row)
    except (OSError,ValueError,UnicodeError) as exc:rows.append({'error':str(exc)[:240]})
print(json.dumps(rows))
'''


def load_many(project, selections):
    values = [selector(value) for value in selections]
    tasks = [task_for(project,s['task_id']) for s in values]
    for task,s in zip(tasks,values):
        if task.get('task_type') == 'neb' and not s.get('image'):
            raise ValueError('NEB结构请指定映像编号（如01）；本地映像位置可先查工作区目录')
        if task.get('task_type') != 'neb' and s.get('image'):
            raise ValueError('仅NEB任务接受映像编号')
    records = [None]*len(values)
    remote = {}
    for i,(task,s) in enumerate(zip(tasks,values)):
        if s['source'] == 'local':
            records[i] = _local(project,task,s)
        else:
            remote.setdefault(task['task_id'],[]).append(i)
    if remote and not project.get('server'):
        raise ValueError('当前项目未配置远端服务器')
    for ids in remote.values():
        import ssh
        root = task_remote_dir(project['server'],tasks[ids[0]])
        if not root or not root.startswith('/') or '..' in Path(root).parts:
            raise ValueError('任务远端目录无效')
        command = 'python3 -c '+shlex.quote(_REMOTE_READ)+' '+shlex.quote(root)+' '+shlex.quote(json.dumps([values[i] for i in ids]))
        response = ssh.run_remote(project['server'],command,timeout=30)
        if response.get('exit_code') != 0:
            raise ValueError('远端结构读取失败，请检查连接和目录')
        try:
            rows = json.loads(response.get('stdout') or '')
        except (ValueError,TypeError):
            raise ValueError('远端结构返回格式无效') from None
        if not isinstance(rows,list) or len(rows) != len(ids):
            raise ValueError('远端结构返回数量不一致')
        for i,row in zip(ids,rows):
            if row.get('error'):
                raise ValueError('所选远端目录缺少结构、文件正在变化或不可读取；不自动回退其他目录')
            text = row.pop('text')
            raw = text.encode('utf-8')
            if not 0 < len(raw) <= MAX_BYTES or row.get('sha256') != hashlib.sha256(raw).hexdigest():
                raise ValueError('远端结构内容或指纹不完整')
            records[i] = raw, {**row,'remote_verified':True,'directory_verified':True}
    result = []
    for task,s,(raw,metadata) in zip(tasks,values,records):
        digest = hashlib.sha256(raw).hexdigest()
        if s.get('expected_sha256') and s['expected_sha256'] != digest:
            raise ValueError('结构文件已变化，请重新读取概览，不能沿用旧结构的原子环境或对比结果')
        try:
            text = raw.decode('utf-8')
        except UnicodeError:
            raise ValueError('结构文件必须是完整UTF-8文本') from None
        pinned = {**s,'expected_sha256':digest}
        if s['source'] == 'remote':
            pinned['directory'] = metadata['directory']
        source = {**metadata,'project_id':project['project_id'],'task_id':task['task_id'],
            'task_name':task.get('model_name'),'task_status':task.get('status'),
            'current_output_directory':(task.get('current_output') or {}).get('latest_dir'),
            'file':s['file'],'image':s.get('image'),
            'kind':s['source'],'sha256':digest,'hash_basis':'full_file','read_at':now_iso(),
            'selector':pinned}
        # A mirror hash is evidence of equality to that saved snapshot only.
        if s['source']=='local':
            meta = ((task.get('input_state') or {}).get('files') or {}).get(s['file']) or {}
            source['snapshot_hash_matches'] = meta.get('hash') == 'sha1:'+hashlib.sha1(text.encode()).hexdigest()[:16] if meta.get('hash') else None
        result.append((text,source))
    return result


def load_check_evidence(project, source, *companions):
    """Only called with a trusted source returned by load_many, never model paths."""
    import structure_check_evidence as probe
    task_for(project, source['task_id'])
    if source['kind'] == 'local':
        evidence = probe.probe(str(Path(source['local_path']).parent), source['file'], source['sha256'], *companions)
    else:
        import ssh
        script = Path(probe.__file__).read_text()
        args = [str(Path(source['remote_path']).parent), source['file'], source['sha256'], *companions]
        command = 'python3 -c ' + shlex.quote(script) + ' ' + ' '.join(shlex.quote(x) for x in args)
        response = ssh.run_remote(project['server'], command, timeout=30)
        if response.get('exit_code') != 0:
            raise ValueError('结构检查补证失败或结构正在变化，请重新读取；不跨目录补证')
        try:
            evidence = json.loads(response.get('stdout') or '')
        except (ValueError, TypeError):
            raise ValueError('结构检查补证格式无效') from None
    return {'files':evidence, 'directory':str(Path(source.get('remote_path') or source['local_path']).parent),
            'kind':source['kind'], 'read_at':now_iso(), 'co_run_verified':False,
            'note':'固定读取结构所在目录；同目录不证明这些输入曾用于该次输出。本地为镜像，OUTCAR仅采样；缺失/不稳定为未知。'}
