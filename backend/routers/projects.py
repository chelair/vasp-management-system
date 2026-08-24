"""项目接口：列表 + 新增（复刻参考实现 add_project.py 全流程）。"""

import os
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import PROJECTS_DIR, load_servers, load_settings, load_task_registry
from dates import now_iso
from envelope import fail, ok
from mappers import map_project
from models import AddProjectPayload
from priority import compute_priority
from ssh import mkdir_remote
from storage import add_project, load_db, save_db

router = APIRouter(prefix="/projects", tags=["projects"])

TASK_SUBDIRS = ("files", "images", "reports", "continuation")

# 与后续任务绑定的类型：不能在新项目中直接创建
DISALLOWED_NEW_TASK_TYPES = {
    "frequency": (
        "任务类型 'frequency'（频率计算）与 free_energy（自由能计算）绑定，"
        "不能在新项目中直接创建；free_energy 完成后会自动衔接频率计算。"
    )
}


def _create_local_dirs(project_dir: Path, tasks) -> None:
    for task in tasks:
        task_dir = project_dir / task["task_type"] / task["model_name"]
        for sub in TASK_SUBDIRS:
            (task_dir / sub).mkdir(parents=True, exist_ok=True)


def _rollback_local_dirs(project_dir: Path, existed_before: bool) -> None:
    if not existed_before and project_dir.exists():
        shutil.rmtree(project_dir)


def _sync_enabled(settings: dict) -> bool:
    env_value = os.environ.get("VASP_SYNC_REMOTE_DIRS")
    if env_value is not None:
        return env_value.strip().lower() in ("1", "true", "yes", "on")
    return bool(settings.get("sync_remote_dirs", False))


@router.get("")
def list_projects():
    try:
        db = load_db()
        return ok("查询成功", {"projects": [map_project(p) for p in db["projects"]]})
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"查询项目失败：{e}"))


@router.post("")
def create_project(payload: AddProjectPayload):
    try:
        p = payload.project
        settings = load_settings()
        servers = load_servers()
        registry = load_task_registry()

        if p.server not in servers:
            return JSONResponse(
                status_code=400,
                content=fail(
                    f"服务器 '{p.server}' 未在 servers.json 中配置",
                    {"errors": [f"project.server: 可用服务器 {list(servers.keys())}"]},
                ),
            )
        unknown_types = [t.task_type for t in p.tasks if t.task_type not in registry]
        if unknown_types:
            return JSONResponse(
                status_code=400,
                content=fail(
                    f"任务类型 {unknown_types} 未在 task_registry.json 中注册",
                    {"errors": [f"project.tasks: 可用任务类型 {list(registry.keys())}"]},
                ),
            )
        for task in p.tasks:
            if task.task_type in DISALLOWED_NEW_TASK_TYPES:
                return JSONResponse(
                    status_code=400,
                    content=fail(DISALLOWED_NEW_TASK_TYPES[task.task_type]),
                )

        priority = compute_priority(
            p.deadline,
            [t.model_dump() for t in p.tasks],
            registry,
            settings,
        )
        remote_base = servers[p.server].get("remote_base", "").rstrip("/")
        project_remote_base = f"{remote_base}/{p.name}"

        project = {
            **p.model_dump(),
            "workload": priority["workload"],
            "urgency": priority["urgency"],
            "priority_quadrant": priority["quadrant"],
            "created_at": now_iso(),
            "remote_base": project_remote_base,
            "tasks": [
                {
                    **t.model_dump(),
                    "status": t.status or "pending",
                    "last_energy": None,
                    "last_check_time": None,
                    "job_id": None,
                    "notes": "",
                    "continuation_ready": False,
                    "continuation_dir": None,
                    "remote_dir": f"{project_remote_base}/{t.task_type}/{t.model_name}",
                }
                for t in p.tasks
            ],
        }

        # 创建本地目录（失败回滚本次新建的目录树）
        project_dir = PROJECTS_DIR / p.name
        dir_existed_before = project_dir.exists()
        try:
            _create_local_dirs(project_dir, project["tasks"])
        except Exception as e:
            _rollback_local_dirs(project_dir, dir_existed_before)
            return JSONResponse(
                status_code=400, content=fail(f"创建本地目录失败：{e}")
            )

        # 可选：在服务器上同步创建任务目录（失败回滚本地目录）
        if _sync_enabled(settings):
            try:
                for task in project["tasks"]:
                    mkdir_remote(p.server, task["remote_dir"])
            except Exception as e:
                _rollback_local_dirs(project_dir, dir_existed_before)
                return JSONResponse(
                    status_code=400, content=fail(f"远程创建项目目录失败：{e}")
                )

        # 写入数据库（失败回滚目录）
        try:
            db = load_db()
            created = add_project(db, project)
            save_db(db)
            return ok(
                "项目创建成功",
                {
                    "project_id": created["project_id"],
                    "priority_quadrant": priority["quadrant"],
                    "urgency": priority["urgency"],
                    "workload": priority["workload"],
                    "remote_base": project_remote_base,
                },
            )
        except ValueError as e:
            _rollback_local_dirs(project_dir, dir_existed_before)
            return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"服务器内部错误：{e}"))
