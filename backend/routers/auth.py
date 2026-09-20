"""认证与 token 管理接口（账号体系第 2 步）。

| 接口 | 说明 |
| --- | --- |
| `POST /api/auth/login` | 用户名密码换 token（失败限速 5 次 / 15 分钟） |
| `POST /api/auth/logout` | 删除当前会话（立即失效） |
| `GET /api/auth/me` | 当前用户 + 当前会话信息 |
| `POST /api/auth/tokens` | 签发长期 token（**仅 admin**），可命名、设过期 |
| `GET /api/auth/tokens` | 列出 token（admin 看全部，其他人只看自己） |
| `DELETE /api/auth/tokens/{token_id}` | 吊销 token（admin 可吊销任意，其他人只能吊销自己的） |

登录成功时除了返回 token，还会写一个 `vasp_token` Cookie（HttpOnly、SameSite=Lax）；
它**只被 GET/HEAD 接受**，方便人类直接用浏览器打开 `/docs`（写操作仍必须用
`Authorization: Bearer` 头，因此不引入 CSRF 面）。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

import auth
from envelope import fail, ok
from middleware.auth import COOKIE_NAME, SESSION_EXTEND_SECONDS, current_user, is_admin

router = APIRouter(prefix="/auth", tags=["auth"])

#: 登录失败限速：15 分钟内同一 (用户名, IP) 最多 5 次失败
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_FAILURES: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
_LOGIN_LOCK = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "") or "unknown"


def _rate_key(request: Request, username: str) -> Tuple[str, str]:
    return (auth.normalize_username(username), _client_ip(request))


def _failures(key: Tuple[str, str]) -> Deque[float]:
    bucket = _LOGIN_FAILURES[key]
    cutoff = time.time() - LOGIN_WINDOW_SECONDS
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    return bucket


def _seconds_until_retry(key: Tuple[str, str]) -> int:
    with _LOGIN_LOCK:
        bucket = _failures(key)
        if len(bucket) < LOGIN_MAX_FAILURES:
            return 0
        return max(1, int(bucket[0] + LOGIN_WINDOW_SECONDS - time.time()) + 1)


def _record_failure(key: Tuple[str, str]) -> None:
    with _LOGIN_LOCK:
        _failures(key).append(time.time())


def _clear_failures(key: Tuple[str, str]) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.pop(key, None)


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": user.get("user_id"),
        "username": user.get("username"),
        "role": user.get("role"),
        "enabled": bool(user.get("enabled")),
        "created_at": user.get("created_at"),
    }


def _public_session(session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "session_id": auth.session_key(session),
        "name": session.get("name"),
        "kind": session.get("kind") or "session",
        "created_at": session.get("created_at"),
        "last_seen": session.get("last_seen"),
        "expires_at": session.get("expires_at"),
    }


@router.post("/login")
def login(request: Request, payload: dict = Body(default={})):
    """用户名 + 密码换 token；失败限速 5 次 / 15 分钟。"""
    username = str((payload or {}).get("username") or "").strip()
    password = str((payload or {}).get("password") or "")
    device = str((payload or {}).get("name") or "web").strip() or "web"
    if not username or not password:
        return JSONResponse(status_code=400, content=fail("请输入用户名和密码"))

    key = _rate_key(request, username)
    retry_after = _seconds_until_retry(key)
    if retry_after > 0:
        return JSONResponse(
            status_code=429,
            content=fail(f"登录失败次数过多，请 {max(1, retry_after // 60)} 分钟后再试"),
        )

    user = auth.authenticate(username, password)
    if user is None:
        _record_failure(key)
        remaining = LOGIN_MAX_FAILURES - len(_failures(key))
        message = "用户名或密码错误"
        if remaining <= 2:
            message += f"（再失败 {max(remaining, 0)} 次将被锁定 {LOGIN_WINDOW_SECONDS // 60} 分钟）"
        return JSONResponse(status_code=401, content=fail(message))

    _clear_failures(key)
    token, session = auth.create_session(
        user, name=device, kind="session", ttl_seconds=SESSION_EXTEND_SECONDS
    )
    response = JSONResponse(
        content=ok(
            "登录成功",
            {
                "token": token,
                "expires_at": session.get("expires_at"),
                "user": _public_user(user),
                "session": _public_session(session),
            },
        )
    )
    # 供浏览器直接打开 /docs 用（仅 GET/HEAD 生效），前端仍用 Authorization 头
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_EXTEND_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request):
    """删除当前会话（旧 token 立即失效）。"""
    token = getattr(request.state, "token", "") or ""
    revoked = auth.revoke_token(token) if token else False
    response = JSONResponse(content=ok("已退出登录", {"revoked": revoked}))
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/me")
def me(request: Request):
    """当前用户 + 当前会话信息（前端启动时校验登录态）。"""
    user = current_user(request)
    session = getattr(request.state, "session", {}) or {}
    return ok(
        "查询成功",
        {
            "user": _public_user(user),
            "session": _public_session(session),
            "is_admin": str(user.get("role") or "") == "admin",
        },
    )


@router.post("/tokens")
def create_token(request: Request, payload: dict = Body(default={})):
    """签发长期 token（仅 admin）：给脚本 / 智能体用，可命名、可设过期、可吊销。"""
    if not is_admin(request):
        return JSONResponse(status_code=403, content=fail("只有管理员可以签发长期 token"))
    admin = current_user(request)

    target_username = str((payload or {}).get("username") or "").strip()
    target_user_id = str((payload or {}).get("user_id") or "").strip()
    if target_user_id:
        target = auth.find_user_by_id(target_user_id)
    elif target_username:
        target = auth.find_user(target_username)
    else:
        target = dict(admin)  # 不指定则给自己签
    if target is None:
        return JSONResponse(status_code=404, content=fail("目标用户不存在"))
    if not target.get("enabled"):
        return JSONResponse(status_code=400, content=fail("目标用户已被禁用，无法签发 token"))

    name = str((payload or {}).get("name") or "").strip() or f"token-{target.get('username')}"
    expires_days = (payload or {}).get("expires_days")
    never_expires = bool((payload or {}).get("never_expires"))
    ttl_days: Optional[int]
    if never_expires:
        ttl_days = None
    elif expires_days is None:
        ttl_days = None  # 未指定也视为长期有效（可随时吊销）
    else:
        try:
            ttl_days = int(expires_days)
        except (TypeError, ValueError):
            return JSONResponse(status_code=400, content=fail("expires_days 必须是整数天数"))
        if ttl_days <= 0:
            return JSONResponse(status_code=400, content=fail("expires_days 必须大于 0"))

    token, session = auth.create_session(
        target,
        name=name,
        ttl_days=ttl_days,
        kind="token",
        created_by=str(admin.get("username") or ""),
        never_expires=ttl_days is None,
    )
    return ok(
        "长期 token 已签发（明文只显示这一次，请立即保存）",
        {
            "token": token,
            "user": _public_user(target),
            "session": _public_session(session),
            "expires_at": session.get("expires_at"),
        },
    )


@router.get("/tokens")
def list_tokens(request: Request):
    """列出 token / 会话：admin 看全部，其他用户只看自己的。"""
    user = current_user(request)
    admin = is_admin(request)
    own_id = None if admin else str(user.get("user_id"))
    current_id = auth.session_key(getattr(request.state, "session", {}) or {})
    rows: List[Dict[str, Any]] = []
    for session in auth.list_sessions(user_id=own_id):
        owner = auth.find_user_by_id(session.get("user_id")) or {}
        rows.append(
            {
                **_public_session(session),
                "user_id": session.get("user_id"),
                "username": owner.get("username") or session.get("username") or "",
                "role": owner.get("role"),
                "created_by": session.get("created_by"),
                "token_hash": session.get("token_hash"),
                "current": auth.session_key(session) == current_id,
            }
        )
    return ok("查询成功", {"tokens": rows, "is_admin": admin})


@router.delete("/tokens/{token_id}")
def delete_token(token_id: str, request: Request):
    """吊销指定 token（admin 可吊销任意，其他用户只能吊销自己的）。"""
    user = current_user(request)
    session = auth.get_session(token_id)
    if session is None:
        return JSONResponse(status_code=404, content=fail("token 不存在或已失效"))
    if not is_admin(request) and str(session.get("user_id")) != str(user.get("user_id")):
        return JSONResponse(status_code=403, content=fail("只能吊销自己的 token"))
    removed = auth.delete_session(token_id)
    return ok("token 已吊销", {"revoked": removed, "session_id": token_id})
