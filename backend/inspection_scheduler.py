"""自动巡检调度：后台线程按间隔触发全局巡检。

规则（对齐 settings.json 配置）：

- `auto_inspection_enabled`：总开关（默认 true），可在巡检中心切换；
- `inspection_interval_hours`：间隔（默认 2 小时）；
- 每次检查「当前时间 - 上次巡检时间 >= 间隔」即触发一轮**全局巡检**，
  也就是"距离上次巡检超过两小时就启动巡检"。

巡检本身在独立线程里跑（`inspection_runner.run_inspection`），
用 `_state.running` 保证同一时间只有一轮自动巡检；
巡检结束后由 inspection_runner 负责静默作废并预热集群快照缓存。
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from checks_store import list_runs
from config import load_settings, save_settings

CHECK_INTERVAL_SECONDS = 60  # 调度器轮询间隔
_state: Dict[str, Any] = {
    "running": False,
    "report_running": False,
    "last_error": None,
    "last_finished_at": None,
    "last_triggered_at": None,
    "last_report_at": None,
    "last_report_error": None,
    "started": False,
}
_lock = threading.Lock()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def last_inspection_time() -> Optional[datetime]:
    runs = list_runs()
    return _parse_ts(runs[0].get("checked_at")) if runs else None


def _due() -> bool:
    settings = load_settings()
    if not settings.get("auto_inspection_enabled", True):
        return False
    try:
        interval = float(settings.get("inspection_interval_hours", 2) or 2)
    except (TypeError, ValueError):
        interval = 2.0
    last = last_inspection_time()
    if last is None:
        return True  # 从未巡检过：立即来一轮
    return datetime.now() - last >= timedelta(hours=interval)


def _run_auto_inspection() -> None:
    from inspection_runner import run_inspection

    try:
        summary = run_inspection()
        _state["last_error"] = None
        print(
            "[auto-inspection] 完成：检查 {inspected} 项，更新 {updated} 项"
            f"（失败批次 {len(summary.get('failed_batches') or [])}）".format(**summary)
        )
    except Exception as e:  # noqa: BLE001 - 自动巡检失败不影响服务
        _state["last_error"] = str(e)
        print(f"[auto-inspection] 失败：{e}")
    finally:
        _state["running"] = False
        _state["last_finished_at"] = datetime.now().isoformat(timespec="seconds")


def _report_due() -> bool:
    """报告是否到期：开启且距上次生成 ≥ report_interval_hours（默认 24 小时）。"""
    settings = load_settings()
    if not settings.get("auto_report_enabled", True):
        return False
    try:
        interval = float(settings.get("report_interval_hours", 24) or 24)
    except (TypeError, ValueError):
        interval = 24.0
    try:
        from report_store import list_reports

        reports = list_reports()
    except Exception:  # noqa: BLE001 - 报告模块不可用时不触发
        return False
    if not reports:
        return True  # 从未生成过：先来一轮
    last = _parse_ts(reports[0].get("generated_at"))
    if last is None:
        return True
    return datetime.now() - last >= timedelta(hours=interval)


def _run_auto_reports() -> None:
    """为每个项目生成一份日报（单个项目失败不影响其他项目）。"""
    from report_builder import build_report
    from report_store import save_report
    from storage import load_db

    try:
        db = load_db()
        created, failed = 0, []
        for project in db.get("projects", []):
            ref = str(project.get("project_id") or project.get("name") or "")
            if not ref:
                continue
            try:
                result = build_report(ref, window_days=7)
                save_report(result["report"], result["markdown"], result["charts"])
                created += 1
            except Exception as e:  # noqa: BLE001
                failed.append(f"{project.get('name')}: {e}")
        _state["last_report_at"] = datetime.now().isoformat(timespec="seconds")
        _state["last_report_error"] = failed[0] if failed else None
        print(f"[auto-report] 生成 {created} 份项目报告（失败 {len(failed)}）")
    except Exception as e:  # noqa: BLE001
        _state["last_report_error"] = str(e)
        print(f"[auto-report] 失败：{e}")
    finally:
        _state["report_running"] = False


def _loop() -> None:
    while True:
        try:
            if not _state["running"] and _due():
                _state["running"] = True
                _state["last_triggered_at"] = datetime.now().isoformat(timespec="seconds")
                threading.Thread(target=_run_auto_inspection, daemon=True).start()
            # 报告自动生成：与巡检共用同一个调度线程，默认每 24 小时一轮
            if not _state["report_running"] and _report_due():
                _state["report_running"] = True
                threading.Thread(target=_run_auto_reports, daemon=True).start()
        except Exception as e:  # noqa: BLE001 - 调度器自身不能挂
            _state["last_error"] = str(e)
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_scheduler() -> None:
    """启动调度线程（幂等）。"""
    with _lock:
        if _state["started"]:
            return
        _state["started"] = True
        threading.Thread(target=_loop, daemon=True).start()
        print(f"[auto-inspection] 调度器已启动（每 {CHECK_INTERVAL_SECONDS}s 检查一次）")


def scheduler_status() -> Dict[str, Any]:
    """调度状态（供 /api/inspections/meta 展示）。"""
    settings = load_settings()
    enabled = bool(settings.get("auto_inspection_enabled", True))
    try:
        interval = float(settings.get("inspection_interval_hours", 2) or 2)
    except (TypeError, ValueError):
        interval = 2.0
    last = last_inspection_time()
    next_run = None
    if last is not None:
        next_run = (last + timedelta(hours=interval)).strftime("%Y-%m-%d %H:%M")
    report_enabled = bool(settings.get("auto_report_enabled", True))
    try:
        report_interval = float(settings.get("report_interval_hours", 24) or 24)
    except (TypeError, ValueError):
        report_interval = 24.0
    try:
        from report_store import list_reports

        reports = list_reports()
        last_report = reports[0].get("generated_at") if reports else None
    except Exception:  # noqa: BLE001
        last_report = None
    next_report = None
    last_report_dt = _parse_ts(last_report)
    if last_report_dt is not None:
        next_report = (last_report_dt + timedelta(hours=report_interval)).strftime(
            "%Y-%m-%d %H:%M"
        )
    return {
        "enabled": enabled,
        "interval_hours": interval,
        "scheduler_started": bool(_state["started"]),
        "running": bool(_state["running"]),
        "last_run_at": last.strftime("%Y-%m-%dT%H:%M:%S") if last else None,
        "next_run_at": next_run,
        "last_triggered_at": _state["last_triggered_at"],
        "last_finished_at": _state["last_finished_at"],
        "last_error": _state["last_error"],
        "report_enabled": report_enabled,
        "report_interval_hours": report_interval,
        "report_running": bool(_state["report_running"]),
        "last_report_at": last_report,
        "next_report_at": next_report,
        "last_report_error": _state["last_report_error"],
    }


def update_schedule(payload: Dict[str, Any]) -> Dict[str, Any]:
    """修改自动巡检开关 / 间隔（写入 settings.json）。"""
    patch: Dict[str, Any] = {}
    if "enabled" in payload and payload.get("enabled") is not None:
        patch["auto_inspection_enabled"] = bool(payload.get("enabled"))
    if payload.get("interval_hours") is not None:
        try:
            hours = float(payload["interval_hours"])
        except (TypeError, ValueError):
            raise ValueError("interval_hours 必须是数字")
        if hours < 0.1 or hours > 168:
            raise ValueError("interval_hours 需在 0.1 ~ 168 之间")
        patch["inspection_interval_hours"] = hours
    if "report_enabled" in payload and payload.get("report_enabled") is not None:
        patch["auto_report_enabled"] = bool(payload.get("report_enabled"))
    if payload.get("report_interval_hours") is not None:
        try:
            report_hours = float(payload["report_interval_hours"])
        except (TypeError, ValueError):
            raise ValueError("report_interval_hours 必须是数字")
        if report_hours < 1 or report_hours > 720:
            raise ValueError("report_interval_hours 需在 1 ~ 720 之间")
        patch["report_interval_hours"] = report_hours
    if patch:
        save_settings(patch)
    return scheduler_status()
