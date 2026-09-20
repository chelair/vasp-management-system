"""认证中间件（账号体系第 2 步）：**全局拦截 /api 与文档路由，未登录一律 401**。

规则（与 TODO.md §14 第 2 步一致）：

- 白名单只有 `POST /api/auth/login` 与 `GET /api/health`；
- `/docs`、`/openapi.json`、`/redoc` 也要登录（`/docs` 是浏览器页面，取 token 的方式见下）；
- **跳过 OPTIONS**（CORS 预检）；
- 静态资源 / SPA 路由（`/`、`/assets/*`、`/3dmol/*` 等）不拦截 —— 否则登录页本身都加载不出来；
- token 取值顺序：`Authorization: Bearer <token>` → `X-Auth-Token` → `?token=` → Cookie `vasp_token`；
  **Cookie 与 `?token=` 只对 GET/HEAD 放行**（写操作必须走 Authorization 头，规避 CSRF）；
- 校验：sha256 → 查 sessions → 过期 / 用户被禁用 → 401 → `request.state.user` / `.session`，
  并做**滑动续期**（有效期推到 now+14 天，漂移 ≥1h 才写盘）。

拦截失败返回与其它接口一致的 JSON 信封：`{"success": false, "message": "...", "data": {}}`。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import auth

#: 免登录白名单：`(方法, 路径)`
WHITELIST: Tuple[Tuple[str, str], ...] = (
    ("POST", "/api/auth/login"),
    ("GET", "/api/health"),
)

#: 需要认证的路径前缀 / 精确路径
PROTECTED_PREFIXES = ("/api/",)
PROTECTED_EXACT = ("/docs", "/openapi.json", "/redoc")

#: 仅允许"Cookie / 查询参数"带 token 的安全方法（写操作必须用 Authorization 头）
SAFE_METHODS = ("GET", "HEAD")

COOKIE_NAME = "vasp_token"
#: 会话滑动续期窗口（秒）：默认 14 天
SESSION_EXTEND_SECONDS = auth.SESSION_TTL_DAYS * 24 * 3600


def _unauthorized(message: str, status_code: int = 401) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "message": message, "data": {}},
    )


def _needs_auth(method: str, path: str) -> bool:
    if (method, path) in WHITELIST:
        return False
    if path in PROTECTED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _bearer(request: Request) -> Optional[str]:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    direct = (request.headers.get("x-auth-token") or "").strip()
    return direct or None


def extract_token(request: Request) -> Optional[str]:
    """按优先级取 token；Cookie / `?token=` 仅限 GET/HEAD。"""
    token = _bearer(request)
    if token:
        return token
    if request.method.upper() in SAFE_METHODS:
        query = (request.query_params.get("token") or "").strip()
        if query:
            return query
        cookie = (request.cookies.get(COOKIE_NAME) or "").strip()
        if cookie:
            return cookie
    return None


async def auth_middleware(request: Request, call_next):
    method = request.method.upper()
    path = request.url.path

    # CORS 预检直接放行；不需要认证的路径也直接放行
    if method == "OPTIONS" or not _needs_auth(method, path):
        return await call_next(request)

    token = extract_token(request)
    if not token:
        return _unauthorized("未登录或登录已过期，请先登录")

    verified = auth.verify_token(token, touch=True, extend_seconds=SESSION_EXTEND_SECONDS)
    if verified is None:
        return _unauthorized("登录已失效（token 无效 / 已过期 / 账号被禁用），请重新登录")

    session, user = verified
    request.state.token = token
    request.state.session = session
    request.state.user = user
    request.state.user_id = user.get("user_id")
    request.state.username = user.get("username")
    return await call_next(request)


def install(app: FastAPI) -> None:
    """把认证中间件挂到 app（在 `main.py` 里调用，需在任何请求之前）。"""
    app.middleware("http")(auth_middleware)


def current_user(request: Request) -> Dict[str, Any]:
    """给路由用的取当前用户助手（中间件已保证存在）。"""
    user = getattr(request.state, "user", None)
    if not user:
        raise PermissionError("未认证")
    return user


def is_admin(request: Request) -> bool:
    user = getattr(request.state, "user", None) or {}
    return str(user.get("role") or "") == "admin"
