"""自动化与统一动作接口（v0.9.6）。

| 接口 | 说明 |
| --- | --- |
| `GET /api/actions` | 动作目录（名称/说明/是否长动作/参数提示） |
| `POST /api/actions/{action_name}` | 统一动作入口：`{task_id?, params, dry_run?, idempotency_key?}` |
| `GET /api/actions/runs/{run_id}` | 长动作轮询（running/done/failed + 结果） |
| `GET /api/automation/status` | 全局开关 + 定时任务（含下次触发）+ 队列/规则统计 |
| `GET/PUT /api/automation/settings` | 全局暂停 / 全局 dry_run / 定时总开关（改完立即生效） |
| `GET /api/automation/rules` · `PUT /api/automation/rules/{id}` | 规则列表 / 启用开关 |
| `POST /api/automation/rules/{id}/run` | 立即触发一条**定时**规则（不等 cron） |
| `GET /api/automation/decisions` | 决策与执行日志（五态审计） |
| `GET /api/automation/runs` | 动作运行记录（含长动作最终结果） |
| `POST /api/automation/reload` | 显式重载配置（其实每次现读，改完即生效） |

权限：自动化是**全局**能力（会提交作业、改远端目录），全部接口 **仅 admin**。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import permissions
from envelope import fail, ok
from automation import actions, audit, cron, events, rules, scheduler, store
from storage import load_db

router = APIRouter(tags=["actions"])

RULE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: 规则里允许出现的字段（多写/拼错的字段直接 400，避免"界面上填了却没生效"）
RULE_FIELDS = {
    "id",
    "enabled",
    "description",
    "trigger",
    "condition",
    "action",
    "guard",
    "follow_up_action",
}

#: 修改（PUT）时允许覆盖的字段
EDITABLE_FIELDS = {
    "enabled",
    "description",
    "trigger",
    "condition",
    "action",
    "guard",
    "follow_up_action",
}


def _require_admin(request: Request) -> None:
    permissions.ensure_admin(
        getattr(request.state, "user", None), "只有管理员可以使用自动化与动作接口"
    )


def _unknown_rule_fields(payload: Dict[str, Any]) -> list:
    """规则里多写 / 拼错的字段（拼错直接报错，避免"界面上填了却没生效"）。"""
    return sorted(
        str(k) for k in payload if str(k) not in RULE_FIELDS and not str(k).startswith("_")
    )


def _validate_rule(rule: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """规则校验（新建/修改共用）：返回 (规范化规则, 错误信息)。"""
    unknown_fields = _unknown_rule_fields(rule)
    if unknown_fields:
        return {}, (
            f"规则里有不支持的字段：{', '.join(unknown_fields)}"
            f"（可用：{', '.join(sorted(RULE_FIELDS))}）"
        )
    rule_id = str(rule.get("id") or "").strip()
    if not RULE_ID_PATTERN.match(rule_id):
        return {}, "规则 id 只能用小写字母、数字、点、下划线、短横线（2-64 位）"
    trigger = dict(rule.get("trigger") or {})
    trigger_type = str(trigger.get("type") or "")
    if trigger_type not in ("inspection_completed", "schedule"):
        return {}, "trigger.type 仅支持 inspection_completed / schedule"
    if trigger_type == "schedule":
        mode = str(trigger.get("mode") or ("cron" if trigger.get("cron") else "after")).strip()
        if mode not in ("cron", "after"):
            return {}, "定时模式仅支持 cron（周期）/ after（N 秒后执行一次）"
        trigger["mode"] = mode
        trigger["scope"] = str(trigger.get("scope") or "all").strip() or "all"
        if mode == "cron":
            cron_expr = str(trigger.get("cron") or "").strip()
            try:
                cron.parse(cron_expr)
            except cron.CronError as e:
                return {}, f"cron 表达式不合法：{e}"
            trigger["cron"] = cron_expr
            trigger.pop("after_seconds", None)
        else:
            try:
                after_seconds = int(trigger.get("after_seconds") or 0)
            except (TypeError, ValueError):
                return {}, "after_seconds 必须是整数秒"
            if after_seconds <= 0:
                return {}, "after_seconds 必须大于 0（多少秒后执行一次）"
            trigger["after_seconds"] = after_seconds
            trigger.pop("cron", None)
    action = str(rule.get("action") or "").strip()
    if action not in actions.ACTIONS:
        return {}, f"未知动作：{action}（可用：{', '.join(actions.ACTIONS)}）"
    follow_up = str(rule.get("follow_up_action") or "").strip()
    if follow_up:
        if follow_up not in actions.ACTIONS:
            return {}, f"后续动作未知：{follow_up}（可用：{', '.join(actions.ACTIONS)}）"
        if follow_up == action:
            return {}, "后续动作不能与主动作相同"
    condition = rule.get("condition") or {}
    if not isinstance(condition, dict):
        return {}, "condition 必须是对象"
    unknown = sorted(str(k) for k in condition if str(k) not in rules.CONDITION_KEYS)
    if unknown:
        return {}, f"condition 里有不支持的字段：{', '.join(unknown)}（可用字段见 API.md）"
    guard = dict(rule.get("guard") or {})
    for key in ("cooldown_seconds", "max_runs_per_task"):
        if key in guard and guard[key] is not None:
            try:
                guard[key] = max(0, int(guard[key]))
            except (TypeError, ValueError):
                return {}, f"guard.{key} 必须是整数"
    return (
        {
            "id": rule_id,
            "enabled": bool(rule.get("enabled", True)),
            "description": str(rule.get("description") or "").strip(),
            "trigger": trigger,
            "condition": condition,
            "action": action,
            "guard": guard,
            "follow_up_action": follow_up or None,
        },
        "",
    )


# ------------------------------------------------------------------ 动作


@router.get("/actions")
def list_actions(request: Request):
    """动作目录：名称、说明、是否长动作、参数提示。"""
    try:
        _require_admin(request)
        return ok("查询成功", {"actions": actions.catalog()})
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取动作目录失败：{e}"))


@router.post("/actions/{action_name}")
def run_action(action_name: str, request: Request, payload: dict = Body(default={})):
    """统一动作入口。

    - `dry_run`：只跑 preflight，返回 `will_do` 与检查结果（不写状态、不建目录）；
    - 短动作同步返回 `{status: done|failed|skipped|blocked, result, audit_id}`；
    - 长动作返回 `{status: running, run_id}`，用 `GET /api/actions/runs/{run_id}` 轮询。
    """
    try:
        _require_admin(request)
        body = payload or {}
        params = dict(body.get("params") or {})
        task_id = body.get("task_id") or params.get("task_id")
        if task_id:
            params.setdefault("task_id", task_id)
        user = getattr(request.state, "user", None) or {}
        result = scheduler.submit(
            action_name,
            task_id=task_id,
            params=params,
            trigger="api",
            trigger_id=str(user.get("username") or ""),
            dry_run=body.get("dry_run"),
            idempotency_key=body.get("idempotency_key"),
            wait=bool(body.get("wait", True)),
            follow_up=body.get("follow_up") or None,
        )
        return ok(result.get("reason") or "动作已处理", result)
    except permissions.PermissionDenied:
        raise
    except KeyError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"动作执行失败：{e}"))


@router.get("/actions/runs/{run_id}")
def action_run(run_id: str, request: Request):
    """长动作轮询：返回 run 记录（含最终 result / reason）。"""
    try:
        _require_admin(request)
        record = scheduler.get_run(run_id)
        if record is None:
            return JSONResponse(status_code=404, content=fail("run 不存在或已被清理"))
        return ok("查询成功", record)
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取运行记录失败：{e}"))


# ------------------------------------------------------------------ 自动化状态


def _schedule_rows() -> list:
    rows = []
    history = store.load_history()
    for schedule in rules.schedules():
        rule = next((r for r in store.load_rules() if str(r.get("id")) == str(schedule["id"])), {})
        rows.append(
            {
                **schedule,
                "trigger": rule.get("trigger") or {},
                "next_run_at": scheduler.next_run_of(schedule["id"]),
                "last_fired_at": history["last_fired"].get(str(schedule["id"])),
                "cron_note": cron.describe(schedule["cron"]) if schedule.get("cron") else "",
            }
        )
    return rows


@router.get("/automation/status")
def automation_status(request: Request):
    """全局开关 + 定时任务 + 队列/规则统计（前端自动化页首屏）。"""
    try:
        _require_admin(request)
        settings = store.load_settings()
        all_rules = store.load_rules()
        history = store.load_history()
        return ok(
            "查询成功",
            {
                "settings": settings,
                "schedules": _schedule_rows(),
                "rules": [
                    {
                        "id": r.get("id"),
                        "enabled": bool(r.get("enabled")),
                        "description": r.get("description"),
                        "trigger": r.get("trigger"),
                        "condition": r.get("condition"),
                        "action": r.get("action"),
                        # ⚠️ 这里是**逐字段**投影：漏字段 = 前端永远看不到它
                        # （v0.9.13 漏了 follow_up_action → 编辑弹窗里勾选项永远回显成未勾）
                        "follow_up_action": r.get("follow_up_action") or None,
                        "guard": r.get("guard"),
                        "failures": int(history["rule_failures"].get(str(r.get("id"))) or 0),
                    }
                    for r in all_rules
                ],
                "counts": {
                    "rules": len(all_rules),
                    "enabled_rules": len([r for r in all_rules if r.get("enabled")]),
                    "queue": events.queue_size(),
                    "runs": len(history["counts"]),
                },
                "last_results": history["last_results"],
            },
        )
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取自动化状态失败：{e}"))


@router.get("/automation/settings")
def get_automation_settings(request: Request):
    try:
        _require_admin(request)
        return ok("查询成功", store.load_settings())
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取自动化设置失败：{e}"))


@router.put("/automation/settings")
def put_automation_settings(request: Request, payload: dict = Body(default={})):
    """改全局开关（enabled=false 立即暂停所有动作；dry_run=true 只演练）。"""
    try:
        _require_admin(request)
        patch = {
            key: payload[key]
            for key in ("enabled", "dry_run", "schedules_enabled", "failure_threshold")
            if key in (payload or {})
        }
        settings = store.save_settings(patch)
        audit.write(
            action="automation.settings",
            status="success",
            trigger="api",
            reason=f"更新全局开关：{patch}",
            details={"settings": settings},
        )
        return ok("设置已保存（立即生效）", settings)
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"保存自动化设置失败：{e}"))


@router.get("/automation/rules")
def list_automation_rules(request: Request):
    try:
        _require_admin(request)
        return ok("查询成功", {"rules": store.load_rules()})
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取规则失败：{e}"))


@router.post("/automation/rules")
def create_automation_rule(request: Request, payload: dict = Body(default={})):
    """新建规则（写 `data/config/rules/<id>.json`，立即生效）。"""
    try:
        _require_admin(request)
        rule, error = _validate_rule(payload or {})
        if error:
            return JSONResponse(status_code=400, content=fail(error))
        try:
            created = store.create_rule(rule)
        except KeyError as e:
            return JSONResponse(status_code=409, content=fail(str(e)))
        rule_trigger = rule.get("trigger") or {}
        if rule_trigger.get("type") == "schedule":
            scheduler.prime_schedule(
                rule["id"],
                rule_trigger.get("cron"),
                rule_trigger.get("after_seconds"),
            )
        audit.write(
            action="automation.rule",
            status="success",
            trigger="api",
            rule_id=rule["id"],
            reason=f"新建规则：{rule.get('description') or rule['id']}",
            details={"rule": created},
        )
        return ok("规则已创建（立即生效）", created)
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"新建规则失败：{e}"))


@router.put("/automation/rules/{rule_id}")
def update_automation_rule(rule_id: str, request: Request, payload: dict = Body(default={})):
    """修改规则：`enabled` 开关，或传完整字段做编辑。

    可覆盖字段见 `EDITABLE_FIELDS`（含 `follow_up_action`；早期版本漏列它，
    导致"执行成功后自动提交作业"勾选后保存不生效）。
    """
    try:
        _require_admin(request)
        existing = store.find_rule(rule_id)
        if existing is None:
            return JSONResponse(status_code=404, content=fail(f"规则不存在：{rule_id}"))
        body = payload or {}
        unknown_fields = _unknown_rule_fields(body)
        if unknown_fields:
            return JSONResponse(
                status_code=400,
                content=fail(
                    f"规则里有不支持的字段：{', '.join(unknown_fields)}"
                    f"（可用：{', '.join(sorted(RULE_FIELDS))}）"
                ),
            )
        editable = EDITABLE_FIELDS
        if not (set(body) & editable):
            return JSONResponse(
                status_code=400,
                content=fail(f"可修改字段：{', '.join(sorted(editable))}"),
            )
        merged = {**{k: v for k, v in existing.items() if not k.startswith("_")}}
        for key in editable:
            if key in body:
                merged[key] = body[key]
        rule, error = _validate_rule(merged)
        if error:
            return JSONResponse(status_code=400, content=fail(error))
        saved = store.save_rule({**rule, "_file": existing.get("_file")})
        rule_trigger = rule.get("trigger") or {}
        if rule_trigger.get("type") == "schedule":
            # mode=after 的规则要按"多少秒后一次"重新计时（漏传会算不出下次触发时间）
            scheduler.prime_schedule(
                rule["id"],
                rule_trigger.get("cron"),
                rule_trigger.get("after_seconds"),
            )
        # 手动启用时把熔断标记也清掉（否则会被 disabled_rules 挡住）
        if body.get("enabled"):
            settings = store.load_settings()
            disabled = [x for x in settings.get("disabled_rules") or [] if str(x) != str(rule_id)]
            if disabled != list(settings.get("disabled_rules") or []):
                store.save_settings({"disabled_rules": disabled})
        audit.write(
            action="automation.rule",
            status="success",
            trigger="api",
            rule_id=rule["id"],
            reason=f"更新规则：{', '.join(sorted(set(body) & editable))}",
        )
        return ok("规则已更新（立即生效）", saved)
    except permissions.PermissionDenied:
        raise
    except KeyError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"更新规则失败：{e}"))


@router.post("/automation/rules/{rule_id}/reset-runs")
def reset_automation_rule_runs(rule_id: str, request: Request):
    """重置这条规则**目标任务的执行次数与冷却**（「单任务执行上限」撑满后用它放行）。

    - 按规则 condition 现算一遍目标任务（与规则命中的口径一致）；
    - 清掉这些任务在该规则**动作**下的 `counts` / `cooldowns` / `last_results`；
    - 同时把该规则的连续失败计数与熔断标记（disabled_rules）清掉；
    - 显式 `idempotency_key` 的指纹不受影响（那是调用方自己传的键，规则链路不带）。
    """
    try:
        _require_admin(request)
        rule = next((r for r in store.load_rules() if str(r.get("id")) == str(rule_id)), None)
        if rule is None:
            return JSONResponse(status_code=404, content=fail(f"规则不存在：{rule_id}"))
        action = str(rule.get("action") or "")
        condition = rule.get("condition") or {}

        targets: List[str] = []
        for project in load_db().get("projects", []):
            for task in project.get("tasks", []):
                try:
                    matched, _ = rules.condition_matches(
                        condition, rules.build_context(project, task)
                    )
                except Exception:  # noqa: BLE001 - 单个任务上下文异常不影响其它
                    matched = False
                if matched:
                    targets.append(str(task.get("task_id") or ""))

        keys = {f"{task_id}|{action}" for task_id in targets if task_id}
        cleared = {"counts": 0, "cooldowns": 0, "last_results": 0}

        def mutate(history: Dict[str, Any]) -> None:
            for bucket in ("counts", "cooldowns", "last_results"):
                data = dict(history.get(bucket) or {})
                for key in list(data):
                    if key in keys:
                        data.pop(key, None)
                        cleared[bucket] += 1
                history[bucket] = data
            failures = dict(history.get("rule_failures") or {})
            failures.pop(str(rule_id), None)
            history["rule_failures"] = failures

        store.update_history(mutate)

        settings = store.load_settings()
        disabled = [x for x in settings.get("disabled_rules") or [] if str(x) != str(rule_id)]
        if disabled != list(settings.get("disabled_rules") or []):
            store.save_settings({"disabled_rules": disabled})

        audit.write(
            action="automation.reset",
            status="success",
            trigger="api",
            rule_id=str(rule_id),
            reason=(
                f"重置执行计数：目标 {len(targets)} 个任务，"
                f"计数 -{cleared['counts']}、冷却 -{cleared['cooldowns']}"
            ),
        )
        return ok(
            f"已重置：{len(targets)} 个目标任务（执行计数 {cleared['counts']} 条、冷却 {cleared['cooldowns']} 条）",
            {
                "rule_id": str(rule_id),
                "action": action,
                "tasks": targets[:50],
                "task_count": len(targets),
                "cleared": cleared,
            },
        )
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"重置执行计数失败：{e}"))


@router.delete("/automation/rules/{rule_id}")
def delete_automation_rule(rule_id: str, request: Request):
    """删除规则（含它的冷却/计数/熔断历史）。"""
    try:
        _require_admin(request)
        if not store.delete_rule(rule_id):
            return JSONResponse(status_code=404, content=fail(f"规则不存在：{rule_id}"))
        audit.write(
            action="automation.rule",
            status="success",
            trigger="api",
            rule_id=rule_id,
            reason=f"删除规则 {rule_id}",
        )
        return ok("规则已删除", {"id": rule_id})
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"删除规则失败：{e}"))


@router.post("/automation/rules/{rule_id}/run")
def run_automation_rule(rule_id: str, request: Request):
    """立即触发一条**定时**规则（不等 cron；条件规则请用 /api/actions）。"""
    try:
        _require_admin(request)
        rule = next((r for r in store.load_rules() if str(r.get("id")) == str(rule_id)), None)
        if rule is None:
            return JSONResponse(status_code=404, content=fail(f"规则不存在：{rule_id}"))
        if rules.trigger_type(rule) != "schedule":
            return JSONResponse(
                status_code=400,
                content=fail("该规则由巡检事件触发，请直接调用 /api/actions/{action_name} 指定 task_id"),
            )
        events.publish(
            {
                "type": "schedule",
                "schedule_id": rule_id,
                "rule_id": rule_id,
                "scope": (rule.get("trigger") or {}).get("scope") or "all",
                "fired_at": "manual",
            }
        )
        return ok("已投递触发信号（规则命中后逐个任务执行，可在决策日志查看）", {"rule_id": rule_id})
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"触发规则失败：{e}"))


@router.post("/automation/reload")
def reload_automation(request: Request):
    """显式重载配置（规则/开关本来就是每次现读，这里同时确保默认文件存在）。"""
    try:
        _require_admin(request)
        store.ensure_defaults()
        return ok(
            "配置已重载（修改 cron / 开关后无需重启服务）",
            {"settings": store.load_settings(), "rules": len(store.load_rules())},
        )
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"重载配置失败：{e}"))


@router.get("/automation/decisions")
def automation_decisions(request: Request, limit: int = Query(default=100, ge=1, le=500)):
    """决策与执行日志：success / failed / skipped / blocked / dry_run 五态。"""
    try:
        _require_admin(request)
        return ok("查询成功", {"decisions": audit.read_recent(limit)})
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取决策日志失败：{e}"))


@router.get("/automation/runs")
def automation_runs(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    try:
        _require_admin(request)
        return ok("查询成功", {"runs": scheduler.list_runs(limit)})
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取运行记录失败：{e}"))
