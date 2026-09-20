"""总览页数据聚合（Dashboard）。

设计要点：

- **单次 SSH 往返（v0.8.7 起与作业管理共用）**：bjobs / blimits / df / bhosts /
  bqueues 的采集在 `cluster_probe.py`，用 `@@@SECTION` 标记分段；总览与作业管理
  读**同一份**缓存，任一页 `refresh=1` 都会强制重采（两边同时更新）。
- **缓存**：集群采集按 TTL 缓存，默认 5 分钟（settings.json `cluster_cache_seconds`，
  兼容旧的 `dashboard_cache_seconds`），`refresh=1` 强制刷新；本地聚合（风险/统计/趋势）
  缓存 60 秒。**打开页面不会每次都发 SSH** —— TTL 内直接命中缓存。
- **命令可配置**：node_status_cmd / queue_status_cmd / user_used_cores_cmd /
  user_total_cores_cmd / storage_check_cmd，servers.json（按服务器）优先，
  其次 settings.json（全局），最后用内置默认值，便于适配 Slurm 等调度器。
- **历史趋势**：每次成功查询追加一条核数/任务数快照到
  `data/dashboard/core_history.json`（10 分钟内不重复采样），前端按天聚合；
  历史从接入本功能那天开始累积。
"""

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

import cluster_probe
from checks_store import CHECKS_DIR, collect_results, list_runs, to_frontend_rows
from config import DATA_DIR, load_servers, load_settings
from storage import load_db
from task_paths import is_continuation_task

DASHBOARD_DIR = DATA_DIR / "dashboard"
HISTORY_FILE = DASHBOARD_DIR / "core_history.json"
AUDIT_FILE = DATA_DIR / "audit_submit.log"

LOCAL_CACHE_TTL = 60  # 本地聚合缓存（秒）
HISTORY_MIN_INTERVAL = 600  # 历史采样最小间隔（秒）
HISTORY_MAX = 4000  # 历史文件最多保留条数
TREND_DAYS = 7
STORAGE_WARN_PERCENT = 85  # 存储使用率告警线（剩余 <15%）
CORES_WARN_PERCENT = 90  # 核数占用告警线

#: 采集命令默认值（实现已搬到 cluster_probe，这里保留别名便于外部引用）
DEFAULT_COMMANDS = cluster_probe.DEFAULT_COMMANDS

_local_cache: Dict[str, Any] = {"at": 0.0, "data": None}
_lock = threading.Lock()


# ------------------------------------------------------------------ 远端解析


def parse_jobs(text: str) -> List[Dict[str, Any]]:
    """解析 `bjobs -o "jobid stat queue job_name slots exec_host" -noheader`。

    行格式：JOBID STAT QUEUE JOB_NAME SLOTS EXEC_HOST
    挂起/排队作业的 SLOTS 与 EXEC_HOST 为 `-`。
    """
    jobs: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        slots = 0
        if len(parts) >= 5 and re.fullmatch(r"\d+", parts[4]):
            slots = int(parts[4])
        hosts: List[Dict[str, Any]] = []
        if len(parts) >= 6 and parts[5] != "-":
            for chunk in parts[5].split(":"):
                m = re.fullmatch(r"(\d+)\*(\S+)", chunk)
                if m:
                    hosts.append({"cores": int(m.group(1)), "host": m.group(2)})
                elif chunk:
                    hosts.append({"cores": 0, "host": chunk})
        jobs.append(
            {
                "job_id": parts[0],
                "status": parts[1],
                "queue": parts[2],
                "name": parts[3],
                "cores": slots,
                "execHosts": hosts,
            }
        )
    return jobs


