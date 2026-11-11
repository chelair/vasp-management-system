"""LSF current-state parsing shared by inspection, reconciliation and continuation."""
import re
import subprocess
import sys

ACTIVE = {'PEND', 'RUN', 'PSUSP', 'USUSP', 'SSUSP', 'WAIT', 'PROV'}
TERMINAL = {'DONE', 'EXIT'}
UNCERTAIN = {'UNKWN', 'ZOMBI'}
FORMAT = 'jobid stat exec_cwd:4096 job_name:128 delimiter="|"'


def empty_jobs(output):
    return bool(re.fullmatch(r'\s*(?:No unfinished job found|No job found)\.?\s*', output, re.I))


def parse_jobs(output):
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.strip().strip('|').split('|')]
        if len(parts) != 4 or not re.fullmatch(r'\d+', parts[0]) or parts[1] not in ACTIVE | TERMINAL | UNCERTAIN:
            raise ValueError('LSF输出无法可靠解析，作业状态尚未确认')
        rows.append(dict(zip(('job_id', 'state', 'directory', 'name'), parts)))
    return rows


def query_jobs(timeout=5):
    proc = subprocess.run(['bjobs', '-a', '-noheader', '-o', FORMAT], capture_output=True, text=True, timeout=timeout)
    output = (proc.stdout or '') + (proc.stderr or '')
    if empty_jobs(output):
        return []
    if proc.returncode:
        raise RuntimeError('调度器查询失败，作业状态尚未确认：' + output.strip()[:300])
    return parse_jobs(proc.stdout or '')


def normalized(state):
    if state in {'PSUSP', 'USUSP'}:
        return 'SSUSP'
    if state in {'WAIT', 'PROV'}:
        return 'PEND'
    return state if state in ACTIVE | TERMINAL else 'UNKNOWN'


def parse_detail(output, returncode):
    compact = re.sub(r'\s+', ' ', output)
    match = re.search(r'Status\s*<\s*([^>]+?)\s*>', compact)
    if match:
        return normalized(re.sub(r'\s+', '', match[1]).upper())
    if re.fullmatch(r'\s*(?:Job\s*<\d+>\s*(?::|is)?\s*)?(?:No matching job found|No job found|not found)\.?\s*', output, re.I):
        return 'NOT_FOUND'
    if not returncode and output.strip() in ACTIVE | TERMINAL:
        return normalized(output.strip())
    return 'UNKNOWN'


if __name__ == '__main__':
    # Continuation embeds this module so the check and subsequent file operation
    # remain in the same remote command, including before the first inspection.
    try:
        target = sys.argv[1].rstrip('/')
        rows = query_jobs()
        registered = sys.argv[2] if len(sys.argv) > 2 else ''
        if any(r['job_id'] == registered and r['state'] not in TERMINAL and r['directory'] in ('', '-') for r in rows):
            raise ValueError('登记作业的工作目录尚未确认')
        row = next((r for r in rows if r['directory'].rstrip('/') == target and r['state'] not in TERMINAL), None)
        print(row['job_id'] + ' ' + row['state'] if row else '- -')
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print('调度器状态未确认，未创建续算目录：' + str(exc), file=sys.stderr)
        sys.exit(9)
