"""单 OPT 的只读证据与保守科学判定。日志永远只是数据。"""
import json
import math
import re
import shlex

from automation import ledger, unknown
from dates import now_iso
from paths import resolve_remote_path

# 一次只读远端采样，不改变既有巡检/结构回传频率。POTCAR 仅保留摘要和元素。
_COLLECT = r'''
import hashlib, json, os, re, sys, time
from pathlib import Path
root = Path(sys.argv[1])
if root.is_symlink() or not root.is_dir(): raise ValueError('invalid task directory')
cons = sorted((p for p in root.iterdir() if re.fullmatch(r'con[0-9]+',p.name)), key=lambda p:int(p.name[3:]))
d = cons[-1] if cons else root
if d.is_symlink() or not d.is_dir() or d.resolve().parent != root.resolve() and d != root:
    raise ValueError('invalid continuation directory')
files = {}
for name in ('INCAR','POSCAR','CONTCAR','KPOINTS','POTCAR','vasp.lsf','OUTCAR','OSZICAR','result'):
    p = d / name
    if p.is_symlink(): raise ValueError('symlink input/output')
    if not p.is_file(): continue
    before = p.stat(); digest = hashlib.sha256(); titles = []; tail = b''
    with p.open('rb') as f:
        if name == 'POTCAR':
            for line in f:
                digest.update(line)
                if b'TITEL' in line: titles.append(line.decode('utf-8','replace').strip())
        else:
            # OUTCAR常达GB级；只读有界尾部，不在每次观察扫描整个输出。
            f.seek(max(0, before.st_size - 524288))
            tail = f.read(524288); digest.update(tail)
    after = p.stat()
    files[name] = {'size':before.st_size,'mtime':before.st_mtime,'sha256':digest.hexdigest(),
        'stable':(before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino),
        'truncated':name != 'POTCAR' and before.st_size > 524288,
        'hash_basis':'full' if name == 'POTCAR' or before.st_size <= 524288 else 'tail_524288_bytes',
        'text':'\n'.join(titles) if name == 'POTCAR' else tail.decode('utf-8','replace')}
print(json.dumps({'directory':str(d),'sampled_epoch':time.time(),'files':files}))
'''


def _owner_job(project, task):
    """作业号登记在主任务：续算子任务没有自己的 job_id 时沿父链找（2026-10-21）。"""
    current, seen = task, set()
    while current:
        job_id = str(current.get('job_id') or '')
        if job_id:
            return job_id
        parent_id = current.get('parent_task_id')
        if not parent_id or str(current.get('task_id')) in seen:
            break
        seen.add(str(current.get('task_id')))
        current = next((t for t in project['tasks'] if str(t.get('task_id')) == str(parent_id)), None)
    return ''


def collect(project, root_task):
    directory = resolve_remote_path(project['server'], root_task['remote_dir']).rstrip('/')
    value = json.loads(unknown.remote(project['server'], f"python3 - {shlex.quote(directory)} <<'OPT_READ_ONLY'\n{_COLLECT}\nOPT_READ_ONLY"))
    import ssh
    if ssh.mock_enabled() and value['directory'].startswith(str(ssh._mock_root())):
        value['directory'] = value['directory'][len(str(ssh._mock_root())):]
    if value['directory'] != directory and not re.fullmatch(re.escape(directory) + r'/con[0-9]+', value['directory']):
        raise ValueError('输出目录超出任务边界')
    matching = [t for t in project['tasks'] if resolve_remote_path(project['server'], t['remote_dir']).rstrip('/') == value['directory']]
    task = next((t for t in matching if t.get('job_id')), matching[0] if matching else {})
    job_id = _owner_job(project, task)
    rows = unknown.jobs(project['server'])
    row = next((r for r in rows if r['job_id'] == job_id and r['directory'].rstrip('/') == value['directory']), None)
    value.update(task_id=task.get('task_id'), job_id=job_id,
                 scheduler=row['state'] if row else 'UNKNOWN', checked_at=now_iso(), source='remote_readonly')
    if row and any(r['directory'].rstrip('/') == value['directory'] and r['job_id'] != row['job_id'] and r['state'] not in unknown.TERMINAL for r in rows):
        value['scheduler'] = 'UNKNOWN'
    value['termination_reason'] = unknown.termination_reason(project['server'], row) if row and row['state'] == 'EXIT' else None
    records = [a for a in ledger.read()['actions'].values() if a.get('job_id') == value['job_id'] and a.get('family_id') == root_task['task_id']]
    if records:
        record = records[-1]
        if not row or row['name'] != record.get('execution_name'):
            value['scheduler'] = 'UNKNOWN'
        value['submitted_at'] = record['created_at']
    # 证据身份只包含目录/作业/文件内容，不包含每次查询都会变化的时刻。
    value['id'] = ledger.fingerprint([value['directory'], value['job_id'], value['scheduler'], value['termination_reason'],
                                     {n:[f['sha256'],f['size'],f['mtime'],f['stable']] for n,f in value['files'].items()}])
    from checks_store import collect_task_observations
    observations = collect_task_observations(root_task['task_id'], limit=3)
    value['inspection_ids'] = [o['observation_id'] for o in observations]
    value['inspection_note'] = '巡检用于历史参考；当前尝试身份、SCF和输入完整性由远端只读补证，不把本地镜像当作当前结果'
    from ai_chat_service import clean
    return clean(value)


