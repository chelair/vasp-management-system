"""单项目报告构建：数据收集 → 结构化对象 → Markdown → 图表。

输出结构对应需求 §3.1–3.11 的 11 个章节，顶层字段与 `report_schema.REPORT_SECTIONS`
一一对应；同时产出 `markdown_sections`（每章一段 Markdown），供前端按范围渲染与导出。

设计要点：
- 所有数据收集都容错：单个任务读取失败只记录到 `appendix.collection_errors`；
- 图表用 report_charts 生成 SVG，结构化数据里同时给出原始数值数组；
- 集群信息复用总览模块的 `cluster_snapshot`（5 分钟缓存），批量生成只付一次 SSH。
"""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from checks_store import collect_results, list_runs, to_frontend_rows
from cif_convert import read_neb_image_cifs, read_or_convert_cif
from config import DATA_DIR, load_servers, load_settings, load_task_registry
from dashboard import build_cluster_health, build_cores_usage, cluster_snapshot
from dates import now_iso
from report_charts import (
    clip_polyline,
    dos_lines_chart,
    donut_chart,
    energy_force_chart,
    planar_average_chart,
    progress_bar,
)
from report_panels import (
    COLOR_PRIMARY,
    SEGMENT_COLORS,
    free_energy_panel,
    neb_panel,
    segmented_progress_chart,
)
from report_rules import evaluate as evaluate_rules
from report_rules import load_rules, priority_for, rules_meta
from report_schema import (
    REPORT_SECTIONS,
    SCHEMA_VERSION,
    TASK_TYPES,
    validate_report,
)
from storage import load_db
from structure_analysis import analyze as analyze_structure
import structure_images
import charge_diff
import bader
import pdos
import work_function
from ele_diff import diff_charge_blocks
from task_paths import is_auxiliary_task, is_continuation_task, task_dir

AUDIT_FILE = DATA_DIR / "audit_submit.log"

TASK_TYPE_LABELS = {
    "opt": "结构优化",
    "frac": "频率矫正",
    "neb": "NEB 过渡态",
    "ele": "电子结构",
}
STATUS_LABELS = {
    "pending": "待提交",
    "queued": "排队中",
    "running": "运行中",
    "completed": "已完成",
    "unconverged": "未收敛",
    "zombied": "异常中断",
    "archived": "已关闭",
    "low_precision": "低精度收敛",
}
SUBTYPE_LABELS = {
    "pdos": "PDOS",
    "bader": "Bader 分析",
    "diff_charge": "差分电荷",
    "work_function": "功函数",
}
ANOMALY_CATEGORIES = ("convergence", "resource", "file", "ssh", "queue")

MAX_STRUCTURE_TASKS = 6  # 单项目正文最多展示多少个结构优化任务（其余只进结构化数据），控制篇幅


