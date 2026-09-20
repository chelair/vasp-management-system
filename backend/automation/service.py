"""自动化系统启停（挂 FastAPI lifespan）。"""

from __future__ import annotations

from datetime import datetime

from automation import audit, events, scheduler, store

_STARTED = False


def _mark_interrupted_runs() -> None:
    """进程重启后，把遗留的 running 运行记录标记为 interrupted（避免永远 running）。"""
    runs = store.load_runs()
    changed = False
    for record in runs.get("runs", []):
        if record.get("status") == "running":
            record["status"] = "failed"
            record["reason"] = "服务重启导致中断"
            record["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            changed = True
    if changed:
        store.save_runs(runs)


def start_automation() -> None:
    """启动自动化：初始化默认配置/规则 → 标记中断运行 → 起事件与调度线程。"""
    global _STARTED
    if _STARTED:
        return
    try:
        store.ensure_defaults()
        _mark_interrupted_runs()
        scheduler.start()
        events.start()
        _STARTED = True
        settings = store.load_settings()
        print(
            f"[automation] 已启动（enabled={settings.get('enabled')} "
            f"dry_run={settings.get('dry_run')} "
            f"schedules={settings.get('schedules_enabled')}，"
            f"规则 {len(store.load_rules())} 条）",
            flush=True,
        )
    except Exception as e:  # noqa: BLE001 - 自动化启动失败不影响主服务
        print(f"[automation] 启动失败：{e}", flush=True)
        audit.write(action="automation.start", status="failed", reason=str(e))


def stop_automation() -> None:
    events.stop()
    scheduler.stop()