def _number(text):
    value = float(str(text).replace('D', 'E').replace('d', 'e'))
    if not math.isfinite(value):
        raise ValueError('非有限参数')
    return value


def structure(text):
    from batch_check import parse_poscar_layout
    layout = parse_poscar_layout(text)
    if not layout or not layout['species'] or layout['n_atoms'] <= 0 or any(n <= 0 for n in layout['counts']):
        raise ValueError('POSCAR元素/原子数不完整（要求VASP5格式）')
    lines = [s.strip() for s in text.splitlines()]
    if len(lines) < 8 or _number(lines[1]) <= 0:
        raise ValueError('暂不自动处理特殊晶格缩放格式')
    for line in lines[2:5]:
        if len(line.split()) != 3:
            raise ValueError('晶格不完整')
        for v in line.split():
            _number(v)
    index = next(i for i in range(7, len(lines)) if lines[i].lower() in ('direct','cartesian','d','c'))
    coords = lines[index + 1:index + 1 + layout['n_atoms']]
    if len(coords) != layout['n_atoms']:
        raise ValueError('原子坐标不完整')
    selective = any(s.lower().startswith('selective') for s in lines[7:index])
    for line in coords:
        parts = line.split()
        if len(parts) < 3:
            raise ValueError('坐标不完整')
        for v in parts[:3]:
            _number(v)
        if selective and parts[3:6] != ['T','T','T']:
            # 现有力分析把任一F视为全固定；初期不据此自动认定约束体系收敛。
            raise ValueError('约束体系力判据需人工复核')
    return layout


