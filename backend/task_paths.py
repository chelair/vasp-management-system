"""任务目录路径解析（集中式，v0.5.0 相对路径规范）。

任务元数据中的 dir_path / remote_dir 为**相对项目根目录**的相对路径
（如 Ag_20260830/opt/Ag111），解析时与本地/远端根目录拼接。
迁移前的旧任务若存有绝对路径或缺少 dir_path，则按旧约定推导：
    <项目>/<任务类型>/<模型名>
新约定（v0.4.1，目录一律 ASCII，前端树显示中文）：
    结构优化：<项目>/opt/<独立任务>
    电子结构：<项目>/ele/<独立任务>
    自由能组：<项目>/free_energy/<组名>/<struct_NN>/<opt|frac>
    NEB 组：  <项目>/neb/<组名>/opt/<IS|FS>、<组名>/neb/<00..n+1>
VASP 文件统一放在任务目录的 files/ 子目录（兼容直接放在任务目录的情况）。
"""

from pathlib import Path
import re
from typing import Any, Dict, Optional

from config import PROJECTS_DIR
from paths import resolve_local_path, resolve_remote_path

#: 任务类型 -> 顶层分类目录（ASCII，前端树显示中文）
CATEGORY_DIRS = {
    "opt": "opt",
    "frac": "free_energy",
    "neb": "neb",
    "ele": "ele",
}

#: 续算子任务的目录后缀（.../con12）
_CONTINUATION_RE = re.compile(r"/con\d+$")


def strip_continuation_suffix(dir_path: str) -> str:
    """去掉续算子任务的 `/conN` 尾巴，得到任务族的本地根目录。

    **远端**仍按 conN 组织（VASP 续算就在那儿跑），只有**本地镜像**合并成一份：
    `<任务目录>/files/` 永远保存"远端最新计算目录"里的文件（v0.8.7 起）。
    任务记录里的 `dir_path` 保持原样 —— 它是续算子任务的逻辑主键
    （重复登记检查、远端目录推导都靠它），只在本地路径解析时剥掉后缀。
    """
    return _CONTINUATION_RE.sub("", str(dir_path or ""))


def is_continuation_task(task: Dict[str, Any]) -> bool:
    """续算子任务：dir_path 指向续算目录（.../conN）。

    续算在后台登记子任务记录（供巡检定位/文件重定向），但不在前端展示为独立子项。
    """
    return bool(_CONTINUATION_RE.search(str(task.get("dir_path", "") or "")))


def free_energy_frac_task(
    project: Dict[str, Any], opt_task: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """自由能组结构优化任务对应的频率矫正子任务。

    目录约定：frac 与 conN 同级，位于 `<结构目录>/frac`；同时校验
    `parent_task_id`（若已登记）避免误配。非自由能组 opt 返回 None。
    """
    if opt_task.get("task_type") != "opt":
        return None
    if (opt_task.get("group") or {}).get("group_type") != "free_energy":
        return None
    target = f"{opt_task.get('dir_path', '')}/frac"
    opt_id = str(opt_task.get("task_id") or "")
    for task in project.get("tasks", []):
        if task.get("task_type") != "frac":
            continue
        if str(task.get("dir_path") or "") != target:
            continue
        parent = str(task.get("parent_task_id") or "")
        if parent and opt_id and parent != opt_id:
            continue
        return task
    return None


def task_dir(project_name: str, task: Dict[str, Any]) -> Path:
    """任务本地目录（绝对路径；dir_path 为相对路径时自动拼接本地根目录）。

    续算子任务（dir_path 形如 `.../con3`）解析到**任务族根目录**：本地只保留一份
    文件镜像，不再建 `conN/` 目录（v0.8.7）。
    """
    stored = task.get("dir_path")
    if stored:
        return resolve_local_path(strip_continuation_suffix(stored))
    return (
        PROJECTS_DIR
        / str(project_name)
        / str(task.get("task_type", ""))
        / str(task.get("model_name", ""))
    )


def task_remote_dir(server: str, task: Dict[str, Any]) -> str:
    """任务远程目录（绝对路径；remote_dir 为相对路径时自动拼接服务器根目录）。"""
    stored = str(task.get("remote_dir", "") or "")
    if not stored:
        return ""
    return resolve_remote_path(server, stored)


def task_files_dir(project_name: str, task: Dict[str, Any]) -> Path:
    """VASP 文件目录：优先 <任务目录>/files/，缺失时退化为任务目录本身。"""
    root = task_dir(project_name, task)
    files_dir = root / "files"
    return files_dir if files_dir.is_dir() else root
