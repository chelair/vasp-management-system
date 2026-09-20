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

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import permissions
from envelope import fail, ok
from automation import actions, audit, cron, events, rules, scheduler, store

router = APIRouter(tags=["actions"])


def _require_admin(request: Request) -> None:
    permissions.ensure_admin(
        getattr(request.state, "user", None), "只有管理员可以使用自动化与动作接口"
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
    for schedule in rules.schedules():
        rule = next((r for r in store.load_rules() if str(r.get("id")) == str(schedule["id"])), {})
        rows.append(
            {
                **schedule,
                "trigger": rule.get("trigger") or {},
                "next_run_at": scheduler.next_run_of(schedule["id"]),
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


@router.put("/automation/rules/{rule_id}")
def update_automation_rule(rule_id: str, request: Request, payload: dict = Body(default={})):
    """启用 / 停用规则（写回规则文件；`disabled_rules` 用于失败熔断）。"""
    try:
        _require_admin(request)
        if "enabled" in (payload or {}):
            rule = store.set_rule_enabled(rule_id, bool(payload["enabled"]))
            settings = store.load_settings()
            disabled = [x for x in settings.get("disabled_rules") or [] if str(x) != str(rule_id)]
            store.save_settings({"disabled_rules": disabled})
            audit.write(
                action="automation.rule",
                status="success",
                trigger="api",
                rule_id=rule_id,
                reason=f"规则 {rule_id} 已{'启用' if payload['enabled'] else '停用'}",
            )
            return ok("规则已更新", rule)
        return JSONResponse(status_code=400, content=fail("仅支持修改 enabled"))
    except KeyError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"更新规则失败：{e}"))


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
