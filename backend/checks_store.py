"""巡检结果存取：归档 check_results_*.json、按 task_id 合并、映射为前端展示行。"""

import json
from pathlib import Path
from typing import Any, Dict, List

from config import DATA_DIR

CHECKS_DIR = DATA_DIR / "checks"
RUNS_FILE = DATA_DIR / "checks" / "runs.json"
MAX_RUNS = 50

TASK_TYPE_LABELS = {
    "structure_opt": "结构优化",
    "electronic_structure": "电子结构",
    "free_energy": "自由能",
    "frequency": "频率计算",
    "neb": "NEB 过渡态",
}


def archive_results(entries: List[Dict[str, Any]], server: str, ts: str) -> str:
    """归档一轮巡检的批量检查结果。"""
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKS_DIR / f"check_results_{ts}_{server}.json"
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def collect_results() -> Dict[str, Dict[str, Any]]:
    """扫描结果文件并按 task_id 合并。

    同一子项保留最新一条结果（不删除历史行）；新结果优先，但新结果
    未提供/本次未检查的字段（markers / notes / force_history / 力统计）
    沿用上一次结果，避免覆盖丢失（例如本次未下载检查时保留上次的检查标记）。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    if not CHECKS_DIR.is_dir():
        return merged
    files = sorted(
        CHECKS_DIR.glob("check_results_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    for path in files:
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 单个结果文件损坏不影响整体
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            task_id = entry.get("task_id")
            if task_id:
                merged[task_id] = (
                    _merge_entry(merged[task_id], entry)
                    if task_id in merged
                    else entry
                )
    return merged


def _merge_entry(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """合并同一任务的新旧结果：新值优先，旧值中"本次未产生"的内容保留。"""
    merged = dict(new)
    # 本次未检查（无标记/无备注/无力历史）时沿用上一次的内容
    for key in ("markers", "notes", "force_history"):
        if not merged.get(key) and old.get(key):
            merged[key] = old[key]
    # 力统计字段：新结果缺失时沿用旧值（例如本次未下载检查）
    for key in ("force_max", "force_rms", "force_converged"):
        if merged.get(key) is None and old.get(key) is not None:
            merged[key] = old[key]
    return merged


def record_run(summary: Dict[str, Any]) -> None:
    """记录巡检轮次摘要（runs.json，保留最近 50 轮）。"""
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    runs: List[Dict[str, Any]] = []
    if RUNS_FILE.is_file():
        try:
            runs = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
            if not isinstance(runs, list):
                runs = []
        except Exception:  # noqa: BLE001
            runs = []
    runs.insert(0, summary)
    runs = runs[:MAX_RUNS]
    RUNS_FILE.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")


def list_runs() -> List[Dict[str, Any]]:
    if not RUNS_FILE.is_file():
        return []
    try:
        runs = json.loads(RUNS_FILE.read_text(encoding="utf-8"))
        return runs if isinstance(runs, list) else []
    except Exception:  # noqa: BLE001
        return []


def _task_lookup(db: Dict[str, Any]):
    """返回 task_id -> (project, task) 的索引。"""
    index: Dict[str, tuple] = {}
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            index[task.get("task_id")] = (project, task)
    return index


def to_frontend_rows(db: Dict[str, Any], merged: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把合并后的检查结果映射为前端巡检列表行（状态/类别/信息）。"""
    lookup = _task_lookup(db)
    rows: List[Dict[str, Any]] = []
    for task_id, entry in merged.items():
        pair = lookup.get(task_id)
        project = pair[0] if pair else {"name": entry.get("project_name", "")}
        task = pair[1] if pair else {}
        rows.append(_to_row(project, task, entry))
    return rows


def _to_row(project: Dict[str, Any], task: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    errors = [str(m) for m in entry.get("error_messages", []) or []]
    markers = [str(m) for m in entry.get("markers", []) or []]
    notes = str(entry.get("notes", "") or "")
    status = entry.get("status")
    queue = entry.get("queue_status")
    energy = entry.get("last_energy")
    all_msgs = errors + markers

    # 巡检状态：错误 > 力未收敛 > 标记/排队异常 > 正常
    if status == "zombied" or errors:
        check_status = "error"
    elif status == "completed" and entry.get("force_converged") is False:
        check_status = "warning"
    elif markers:
        check_status = "warning"
    elif queue in ("PEND", "UNKNOWN") and status not in ("completed", "running"):
        check_status = "warning"
    else:
        check_status = "normal"

    # 类别：文件问题 > 排队 > 收敛性（结构优化）
    text = " ".join(all_msgs)
    if any(k in text for k in ("OUTCAR", "POSCAR", "CONTCAR")):
        category = "file"
    elif queue == "PEND":
        category = "queue"
    elif task.get("task_type") == "structure_opt":
        category = "convergence"
    else:
        category = "file"

    energy_text = f"{energy:.4f} eV" if isinstance(energy, (int, float)) else "—"
    if check_status == "error":
        message = all_msgs[0] if all_msgs else "任务状态异常"
    elif status == "completed":
        message = f"计算完成 · 能量 {energy_text}"
        if entry.get("force_converged") is False:
            message += " · 力未收敛"
    elif status == "running":
        message = f"运行中 · 能量 {energy_text}"
        if entry.get("force_max") is not None:
            message += f" · 最大力 {entry['force_max']} eV/A"
    elif status == "queued":
        message = "排队中"
    else:
        message = f"状态：{status}"

    detail_parts: List[str] = []
    if notes:
        detail_parts.append(notes)
    detail_parts.extend(all_msgs)
    history = entry.get("force_history")
    if isinstance(history, list) and history:
        last = history[-1]
        if last.get("max_force") is not None:
            detail_parts.append(
                f"最近离子步：第 {last['step']} 步 · 最大力 {last['max_force']} eV/A"
            )
        else:
            detail_parts.append(f"离子步数：{len(history)}")
    detail = "；".join(dict.fromkeys(detail_parts)) or "无异常信息"

    task_type = task.get("task_type", "")
    return {
        "id": str(entry.get("task_id", "")),
        "check_time": str(entry.get("checked_at", "")),
        "project_name": str(entry.get("project_name", project.get("name", ""))),
        "task_id": str(entry.get("task_id", "")),
        "task_name": f"{task.get('model_name', '')} · {TASK_TYPE_LABELS.get(task_type, task_type)}",
        "category": category,
        "status": check_status,
        "message": message,
        "detail": detail,
        "analysis_needed": bool(entry.get("analysis_needed", False)),
        "has_force_history": isinstance(entry.get("force_history"), list)
        and bool(entry.get("force_history")),
    }
