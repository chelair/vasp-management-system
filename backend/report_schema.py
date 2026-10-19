"""项目报告数据结构规范（schema）。

设计原则（对应需求 §2）：

- 字段命名：英文小写 + 下划线，含义唯一；
- 枚举封闭：状态 / 类型 / 严重程度等取值固定，不允许自由文本；
- 单位统一：能量 eV、时间小时、容量 GB、核数整数、位移 Å；
- 时间统一 ISO 8601（本地时间，YYYY-MM-DDTHH:mm:ss）；
- 层级扁平：章节即顶层字段，嵌套不超过三层；
- 版本管理：`schema_version` 变更时递增，并在 SCHEMA_CHANGELOG 记录；
- 图片与数据分离：图表只给路径，数值以数组/表格字段提供。
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple

SCHEMA_VERSION = "1.2.0"

SCHEMA_CHANGELOG: List[Dict[str, str]] = [
    {
        "version": "1.2.0",
        "date": "2026-10-19",
        "changes": "R1：任务快照增加 INCAR/KPOINTS、参数来源、精度/巡检状态/时间和组归属；注解增加来源、模型、生成时间、指纹、修订与单次恢复信息。原章节布局及既有字段兼容。",
    },
    {
        "version": "1.1.0",
        "date": "2026-09-13",
        "changes": "以总结为核心重做章节：基本信息 / 重点科学结果分析（opt 每任务三视图+能量力同图、自由能按路径、NEB 按组含映像结构对比、电子结构占位）/ 异常与关注项 / 下一步建议（v0.7.2 起去掉附录章节）；数据章节仍保留在结构化数据中供大模型消费，但不再逐字段堆砌进正文",
    },
    {
        "version": "1.0.0",
        "date": "2026-09-13",
        "changes": "首个版本：元数据 / 执行摘要 / 进度总览 / 任务详情 / 科学结果 / 巡检异常 / 资源健康 / 风险分析 / 行动清单 / 大模型上下文 / 附录",
    }
]

UNITS: Dict[str, str] = {
    "energy": "eV",
    "force": "eV/A",
    "displacement": "A",
    "time": "hour",
    "capacity": "GB",
    "cores": "int",
    "temperature": "K",
    "frequency": "cm^-1",
    "free_energy": "eV",
    "zpe": "eV",
}

TASK_TYPES: Tuple[str, ...] = ("opt", "frac", "neb", "ele")
TASK_STATUSES: Tuple[str, ...] = (
    "pending",
    "queued",
    "running",
    "completed",
    "unconverged",
    "zombied",
    "archived",
)
PROJECT_STATUSES: Tuple[str, ...] = ("normal", "warning", "critical")

#: **状态族**（2026-10-12 审查结论）：`status` 这个键在不同 payload 里含义不同，
#: AI 必须先看这张表，别把"任务的 completed"和"巡检行的 normal/警告"混为一谈。
STATUS_FAMILIES: Dict[str, Dict[str, Any]] = {
    "task_status": {
        "values": list(TASK_STATUSES),
        "where": "任务记录（DB）/ 报告任务表 / 自由能结构状态",
        "meaning": "数据库任务状态，唯一真相；unconverged=算完但力未收敛",
    },
    "check_status": {
        "values": ["normal", "warning", "error", "pending", "archived"],
        "where": "巡检列表 `GET /inspections` 的 `status`（前端行口径）",
        "meaning": "巡检结论：正常 / 需关注（未收敛、低精度、挂起）/ 异常 / 未检 / 已关闭",
    },
    "archive_status": {
        "values": [
            "completed",
            "unconverged",
            "zombied",
            "running",
            "pending",
            "archived",
            "low_precision",
        ],
        "where": "巡检归档原始文件 `data/checks/check_results_*.json` 的 `status`",
        "meaning": "回填时的任务状态；**low_precision 是归档特有**：低精度收敛，数据库里记 completed",
    },
    "output_state": {
        "values": ["waiting", "running", "finished", "failed"],
        "where": "`task.current_output.status`（最新输出目录的判读）",
        "meaning": "只看 OUTCAR 尾部：无输出 / 未结束 / 正常结束 / 命中错误关键字",
    },
    "queue_state": {
        "values": ["PEND", "RUN", "SSUSP", "USUSP", "PSUSP", "UNKNOWN", "Open:Active"],
        "where": "`queue_status` / `resources.queues[].status`（LSF 原样值）",
        "meaning": "集群队列状态，原样透传 bjobs；`Open:Active` 是队列（queue）状态",
    },
    "project_status": {
        "values": list(PROJECT_STATUSES),
        "where": "报告 `basic_info.project_status` / 总览统计",
        "meaning": "项目整体健康度：正常 / 警告 / 异常",
    },
}

#: 时间格式约定（2026-10-12 审查）：主线 `YYYY-MM-DDTHH:mm:ss+08:00`（本地时间带偏移）；
#: 纯日期字段保持 `YYYY-MM-DD`；带 `_label` 的字段是人类可读文案，不要当时间解析。
TIME_FORMAT: Dict[str, str] = {
    "datetime": "YYYY-MM-DDTHH:mm:ss+08:00",
    "date": "YYYY-MM-DD",
    "timezone": "Asia/Shanghai",
    "note": "历史数据里的时间无偏移（本地时间），规范化视图会补上 +08:00；`*_label` 是文案不是时间",
}

#: 字段别名（同一含义在不同面的两套写法）：AI 用左边（规范名），右边是历史/前端别名
FIELD_ALIASES: Dict[str, List[str]] = {
    "created_at": ["createdAt"],
    "closed_at": ["closedAt"],
    "updated_at": ["updatedAt"],
    "last_energy_ev": ["last_energy"],
    "force_max_ev_per_a": ["force_max"],
    "force_rms_ev_per_a": ["force_rms"],
    "remaining_hours": ["remainingHours"],
    "queue_state": ["queue_status"],
    "task_status": ["status（任务记录里）"],
}

#: 低精度收敛的规范化政策（2026-10-12 用户确认）：归档的 `low_precision` 在 AI 视图里
#: 归并成 `task_status=completed` + `precision_ok=false` + `precision_issues=[...]`。
LOW_PRECISION_POLICY = "low_precision → task_status=completed 且 precision_ok=false（问题写进 precision_issues）"
SEVERITIES: Tuple[str, ...] = ("high", "medium", "low")
PRIORITIES: Tuple[str, ...] = ("P0", "P1", "P2")
RISK_TYPES: Tuple[str, ...] = (
    "convergence",  # 未收敛 / 异常中断
    "resource",  # 核数占用超限
    "storage",  # 存储空间不足
    "queue",  # 排队过久 / 挂起
    "file",  # 输入/输出文件缺失
    "dependency",  # 依赖任务未完成
    "analysis",  # 后处理未分析（PDOS/Bader/频率矫正缺失）
    "progress",  # 进度落后 / 逾期
)
RISK_SEVERITY_BY_TYPE = {
    "convergence": "high",
    "resource": "medium",
    "storage": "high",
    "queue": "medium",
    "file": "high",
    "dependency": "medium",
    "analysis": "low",
    "progress": "medium",
}

# 章节定义：(key, 标题)——报告 Markdown 与前端导出范围都以此为准
REPORT_SECTIONS: List[Tuple[str, str]] = [
    ("basic_info", "基本信息"),
    ("science", "重点科学结果分析"),
    ("issues", "异常与关注项"),
    ("actions", "下一步建议"),
]

SECTION_KEYS: Tuple[str, ...] = tuple(key for key, _ in REPORT_SECTIONS)


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def schema_manifest() -> Dict[str, Any]:
    """schema 清单（供接口暴露，方便大模型/前端声明支持的版本）。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "changelog": SCHEMA_CHANGELOG,
        "units": UNITS,
        "enums": {
            "task_types": list(TASK_TYPES),
            "task_statuses": list(TASK_STATUSES),
            "project_statuses": list(PROJECT_STATUSES),
            "severities": list(SEVERITIES),
            "priorities": list(PRIORITIES),
            "risk_types": list(RISK_TYPES),
        },
        # 2026-10-12 新增（只加不改）：状态族 / 时间格式 / 字段别名 / 低精度政策
        "status_families": STATUS_FAMILIES,
        "time_format": TIME_FORMAT,
        "field_aliases": FIELD_ALIASES,
        "low_precision_policy": LOW_PRECISION_POLICY,
        "normalized_view": {
            "where": "报告结构化数据 `ai_view`（GET /api/reports/project/{id}/structured 或 /ai）",
            "rules": [
                "键名一律 snake_case（camelCase 只保留在旧字段里，AI 用 snake）",
                "状态字段带族名：task_status / check_status / output_state / queue_state / project_status",
                "能量/力一律带单位后缀：*_ev、*_ev_per_a、*_a、*_hour",
                f"时间：{TIME_FORMAT['datetime']}（本地时间带偏移）；纯日期 YYYY-MM-DD",
                LOW_PRECISION_POLICY,
            ],
        },
        "sections": [{"key": key, "title": title} for key, title in REPORT_SECTIONS],
    }


