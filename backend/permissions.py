"""归属判断（账号体系第 4 步：授权生效）。

本模块**只做归属判断**，不含任何业务逻辑，也不读 request（除审计辅助函数）：

1. **列表过滤**：`visible_projects(db, user)` / `visible_project_names(db, user)`
   —— admin 全可见；普通用户只看 `owner == 自己用户名` 的项目（大小写归一）。
2. **单对象校验**：`ensure_project_owner(project, user)` / `ensure_task_owner(task, user, db)`
   —— 非 owner 且非 admin 一律抛 `PermissionDenied`（全局异常处理器统一转成 403）。
3. **审计辅助**：`current_username(request)` / `context_username()`。

另外提供 `enforce_task(task, db)`：给 `jobs._resolve_task` 这类"唯一入口"用——
它从 contextvar 取当前登录用户（由认证中间件写入），**后台线程等没有登录用户的
场景自动跳过**（内部调用不触发 403）。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Set

import auth

__all__ = [
    "PermissionDenied",
    "set_current_user",
    "current_user_from_context",
    "clear_current_user",
    "context_username",
    "current_username",
    "username_of",
    "is_admin",
    "owned_by",
    "visible_projects",
    "visible_project_names",
    "project_of_task",
    "ensure_project_owner",
    "ensure_task_owner",
    "ensure_admin",
    "enforce_task",
]


class PermissionDenied(Exception):
    """越权访问：全局异常处理器会转成 `403` + 统一 JSON 信封。"""

    def __init__(self, message: str = "无权访问该项目"):
        super().__init__(message)
        self.message = message


_CURRENT_USER: ContextVar[Optional[Dict[str, Any]]] = ContextVar("vasp_current_user", default=None)


# ------------------------------------------------------------------ 当前用户


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """认证中间件校验通过后写入（供 `_resolve_task` 等深层调用使用）。"""
    _CURRENT_USER.set(user or None)


def current_user_from_context() -> Optional[Dict[str, Any]]:
    return _CURRENT_USER.get()


def clear_current_user() -> None:
    _CURRENT_USER.set(None)


def context_username() -> str:
    """contextvar 里的用户名（后台线程为空串）。"""
    return username_of(current_user_from_context())


def current_username(request: Any = None) -> str:
    """审计用：优先从 `request.state.user` 取，取不到再退回 contextvar。"""
    if request is not None:
        user = getattr(getattr(request, "state", None), "user", None)
        name = username_of(user)
        if name:
            return name
    return context_username()


# ------------------------------------------------------------------ 归属判断


def username_of(user: Optional[Dict[str, Any]]) -> str:
    """取用户名（统一小写归一，与账号模块一致，大小写不敏感）。"""
    if not user:
        return ""
    return auth.normalize_username(user.get("username"))


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    return str((user or {}).get("role") or "") == "admin"


def owned_by(project: Optional[Dict[str, Any]], user: Optional[Dict[str, Any]]) -> bool:
    """项目是否归该用户所有（admin 恒为 True）。"""
    if is_admin(user):
        return True
    if not project:
        return False
    owner = auth.normalize_username(project.get("owner"))
    name = username_of(user)
    return bool(owner) and owner == name


def visible_projects(db: Dict[str, Any], user: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """当前用户可见的项目列表（admin 全部，普通用户只看自己的）。"""
    projects = list(db.get("projects", []) or [])
    if is_admin(user):
        return projects
    name = username_of(user)
    if not name:
        return []
    return [p for p in projects if auth.normalize_username(p.get("owner")) == name]


def visible_project_names(db: Dict[str, Any], user: Optional[Dict[str, Any]]) -> Set[str]:
    """可见项目名集合（用于按项目管理过滤巡检结果 / 报告 / 统计）。"""
    return {str(p.get("name") or "") for p in visible_projects(db, user)}


def project_of_task(db: Dict[str, Any], task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按任务反查所属项目（优先 task_id，其次项目名）。"""
    task_id = str(task.get("task_id") or "")
    if task_id:
        for project in db.get("projects", []) or []:
            for item in project.get("tasks", []) or []:
                if str(item.get("task_id") or "") == task_id:
                    return project
    return None


def ensure_project_owner(project: Optional[Dict[str, Any]], user: Optional[Dict[str, Any]]) -> None:
    """非 owner 且非 admin → 403（不返回 404，避免探测项目是否存在）。"""
    if owned_by(project, user):
        return
    raise PermissionDenied("无权访问该项目")


def ensure_task_owner(
    task: Optional[Dict[str, Any]],
    user: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]] = None,
) -> None:
    """任务归属校验：找到任务所属项目再校验（admin 直接放行）。"""
    if is_admin(user):
        return
    if not task:
        raise PermissionDenied("无权访问该任务")
    if db is None:
        from storage import load_db

        db = load_db()
    project = project_of_task(db, task)
    if not owned_by(project, user):
        raise PermissionDenied("无权访问该任务")


def ensure_admin(user: Optional[Dict[str, Any]], message: str = "需要管理员权限") -> None:
    if not is_admin(user):
        raise PermissionDenied(message)


def enforce_task(task: Dict[str, Any], db: Optional[Dict[str, Any]] = None, user: Any = "__ctx__") -> None:
    """给"唯一入口"用的守卫：从 contextvar 取用户；

    - 有登录用户 → 走 `ensure_task_owner`；
    - 没有（后台线程 / 内部调用）→ 直接放行，保持内部流程不受影响。
    """
    if user == "__ctx__":
        user = current_user_from_context()
    if user is None:
        return
    ensure_task_owner(task, user, db)
