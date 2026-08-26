"""巡检接口：结果列表 / 触发巡检 / 调度信息。"""

import base64
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from checks_store import collect_results, list_runs, to_frontend_rows
from config import load_settings
from envelope import fail, ok
from inspection_runner import run_inspection
from paths import resolve_remote_path
from storage import load_db
from structure_analysis import analyze as analyze_structure
import vesta_render

router = APIRouter(prefix="/inspections", tags=["inspections"])


@router.get("")
def list_inspections():
    """巡检结果列表（按任务合并最近一次结果，供巡检中心页面展示）。"""
    try:
        db = load_db()
        merged = collect_results()
        return ok("查询成功", {"results": to_frontend_rows(db, merged)})
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取巡检结果失败：{e}"))


@router.get("/meta")
def inspection_meta():
    """自动巡检调度信息（每 N 小时；调度执行器后续接入 APScheduler）。"""
    try:
        settings = load_settings()
        interval = int(settings.get("inspection_interval_hours", 2))
        enabled = bool(settings.get("auto_inspection_enabled", True))
        runs = list_runs()
        last = runs[0] if runs else None
        next_run_at = None
        if last and last.get("checked_at"):
            try:
                next_run_at = (
                    datetime.fromisoformat(last["checked_at"]) + timedelta(hours=interval)
                ).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                next_run_at = None
        return ok(
            "查询成功",
            {
                "enabled": enabled,
                "interval_hours": interval,
                "last_run_at": last.get("checked_at") if last else None,
                "last_run_summary": last,
                "next_run_at": next_run_at,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取巡检配置失败：{e}"))


@router.post("/run")
def trigger_inspection(
    payload: dict = Body(default={"project_name": None, "task_id": None}),
):
    """立即巡检：可选限定项目或任务。"""
    project_name: Optional[str] = payload.get("project_name")
    task_id: Optional[str] = payload.get("task_id")
    try:
        summary = run_inspection(project_name=project_name, task_id=task_id)
        return ok("巡检完成", summary)
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"巡检失败：{e}"))


@router.post("/run-single/{task_id}")
def run_single_inspection(task_id: str):
    """单任务巡检：对该任务执行完整检查、回填、归档。"""
    try:
        summary = run_inspection(task_id=task_id)
        return ok("巡检完成", summary)
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"巡检失败：{e}"))


def _data_uri(image_path: str) -> str:
    data = Path(image_path).read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


def _display_current_output(project: dict, current_output):
    """巡检详情展示用：归档/元数据中为相对路径，按当前远程根解析为完整路径。"""
    if not isinstance(current_output, dict):
        return current_output
    out = dict(current_output)
    server = project.get("server")
    for key in ("dir", "contcar_path", "outcar_path", "oszicar_path"):
        if out.get(key):
            out[key] = resolve_remote_path(server, str(out[key]))
    return out


@router.get("/{task_id}")
def inspection_detail(task_id: str):
    """单任务巡检详情：能量/力曲线数据 + 结构分析（晶格对比 + VESTA 渲染图）。"""
    try:
        db = load_db()
        merged = collect_results()
        entry = merged.get(task_id)
        if entry is None:
            return JSONResponse(status_code=404, content=fail("该任务暂无巡检结果"))

        pair = None
        for project in db.get("projects", []):
            for task in project.get("tasks", []):
                if task.get("task_id") == task_id:
                    pair = (project, task)
                    break
            if pair:
                break
        if pair is None:
            return JSONResponse(status_code=404, content=fail("未找到任务"))
        project, task = pair

        # 自由能组结构优化详情：附带其频率矫正子任务的巡检数据（列表不单独展示 frac）
        frac = None
        group = task.get("group") or {}
        if task.get("task_type") == "opt" and group.get("group_type") == "free_energy":
            frac_task = None
            for t in project.get("tasks", []):
                if (
                    t.get("task_type") == "frac"
                    and t.get("dir_path") == f"{task.get('dir_path', '')}/frac"
                ):
                    frac_task = t
                    break
            if frac_task is not None:
                frac_entry = merged.get(frac_task.get("task_id"))
                frac_co = frac_task.get("current_output") or (
                    frac_entry.get("current_output") if frac_entry else None
                ) or None
                frac = {
                    "task_id": frac_task.get("task_id"),
                    "task_name": frac_task.get("model_name"),
                    "status": frac_task.get("status"),
                    "has_inspection": frac_entry is not None,
                    "check_time": frac_entry.get("checked_at") if frac_entry else None,
                    "last_energy": frac_entry.get("last_energy") if frac_entry else None,
                    "errors": (frac_entry.get("error_messages") or []) if frac_entry else [],
                    "notes": (frac_entry.get("notes") or "") if frac_entry else "",
                    "queue_status": frac_entry.get("queue_status") if frac_entry else None,
                    "current_output": _display_current_output(project, frac_co),
                }

        history = entry.get("force_history") or []
        analysis = None
        if task.get("task_type") == "opt":
            in_scope = bool(entry.get("analysis_needed", False))
            steps = len(history) if history else None
            struct = analyze_structure(project, task)
            # 详情为单任务按需查看：结构文件齐全且离子步足够时直接渲染对比图
            render = vesta_render.render_task(project, task, steps=steps)
            images = {
                label: {
                    axis: _data_uri(path)
                    for axis, path in axes.items()
                    if path
                }
                for label, axes in render["images"].items()
            }
            analysis = {
                "in_scope": in_scope,
                "steps": steps,
                "files": struct["files"],
                "isif": struct["isif"],
                "isif_source": struct["isif_source"],
                "cell_fixed": struct["cell_fixed"],
                "poscar": struct["poscar"],
                "contcar": struct["contcar"],
                "deltas": struct["deltas"],
                "displacements": struct["displacements"],
                "images": images,
                "skipped": render["skipped"],
                "warnings": struct["warnings"] + render["warnings"],
            }

        return ok(
            "查询成功",
            {
                "task_id": task_id,
                "project_name": project["name"],
                "model_name": task.get("model_name", ""),
                "task_type": task.get("task_type", ""),
                "status": task.get("status"),
                "check_time": entry.get("checked_at"),
                "queue_status": entry.get("queue_status"),
                "last_energy": entry.get("last_energy"),
                "force_max": entry.get("force_max"),
                "force_rms": entry.get("force_rms"),
                "force_converged": entry.get("force_converged"),
                "force_history": history,
                "errors": entry.get("error_messages", []) or [],
                "notes": entry.get("notes", "") or "",
                "current_output": (
                    _display_current_output(
                        project,
                        task.get("current_output") or entry.get("current_output") or None,
                    )
                ),
                "frac": frac,
                "analysis": analysis,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取巡检详情失败：{e}"))