def parse_blimits(text: str, user: str) -> Dict[str, Any]:
    """解析 `blimits` 中当前用户的 SLOTS 配额行。

    列：NAME USERS QUEUES HOSTS PROJECTS APPS SLOTS MEM TMP SWP JOBS，
    其中 QUEUES 可能含多个队列（含空格），所以取该行第一个 `n/m` 形式的
    数值作为 SLOTS（已用/上限）；同一用户多行（按队列组分别限制）取最大值。
    """
    used: Optional[int] = None
    limit: Optional[int] = None
    queues: List[str] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0].upper() == "NAME":
            continue
        if user not in parts:
            continue
        slot_tokens = [p for p in parts if re.fullmatch(r"\d+/\d+", p)]
        if not slot_tokens:
            continue
        cur_used, cur_limit = (int(x) for x in slot_tokens[0].split("/"))
        used = cur_used if used is None else max(used, cur_used)
        limit = cur_limit if limit is None else max(limit, cur_limit)
        if not queues:
            # USERS 之后的队列名（到第一个非队列标记前）
            idx = parts.index(user) + 1
            for token in parts[idx:]:
                if token in ("-",) or re.fullmatch(r"[\d/]+", token):
                    break
                queues.append(token)
    return {"used": used, "limit": limit, "queues": queues}


def parse_bhosts(text: str) -> Dict[str, Any]:
    """解析 `bhosts`：按节点汇总正常/满载/关闭/不可用与核数占用。"""
    nodes: List[Dict[str, Any]] = []
    header: Dict[str, int] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].upper() == "HOST_NAME":
            header = {name.upper(): i for i, name in enumerate(parts)}
            continue
        if not header:
            continue

        def col(key: str) -> int:
            idx = header.get(key)
            if idx is None or idx >= len(parts):
                return 0
            try:
                return int(parts[idx])
            except ValueError:
                return 0

        max_cores = col("MAX")
        if max_cores <= 0:  # 登录/管理节点不计入计算资源
            continue
        running = col("RUN")
        suspended = col("SSUSP") + col("USUSP")
        unavail = col("UNAVAIL")
        idle = max(0, max_cores - running - suspended - unavail)
        nodes.append(
            {
                "name": parts[0],
                "lsfStatus": parts[1] if len(parts) > 1 else "",
                "maxCores": max_cores,
                "runningCores": running,
                "idleCores": idle,
                "unavailCores": unavail,
            }
        )

    def kind(node: Dict[str, Any]) -> str:
        status = str(node["lsfStatus"]).lower()
        if status in ("unavail", "unknow", "new"):
            return "down"
        # LSF 常把跑满的节点置为 closed：先按核数判定满载，再区分真正关闭的节点
        if node["runningCores"] >= node["maxCores"] > 0:
            return "full"
        if status.startswith("closed"):
            return "closed"
        if node["idleCores"] <= 0 and node["runningCores"] > 0:
            return "full"
        return "ok"

    counted = [{**n, "kind": kind(n)} for n in nodes]
    by_kind = {
        k: sum(1 for n in counted if n["kind"] == k)
        for k in ("ok", "full", "closed", "down")
    }
    return {
        "total": len(counted),
        "ok": by_kind["ok"],
        "full": by_kind["full"],
        "closed": by_kind["closed"],
        "down": by_kind["down"],
        "totalCores": sum(n["maxCores"] for n in counted),
        "runningCores": sum(n["runningCores"] for n in counted),
        "idleCores": sum(n["idleCores"] for n in counted),
    }


def parse_bqueues(text: str) -> List[Dict[str, Any]]:
    """解析 `bqueues`：QUEUE_NAME PRIO STATUS MAX JL/U JL/P JL/H NJOBS PEND RUN SUSP。"""
    queues: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 11 or parts[0].upper() == "QUEUE_NAME":
            continue
        try:
            queues.append(
                {
                    "queue": parts[0],
                    "status": parts[2],
                    "jobs": int(parts[7]),
                    "pending": int(parts[8]),
                    "running": int(parts[9]),
                    "suspended": int(parts[10]),
                }
            )
        except ValueError:
            continue
    return queues


