"""AI 专用入口（2026-10-13）：给大模型/智能体一个明确、稳定的调用面。

设计：**不复制业务逻辑**，只是把已有的只读数据按 AI 需要的方式暴露出来：

| 接口 | 说明 |
| --- | --- |
| `GET /api/ai` | 入口清单（有哪些接口、契约从哪拿、scope 怎么用） |
| `GET /api/ai/contract` | 数据契约（同 `/reports/project/schema`：状态族/单位/时间/别名） |
| `GET /api/ai/tasks/{task_id}/context` | **任务上下文**（= `/api/jobs/tasks/{id}/context`） |
| `GET /api/ai/pending-actions` | 待确认队列（AI 提案后在这里看状态） |

认证：agent 账号需带 `delegate_to`（继承某用户可见范围），token 需带 `scope`
（`read` 只读 / `propose` 可进待确认队列 / `write` 可直接执行动作）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

import permissions
from envelope import fail, ok
from report_schema import schema_manifest

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("")
def ai_index(request: Request):
    """AI 入口清单：先读这里，再按需调用。"""
    user = getattr(request.state, "user", None) or {}
    session = getattr(request.state, "session", None) or {}
    return ok(
        "查询成功",
        {
            "actor": {
                "username": permissions.username_of(user),
                "role": user.get("role"),
                "delegate_to": user.get("delegate_to"),
                "scope": permissions.token_scope(session),
                "scope_meaning": {
                    "read": "只读（上下文/报告/巡检）",
                    "propose": "可提交待确认动作，由人工批准后才执行",
                    "write": "允许直接执行动作（submit / continuation / frac.create 等）",
                },
            },
            "entrypoints": [
                {"method": "GET", "path": "/api/ai/contract", "purpose": "数据契约：状态族/单位/时间/字段别名"},
                {"method": "GET", "path": "/api/ai/tasks/{task_id}/context", "purpose": "任务上下文（AI 决策唯一入口）"},
                {"method": "GET", "path": "/api/ai/tasks/{task_id}/outcar-tail", "purpose": "OUTCAR 尾部（异常排查）"},
                {"method": "GET", "path": "/api/ai/pending-actions", "purpose": "待确认队列（提案后看状态）"},
                {"method": "POST", "path": "/api/pending-actions", "purpose": "提交动作提案（需 scope=propose）"},
                {"method": "GET", "path": "/api/inspections", "purpose": "全项目巡检结论（一行一任务）"},
            ],
            "hint": "数值以字段为准、图表只作可视化；决策前先读 /api/ai/contract 与任务上下文里的 hints.missing",
        },
    )


@router.get("/contract")
def ai_contract():
    """数据契约（与报告 schema 同一份，便于 AI 固定 prompt）。"""
    return ok("查询成功", schema_manifest())


@router.get("/tasks/{task_id}/context")
def ai_task_context(
    task_id: str,
    n_checks: int = Query(default=5, ge=0, le=50),
    n_actions: int = Query(default=10, ge=0, le=200),
    refresh: bool = Query(default=False),
):
    """任务上下文（等价于 `/api/jobs/tasks/{id}/context`，AI 用这个入口更清晰）。"""
    try:
        from routers.jobs import _resolve_task
        from task_context import load_task_context

        project, task = _resolve_task(task_id)
        context = load_task_context(
            project, task, n_checks=n_checks, n_actions=n_actions, refresh=refresh
        )
        return ok("查询成功", context)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"构建任务上下文失败：{e}"))


@router.get("/tasks/{task_id}/outcar-tail")
def ai_outcar_tail(
    task_id: str,
    lines: int = Query(default=60, ge=1, le=500),
    image: str = Query(default=""),
):
    """OUTCAR 尾部（等价于 `/api/jobs/tasks/{id}/outcar-tail`）。"""
    try:
        from routers.jobs import _resolve_task
        from task_files_summary import outcar_tail_for_task

        project, task = _resolve_task(task_id)
        data = outcar_tail_for_task(project, task, lines=lines, image=(image.strip() or None))
        return ok("查询成功", data)
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except permissions.PermissionDenied:
        raise
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"读取 OUTCAR 尾部失败：{e}"))


@router.get("/pending-actions")
def ai_pending_actions(
    status: str = Query(default="", description="pending/approved/rejected/failed"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """待确认队列（AI 侧视角，等价于 `/api/pending-actions`）。"""
    import pending_actions

    return ok(
        "查询成功",
        {
            "items": pending_actions.list_items(
                status=(status.strip() or None), limit=limit
            )
        },
    )
