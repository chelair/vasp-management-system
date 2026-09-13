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

SCHEMA_VERSION = "1.1.0"

SCHEMA_CHANGELOG: List[Dict[str, str]] = [
    {
        "version": "1.1.0",
        "date": "2026-09-13",
        "changes": "以总结为核心重做章节：基本信息 / 重点科学结果分析（opt 每任务三视图+能量力同图、自由能按路径、NEB 按组含映像结构对比、电子结构占位）/ 异常与关注项 / 下一步建议 / 附录；数据章节仍保留在结构化数据中供大模型消费，但不再逐字段堆砌进正文",
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
    ("appendix", "附录（任务清单与生成参数）"),
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
