"""巡检接口：结果列表 / 触发巡检 / 调度信息。"""

import re
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from checks_store import collect_results, list_runs, to_frontend_rows
from cif_convert import read_neb_image_cifs, read_or_convert_cif
from config import load_settings, load_servers
from continuation import _remote_latest_con
from envelope import fail, ok
from inspection_scheduler import scheduler_status, update_schedule
from inspection_runner import run_inspection
from paths import resolve_remote_path
import ssh
from storage import load_db
from structure_analysis import analyze as analyze_structure
from task_paths import task_remote_dir

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
    """自动巡检调度信息：开关、间隔、上次 / 下次执行时间、调度器运行状态。"""
    try:
        status = scheduler_status()
        runs = list_runs()
        last = runs[0] if runs else None
        return ok(
            "查询成功",
            {
                "enabled": status["enabled"],
                "interval_hours": status["interval_hours"],
                "last_run_at": status["last_run_at"] or (last.get("checked_at") if last else None),
                "last_run_summary": last,
                "next_run_at": status["next_run_at"],
                "scheduler": status,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取巡检配置失败：{e}"))


@router.put("/auto")
def update_auto_inspection(payload: dict = Body(default={})):
    """开关自动巡检 / 调整间隔（写入 settings.json，调度线程下一轮生效）。"""
    try:
        return ok("自动巡检设置已保存", update_schedule(payload))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"保存自动巡检设置失败：{e}"))


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


def _build_analysis(project: dict, task: dict, entry: dict, history: list):
    """按任务类型构建详情分析数据（后续按四种类型分别扩展）。

    - opt（结构优化）：结构分析（晶格对比 + 原子位移 + 3Dmol 结构视图）；
    - frac（频率矫正）：预留——频率/热力学数据；
    - neb（NEB 过渡态）：预留——各映像能量/能垒；
    - ele（电子结构）：预留——PDOS/Bader/功函数等后处理结果。
    未实现的分析返回 None，前端展示"该类型暂无分析"占位。
    """
    task_type = task.get("task_type")
    if task_type == "opt":
        in_scope = bool(entry.get("analysis_needed", False))
        steps = len(history) if history else None
        struct = analyze_structure(project, task)
        # 3Dmol 结构视图：有 CIF 用 CIF；没有 CIF 但本地有 POSCAR/CONTCAR 时现场转换补缺
        poscar_cif = read_or_convert_cif(project, task, "POSCAR")
        contcar_cif = read_or_convert_cif(project, task, "CONTCAR")
        skipped = (
            None
            if poscar_cif and contcar_cif
            else "结构 CIF 未生成（本地无 CIF 且无 POSCAR/CONTCAR 源，或转换失败）"
        )
        return {
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
            "images": {"poscar": {}, "contcar": {}},
            "poscar_cif": poscar_cif,
            "contcar_cif": contcar_cif,
            "skipped": skipped,
            "warnings": struct["warnings"],
        }
    if task_type == "neb":
        # NEB 映像分析（v0.6.9）：展示优化后的 IS → 中间态 → FS 结构横向对比。
        # 结构由巡检按与 opt 相同的 25 步桶规则同步到本地上表（reports/structure/images/）。
        cifs = read_neb_image_cifs(project, task)
        barrier = entry.get("neb_barrier") or {}
        # nebef.pl 的映像号是 0/1/2…，目录名是 00/01/02…：按数值归一化后再匹配
        def _norm_label(value) -> Any:
            text = str(value).strip()
            return int(text) if text.isdigit() else text

        by_label = {
            _norm_label(item.get("label")): item
            for item in (barrier.get("images") or [])
        }
        labels = sorted(
            cifs.keys(), key=lambda x: int(x) if str(x).isdigit() else 999
        )
        images = []
        for index, label in enumerate(labels):
            info = by_label.get(_norm_label(label)) or {}
            images.append(
                {
                    "label": str(label),
                    "role": (
                        "is"
                        if index == 0
                        else "fs"
                        if index == len(labels) - 1
                        else "middle"
                    ),
                    "cif": cifs[label],
                    "energy": info.get("energy"),
                    "relative": info.get("relative"),
                    "max_force": info.get("max_force"),
                }
            )
        band_steps = entry.get("neb_band_steps")
        return {
            "in_scope": bool(entry.get("analysis_needed", False)),
            "steps": band_steps if isinstance(band_steps, int) else None,
            "neb_images": images,
            "skipped": (
                None
                if images
                else "尚未同步 NEB 映像结构：需要巡检推进到 25 离子步桶后自动抓取各映像 CONTCAR"
            ),
            "warnings": [],
        }
    # TODO(frac/ele): 后续按任务类型补充专属分析数据
    return None


