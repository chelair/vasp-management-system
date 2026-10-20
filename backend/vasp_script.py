"""VASP LSF 提交脚本的后端受控渲染与校验（托管的资源方案 → 脚本 → 提交前检查）。

模板以 `src/utils/vaspLsf.ts` 的八段结构为准（S1 头 → S2 BSUB → S3 变量 → S4 环境
→ S5 日志 → S6 软结束 → S7 主运行 → S8 收尾）。本模块只负责"资源方案决定的部分"，
固定段与前端模板逐行一致，并由 `tests/test_vasp_script.py` 做漂移检查。

不在这里提交作业：渲染只产出文本，供预览/校验或后续由 `automation.gateway`
复用现有提交核心使用。
"""

from __future__ import annotations

import math
import re

VASP_BIN = "/data/gpfs03/mdye/vasp.6.4.2/bin/vasp_std"
PSXEVARS = "/data/gpfs03/mdye/intel/parallel_studio_xe_2020/psxevars.sh"
DEFAULT_WARN_MINUTES = 50

_QUEUE_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_BSUB_RE = re.compile(r"^#BSUB\s+(-[A-Za-z]+)(?:\s+(.*?))?\s*$")
_ALLOWED = {"-J", "-q", "-o", "-e", "-W", "-wt", "-wa", "-n", "-R"}

_FIXED_S1 = "#!/bin/bash"
_FIXED_S4 = "\n".join(["source " + PSXEVARS, "module load impi", "",
                       "export I_MPI_HYDRA_BOOTSTRAP=lsf", "export I_MPI_FABRICS=shm:ofi"])
_FIXED_S5 = "\n".join(["rm -f STOPCAR", "", 'echo "=== Job Started at $(date) | NP=$NPROCS ===" > result'])
_FIXED_S7 = "\n".join(["START=$(date +%s)",
                       "mpiexec.hydra -genvall -n $NPROCS $VASP_BIN >> result 2>&1", "RC=$?",
                       "ELAPSED=$(( $(date +%s) - START ))"])


class ScriptError(ValueError):
    pass


def format_walltime(hours: float) -> str:
    """小时数 → LSF `HH:MM`（24 → 24:00；不截断到一天）。"""
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not math.isfinite(hours) or hours <= 0:
        raise ScriptError("walltime 必须是大于 0 的小时数")
    total = int(round(hours * 60))
    h, m = divmod(total, 60)
    return f"{h:02d}:{m:02d}"


def render(*, queue: str, cores: int, cores_per_node: int, walltime_hours: float, job_name: str,
           soft_kill: bool = True, warn_minutes: int = DEFAULT_WARN_MINUTES) -> str:
    """生成 vasp.lsf 文本；软结束默认开启（与前端模板一致）。"""
    queue = str(queue or "").strip()
    if not _QUEUE_RE.fullmatch(queue):
        raise ScriptError("队列名不合法")
    if isinstance(cores, bool) or not isinstance(cores, int) or not 1 <= cores <= 100000:
        raise ScriptError("核数必须是 1 到 100000 的整数")
    if isinstance(cores_per_node, bool) or not isinstance(cores_per_node, int) or not 1 <= cores_per_node <= 1024:
        raise ScriptError("每节点核数必须是 1 到 1024 的整数")
    ptile = max(1, min(cores, cores_per_node))
    warn = int(warn_minutes or DEFAULT_WARN_MINUTES)
    if not 1 <= warn <= 1440:
        raise ScriptError("软结束预警分钟数不合法")
    name = str(job_name or "").strip()
    if not name or len(name) > 128 or re.search(r"[\r\n]", name):
        raise ScriptError("作业名不合法")

    lines = ["#BSUB -J " + name, "#BSUB -q " + queue, "#BSUB -o %J.out", "#BSUB -e %J.err",
             "#BSUB -W " + format_walltime(walltime_hours)]
    if soft_kill:
        lines.extend(["#BSUB -wt " + str(warn), "#BSUB -wa URG"])
    lines.extend(["#BSUB -n " + str(cores), '#BSUB -R "span[ptile=%d]"' % ptile])

    sections = [
        _FIXED_S1,
        "\n".join(lines),
        "\n".join(["VASP_BIN=" + VASP_BIN, "NPROCS=${LSB_DJOB_NUMPROC:-" + str(cores) + "}"]),
        _FIXED_S4,
        _FIXED_S5,
    ]
    if soft_kill:
        sections.append("\n".join([
            "lsf_watcher() {",
            "    trap 'echo \"LSTOP = .TRUE.\" > STOPCAR; echo \"=== [$(date)] LSF Walltime Warning! STOPCAR generated. ===\" >> result; exit 0' SIGURG",
            "    while true; do sleep 60; done",
            "}",
            "lsf_watcher &",
            "WATCHER_PID=$!",
        ]))
    sections.append(_FIXED_S7)
    closing = ["if [ $RC -eq 0 ]; then",
               '    echo "=== Job Finished normally at $(date) | elapsed=${ELAPSED}s ===" >> result',
               "else",
               '    echo "=== Job Failed at $(date) | elapsed=${ELAPSED}s | exit=$RC ===" >> result',
               "fi"]
    if soft_kill:
        closing.append("kill $WATCHER_PID 2>/dev/null")
    closing.append("exit $RC")
    sections.append("\n".join(closing))
    return "\n\n".join(sections) + "\n"


