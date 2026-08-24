"""工作量 / 紧急度 / 优先级象限（对齐参考实现 priority.py）。"""

from typing import Any, Dict, List

from dates import days_until

DEFAULT_WORKLOAD_WEIGHT = 1


def workload_total(tasks: List[Dict[str, Any]], task_registry: Dict[str, Any]) -> float:
    """按任务类型权重计算总工作量，统一舍入 6 位消除浮点误差。"""
    total = 0.0
    for task in tasks:
        entry = task_registry.get(task.get("task_type", ""), {})
        total += entry.get("workload_weight", DEFAULT_WORKLOAD_WEIGHT)
    return round(total, 6)


def compute_priority(
    deadline: str,
    tasks: List[Dict[str, Any]],
    task_registry: Dict[str, Any],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """返回 workload / urgency / quadrant / workload_total。"""
    total = workload_total(tasks, task_registry)
    workload = (
        "large" if total >= settings.get("workload_large_threshold", 20) else "small"
    )
    days_left = days_until(deadline)
    urgency = (
        "urgent"
        if days_left < settings.get("urgent_days_threshold", 15)
        else "not_urgent"
    )
    return {
        "workload": workload,
        "urgency": urgency,
        "quadrant": f"{urgency}_{workload}",
        "workload_total": total,
    }
