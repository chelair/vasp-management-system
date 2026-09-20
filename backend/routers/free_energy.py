"""自由能路径汇总：按 group_id 聚合路径上各中间体的能量与矫正项。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from envelope import fail, ok
import permissions
from storage import load_db

router = APIRouter(prefix="/free-energy", tags=["free-energy"])


@router.get("/{group_id}/summary")
def free_energy_summary(group_id: str, request: Request):
    """返回自由能路径汇总：各中间体 DFT 能量、矫正项、自由能及状态。"""
    try:
        db = load_db()
        opt_tasks = []
        for project in db.get("projects", []):
            for task in project.get("tasks", []):
                group = task.get("group") or {}
                if group.get("group_type") == "free_energy" and group.get("group_id") == group_id:
                    opt_tasks.append((project, task))
        if not opt_tasks:
            return JSONResponse(status_code=404, content=fail("自由能路径不存在"))
        # 归属校验（第 4 步）：组属于哪个项目就按哪个项目校验
        permissions.ensure_project_owner(opt_tasks[0][0], getattr(request.state, "user", None))

        group_name = opt_tasks[0][1].get("group", {}).get("name", group_id)
        structures = []
        for project, opt_task in opt_tasks:
            if opt_task.get("task_type") != "opt":
                continue
            frac_task = next(
                (
                    t
                    for t in project.get("tasks", [])
                    if t.get("dir_path") == f"{opt_task.get('dir_path', '')}/frac"
                ),
                None,
            )
            dft = opt_task.get("last_energy")
            correction = frac_task.get("correction") if frac_task else None
            # 归档（关闭）任务：以归档前状态判断是否收敛，否则看板会把已完成的路径标成未收敛
            opt_status = str(opt_task.get("status") or "")
            converged = opt_status == "completed" or (
                opt_status == "archived"
                and str(opt_task.get("archived_from") or "") == "completed"
            )
            structures.append(
                {
                    "task_id": opt_task.get("task_id"),
                    "structure_label": (opt_task.get("group") or {}).get(
                        "structure_label", ""
                    ),
                    "dft_energy": dft,
                    "correction": correction,
                    "free_energy": (
                        round(dft + correction, 6)
                        if isinstance(dft, (int, float))
                        and isinstance(correction, (int, float))
                        else None
                    ),
                    "converged": converged,
                    "corrected": correction is not None,
                }
            )
        structures.sort(
            key=lambda s: (
                int(s["structure_label"])
                if str(s["structure_label"]).isdigit()
                else 999
            )
        )
        return ok(
            "查询成功",
            {"group_id": group_id, "name": group_name, "structures": structures},
        )
    except permissions.PermissionDenied:
        raise  # 越权 403：交给全局异常处理器，不要被本地 except 吞掉
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取自由能路径汇总失败：{e}"))
