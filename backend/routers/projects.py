"""项目接口：列表 + 新增（复刻参考实现 add_project.py 全流程）。"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import DATA_DIR, PROJECTS_DIR, load_servers, load_settings, load_task_registry
from checks_store import task_check_summary
from dates import now_iso
from envelope import fail, ok
from mappers import map_project
from models import AddProjectPayload
from paths import resolve_remote_path, to_local_rel, to_remote_rel
from priority import compute_priority
from ssh import mkdir_remote
from storage import add_project, db_transaction, load_db, save_db
from task_paths import CATEGORY_DIRS, is_continuation_task

router = APIRouter(prefix="/projects", tags=["projects"])

TASK_SUBDIRS = ("files", "images", "reports", "continuation")


def _create_local_dirs(project_dir: Path, tasks) -> None:
    for task in tasks:
        # v0.4.0：独立任务目录 <项目>/<类型分类>/<模型名>
        category = CATEGORY_DIRS.get(task.get("task_type", ""), "结构优化")
        task_dir = project_dir / category / task["model_name"]
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
        # 带上最近一次巡检结论（低精度收敛 / 力未收敛等），作业管理页与巡检中心同口径
        check_map = task_check_summary(db)
        return ok(
            "查询成功",
            {"projects": [map_project(p, check_map) for p in db["projects"]]},
        )
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
                    "dir_path": to_local_rel(
                        str(
                            PROJECTS_DIR
                            / p.name
                            / CATEGORY_DIRS.get(t.task_type, "结构优化")
                            / t.model_name
                        )
                    ),
                    "remote_dir": to_remote_rel(
                        p.server,
                        f"{project_remote_base}/"
                        f"{CATEGORY_DIRS.get(t.task_type, '结构优化')}/{t.model_name}",
                    ),
                    "group": None,
                    "parent_task_id": None,
                    "input_source": None,
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
                    # remote_dir 为相对路径，必须拼接远程根目录后再创建，否则会建到服务器 home 下
                    mkdir_remote(p.server, resolve_remote_path(p.server, task["remote_dir"]))
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


@router.post("/{project_id}/close")
def close_project(project_id: str):
    """关闭项目：前提是项目下（可见）任务全部已关闭（归档）。

    关闭只改项目元数据（closed / closed_at），本地与远端文件都不动；
    关闭后的项目在总览 / 巡检中心 / 作业管理里都排到最后并默认折叠。
    """
    try:
        db = load_db()
        project = next(
            (p for p in db.get("projects", []) if p.get("project_id") == project_id),
            None,
        )
        if project is None:
            return JSONResponse(status_code=404, content=fail("项目不存在"))
        if project.get("closed"):
            return JSONResponse(status_code=409, content=fail("项目已经关闭"))
        remaining = [
            str(t.get("model_name") or "")
            for t in project.get("tasks", [])
            if not is_continuation_task(t) and t.get("status") != "archived"
        ]
        if remaining:
            head = "、".join(remaining[:5])
            more = f" 等 {len(remaining)} 个" if len(remaining) > 5 else ""
            return JSONResponse(
                status_code=400,
                content=fail(f"还有未关闭的任务（{head}{more}），请先全部关闭后再关闭项目"),
            )
        with db_transaction() as fresh:
            target = next(
                (p for p in fresh.get("projects", []) if p.get("project_id") == project_id),
                None,
            )
            if target is None:
                return JSONResponse(status_code=404, content=fail("项目不存在"))
            target["closed"] = True
            target["closed_at"] = now_iso()
        return ok(
            "项目已关闭",
            {"project_id": project_id, "project_name": str(project.get("name") or "")},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"关闭项目失败：{e}"))


@router.post("/{project_id}/reopen")
def reopen_project(project_id: str):
    """重新打开项目：清除 closed 标记（任务状态不变）。"""
    try:
        with db_transaction() as db:
            target = next(
                (p for p in db.get("projects", []) if p.get("project_id") == project_id),
                None,
            )
            if target is None:
                return JSONResponse(status_code=404, content=fail("项目不存在"))
            target["closed"] = False
            target.pop("closed_at", None)
            name = str(target.get("name") or "")
        return ok("项目已重新打开", {"project_id": project_id, "project_name": name})
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"重新打开项目失败：{e}"))


@router.delete("/{project_id}")
def delete_project(project_id: str):
    """删除项目：本地项目目录移入回收站 data/trash/，数据库移除（远端目录不自动删除）。"""
    try:
        db = load_db()
        project = next(
            (p for p in db.get("projects", []) if p.get("project_id") == project_id),
            None,
        )
        if project is None:
            return JSONResponse(status_code=404, content=fail("项目不存在"))
        name = str(project.get("name", ""))
        trash_path = None
        project_dir = PROJECTS_DIR / name
        if project_dir.is_dir():
            trash_dir = DATA_DIR / "trash"
            trash_dir.mkdir(parents=True, exist_ok=True)
            trash_path = trash_dir / f"{name}_{int(datetime.now().timestamp())}"
            shutil.move(str(project_dir), str(trash_path))
        db["projects"] = [p for p in db.get("projects", []) if p.get("project_id") != project_id]
        save_db(db)
        return ok(
            "项目已删除",
            {
                "project_id": project_id,
                "project_name": name,
                "local_trash": str(trash_path) if trash_path else None,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"删除项目失败：{e}"))
