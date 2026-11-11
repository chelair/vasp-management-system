"""只读LSF对账；查不到不等于失败，不据此重提。远端访问仅复用ssh。"""
import base64
import re
import shlex
import json

import ssh
from config import load_servers
from lsf_state import ACTIVE, TERMINAL, FORMAT, parse_jobs as parse_lsf_jobs



def remote(server, script):
    encoded = base64.b64encode(script.encode()).decode('ascii')
    result = ssh.run_remote(server, f'echo {encoded} | base64 -d | bash', timeout=45)
    if result.get('exit_code') != 0:
        raise ValueError('SSH/LSF查询失败，远端状态未知，禁止重复提交')
    return str(result.get('stdout') or '')


def jobs_script(server):
    profile = load_servers().get(server, {}).get('lsf_profile', '/opt/ibm/lsfsuite/lsf/conf/profile.lsf')
    return '\n'.join([
        'export LC_ALL=C', f'source {shlex.quote(profile)} >/dev/null 2>&1 || true',
        'OUT=$(bjobs -a -noheader -o ' + shlex.quote(FORMAT) + ' 2>&1)',
        'RC=$?',
        'if [ "$RC" -ne 0 ]; then',
        '  case "$OUT" in *"No unfinished job found"*|*"No job found"*) OUT="" ;; *) exit 9 ;; esac',
        'fi', r'OUT=${OUT//\$HOME/$HOME}', 'printf "%s\\n" "$OUT"',
    ])


def parse_jobs(output):
    result = parse_lsf_jobs(output)
    if ssh.mock_enabled():
        prefix = str(ssh._mock_root())
        for row in result:
            if row['directory'].startswith(prefix):
                row['directory'] = row['directory'][len(prefix):]
    return result


def jobs(server):
    return parse_jobs(remote(server,jobs_script(server)))


def find(record, rows):
    """已知作业号按 ID 和目录匹配；丢失回执时查找目标目录唯一作业。"""
    directory = str((record.get('plan') or {}).get('work_dir') or '').rstrip('/')
    if not directory:
        return None
    matches = [row for row in rows if row['directory'].rstrip('/') == directory]
    if record.get('job_id'):
        matches = [row for row in matches if row['job_id'] == str(record['job_id'])]
    else:
        active = [row for row in matches if row['state'] not in TERMINAL]
        if active:
            matches = active
    return matches[0] if len(matches) == 1 else None


def prior_job_receipts(server, root, job_id):
    """Bounded read of the named LSF receipt in root/conN; never execution authority."""
    if not re.fullmatch(r'[0-9]+', str(job_id)):
        return []
    script = r'''
import json,sys,re
from pathlib import Path
root=Path(sys.argv[1]).resolve(); job=sys.argv[2]
dirs=[root]+sorted([p for p in root.iterdir() if re.fullmatch(r'con[0-9]+',p.name) and p.is_dir()],key=lambda p:int(p.name[3:]),reverse=True)[:100]
rows=[]
for directory in dirs:
    path=directory/(job+'.out')
    if not path.is_file(): continue
    try: path.resolve().relative_to(root)
    except ValueError: continue
    with path.open('rb') as f:
        head=f.read(4096).decode('utf-8','replace').splitlines()[:14]
        f.seek(max(0,path.stat().st_size-4096))
        tail=f.read(4096).decode('utf-8','replace').splitlines()[-22:]
    rows.append({'directory':str(directory),'file':path.name,'size':path.stat().st_size,'text':'\n'.join(head+['…']+tail)})
    if len(rows)>=3: break
print(json.dumps(rows))
'''
    output = remote(server, f"python3 - {shlex.quote(root)} {shlex.quote(str(job_id))} <<'PRIOR_JOB_READ_ONLY'\n{script}\nPRIOR_JOB_READ_ONLY")
    rows = json.loads(output)
    if ssh.mock_enabled():
        prefix = str(ssh._mock_root())
        for row in rows:
            if row['directory'].startswith(prefix):
                row['directory'] = row['directory'][len(prefix):]
    return rows


def termination_reason(server, row):
    """结束原因必须来自LSF本身且身份一致，不能从用户可写的result日志授权续算。"""
    if not re.fullmatch(r'\d+', row['job_id']):
        return 'UNKNOWN'
    profile = load_servers().get(server, {}).get('lsf_profile', '/opt/ibm/lsfsuite/lsf/conf/profile.lsf')
    try:
        output = remote(server, '\n'.join([
            'export LC_ALL=C', f'source {shlex.quote(profile)} >/dev/null 2>&1 || true',
            f'bjobs -l {row["job_id"]} 2>/dev/null | head -c 65536',
        ]))
    except ValueError:
        return 'UNKNOWN'
    # LSF可能换行缩进，名称内空白不放宽；识别失败即暂停。
    compact = re.sub(r'\n\s+', '', output)
    if f'Job <{row["job_id"]}>' not in compact or f'Job Name <{row["name"]}>' not in compact:
        return 'UNKNOWN'
    return 'TERM_RUNLIMIT' if re.search(r'\bTERM_RUNLIMIT\b', compact) else 'UNKNOWN'