def parse(text: str) -> dict:
    """解析脚本里的资源申请；软结束的 `-wt/-wa` 是合法指令，不算未知参数。"""
    if not isinstance(text, str) or not text.strip():
        raise ScriptError("脚本为空")
    facts = {"cores": None, "walltime": None, "queue": None, "ptile": None, "soft_kill": False,
             "warn_minutes": None}
    issues = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("#BSUB"):
            if raw.strip() and raw.lstrip().startswith("#BSUB"):
                issues.append("BSUB 指令必须顶格")
            continue
        match = _BSUB_RE.match(line)
        if not match:
            issues.append(f"无法解析的 BSUB 指令：{line}")
            continue
        flag, value = match.group(1), (match.group(2) or "").strip()
        if flag not in _ALLOWED:
            issues.append(f"不支持的 BSUB 指令：{flag}")
            continue
        if flag in seen:
            issues.append(f"重复的 BSUB 指令：{flag}")
            continue
        seen.add(flag)
        if flag == "-n":
            try:
                facts["cores"] = int(value)
            except ValueError:
                issues.append("-n 核数不是整数")
        elif flag == "-W":
            try:
                h, m = value.split(":")
                facts["walltime"] = int(h) + int(m) / 60.0
            except ValueError:
                issues.append("-W 必须是 HH:MM")
        elif flag == "-q":
            facts["queue"] = value
        elif flag == "-R":
            span = re.search(r"span\[ptile=(\d+)\]", value)
            if span:
                facts["ptile"] = int(span.group(1))
            else:
                issues.append("-R 不是可识别的 span[ptile=N]")
        elif flag == "-wt":
            facts["soft_kill"] = True
            try:
                facts["warn_minutes"] = int(value)
            except ValueError:
                issues.append("-wt 必须是分钟数")
        elif flag == "-wa":
            facts["soft_kill"] = True
    if facts["cores"] is None:
        issues.append("缺少 #BSUB -n")
    if facts["walltime"] is None:
        issues.append("缺少 #BSUB -W")
    if facts["queue"] is None:
        issues.append("缺少 #BSUB -q")
    if facts["cores"] and facts["ptile"] and facts["ptile"] > facts["cores"]:
        issues.append("span[ptile] 大于总核数")
    if facts["soft_kill"] and facts["warn_minutes"] and facts["walltime"]:
        if facts["warn_minutes"] / 60.0 >= facts["walltime"]:
            issues.append("-wt 预警时间不小于 walltime")
    facts["issues"] = issues
    return facts


def check(text: str, *, expected_cores=None, expected_walltime=None, expected_queue=None) -> list:
    """提交前一致性检查：返回问题列表（空 = 通过）。"""
    facts = parse(text)
    issues = list(facts["issues"])
    if expected_cores is not None and facts["cores"] != expected_cores:
        issues.append(f"脚本核数 {facts['cores']} 与计划 {expected_cores} 不一致")
    if expected_walltime is not None and facts["walltime"] is not None and abs(facts["walltime"] - expected_walltime) > 1e-6:
        issues.append(f"脚本 walltime {facts['walltime']:g} 与计划 {expected_walltime:g} 不一致")
    if expected_queue is not None and facts["queue"] != expected_queue:
        issues.append(f"脚本队列 {facts['queue']} 与计划 {expected_queue} 不一致")
    return issues
