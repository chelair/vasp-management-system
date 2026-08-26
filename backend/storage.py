"""文件型数据库：原子写入 + 自动备份（保留 20 份），对齐参考实现 project_db.py。"""

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config import BACKUPS_DIR, DATA_DIR, ensure_data_dirs
from dates import now_iso

MAX_BACKUPS = 20


def _resolve_db_path() -> Path:
    """数据库文件：优先 web 命名 projects.json；存在真实系统 project_db.json 时使用它。"""
    primary = DATA_DIR / "projects.json"
    legacy = DATA_DIR / "project_db.json"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


DB_PATH = _resolve_db_path()

#: 任务状态枚举（对齐参考实现 project_db.STATUS_ENUM）
STATUS_ENUM = (
    "pending",
    "queued",
    "running",
    "completed",
    "unconverged",
    "zombied",
    "archived",
)

_backup_seq = 0


def load_db() -> Dict[str, Any]:
    """读取数据库；文件不存在时返回空结构（不写入演示数据）。"""
    ensure_data_dirs()
    if not DB_PATH.exists():
        return {"projects": []}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"数据库文件 {DB_PATH} 的 JSON 解析失败，请检查文件内容是否完整：{e}")
    if not isinstance(data, dict):
        raise ValueError(f"数据库文件 {DB_PATH} 的内容必须是 JSON 对象（字典）")
    data.setdefault("projects", [])
    return data


def _backup_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def backup_db() -> Optional[str]:
    """手动触发一次数据库备份，只保留最近 MAX_BACKUPS 份。"""
    global _backup_seq
    if not DB_PATH.exists():
        return None
    _backup_seq += 1
    name = f"project_db_{_backup_stamp()}_{_backup_seq:04d}.json"
    shutil.copy2(DB_PATH, BACKUPS_DIR / name)
    _prune_backups()
    return name


def _prune_backups() -> None:
    backups = sorted(BACKUPS_DIR.glob("project_db_*.json"))
    for old in backups[:-MAX_BACKUPS]:
        old.unlink(missing_ok=True)


def save_db(db: Dict[str, Any], backup: bool = True) -> None:
    """原子写入：先写临时文件再 os.replace，写入前自动备份现有文件。"""
    ensure_data_dirs()
    if backup:
        backup_db()
    fd, tmp_name = tempfile.mkstemp(
        dir=str(DATA_DIR), prefix=".projects_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, DB_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def get_project(db: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    for project in db.get("projects", []):
        if project.get("name") == name:
            return project
    return None


def _allocate_unique_ts(db: Dict[str, Any], task_count: int) -> str:
    """分配不与现有 project_id/task_id 冲突的毫秒时间戳（冲突则 +1 重试）。"""
    used = set()
    for project in db.get("projects", []):
        used.add(project.get("project_id"))
        for task in project.get("tasks", []):
            used.add(task.get("task_id"))
    ts = int(datetime.now().timestamp() * 1000)
    while True:
        project_id = f"proj_{ts}"
        task_ids = [f"task_{ts}_{i}" for i in range(1, task_count + 1)]
        if project_id not in used and not any(tid in used for tid in task_ids):
            return str(ts)
        ts += 1


def add_project(db: Dict[str, Any], project_data: Dict[str, Any]) -> Dict[str, Any]:
    """追加项目并生成 project_id / task_id（对齐参考实现 project_db.add_project）。"""
    name = project_data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("项目名称（name）不能为空。")
    if get_project(db, name) is not None:
        raise ValueError(f"项目 '{name}' 已存在，不能重复创建。")
    tasks = project_data.get("tasks", [])
    if not isinstance(tasks, list):
        raise ValueError("项目数据中的 tasks 必须是列表。")

    ts = _allocate_unique_ts(db, len(tasks))
    project = dict(project_data)
    project["project_id"] = f"proj_{ts}"
    project["tasks"] = [
        {**task, "task_id": f"task_{ts}_{index}"}
        for index, task in enumerate(tasks, start=1)
    ]
    db["projects"].append(project)
    return project


def get_task(
    db: Dict[str, Any], project_name: str, task_id: str
) -> Optional[Dict[str, Any]]:
    """查找指定项目下的任务。"""
    project = get_project(db, project_name)
    if project is None:
        return None
    for task in project.get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None


def update_task_status(
    db: Dict[str, Any],
    project_name: str,
    task_id: str,
    new_status: str,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """更新任务状态：校验合法性 + 流转规则，合并附加字段，刷新 last_check_time。

    Raises:
        ValueError: 状态非法、流转非法、项目或任务不存在时。
    """
    if new_status not in STATUS_ENUM:
        raise ValueError(
            f"非法状态 '{new_status}'，允许的状态：{', '.join(STATUS_ENUM)}。"
        )
    project = get_project(db, project_name)
    if project is None:
        raise ValueError(f"项目 '{project_name}' 不存在。")
    task = get_task(db, project_name, task_id)
    if task is None:
        raise ValueError(f"项目 '{project_name}' 下不存在任务 '{task_id}'。")

    current_status = task.get("status")
    if current_status not in STATUS_ENUM:
        raise ValueError(
            f"任务 '{task_id}' 当前状态 '{current_status}' 不在状态枚举中，无法更新状态。"
        )
    # 状态流转不设白名单限制：以巡检/服务器观测状态为准，合法枚举状态间可自由流转

    if extra_fields:
        task.update(extra_fields)
    task["status"] = new_status
    task["last_check_time"] = now_iso()
    return task
