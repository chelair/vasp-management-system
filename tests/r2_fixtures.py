"""R2 隔离夹具：临时数据目录里的项目、任务、巡检归档与本地镜像文件。

只写 `data_dir` 下的文件（`projects.json`、`checks/`、`projects/`），
不触碰生产数据、不连 SSH、不生成真实报告。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ID = "p_r2"
PROJECT_NAME = "R2P"
OWNER = "tester"
OPT_COUNT = 10

#: 这些任务故意缺数据，用来验证状态不会被合并
NO_CHECK_TASK = "task_opt_05"       # 有 OUTCAR，无巡检归档 → unparsed
NO_DATA_TASK = "task_opt_06"        # 无文件、无归档、无能量 → missing
UNCONVERGED_TASK = "task_opt_03"
SHARED_NAME_TASK = "task_opt_07"    # 与 task_opt_04 同名不同任务


def _now_minus(hours: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(hours=hours)
    return moment.astimezone().isoformat(timespec="seconds")


def _tasks() -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for index in range(1, OPT_COUNT + 1):
        task_id = f"task_opt_{index:02d}"
        name = f"Model{index:02d}"
        if task_id == SHARED_NAME_TASK:
            name = "Model04"  # 同名任务：ID 必须仍由 task_id 区分
        task = {
            "task_id": task_id,
            "task_type": "opt",
            "model_name": name,
            "status": "completed",
            "job_id": f"2301{index:02d}",
            "dir_path": f"{PROJECT_NAME}/opt/{name}",
            "remote_dir": f"{PROJECT_NAME}/opt/{name}",
            "current_output": {"latest_dir": "con1", "status": "completed"},
            "last_energy": -100.0 - index,
            "last_check_time": _now_minus(2),
            "group": None,
            "input_state": {},
        }
        if task_id == UNCONVERGED_TASK:
            task["status"] = "unconverged"
            task["current_output"] = {"latest_dir": "con1", "status": "unconverged"}
        if task_id == NO_DATA_TASK:
            task["last_energy"] = None
            task["current_output"] = {}
        if task_id == NO_CHECK_TASK:
            # 只有原始文件，没有巡检归档：既无能量也无曲线 → 应判 unparsed
            task["last_energy"] = None
            task["current_output"] = {}
        tasks.append(task)
    # 辅助任务（续算子）：出现在任务库里，但不应成为独立元素
    tasks.append(
        {
            "task_id": "task_opt_01_con1",
            "task_type": "opt",
            "model_name": "Model01_con1",
            "status": "pending",
            "job_id": None,
            "dir_path": f"{PROJECT_NAME}/opt/Model01/con1",
            "remote_dir": f"{PROJECT_NAME}/opt/Model01/con1",
            "parent_task_id": "task_opt_01",
            "group": None,
            "input_state": {},
        }
    )
    return tasks


def _check_entry(task: Dict[str, Any]) -> Dict[str, Any]:
    task_id = str(task["task_id"])
    converged = task_id != UNCONVERGED_TASK
    status = "unconverged" if task_id == UNCONVERGED_TASK else "completed"
    energy = task.get("last_energy")
    series = []
    for step in range(1, 4):
        series.append(
            {
                "step": step,
                "energy": round(float(energy) + 0.05 * (4 - step), 6) if energy is not None else None,
                "max_force": round(0.30 / step, 6),
            }
        )
    return {
        "task_id": task_id,
        "remote_dir": f"/data/gpfs03/mdye/projects/HS/{task['dir_path']}",
        "task_type": "opt",
        "model_name": task["model_name"],
        "status": status,
        "queue_status": "DONE",
        "last_energy": energy,
        "force_max": 0.012 if converged else 0.31,
        "force_rms": 0.008 if converged else 0.12,
        "force_converged": converged,
        "force_history": series,
        "incar": {"ENCUT": "450", "EDIFFG": "-0.02", "NSW": "100"},
        "kpoints": {"source": "KPOINTS", "mesh": [2, 2, 2]},
        "precision": {"ok": True, "requirements": {}},
        "parameter_sources": ["INCAR", "KPOINTS"],
        "checked_at": _now_minus(2),
        "error_messages": [] if converged else ["离子优化未收敛"],
    }


def write_project(data_dir: Path, *, name: str = PROJECT_NAME, owner: str = OWNER) -> Dict[str, Any]:
    """写 projects.json 并返回项目字典。"""
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    project = {
        "project_id": PROJECT_ID,
        "name": name,
        "owner": owner,
        "server": "server1",
        "status": "active",
        "created_at": _now_minus(72),
        "deadline": "2030-01-01",
        "tasks": _tasks(),
    }
    (data / "projects.json").write_text(
        json.dumps({"projects": [project]}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return project


def write_local_files(data_dir: Path, project: Optional[Dict[str, Any]] = None) -> None:
    """在本地镜像里写 OUTCAR/POSCAR/INCAR（缺数据任务故意不写）。"""
    data = Path(data_dir)
    project = project or {"name": PROJECT_NAME, "tasks": _tasks()}
    for task in project["tasks"]:
        task_id = str(task.get("task_id"))
        if task_id == NO_DATA_TASK or task_id == "task_opt_01_con1":
            continue
        files = data / "projects" / str(task["dir_path"]) / "files"
        files.mkdir(parents=True, exist_ok=True)
        names = ["OUTCAR", "POSCAR", "INCAR"]
        if task_id == NO_CHECK_TASK:
            names = ["OUTCAR"]  # 只有原始文件，没有巡检归档
        for name in names:
            (files / name).write_text(f"{name} fixture for {task_id}\n", encoding="utf-8")


def write_checks(data_dir: Path, *, checked_at: Optional[str] = None) -> None:
    """写一份巡检归档（check_results_*.json，list[entry]）。"""
    data = Path(data_dir)
    checks = data / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    entries = []
    for task in _tasks():
        task_id = str(task.get("task_id"))
        if task_id in (NO_CHECK_TASK, NO_DATA_TASK, "task_opt_01_con1"):
            continue
        entry = _check_entry(task)
        if checked_at:
            entry["checked_at"] = checked_at
        entries.append(entry)
    (checks / "check_results_20261020_000000_000000_server1.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def rewrite_checks(data_dir: Path, mutate) -> None:
    """改写巡检归档里的条目（用于验证版本变化），mutate(entries) 就地修改。"""
    data = Path(data_dir)
    path = data / "checks" / "check_results_20261020_000000_000000_server1.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    mutate(entries)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def seed(data_dir: Path) -> Dict[str, Any]:
    project = write_project(data_dir)
    write_local_files(data_dir, project)
    write_checks(data_dir)
    return project
