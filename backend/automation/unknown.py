"""只读LSF对账；查不到不等于失败，不据此重提。远端访问仅复用ssh。"""
import base64
import re
import shlex

import ssh
from config import load_servers

ACTIVE = {'PEND', 'RUN', 'PSUSP', 'USUSP', 'SSUSP', 'WAIT', 'PROV'}
TERMINAL = {'DONE', 'EXIT'}


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
        'OUT=$(bjobs -a -noheader -o \'jobid stat exec_cwd:4096 job_name:128 delimiter="|"\' 2>&1)',
        'RC=$?',
        'if [ "$RC" -ne 0 ]; then',
        '  case "$OUT" in *"No unfinished job found"*|*"No job found"*) OUT="" ;; *) exit 9 ;; esac',
        'fi', 'printf "%s\\n" "$OUT"',
    ])


def parse_jobs(output):
    result = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.strip().strip('|').split('|')]
        if len(parts) != 4 or not re.fullmatch(r'\d+', parts[0]) or parts[1] not in ACTIVE | TERMINAL | {'UNKWN', 'ZOMBI'}:
            raise ValueError('LSF输出无法可靠解析，需人工核实')
        if ssh.mock_enabled() and parts[2].startswith(str(ssh._mock_root())):
            parts[2] = parts[2][len(str(ssh._mock_root())):]
        result.append({'job_id': parts[0], 'state': parts[1], 'directory': parts[2], 'name': parts[3]})
    return result


def jobs(server):
    return parse_jobs(remote(server,jobs_script(server)))


def find(record, rows):
    matches = [row for row in rows if row['name'] == record.get('execution_name') and
               (not record.get('job_id') or row['job_id'] == str(record['job_id']))]
    if len(matches) != 1:
        return None
    return matches[0]


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