def parse_df(text: str) -> Optional[Dict[str, Any]]:
    """解析 `df -h`，取第一条数据行（项目根所在文件系统）。"""
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[0].lower() == "filesystem":
            continue
        if not re.fullmatch(r"\d+%", parts[4]):
            continue
        used_percent = int(parts[4].rstrip("%"))
        return {
            "filesystem": parts[0],
            "size": parts[1],
            "used": parts[2],
            "available": parts[3],
            "usedPercent": used_percent,
            "mountedOn": parts[5],
            "warning": used_percent >= STORAGE_WARN_PERCENT,
        }
    return None


# ------------------------------------------------------------------ 集群快照


def cluster_snapshot(
    server_name: str, refresh: bool = False
) -> Dict[str, Any]:
    """取集群快照：读 `cluster_probe` 的**共享采集**（默认缓存 5 分钟，作业管理同一份）。

    失败但有上一份采集时返回旧数据 + `stale` + `error`（不伪造数据）；
    完全没有数据时返回 `source="error"` 的空快照。
    """
    with _lock:
        probe = cluster_probe.probe(server_name, refresh=refresh)
        sections = probe.get("sections") or {}
        cfg = load_servers().get(server_name, {}) or {}
        user = str(cfg.get("user", "") or "")
        snapshot: Dict[str, Any] = {
            "server": server_name,
            "source": "real" if sections else "error",
            "error": probe.get("error"),
            "queriedAt": probe.get("queriedAt"),
            "jobs": [],
            "coreLimit": {"used": None, "limit": None, "queues": []},
            "storage": None,
            "nodes": None,
            "queues": [],
        }
        if sections:
            snapshot["jobs"] = parse_jobs(sections.get("BJOBS", ""))
            snapshot["coreLimit"] = parse_blimits(sections.get("BLIMITS", ""), user)
            snapshot["storage"] = parse_df(sections.get("DF", ""))
            snapshot["nodes"] = parse_bhosts(sections.get("BHOSTS", ""))
            snapshot["queues"] = parse_bqueues(sections.get("BQUEUES", ""))
            snapshot["raw"] = {
                key: sections.get(key, "")[:4000]
                for key in ("BJOBS", "BLIMITS", "DF")
            }
        if snapshot["source"] == "real" and not probe.get("cached"):
            _append_history(snapshot)
        return {
            **snapshot,
            "cached": probe.get("cached"),
            "stale": probe.get("stale"),
            "cacheAgeSeconds": probe.get("cacheAgeSeconds"),
            "cacheTtlSeconds": probe.get("cacheTtlSeconds"),
        }


# ------------------------------------------------------------------ 历史趋势


def _read_history() -> List[Dict[str, Any]]:
    if not HISTORY_FILE.is_file():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _append_history(snapshot: Dict[str, Any]) -> None:
    """记录一条核数/任务快照（10 分钟内不重复采样）。"""
    jobs = snapshot.get("jobs", [])
    running = [j for j in jobs if j.get("status") == "RUN"]
    sample = {
        "ts": snapshot.get("queriedAt"),
        "usedCores": sum(int(j.get("cores") or 0) for j in running),
        "runningTasks": len(running),
        "pendingTasks": sum(1 for j in jobs if j.get("status") == "PEND"),
        "limitCores": (snapshot.get("coreLimit") or {}).get("limit"),
    }
    history = _read_history()
    if history:
        try:
            last = datetime.fromisoformat(str(history[-1].get("ts")))
            if (datetime.now() - last).total_seconds() < HISTORY_MIN_INTERVAL:
                return
        except Exception:  # noqa: BLE001
            pass
    history.append(sample)
    history = history[-HISTORY_MAX:]
    try:
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(HISTORY_FILE)
    except Exception:  # noqa: BLE001 - 历史写入失败不影响接口
        pass


