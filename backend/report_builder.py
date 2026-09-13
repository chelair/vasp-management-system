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
from config import DATA_DIR, load_servers, load_task_registry
from dashboard import build_cluster_health, build_cores_usage, cluster_snapshot
from dates import now_iso
from report_charts import (
    donut_chart,
    energy_force_chart,
    progress_bar,
    structure_matrix,
    structure_views,
    task_panel,
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
from task_paths import is_continuation_task, task_dir

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
}
SUBTYPE_LABELS = {
    "pdos": "PDOS",
    "bader": "Bader 分析",
    "diff_charge": "差分电荷",
    "work_function": "功函数",
}
ANOMALY_CATEGORIES = ("convergence", "resource", "file", "ssh", "queue")

MAX_STRUCTURE_TASKS = 6  # 单项目正文最多展示多少个结构优化任务（其余只进结构化数据），控制篇幅

# 任务类别（与巡检列表 / 前端任务树同口径）
CATEGORY_ORDER = ("结构优化", "自由能路径", "NEB 过渡态", "电子结构")
STATUS_DONE = ("completed", "archived")
DEFAULT_WORKLOAD_WEIGHT = 1.0


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
    try:
        registry = load_task_registry()
    except Exception:  # noqa: BLE001 - 配置缺失不阻塞报告
        registry = {}
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


