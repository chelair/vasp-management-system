"""巡检结果存取：归档 check_results_*.json、按 task_id 合并、映射为前端展示行。"""

import json
import math
import re
import hashlib
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
import os
import posixpath
import tarfile
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from config import DATA_DIR
from task_paths import is_auxiliary_task

CHECKS_DIR = DATA_DIR / "checks"
RUNS_FILE = DATA_DIR / "checks" / "runs.json"
MAX_RUNS = 50
MAX_TASK_HISTORY = 5
_LOCK = threading.RLock()
_LOCAL = threading.local()


@contextmanager
def _locked():
    import fcntl
    with _LOCK:
        depth = getattr(_LOCAL, "depth", 0)
        _LOCAL.depth = depth + 1
        try:
            if depth:
                yield
            else:
                CHECKS_DIR.mkdir(parents=True, exist_ok=True)
                with (CHECKS_DIR / ".retention.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            _LOCAL.depth = depth


def _synchronized(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with _locked():
            return func(*args, **kwargs)
    return wrapped


def _atomic_json(path: Path, value, *, mtime_ns: int | None = None):
    fd, temporary = tempfile.mkstemp(dir=CHECKS_DIR, prefix=".checks_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        if mtime_ns is not None:
            os.utime(temporary, ns=(mtime_ns, mtime_ns))
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _archives():
    result = []
    for path in CHECKS_DIR.glob("check_results_*.json"):
        try:
            entries = _read_json(path, [])
            if isinstance(entries, list):
                result.append((path, path.stat().st_mtime_ns, entries))
        except (OSError, ValueError):
            continue  # 损坏文件不参与裁剪，避免误删。
    return sorted(result, key=lambda item: (item[1], item[0].name))


def _entry_time(entry: dict, fallback: float) -> float:
    try:
        return datetime.fromisoformat(str(entry.get("checked_at") or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return fallback


def _ordered_entries(archives):
    rows = [(entry, path, index, _entry_time(entry, mtime / 1e9))
            for path, mtime, entries in archives for index, entry in enumerate(entries)
            if isinstance(entry, dict) and entry.get("task_id")]
    return sorted(rows, key=lambda row: (row[3], str(row[1]), row[2]))


def observation_directory(entry: dict) -> dict:
    """目录身份独立于作业/参数；统一相对conN、完整路径和主目录别名。"""
    root = str(entry.get("remote_dir") or "").strip().rstrip("/")
    output = (entry.get("current_output") or {}).get("latest_dir")
    if output is None:
        # 没有输出来源时不擅自当作主目录；保留一个明确标记未知来源的槽。
        return {"key": "unknown:" + root, "path": None, "known": False}
    output = str(output).strip().rstrip("/")
    if output in ("", ".", "MAIN", "main"):
        path = root or "."
    elif output.startswith("/"):
        path = output
    elif root and (root == output or root.endswith("/" + output)):
        path = root
    else:
        path = posixpath.join(root, output)
    path = posixpath.normpath(path)
    return {"key": "directory:" + path, "path": path, "known": True}


def _energy_view(entry: dict) -> dict:
    """Reparse a proven legacy energy error without changing raw archives or IDs.

    Only same-directory, stable OUTCAR ionic summaries corroborated by the last
    completed OSZICAR F qualify; never borrow inherited curves or current files.
    """
    from batch_check import extract_toten
    recorded = entry.get("last_energy")
    if type(recorded) not in (int, float) or not math.isfinite(recorded):
        return entry
    evidence = entry.get("property_evidence") or {}
    directory = observation_directory(entry)
    if (not directory["known"] or not evidence.get("directory") or
            posixpath.normpath(str(evidence["directory"])) != directory["path"]):
        return entry
    files = evidence.get("files") or {}
    out, osz = files.get("OUTCAR") or {}, files.get("OSZICAR") or {}
    if out.get("stable") is not True or osz.get("stable") is not True:
        return entry
    corrected = extract_toten(str(out.get("text") or ""))
    tail = str(osz.get("text") or "").split("@@R3_TAIL@@")[-1]
    values = re.findall(r"^\s*\d+\s+F=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)", tail, re.M)
    if corrected is None or not values or abs(corrected - recorded) < 1e-8:
        return entry
    ionic_f = float(values[-1].replace("D", "E").replace("d", "e"))
    if not math.isfinite(ionic_f) or abs(ionic_f - corrected) > 1e-5:
        return entry
    return {**entry, "last_energy": corrected, "energy_correction": {
        "recorded_energy_ev": recorded, "corrected_energy_ev": corrected,
        "source": "same_observation_OUTCAR_ionic_summary_and_OSZICAR_F",
        "directory": directory["path"],
        "note": "按同次巡检保存的离子步总能重解析；原归档和观测标识保持不变，排除电子迭代能。",
    }}


def _latest_from(archives):
    merged = _read_json(CHECKS_DIR / "latest_results.json", {})
    for entry, _, _, _ in _ordered_entries(archives):
        tid = entry["task_id"]
        if tid not in merged or _entry_time(entry, 0) >= _entry_time(merged[tid], 0):
            merged[tid] = _merge_entry(merged[tid], entry) if tid in merged else entry
    return merged


def _daily_from(archives):
    # 仅保存任务ID去重集合，不保存额外巡检详情，保证裁剪不改变历史统计。
    saved = _read_json(CHECKS_DIR / "daily_summary.json", {})
    days = {day: {"completed": set(row.get("completed", [])),
                  "anomalies": {project: set(ids) for project, ids in row.get("anomalies", {}).items()}}
            for day, row in saved.items()}
    for _, mtime, entries in archives:
        day = datetime.fromtimestamp(mtime / 1e9).date().isoformat()
        bucket = days.setdefault(day, {"completed": set(), "anomalies": {}})
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("task_id"):
                continue
            tid = str(entry["task_id"])
            if entry.get("status") == "completed":
                bucket["completed"].add(tid)
            if entry.get("status") in ("zombied", "unconverged") or entry.get("error_messages"):
                bucket["anomalies"].setdefault(str(entry.get("project_name")), set()).add(tid)
    return {day: {"completed": sorted(row["completed"]),
                  "anomalies": {project: sorted(ids) for project, ids in row["anomalies"].items()}}
            for day, row in days.items()}


@_synchronized
def daily_summary() -> dict:
    return _daily_from(_archives())


def _include_backup(archives, backup_path: Path):
    """一次性迁移只读备份，不解包任意路径；恢复候选最终仍经目录去重和上限裁剪。"""
    grouped = {path.name: [path, mtime, list(entries)] for path, mtime, entries in archives}
    with tarfile.open(backup_path, "r:gz") as backup:
        for member in backup:
            name = Path(member.name).name
            if not member.isfile() or not name.startswith("check_results_") or not name.endswith(".json"):
                continue
            stream = backup.extractfile(member)
            if stream is None:
                continue
            with stream:
                entries = json.load(stream)
            if not isinstance(entries, list):
                continue
            target = grouped.setdefault(name, [CHECKS_DIR / name, int(member.mtime * 1e9), []])
            seen = {json.dumps(row, sort_keys=True, ensure_ascii=False) for row in target[2]}
            for row in entries:
                canonical = json.dumps(row, sort_keys=True, ensure_ascii=False)
                if canonical not in seen:
                    target[2].append(row)
                    seen.add(canonical)
    return list(grouped.values())


@_synchronized
def enforce_retention(backup_path: Path | None = None) -> dict:
    """每任务最多5个计算目录、每目录一个最新原始观测；先保视图/统计再原子裁剪。"""
    archives = _archives()
    existing = {path: entries for path, _, entries in archives}
    if backup_path is not None:
        archives = _include_backup(archives, backup_path)
    latest = _latest_from(archives)
    daily = _daily_from(archives)
    _atomic_json(CHECKS_DIR / "latest_results.json", latest)
    _atomic_json(CHECKS_DIR / "daily_summary.json", daily)
    kept = set()
    counts = {}
    seen_directories = set()
    for entry, path, index, _ in reversed(_ordered_entries(archives)):
        tid = entry["task_id"]
        directory = (tid, observation_directory(entry)["key"])
        if directory not in seen_directories and counts.get(tid, 0) < MAX_TASK_HISTORY:
            kept.add((path, index))
            seen_directories.add(directory)
            counts[tid] = counts.get(tid, 0) + 1
    removed = deleted = restored = 0
    for path, mtime, entries in archives:
        remaining = [entry for index, entry in enumerate(entries)
                     if not isinstance(entry, dict) or not entry.get("task_id") or (path, index) in kept]
        removed += len(entries) - len(remaining)
        restored += sum(entry not in existing.get(path, []) for entry in remaining)
        if not remaining and path.exists():
            path.unlink()
            deleted += 1
        elif remaining and remaining != existing.get(path):
            _atomic_json(path, remaining, mtime_ns=mtime)
    invalidate_cache()
    return {"tasks": len(counts), "removed_records": removed, "deleted_files": deleted,
            "retained_records": sum(counts.values()), "restored_records": restored,
            "max_per_task": MAX_TASK_HISTORY, "retention_unit": "calculation_directory"}

TASK_TYPE_LABELS = {
    "opt": "结构优化",
    "frac": "频率矫正",
    "neb": "NEB 过渡态",
    "ele": "电子结构",
}


@_synchronized
def archive_results(entries: List[Dict[str, Any]], server: str, ts: str) -> str:
    """归档一轮巡检的批量检查结果。"""
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKS_DIR / f"check_results_{ts}_{server}.json"
    _atomic_json(path, entries)
    enforce_retention()
    return str(path)


@_synchronized
def collect_results() -> Dict[str, Dict[str, Any]]:
    """扫描结果文件并按 task_id 合并。

    同一子项保留最新一条结果（不删除历史行）；新结果优先，但新结果
    未提供/本次未检查的字段（markers / notes / force_history / 力统计）
    沿用上一次结果，避免覆盖丢失（例如本次未下载检查时保留上次的检查标记）。
    """
    return {tid: _energy_view(entry) for tid, entry in _latest_from(_archives()).items()}


@_synchronized
def collect_task_observations(task_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """最近最多5个目录的最新观测及原始标识；能量可按同次证据重解析，不补填历史字段。"""
    result = []
    seen = set()
    if not task_id or limit <= 0:
        return result
    for entry, path, _, _ in reversed(_ordered_entries(_archives())):
        if entry.get("task_id") != task_id:
            continue
        directory = observation_directory(entry)
        if directory["key"] in seen:
            continue
        seen.add(directory["key"])
        canonical = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        result.append({"observation_id": hashlib.sha256((path.name + "\n" + canonical).encode()).hexdigest()[:24],
                       "archive": path.name, "directory": directory, "data": _energy_view(entry)})
        if len(result) >= min(limit, MAX_TASK_HISTORY):
            break
    return result


@_synchronized
def collect_task_history(task_id: str, limit: int = 5, scan_files: int | None = None) -> List[Dict[str, Any]]:
    """取某任务最近 `limit` 个计算目录各自最新的巡检原始条目（新→旧）。

    与 `collect_results()`（合并成"最新一条"）不同：这里要的是**历史序列**
    每目录只有一个最新结果，不是同目录的连续巡检时间序列。最多5个目录；scan_files仅保留参数兼容，
    不再限制扫描范围，避免较早停止的任务被错误判为没有历史。
    """
    if not CHECKS_DIR.is_dir() or not task_id or limit <= 0:
        return []
    return [row["data"] for row in collect_task_observations(task_id, limit)]


#: `collect_results()` 的短缓存：data/checks 有 20+MB，作业管理/总览每次请求都全量读代价太高。
#: 巡检结束后调用 `invalidate_cache()` 立即失效。
_MERGED_CACHE: Dict[str, Any] = {"at": 0.0, "data": None}
MERGED_CACHE_TTL = 30  # 秒


def merged_results(force: bool = False) -> Dict[str, Dict[str, Any]]:
    """带短缓存的 `collect_results()`（默认 30s）。"""
    now = time.time()
    cached = _MERGED_CACHE.get("data")
    if not force and cached is not None and now - float(_MERGED_CACHE.get("at") or 0) < MERGED_CACHE_TTL:
        return cached
    data = collect_results()
    _MERGED_CACHE["at"] = now
    _MERGED_CACHE["data"] = data
    return data


def invalidate_cache() -> None:
    """作废巡检结果缓存（巡检归档后调用）。"""
    _MERGED_CACHE["data"] = None


def task_check_summary(db: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """`{task_id: {status, message, checked_at, energy}}` —— 与巡检中心同一口径。

    供作业管理等页面复用：那里的"任务状态"是数据库状态，而"低精度收敛"、
    "计算完成但力未收敛"这类结论只存在于巡检结果里（落库状态仍可能是 completed）。
    """
    summary: Dict[str, Dict[str, Any]] = {}
    for row in to_frontend_rows(db, merged_results()):
        task_id = str(row.get("id") or "")
        if not task_id:
            continue
        summary[task_id] = {
            "status": row.get("status"),
            "message": row.get("message"),
            "checked_at": row.get("last_check_time"),
            "energy": row.get("last_energy"),
            "has_inspection": row.get("has_inspection"),
        }
    return summary


def _merge_entry(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """合并同一任务的新旧结果：新值优先，旧值中"本次未产生"的内容保留。"""
    merged = dict(new)
    # 本次未检查（无力历史）时沿用上一次的内容；
    # markers / notes：最新结果总是权威（空 = 本次检查无异常/无备注，覆盖旧的失败信息）
    for key in ("force_history",):
        if not merged.get(key) and old.get(key):
            merged[key] = old[key]
    # 力统计字段：新结果缺失时沿用旧值（例如本次未下载检查）。
    # force_thresholds 必须跟 force_converged 一起沿用，否则会出现"判定来自 INCAR、图上却退回 0.02"。
    for key in ("force_max", "force_rms", "force_converged", "force_thresholds"):
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


def _is_group_frac(task: Dict[str, Any]) -> bool:
    """自由能组内的频率矫正任务：不单独展示，合并到对应结构优化任务的详情。"""
    return (
        task.get("task_type") == "frac"
        and (task.get("group") or {}).get("group_type") == "free_energy"
    )


def _is_hidden_task(task: Dict[str, Any]) -> bool:
    """不出现在巡检清单里的任务：续算子任务 + 差分电荷分块（挂在 ele 主任务详情里）。"""
    return is_auxiliary_task(task) or _is_group_frac(task)


def to_frontend_rows(db: Dict[str, Any], merged: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把合并后的检查结果映射为前端巡检列表行；未巡检的任务也一并展示。"""
    lookup = _task_lookup(db)
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for task_id, entry in merged.items():
        pair = lookup.get(task_id)
        if pair is None:
            # 任务已从数据库删除（删除任务/项目后），归档中的历史记录不再展示
            continue
        project, task = pair
        if _is_hidden_task(task):
            continue
        rows.append(_to_row(project, task, entry))
        seen.add(task_id)
    # 全部项目/任务都展示：没有巡检记录的任务标记为“未巡检”
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if _is_hidden_task(task):
                continue
            if task.get("task_id") in seen:
                continue
            rows.append(_to_row(project, task, None))
    return rows


def _to_row(project: Dict[str, Any], task: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    task_category = _task_category(task)
    group = task.get("group") or {}
    group_name = group.get("name") or ""
    structure_label = group.get("structure_label") or ""
    group_id = group.get("group_id") or ""
    if entry is None:
        task_type = task.get("task_type", "")
        archived = str(task.get("status") or "") == "archived"
        return {
            "id": str(task.get("task_id", "")),
            "check_time": "",
            "project_name": str(project.get("name", "")),
            "task_id": str(task.get("task_id", "")),
            "task_name": f"{task.get('model_name', '')} · {TASK_TYPE_LABELS.get(task_type, task_type)}",
            "group_name": group_name,
            "group_id": group_id,
            "structure_label": structure_label,
            "category": "queue",
            "task_category": task_category,
            # 已归档任务：状态列显示“关闭”，不再按未巡检处理
            "status": "archived" if archived else "pending",
            "task_status": str(task.get("status") or "pending"),
            "message": "关闭" if archived else "未检",
            "detail": (
                "任务已关闭（归档），不再参与巡检"
                if archived
                else "暂无巡检记录，可点击「单独巡检」获取该任务当前状态"
            ),
            "project_closed": bool(project.get("closed")),
            "analysis_needed": False,
            "has_force_history": False,
            "has_inspection": False,
            "status_changed": False,
            "latest_dir": None,
            "output_status": None,
        }
    errors = [str(m) for m in entry.get("error_messages", []) or []]
    markers = [str(m) for m in entry.get("markers", []) or []]
    notes = str(entry.get("notes", "") or "")
    status = entry.get("status")
    task_status = str(task.get("status") or "")
    queue = entry.get("queue_status")
    energy = entry.get("last_energy")
    all_msgs = errors + markers

    # 巡检状态：错误 > 力未收敛 > 标记/排队异常 > 正常
    # 标记仅限真正的异常（下载失败/文件缺失等）；信息性标记（如“结构对比使用续算输出”）不告警
    warning_markers = [
        m
        for m in markers
        if any(
            k in m
            for k in ("缺失", "为空", "未生成", "失败", "异常", "error", "not found", "unreadable")
        )
    ]
    # 僵尸/异常先判 error；未收敛（unconverged）优先于 error_messages
    # （batch_check 会把"forces not converged"写入 error_messages，不能因此判为错误）
    # 已归档优先：归档只改本地状态，不参与巡检判定，也不应被巡检结果覆盖
    if task_status == "archived" or status == "archived":
        check_status = "archived"
    elif status == "zombied":
        check_status = "error"
    elif status in ("unconverged", "low_precision"):
        check_status = "warning"
    elif errors:
        check_status = "error"
    elif status == "completed" and entry.get("force_converged") is False:
        check_status = "warning"
    elif queue == "SSUSP":
        check_status = "warning"
    elif warning_markers:
        check_status = "warning"
    # 排队中（PEND）算正常等待，不再报警告（v0.9.19 用户确认："排队中就是正常"）；
    # 只有"查不到队列状态"（UNKNOWN，bjobs 拿不到信息）才提示
    elif queue == "UNKNOWN" and status not in ("completed", "running"):
        check_status = "warning"
    else:
        check_status = "normal"

    # 类别：文件问题 > 排队 > 收敛性（结构优化）
    text = " ".join(all_msgs)
    if any(k in text for k in ("OUTCAR", "POSCAR", "CONTCAR")):
        category = "file"
    elif queue in ("PEND", "SSUSP"):
        category = "queue"
    elif task.get("task_type") == "opt":
        category = "convergence"
    else:
        category = "file"

    energy_text = f"{energy:.4f} eV" if isinstance(energy, (int, float)) else "—"
    if check_status == "error":
        message = all_msgs[0] if all_msgs else "任务状态异常"
    elif check_status == "archived":
        message = "任务已关闭（归档）"
    elif status == "low_precision":
        precision = entry.get("precision") or {}
        issues = "；".join(str(x) for x in precision.get("issues") or [])
        message = f"低精度收敛 · 能量 {energy_text}" + (f" · {issues}" if issues else "")
    elif status == "completed":
        message = f"计算完成 · 能量 {energy_text}"
        if entry.get("force_converged") is False:
            message += " · 力未收敛"
    elif status == "unconverged":
        message = f"计算完成但力未收敛 · 能量 {energy_text}"
        if entry.get("force_max") is not None:
            message += f" · 最大力 {entry['force_max']} eV/A"
    elif status == "running":
        if queue == "SSUSP":
            message = "挂起（SSUSP）"
        else:
            message = f"运行中 · 能量 {energy_text}"
            if entry.get("force_max") is not None:
                message += f" · 最大力 {entry['force_max']} eV/A"
    elif status == "queued":
        message = "排队中"
    else:
        message = f"状态：{status}"

    detail_parts: List[str] = []
    precision = entry.get("precision") or {}
    if precision and precision.get("ok") is False:
        detail_parts.append(
            "精度检查未达标：" + "；".join(str(x) for x in precision.get("issues") or [])
        )
    elif precision and precision.get("undetermined"):
        detail_parts.append(
            "精度检查部分无法判定："
            + "；".join(str(x) for x in precision.get("undetermined") or [])
        )
    thresholds = entry.get("force_thresholds") or {}
    if thresholds.get("source"):
        detail_parts.append(
            f"力收敛阈值 {thresholds.get('max_force_threshold')} eV/A（来源 {thresholds['source']}）"
        )
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
    current_output = task.get("current_output") or entry.get("current_output") or {}
    latest_dir = current_output.get("latest_dir") if isinstance(current_output, dict) else None
    output_status = (
        current_output.get("status") if isinstance(current_output, dict) else None
    )
    return {
        "id": str(entry.get("task_id", "")),
        "check_time": str(entry.get("checked_at", "")),
        "project_name": str(entry.get("project_name", project.get("name", ""))),
        "task_id": str(entry.get("task_id", "")),
        "task_name": f"{task.get('model_name', '')} · {TASK_TYPE_LABELS.get(task_type, task_type)}",
        "group_name": group_name,
        "group_id": group_id,
        "structure_label": structure_label,
        "category": category,
        "status": check_status,
        "message": message,
        "detail": detail,
        "task_category": task_category,
        "task_status": task_status,
        "project_closed": bool(project.get("closed")),
        "analysis_needed": bool(entry.get("analysis_needed", False)),
        "has_force_history": isinstance(entry.get("force_history"), list)
        and bool(entry.get("force_history")),
        "has_inspection": True,
        # 本次巡检相对上次状态有变化（如 running→completed），前端用于未读红点提醒
        "status_changed": bool(entry.get("observed_changed", False)),
        "latest_dir": latest_dir,
        "output_status": output_status,
    }


def _task_category(task: Dict[str, Any]) -> str:
    """任务类型分类（结构优化 / 自由能 / NEB / 电子结构），与前端树分类一致。"""
    gtype = (task.get("group") or {}).get("group_type")
    task_type = task.get("task_type", "")
    if gtype == "free_energy" or (task_type == "frac" and not gtype):
        return "自由能"
    if gtype == "neb" or task_type == "neb":
        return "NEB"
    if task_type == "ele":
        return "电子结构"
    return "结构优化"
