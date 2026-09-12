"""数据库项目 → 前端展示结构（派生 progress / remainingHours / local_dir）。"""

import os
from datetime import date
from typing import Any, Dict

from config import PROJECTS_DIR
from paths import to_local_rel
from task_paths import free_energy_frac_task, is_continuation_task, task_dir


def _str(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) else fallback


def _days_until(deadline: str) -> int:
    try:
        return (date.fromisoformat(deadline) - date.today()).days
    except ValueError:
        return 0


def map_project(project: Dict[str, Any]) -> Dict[str, Any]:
    tasks = project.get("tasks", []) or []
    completed = sum(1 for t in tasks if t.get("status") in ("completed", "archived"))
    progress = round(completed / len(tasks) * 100) if tasks else 0
    check_times = [
        t.get("last_check_time")
        for t in tasks
        if isinstance(t.get("last_check_time"), str)
    ]
    updated_at = (
        max(check_times)
        if check_times
        else _str(project.get("created_at"), project.get("project_id", ""))
    )
    remaining_hours = max(0, _days_until(_str(project.get("deadline"), "")) * 24)

    mapped_tasks = []
    # 续算子任务（_conN）不在前端展示为独立子项，仅后台登记
    for task in tasks:
        if is_continuation_task(task):
            continue
        local_dir = to_local_rel(
            str(task_dir(_str(project.get("name"), ""), task))
        ).replace("\\", "/")
        mapped_tasks.append(
            {
                "task_id": _str(task.get("task_id"), ""),
                "task_type": _str(task.get("task_type"), ""),
                "subtype": task.get("subtype") or None,
                "model_name": _str(task.get("model_name"), ""),
                "status": _str(task.get("status"), "pending"),
                "last_energy": (
                    task.get("last_energy")
                    if isinstance(task.get("last_energy"), (int, float))
                    else None
                ),
                "last_check_time": _str(task.get("last_check_time"), "") or None,
                "job_id": _str(task.get("job_id"), "") or None,
                "notes": _str(task.get("notes"), ""),
                "continuation_ready": task.get("continuation_ready") is True,
                "continuation_dir": _str(task.get("continuation_dir"), "") or None,
                "current_output": task.get("current_output") or None,
                "remote_dir": _str(task.get("remote_dir"), ""),
                "local_dir": local_dir,
                "dir_path": _str(task.get("dir_path"), "") or local_dir,
                "group": task.get("group") or None,
                "parent_task_id": task.get("parent_task_id") or None,
                "input_source": task.get("input_source") or None,
                # 自由能组主任务：带上频率矫正子任务状态，供归档前提示使用
                "frac_sibling": _frac_sibling(project, task),
            }
        )

    return {
        "id": _str(project.get("project_id"), ""),
        "name": _str(project.get("name"), ""),
        "description": _str(project.get("description"), "") or "暂无描述",
        "deadline": _str(project.get("deadline"), ""),
        "workload": _str(project.get("workload"), "small"),
        "server": _str(project.get("server"), ""),
        "remote_base": _str(project.get("remote_base"), ""),
        "progress": progress,
        "remainingHours": remaining_hours,
        # 项目关闭（归档）：需要项目下可见任务全部归档后才允许，只影响展示排序与折叠
        "closed": project.get("closed") is True,
        "closedAt": _str(project.get("closed_at"), "") or None,
        "createdAt": _str(project.get("created_at"), project.get("project_id", "")),
        "updatedAt": updated_at,
        "tasks": mapped_tasks,
    }


def _frac_sibling(project: Dict[str, Any], task: Dict[str, Any]):
    """自由能结构优化任务的频率矫正子任务摘要（不存在则为 None）。"""
    frac = free_energy_frac_task(project, task)
    if frac is None:
        return None
    return {
        "task_id": _str(frac.get("task_id"), ""),
        "model_name": _str(frac.get("model_name"), ""),
        "status": _str(frac.get("status"), ""),
    }
