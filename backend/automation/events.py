"""触发层：事件总线（巡检完成事件 + 定时触发信号）。

巡检**只发事件、不调动作**（坑 #1：SSH 抖动会连锁失败）；事件由独立线程消费，
规则命中后交给调度层入队执行。
"""

from __future__ import annotations

import queue
import threading
from typing import Any, Dict, List

from storage import load_db

from automation import actions, audit, rules, scheduler, store

_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_THREADS: List[threading.Thread] = []
_STOP = threading.Event()


def publish(event: Dict[str, Any]) -> None:
    """投递事件（非阻塞，立即返回；调用方不等待规则匹配与动作执行）。"""
    try:
        _QUEUE.put(dict(event))
    except Exception:  # noqa: BLE001 - 事件投递失败不影响调用方
        pass


def publish_inspection_events(run_id: str, entries: List[Dict[str, Any]]) -> None:
    """巡检完成后按任务发事件（负载含 task_id / status / converged / …）。"""
    for entry in entries or []:
        task_id = str(entry.get("task_id") or "")
        if not task_id:
            continue
        status = str(entry.get("status") or entry.get("new_status") or "")
        publish(
            {
                "type": "inspection_completed",
                "run_id": run_id,
                "task_id": task_id,
                "status": status,
                "converged": status == "completed",
                "task_type": entry.get("task_type") or entry.get("type"),
                "group_id": (entry.get("group") or {}).get("group_id"),
                "source_dir": entry.get("current_output") or entry.get("source_dir"),
            }
        )


def _match_rules_for_task(rule_iter, project: Dict[str, Any], task: Dict[str, Any], event: Dict[str, Any]) -> int:
    """对单个任务跑规则匹配：命中就投递动作，未命中记 skipped（带原因）。"""
    submitted = 0
    for rule in rule_iter:
        ok, reason, _ctx = rules.match_task(rule, project, task)
        if not ok:
            audit.write(
                action=str(rule.get("action") or ""),
                status="skipped",
                task_id=str(task.get("task_id") or ""),
                project=str(project.get("name") or ""),
                trigger=str(event.get("type") or ""),
                trigger_id=str(event.get("run_id") or event.get("schedule_id") or ""),
                rule_id=str(rule.get("id") or ""),
                reason=reason,
            )
            continue
        submitted += 1
        scheduler.submit(
            str(rule.get("action") or ""),
            task_id=str(task.get("task_id") or ""),
            params=rule.get("params") or {},
            trigger=str(event.get("type") or ""),
            trigger_id=str(event.get("run_id") or event.get("schedule_id") or ""),
            rule_id=str(rule.get("id") or ""),
            guard=rule.get("guard") or {},
            wait=False,
            project_name=str(project.get("name") or ""),
        )
    return submitted


def _handle(event: Dict[str, Any]) -> None:
    event_type = str(event.get("type") or "")
    rules_now = rules.enabled_rules()
    db = load_db()

    if event_type == "inspection_completed":
        task_id = str(event.get("task_id") or "")
        for project in db.get("projects", []):
            for task in project.get("tasks", []):
                if str(task.get("task_id")) != task_id:
                    continue
                triggered = [
                    r for r in rules_now if rules.trigger_type(r) == "inspection_completed"
                ]
                _match_rules_for_task(triggered, project, task, event)
                return
        return

    if event_type == "schedule":
        rule_id = str(event.get("rule_id") or "")
        targets = [
            r
            for r in rules_now
            if rules.trigger_type(r) == "schedule" and (not rule_id or str(r.get("id")) == rule_id)
        ]
        if not targets:
            return
        scope = event.get("scope") or (targets[0].get("trigger") or {}).get("scope") or "all"
        for project, task in rules.resolve_scope(db, scope):
            _match_rules_for_task(targets, project, task, event)


def _loop() -> None:
    while not _STOP.is_set():
        try:
            event = _QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _handle(event)
        except Exception as e:  # noqa: BLE001 - 单次事件失败不影响后续
            audit.write(
                action="automation.event",
                status="failed",
                task_id=str(event.get("task_id") or ""),
                trigger=str(event.get("type") or ""),
                trigger_id=str(event.get("run_id") or event.get("schedule_id") or ""),
                reason=f"事件处理失败：{e}",
            )


def start() -> None:
    if _THREADS:
        return
    _STOP.clear()
    thread = threading.Thread(target=_loop, name="automation-events", daemon=True)
    thread.start()
    _THREADS.append(thread)


def stop() -> None:
    _STOP.set()


def queue_size() -> int:
    return _QUEUE.qsize()
