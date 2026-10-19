"""保守解析LSF资源申请并核对上限；核时是最坏情况预留，不是计费。"""
import math
import re
import shlex


class BudgetError(ValueError):
    pass


def limits(payload):
    result = {}
    for key, default, integer in (
        ('max_active_jobs', 1, True), ('max_submissions', 3, True), ('max_retries', 1, True),
        ('max_core_hours', None, False), ('max_walltime_hours', None, False), ('max_cores', None, True),
    ):
        raw = payload.get(key, default)
        if raw is None or isinstance(raw, bool):
            raise BudgetError(f'必须显式配置有效的 {key}')
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise BudgetError(f'{key} 必须是数字') from None
        if not math.isfinite(value) or value < (0 if key == 'max_retries' else 0.000001) or (integer and not value.is_integer()):
            raise BudgetError(f'{key} 超出允许范围')
        result[key] = int(value) if integer else value
    return result


def parse_lsf(text):
    """只接受可验证的单作业静态脚本；未知资源选项拒绝自动执行。

    资源/队列必须在 #BSUB 中给定，禁止动态环境、job array、多个资源请求、嵌套提交。
    脚本其余内容仍是现有受信任人工脚本，LLM不能写或替换它。
    """
    options = {}
    allowed = {'-n', '-W', '-q', '-J', '-o', '-e', '-R', '-M'}
    for line in text.splitlines():
        if not line.startswith('#BSUB'):
            if re.search(r'\bbsub\b', line) and not line.lstrip().startswith('#'):
                raise BudgetError('禁止脚本内嵌套提交')
            continue
        if any(char in line for char in ('$', '`', '\\')):
            raise BudgetError('不能可靠解析动态LSF指令')
        try:
            parts = shlex.split(line[5:].strip())
        except ValueError:
            raise BudgetError('LSF指令引号不完整') from None
        if len(parts) != 2 or parts[0] not in allowed or parts[0] in options:
            raise BudgetError('不支持的、重复的或组合LSF指令')
        options[parts[0]] = parts[1]
    if not re.fullmatch(r'[1-9]\d*', options.get('-n', '')):
        raise BudgetError('必须声明固定正整数 #BSUB -n')
    match = re.fullmatch(r'(\d+):(\d{2})', options.get('-W', ''))
    if not match or int(match[2]) >= 60:
        raise BudgetError('必须声明 #BSUB -W 小时:分钟')
    hours = int(match[1]) + int(match[2]) / 60
    if hours <= 0:
        raise BudgetError('walltime必须大于0')
    queue = options.get('-q', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', queue):
        raise BudgetError('必须显式声明单个队列 #BSUB -q')
    if '[' in options.get('-J', '') or ']' in options.get('-J', ''):
        raise BudgetError('不支持job array')
    if re.search(r'(?i)ngpus|gpu|\btile\b', options.get('-R', '')):
        raise BudgetError('暂不支持GPU等异构资源')
    request = options.get('-R', '')
    if request and not re.fullmatch(r'(?:span\[(?:ptile|hosts)=[1-9]\d*\]|rusage\[mem=[1-9]\d*\])(?:\s+(?:span\[(?:ptile|hosts)=[1-9]\d*\]|rusage\[mem=[1-9]\d*\]))*', request):
        raise BudgetError('资源表达式未在已验证CPU子集中，不能可靠估算')
    cores = int(options['-n'])
    return {'cores': cores, 'walltime_hours': hours, 'core_hours': cores * hours, 'queue': queue}


def reserve_check(doc, grant, resources, *, family_id, action, submitting):
    related = [a for a in doc['actions'].values() if a.get('grant_id') == grant['id']]
    policy = grant['limits']
    # 失败、跳过均计入尝试；未知未解除前不能用新幂等键绕过。
    attempts = [a for a in related if a['family_id'] == family_id and a['action'] == action and a.get('attempted')]
    if len(attempts) >= 1 + policy['max_retries']:
        raise BudgetError('已达到该节点自动尝试/重试上限')
    if not submitting:
        return 0
    if resources['queue'] != grant['queue']:
        raise BudgetError('队列与授权不符；不同资源池不得混算')
    if resources['cores'] > policy['max_cores'] or resources['walltime_hours'] > policy['max_walltime_hours']:
        raise BudgetError('申请核心数或walltime超过授权上限')
    if sum(bool(a.get('submission_attempted')) for a in related) >= policy['max_submissions']:
        raise BudgetError('已达到自动提交次数上限')
    active = [a for a in related if a.get('reservation', 0) > 0]
    if len(active) >= policy['max_active_jobs']:
        raise BudgetError('已达到活跃作业上限')
    used = sum(a.get('reservation', 0) + a.get('consumed_core_hours', 0) for a in related)
    if used + resources['core_hours'] > policy['max_core_hours'] + 1e-9:
        raise BudgetError('核时预算不足')
    return resources['core_hours']