def _audit_submissions() -> Dict[str, int]:
    """从 data/audit_submit.log 统计每日提交成功作业数（result=OK）。"""
    counts: Dict[str, int] = {}
    if not AUDIT_FILE.is_file():
        return counts
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()[-2000:]
    except Exception:  # noqa: BLE001
        return counts
    for line in lines:
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2})T[^\]]*\]", line)
        if not m or "result=OK" not in line or "job=" not in line:
            continue
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def build_trend(days: int = TREND_DAYS) -> Dict[str, Any]:
    """近 N 天趋势：核数占用/运行中任务（历史快照按天取峰值）+ 每日提交数。"""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    samples = _read_history()
    submissions = _audit_submissions()
    buckets: Dict[str, List[Dict[str, Any]]] = {d.isoformat(): [] for d in dates}
    for sample in samples:
        day = str(sample.get("ts", ""))[:10]
        if day in buckets:
            buckets[day].append(sample)
    points: List[Dict[str, Any]] = []
    for d in dates:
        key = d.isoformat()
        day_samples = buckets[key]
        points.append(
            {
                "date": key,
                "label": d.strftime("%m-%d"),
                "usedCores": max((int(s.get("usedCores") or 0) for s in day_samples), default=None),
                "runningTasks": max((int(s.get("runningTasks") or 0) for s in day_samples), default=None),
                "submissions": submissions.get(key, 0),
            }
        )
    return {
        "points": points,
        "since": str(samples[0].get("ts"))[:10] if samples else None,
        "sampleCount": len(samples),
        "note": (
            f"核数占用/运行中任务自 {str(samples[0].get('ts'))[:10]} 起累积（每次查询集群时采样）"
            if samples
            else "尚无集群采样记录：刷新集群状态后开始累积"
        ),
    }


# ------------------------------------------------------------------ 本地聚合


def _completed_stats(db: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """今日/昨日「新完成」任务数：当天巡检观察到 completed 且前一天未完成的任务。

    按检查文件 mtime 归日（归档文件即一轮巡检的产物），任务去重。
    `db` 不为 None 时只统计该项目集合下的任务（第 4 步：普通用户只看自己的）。
    """
    allowed: Optional[set] = None
    if db is not None:
        allowed = {
            str(t.get("task_id"))
            for p in db.get("projects", [])
            for t in p.get("tasks", [])
        }
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    prev = today - timedelta(days=2)
    seen: Dict[str, set] = {"today": set(), "yesterday": set(), "prev": set()}
    files = sorted(CHECKS_DIR.glob("check_results_*.json"), key=lambda p: p.stat().st_mtime)
    for path in files[-400:]:
        try:
            day = datetime.fromtimestamp(path.stat().st_mtime).date()
        except OSError:
            continue
        if day == today:
            key = "today"
        elif day == yesterday:
            key = "yesterday"
        elif day == prev:
            key = "prev"
        else:
            continue
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if entry.get("status") == "completed" and entry.get("task_id"):
                task_id = str(entry["task_id"])
                if allowed is not None and task_id not in allowed:
                    continue
                seen[key].add(task_id)
    today_new = seen["today"] - seen["yesterday"]
    yesterday_new = seen["yesterday"] - seen["prev"]
    return {
        "todayCompleted": len(today_new),
        "yesterdayCompleted": len(yesterday_new),
        "delta": len(today_new) - len(yesterday_new),
        "stillCompletedToday": len(seen["today"]),
    }


def _task_index(db: Dict[str, Any]) -> Tuple[Dict[str, Tuple[Dict, Dict]], Dict[str, Tuple[Dict, Dict]]]:
    """按 job_id 与作业名建立 task 索引（作业名回退匹配，LSF 名可能被截断）。"""
    by_job: Dict[str, Tuple[Dict, Dict]] = {}
    by_name: Dict[str, Tuple[Dict, Dict]] = {}
    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if is_continuation_task(task):
                continue
            job_id = str(task.get("job_id") or "").strip()
            if job_id:
                by_job.setdefault(job_id, (project, task))
            name = str(task.get("model_name") or "").strip()
            if name:
                by_name.setdefault(name, (project, task))
    return by_job, by_name


UNREGISTERED = "未登记任务"


def build_running_tasks(db: Dict[str, Any], snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_job, by_name = _task_index(db)
    rows: List[Dict[str, Any]] = []
    order = {"RUN": 0, "SSUSP": 1, "USUSP": 2, "PSUSP": 3, "PEND": 4}
    for job in snapshot.get("jobs", []):
        pair = by_job.get(str(job.get("job_id")))
        lsf_name = str(job.get("name") or "")
        if pair is None and lsf_name:
            pair = by_name.get(lsf_name)
        project, task = pair if pair else (None, None)
        rows.append(
            {
                "job_id": str(job.get("job_id")),
                "job_name": lsf_name,
                "task_id": str(task.get("task_id")) if task else None,
                "task_name": str(task.get("model_name")) if task else lsf_name,
                "task_type": str(task.get("task_type")) if task else None,
                "project_name": str(project.get("name")) if project else UNREGISTERED,
                "queue": str(job.get("queue") or ""),
                "cores": int(job.get("cores") or 0),
                "status": str(job.get("status") or ""),
                "execHosts": job.get("execHosts") or [],
            }
        )
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["project_name"], r["task_name"]))
    return rows


