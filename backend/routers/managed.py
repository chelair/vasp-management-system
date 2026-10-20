"""托管计划 HTTP 入口：只保存计划/优先级/资源规则，不提交作业。

- 计划、任务优先级、资源规则：`managed_plan`
- 候选排序与资源评分：`managed_schedule`（只读、确定性）
- 执行开关仍看 `automation.ledger` 的 enabled；本模块没有任何执行动作。
"""

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

import managed_plan
import managed_schedule
import permissions
from envelope import fail, ok

router = APIRouter(prefix="/managed", tags=["managed"])


def _user(request):
    return getattr(request.state, "user", None)


def _execution_enabled() -> bool:
    try:
        from automation import ledger

        return bool(ledger.read().get("enabled"))
    except Exception:  # noqa: BLE001 - 台账损坏时只当作未开启
        return False


def _with_summary(plan: dict, project: dict) -> dict:
    try:
        summary = managed_schedule.summary(plan, project)
    except Exception as exc:  # noqa: BLE001 - 计划字段异常不应拖垮列表
        summary = {"error": str(exc), "candidates": [], "needs_user": ["计划数据异常，请检查"]}
    return {"plan": plan, "summary": summary}


def _project_of(plan: dict):
    from storage import load_db

    return next((p for p in load_db().get("projects", []) if str(p.get("name")) == str(plan.get("project"))), None)


@router.get("")
def list_plans(request: Request):
    try:
        user = _user(request)
        items = []
        for plan in managed_plan.list_plans(user):
            project = _project_of(plan)
            if project is None:
                continue
            items.append(_with_summary(plan, project))
        return ok("查询成功", {"plans": items, "execution_enabled": _execution_enabled()})
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.post("/plans")
def create_plan(request: Request, payload: dict = Body(...)):
    try:
        plan = managed_plan.create(_user(request), payload)
        project = _project_of(plan)
        return ok("托管计划已保存；只记录计划与规则，不等于已开始计算", _with_summary(plan, project or {}))
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, request: Request):
    try:
        plan = managed_plan.get(plan_id, _user(request))
        project = _project_of(plan)
        return ok("查询成功", _with_summary(plan, project or {}))
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.patch("/plans/{plan_id}")
def patch_plan(plan_id: str, request: Request, payload: dict = Body(...)):
    try:
        if not isinstance(payload, dict) or "revision" not in payload:
            raise managed_plan.ManagedError("修改计划需要 revision（当前版本号）")
        revision = payload.pop("revision")
        plan = managed_plan.patch(plan_id, _user(request), revision, payload, source="human")
        project = _project_of(plan)
        return ok("计划已更新；不会自动提交作业", _with_summary(plan, project or {}))
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.post("/plans/{plan_id}/status")
def set_status(plan_id: str, request: Request, payload: dict = Body(...)):
    try:
        if set(payload) != {"status"} or payload.get("status") not in ("active", "paused", "ended"):
            raise managed_plan.ManagedError("只支持 status: active/paused/ended")
        plan = managed_plan.set_status(plan_id, _user(request), payload["status"])
        project = _project_of(plan)
        return ok("计划状态已更新；暂停/结束不会停止远端作业", _with_summary(plan, project or {}))
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.get("/plans/{plan_id}/candidates")
def plan_candidates(plan_id: str, request: Request):
    try:
        plan = managed_plan.get(plan_id, _user(request))
        project = _project_of(plan) or {}
        return ok("查询成功；仅排序，不提交", managed_schedule.summary(plan, project))
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.get("/plans/{plan_id}/resource-plan")
def resource_plan(plan_id: str, request: Request):
    """只读资源建议：复用集群共享采集（TTL 内读缓存），不做 SSH 写入、不提交。"""
    try:
        plan = managed_plan.get(plan_id, _user(request))
        from config import load_servers

        cfg = load_servers().get(plan.get("server")) or {}
        snapshot, error = None, ""
        try:
            from cluster_status import build_snapshot

            snapshot = build_snapshot(str(plan.get("server")), use_cache=True)
        except Exception as exc:  # noqa: BLE001 - 采集失败按"没有快照"处理
            error = str(exc)
        result = managed_schedule.resource_plan(plan, cfg, snapshot)
        if error:
            result.setdefault("notes", []).append(f"集群快照采集失败：{error}")
        return ok("仅给出资源建议；没有提交任何作业", result)
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


@router.get("/plans/{plan_id}/script-preview")
def script_preview(plan_id: str, request: Request, index: int = 0):
    """按评分最高的资源方案渲染 vasp.lsf 预览；不写入远端、不提交。"""
    try:
        plan = managed_plan.get(plan_id, _user(request))
        from config import load_servers

        cfg = load_servers().get(plan.get("server")) or {}
        snapshot = None
        try:
            from cluster_status import build_snapshot

            snapshot = build_snapshot(str(plan.get("server")), use_cache=True)
        except Exception:  # noqa: BLE001 - 采集失败时 resource_plan 会给出等待原因
            snapshot = None
        scored = managed_schedule.resource_plan(plan, cfg, snapshot)
        if scored.get("state") != "ok" or not scored.get("candidates"):
            return ok("当前没有可预览的资源方案；未生成脚本", {"state": scored.get("state"),
                                                              "reason": scored.get("reason"), "written": False})
        candidates = scored["candidates"]
        if isinstance(index, bool) or not 0 <= index < len(candidates):
            raise managed_plan.ManagedError("没有该序号的资源方案")
        import vasp_script

        candidate = candidates[index]
        text = vasp_script.render(
            queue=candidate["queue"], cores=candidate["cores"], cores_per_node=candidate["cores_per_node"],
            walltime_hours=candidate["walltime_hours"], job_name="managed_" + plan["id"][-8:],
            soft_kill=bool(plan["resource_rules"].get("soft_kill", True)),
        )
        issues = vasp_script.check(text, expected_cores=candidate["cores"],
                                   expected_walltime=candidate["walltime_hours"], expected_queue=candidate["queue"])
        return ok("仅生成脚本预览；未写入远端、未提交任何作业",
                  {"candidate": candidate, "script": text, "issues": issues, "written": False})
    except Exception as exc:  # noqa: BLE001
        return _failure(exc)


def _failure(exc):
    if isinstance(exc, permissions.PermissionDenied):
        raise exc
    if isinstance(exc, managed_plan.ManagedError):
        return JSONResponse(status_code=exc.code, content=fail(exc.message))
    if isinstance(exc, ValueError):
        return JSONResponse(status_code=400, content=fail(str(exc)))
    return JSONResponse(status_code=503, content=fail(str(exc)))