def validate_report(doc: Dict[str, Any]) -> List[str]:
    """轻量校验：枚举是否封闭、单位字段是否存在、时间格式是否规范。

    只做「结构化数据是否可被大模型安全消费」这一层校验，不校验业务正确性。
    返回问题列表（空 = 通过）。
    """
    problems: List[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version 应为 {SCHEMA_VERSION}，实际 {doc.get('schema_version')!r}"
        )

    def check_time(value: Any, where: str) -> None:
        if value in (None, ""):
            return
        try:
            datetime.fromisoformat(str(value))
        except ValueError:
            problems.append(f"{where} 时间格式不是 ISO 8601：{value!r}")

    meta = doc.get("metadata") or {}
    check_time(meta.get("generated_at"), "metadata.generated_at")
    window = meta.get("time_window") or {}
    check_time(window.get("start"), "metadata.time_window.start")
    check_time(window.get("end"), "metadata.time_window.end")

    summary = doc.get("executive_summary") or {}
    if summary.get("project_status") not in PROJECT_STATUSES:
        problems.append(f"executive_summary.project_status 非法：{summary.get('project_status')!r}")
    tasks = (doc.get("tasks") or {}).get("groups") or []
    for group in tasks:
        if group.get("task_type") not in TASK_TYPES:
            problems.append(f"tasks.groups[].task_type 非法：{group.get('task_type')!r}")
        for task in group.get("tasks") or []:
            if task.get("status") not in TASK_STATUSES:
                problems.append(f"任务 {task.get('task_id')} 状态非法：{task.get('status')!r}")

    for risk in (doc.get("risks") or {}).get("items") or []:
        if risk.get("severity") not in SEVERITIES:
            problems.append(f"风险 {risk.get('risk_id')} 严重程度非法：{risk.get('severity')!r}")
        if risk.get("risk_type") not in RISK_TYPES:
            problems.append(f"风险 {risk.get('risk_id')} 类型非法：{risk.get('risk_type')!r}")
    for action in (doc.get("actions") or {}).get("items") or []:
        if action.get("priority") not in PRIORITIES:
            problems.append(f"行动 {action.get('action_id')} 优先级非法：{action.get('priority')!r}")
    return problems