def build_cores_usage(db: Dict[str, Any], snapshot: Dict[str, Any]) -> Dict[str, Any]:
    running = [j for j in snapshot.get("jobs", []) if j.get("status") == "RUN"]
    used_from_jobs = sum(int(j.get("cores") or 0) for j in running)
    core_limit = snapshot.get("coreLimit") or {}
    # 总核数上限：settings.json 的 dashboard_total_cores 可手动覆盖 blimits（管理员自定义配额）
    manual_total = load_settings().get("dashboard_total_cores")
    limit_source = "blimits"
    limit = core_limit.get("limit")
    try:
        manual_total = int(manual_total) if manual_total else None
    except (TypeError, ValueError):
        manual_total = None
    if manual_total and manual_total > 0:
        limit = manual_total
        limit_source = "manual"
    used = core_limit.get("used")
    if used is None:
        used = used_from_jobs

    by_job, by_name = _task_index(db)
    groups: Dict[str, int] = {}
    for job in running:
        pair = by_job.get(str(job.get("job_id"))) or by_name.get(str(job.get("name") or ""))
        project_name = str(pair[0].get("name")) if pair else UNREGISTERED
        groups[project_name] = groups.get(project_name, 0) + int(job.get("cores") or 0)

    total = int(limit) if limit else None
    remaining = max(0, total - int(used)) if total else None
    percent = round(int(used) / total * 100, 1) if total else None
    level = "normal"
    if percent is not None and percent >= 100:
        level = "critical"
    elif percent is not None and percent >= CORES_WARN_PERCENT:
        level = "warning"
    return {
        "usedCores": int(used),
        "totalCores": total,
        "remainingCores": remaining,
        "usedPercent": percent,
        "level": level,
        "limitSource": limit_source if limit else "unknown",
        "runningJobs": len(running),
        "summedJobCores": used_from_jobs,
        "queues": core_limit.get("queues") or [],
        "byProject": sorted(
            ({"project_name": k, "cores": v} for k, v in groups.items()),
            key=lambda g: -g["cores"],
        ),
    }


