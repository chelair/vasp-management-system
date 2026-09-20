"""调度层：动作队列、并发控制、执行与审计。

并发控制三条（都写进 `data/action_history.json`）：
1. **任务级互斥锁**：`data/locks/task_<task_id>.lock`（fcntl 非阻塞，忙则 blocked）；
2. **冷却期**：同 `task+action` 在 `guard.cooldown_seconds` 内不重复；
3. **执行上限**：同 `task+action` 累计次数超过 `guard.max_runs_per_task` 拒绝。

另外：幂等指纹去重、用户手动接管跳过、全局暂停立即生效、`dry_run` 只跑 preflight。
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from config import DATA_DIR

from automation import actions, audit, cron, rules, store

MANUAL_HOLD_SECONDS = 300          # 用户手动操作过 → 5 分钟内不让自动化碰
SHORT_WAIT_SECONDS = 150           # 短动作等待上限（超时按 running 返回）
TICK_SECONDS = int(os.environ.get("AUTOMATION_TICK_SECONDS", "20"))  # 定时检查间隔
WORKER_COUNT = 2

_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()
_WAITERS: Dict[str, Dict[str, Any]] = {}
_WAITERS_LOCK = threading.RLock()
_STOP = threading.Event()
_THREADS: list = []
_TASK_LOCKS: Dict[str, Any] = {}
_TASK_LOCKS_LOCK = threading.RLock()
_AUDIT_FILE = Path(DATA_DIR) / "audit" / "actions.jsonl"


def _fingerprint(task_id: str, action: str, params: Dict[str, Any]) -> str:
    payload = json.dumps(
        {"task_id": task_id, "action": action, "params": params or {}},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _manual_takeover(task_id: str) -> Optional[str]:
    """最近是否有"用户手动操作"该任务（审计里有非 automation 的记录）。"""
    if not _AUDIT_FILE.is_file():
        return None
    try:
        with open(_AUDIT_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-400:]
    except OSError:
        return None
    cutoff = datetime.now().astimezone() - timedelta(seconds=MANUAL_HOLD_SECONDS)
    for line in reversed(lines):
        line = line.strip()
        if not line or str(task_id) not in line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(record.get("task_id") or "") != str(task_id):
            continue
        if record.get("automation"):
            continue
        # 没有真实用户名 = 后台/系统写入（例如提交成功后的自动同步），不算"用户手动接管"
        if str(record.get("username") or "").strip() in ("", "-", "automation"):
            continue
        if str(record.get("command") or "").startswith("auth."):
            continue
        try:
            at = datetime.fromisoformat(str(record.get("at") or ""))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.astimezone()
        if at >= cutoff:
            return f"{record.get('username') or '用户'} 在 {record.get('at')} 手动执行过 {record.get('command')}"
    return None


def _task_lock_path(task_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_@" else "_" for ch in str(task_id))
    return Path(DATA_DIR) / "locks" / f"task_{safe}.lock"


class _TaskBusy(Exception):
    pass


def _acquire_task_lock(task_id: str):
    """任务级互斥（进程内 + 文件锁）；忙则抛 _TaskBusy。"""
    with _TASK_LOCKS_LOCK:
        local = _TASK_LOCKS.get(str(task_id))
        if local is None:
            local = threading.Lock()
            _TASK_LOCKS[str(task_id)] = local
    if not local.acquire(blocking=False):
        raise _TaskBusy("任务正在执行其他动作")
    handle = None
    try:
        path = _task_lock_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # pragma: no cover - 非 POSIX
            pass
        except OSError:
            raise _TaskBusy("任务正在被其他进程执行") from None
    except _TaskBusy:
        local.release()
        if handle is not None:
            handle.close()
        raise
    except Exception:
        local.release()
        if handle is not None:
            handle.close()
        raise
    return local, handle


def _release_task_lock(lock_tuple) -> None:
    local, handle = lock_tuple
    try:
        if handle is not None:
            handle.close()
    finally:
        local.release()


def _remember_run(record: Dict[str, Any]) -> None:
    def mutate(runs: Dict[str, Any]) -> None:
        items = [r for r in runs.get("runs", []) if r.get("run_id") != record["run_id"]]
        items.append(record)
        runs["runs"] = items[-200:]

    store.update_runs(mutate)


def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    for record in reversed(store.load_runs().get("runs", [])):
        if str(record.get("run_id")) == str(run_id):
            return record
    return None


def list_runs(limit: int = 50) -> list:
    runs = list(store.load_runs().get("runs", []))
    runs.reverse()
    return runs[:limit]


def _blocked(
    action: str,
    task_id: str,
    reason: str,
    *,
    trigger: str = "",
    trigger_id: str = "",
    rule_id: str = "",
    project: str = "",
    action_name: str = "",
) -> Dict[str, Any]:
    record = audit.write(
        action=action_name or action,
        status="blocked",
        task_id=task_id,
        project=project,
        trigger=trigger,
        trigger_id=trigger_id,
        rule_id=rule_id,
        reason=reason,
    )
    return {"status": "blocked", "reason": reason, "audit_id": record.get("at"), "action": action}


def submit(
    action_name: str,
    *,
    task_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    trigger: str = "manual",
    trigger_id: str = "",
    rule_id: str = "",
    dry_run: Optional[bool] = None,
    idempotency_key: Optional[str] = None,
    guard: Optional[Dict[str, Any]] = None,
    wait: bool = True,
    project_name: str = "",
) -> Dict[str, Any]:
    """统一入口：前置检查 → （dry_run 只跑 preflight）→ 入队执行。"""
    params = dict(params or {})
    guard = dict(guard or {})
    settings = store.load_settings()

    try:
        spec = actions.get(action_name)
    except KeyError as e:
        return _blocked(action_name, task_id or "", str(e), trigger=trigger, trigger_id=trigger_id)

    if spec.requires_task and not task_id:
        return _blocked(action_name, "", "缺少 task_id", trigger=trigger, trigger_id=trigger_id, rule_id=rule_id)

    if not settings.get("enabled", True):
        return _blocked(
            action_name, task_id or "",
            "全局自动化已暂停（automation.json enabled=false）",
            trigger=trigger, trigger_id=trigger_id, rule_id=rule_id,
        )

    if rule_id and rule_id in {str(x) for x in settings.get("disabled_rules") or []}:
        return _blocked(
            action_name, task_id or "", f"规则 {rule_id} 已被熔断禁用",
            trigger=trigger, trigger_id=trigger_id, rule_id=rule_id,
        )

    if task_id:
        takeover = _manual_takeover(task_id)
        if takeover:
            return _blocked(
                action_name, task_id, f"近期有手动操作，自动跳过（{takeover}）",
                trigger=trigger, trigger_id=trigger_id, rule_id=rule_id, project=project_name,
            )

    history = store.load_history()
    cooldown_seconds = int(guard.get("cooldown_seconds") or 0)
    if task_id and cooldown_seconds > 0:
        last = history["cooldowns"].get(f"{task_id}|{action_name}")
        if last:
            try:
                remaining = (
                    datetime.fromisoformat(last)
                    + timedelta(seconds=cooldown_seconds)
                    - datetime.now().astimezone()
                ).total_seconds()
            except ValueError:
                remaining = 0
            if remaining > 0:
                return _blocked(
                    action_name, task_id,
                    f"冷却中，还有 {int(remaining)} 秒（cooldown={cooldown_seconds}s）",
                    trigger=trigger, trigger_id=trigger_id, rule_id=rule_id, project=project_name,
                )

    max_runs = int(guard.get("max_runs_per_task") or 0)
    if task_id and max_runs > 0:
        used = int(history["counts"].get(f"{task_id}|{action_name}") or 0)
        if used >= max_runs:
            return _blocked(
                action_name, task_id, f"已达执行上限（{used}/{max_runs}）",
                trigger=trigger, trigger_id=trigger_id, rule_id=rule_id, project=project_name,
            )

    fingerprint = idempotency_key or (f"{task_id}|{action_name}" if task_id else "")
    if fingerprint:
        seen = history["fingerprints"].get(fingerprint)
        if seen and seen.get("status") in ("success", "running", "dry_run"):
            return _blocked(
                action_name, task_id or "",
                f"重复请求（幂等键命中，上次 {seen.get('at')} {seen.get('status')}）",
                trigger=trigger, trigger_id=trigger_id, rule_id=rule_id, project=project_name,
            )

    effective_dry = settings.get("dry_run", False) if dry_run is None else bool(dry_run)
    if effective_dry:
        try:
            preflight = spec.preflight(str(task_id), params) if spec.requires_task else {}
        except Exception as e:  # noqa: BLE001 - preflight 失败本身就是 dry_run 结果
            record = audit.write(
                action=action_name, status="dry_run", task_id=task_id or "", project=project_name,
                trigger=trigger, trigger_id=trigger_id, rule_id=rule_id,
                reason=f"preflight 未通过：{e}", details={"preflight_ok": False},
            )
            return {
                "status": "dry_run",
                "preflight_ok": False,
                "reason": str(e),
                "will_do": None,
                "audit_id": record.get("at"),
            }
        record = audit.write(
            action=action_name, status="dry_run", task_id=task_id or "", project=project_name,
            trigger=trigger, trigger_id=trigger_id, rule_id=rule_id,
            reason="dry_run 通过（未执行、未写状态）", details={"preflight": preflight},
        )
        return {
            "status": "dry_run",
            "preflight_ok": True,
            "preflight": preflight,
            "will_do": preflight.get("will_do"),
            "audit_id": record.get("at"),
        }

    job = {
        "action": action_name,
        "task_id": task_id or "",
        "params": params,
        "trigger": trigger,
        "trigger_id": trigger_id,
        "rule_id": rule_id,
        "guard": guard,
        "fingerprint": fingerprint,
        "run_id": store.new_run_id(),
        "project": project_name,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if spec.long_running:
        _remember_run(
            {
                "run_id": job["run_id"],
                "action": action_name,
                "task_id": job["task_id"],
                "trigger": trigger,
                "trigger_id": trigger_id,
                "status": "running",
                "started_at": job["started_at"],
                "finished_at": None,
                "result": None,
                "reason": "",
            }
        )
        if fingerprint:
            store.update_history(
                lambda h: h["fingerprints"].update(
                    {fingerprint: {"at": job["started_at"], "run_id": job["run_id"], "status": "running"}}
                )
            )

    if wait and not spec.long_running:
        waiter = threading.Event()
        with _WAITERS_LOCK:
            _WAITERS[job["run_id"]] = {"event": waiter, "result": None}
        _QUEUE.put(job)
        waiter.wait(SHORT_WAIT_SECONDS)
        with _WAITERS_LOCK:
            outcome = _WAITERS.pop(job["run_id"], None)
        if outcome and outcome.get("result"):
            return outcome["result"]
        return {"status": "running", "run_id": job["run_id"], "action": action_name}

    _QUEUE.put(job)
    if spec.long_running:
        return {"status": "running", "run_id": job["run_id"], "action": action_name}
    return {"status": "queued", "run_id": job["run_id"], "action": action_name}


def _finish_run(job: Dict[str, Any], status: str, result: Any, reason: str = "") -> None:
    _remember_run(
        {
            "run_id": job["run_id"],
            "action": job["action"],
            "task_id": job["task_id"],
            "trigger": job.get("trigger", ""),
            "trigger_id": job.get("trigger_id", ""),
            "status": status,
            "started_at": job.get("started_at")
            or datetime.now().astimezone().isoformat(timespec="seconds"),
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "result": result,
            "reason": reason,
        }
    )


def _record_history(job: Dict[str, Any], status: str, reason: str = "") -> None:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    task_id = job.get("task_id") or ""
    action_name = job["action"]
    key = f"{task_id}|{action_name}"

    def mutate(history: Dict[str, Any]) -> None:
        if status == "success":
            history["cooldowns"][key] = now
            history["counts"][key] = int(history["counts"].get(key) or 0) + 1
        history["last_results"][key] = {"at": now, "status": status, "reason": reason}
        if job.get("fingerprint"):
            history["fingerprints"][job["fingerprint"]] = {
                "at": now,
                "run_id": job["run_id"],
                "status": status,
            }
        rule_id = job.get("rule_id")
        if rule_id:
            if status in ("success", "skipped"):
                history["rule_failures"][rule_id] = 0
            elif status == "failed":
                history["rule_failures"][rule_id] = int(history["rule_failures"].get(rule_id) or 0) + 1

    store.update_history(mutate)


def _maybe_disable_rule(job: Dict[str, Any]) -> None:
    """失败熔断：同一规则连续失败 N 次自动进 disabled_rules（审计留痕）。"""
    rule_id = job.get("rule_id")
    if not rule_id:
        return
    settings = store.load_settings()
    threshold = int(settings.get("failure_threshold") or 3)
    failures = int(store.load_history()["rule_failures"].get(rule_id) or 0)
    if failures < threshold:
        return
    disabled = {str(x) for x in settings.get("disabled_rules") or []}
    if rule_id in disabled:
        return
    disabled.add(rule_id)
    store.save_settings({"disabled_rules": sorted(disabled)})
    audit.write(
        action=job["action"],
        status="blocked",
        task_id=job.get("task_id") or "",
        trigger=job.get("trigger", ""),
        trigger_id=job.get("trigger_id", ""),
        rule_id=rule_id,
        reason=f"规则连续失败 {failures} 次，已自动禁用（failure_threshold={threshold}）",
    )


def _execute(job: Dict[str, Any]) -> Dict[str, Any]:
    spec = actions.get(job["action"])
    started = time.time()
    task_id = job.get("task_id") or ""
    try:
        preflight = spec.preflight(task_id, job.get("params") or {}) if spec.requires_task else {}
    except Exception as e:  # noqa: BLE001 - 执行时复检失败（远端状态可能已变）
        elapsed = int((time.time() - started) * 1000)
        record = audit.write(
            action=job["action"], status="failed", task_id=task_id,
            project=job.get("project", ""), trigger=job.get("trigger", ""),
            trigger_id=job.get("trigger_id", ""), rule_id=job.get("rule_id", ""),
            run_id=job["run_id"], reason=f"preflight：{e}", elapsed_ms=elapsed,
        )
        _record_history(job, "failed", str(e))
        _maybe_disable_rule(job)
        return {"status": "failed", "reason": str(e), "audit_id": record.get("at"), "run_id": job["run_id"]}

    try:
        result = spec.execute(task_id, job.get("params") or {})
    except Exception as e:  # noqa: BLE001 - 执行失败
        elapsed = int((time.time() - started) * 1000)
        record = audit.write(
            action=job["action"], status="failed", task_id=task_id,
            project=job.get("project", ""), trigger=job.get("trigger", ""),
            trigger_id=job.get("trigger_id", ""), rule_id=job.get("rule_id", ""),
            run_id=job["run_id"], reason=str(e), elapsed_ms=elapsed,
        )
        _record_history(job, "failed", str(e))
        _maybe_disable_rule(job)
        return {"status": "failed", "reason": str(e), "audit_id": record.get("at"), "run_id": job["run_id"]}

    business_action = str((result or {}).get("action") or "")
    status = "success"
    reason = ""
    if job["action"] == "task.continuation" and business_action and business_action != "created":
        # 续算的业务语义：只有 action=created 才算真的创建成功（坑 #7）
        status = "skipped"
        reason = f"业务判断未创建（action={business_action}）"
    elapsed = int((time.time() - started) * 1000)
    record = audit.write(
        action=job["action"], status=status, task_id=task_id,
        project=job.get("project", ""), trigger=job.get("trigger", ""),
        trigger_id=job.get("trigger_id", ""), rule_id=job.get("rule_id", ""),
        run_id=job["run_id"], reason=reason or "执行完成",
        elapsed_ms=elapsed, details={"preflight": preflight, "result": result},
    )
    _record_history(job, status, reason)
    return {
        "status": status,
        "result": result,
        "reason": reason,
        "audit_id": record.get("at"),
        "run_id": job["run_id"],
    }


def _worker_loop() -> None:
    while not _STOP.is_set():
        try:
            job = _QUEUE.get(timeout=0.5)
        except queue.Empty:
            continue
        lock_tuple = None
        try:
            if job["task_id"]:
                lock_tuple = _acquire_task_lock(job["task_id"])
            outcome = _execute(job)
        except _TaskBusy as e:
            outcome = _blocked(
                job["action"], job["task_id"], str(e),
                trigger=job.get("trigger", ""), trigger_id=job.get("trigger_id", ""),
                rule_id=job.get("rule_id", ""), project=job.get("project", ""),
            )
        except Exception as e:  # noqa: BLE001 - 兜底，避免工作线程退出
            outcome = {
                "status": "failed",
                "reason": f"调度异常：{e}",
                "run_id": job.get("run_id"),
            }
        finally:
            if lock_tuple is not None:
                _release_task_lock(lock_tuple)

        spec = actions.ACTIONS.get(job["action"])
        if spec and spec.long_running:
            _finish_run(
                job,
                str(outcome.get("status") or "failed"),
                outcome.get("result"),
                str(outcome.get("reason") or ""),
            )
        with _WAITERS_LOCK:
            waiter = _WAITERS.get(job["run_id"])
            if waiter:
                waiter["result"] = outcome
                waiter["event"].set()


def _tick_schedules() -> None:
    settings = store.load_settings()
    if not settings.get("enabled", True) or not settings.get("schedules_enabled", True):
        return
    now = datetime.now()
    history = store.load_history()
    changed = False
    for schedule in rules.schedules():
        if not schedule.get("enabled"):
            continue
        schedule_id = str(schedule["id"])
        cron_expr = str(schedule.get("cron") or "")
        mode = str(schedule.get("mode") or ("cron" if cron_expr else "after"))
        # ---- 模式二：`xx 秒后执行一次`（一次性，触发后不自动重排）----
        if mode == "after":
            try:
                delay = int(schedule.get("after_seconds") or 0)
            except (TypeError, ValueError):
                delay = 0
            if delay <= 0:
                continue
            next_text = str(history["next_runs"].get(schedule_id) or "")
            fired = str(history["last_fired"].get(schedule_id) or "")
            if not next_text:
                if fired:
                    continue  # 已经执行过一次，等"重新计时"
                history["next_runs"][schedule_id] = (
                    now + timedelta(seconds=delay)
                ).astimezone().isoformat(timespec="seconds")
                changed = True
                continue
            try:
                due_at = datetime.fromisoformat(next_text)
            except ValueError:
                continue
            if now < due_at:
                continue
            from automation import events

            events.publish(
                {
                    "type": "schedule",
                    "schedule_id": schedule_id,
                    "rule_id": schedule_id,
                    "scope": schedule.get("scope") or "all",
                    "mode": "after",
                    "fired_at": now.astimezone().isoformat(timespec="seconds"),
                }
            )
            history["next_runs"].pop(schedule_id, None)
            history["next_crons"].pop(schedule_id, None)
            history["last_fired"][schedule_id] = now.isoformat(timespec="seconds")
            changed = True
            continue

        # ---- 模式一：cron（周期）----
        try:
            next_dt = datetime.fromisoformat(str(history["next_runs"].get(schedule_id) or ""))
        except ValueError:
            next_dt = None
        # cron 改过 → 立即按新表达式重算（验收：改配置无需重启服务）
        if str(history["next_crons"].get(schedule_id) or "") != cron_expr:
            try:
                history["next_runs"][schedule_id] = cron.next_after(
                    cron_expr, now
                ).isoformat(timespec="seconds")
                history["next_crons"][schedule_id] = cron_expr
                changed = True
            except cron.CronError:
                continue
            continue
        if next_dt is None:
            try:
                history["next_runs"][schedule_id] = cron.next_after(
                    schedule["cron"], now
                ).isoformat(timespec="seconds")
                history["next_crons"][schedule_id] = cron_expr
                changed = True
            except cron.CronError:
                continue
            continue
        if now >= next_dt:
            try:
                history["next_runs"][schedule_id] = cron.next_after(
                    schedule["cron"], now
                ).isoformat(timespec="seconds")
                history["next_crons"][schedule_id] = cron_expr
            except cron.CronError:
                continue
            changed = True
            from automation import events

            events.publish(
                {
                    "type": "schedule",
                    "schedule_id": schedule_id,
                    "rule_id": schedule_id,
                    "scope": schedule.get("scope") or "all",
                    "cron": schedule.get("cron"),
                    "fired_at": now.astimezone().isoformat(timespec="seconds"),
                }
            )
    if changed:
        store.save_history(history)


def _schedule_loop() -> None:
    while not _STOP.is_set():
        try:
            _tick_schedules()
        except Exception as e:  # noqa: BLE001 - 定时线程不允许退出
            audit.write(
                action="automation.schedule", status="failed",
                reason=f"定时检查失败：{e}", trigger="schedule",
            )
        _STOP.wait(TICK_SECONDS)


def next_run_of(schedule_id: str) -> Optional[str]:
    return store.load_history()["next_runs"].get(str(schedule_id))


def prime_schedule(
    schedule_id: str,
    cron_expr: Optional[str] = None,
    after_seconds: Optional[int] = None,
) -> Optional[str]:
    """新建/修改定时规则后立刻算出下次触发时间（"xx 秒后一次"同时清除已执行标记）。"""
    if after_seconds:
        # 与 cron 分支 / `_tick_schedules()` 的 datetime.now() 保持同一表示（本地 naive），
        # 否则 naive 与 aware 比较会抛 TypeError
        next_at = (datetime.now() + timedelta(seconds=int(after_seconds))).isoformat(
            timespec="seconds"
        )
    else:
        try:
            next_at = cron.next_after(str(cron_expr or "")).isoformat(timespec="seconds")
        except cron.CronError:
            return None

    def mutate(history: Dict[str, Any]) -> None:
        history["next_runs"][str(schedule_id)] = next_at
        history["next_crons"][str(schedule_id)] = str(cron_expr or "")
        history["last_fired"].pop(str(schedule_id), None)

    store.update_history(mutate)
    return next_at


def start() -> None:
    """启动工作线程与定时线程（幂等：重复调用只启动一次）。"""
    if _THREADS:
        return
    _STOP.clear()
    for _ in range(WORKER_COUNT):
        thread = threading.Thread(target=_worker_loop, name="automation-worker", daemon=True)
        thread.start()
        _THREADS.append(thread)
    schedule_thread = threading.Thread(target=_schedule_loop, name="automation-cron", daemon=True)
    schedule_thread.start()
    _THREADS.append(schedule_thread)


def stop() -> None:
    _STOP.set()