def diagnose(evidence):
    """不从HTTP成功、单一结束标记或LLM自述推断收敛。"""
    result = {'status':'UNKNOWN', 'diagnosis':'missing_evidence', 'electronic':'UNKNOWN',
              'ionic':'UNKNOWN', 'numerical_precision':'NOT_TESTED', 'science':'WARNING',
              'reason':'缺少完整证据', 'forces':[], 'checks':{}}
    files = evidence['files']
    text = lambda name: files.get(name, {}).get('text', '')
    if evidence['scheduler'] == 'UNKNOWN' or evidence['scheduler'] not in unknown.ACTIVE | unknown.TERMINAL:
        return {**result, 'diagnosis':'scheduler_unknown', 'reason':'作业身份或LSF状态未知；只能重新查询，禁止重提'}
    if evidence['scheduler'] in unknown.ACTIVE:
        return {**result, 'diagnosis':'running', 'reason':'调度器显示作业仍活跃，等待下一次巡检'}
    required = ('INCAR','POSCAR','KPOINTS','POTCAR','vasp.lsf','OUTCAR','OSZICAR','CONTCAR')
    missing = [n for n in required if not files.get(n, {}).get('size') or not files[n]['stable']]
    if missing:
        return {**result, 'reason':'必需文件缺失/写入中：' + ','.join(missing)}
    if any(files[n]['mtime'] > evidence['sampled_epoch'] + 5 for n in required):
        return {**result, 'diagnosis':'stale_output', 'reason':'文件时间超出远端采样时间，需核实时钟/尝试来源'}
    if any(files[n]['truncated'] for n in ('INCAR','POSCAR','CONTCAR','KPOINTS','vasp.lsf')):
        return {**result, 'reason':'输入超出解析上限'}
    if evidence.get('submitted_at'):
        from datetime import datetime
        submitted = datetime.fromisoformat(evidence['submitted_at']).timestamp()
        if any(files[n]['mtime'] < submitted - 2 for n in ('OUTCAR','OSZICAR','CONTCAR')):
            return {**result, 'diagnosis':'stale_output', 'reason':'输出早于本次提交，可能属于旧尝试/尚未同步'}
    try:
        from input_state import parse_incar_text
        if ';' in text('INCAR'):
            raise ValueError('暂不自动解析同一行多参数')
        params = parse_incar_text(text('INCAR'))
        nsw, nelm, ibrion = (int(params[k]) for k in ('NSW','NELM','IBRION'))
        ediff, ediffg = (_number(params[k]) for k in ('EDIFF','EDIFFG'))
        if nsw <= 0 or nelm <= 1 or ibrion not in (1,2) or ediff <= 0 or ediffg >= 0:
            raise ValueError('初期仅自动处理IBRION=1/2、负EDIFFG且显式NSW/NELM/EDIFF的OPT')
        pos, cont = structure(text('POSCAR')), structure(text('CONTCAR'))
        titles = re.findall(r'TITEL\s*=\s*\S+\s+([A-Z][a-z]?)(?:[_\s]|$)', text('POTCAR'))
        if titles != pos['species'] or pos['species'] != cont['species'] or pos['counts'] != cont['counts']:
            raise ValueError('POTCAR/POSCAR/CONTCAR元素顺序或原子数不一致')
        result.update(incar=params, nsw=nsw, nelm=nelm, force_threshold=abs(ediffg))
        result['checks'].update(inputs='PASS', elements='PASS')
    except (ValueError, KeyError, StopIteration, IndexError) as exc:
        return {**result, 'diagnosis':'invalid_input', 'reason':str(exc)}
    from batch_check import parse_total_force_blocks, diagnose_errors
    blocks = parse_total_force_blocks(text('OUTCAR'))
    if not blocks or any(len(b['forces']) != pos['n_atoms'] for b in blocks):
        return {**result, 'reason':'缺少完整原子力块'}
    result['forces'] = [max(math.sqrt(sum(v*v for v in f)) for f in b['forces']) for b in blocks]
    if not all(math.isfinite(f) for f in result['forces']):
        return {**result, 'reason':'原子力含非有限值'}
    # OSZICAR最后一个完整电子/离子周期；能量和本征值变化均小于EDIFF，且未耗尽NELM。
    out = text('OUTCAR')
    osz = text('OSZICAR')
    ionic_rows = list(re.finditer(r'^\s*(\d+)\s+F=\s*([-+\d.EeDd]+).*?E0=\s*([-+\d.EeDd]+)[^\n]*', osz, re.M))
    if not ionic_rows:
        return {**result, 'reason':'OSZICAR缺少完整离子步'}
    final = ionic_rows[-1]
    segment = osz[ionic_rows[-2].end():final.start()] if len(ionic_rows) > 1 else osz[:final.start()]
    scf = re.findall(r'^\s*(?:DAV|RMM|CG|DMP):\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)', segment, re.M)
    if not scf or osz[final.end():].strip():
        return {**result, 'reason':'OSZICAR电子周期不完整/末尾仍在计算'}
    try:
        last = scf[-1]
        electronic = int(last[0]) < nelm and abs(_number(last[2])) < ediff and abs(_number(last[3])) < ediff
        _number(final[2]); _number(final[3])
    except ValueError:
        return {**result, 'reason':'SCF数值不可解析'}
    iterations = re.findall(r'Iteration\s+(\d+)\s*\(', out)
    if (not iterations or int(iterations[-1]) != int(final[1]) or blocks[-1]['energy'] is None
            or not math.isfinite(blocks[-1]['energy'])
            or abs(blocks[-1]['energy'] - _number(final[2])) > max(ediff * 10, 1e-5)):
        return {**result, 'diagnosis':'incomplete_output', 'reason':'OUTCAR与OSZICAR最后离子步/能量不一致，不能认定当前输出完整'}
    result.update(electronic='PASS' if electronic else 'FAIL', step=int(final[1]),
                  ionic='PASS' if electronic and result['forces'][-1] < abs(ediffg) and 'reached required accuracy' in out else 'FAIL')
    errors, generic = diagnose_errors(out)
    if errors or generic or any(s in out for s in ('VERY BAD NEWS','ZBRENT: fatal','BRMIX: very serious')):
        return {**result, 'status':'FAILED', 'diagnosis':'new_error', 'reason':'出现未列入自动修复白名单的VASP错误，需人工复核'}
    completed = 'General timing and accounting informations' in out
    if completed and result['ionic'] == 'PASS' and evidence['scheduler'] == 'DONE':
        return {**result, 'status':'CONVERGED', 'diagnosis':'converged', 'reason':'电子、离子力、正常退出与调度结束交叉验证通过；物理性质可靠性与数值精度尚未证明'}
    if not electronic:
        return {**result, 'status':'FAILED', 'diagnosis':'scf_unconverged', 'reason':'电子自洽未通过；ALGO/混合/展宽/磁性修改仅建议人工评估'}
    if evidence['scheduler'] == 'EXIT' and evidence.get('termination_reason') == 'TERM_RUNLIMIT':
        return {**result, 'status':'FAILED', 'diagnosis':'walltime', 'reason':'LSF明确报告walltime上限，且存在可续算的完整输入输出'}
    if completed and evidence['scheduler'] == 'DONE' and int(final[1]) >= nsw and result['ionic'] == 'FAIL':
        return {**result, 'status':'COMPLETED', 'diagnosis':'nsw_limit', 'reason':'程序正常结束，但NSW耗尽且离子力未收敛'}
    return {**result, 'status':'COMPLETED' if completed else 'UNKNOWN', 'diagnosis':'incomplete_output',
            'reason':'输出与结束/收敛证据不充分，需人工确认'}