def _ele_details(facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """电子结构任务：子类型 / 分析状态 / 结果文件（§3.5）。"""
    items = []
    for fact in facts:
        if fact["task_type"] != "ele":
            continue
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
    status_icon = {"normal": "🟢", "warning": "🟠", "critical": "🔴"}[info["project_status"]]
    sections["basic_info"] = "\n".join(
        [
            f"- **项目**：{info['project_name']}",
            f"- **报告生成时间**：{info['generated_at']}",
            f"- **整体状态**：{status_icon} **{info['project_status_label']}** —— {info['status_reason']}",
            f"- **项目进度**：**{info.get('weighted_progress_percent', info['progress_percent'])}%**"
            f"（按任务当量加权；{summary}）",
            f"- **时间窗口**：{info['time_window_label']}",
            "",
            f"![项目进度](charts/progress.svg)",
        ]
    ).strip() + "\n"

    science = report["science"]
    blocks = []
    opt_items = science.get("opt") or []
    if opt_items:
        blocks.append("### 结构优化\n")
        blocks.append(
            f"共 {science.get('opt_total') or len(opt_items)} 个结构优化任务有收敛数据，"
            f"下列展示其中 {len(opt_items)} 个，其余仅保留在报告数据中。每条包含结构三视图与能量/力曲线。"
            "（自由能路径的中间体与 NEB 的初/末态优化不在此列，见各自章节。）\n"
        )
        entries: List[str] = []
        for item in opt_items:
            converge = "✅ 已收敛" if item["converged"] else "⚠️ 未收敛"
            lines = [
                f"**{item['task_name']}** · {converge} · 最终能量 "
                f"**{_fmt(item['final_energy_ev'])} eV** · "
                f"最终最大力 **{_fmt(item['force_max_ev_per_a'])} eV/Å** · "
                f"离子步 {_fmt(item['ionic_steps'], 0)}"
            ]
            panel = item["charts"].get("panel") or item["charts"].get("energy_force")
            if panel:
                lines.append(f"![{item['task_name']} 结构三视图与能量/力曲线]({panel})")
            entries.append("\n\n".join(lines))
        # 任务之间用分隔线隔开，避免上下两个任务的面板图糊成一片
        blocks.append("\n\n---\n\n".join(entries) + "\n")
    paths = science.get("free_energy") or []
    if paths:
        blocks.append("### 自由能路径\n")
        entries = []
        for path in paths:
            lines = []
            if path.get("chart"):
                lines.append(f"![{path['group_name']} 自由能路径看板]({path['chart']})")
            structures = path["structures"]
            with_energy = [s for s in structures if s.get("free_energy_ev") is not None]
            ref = float(with_energy[0]["free_energy_ev"]) if with_energy else None
            lines.append(
                _md_table(
                    ["中间体", "DFT 能量 (eV)", "矫正项 (eV)", "自由能 (eV)", "相对 ΔE (eV)", "状态"],
                    [
                        [
                            f"结构 {s['structure_label']}",
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
                        for s in structures
                    ],
                )
            )
            entries.append("\n\n".join(lines))
        blocks.append("\n\n---\n\n".join(entries) + "\n")
    nebs = science.get("neb") or []
    if nebs:
        blocks.append("### NEB 过渡态\n")
        entries = []
        for item in nebs:
            lines = []
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
                                f"映像 {img['label']}",
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
            if item.get("matrix_chart"):
                lines.append(f"![{item['task_name']} 映像结构对比]({item['matrix_chart']})")
            entries.append("\n\n".join(lines))
        blocks.append("\n\n---\n\n".join(entries) + "\n")
    if not blocks:
        blocks.append("_本项目暂无可展示的科学结果（需任务产出 OUTCAR/CONTCAR 后自动生成）_\n")
    else:
        ele_note = science.get("ele") or {}
        blocks.append(
            "### 电子结构\n\n"
            + (
                f"待接入：{ele_note.get('note', '电子结构分析（PDOS / Bader / 功函数）尚未接入报告')}\n"
            )
        )
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


def _estimated_completion(project: Dict[str, Any], facts: List[Dict[str, Any]]) -> Optional[str]:
    """基于已完成任务的平均耗时估算剩余任务完成时间（数据不足时返回 None）。"""
    durations: List[float] = []
    for task in project.get("tasks", []):
        if task.get("status") != "completed":
            continue
        created = _parse_time(task.get("created_at"))
        checked = _parse_time(task.get("last_check_time"))
        if created and checked and checked > created:
            durations.append((checked - created).total_seconds() / 3600)
    remaining = len([f for f in facts if f["status"] not in ("completed", "archived")])
    if not durations or remaining == 0:
        return None
    avg_hours = sum(durations) / len(durations)
    finish = datetime.now() + timedelta(hours=avg_hours * remaining / 3)
    return finish.strftime("%Y-%m-%dT%H:%M:%S")


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

    tasks = [t for t in project.get("tasks", []) if not is_continuation_task(t)]
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
    # 只把**独立**结构优化任务（不含自由能路径中间体 / NEB 初末态优化）计入本节
    opt_facts = [f for f in facts if f["task_type"] == "opt" and _task_category(f) == "结构优化"]
    opt_total = len([f for f in opt_facts if f.get("force_history")])
    for fact in opt_facts:
        history = fact.get("force_history") or []
        if not history or len(opt_science) >= MAX_STRUCTURE_TASKS:
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
        curve_svg = energy_force_chart(points, title=f"{fact['task_name']} 能量与最大力")
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
        view_cif = contcar_cif or poscar_cif
        if view_cif:
            vname = f"{fact['task_id']}_views.svg"
            views_svg = structure_views(
                view_cif, title="", labels=["a-b 视图", "b-c 视图", "a-c 视图"]
            )
            charts[vname] = views_svg
            chart_refs["views"] = f"charts/{vname}"
            # 三视图 + 曲线横向拼成一张面板图（前端与导出所见即所得）
            pname = f"{fact['task_id']}_panel.svg"
            charts[pname] = task_panel(views_svg, curve_svg)
            chart_refs["panel"] = f"charts/{pname}"
        else:
            ename = f"{fact['task_id']}_energy_force.svg"
            charts[ename] = curve_svg
            chart_refs["energy_force"] = f"charts/{ename}"
        opt_science.append(
            {
                "task_id": fact["task_id"],
                "task_name": fact["task_name"],
                "status": fact["status"],
                "status_label": fact["status_label"],
                "final_energy_ev": fact["last_energy"],
                "force_max_ev_per_a": fact["force_max"],
                "converged": bool(fact["converged"])
                if fact["converged"] is not None
                else fact["status"] in STATUS_DONE,
                "ionic_steps": fact["steps"],
                "energy_force_series": points,
                "structure": {
                    "poscar_cif": poscar_cif,
                    "contcar_cif": contcar_cif,
                },
                "charts": chart_refs,
            }
        )

    free_paths = _free_energy_paths(project, facts)
    for path in free_paths:
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
        name = f"{item['task_id']}_barrier.svg"
        # 与巡检详情页的 NEB 能垒看板同版式：统计卡 + 能垒曲线
        charts[name] = neb_panel(item, title=f"{item['task_name']} NEB 能垒看板")
        item["chart"] = f"charts/{name}"
        # 映像结构对比矩阵（行 = a-b / b-c / a-c 视图，列 = 映像 IS → FS）
        try:
            task_obj = next(
                (x for x in project.get("tasks", []) if str(x.get("task_id")) == item["task_id"]),
                {},
            )
            image_cifs = read_neb_image_cifs(project, task_obj)
            if len(image_cifs) >= 2:
                matrix_items = [
                    {"label": label, "cif": cif} for label, cif in image_cifs.items()
                ]
                item["images_with_structure"] = [
                    {"label": i["label"], "cif": image_cifs.get(i["label"])} for i in item["images"]
                ]
                mname = f"{item['task_id']}_images.svg"
                charts[mname] = structure_matrix(
                    matrix_items, title=f"{item['task_name']} 映像结构对比"
                )
                item["matrix_chart"] = f"charts/{mname}"
            else:
                item["note"] = "尚未同步映像结构（巡检推进到 25 离子步桶后自动抓取）"
        except Exception as e:  # noqa: BLE001
            collection_errors.append(f"{item['task_name']} 映像结构读取失败：{e}")

    project_cores = next(
        (g["cores"] for g in (cores.get("byProject") or []) if g["project_name"] == project_name),
        0,
    )
    # 项目进度：按任务类型分块（块宽 = 当量占比）+ 当量加权主进度
    progress_segments, weighted_percent = _progress_segments(facts)
    charts["progress.svg"] = segmented_progress_chart(
        progress_segments,
        main_percent=weighted_percent,
        main_detail=(
            f"当量加权主进度 · 任务 {stats['completed']}/{stats['total']} 已完成"
            + (f"，{stats['archived']} 个已关闭" if stats["archived"] else "")
        ),
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
        "progress_percent": stats["completion_percent"],
        "time_progress_percent": time_progress,
        "progress_gap": (
            round((time_progress or 0) - stats["completion_percent"], 1)
            if time_progress is not None
            else None
        ),
        "overdue": bool(deadline_days is not None and deadline_days < 0 and stats["completion_percent"] < 100),
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
        f"本项目共 {stats['total']} 个任务，已完成 {stats['completed']}"
        f"（完成率 {stats['completion_percent']}%），运行中 {stats['running']}、"
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
        f"完成度 {stats['completion_percent']}%（{stats['completed']}/{stats['total']}），当前阶段："
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
    issue_items = issue_items[:6]

    report: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "basic_info": {
            "project_name": project_name,
            "project_id": project_id,
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
            "time_progress_percent": time_progress,
            "days_left": deadline_days,
            "deadline": str(project.get("deadline") or ""),
            "current_stage": _current_stage(active_facts, counter),
            "estimated_completion": _estimated_completion(project, active_facts),
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
            "free_energy": free_paths,
            "neb": neb_science,
            "ele": {
                "note": "电子结构分析（PDOS / Bader / 功函数 / 差分电荷）待接入报告",
                "tasks": _ele_details(facts),
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
        },
    }

    sections = _sections_markdown(report, charts)
    report["markdown_sections"] = sections
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