def _check_remote_files(server: str, remote_dir: str, filenames) -> dict:
    """检查远端任务目录中指定文件是否存在且非空。"""
    result = {}
    conds = " ".join(
        f'[ -s "{remote_dir}/{name}" ] && echo OK_{i} || echo MISS_{i};'
        for i, name in enumerate(filenames)
    )
    try:
        r = ssh.run_remote(server, f"bash -c '{conds}'", timeout=30)
        out = r.get("stdout", "")
        for i, name in enumerate(filenames):
            result[name] = f"OK_{i}" in out
    except Exception:  # noqa: BLE001 - 检查失败视为不可用
        for name in filenames:
            result[name] = False
    return result


def _run_nebef(server: str, remote_dir: str):
    """在 NEB 最新**有结果**目录（含中间映像 OUTCAR，逐级回退到主目录）运行 nebef.pl。"""
    cmd = (
        "mid_outcar() { dir=$1; "
        'nums=$(ls -d "$dir"/[0-9]* 2>/dev/null | xargs -n1 basename | sort -n); '
        'first=$(echo "$nums" | head -1); last=$(echo "$nums" | tail -1); '
        "for n in $nums; do "
        '[ "$n" != "$first" ] && [ "$n" != "$last" ] && [ -f "$dir/$n/OUTCAR" ] && return 0; '
        "done; return 1; }; "
        f'D=""; for c in $(ls -d "{remote_dir}"/con[0-9]* 2>/dev/null | sed "s|.*/||" | sort -V | tail -r) MAIN; do '
        f'dir="{remote_dir}/$c"; [ "$c" = MAIN ] && dir="{remote_dir}"; '
        'if mid_outcar "$dir"; then D="$c"; break; fi; done; '
        f'if [ -n "$D" ]; then cd "{remote_dir}/$D" && perl /data/gpfs03/mdye/VTST/vtstscripts/nebef.pl; '
        "else echo NO_RESULT; fi"
    )
    r = ssh.run_remote(
        server,
        f"bash -c '{cmd}'",
        timeout=120,
    )
    images = []
    for line in (r.get("stdout", "") or "").splitlines():
        m = re.match(r"^\s*(\d+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)", line)
        if m:
            images.append(
                {
                    "label": m.group(1),
                    "max_force": float(m.group(2)),
                    "energy": float(m.group(3)),
                    "relative": float(m.group(4)),
                }
            )
    return {"images": images} if images else None


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
                    "correction": frac_task.get("correction"),
                }

        history = entry.get("force_history") or []
        analysis = _build_analysis(project, task, entry, history)

        # 电子结构：自动识别可分析内容（对应输出文件存在且非空）
        available_analyses = None
        if task.get("task_type") == "ele":
            ele_dir = task_remote_dir(project.get("server"), task).rstrip("/")
            files = _check_remote_files(
                project.get("server"),
                ele_dir,
                ["DOSCAR", "AECCAR0", "AECCAR1", "AECCAR2", "COHPCAR", "LOCPOT"],
            )
            available_analyses = {
                "pdos": bool(files.get("DOSCAR")),
                "bader": bool(
                    files.get("AECCAR0")
                    and files.get("AECCAR1")
                    and files.get("AECCAR2")
                ),
                "cohp": bool(files.get("COHPCAR")),
                "work_function": bool(files.get("LOCPOT")),
                "diff_charge": False,
            }

        # NEB 过渡态：nebef.pl 输出（受力/能量/相对能垒）
        # 巡检已回传 neb_barrier 则直接用，否则实时运行 nebef.pl 兜底
        neb_barrier = entry.get("neb_barrier")
        if task.get("task_type") == "neb" and not neb_barrier:
            neb_dir = task_remote_dir(project.get("server"), task).rstrip("/")
            try:
                neb_barrier = _run_nebef(project.get("server"), neb_dir)
            except Exception:  # noqa: BLE001 - 实时运行失败不影响详情
                neb_barrier = None

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
                "available_analyses": available_analyses,
                "neb_barrier": neb_barrier,
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content=fail(f"读取巡检详情失败：{e}"))