def _views_dialog(
    project_name: str,
    task_obj: Dict[str, Any],
    dialog_id: str,
    title: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """把一个任务（opt/ele）的 a/b/c 三视图打包成弹窗规格。

    返回 `(弹窗规格, {报告内的图片相对路径: 磁盘源文件})`；没有图就返回 `(None, {})` ——
    报告**优先用 `<任务目录>/images/` 里 VESTA 渲染好的三视图**，没有就跳过（用户口径 2026-10-07）。
    """
    if not task_obj:
        return None, {}
    views = structure_images.task_views(project_name, task_obj)
    rows: List[Dict[str, Any]] = []
    images: Dict[str, str] = {}
    for key, label in (("poscar", "初始（POSCAR）"), ("contcar", "优化后（CONTCAR）")):
        axis_views = views.get(key) or {}
        if len(axis_views) < 3:
            continue
        row: Dict[str, Any] = {"label": label, "views": {}}
        for axis in ("a", "b", "c"):
            name = f"{dialog_id}_{key}_{axis}.png"
            images[name] = axis_views[axis]
            row["views"][axis] = f"images/{name}"
        rows.append(row)
    if not rows:
        return None, {}
    return {"id": dialog_id, "title": title, "rows": rows}, images


def _charge_diff_dialog(
    dialog_id: str, title: str, views: Dict[str, str]
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """差分电荷（`CHGCAR_diff`）三视图弹窗规格（结构与 `_views_dialog` 一致，单行）。

    `views` = `{axis: 磁盘 PNG 路径}`（来自 `charge_diff.local_images`，缺轴就不出弹窗）；
    图片按 `images/<dialog_id>_<axis>.png` 命名，与结构/映像三视图共用同一条内联通道
    （导出 HTML 时 base64 内联，网页里走报告图片接口）。
    """
    if len(views) < 3:
        return None, {}
    row: Dict[str, Any] = {"label": "差分电荷 Δρ（CHGCAR_diff）", "views": {}}
    images: Dict[str, str] = {}
    for axis in ("a", "b", "c"):
        name = f"{dialog_id}_{axis}.png"
        images[name] = views[axis]
        row["views"][axis] = f"images/{name}"
    return {"id": dialog_id, "title": title, "rows": [row]}, images


def _neb_image_dialog(
    dialog_id: str, title: str, views: Dict[str, str]
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """NEB 单个映像的三视图弹窗规格（结构与 `_views_dialog` 一致）。"""
    if len(views) < 3:
        return None, {}
    row: Dict[str, Any] = {"label": "优化后（CONTCAR）", "views": {}}
    images: Dict[str, str] = {}
    for axis in ("a", "b", "c"):
        name = f"{dialog_id}_{axis}.png"
        images[name] = views[axis]
        row["views"][axis] = f"images/{name}"
    return {"id": dialog_id, "title": title, "rows": [row]}, images
CHART_WIDTH = 1000  # 报告里所有图表统一宽度（页面按 1:1 展示，排版与字号才一致）
OPT_CURVE_W = 538  # 面板里右侧能量/力曲线宽度（4+438+16+538+4 = 1000）
OPT_CURVE_H = 250

# 任务类别（与巡检列表 / 前端任务树同口径）
CATEGORY_ORDER = ("结构优化", "自由能路径", "NEB 过渡态", "电子结构")
STATUS_DONE = ("completed", "archived")
DEFAULT_WORKLOAD_WEIGHT = 1.0

# 当量 → 核时 → 工期（2026-10-06 用户更新口径）
#   1 当量（= 一次结构优化）＝ 24 核 × 24 h/天 × 3 天 = **1728 核时**；
#   服务器最大算力 200 核 × 24 h；实际可用按 70% 折算
DEFAULT_CORE_HOURS_PER_WEIGHT = 1728.0
DEFAULT_CLUSTER_MAX_CORES = 200.0
DEFAULT_CLUSTER_UTILIZATION = 0.7
CAPACITY_KEYS = ("core_hours_per_weight", "cluster_max_cores", "cluster_utilization")


def _task_category(fact: Dict[str, Any]) -> str:
    """按任务分组判定类别（口径同 `checks_store._task_category`）。

    自由能路径的中间体结构优化（group_type=free_energy）与 NEB 的初/末态优化
    （group_type=neb）**不算独立的结构优化任务**——否则一条 7 个中间体的自由能
    路径会被误记成 7 个结构优化任务（v0.7.3 修正）。
    """
    group = fact.get("group") or {}
    gtype = group.get("group_type")
    task_type = str(fact.get("task_type") or "")
    if gtype == "free_energy" or (task_type == "frac" and not gtype):
        return "自由能路径"
    if gtype == "neb" or task_type == "neb":
        return "NEB 过渡态"
    if task_type == "ele":
        return "电子结构"
    return "结构优化"


def _workload_weight(task_type: str, registry: Dict[str, Any]) -> float:
    """任务当量：`task_registry.json` 的 workload_weight（opt/frac 1、neb 5、ele 0.4）。"""
    entry = registry.get(task_type) or {}
    try:
        return float(entry.get("workload_weight", DEFAULT_WORKLOAD_WEIGHT))
    except (TypeError, ValueError):
        return DEFAULT_WORKLOAD_WEIGHT


def _progress_segments(facts: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float]:
    """按任务类型分段统计进度：块宽 = 该类型当量占比，主进度 = 当量加权完成率。"""
    registry = _registry()
    buckets: Dict[str, Dict[str, float]] = {}
    for fact in facts:
        category = _task_category(fact)
        weight = _workload_weight(str(fact.get("task_type") or ""), registry)
        bucket = buckets.setdefault(
            category, {"count": 0.0, "done": 0.0, "weight": 0.0, "done_weight": 0.0}
        )
        bucket["count"] += 1
        bucket["weight"] += weight
        if fact.get("status") in STATUS_DONE:
            bucket["done"] += 1
            bucket["done_weight"] += weight
    total_weight = sum(b["weight"] for b in buckets.values()) or 1.0
    segments: List[Dict[str, Any]] = []
    for category in CATEGORY_ORDER:
        bucket = buckets.get(category)
        if not bucket or not bucket["count"]:
            continue
        segments.append(
            {
                "label": category,
                "color": SEGMENT_COLORS.get(category, COLOR_PRIMARY),
                "count": int(bucket["count"]),
                "done": int(bucket["done"]),
                "weight": round(bucket["weight"], 2),
                "done_weight": round(bucket["done_weight"], 2),
                "percent": round(bucket["done_weight"] / (bucket["weight"] or 1.0) * 100, 1),
                "share": round(bucket["weight"] / total_weight * 100, 1),
            }
        )
    main_percent = round(sum(b["done_weight"] for b in buckets.values()) / total_weight * 100, 1)
    return segments, main_percent


def _registry() -> Dict[str, Any]:
    try:
        return load_task_registry()
    except Exception:  # noqa: BLE001 - 配置缺失不阻塞报告
        return {}


def _capacity() -> Dict[str, float]:
    """算力口径（settings.json 可改）：1 当量 = 1728 核时（24 核 × 3 天），200 核 × 24h × 70%。"""
    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001
        settings = {}

    def _num(key: str, default: float) -> float:
        try:
            return float(settings.get(key, default))
        except (TypeError, ValueError):
            return default

    per_unit = _num("core_hours_per_weight", DEFAULT_CORE_HOURS_PER_WEIGHT)
    max_cores = _num("cluster_max_cores", DEFAULT_CLUSTER_MAX_CORES)
    utilization = _num("cluster_utilization", DEFAULT_CLUSTER_UTILIZATION)
    per_day = max_cores * 24 * utilization
    return {
        "core_hours_per_weight": per_unit,
        "max_cores": max_cores,
        "utilization": utilization,
        "core_hours_per_day": per_day,
    }


def _workload_plan(facts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按当量折算核时并给出工期：剩余核时 ÷ 有效产能（核时/天）。"""
    registry = _registry()
    capacity = _capacity()
    per_unit = capacity["core_hours_per_weight"]
    total_units = 0.0
    done_units = 0.0
    for fact in facts:
        weight = _workload_weight(str(fact.get("task_type") or ""), registry)
        total_units += weight
        if fact.get("status") in STATUS_DONE:
            done_units += weight
    remaining_units = max(total_units - done_units, 0.0)
    total_hours = total_units * per_unit
    done_hours = done_units * per_unit
    remaining_hours = remaining_units * per_unit
    per_day = capacity["core_hours_per_day"]
    eta_days = round(remaining_hours / per_day, 2) if per_day > 0 else None
    eta_at = (
        (datetime.now() + timedelta(days=eta_days)).strftime("%Y-%m-%d") if eta_days is not None else None
    )
    return {
        "total_units": round(total_units, 2),
        "done_units": round(done_units, 2),
        "remaining_units": round(remaining_units, 2),
        "core_hours_total": round(total_hours, 1),
        "core_hours_done": round(done_hours, 1),
        "core_hours_remaining": round(remaining_hours, 1),
        "core_hours_per_weight": per_unit,
        "core_hours_per_day": round(per_day, 1),
        "max_cores": capacity["max_cores"],
        "utilization": capacity["utilization"],
        "eta_days": eta_days,
        "eta_at": eta_at,
    }


# --------------------------------------------------------------------- 工具


def _label(mapping: Dict[str, str], key: Any, fallback: str = "—") -> str:
    return mapping.get(str(key), str(key) if key else fallback)


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("/", "-").replace(" ", "T", 1) if "/" in value else value)
    except ValueError:
        return None


def _submit_times() -> Dict[str, str]:
    """从审计日志解析 job_id → 提交时间（用于估算运行时长）。"""
    result: Dict[str, str] = {}
    if not AUDIT_FILE.is_file():
        return result
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-3000:]
    except OSError:
        return result
    for line in lines:
        m = re.match(r"^\[([^\]]+)\].*job=(\d+)", line)
        if m:
            result[m.group(2)] = m.group(1)
    return result


def _find_project(db: Dict[str, Any], project: str) -> Optional[Dict[str, Any]]:
    for item in db.get("projects", []):
        if project in (str(item.get("project_id")), str(item.get("name"))):
            return item
    return None


def _project_days_left(project: Dict[str, Any]) -> Optional[int]:
    try:
        return (date.fromisoformat(str(project.get("deadline"))) - date.today()).days
    except ValueError:
        return None


def _time_progress_percent(project: Dict[str, Any]) -> Optional[float]:
    try:
        created = date.fromisoformat(str(project.get("created_at"))[:10])
        deadline = date.fromisoformat(str(project.get("deadline")))
    except ValueError:
        return None
    span = (deadline - created).days
    if span <= 0:
        return 100.0
    used = (date.today() - created).days
    return round(min(max(used / span * 100, 0), 100), 1)


# ----------------------------------------------------- 任务事实 / 结构化数据


def _task_facts(
    project: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    merged: Dict[str, Dict[str, Any]],
    submit_times: Dict[str, str],
    cores_by_job: Dict[str, int],
) -> List[Dict[str, Any]]:
    """把任务压成扁平事实表（供规则引擎与各章节复用）。"""
    by_dir = {str(t.get("dir_path") or ""): t for t in project.get("tasks", [])}
    frac_of: Dict[str, Dict[str, Any]] = {}
    for task in project.get("tasks", []):
        if task.get("task_type") == "frac":
            frac_of[str(task.get("dir_path") or "").rsplit("/frac", 1)[0]] = task

    facts: List[Dict[str, Any]] = []
    for task in tasks:
        entry = merged.get(str(task.get("task_id"))) or {}
        current = task.get("current_output") or {}
        latest_dir = ""
        if isinstance(current, dict):
            latest_dir = str(current.get("latest_dir") or "")
        job_id = str(task.get("job_id") or "")
        submitted = _parse_time(submit_times.get(job_id)) if job_id else None
        runtime_hours = None
        if submitted:
            runtime_hours = round((datetime.now() - submitted).total_seconds() / 3600, 2)
        continuation_count = len(
            [
                t
                for t in project.get("tasks", [])
                if is_continuation_task(t)
                and str(t.get("dir_path") or "").startswith(
                    str(task.get("dir_path") or "") + "/con"
                )
            ]
        )
        frac = frac_of.get(str(task.get("dir_path") or ""))
        dependency = None
        dependency_name = ""
        dependency_status = None
        if task.get("task_type") == "frac" and frac is None:
            pass
        # 依赖关系：NEB 依赖初/末态优化；frac 依赖同结构 opt
        parent_id = str(task.get("parent_task_id") or "")
        if parent_id:
            parent = next(
                (t for t in project.get("tasks", []) if str(t.get("task_id")) == parent_id),
                None,
            )
            if parent is not None:
                dependency = parent
        if dependency is None and (task.get("group") or {}).get("group_role") == "neb_images":
            siblings = [
                t
                for t in project.get("tasks", [])
                if str((t.get("group") or {}).get("group_id"))
                == str((task.get("group") or {}).get("group_id"))
                and (t.get("group") or {}).get("group_role") in ("initial_opt", "final_opt")
            ]
            pending = [t for t in siblings if t.get("status") != "completed"]
            if pending:
                dependency = pending[0]
        if dependency is not None:
            dependency_name = str(dependency.get("model_name") or "")
            dependency_status = str(dependency.get("status") or "")

        force_history = entry.get("force_history") or []
        last_step = None
        if isinstance(force_history, list) and force_history:
            last = force_history[-1]
            if isinstance(last, dict):
                last_step = last.get("step")
        band_steps = entry.get("neb_band_steps")
        steps = band_steps if task.get("task_type") == "neb" and band_steps else (
            len(force_history) if isinstance(force_history, list) and force_history else None
        )
        facts.append(
            {
                "task_id": str(task.get("task_id") or ""),
                "task_name": str(task.get("model_name") or ""),
                "task_type": str(task.get("task_type") or ""),
                "task_type_label": _label(TASK_TYPE_LABELS, task.get("task_type")),
                "subtype": str(task.get("subtype") or ""),
                "subtype_label": _label(SUBTYPE_LABELS, task.get("subtype"), "—"),
                "status": str(task.get("status") or "pending"),
                "status_label": _label(STATUS_LABELS, task.get("status")),
                "job_id": job_id or None,
                "queue": entry.get("queue_status") or None,
                "cores": cores_by_job.get(job_id),
                "runtime_hours": runtime_hours,
                "dir_path": str(task.get("dir_path") or ""),
                "remote_dir": str(task.get("remote_dir") or ""),
                "latest_output_dir": latest_dir or None,
                "last_energy": task.get("last_energy"),
                "force_max": entry.get("force_max"),
                "force_rms": entry.get("force_rms"),
                "converged": entry.get("force_converged"),
                "corrected": (frac or {}).get("correction") is not None
                if task.get("task_type") == "frac"
                else None,
                "steps": steps,
                "last_step": last_step,
                "continuation_count": continuation_count,
                "has_output": bool(
                    entry.get("last_energy") is not None
                    or task.get("last_energy") is not None
                    or latest_dir
                ),
                "analyzed": bool(
                    entry.get("available_analyses")
                    or (entry.get("neb_barrier") or {}).get("images")
                )
                if task.get("task_type") in ("ele", "neb")
                else None,
                "dependency_name": dependency_name,
                "dependency_status": dependency_status,
                "dependency_status_label": _label(STATUS_LABELS, dependency_status, "—")
                if dependency_status
                else "—",
                "errors": [str(x) for x in (entry.get("error_messages") or [])],
                "markers": [str(x) for x in (entry.get("markers") or [])],
                # 精度检查（batch_check 按 INCAR/KPOINTS 判定，见 §6.2 巡检性能与精度）
                "precision": entry.get("precision") or None,
                "precision_ok": (entry.get("precision") or {}).get("ok"),
                "convergence": entry.get("status"),
                "incar_snapshot": entry.get("incar") or None,
                "notes": str(entry.get("notes") or ""),
                "last_check_time": task.get("last_check_time"),
                "force_history": force_history if isinstance(force_history, list) else [],
                "neb_barrier": entry.get("neb_barrier") or None,
                "group": task.get("group") or None,
                "archived_from": task.get("archived_from"),
            }
        )
    return facts


def _task_detail_row(fact: Dict[str, Any]) -> Dict[str, Any]:
    """§3.4 任务详情字段（统一字段 + 单位）。"""
    return {
        "task_id": fact["task_id"],
        "task_name": fact["task_name"],
        "task_type": fact["task_type"],
        "task_type_label": fact["task_type_label"],
        "subtype": fact["subtype"] or None,
        "status": fact["status"],
        "status_label": fact["status_label"],
        "remote_dir": fact["remote_dir"],
        "latest_output_dir": fact["latest_output_dir"],
        "last_energy_ev": fact["last_energy"],
        "force_max_ev_per_a": fact["force_max"],
        "force_rms_ev_per_a": fact["force_rms"],
        "force_converged": fact["converged"],
        "ionic_steps": fact["steps"],
        "continuation_count": fact["continuation_count"],
        "job_id": fact["job_id"],
        "queue": fact["queue"],
        "cores": fact["cores"],
        "runtime_hours": fact["runtime_hours"],
        "errors": fact["errors"],
    }


def _free_energy_paths(
    project: Dict[str, Any], facts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """自由能路径：按组聚合 opt + frac（§3.4 / §3.5）。"""
    by_group: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for fact in facts:
        group = fact.get("group") or {}
        if group.get("group_type") == "free_energy" and group.get("group_id"):
            by_group[str(group["group_id"])].append(fact)
    paths: List[Dict[str, Any]] = []
    for group_id, members in by_group.items():
        main = [
            f
            for f in members
            if (f.get("group") or {}).get("group_role") == "main_structure"
            and f["task_type"] == "opt"
        ]
        fracs = {
            str((f.get("group") or {}).get("structure_label")): f
            for f in members
            if f["task_type"] == "frac"
        }
        structures: List[Dict[str, Any]] = []
        for opt in main:
            label = str((opt.get("group") or {}).get("structure_label") or "")
            frac = fracs.get(label)
            correction = None
            if frac is not None:
                frac_task = next(
                    (
                        t
                        for t in project.get("tasks", [])
                        if str(t.get("task_id")) == frac["task_id"]
                    ),
                    None,
                )
                correction = (frac_task or {}).get("correction")
            dft = opt["last_energy"]
            free = (
                round(float(dft) + float(correction), 6)
                if isinstance(dft, (int, float)) and isinstance(correction, (int, float))
                else None
            )
            structures.append(
                {
                    "structure_label": label,
                    "opt_task_id": opt["task_id"],
                    "opt_status": opt["status"],
                    "frac_task_id": (frac or {}).get("task_id"),
                    "frac_status": (frac or {}).get("status"),
                    "dft_energy_ev": dft,
                    "zpe_ev": None,  # 频率输出解析待接入（TODO）
                    "correction_ev": correction,
                    "free_energy_ev": free,
                    # 收敛判定优先用巡检结果（force_converged），归档任务也保留该结果；
                    # 没有巡检数据时退回状态判断（已完成 / 已关闭都算收尾）
                    "converged": (
                        bool(opt["converged"])
                        if opt.get("converged") is not None
                        else opt["status"] in STATUS_DONE
                    ),
                    "corrected": correction is not None,
                }
            )
        try:
            structures.sort(key=lambda s: int(s["structure_label"] or 999))
        except ValueError:
            structures.sort(key=lambda s: str(s["structure_label"]))
        name = ""
        for fact in members:
            name = str((fact.get("group") or {}).get("name") or "")
            if name:
                break
        paths.append(
            {
                "group_id": group_id,
                "group_name": name or group_id,
                "structures": structures,
                "structure_count": len(structures),
                "corrected_count": sum(1 for s in structures if s["corrected"]),
            }
        )
    paths.sort(key=lambda p: p["group_name"])
    return paths


def _neb_details(facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """NEB 任务：映像能量/能垒 + 初末态优化状态（§3.4 / §3.5）。"""
    items: List[Dict[str, Any]] = []
    for fact in facts:
        if fact["task_type"] != "neb":
            continue
        barrier = fact.get("neb_barrier") or {}
        images = [
            {
                "label": str(img.get("label")),
                "relative_energy_ev": img.get("relative"),
                "energy_ev": img.get("energy"),
                "max_force_ev_per_a": img.get("max_force"),
            }
            for img in (barrier.get("images") or [])
        ]
        rels = [i["relative_energy_ev"] for i in images if i["relative_energy_ev"] is not None]
        barrier_value = max(rels) if rels else None
        ts_label = None
        if rels:
            ts_label = images[rels.index(barrier_value)]["label"]
        items.append(
            {
                "task_id": fact["task_id"],
                "task_name": fact["task_name"],
                "status": fact["status"],
                "status_label": fact["status_label"],
                "stages": {
                    "initial_opt": {"status": None, "status_label": "—"},
                    "final_opt": {"status": None, "status_label": "—"},
                },
                "images": images,
                "image_count": len(images),
                "barrier_ev": barrier_value,
                "transition_state_image": ts_label,
                "band_steps": fact["steps"],
                "converged_images": [
                    i["label"]
                    for i in images
                    if (i["max_force_ev_per_a"] or 0) < 0.05
                ],
                "charts": [],
            }
        )
    return items


def _ele_details(
    project: Dict[str, Any],
    facts: List[Dict[str, Any]],
    merged: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """电子结构任务：子类型 / 分析状态 / 结果文件（§3.5）+ **差分电荷分块**（2026-10-13）。

    分块子任务（`ele_diff`）不进入 facts（不参与统计/当量），这里从任务库取它们的
    状态与能量（有巡检结果就以巡检为准）。
    """
    items = []
    merged = merged or {}
    by_id = {str(t.get("task_id")): t for t in project.get("tasks", [])}
    for fact in facts:
        if fact["task_type"] != "ele":
            continue
        task = by_id.get(str(fact["task_id"])) or {}
        blocks = []
        for block in diff_charge_blocks(project, task):
            entry = merged.get(str(block.get("task_id"))) or {}
            status = str(block.get("status") or "")
            blocks.append(
                {
                    "task_id": block.get("task_id"),
                    "task_name": block.get("model_name"),
                    "block": int(block.get("ele_block") or 0),
                    "block_label": block.get("ele_block_label"),
                    "atoms_count": len(block.get("ele_block_atoms") or []),
                    "status": status,
                    "status_label": _label(STATUS_LABELS, status),
                    "last_energy_ev": entry.get("last_energy")
                    if entry.get("last_energy") is not None
                    else block.get("last_energy"),
                    "force_max_ev_per_a": entry.get("force_max"),
                    "converged": bool(entry.get("force_converged")),
                    "check_time": entry.get("checked_at"),
                    "errors": entry.get("error_messages") or [],
                }
            )
        items.append(
            {
                "task_id": fact["task_id"],
                "task_name": fact["task_name"],
                "subtype": fact["subtype"] or None,
                "subtype_label": fact["subtype_label"],
                "status": fact["status"],
                "status_label": fact["status_label"],
                "analysis_status": "analyzed" if fact["analyzed"] else "pending",
                "result_files": [],
                "chart_paths": [],
                "notes": fact["notes"],
                # 差分电荷：块数 + 各分块状态；差分文件由**远端** VTST 脚本算好回传
                # （2026-10-14 口径变更，见 backend/ele_diff.py::compute_charge_difference）
                "diff_charge": blocks,
                "charge_diff": task.get("charge_diff") or None,
                # Bader 电荷：远端算完的 ACF.dat 台账（v0.9.51；逐原子净电荷在 build_report 里补）
                "bader": task.get("bader") or None,
            }
        )
    return items


def _frac_details(
    project: Dict[str, Any], facts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """频率矫正：ZPE / 热校正 / 频率列表（频率解析待接入，字段先占位）。"""
    items = []
    by_id = {str(t.get("task_id")): t for t in project.get("tasks", [])}
    for fact in facts:
        if fact["task_type"] != "frac":
            continue
        task = by_id.get(fact["task_id"]) or {}
        items.append(
            {
                "task_id": fact["task_id"],
                "task_name": fact["task_name"],
                "status": fact["status"],
                "status_label": fact["status_label"],
                "zpe_ev": task.get("zpe"),
                "thermal_correction_ev": task.get("correction"),
                "frequencies_cm1": task.get("frequencies") or [],
                "imaginary_frequencies_cm1": task.get("imaginary_frequencies") or [],
                "parsed": task.get("zpe") is not None or task.get("correction") is not None,
            }
        )
    return items


# ------------------------------------------------------------------ Markdown


# ------------------------------------------------- 电子结构（PDOS / 功函数，v0.9.61）

#: 报告里 PDOS 静态图的默认坐标范围与带中心积分区间（与前端面板默认值一致：-10 ~ 10 eV）
PDOS_REPORT_RANGE = (-10.0, 10.0)
#: 静态图每条约多少点（交互版用全量 3000 点；静态图只求"看得清"，控制 SVG 体积）
PDOS_REPORT_POINTS = 600
#: 静态图默认画几条曲线：总态密度 + 各元素的 d 轨道（催化里最常看的一组）
PDOS_REPORT_MAX_CURVES = 16


def _downsample(xs: List[float], ys: List[float], limit: int) -> List[tuple]:
    """等距抽点（首尾保留）—— 静态图不需要 3000 个点，抽到 600 点肉眼看不出差别。"""
    n = min(len(xs), len(ys))
    if n <= limit:
        return [(xs[i], ys[i]) for i in range(n)]
    step = n / float(limit)
    out = [(xs[int(i * step)], ys[int(i * step)]) for i in range(limit)]
    out.append((xs[n - 1], ys[n - 1]))
    return out


def _band_center(xs: List[float], ys: List[float], lo: float, hi: float) -> Optional[float]:
    """带中心 ∫E·DOS dE / ∫DOS dE（梯形积分 + 边界线性插值裁剪）。

    与前端 `src/utils/bandCenter.ts`、报告页内核 `interactive/pdosChart.ts` **同口径**：
    含未占据态、边界裁剪、区间内没有态返回 None。
    """
    n = min(len(xs), len(ys))
    if n < 2 or not (hi > lo):
        return None
    num = 0.0
    den = 0.0
    for i in range(1, n):
        x0, x1 = xs[i - 1], xs[i]
        v0, v1 = ys[i - 1], ys[i]
        if x1 == x0:
            continue
        left = max(x0, lo)
        right = min(x1, hi)
        if right <= left:
            continue
        span = x1 - x0
        v_left = v0 + (v1 - v0) * (left - x0) / span
        v_right = v0 + (v1 - v0) * (right - x0) / span
        weight = (v_left + v_right) / 2.0 * (right - left)
        num += (left + right) / 2.0 * weight
        den += weight
    if abs(den) < 1e-12:
        return None
    return num / den


def _pdos_walk(node: Dict[str, Any]):
    yield node
    for child in node.get("children") or []:
        yield from _pdos_walk(child)


def _pdos_report_data(
    project_name: str,
    ele_obj: Dict[str, Any],
    charts: Dict[str, str],
    errors: List[str],
) -> Optional[Dict[str, Any]]:
    """PDOS 本地整合数据 → 报告摘要 + 静态兜底图；没有结果返回 None。

    静态图 = **总态密度 + 各元素 d 轨道**（默认视角，自旋镜像布局），带中心按
    `PDOS_REPORT_RANGE` 积分后画在同色竖直虚线上。交互版（勾轨道 / 改范围 / 实时算带中心）
    由报告页与导出的单文件 HTML 注入的 ECharts 组件提供，用的是同一份数据。
    """
    path = pdos.data_path(project_name, ele_obj)
    if not (path.is_file() and path.stat().st_size > 0):
        return None
    try:
        view = pdos.load_view(project_name, ele_obj)
    except Exception as exc:  # noqa: BLE001 - 报告不因 PDOS 失败
        errors.append(f"{ele_obj.get('task_name')} PDOS 结果读取失败：{exc}")
        return None

    total_xs = list(view.get("energy", {}).get("total") or [])
    partial_xs = list(view.get("energy", {}).get("partial") or [])
    if not total_xs:
        return None
    # 投影网格 = 总网格去掉 EMIN 首行，按"起点偏移"对齐（与前端 partialOffsetOf 同口径）
    offset = 1
    if partial_xs:
        found = next(
            (i for i, x in enumerate(total_xs) if abs(x - partial_xs[0]) < 0.002), None
        )
        if found is not None:
            offset = found
    efermi = float(view.get("meta", {}).get("efermi") or 0.0)
    spin = bool(view.get("meta", {}).get("spin_polarized"))
    series = view.get("series") or {}

    def curve_points(curve: Dict[str, Any]):
        ref = series.get(curve.get("id") or "")
        if not ref:
            return None
        values = list(ref.get("values") or [])
        if not values:
            return None
        if ref.get("grid") == "partial":
            xs = [total_xs[i + offset] for i in range(len(values)) if i + offset < len(total_xs)]
        else:
            xs = total_xs[: len(values)]
        if len(xs) != len(values):
            values = values[: len(xs)]
        return xs, values

    # 默认视角：总态密度 + 各元素 d 轨道
    picked: List[tuple] = []  # (节点标题, 元素, 曲线)
    for node in _pdos_walk({"children": view.get("tree") or []}):
        if not node.get("key"):
            continue
        if node["key"] == "total":
            for curve in node.get("curves") or []:
                picked.append(("总态密度", "", curve))
        elif str(node["key"]).endswith(":d") and not str(node["key"]).endswith(":d:d"):
            # 节点 key = `el:<元素>:d`（节点自身 label 只是轨道名 "d"）
            parts = str(node["key"]).split(":")
            element = parts[1] if len(parts) > 1 else ""
            for curve in node.get("curves") or []:
                picked.append(("d", element, curve))
    picked = picked[:PDOS_REPORT_MAX_CURVES]

    lo, hi = PDOS_REPORT_RANGE
    spin_label = {"up": "↑", "down": "↓", "total": ""}
    lines: List[Dict[str, Any]] = []
    bands: List[Dict[str, Any]] = []
    centers: List[Dict[str, Any]] = []
    for title_text, element, curve in picked:
        got = curve_points(curve)
        if not got or not got[1]:
            continue
        xs, values = got
        rel_x = [x - efermi for x in xs]
        name = (
            f"{title_text}{' ' + element if element else ''} "
            f"{spin_label.get(str(curve.get('spin')), '')}"
        ).strip()
        sign = -1.0 if (spin and curve.get("spin") == "down") else 1.0
        # **先按展示窗口裁剪再抽点** —— 否则 600 个点里绝大部分落在窗口外，窗口内变得很稀疏
        clipped = clip_polyline(list(zip(rel_x, [v * sign for v in values])), lo, hi)
        points = _downsample(
            [p[0] for p in clipped], [p[1] for p in clipped], PDOS_REPORT_POINTS
        )
        lines.append(
            {
                "name": name,
                "color": curve.get("color") or "#5B8DEF",
                "points": points,
                "dashed": curve.get("spin") == "down",
                "width": 2.2 if title_text == "总态密度" else 1.3,
            }
        )
        center = _band_center(rel_x, values, lo, hi)
        if center is not None:
            centers.append({"name": name, "value": round(center, 4), "color": curve.get("color")})
            bands.append(
                {
                    "x": center,
                    "color": curve.get("color") or "#5B8DEF",
                    "label": f"{name} 带中心 {center:.2f} eV",
                    "dashed": curve.get("spin") == "down",
                }
            )

    task_id = str(ele_obj.get("task_id") or "")
    chart_name = f"pdos_{task_id}.svg"
    if lines:
        charts[chart_name] = dos_lines_chart(
            lines,
            title=f"{ele_obj.get('task_name') or task_id} 态密度（PDOS）",
            x_min=lo,
            x_max=hi,
            bands=bands,
        )
    return {
        "available": True,
        "task_id": task_id,
        "elements": view.get("meta", {}).get("elements") or [],
        "efermi": view.get("meta", {}).get("efermi"),
        "spin_polarized": spin,
        "points": view.get("meta", {}).get("points"),
        "partial_points": view.get("meta", {}).get("partial_points"),
        "has_projection": view.get("meta", {}).get("has_projection"),
        "has_fine_orbitals": view.get("meta", {}).get("has_fine_orbitals"),
        "series_count": len(series),
        "generated_at": view.get("meta", {}).get("generated_at"),
        "source": view.get("meta", {}).get("source"),
        "range": list(PDOS_REPORT_RANGE),
        "default_curves": [line["name"] for line in lines],
        "band_centers": centers,
        "chart": f"charts/{chart_name}" if lines else None,
    }


def _work_function_report_data(
    project_name: str,
    ele_obj: Dict[str, Any],
    charts: Dict[str, str],
    errors: List[str],
) -> Optional[Dict[str, Any]]:
    """功函数本地结果（PLANAR_AVERAGE.dat + meta）→ 报告摘要 + 静态兜底图；没有返回 None。"""
    path = work_function.data_path(project_name, ele_obj)
    if not (path.is_file() and path.stat().st_size > 0):
        return None
    try:
        data = work_function.load_data(project_name, ele_obj)
    except Exception as exc:  # noqa: BLE001 - 报告不因功函数失败
        errors.append(f"{ele_obj.get('task_name')} 功函数结果读取失败：{exc}")
        return None
    task_id = str(ele_obj.get("task_id") or "")
    chart_name = f"wf_{task_id}.svg"
    axis = str(data.get("axis") or "c")
    charts[chart_name] = planar_average_chart(
        list(zip(data.get("z") or [], data.get("potential") or [])),
        title=f"{ele_obj.get('task_name') or task_id} 平面平均静电势（{axis} 方向）",
        vacuum=data.get("vacuum_level"),
        fermi=data.get("efermi"),
    )
    return {
        "available": True,
        "task_id": task_id,
        "axis": axis,
        "axis_cartesian": data.get("axis_cartesian"),
        "efermi": data.get("efermi"),
        "vacuum_level": data.get("vacuum_level"),
        "vacuum_level_source": data.get("vacuum_level_source"),
        "work_function": data.get("work_function"),
        "work_function_vaspkit": data.get("work_function_vaspkit"),
        "points": data.get("points"),
        "warnings": data.get("warnings") or [],
        "dipole": data.get("dipole"),
        "elapsed_seconds": data.get("elapsed_seconds"),
        "elapsed": data.get("elapsed_seconds"),
        "z": data.get("z"),
        "potential": data.get("potential"),
        "chart": f"charts/{chart_name}",
    }


def _md_table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "_无数据_\n"
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = [
        "| " + " | ".join("" if c is None else str(c) for c in row) + " |" for row in rows
    ]
    return "\n".join([head, sep, *body]) + "\n"


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}" if isinstance(value, float) else str(value)
    return str(value)


def _one_line_summary(facts, stats, stage):
    return (
        f"未关闭任务 {stats['total']} 个，已完成 {stats['completed']} 个"
        + (f"、{stats['running']} 个运行中" if stats["running"] else "")
        + (f"、{stats['queued']} 个排队中" if stats["queued"] else "")
        + (f"、{stats['failed'] + stats['unconverged']} 个异常" if stats["failed"] + stats["unconverged"] else "")
        + (f"、{stats['pending']} 个待处理" if stats["pending"] else "")
        + f"；当前阶段：{stage}"
    )


def _sections_markdown(report, charts):
    """把结构化字段渲染为各章 Markdown（以总结为核心，不堆砌字段）。"""
    sections = {}
    info = report["basic_info"]
    summary = info["task_summary"]
    workload = info.get("workload") or {}
    status_icon = {"normal": "🟢", "warning": "🟠", "critical": "🔴"}[info["project_status"]]
    eta_text = (
        f"**{workload['eta_at']}**（按当量估算还需 {workload['eta_days']:.1f} 天"
        f"：剩余 {workload['core_hours_remaining']:,.0f} 核时 ÷ 有效算力 "
        f"{workload['core_hours_per_day']:,.0f} 核时/天）"
        if workload.get("eta_days") is not None and workload.get("core_hours_remaining", 0) > 0
        else "**已收尾**（剩余工作量为 0）"
    )
    sections["basic_info"] = "\n".join(
        [
            f"- **项目**：{info['project_name']}",
            f"- **交付日期**：{info.get('deadline') or '未填写'}",
            f"- **报告生成时间**：{info['generated_at']}",
            f"- **整体状态**：{status_icon} **{info['project_status_label']}** —— {info['status_reason']}",
            f"- **项目进度**：**{info.get('weighted_progress_percent', info['progress_percent'])}%**"
            f"（按任务当量加权，含已归档成果；{summary}）",
            f"- **未归档任务完成率**：{info['progress_percent']}%",
            f"- **折算工作量**：{workload.get('total_units', 0):.1f} 当量 ≈ "
            f"{workload.get('core_hours_total', 0):,.0f} 核时（1 当量 "
            f"{workload.get('core_hours_per_weight', 0):.0f} 核时），已完成 "
            f"{workload.get('core_hours_done', 0):,.0f} 核时",
            f"- **预计完成（估算）**：{eta_text}",
            f"- **时间窗口**：{info['time_window_label']}",
            "",
            "_核时按任务当量折算，并非实测消耗；工期按固定有效算力估算，未计入排队与后续续算变化。_",
            "",
            f"**计算内容描述**：{info.get('calc_description') or '未填写'}",
            "",
            f"**预期结果**：{info.get('expected_results') or '未填写'}",
            "",
            f"![项目进度](charts/progress.svg)",
        ]
    ).strip() + "\n"

    science = report["science"]
    blocks = []
    ele_tasks = (science.get("ele") or {}).get("tasks") or []
    result_rows = []
    for item in ele_tasks:
        pdos_result = item.get("pdos_summary") or {}
        wf = item.get("work_function_summary") or {}
        bader_result = item.get("bader_summary") or {}
        if not (pdos_result or wf or bader_result or (item.get("charge_diff") or {}).get("ok")):
            continue
        centers = "；".join(
            f"{center['name']} {center['value']:+.2f}"
            for center in pdos_result.get("band_centers") or []
        )
        energy_range = pdos_result.get("range") or []
        if centers and len(energy_range) >= 2:
            centers += f"（区间 {_fmt(energy_range[0], 1)} ~ {_fmt(energy_range[1], 1)}）"
        result_rows.append([
            str(item.get("task_name") or "—"),
            _fmt(wf.get("work_function")),
            str(wf.get("axis") or "—"),
            centers or "—",
            f"{bader_result['n_atoms']} 个原子" if bader_result.get("n_atoms") else "—",
            "已生成" if (item.get("charge_diff") or {}).get("ok") else "—",
        ])
    if result_rows:
        blocks.extend([
            "### 关键结果概览\n\n",
            _md_table(
                ["模型", "功函数 (eV)", "方向", "带中心 (eV，相对 E_F)", "Bader 分析", "差分电荷"],
                result_rows,
            ),
            "\n带中心按所列轨道、自旋与积分区间分别统计；功函数按所列方向计算。详细结果见各模型分析。\n\n",
        ])
    opt_items = science.get("opt") or []
    if opt_items:
        blocks.append("### 结构优化\n")
        blocks.append(
            f"共 {science.get('opt_total') or len(opt_items)} 个结构优化任务有收敛数据，"
            f"下列展示其中 {len(opt_items)} 个，其余仅保留在报告数据中。每条包含结构三视图与能量/力曲线。"
            "（自由能路径的中间体与 NEB 的初/末态优化不在此列，见各自章节。）\n\n"
        )
        skipped_unconverged = int(science.get("opt_skipped_unconverged") or 0)
        if skipped_unconverged:
            blocks.append(
                # 只陈述事实（报告是对外文件，2026-10-15 用户："报告不出现警告和提示"）
                f"另有 **{skipped_unconverged} 个结构优化任务未收敛**，其结构与曲线未纳入本报告。\n\n"
            )
        entries: List[str] = []
        for item in opt_items:
            converge = "✅ 已收敛" if item["converged"] else "⚠️ 未收敛"
            lines = [
                f"#### {item['task_name']}",
                f"{converge} · 最终能量 **{_fmt(item['final_energy_ev'])} eV** · "
                f"最大力 **{_fmt(item['force_max_ev_per_a'])} eV/Å** · "
                f"离子步 {_fmt(item['ionic_steps'], 0)}",
            ]
            panel = item["charts"].get("panel") or item["charts"].get("energy_force")
            if item.get("conv_dialog"):
                # 能量/力曲线收进「收敛历史」弹窗（用户口径 2026-10-15）：正文只留一行入口，
                # 点开在弹窗里看曲线（报告页是可交互 ECharts，导出/打印是内联的那张 SVG）。
                lines.append(
                    f"**收敛历史**：[能量 / 最大力曲线"
                    f"（{_fmt(item['ionic_steps'], 0)} 个离子步）](#{item['conv_dialog']})"
                )
            elif panel:
                lines.append(f"![{item['task_name']} 结构三视图与能量/力曲线]({panel})")
            # VESTA 三视图（a/b/c，横向排列；报告生成时按用户口径优先用 images/ 里的图）
            # 同一行（初始 / 优化后）的 3 张图必须**连着写**（中间不留空行），
            # 导出器与前端才会把它们合成一行 .img-row；空行会把一行拆成三张竖排。
            # ⚠ 2026-10-16 起：屏幕上看 **3D 视图**（`@[structure-3d:...]`），这堆 PNG
            # **只留给打印 / PDF**（前端与导出运行时会把它们标记成"仅打印"，屏幕隐藏）。
            # 图片链路本身保留（生成、复制、内联都照旧）。
            structure = item.get("structure") or {}
            if structure.get("poscar_cif") or structure.get("contcar_cif"):
                lines.append(f"@[structure-3d:{item['task_id']}]")
            for row in item.get("structure_views") or []:
                row_lines = [
                    f"![{row['label']} · {axis} 视图]({(row.get('views') or {}).get(axis)})"
                    for axis in ("a", "b", "c")
                    if (row.get("views") or {}).get(axis)
                ]
                if row_lines:
                    lines.append("\n".join(row_lines))
            entries.append("\n\n".join(lines))
        # 任务之间用分隔线隔开，避免上下两个任务的面板图糊成一片
        blocks.append("\n\n---\n\n".join(entries) + "\n")
    paths = science.get("free_energy") or []
    if paths:
        blocks.append("### 自由能路径\n\n")
        blocks.append(
            "数值口径：校正后能量 = DFT 总能量 + 已有矫正项，相对值以首个具备数据的中间体为零点。"
            "反应自由能需结合配平反应、参考物种及温度、电位等条件解释；该台阶相对值不等同于 NEB 活化能垒。\n\n"
        )
        entries = []
        for path in paths:
            structures = path["structures"]
            with_energy = [s for s in structures if s.get("free_energy_ev") is not None]
            ref = float(with_energy[0]["free_energy_ev"]) if with_energy else None
            rels = [
                float(s["free_energy_ev"]) - ref
                for s in with_energy
                if ref is not None
            ]
            corrected = sum(1 for s in structures if s.get("corrected"))
            lines = [
                f"#### {path['group_name']}",
                f"{path['structure_count']} 个中间体 · {corrected} 个已矫正"
                + (f" · 最高相对能 {max(rels):+.3f} eV" if rels else ""),
            ]
            if not with_energy:
                # 频率矫正（G(T)）还没算 → 自由能列为空、台阶图不画；但结构三视图照样能点开
                lines.append(
                    "_尚未做频率矫正（G(T)）：自由能与相对 ΔE 列为空。_"
                )
            if path.get("chart"):
                lines.append(f"![{path['group_name']} 自由能路径看板]({path['chart']})")
            # 中间体结构：**3D 视图**（v0.9.73）—— 点表格里的「结构 N」切换显示哪个中间体；
            # 原来那个"点结构 N 看 PNG 三视图"的弹窗不再用（PNG 仍生成，留给打印/PDF）
            if any(s.get("cif") for s in structures):
                lines.append(f"@[free-energy-3d:{path['group_id']}]")

            def _structure_cell(index: int, structure: Dict[str, Any]) -> str:
                """中间体那一格：有 CIF → 点它切换上面的 3D 视图（`#fe-3d:<组>:<下标>:<任务 id>`，
                任务 id 供报告页在芯片旁挂「注」按钮用）；否则退回旧的 PNG 三视图弹窗链接。"""
                label = structure["structure_label"]
                if structure.get("cif"):
                    return (
                        f"[结构 {label}](#fe-3d:{path['group_id']}:{index}:"
                        f"{structure.get('opt_task_id') or ''})"
                    )
                if structure.get("dialog"):
                    return f"[结构 {label}](#{structure['dialog']})"
                return f"结构 {label}"

            lines.append(
                _md_table(
                    ["中间体", "DFT 能量 (eV)", "矫正项 (eV)", "自由能 (eV)", "相对 ΔE (eV)", "状态"],
                    [
                        [
                            _structure_cell(index, s),
                            _fmt(s["dft_energy_ev"]),
                            ("—" if s["correction_ev"] is None else f"{float(s['correction_ev']):+.4f}"),
                            _fmt(s["free_energy_ev"]),
                            (
                                "—"
                                if ref is None or s["free_energy_ev"] is None
                                else f"{float(s['free_energy_ev']) - ref:+.4f}"
                            ),
                            f"{'已收敛' if s['converged'] else '未收敛'} · "
                            f"{'已矫正' if s['corrected'] else '未矫正'}",
                        ]
                        for index, s in enumerate(structures)
                    ],
                )
            )
            entries.append("\n\n".join(lines))
        blocks.append("\n\n---\n\n".join(entries) + "\n")
    nebs = science.get("neb") or []
    if nebs:
        blocks.append("### NEB 过渡态\n\n")
        entries = []
        for item in nebs:
            lines = [
                f"#### {item['task_name']}",
                f"能垒 **{_fmt(item['barrier_ev'])} eV** · "
                f"过渡态映像 {item['transition_state_image'] or '—'} · "
                f"{item['image_count']} 个映像",
            ]
            if item.get("chart"):
                lines.append(f"![{item['task_name']} NEB 能垒看板]({item['chart']})")
            images = item.get("images") or []
            if images:
                saddle_label = item.get("transition_state_image")
                max_force_label = None
                force_values = [
                    (img.get("max_force_ev_per_a"), img.get("label")) for img in images
                ]
                force_values = [x for x in force_values if x[0] is not None]
                if force_values:
                    max_force_label = max(force_values)[1]
                roles = []
                for index, img in enumerate(images):
                    if index == 0:
                        roles.append("初态")
                    elif index == len(images) - 1:
                        roles.append("末态")
                    elif img.get("label") == saddle_label:
                        roles.append("鞍点")
                    else:
                        roles.append("中间态")
                lines.append(
                    _md_table(
                        ["映像", "相对能垒 (eV)", "绝对能量 (eV)", "最大受力 (eV/Å)", "角色"],
                        [
                            [
                                (
                                    f"[映像 {img['label']}](#{img['dialog']})"
                                    if img.get("dialog")
                                    else f"映像 {img['label']}"
                                ),
                                _fmt(img["relative_energy_ev"], 4),
                                _fmt(img["energy_ev"], 4),
                                _fmt(img["max_force_ev_per_a"], 4)
                                + (" ⬆" if img.get("label") == max_force_label else ""),
                                roles[index] + (" · 受力最大" if img.get("label") == max_force_label else ""),
                            ]
                            for index, img in enumerate(images)
                        ],
                    )
                )
            if any(not img.get("dialog") for img in images):
                lines.append(
                    "_部分映像暂无三视图。_"  # 报告对外：只说事实，不写内部流程
                )
            entries.append("\n\n".join(lines))
        blocks.append("\n\n---\n\n".join(entries) + "\n")
    empty_project = not blocks
    if empty_project:
        blocks.append("_本项目暂无可展示的科学结果（需任务产出 OUTCAR/CONTCAR 后自动生成）_\n")
    ele_note = science.get("ele") or {}
    ele_tasks = ele_note.get("tasks") or []
    # 「电子结构」章节：有差分电荷分块 / Bader / PDOS / 功函数结果时**一定**出
    # （哪怕项目里还没有别的科学结果），否则跟其它类型一样只留一句占位说明。
    with_diff = [
        item
        for item in ele_tasks
        if item.get("diff_charge")
        or item.get("bader")
        or item.get("pdos_summary")
        or item.get("work_function_summary")
    ]
    if with_diff or not empty_project:
        ele_blocks: List[str] = ["### 电子结构\n"]
        if with_diff:
            # 分两块渲染：差分电荷（有分块的任务）/ Bader 电荷（有 ACF.dat 的任务）
            for item in [x for x in with_diff if x.get("diff_charge")]:
                ele_blocks.append(f"\n#### {item['task_name']} · 差分电荷\n")
                ele_blocks.append(
                    "把完整结构按原子拆成若干分块单独做静态计算（各自独立提交），"
                    "再用三个 CHGCAR 做电荷密度差分（\u0394\u03c1 = \u03c1(完整) \u2212 \u03a3\u03c1(分块)）。\n\n"
                )
                ele_blocks.append(
                    _md_table(
                        ["分块", "原子数", "状态", "最后能量 (eV)", "最大受力 (eV/Å)", "检查时间"],
                        [
                            [
                                str(
                                    block.get("block_label")
                                    or f"分块{block.get('block')}"
                                ),
                                block.get("atoms_count"),
                                block.get("status_label") or "—",
                                _fmt(block.get("last_energy_ev"), 6),
                                _fmt(block.get("force_max_ev_per_a"), 4),
                                block.get("check_time") or "—",
                            ]
                            for block in item["diff_charge"]
                        ],
                    )
                )
                charge_diff = item.get("charge_diff") or {}
                if charge_diff.get("ok"):
                    diff_state = "差分电荷已生成（Δρ = ρ(完整) − Σρ(分块)）。"
                elif charge_diff:
                    # 失败原因只留在结构化数据里（报告是对外文件，不放警告）
                    diff_state = "差分电荷未完成。"
                else:
                    diff_state = "差分电荷尚未生成。"
                if item.get("charge_diff_dialog"):
                    ele_blocks.append(
                        f"{diff_state} 差分图（VESTA 三视图）见 "
                        f"[差分三视图（a / b / c）](#{item['charge_diff_dialog']})。\n\n"
                    )
                elif charge_diff.get("ok"):
                    # 差分算好了但本地三视图不在（被「清除三视图」删掉 / 只回了数据）
                    ele_blocks.append(
                        f"{diff_state} 差分图（VESTA 三视图）当前不在本地。\n\n"
                    )
                else:
                    ele_blocks.append(
                        f"{diff_state}\n\n"
                    )
            # Bader 电荷（v0.9.54）：远端 ACF.dat 的结果 + 逐原子净电荷统计（不做元素分组）
            for item in [x for x in with_diff if x.get("bader_summary")]:
                summary = item["bader_summary"]
                stats = summary.get("stats") or {}
                ele_blocks.append(f"\n#### {item['task_name']} · Bader 电荷\n")
                ele_blocks.append("Bader 电荷为原子分区内的电子数；净电荷 Δq = ZVAL − Bader 电荷，正值表示失电子，负值表示得电子。\n\n")
                if summary.get("net_charge_available") and stats:
                    ele_blocks.append(
                        f"共 {summary['n_atoms']} 个原子：Bader 电荷合计 "
                        f"{stats['charge_total']:.4f} e，价电子数（POTCAR ZVAL）合计 "
                        f"{stats['zval_total']:.4f} e，**净电荷合计 {stats['net_total']:+.4f} e**"
                        f"（平均 {stats['net_mean']:+.4f} e/原子）。"
                        f"Δq 最大（最正）的是 {stats['net_max']['element']}{stats['net_max']['index']}"
                        f"（{stats['net_max']['value']:+.4f} e），Δq 最小（最负）的是 "
                        f"{stats['net_min']['element']}{stats['net_min']['index']}"
                        f"（{stats['net_min']['value']:+.4f} e）。"
                        f"（净电荷 \u0394q = ZVAL \u2212 Bader 电荷，正值表示该原子失电子。）\n\n"
                    )
                    # 逐原子数据**只给完整表**（用户 2026-10-15："|Δq| 列最大的 10 个原子不需要"）：
                    # 上面那段统计已经给了关键数值（合计 / 均值 / Δq 最大最小），明细走下面的完整表。
                    # 完整表在页面/导出里是"直接展示 + 可滑动容器"（不是折叠）。
                    ele_blocks.append(f"@[bader-table:{item['task_id']}]\n\n")
                else:
                    ele_blocks.append(
                        f"已算出 `ACF.dat`（{summary['n_atoms']} 个原子，Bader 电荷合计 "
                        f"{summary['total_charge']:.4f} e）；"
                        "缺价电子数（ZVAL），未计算净电荷 Δq。\n\n"
                    )
            # PDOS（v0.9.61）：摘要 + 静态图（交互版由报告页 / 导出注入的组件接管这张图）
            for item in [x for x in with_diff if x.get("pdos_summary")]:
                summary = item["pdos_summary"]
                ele_blocks.append(f"\n#### {item['task_name']} · 态密度（PDOS）\n")
                ele_blocks.append("横轴能量相对费米能级 E_F；带中心按所列轨道与积分范围计算。\n\n")
                if summary.get("chart"):
                    ele_blocks.append(
                        f"![{item['task_name']} 态密度]({summary['chart']})\n\n"
                    )
                    # 交互挂点：报告页点「加载交互图」后接管；导出的单文件 HTML 直接注入运行时
                    ele_blocks.append(f"@[pdos-chart:{item['task_id']}]\n\n")
                facts = [
                    f"E_F = {_fmt(summary.get('efermi'), 4)} eV",
                    "自旋极化" if summary.get("spin_polarized") else "非自旋",
                    f"元素 {'/'.join(summary.get('elements') or []) or '—'}",
                    f"轨道投影 {summary.get('series_count')} 条",
                ]
                ele_blocks.append("· " + " · ".join(facts) + "\n\n")
                if summary.get("default_curves"):
                    lo, hi = (summary.get("range") or [None, None])[:2]
                    text = (
                        f"图上默认画**总态密度 + 各元素 d 轨道**共 "
                        f"{len(summary['default_curves'])} 条"
                    )
                    if summary.get("band_centers"):
                        centers_text = "；".join(
                            "{name} {value:+.2f} eV".format(**center)
                            for center in summary["band_centers"]
                        )
                        text += (
                            f"（带中心按区间 {_fmt(lo, 1)} ~ {_fmt(hi, 1)} eV 积分，"
                            f"含未占据态、up/down 各自算）：{centers_text}"
                        )
                    ele_blocks.append(text + "。\n\n")
            # 功函数（v0.9.61）：数值 + 平面平均电位曲线
            for item in [x for x in with_diff if x.get("work_function_summary")]:
                summary = item["work_function_summary"]
                ele_blocks.append(f"\n#### {item['task_name']} · 功函数\n")
                ele_blocks.append(
                    f"平面平均静电势沿 {summary.get('axis')} 方向提取"
                    f"（对应 {summary.get('axis_cartesian')}），"
                    "**功函数 = 真空能级 − E_F**。\n\n"
                )
                if summary.get("chart"):
                    ele_blocks.append(
                        f"![{item['task_name']} 平面平均静电势]({summary['chart']})\n\n"
                    )
                    ele_blocks.append(f"@[work-function-chart:{item['task_id']}]\n\n")
                vacuum_source = (
                    "VASPKIT 汇总" if summary.get("vacuum_level_source") == "vaspkit"
                    else "本地平台估计"
                )
                ele_blocks.append(
                    f"真空能级 {_fmt(summary.get('vacuum_level'), 4)} eV"
                    f"（{vacuum_source}） · E_F {_fmt(summary.get('efermi'), 4)} eV"
                    f" · **功函数 {_fmt(summary.get('work_function'), 4)} eV**\n\n"
                )
                # ⚠ 警告不进报告（2026-10-15 用户："报告不出现警告和提示，报告是给客户看的"）：
                # 真空能级交叉校验 / 平台波动这类提示只在巡检详情面板与结构化数据里给，
                # 客户看的报告只呈现数值与出处（VASPKIT 汇总 / 本地平台估计）。
        # 仅重排现有模型分析块：标题、挂点、数据与模型内的分析顺序均保持兼容。
        electronic_text = "".join(ele_blocks)
        chunks = re.split(r"(?=\n#### )", electronic_text)
        grouped = [chunks[0]]
        remaining = chunks[1:]
        for item in with_diff:
            headings = tuple(
                f"\n#### {item['task_name']} · {kind}\n"
                for kind in ("差分电荷", "Bader 电荷", "态密度（PDOS）", "功函数")
            )
            selected = [chunk for chunk in remaining if chunk.startswith(headings)]
            grouped.extend(selected)
            remaining = [chunk for chunk in remaining if not chunk.startswith(headings)]
        blocks.append("".join(grouped + remaining))
    sections["science"] = "".join(blocks).strip() + "\n"

    issues = report["issues"]["items"]
    sections["issues"] = (
        "\n".join(
            f"- {issue['level_icon']} **{issue['task_name']}**：{issue['text']}"
            + (f" —— {issue['suggestion']}" if issue.get("suggestion") else "")
            for issue in issues
        )
        if issues
        else "本次巡检未发现需要关注的异常，项目状态正常。"
    ) + "\n"

    actions = report["actions"]["items"]
    sections["actions"] = (
        "\n".join(
            f"{index}. **[{action['priority']}]** {action['action']}"
            + (f"（{action['task_name']}）" if action.get("task_name") else "")
            + (f" —— {action['reason']}" if action.get("reason") else "")
            for index, action in enumerate(actions, start=1)
        )
        if actions
        else "暂无待办建议：保持当前推进节奏即可。"
    ) + "\n"

    appendix = report["appendix"]
    sections["appendix"] = "\n".join(
        [
            _md_table(
                ["任务", "类型", "状态"],
                [
                    [t["task_name"], t["task_type_label"], t["status_label"]]
                    for t in appendix["all_tasks"]
                ],
            ),
            f"生成参数：时间窗口 {appendix['generation_params']['window_days']} 天 · "
            f"结构展示上限 {appendix['generation_params']['max_structure_tasks']} 个任务 · "
            f"schema {appendix['generation_params']['schema_version']}",
            "",
            "数据时间戳：" + "；".join(
                f"{k}={v or '—'}" for k, v in appendix["data_timestamps"].items()
            ),
        ]
    ) + "\n"

    return [
        {"key": key, "title": title, "markdown": (sections.get(key) or "_（本章节无数据）_").strip() + "\n"}
        for key, title in REPORT_SECTIONS
    ]


def _anomaly_trend(project_name: str, days: int = 7) -> List[Dict[str, Any]]:
    """近 N 天异常任务数量趋势（按归档文件的修改时间归日，任务去重）。"""
    from checks_store import CHECKS_DIR

    today = datetime.now().date()
    buckets: Dict[str, set] = {
        (today - timedelta(days=i)).isoformat(): set() for i in range(days)
    }
    if not CHECKS_DIR.is_dir():
        return [{"date": d, "count": 0} for d in sorted(buckets)]
    files = sorted(CHECKS_DIR.glob("check_results_*.json"), key=lambda p: p.stat().st_mtime)
    for path in files:
        try:
            day = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        except OSError:
            continue
        if day not in buckets:
            continue
        try:
            entries = __import__("json").loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if str(entry.get("project_name")) != project_name:
                continue
            if (
                entry.get("status") in ("zombied", "unconverged")
                or entry.get("error_messages")
            ):
                buckets[day].add(str(entry.get("task_id")))
    return [{"date": d, "count": len(buckets[d])} for d in sorted(buckets)]


def _stats(facts: List[Dict[str, Any]], archived_count: int) -> Dict[str, Any]:
    """统计口径：分母为**未关闭（非 archived）任务**，已关闭任务单独计数。

    归档（关闭）代表任务已人工收尾，不应拉低完成率、也不参与风险判定。
    """
    active = [f for f in facts if f["status"] != "archived"]
    counter = Counter(f["status"] for f in active)
    total = len(active)
    completed = counter.get("completed", 0)
    # 全部任务已关闭 = 项目收尾完成；没有未关闭任务时不按 0% 呈现
    percent = (
        round(completed / total * 100, 1)
        if total
        else (100.0 if archived_count else 0.0)
    )
    return {
        "total": total,
        "completed": completed,
        "running": counter.get("running", 0),
        "queued": counter.get("queued", 0),
        "failed": counter.get("zombied", 0),
        "unconverged": counter.get("unconverged", 0),
        "pending": counter.get("pending", 0),
        "archived": archived_count,
        "completion_percent": percent,
    }


def _current_stage(facts: List[Dict[str, Any]], counter: Counter) -> str:
    running_types = {f["task_type"] for f in facts if f["status"] == "running"}
    if "ele" in running_types:
        return "电子结构计算"
    if "neb" in running_types:
        return "NEB 过渡态搜索"
    if "frac" in running_types:
        return "频率矫正计算"
    if "opt" in running_types:
        return "结构优化"
    if counter.get("queued"):
        return "排队等待调度"
    if counter.get("unconverged") or counter.get("zombied"):
        return "结果核查与续算"
    if facts and all(f["status"] in ("completed", "archived") for f in facts):
        return "已完成"
    return "准备阶段"


def _storage_gb(size: str) -> Optional[float]:
    """把 df -h 的 '514T' 之类转换为 GB。"""
    if not size:
        return None
    m = re.match(r"^([\d.]+)\s*([KMGTP]?)", str(size).strip(), re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1))
    unit = (m.group(2) or "").upper()
    factor = {"": 1 / 1024 / 1024 / 1024, "K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024, "P": 1024 * 1024}
    return round(value * factor.get(unit, 1), 1)


# ------------------------------------------------------------------ 主入口


def ai_generate_notes(
    calc_description: str,
    expected_results: str,
    task_result: Dict[str, Any],
    report: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """**预留接口**：将来接 LLM 生成"结果分析描述 / 论文写作参考"。

    输入：项目计算内容描述、预期结果、单个任务的计算结果与全局结构化数据；
    输出：`{"analysis_note": ..., "paper_note": ...}`。
    现在返回空串（前端"AI 生成"按钮置灰提示"即将支持"），接入时只改这个函数即可。
    """
    return {"analysis_note": "", "paper_note": ""}


#: 注解的「类型级」落点（用户 2026-10-13 口径）：markdown 标题 → 注解 key。
#: **只在「重点科学结果分析」章节内有注解**；四个类型各一条"总的"（电子结构目前是占位区块，
#: 只有类型级没有子项级 —— 子任务还没做完，按用户要求暂不提供）。
NOTE_TYPE_KEYS: Dict[str, str] = {
    "结构优化": "type_opt",
    "自由能路径": "type_free_energy",
    "NEB 过渡态": "type_neb",
    "电子结构": "type_ele",
}

#: 自由能路径的「组级」注解 key 前缀（每个路径一条）：`path:<group_id>`
NOTE_PATH_PREFIX = "path:"


def attach_report_notes(report: Dict[str, Any], report_id: str) -> Dict[str, Any]:
    """把 `data/reports/notes/<report_id>.json` 的注解贴到报告上（生成时 / 详情 / 导出前各调一次）。

    落点（用户 2026-10-13 口径，**只在「重点科学结果分析」章节内**）：

    | 落点 | key | 说明 |
    | --- | --- | --- |
    | 类型级（总的） | `type_opt` / `type_free_energy` / `type_neb` / `type_ele` | 每个类型一条 |
    | 结构优化子项 | `task_id` | 每个任务一条 |
    | NEB 组 | `task_id` | 每个 NEB 任务（= 一组）一条 |
    | 自由能路径组 | `path:<group_id>` | 每条路径一条；路径内各结构仍按各自 `task_id` |

    电子结构**只有类型级**（`type_ele`）—— 其子任务未完成，子项级暂不提供。
    函数幂等：只写 `notes` / `note_blocks`
    与各条目的 `analysis_note` / `paper_note`，不改其它字段。

    `note_blocks`（导出 HTML 用）：key = markdown 里 `#### 标题`（任务名 / 路径名），
    value = 该块要显示的注解条目（自由能路径块另外汇总组内已填写的结构级注解）。
    """
    try:
        from report_store import read_notes

        notes = read_notes(report_id)
    except Exception:  # noqa: BLE001 - 读注解失败不影响报告本体
        notes = {}
    report["notes"] = notes or {}
    science = report.get("science") or {}
    blocks: Dict[str, List[Dict[str, Any]]] = {}

    def _entry(note: Dict[str, Any], label: str = "") -> Dict[str, Any]:
        return {
            "label": label,
            "analysis_note": str((note or {}).get("analysis_note") or ""),
            "paper_note": str((note or {}).get("paper_note") or ""),
        }

    def _apply(target: Dict[str, Any], key: str) -> Dict[str, Any]:
        note = report["notes"].get(str(key or ""), {})
        target["analysis_note"] = str(note.get("analysis_note") or "")
        target["paper_note"] = str(note.get("paper_note") or "")
        return note

    # 结构优化 / NEB：每个子项（任务）一条
    for entry in (science.get("opt") or []) + (science.get("neb") or []):
        label = str(entry.get("task_name") or "")
        blocks.setdefault(label, []).append(
            _entry(_apply(entry, str(entry.get("task_id") or "")), "")
        )

    # 自由能路径：每个组一条（+ 组内各结构已填写的注解作为只读汇总）
    for path in science.get("free_energy") or []:
        entries: List[Dict[str, Any]] = []
        path_note = _apply(path, f"{NOTE_PATH_PREFIX}{path.get('group_id') or path.get('group_name')}")
        if path_note.get("analysis_note") or path_note.get("paper_note"):
            entries.append(_entry(path_note, ""))
        for structure in path.get("structures") or []:
            note = _apply(structure, str(structure.get("opt_task_id") or ""))
            if note.get("analysis_note") or note.get("paper_note"):
                entries.append(_entry(note, f"结构 {structure.get('structure_label')}"))
        if entries:
            blocks.setdefault(str(path.get("group_name") or ""), []).extend(entries)
    report["note_blocks"] = blocks
    return report


def build_report(
    project_ref: str,
    *,
    window_days: int = 7,
    report_id: Optional[str] = None,
    refresh_cluster: bool = False,
) -> Dict[str, Any]:
    """构建单个项目的报告。

    返回 {"report": 结构化对象, "charts": {文件名: SVG 文本}, "markdown": 全文}
    """
    db = load_db()
    project = _find_project(db, project_ref)
    if project is None:
        raise ValueError(f"项目不存在：{project_ref}")
    project_name = str(project.get("name") or "")
    project_id = str(project.get("project_id") or "")
    server = str(project.get("server") or "")
    collection_errors: List[str] = []

    # 附属任务（续算子 conN / 差分电荷分块）不进 facts：不单独成行、不计当量、不进统计
    tasks = [t for t in project.get("tasks", []) if not is_auxiliary_task(t)]
    archived_count = len([t for t in project.get("tasks", []) if t.get("status") == "archived"])
    merged = collect_results()
    submit_times = _submit_times()

    snapshot: Dict[str, Any] = {}
    try:
        snapshot = cluster_snapshot(server, refresh=refresh_cluster) if server else {}
    except Exception as e:  # noqa: BLE001 - 集群不可用不影响报告
        collection_errors.append(f"集群快照获取失败：{e}")
    cores = build_cores_usage(db, snapshot) if snapshot else {}
    health = build_cluster_health(snapshot) if snapshot else {}
    cores_by_job = {
        str(job.get("job_id")): int(job.get("cores") or 0)
        for job in (snapshot.get("jobs") or [])
        if job.get("status") == "RUN"
    }

    facts = _task_facts(project, tasks, merged, submit_times, cores_by_job)
    # 未关闭任务：统计口径 / 风险判定 / 进度树只看这些（已关闭任务只在任务详情与附录里列出）
    active_facts = [f for f in facts if f["status"] != "archived"]
    counter = Counter(f["status"] for f in active_facts)
    stats = _stats(facts, archived_count)
    now = now_iso()
    if not report_id:
        # 同一项目恒定使用一个报告 ID：重新生成即覆盖旧报告（报告历史 = 每项目一份最新）
        report_id = f"rpt_{project_id or project_name}"

    # ---------------- 图表
    charts: Dict[str, str] = {}
    opt_science: List[Dict[str, Any]] = []
    # 结构三视图弹窗（点击「结构 N」/「映像 N」打开）与要复制进报告的 PNG 清单
    dialogs: List[Dict[str, Any]] = []
    dialog_images: Dict[str, str] = {}
    # 只把**独立**结构优化任务（不含自由能路径中间体 / NEB 初末态优化）计入本节
    opt_facts = [f for f in facts if f["task_type"] == "opt" and _task_category(f) == "结构优化"]
    opt_total = len([f for f in opt_facts if f.get("force_history")])
    opt_skipped_unconverged = 0
    for fact in opt_facts:
        history = fact.get("force_history") or []
        if not history or len(opt_science) >= MAX_STRUCTURE_TASKS:
            continue
        # 用户口径（2026-10-07）：**未收敛的 opt 任务不输出详细内容**，不生成空壳
        converged = (
            bool(fact["converged"]) if fact.get("converged") is not None else fact["status"] in STATUS_DONE
        )
        if not (converged or fact["status"] == "archived"):
            opt_skipped_unconverged += 1
            continue
        points = [
            {
                "step": p.get("step"),
                "energy": p.get("energy"),
                "max_force": p.get("max_force"),
            }
            for p in history
        ]
        chart_refs: Dict[str, str] = {}
        curve_svg = energy_force_chart(
            points,
            title=f"{fact['task_name']} 能量与最大力",
            width=OPT_CURVE_W,
            height=OPT_CURVE_H,
        )
        # 最终结构三视图（导出用；前端另有 3Dmol 交互视图）
        poscar_cif = contcar_cif = None
        try:
            task_obj = next(
                (x for x in project.get("tasks", []) if str(x.get("task_id")) == fact["task_id"]),
                {},
            )
            poscar_cif = read_or_convert_cif(project, task_obj, "POSCAR")
            contcar_cif = read_or_convert_cif(project, task_obj, "CONTCAR")
        except Exception as e:  # noqa: BLE001
            collection_errors.append(f"{fact['task_name']} 结构 CIF 读取失败：{e}")
        # 三视图优先用 VESTA 渲染好的 PNG（images/），没有就走原来的 CIF 示意三视图
        dialog, dialog_pngs = _views_dialog(
            project_name,
            task_obj,
            f"dlg_{fact['task_id']}",
            f"{fact['task_name']} 结构三视图",
        )
        if dialog:
            dialogs.append(dialog)
            dialog_images.update(dialog_pngs)
        view_cif = contcar_cif or poscar_cif
        # 三视图统一用 VESTA 渲染的 PNG（images/）；**没有就不再退回旧的 CIF 示意三视图**
        # ——用户口径 2026-10-07："报告优先用 images 里的，没有就跳过"，
        # 否则同一份报告里有的任务是新三视图、有的是旧版示意（Ag24/Ag111 被问过）。
        # 曲线永远单独出一张。
        ename = f"{fact['task_id']}_energy_force.svg"
        charts[ename] = curve_svg
        chart_refs["energy_force"] = f"charts/{ename}"
        # 收敛历史弹窗（2026-10-15 用户："报告中能量、力曲线放到收敛历史中折叠，点击弹窗展示"）：
        # 曲线不再铺在正文里，正文只留一个「收敛历史」chip，点开在弹窗里看
        # （弹窗内容 = 同一张 energy_force 图：导出时内联 SVG，报告页里换成可交互 ECharts）。
        conv_dialog_id = f"dlg_conv_{fact['task_id']}"
        dialogs.append(
            {
                "id": conv_dialog_id,
                "title": f"{fact['task_name']} · 收敛历史（能量 / 最大力）",
                "chart": f"charts/{ename}",
                "note": (
                    f"共 {len(points)} 个离子步 · 能量（蓝，左轴）与最大力（橙，右轴）同图 · "
                    "红色虚线为力收敛阈值 0.020 eV/Å（EDIFFG）"
                ),
            }
        )
        opt_science.append(
            {
                "task_id": fact["task_id"],
                "task_name": fact["task_name"],
                "status": fact["status"],
                "status_label": fact["status_label"],
                "final_energy_ev": fact["last_energy"],
                "force_max_ev_per_a": fact["force_max"],
                "converged": converged,
                "ionic_steps": fact["steps"],
                "energy_force_series": points,
                "structure": {
                    "poscar_cif": poscar_cif,
                    "contcar_cif": contcar_cif,
                },
                "structure_dialog": dialog["id"] if dialog else None,
                "structure_views": dialog["rows"] if dialog else [],
                "charts": chart_refs,
                # 收敛历史弹窗 id（正文里那个 chip 指向它）
                "conv_dialog": conv_dialog_id,
            }
        )

    free_paths = _free_energy_paths(project, facts)
    for path in free_paths:
        # 每个中间体的三视图弹窗（点「结构 N」打开）——**与"有没有频率矫正"无关**：
        # 自由能表格本身总会打印，结构三视图也不该因为矫正项还没算就整块消失
        # （2026-10-12 用户：FS_Kaolin 的自由能没有结构图，就是被下面那个 continue 跳过了）
        for s in path["structures"]:
            opt_obj = next(
                (
                    x
                    for x in project.get("tasks", [])
                    if str(x.get("task_id")) == str(s.get("opt_task_id"))
                ),
                {},
            )
            dialog, pngs = _views_dialog(
                project_name,
                opt_obj,
                f"dlg_{s.get('opt_task_id') or s['structure_label']}",
                f"结构 {s['structure_label']} · {opt_obj.get('model_name') or ''}".strip(" ·"),
            )
            if dialog:
                dialogs.append(dialog)
                dialog_images.update(pngs)
                s["dialog"] = dialog["id"]
            # 自由能中间体的结构：报告里用 **3D 视图**（v0.9.73），CIF 本地转好带上
            # （三视图 PNG 仍生成，留着打印/PDF 兜底）
            try:
                s["cif"] = read_or_convert_cif(project, opt_obj, "CONTCAR") or read_or_convert_cif(
                    project, opt_obj, "POSCAR"
                )
            except Exception as exc:  # noqa: BLE001 - 报告不因 CIF 失败
                collection_errors.append(f"自由能结构 {s['structure_label']} CIF 读取失败：{exc}")
        # 台阶图要自由能数值（没有频率矫正就没有）→ 仍然只在有值时画
        if not any(s.get("free_energy_ev") is not None for s in path["structures"]):
            continue
        name = f"{path['group_id']}_step.svg"
        # 与巡检详情页的自由能路径看板同版式：统计卡 + 台阶图
        charts[name] = free_energy_panel(path, title=f"{path['group_name']} 自由能路径看板")
        path["chart"] = f"charts/{name}"

    neb_science = _neb_details(facts)
    for item in neb_science:
        if not item["images"]:
            continue
        # 每个映像的三视图弹窗（点「映像 N」打开）
        neb_obj = next(
            (
                x
                for x in project.get("tasks", [])
                if str(x.get("task_id")) == str(item["task_id"])
            ),
            {},
        )
        views_by_label = structure_images.neb_views(project_name, neb_obj) if neb_obj else {}
        for img in item["images"]:
            label_key = structure_images.image_label_key(img["label"])
            dialog, pngs = _neb_image_dialog(
                f"dlg_{item['task_id']}_{label_key}",
                f"映像 {img['label']} · {item['task_name']}",
                views_by_label.get(label_key) or {},
            )
            if dialog:
                dialogs.append(dialog)
                dialog_images.update(pngs)
                img["dialog"] = dialog["id"]
        name = f"{item['task_id']}_barrier.svg"
        # 与巡检详情页的 NEB 能垒看板同版式：统计卡 + 能垒曲线
        charts[name] = neb_panel(item, title=f"{item['task_name']} NEB 能垒看板")
        item["chart"] = f"charts/{name}"
        # 映像结构：**不再画 Python 投影矩阵**（旧的 a-b/b-c/a-c 示意），统一用 VESTA 三视图
        # ——点表格里的「映像 N」弹窗看该映像的 a/b/c（用户口径 2026-10-07）。
        if not views_by_label:
            # 报告是对外文件：只陈述事实，不写"还没出/自动渲染"这类内部提示
            item["note"] = "该 NEB 任务暂无映像三视图。"

    project_cores = next(
        (g["cores"] for g in (cores.get("byProject") or []) if g["project_name"] == project_name),
        0,
    )
    # 项目进度：按任务类型分块（块宽 = 当量占比）+ 当量加权主进度
    progress_segments, weighted_percent = _progress_segments(facts)
    plan = _workload_plan(facts)
    charts["progress.svg"] = segmented_progress_chart(
        progress_segments,
        main_percent=weighted_percent,
        main_detail=(
            f"当量加权主进度 · 任务 {stats['completed']}/{stats['total']} 已完成"
            + (f"，{stats['archived']} 个已关闭" if stats["archived"] else "")
        ),
        notes=[
            f"折算工作量 {plan['total_units']:.1f} 当量 ≈ {plan['core_hours_total']:,.0f} 核时"
            f"（1 当量 {plan['core_hours_per_weight']:.0f} 核时）· "
            f"已完成 {plan['core_hours_done']:,.0f} · 剩余 {plan['core_hours_remaining']:,.0f} 核时",
            f"有效算力 {plan['core_hours_per_day']:,.0f} 核时/天"
            f"（{plan['max_cores']:.0f} 核 × 24h × {plan['utilization'] * 100:.0f}%）"
            + (
                f" → 按当量估算还需 {plan['eta_days']:.1f} 天，预计 {plan['eta_at']} 完成"
                if plan["eta_days"] is not None and plan["core_hours_remaining"] > 0
                else " → 剩余工作量为 0，项目已收尾"
            ),
        ],
        title="项目进度",
    )
    charts["cores_donut.svg"] = donut_chart(
        cores.get("usedCores"), cores.get("totalCores"), title="集群核数占用"
    )
    storage = health.get("storage") or {}
    charts["storage_bar.svg"] = progress_bar(
        storage.get("usedPercent"),
        title="存储使用",
        detail=f"已用 {storage.get('used', '—')} / {storage.get('size', '—')}"
        if storage
        else "",
    )

    # ---------------- 风险与行动
    deadline_days = _project_days_left(project)
    time_progress = _time_progress_percent(project)
    project_facts = {
        "project_name": project_name,
        "project_id": project_id,
        # 已关闭（或全部任务已归档）的项目不再判定进度/资源/队列类风险
        "closed": bool(project.get("closed")) or stats["total"] == 0,
        "progress_percent": weighted_percent,
        "task_completion_percent": stats["completion_percent"],
        "time_progress_percent": time_progress,
        "progress_gap": (
            round((time_progress or 0) - weighted_percent, 1)
            if time_progress is not None
            else None
        ),
        "overdue": bool(deadline_days is not None and deadline_days < 0 and weighted_percent < 100),
        "overdue_days": abs(deadline_days) if deadline_days is not None and deadline_days < 0 else 0,
        "days_left": deadline_days,
        "deadline": str(project.get("deadline") or ""),
        "storage_used_percent": storage.get("usedPercent"),
        "storage_available": storage.get("available"),
        "cores_used": cores.get("usedCores"),
        "cores_total": cores.get("totalCores"),
        "cores_used_percent": cores.get("usedPercent"),
        "max_queue_pending": max(
            (q.get("pending") or 0 for q in (health.get("queues") or [])), default=0
        ),
        "busiest_queue": max(
            (health.get("queues") or []), key=lambda q: q.get("pending") or 0, default={}
        ).get("queue"),
        "running_tasks": stats["running"],
        "queued_tasks": stats["queued"],
    }
    risks = evaluate_rules(
        active_facts,
        project_facts,
        rules=load_rules(),
        detected_at=now,
    )
    severity_counter = Counter(r["severity"] for r in risks)
    project_status = (
        "critical"
        if severity_counter.get("high")
        else "warning"
        if risks
        else "normal"
    )
    status_reasons = {
        "critical": f"存在 {severity_counter.get('high', 0)} 条高风险"
        + (
            f"（首要：{risks[0]['description'][:40]}）"
            if risks
            else ""
        ),
        "warning": f"存在 {severity_counter.get('medium', 0)} 条中风险 / "
        f"{severity_counter.get('low', 0)} 条低风险",
        "normal": "未触发风险规则，项目运行正常",
    }
    summary_text = (
        f"项目进度 {weighted_percent}%（当量加权，含已归档成果）；"
        f"未归档任务 {stats['total']} 个，已完成 {stats['completed']}"
        f"（任务完成率 {stats['completion_percent']}%），运行中 {stats['running']}、"
        f"排队 {stats['queued']}、待处理 {stats['pending']}；"
        f"异常 {stats['failed'] + stats['unconverged']} 个"
        f"（未收敛 {stats['unconverged']}、异常中断 {stats['failed']}）。"
        f"核数占用 {cores.get('usedCores', '—')} / {cores.get('totalCores', '—')}"
        f"（{_fmt(cores.get('usedPercent'), 1)}%），存储使用 "
        f"{_fmt(storage.get('usedPercent'), 1)}%。"
    )

    # ---------------- 巡检汇总
    rows = to_frontend_rows(db, merged)
    project_rows = [r for r in rows if r.get("project_name") == project_name]
    anomalies = [
        {
            "task_id": str(r.get("task_id")),
            "task_name": str(r.get("task_name", "")).split(" · ")[0],
            "anomaly_type": (
                "convergence"
                if r.get("task_category") == "结构优化"
                else "resource"
                if r.get("category") == "resource"
                else "queue"
                if r.get("category") == "queue"
                else "file"
            ),
            "description": str(r.get("message") or r.get("detail") or ""),
            "detected_at": str(r.get("check_time") or ""),
            "current_status": str(r.get("status")),
        }
        for r in project_rows
        if r.get("status") in ("error", "warning")
    ]
    category_counts = {key: 0 for key in ANOMALY_CATEGORIES}
    for item in anomalies:
        category_counts[item["anomaly_type"]] = category_counts.get(item["anomaly_type"], 0) + 1
    runs = list_runs()
    last_run = runs[0] if runs else {}

    # ---------------- 行动清单（由风险生成，最多 §10 约束条数）
    action_items: List[Dict[str, Any]] = []
    for risk in risks:
        task = (risk["affected_tasks"] or [{}])[0]
        action_items.append(
            {
                "action_id": f"AC{len(action_items) + 1:03d}",
                "priority": priority_for(risk["severity"]),
                "task_id": task.get("task_id") or None,
                "task_name": task.get("task_name") or risk["target"],
                "action": risk["advice"],
                "reason": risk["description"],
                "link": f"/jobs?task={task['task_id']}" if task.get("task_id") else "/report",
                "estimated_hours": {"high": 4.0, "medium": 2.0, "low": 1.0}.get(risk["severity"], 1.0),
                "risk_id": risk["risk_id"],
            }
        )
    order = {"P0": 0, "P1": 1, "P2": 2}
    action_items.sort(key=lambda a: (order.get(a["priority"], 9), a["action_id"]))
    for index, item in enumerate(action_items, start=1):
        item["action_id"] = f"AC{index:03d}"

    key_findings: List[str] = [
        f"项目进度 {weighted_percent}%（当量加权）；未归档任务完成率 "
        f"{stats['completion_percent']}%（{stats['completed']}/{stats['total']}），当前阶段："
        f"{_current_stage(facts, counter)}"
    ]
    if stats["unconverged"] or stats["failed"]:
        key_findings.append(
            f"存在 {stats['unconverged']} 个未收敛、{stats['failed']} 个异常中断任务，需要续算或重新提交"
        )
    if severity_counter.get("high"):
        key_findings.append(f"触发 {severity_counter['high']} 条高风险规则，详见 risks 字段")
    if storage.get("usedPercent") is not None:
        key_findings.append(
            f"集群存储使用 {_fmt(storage.get('usedPercent'), 1)}%，核数占用 "
            f"{cores.get('usedCores', '—')}/{cores.get('totalCores', '—')}"
        )
    if anomalies:
        key_findings.append(f"最近巡检发现 {len(anomalies)} 项异常/警告")
    while len(key_findings) < 3:
        key_findings.append("暂无明显风险项，继续按计划推进即可")

    stage = _current_stage(active_facts, counter)
    task_summary_text = _one_line_summary(active_facts, stats, stage)
    # 异常与关注项：模板生成（不走大模型），只保留最关键的几条
    issue_items: List[Dict[str, Any]] = []
    for risk in risks:
        if risk["severity"] == "low":
            continue
        task = (risk["affected_tasks"] or [{}])[0]
        issue_items.append(
            {
                "level": risk["severity"],
                "level_icon": {"high": "🔴", "medium": "🟠"}.get(risk["severity"], "🟡"),
                "task_id": task.get("task_id"),
                "task_name": task.get("task_name") or risk["target"],
                "text": risk["description"],
                "suggestion": risk["advice"],
                "rule_id": risk["rule_id"],
            }
        )
    for anomaly in anomalies[:3]:
        if any(i["task_id"] == anomaly["task_id"] for i in issue_items):
            continue
        issue_items.append(
            {
                "level": "medium" if anomaly["current_status"] == "warning" else "high",
                "level_icon": "🟠" if anomaly["current_status"] == "warning" else "🔴",
                "task_id": anomaly["task_id"],
                "task_name": anomaly["task_name"],
                "text": anomaly["description"],
                "suggestion": "查看巡检详情并处理",
                "rule_id": "inspection",
            }
        )
    # 低精度收敛：按 INCAR 的 EDIFFG 判定收敛，但三项精度要求没达标
    for fact in [f for f in active_facts if (f.get("precision") or {}).get("ok") is False][:3]:
        if any(i["task_id"] == fact["task_id"] for i in issue_items):
            continue
        precision = fact.get("precision") or {}
        issue_items.append(
            {
                "level": "medium",
                "level_icon": "🟡",
                "task_id": fact["task_id"],
                "task_name": fact["task_name"],
                "text": "低精度收敛：" + "；".join(str(x) for x in precision.get("issues") or []),
                "suggestion": "结果可用但精度偏低；如需更可靠的数据，建议收紧 INCAR（EDIFFG / EDIFF）或加密 k 网格后重算",
                "rule_id": "precision",
            }
        )
    issue_items = issue_items[:6]

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "basic_info": {
            "project_name": project_name,
            "project_id": project_id,
            # 项目元数据（2026-10-12）：交付日期沿用 deadline；两个报告辅助字段来自项目管理
            "deadline": str(project.get("deadline") or ""),
            "calc_description": str(project.get("calc_description") or ""),
            "expected_results": str(project.get("expected_results") or ""),
            "generated_at": now,
            "time_window_label": f"最近 {window_days} 天",
            "project_status": project_status,
            "project_status_label": {"normal": "正常", "warning": "警告", "critical": "异常"}[
                project_status
            ],
            "status_reason": status_reasons[project_status],
            "progress_percent": stats["completion_percent"],
            "weighted_progress_percent": weighted_percent,
            "progress_segments": progress_segments,
            "workload": plan,
            "task_summary": task_summary_text,
            "current_stage": stage,
            "progress_chart": "charts/progress.svg",
        },
        "report_type": "project_status",
        "metadata": {
            "report_id": report_id,
            "project_id": project_id,
            "project_name": project_name,
            "generated_at": now,
            "time_window": {
                "start": (datetime.now() - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%S"),
                "end": now,
                "label": f"最近 {window_days} 天",
            },
            "data_sources": [
                "projects.json（任务元数据）",
                "data/checks（巡检归档）",
                f"集群快照（{snapshot.get('source', 'unavailable')}）",
                "data/audit_submit.log（提交记录）",
                "本地项目镜像目录（结构/OSZICAR）",
            ],
            "server": server,
            "units": {
                "energy": "eV",
                "force": "eV/A",
                "time": "hour",
                "capacity": "GB",
                "cores": "int",
            },
            "chart_directory": "charts/",
        },
        "executive_summary": {
            "project_status": project_status,
            "project_status_label": {
                "normal": "正常",
                "warning": "警告",
                "critical": "异常",
            }[project_status],
            "status_reason": status_reasons[project_status],
            "task_stats": stats,
            "resources": {
                "cores_used": cores.get("usedCores"),
                "cores_total": cores.get("totalCores"),
                "cores_used_percent": cores.get("usedPercent"),
                "storage_used_percent": storage.get("usedPercent"),
                "storage_available": storage.get("available"),
            },
            "summary_text": summary_text,
        },
        "progress": {
            "progress_percent": stats["completion_percent"],
            "weighted_progress_percent": weighted_percent,
            "progress_segments": progress_segments,
            "workload": plan,
            "time_progress_percent": time_progress,
            "days_left": deadline_days,
            "deadline": str(project.get("deadline") or ""),
            "current_stage": _current_stage(active_facts, counter),
            # 预估完成时间：剩余当量 × 1728 核时（24 核 × 3 天）÷（200 核 × 24h × 70%）
            "estimated_completion": plan["eta_at"],
            "eta_days": plan["eta_days"],
            "stage_breakdown": [
                {
                    "task_type": task_type,
                    "task_type_label": TASK_TYPE_LABELS[task_type],
                    "total": len([f for f in active_facts if f["task_type"] == task_type]),
                    "completed": len(
                        [f for f in active_facts if f["task_type"] == task_type and f["status"] == "completed"]
                    ),
                    "running": len(
                        [f for f in facts if f["task_type"] == task_type and f["status"] == "running"]
                    ),
                    "anomalies": len(
                        [
                            f
                            for f in facts
                            if f["task_type"] == task_type
                            and f["status"] in ("zombied", "unconverged")
                        ]
                    ),
                }
                for task_type in TASK_TYPES
            ],
            "task_tree": [
                {
                    "task_type": task_type,
                    "task_type_label": TASK_TYPE_LABELS[task_type],
                    "tasks": [
                        {
                            "task_id": f["task_id"],
                            "task_name": f["task_name"],
                            "status": f["status"],
                            "status_label": f["status_label"],
                        }
                        for f in facts
                        if f["task_type"] == task_type
                    ],
                }
                for task_type in TASK_TYPES
            ],
        },
        "tasks": {
            "groups": [
                {
                    "task_type": task_type,
                    "task_type_label": TASK_TYPE_LABELS[task_type],
                    "total": len([f for f in active_facts if f["task_type"] == task_type]),
                    "status_counts": dict(
                        Counter(f["status"] for f in facts if f["task_type"] == task_type)
                    ),
                    "tasks": [
                        _task_detail_row(f) for f in facts if f["task_type"] == task_type
                    ],
                }
                for task_type in TASK_TYPES
                if any(f["task_type"] == task_type for f in facts)
            ],
            "free_energy_paths": free_paths,
            "neb": neb_science,
        },
        "science": {
            "opt": opt_science,
            "opt_total": opt_total,
            # 未收敛（且未归档）的 opt 任务按用户口径不展开（2026-10-07）
            "opt_skipped_unconverged": opt_skipped_unconverged,
            "free_energy": free_paths,
            "neb": neb_science,
            "ele": {
                "note": (
                    "电子结构分析：差分电荷（结果 + VESTA 三视图弹窗）、Bader 电荷"
                    "（ACF.dat + 逐原子净电荷统计）、PDOS（可交互图 + 带中心）、"
                    "功函数（真空能级 − E_F）均已接入报告；COHP 待接入"
                ),
                "tasks": _ele_details(project, facts, merged),
            },
            "frac": _frac_details(project, facts),
            "parsing_notes": [
                "自由能 ZPE 与频率列表解析待接入（字段已占位）",
                "电子结构 PDOS/Bader 结果文件列表待接入",
            ],
        },
        "inspection": {
            "last_inspection_at": last_run.get("checked_at"),
            "last_inspection_inspected": last_run.get("inspected"),
            "covered_tasks": len([r for r in project_rows if r.get("has_inspection")]),
            "anomalies": anomalies,
            "category_counts": category_counts,
            "trend_7d": _anomaly_trend(project_name, window_days),
        },
        "resources": {
            "cores": {
                "used": cores.get("usedCores"),
                "total": cores.get("totalCores"),
                "available": cores.get("remainingCores"),
                "used_percent": cores.get("usedPercent"),
                "project_used": project_cores,
                "by_project": cores.get("byProject") or [],
                "running_jobs": cores.get("runningJobs"),
            },
            "storage": {
                "filesystem": storage.get("filesystem"),
                "mounted_on": storage.get("mountedOn"),
                "used_gb": _storage_gb(storage.get("used", "")),
                "total_gb": _storage_gb(storage.get("size", "")),
                "available_gb": _storage_gb(storage.get("available", "")),
                "used_percent": storage.get("usedPercent"),
                "available_percent": (
                    round(100 - float(storage["usedPercent"]), 1)
                    if storage.get("usedPercent") is not None
                    else None
                ),
            },
            "nodes": {
                "total": (health.get("nodes") or {}).get("total"),
                "ok": (health.get("nodes") or {}).get("ok"),
                "full": (health.get("nodes") or {}).get("full"),
                "down": (health.get("nodes") or {}).get("down"),
            },
            "queues": health.get("queues") or [],
            "charts": {
                "cores": "charts/cores_donut.svg",
                "storage": "charts/storage_bar.svg",
            },
        },
        "risks": {
            "items": risks,
            "summary": {
                "high": severity_counter.get("high", 0),
                "medium": severity_counter.get("medium", 0),
                "low": severity_counter.get("low", 0),
                "total": len(risks),
            },
            "rules": rules_meta(),
        },
        "issues": {
            "items": issue_items,
            "summary": {
                "total": len(issue_items),
                "high": len([i for i in issue_items if i["level"] == "high"]),
                "medium": len([i for i in issue_items if i["level"] == "medium"]),
            },
        },
        "actions": {"items": action_items[:5]},
        "llm_context": {
            "purpose": "供大模型进行项目风险分析、优先级排序与行动规划；数值以字段为准，图表仅作可视化",
            "key_findings": key_findings[:5],
            "open_questions": [
                "当前未收敛任务是否应继续续算，还是需要调整 INCAR 收敛参数？",
                "已逾期的交付节点是否需要重新协商截止日期？",
                "频率矫正缺失的中间体是否影响自由能路径结论？",
            ],
            "data_references": [
                "executive_summary.task_stats",
                "tasks.groups",
                "science",
                "inspection.anomalies",
                "risks.items",
                "actions.items",
            ],
            "constraints": {
                "max_suggestions": 5,
                "language": "zh-CN",
                "output_format": "json",
            },
        },
        "appendix": {
            "all_tasks": [_task_detail_row(f) for f in facts],
            "generation_params": {
                "window_days": window_days,
                "max_structure_tasks": MAX_STRUCTURE_TASKS,
                "schema_version": SCHEMA_VERSION,
                "generated_at": now,
            },
            "data_timestamps": {
                "projects_json": str(project.get("updated_at") or ""),
                "last_inspection": last_run.get("checked_at"),
                "cluster_snapshot": snapshot.get("queriedAt"),
                "audit_log_entries": len(submit_times),
            },
            "collection_errors": collection_errors,
            "charts": [{"name": f"charts/{name}", "bytes": len(svg)} for name, svg in charts.items()],
            # 结构三视图弹窗（<dialog>）+ 需要复制进报告目录的 PNG 清单
        },
    }
    # 结构三视图弹窗（<dialog>）与内联 PNG 清单：放在报告根节点，导出 HTML 时用
    # 差分电荷三视图（v0.9.47）：算好了就在「电子结构」章节给一个 a/b/c 弹窗，
    # 图片复用同一个 images/ 内联通道（口径与结构/映像三视图完全一致）
    for item in ((report.get("science") or {}).get("ele") or {}).get("tasks") or []:
        ele_obj = next(
            (
                x
                for x in project.get("tasks", [])
                if str(x.get("task_id")) == str(item.get("task_id"))
            ),
            None,
        )
        # Bader（v0.9.54）：把逐原子净电荷/统计一次性算好挂到 item 上，供章节渲染。
        # 纯本地读文件（ACF.dat + meta 里的 ZVAL + 本地 POSCAR），不连远端。
        bader_record = item.get("bader") or {}
        if bader_record.get("ok"):
            if ele_obj is not None:
                try:
                    parsed = bader.load_data(project_name, ele_obj)
                    item["bader_summary"] = {
                        "n_atoms": parsed["n_atoms"],
                        "total_charge": parsed["total_charge"],
                        "n_electrons": parsed["n_electrons"],
                        "vacuum_charge": parsed["vacuum_charge"],
                        "net_charge_available": parsed.get("net_charge_available"),
                        "net_charge_reason": parsed.get("net_charge_reason"),
                        "stats": parsed.get("stats"),
                        "local_path": parsed.get("source"),
                        "elapsed_seconds": bader_record.get("elapsed_seconds"),
                        "top": sorted(
                            (
                                {
                                    "index": atom["index"],
                                    "element": atom.get("element"),
                                    "charge": atom["charge"],
                                    "zval": atom.get("zval"),
                                    "net_charge": atom.get("net_charge"),
                                }
                                for atom in parsed["atoms"]
                                if atom.get("net_charge") is not None
                            ),
                            key=lambda a: abs(a["net_charge"]),
                            reverse=True,
                        )[:10],
                        # 完整表（v0.9.61）：报告正文里默认折叠（原生 <details>），
                        # 报告页 / 导出都渲染成"滑动折叠"的报表，不把 100+ 行铺在正文里
                        "atoms": [
                            {
                                "index": atom["index"],
                                "element": atom.get("element"),
                                "charge": atom["charge"],
                                "zval": atom.get("zval"),
                                "net_charge": atom.get("net_charge"),
                            }
                            for atom in parsed["atoms"]
                        ],
                    }
                except Exception as exc:  # noqa: BLE001 - 报告不因 Bader 失败
                    collection_errors.append(f"{item.get('task_name')} Bader 结果读取失败：{exc}")
                # Bader 的 3D 结构（v0.9.72）：报告里要「3D 结构窗口 + 表格」并排，
                # 结构用该任务的 CONTCAR（没有就 POSCAR）转 CIF —— 与结构优化同一套转换，
                # 本地读、失败就退化成只有表格。
                try:
                    summary = item.get("bader_summary") or {}
                    if summary and not summary.get("cif"):
                        # 优先用**分析时冻结的结构 CIF**（<任务>/bader/structure.cif）：
                        # 与 ACF.dat 同一次分析；本地 files/CONTCAR 之后可能被新运行覆盖（v0.9.75）
                        cif_text = bader.report_cif(project_name, ele_obj) or read_or_convert_cif(
                            project, ele_obj, "CONTCAR"
                        ) or read_or_convert_cif(project, ele_obj, "POSCAR")
                        summary["cif"] = cif_text
                        summary["cif_source"] = (
                            "frozen" if bader.report_cif(project_name, ele_obj) else "mirror"
                        )
                        item["bader_summary"] = summary
                except Exception as exc:  # noqa: BLE001 - 报告不因 CIF 失败
                    collection_errors.append(f"{item.get('task_name')} Bader 结构 CIF 读取失败：{exc}")

        # PDOS / 功函数（v0.9.61）：本地有结果就出摘要 + 静态图，交互版由报告页与导出注入。
        # **必须放在下面 charge_diff 的 `continue` 之前** —— 只有 PDOS/功函数、
        # 没有差分电荷的 ele 任务也要能进报告。
        if ele_obj is not None:
            pdos_record = _pdos_report_data(project_name, ele_obj, charts, collection_errors)
            if pdos_record:
                item["pdos_summary"] = pdos_record
            wf_record = _work_function_report_data(project_name, ele_obj, charts, collection_errors)
            if wf_record:
                item["work_function_summary"] = wf_record

        record = item.get("charge_diff") or {}
        if not record.get("ok"):
            continue
        ele_obj = next(
            (
                x
                for x in project.get("tasks", [])
                if str(x.get("task_id")) == str(item.get("task_id"))
            ),
            {},
        )
        views = {
            axis: str(path)
            for axis, path in charge_diff.local_images(project_name, ele_obj).items()
        }
        dialog, pngs = _charge_diff_dialog(
            f"dlg_chgdiff_{item.get('task_id')}",
            f"{item.get('task_name')} 差分电荷三视图",
            views,
        )
        if dialog:
            dialogs.append(dialog)
            dialog_images.update(pngs)
            item["charge_diff_dialog"] = dialog["id"]

    report["dialogs"] = dialogs
    report["images"] = dialog_images

    sections = _sections_markdown(report, charts)
    report["markdown_sections"] = sections
    # 报告注解（结果分析 / 论文参考）：统一入口见 attach_report_notes（生成时 / 详情 / 导出前都调）
    attach_report_notes(report, report_id)
    # 规范化 AI 视图（2026-10-12）：只加字段，既有结构不动；规则见 report_schema
    try:
        from ai_view import build_ai_view

        report["ai_view"] = build_ai_view(report)
    except Exception as e:  # noqa: BLE001 - AI 视图失败不影响报告本体
        report["ai_view"] = {"error": f"生成 AI 视图失败：{e}"}
    report["markdown_meta"] = {
        "sections": [{"key": s["key"], "title": s["title"]} for s in sections],
        "chart_paths": [f"charts/{name}" for name in charts],
    }
    problems = validate_report(report)
    if problems:
        report["appendix"]["validation_problems"] = problems
    markdown = "\n".join(
        [f"# {project_name} · 项目报告", f"> 报告 ID：`{report_id}` · 生成时间：{now} · schema {SCHEMA_VERSION}", ""]
        + [f"## {s['title']}\n\n{s['markdown']}" for s in sections]
    )
    return {"report": report, "charts": charts, "markdown": markdown}
