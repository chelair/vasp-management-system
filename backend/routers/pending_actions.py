"""待确认队列接口（2026-10-13）：AI 提案 → 人工批准/驳回 → 才真正执行。

| 接口 | 谁用 | 说明 |
| --- | --- | --- |
| `POST /api/pending-actions` | AI（token scope 需 `propose`） | 提交动作提案，入库不执行 |
| `GET  /api/pending-actions` | 人工 | 查看队列（可按 status / project 过滤） |
| `POST /api/pending-actions/{id}/approve` | **人工** | 批准并执行（复用自动化动作实现） |
| `POST /api/pending-actions/{id}/reject` | **人工** | 驳回 |

安全：**agent 账号不能批准/驳回**（AI 不能自审自批），只有人类会话可以。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

import auth
import pending_actions
import permissions
from automation import actions as action_catalog
from envelope import fail, ok

router = APIRouter(prefix="/pending-actions", tags=["pending-actions"])


def _current(request: Request):
    return getattr(request.state, "user", None) or {}


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "") or "unknown"


def _require_human(request: Request) -> Optional[JSONResponse]:
    """批准/驳回必须是人（agent 账号一律拒绝）。"""
    user = _current(request)
    if str(user.get("role") or "") == "agent":
        return JSONResponse(
            status_code=403,
            content=fail("agent 账号不能批准/驳回待确认动作（AI 不能自审自批）"),
        )
    return None


@router.get("/catalog")
def pending_action_catalog():
    """可用动作目录（AI 提案前先看这个：动作名 / 说明 / 需要哪些参数）。"""
    return ok("查询成功", {"actions": action_catalog.catalog()})


@router.post("")
def create_pending_action(request: Request, payload: dict = Body(default={})):
    """**AI 侧**：提交一个待确认动作（不会立即执行）。"""
    try:
        data = payload or {}
        action = str(data.get("action") or "").strip()
        params = data.get("payload") or {}
        if not isinstance(params, dict):
            return JSONResponse(status_code=400, content=fail("payload 必须是对象"))
        user = _current(request)
        project_name = str(data.get("project_name") or "")
        task_name = str(data.get("task_name") or "")
        # 归属校验：拿 task_id 反查项目，确保 AI 只能对自己可见的任务提案
        task_id = str(params.get("task_id") or "")
        if task_id:
            from storage import load_db

            db = load_db()
            project = None
            task = None
            for p in db.get("projects", []):
                for t in p.get("tasks", []) or []:
                    if str(t.get("task_id")) == task_id:
                        project, task = p, t
                        break
                if project:
                    break
            if project is None or task is None:
                return JSONResponse(status_code=404, content=fail(f"任务不存在：{task_id}"))
            permissions.ensure_project_owner(project, user)
            project_name = project_name or str(project.get("name") or "")
            task_name = task_name or str(task.get("model_name") or "")
        item = pending_actions.create(
            action=action,
            payload=params,
            reason=str(data.get("reason") or ""),
            requested_by=permissions.username_of(user) or "-",
            requested_kind="agent" if str(user.get("role") or "") == "agent" else "user",
            project_name=project_name,
            task_name=task_name,
        )
        auth.audit(
            "pending-propose",
            "OK",
            permissions.username_of(user),
            _client_ip(request),
            detail=f"{item['id']} action={item['action']} task={item.get('task_id') or '-'} kind={item['requested_kind']}",
        )
        return ok("已进入待确认队列（等待人工批准）", {"item": item})
    except permissions.PermissionDenied:
        raise
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"提交待确认动作失败：{e}"))


@router.get("")
def list_pending_actions(
    status: Optional[str] = Query(default=None, description="pending/approved/rejected/failed，可逗号分隔"),
    project: Optional[str] = Query(default=None, description="按项目名过滤"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """**人工侧**：查看待确认动作队列（新 → 旧）。"""
    items = pending_actions.list_items(status=status, project_name=project, limit=limit)
    counts = {"pending": 0, "approved": 0, "rejected": 0, "failed": 0}
    for item in pending_actions.list_items(limit=500):
        key = str(item.get("status") or "")
        if key in counts:
            counts[key] += 1
    return ok("查询成功", {"items": items, "counts": counts, "available_actions": action_catalog.catalog()})


@router.post("/{item_id}/approve")
def approve_pending_action(item_id: str, request: Request, payload: dict = Body(default={})):
    """**人工批准**：执行该动作（复用自动化动作实现），执行失败标 `failed` 并留痕。"""
    denied = _require_human(request)
    if denied is not None:
        return denied
    try:
        user = _current(request)
        if set(payload or {}) - {'note'}:
            raise ValueError('审批不能修改动作参数，请重新创建提案')
        item = pending_actions.approve(
            item_id,
            decided_by=permissions.username_of(user) or "-",
            note=str((payload or {}).get("note") or ""),
        )
        auth.audit(
            "pending-approve",
            str(item.get("status") or ""),
            permissions.username_of(user),
            _client_ip(request),
            detail=f"{item_id} action={item.get('action')} error={item.get('error') or '-'}",
        )
        return ok("已批准并执行", {"item": item})
    except permissions.PermissionDenied:
        raise
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"批准失败：{e}"))


@router.post("/{item_id}/reject")
def reject_pending_action(item_id: str, request: Request, payload: dict = Body(default={})):
    """**人工驳回**：只改状态，不执行。"""
    denied = _require_human(request)
    if denied is not None:
        return denied
    try:
        user = _current(request)
        pending = pending_actions.get_item(item_id)
        if pending is None:
            raise LookupError('待确认动作不存在')
        from automation.actions import load_task
        project, _ = load_task(pending['task_id'])
        permissions.ensure_project_owner(project, _current(request))
        item = pending_actions.reject(
            item_id,
            decided_by=permissions.username_of(user) or "-",
            note=str((payload or {}).get("note") or ""),
        )
        auth.audit(
            "pending-reject",
            "OK",
            permissions.username_of(user),
            _client_ip(request),
            detail=f"{item_id} action={item.get('action')}",
        )
        return ok("已驳回", {"item": item})
    except permissions.PermissionDenied:
        raise
    except LookupError as e:
        return JSONResponse(status_code=404, content=fail(str(e)))
    except ValueError as e:
        return JSONResponse(status_code=400, content=fail(str(e)))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content=fail(f"驳回失败：{e}"))