def build_cluster_health(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    nodes = snapshot.get("nodes") or {}
    queues = snapshot.get("queues") or []
    top_queues = sorted(queues, key=lambda q: -int(q.get("pending") or 0))[:6]
    return {
        "nodes": nodes,
        "queues": [
            {
                "queue": q.get("queue"),
                "pending": q.get("pending"),
                "running": q.get("running"),
                "suspended": q.get("suspended"),
                "status": q.get("status"),
            }
            for q in top_queues
        ],
        "queueTotals": {
            "pending": sum(int(q.get("pending") or 0) for q in queues),
            "running": sum(int(q.get("running") or 0) for q in queues),
            "queues": len(queues),
        },
        "storage": snapshot.get("storage"),
    }


def build_risk_alerts(db: Dict[str, Any]) -> Dict[str, Any]:
    merged = collect_results()
    rows = to_frontend_rows(db, merged)
    alerts: List[Dict[str, Any]] = []
    seen: set = set()

    def add(item: Dict[str, Any]) -> None:
        key = f"{item.get('task_id')}:{item.get('kind')}"
        if key in seen:
            return
        seen.add(key)
        alerts.append(item)

    for project in db.get("projects", []):
        for task in project.get("tasks", []):
            if is_continuation_task(task):
                continue
            status = str(task.get("status") or "")
            base = {
                "task_id": str(task.get("task_id") or ""),
                "task_name": str(task.get("model_name") or ""),
                "task_type": str(task.get("task_type") or ""),
                "project_name": str(project.get("name") or ""),
                "status": status,
                "last_check_time": task.get("last_check_time"),
                "remote_dir": task.get("remote_dir"),
            }
            if status == "unconverged":
                add(
                    {
                        **base,
                        "kind": "unconverged",
                        "severity": "warning",
                        "title": "力未收敛，需要续算",
                        "reason": "结构优化未达到力收敛标准（max>0.02 或 rms>0.01 eV/A）",
                        "action": "续算",
                    }
                )
            elif status == "zombied":
                add(
                    {
                        **base,
                        "kind": "zombied",
                        "severity": "error",
                        "title": "作业异常中断（Zombie）",
                        "reason": "计算被中断且无结束标志，需要重新提交或续算",
                        "action": "重新提交",
                    }
                )

    for row in rows:
        if row.get("status") not in ("error", "warning"):
            continue
        if any(a.get("task_id") == str(row.get("task_id")) for a in alerts):
            continue
        add(
            {
                "task_id": str(row.get("task_id") or ""),
                "task_name": str(row.get("task_name") or "").split(" · ")[0],
                "task_type": "",
                "project_name": str(row.get("project_name") or ""),
                "status": "check",
                "kind": "inspection",
                "severity": str(row.get("status")),
                "title": "巡检发现异常",
                "reason": str(row.get("message") or row.get("detail") or ""),
                "action": "查看巡检",
                "last_check_time": row.get("check_time"),
                "remote_dir": None,
            }
        )

    runs = list_runs()
    last_run = runs[0] if runs else None
    severity_order = {"error": 0, "warning": 1}
    alerts.sort(key=lambda a: severity_order.get(str(a.get("severity")), 9))
    return {
        "alerts": alerts,
        "errorCount": sum(1 for a in alerts if a.get("severity") == "error"),
        "warningCount": sum(1 for a in alerts if a.get("severity") == "warning"),
        "lastInspectionAt": (last_run or {}).get("checked_at"),
        "lastInspectionInspected": (last_run or {}).get("inspected"),
        "lastInspectionUpdated": (last_run or {}).get("updated"),
    }


def build_project_progress(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    today = date.today()
    result: List[Dict[str, Any]] = []
    for project in db.get("projects", []):
        tasks = [t for t in project.get("tasks", []) if not is_continuation_task(t)]
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") in ("completed", "archived"))
        archived = sum(1 for t in tasks if t.get("status") == "archived")
        running = sum(1 for t in tasks if t.get("status") == "running")
        queued = sum(1 for t in tasks if t.get("status") == "queued")
        anomalies = sum(1 for t in tasks if t.get("status") in ("zombied", "unconverged"))
        deadline = str(project.get("deadline") or "")
        try:
            days_left = (date.fromisoformat(deadline) - today).days
        except ValueError:
            days_left = None
        started = str(project.get("created_at") or "")[:10]
        try:
            span = max(1, (date.fromisoformat(deadline) - date.fromisoformat(started)).days)
            time_ratio = min(1.0, max(0.0, (today - date.fromisoformat(started)).days / span))
        except ValueError:
            time_ratio = None
        result.append(
            {
                "project_id": str(project.get("project_id") or ""),
                "project_name": str(project.get("name") or ""),
                "deadline": deadline,
                "daysLeft": days_left,
                "overdue": days_left is not None and days_left < 0 and completed < total,
                "totalTasks": len(project.get("tasks", []) or []),
                "visibleTasks": total,
                "continuationTasks": len(project.get("tasks", []) or []) - total,
                "completed": completed,
                "archived": archived,
                "closable": bool(tasks) and archived == total,
                "closed": bool(project.get("closed")),
                "running": running,
                "queued": queued,
                "anomalies": anomalies,
                "progress": round(completed / total * 100) if total else 0,
                "timeRatio": time_ratio,
                "workload": str(project.get("workload") or ""),
            }
        )
    return result


def _visible_db(project_names: Optional[Set[str]]) -> Dict[str, Any]:
    """按可见项目名过滤项目库（None = 不过滤；admin 走 None）。"""
    db = load_db()
    if project_names is None:
        return db
    return {
        **db,
        "projects": [
            p for p in db.get("projects", []) if str(p.get("name") or "") in project_names
        ],
    }


def _build_local_bundle(db: Dict[str, Any], month: str, at: float) -> Dict[str, Any]:
    """本地聚合结果（项目进度 / 风险 / 完成统计）；db 决定统计范围。"""
    all_tasks = [
        t
        for p in db.get("projects", [])
        for t in p.get("tasks", [])
        if not is_continuation_task(t)
    ]
    return {
        "riskAlerts": build_risk_alerts(db),
        "trend": build_trend(),
        "projectProgress": build_project_progress(db),
        "completed": _completed_stats(db),
        "stats": {
            "projects": len(db.get("projects", [])),
            "projectsThisMonth": sum(
                1
                for p in db.get("projects", [])
                if str(p.get("created_at") or "").startswith(month)
            ),
            "running": sum(1 for t in all_tasks if t.get("status") == "running"),
            "queued": sum(1 for t in all_tasks if t.get("status") == "queued"),
            "totalTasks": len(all_tasks),
        },
        "at": at,
    }


def local_bundle(
    refresh: bool = False, project_names: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """本地聚合结果（风险任务 / 趋势 / 项目进度 / 完成统计），缓存 60 秒。

    巡检归档目录有数百个结果文件，逐个读取约 1-2 秒，因此整体缓存。

    第 4 步：`project_names` 不为 None 时按可见项目过滤（普通用户）——
    各用户可见集合不同，这条路径不走全局缓存，直接现算；admin 传 None 走缓存。
    """
    global _local_cache
    now = time.time()
    month = datetime.now().strftime("%Y-%m")
    if project_names is not None:
        return _build_local_bundle(_visible_db(project_names), month, now)
    if (
        not refresh
        and _local_cache["data"]
        and now - _local_cache["at"] < LOCAL_CACHE_TTL
    ):
        return _local_cache["data"]
    bundle = _build_local_bundle(load_db(), month, now)
    _local_cache = {"at": now, "data": bundle}
    return bundle


def build_overview(
    server_name: str,
    refresh: bool = False,
    project_names: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """总览页聚合数据（顶部统计 + 运行任务 + 核数 + 集群 + 风险 + 项目进度 + 趋势）。

    `project_names` 不为 None 时只统计当前用户可见的项目（第 4 步）；
    集群级信息（节点 / 队列 / 存储 / 提交趋势）保持全局。
    """
    snapshot = cluster_snapshot(server_name, refresh=refresh)
    local = local_bundle(refresh=refresh, project_names=project_names)
    db = _visible_db(project_names)
    risks = local["riskAlerts"]
    completed = local["completed"]
    base = local["stats"]
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "server": server_name,
        "stats": {
            **base,
            "runningJobs": len([j for j in snapshot.get("jobs", []) if j.get("status") == "RUN"]),
            "pendingJobs": len([j for j in snapshot.get("jobs", []) if j.get("status") == "PEND"]),
            "todayCompleted": completed["todayCompleted"],
            "yesterdayCompleted": completed["yesterdayCompleted"],
            "completedDelta": completed["delta"],
            "anomalies": len(risks["alerts"]),
            "errorCount": risks["errorCount"],
            "warningCount": risks["warningCount"],
        },
        "runningTasks": build_running_tasks(db, snapshot),
        "coresUsage": build_cores_usage(db, snapshot),
        "clusterHealth": build_cluster_health(snapshot),
        "riskAlerts": risks,
        "projectProgress": local["projectProgress"],
        "recentTasks": recent_tasks(db),
        "trend": local["trend"],
        "cluster": {
            "source": snapshot.get("source"),
            "error": snapshot.get("error"),
            "queriedAt": snapshot.get("queriedAt"),
            "cached": snapshot.get("cached"),
            "cacheAgeSeconds": snapshot.get("cacheAgeSeconds"),
            "stale": snapshot.get("stale", False),
        },
    }


def recent_tasks(db: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    """最近有巡检记录的任务，按项目轮转取样，避免整张表只来自一个项目。"""
    by_project: Dict[str, List[Dict[str, Any]]] = {}
    for project in db.get("projects", []):
        name = str(project.get("name") or "")
        for task in project.get("tasks", []):
            if is_continuation_task(task):
                continue
            by_project.setdefault(name, []).append(
                {
                    "task_id": str(task.get("task_id") or ""),
                    "task_name": str(task.get("model_name") or ""),
                    "task_type": str(task.get("task_type") or ""),
                    "project_name": name,
                    "status": str(task.get("status") or ""),
                    "last_energy": task.get("last_energy"),
                    "job_id": task.get("job_id"),
                    "last_check_time": task.get("last_check_time"),
                }
            )
    for rows in by_project.values():
        rows.sort(
            key=lambda r: (str(r.get("last_check_time") or ""), str(r.get("task_id") or "")),
            reverse=True,
        )
    # 轮转取样：每轮从各项目取一条最新的，直到取满 limit
    result: List[Dict[str, Any]] = []
    index = 0
    while len(result) < limit:
        added = False
        for rows in by_project.values():
            if index < len(rows) and len(result) < limit:
                result.append(rows[index])
                added = True
        if not added:
            break
        index += 1
    return result


def cached_overview(
    server_name: str, refresh: bool = False, project_names: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """兼容入口：集群快照与本地聚合各自带缓存。"""
    return build_overview(server_name, refresh=refresh, project_names=project_names)


def invalidate_cluster_cache(
    servers: Optional[List[str]] = None, prewarm: bool = True
) -> List[str]:
    """作废集群采集缓存（巡检结束后调用，让总览/作业管理都拿到最新数据）。

    - 只作废传入的服务器；不传则作废全部有缓存的服务器。
    - `prewarm=True` 时后台线程立即重查一次（静默，不阻塞调用方），
      这样用户切到总览页时直接命中新快照。
    """
    global _local_cache
    targets = cluster_probe.invalidate(servers)
    # 本地聚合（风险/趋势/项目进度）同样可能与巡检结果相关
    _local_cache = {"at": 0.0, "data": None}

    if not prewarm or not targets:
        return targets

    def _worker() -> None:
        for name in targets:
            try:
                cluster_snapshot(name, refresh=True)
            except Exception:  # noqa: BLE001 - 预热失败不影响任何功能
                pass

    threading.Thread(target=_worker, daemon=True).start()
    return targets
