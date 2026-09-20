"""FastAPI 应用入口：统一信封、校验错误翻译、后台依赖检查、静态托管 dist。"""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import PROJECT_ROOT, ensure_data_dirs, load_servers
from dependencies import INSTALL_HINT, check_dependencies
from envelope import fail
from middleware.auth import install as install_auth_middleware
from routers import auth as auth_router
from routers import auxiliary as aux
from routers import free_energy
from routers import (
    dashboard,
    groups,
    inspections,
    jobs,
    meta,
    paths,
    project_reports,
    projects,
    reports,
    settings,
    ssh,
)
from ssh import warmup_connection


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dirs()

    # 账号底座（第 1 步）：users.json 不存在时自动创建默认管理员（随机密码打印一次）
    # 目前只做"文件与账号初始化"，**没有任何接口依赖它**（认证/授权见后续步骤）
    try:
        from auth import ensure_users_file, purge_expired_sessions

        created = ensure_users_file()
        if created.get("created"):
            print(f"[auth] 已创建默认管理员 {created['username']}，初始密码见上方提示", flush=True)
        purged = purge_expired_sessions()
        if purged:
            print(f"[auth] 已清理过期会话 {purged} 个", flush=True)
    except Exception as e:  # noqa: BLE001 - 账号底座初始化失败不阻塞服务启动
        print(f"[auth] 初始化失败（不影响现有功能）：{e}", flush=True)

    def _check_deps() -> None:
        missing = [d for d in check_dependencies() if not d["installed"]]
        if missing:
            names = "、".join(f"{d['name']}（{d['purpose']}）" for d in missing)
            print(f"[deps] 缺失依赖：{names}")
            print(f"[deps] 安装命令：{INSTALL_HINT}")
        else:
            print("[deps] 依赖检查通过")

    # 后台线程检查依赖，不阻塞启动
    threading.Thread(target=_check_deps, daemon=True).start()

    def _warmup_ssh() -> None:
        try:
            servers = load_servers()
            if servers:
                warmup_connection(next(iter(servers)))
        except Exception:  # noqa: BLE001 - 预热失败不阻塞启动
            pass

    # 启动时后台建立常驻 SSH 连接（保持登录状态）
    threading.Thread(target=_warmup_ssh, daemon=True).start()

    # 自动巡检调度：距上次巡检超过 inspection_interval_hours 即触发全局巡检
    try:
        from inspection_scheduler import start_scheduler

        start_scheduler()
    except Exception as e:  # noqa: BLE001 - 调度器启动失败不影响服务
        print(f"[auto-inspection] 调度器启动失败：{e}")
    yield


app = FastAPI(title="VASP 计算项目管理系统 API", version="0.2.0", lifespan=lifespan)

# 认证中间件（第 2 步）：除白名单（POST /api/auth/login、GET /api/health）外，
# /api/** 与 /docs、/openapi.json 一律要求登录
install_auth_middleware(app)


def _loc_to_path(loc) -> str:
    parts = []
    for item in loc:
        if item == "body":
            continue
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(f".{item}" if parts else str(item))
    return "".join(parts)


def _translate_error(err: dict) -> str:
    etype = err.get("type")
    if etype == "missing":
        return "缺少必填字段"
    if etype == "extra_forbidden":
        loc = err.get("loc", ())
        extra = err.get("ctx", {}).get("extra_keys") or (
            [str(loc[-1])] if loc else []
        )
        return f"不允许的字段 {[str(x) for x in extra]}"
    if etype == "string_pattern_mismatch":
        return f"格式不合法（须匹配 {err.get('ctx', {}).get('pattern', '')}）"
    if etype == "literal_error":
        expected = err.get("ctx", {}).get("expected")
        if isinstance(expected, str):
            expected = [expected]
        return f"必须是 {list(expected) if expected is not None else ''} 之一，当前为 {err.get('input')!r}"
    if etype == "list_too_short":
        return f"至少需要 {err.get('ctx', {}).get('min_length', '')} 个元素"
    if etype == "too_short":
        return f"至少需要 {err.get('ctx', {}).get('min_length', '')} 个元素"
    if etype == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ")
    return str(err.get("msg", ""))


@app.exception_handler(RequestValidationError)
async def validation_handler(_, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = _loc_to_path(err.get("loc", ()))
        msg = _translate_error(err)
        errors.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=400,
        content=fail("输入校验失败，请按错误信息修改后重试", {"errors": errors}),
    )


app.include_router(meta.router, prefix="/api")
app.include_router(auth_router.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(groups.router, prefix="/api")
app.include_router(aux.router, prefix="/api")
app.include_router(free_energy.router, prefix="/api")
app.include_router(paths.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(project_reports.router, prefix="/api")
app.include_router(ssh.router, prefix="/api")
app.include_router(inspections.router, prefix="/api")


# 生产模式：同时托管前端 dist/（单端口部署）
dist_dir = PROJECT_ROOT / "dist"
if (dist_dir / "index.html").exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    # 3Dmol 本地库（public/3dmol → dist/3dmol），不挂载会被 SPA 兜底当页面返回
    dmol_dir = dist_dir / "3dmol"
    if dmol_dir.exists():
        app.mount("/3dmol", StaticFiles(directory=dmol_dir), name="3dmol")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(dist_dir / "index.html")
