"""FastAPI 应用入口：统一信封、校验错误翻译、后台依赖检查、静态托管 dist。"""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import PROJECT_ROOT, ensure_data_dirs
from dependencies import INSTALL_HINT, check_dependencies
from envelope import fail
from routers import inspections, meta, projects, ssh


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_dirs()

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
    yield


app = FastAPI(title="VASP 计算项目管理系统 API", version="0.2.0", lifespan=lifespan)


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
app.include_router(projects.router, prefix="/api")
app.include_router(ssh.router, prefix="/api")
app.include_router(inspections.router, prefix="/api")


# 生产模式：同时托管前端 dist/（单端口部署）
dist_dir = PROJECT_ROOT / "dist"
if (dist_dir / "index.html").exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(dist_dir / "index.html")
