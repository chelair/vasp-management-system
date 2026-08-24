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


def _data_uri(image_path: str) -> str:
    data = Path(image_path).read_bytes()
    return f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"


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

        history = entry.get("force_history") or []
        analysis = None
        if task.get("task_type") == "structure_opt":
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
                "current_output": task.get("current_output") or entry.get("current_output") or None,
                "analysis": analysis,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取巡检详情失败：{e}"))
